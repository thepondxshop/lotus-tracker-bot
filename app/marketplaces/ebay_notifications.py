"""EBAY-NOTIFY3: verified receiver with durable pilot deletion queue.
Raw identifiers, notification bodies and credentials are never logged.
LIVE_REVIEWED retains keyed suppression hashes; the bot cleans up Discord.
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.marketplaces.ebay import EbayPreview, AccessFailure

PATH = '/ebay/account-deletion'
HEALTH_PATH = '/ebay/health'
MODE = 'PREVIEW_ONLY'
LIMIT = 16384

class ConfigurationError(ValueError):
    pass

class VerificationUnavailable(Exception):
    def __init__(self, phase='UNKNOWN', status=None, reason='UNAVAILABLE'):
        self.phase, self.status, self.reason = phase, status, reason
        super().__init__('eBay verification unavailable')


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError('Invalid JSON constant')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


@dataclass(frozen=True, repr=False)
class Settings:
    endpoint: str
    token: str
    mode: str = MODE

    @classmethod
    def from_env(cls):
        endpoint = os.getenv('EBAY_DELETION_ENDPOINT', '').strip()
        token = os.getenv('EBAY_DELETION_VERIFICATION_TOKEN', '').strip()
        mode = os.getenv('EBAY_DATA_RETENTION_MODE', MODE).strip()
        p = urlsplit(endpoint)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.query or p.fragment or p.path != PATH
                or p.hostname in {'localhost', '127.0.0.1', '::1'}):
            raise ConfigurationError('Set EBAY_DELETION_ENDPOINT to the exact public HTTPS callback URL')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,80}', token):
            raise ConfigurationError('Set a 32-80 character EBAY_DELETION_VERIFICATION_TOKEN')
        if mode not in {MODE, 'LIVE_REVIEWED'}:
            raise ConfigurationError('Saved eBay data requires an erasure integration; only PREVIEW_ONLY is implemented')
        if not (os.getenv('EBAY_PRODUCTION_CLIENT_ID', '').strip()
                and os.getenv('EBAY_PRODUCTION_CLIENT_SECRET', '').strip()):
            raise ConfigurationError('Production client ID and secret must also be set on this identity service')
        if (mode == 'LIVE_REVIEWED' or os.getenv('EBAY_DATABASE_URL') or os.getenv('EBAY_RETENTION_HMAC_KEY')) and (not os.getenv('EBAY_DATABASE_URL') or len(os.getenv('EBAY_RETENTION_HMAC_KEY','')) < 32):
            raise ConfigurationError('Shared retention database and key required')
        return cls(endpoint, token, mode)

    def challenge(self, code):
        if not isinstance(code, str) or not 1 <= len(code) <= 1024:
            raise ValueError('Invalid challenge')
        return hashlib.sha256((code + self.token + self.endpoint).encode('utf-8')).hexdigest()


def signature_header(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('Missing signature')
    data = strict_json(base64.b64decode(value, validate=True))
    if not isinstance(data, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', str(data.get('kid', ''))):
        raise ValueError('Invalid key identity')
    if str(data.get('alg', '')).upper() != 'ECDSA':
        raise ValueError('Unsupported signature algorithm')
    if str(data.get('digest', '')).upper() not in {'SHA1', 'SHA256'}:
        raise ValueError('Unsupported digest')
    signature = base64.b64decode(data.get('signature', ''), validate=True)
    if not signature or len(signature) > 256:
        raise ValueError('Invalid signature length')
    return data, signature


def verify_payload(raw, document, header, signature, record):
    """Use the trusted API key's digest, not an attacker-selected algorithm.

    eBay's Node SDK signs compact JSON. Accept exact wire bytes first and then
    equivalent compact JSON, preserving field order, for SDK compatibility.
    SHA1 here is eBay's published legacy signature format, not a new design.
    """
    algorithm = str(record.get('algorithm', '')).upper()
    digest = str(record.get('digest', '')).upper()
    if algorithm != 'ECDSA' or digest != str(header.get('digest', '')).upper():
        raise ValueError('Signature metadata mismatch')
    digest_class = {'SHA1': hashes.SHA1, 'SHA256': hashes.SHA256}.get(digest)
    if digest_class is None:
        raise ValueError('Unsupported key digest')
    pem = record.get('key', '')
    if not isinstance(pem, str) or len(pem) > 8192:
        raise ValueError('Invalid public key')
    pem = pem.replace('-----BEGIN PUBLIC KEY-----', '-----BEGIN PUBLIC KEY-----\n').replace('-----END PUBLIC KEY-----', '\n-----END PUBLIC KEY-----')
    key = serialization.load_pem_public_key(pem.encode('ascii'))
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise ValueError('Expected EC public key')
    compact = json.dumps(document, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    for candidate in dict.fromkeys((raw, compact)):
        try:
            key.verify(signature, candidate, ec.ECDSA(digest_class()))
            return
        except InvalidSignature:
            continue
    raise ValueError('Invalid signature')


def valid_deletion(document):
    if not isinstance(document, dict):
        return False
    metadata = document.get('metadata')
    notification = document.get('notification')
    if not isinstance(metadata, dict) or not isinstance(notification, dict):
        return False
    if metadata.get('topic') != 'MARKETPLACE_ACCOUNT_DELETION' or metadata.get('schemaVersion') != '1.0':
        return False
    data = notification.get('data')
    if not isinstance(data, dict) or not isinstance(notification.get('notificationId'), str):
        return False
    return any(isinstance(data.get(k), str) and 0 < len(data[k]) <= 4096
               for k in ('userId', 'username', 'eiasToken'))


class PublicKeys:
    def __init__(self):
        self.session = None
        self.auth = EbayPreview('production')
        self.cache = {}
        self.lock = asyncio.Lock()
        self.next_fetch = 0.0

    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6),
            trust_env=False, cookie_jar=aiohttp.DummyCookieJar())

    async def close(self):
        if self.session:
            await self.session.close()

    async def get(self, kid):
        async with self.lock:
            now = time.monotonic()
            cached = self.cache.get(kid)
            if cached and now < cached[0]:
                return cached[1]
            # Avoid unauthenticated requests exhausting eBay's key-fetch quota.
            if now < self.next_fetch or self.session is None:
                raise VerificationUnavailable('LOCAL', reason='KEY_FETCH_COOLDOWN_OR_NOT_STARTED')
            self.next_fetch = now + 2
            try:
                token = await self.auth.token(self.session)
                url = 'https://api.ebay.com/commerce/notification/v1/public_key/' + kid
                async with self.session.get(url, headers={'Authorization': 'Bearer ' + token},
                        allow_redirects=False) as response:
                    if response.status != 200:
                        self.next_fetch = now + 30
                        raise VerificationUnavailable('PUBLIC_KEY', response.status, 'HTTP_ERROR')
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(4096):
                        body.extend(chunk)
                        if len(body) > LIMIT:
                            raise VerificationUnavailable('PUBLIC_KEY', response.status, 'RESPONSE_TOO_LARGE')
                    record = strict_json(body)
                    if not isinstance(record, dict) or not all(k in record for k in ('key', 'algorithm', 'digest')):
                        raise VerificationUnavailable('PUBLIC_KEY', response.status, 'INVALID_KEY_RESPONSE')
            except AccessFailure as error:
                self.next_fetch = now + 30
                raise VerificationUnavailable('AUTH', error.result.get('http_status'),
                    error.result.get('state', 'AUTH_FAILED')) from None
            except VerificationUnavailable:
                self.next_fetch = now + 30
                raise
            except asyncio.TimeoutError:
                self.next_fetch = now + 30
                raise VerificationUnavailable('NETWORK', reason='TIMEOUT') from None
            except Exception:
                self.next_fetch = now + 30
                raise VerificationUnavailable('NETWORK_OR_RESPONSE', reason='REQUEST_FAILED') from None
            self.cache = {k: v for k, v in self.cache.items() if v[0] > now}
            if len(self.cache) >= 32:
                self.cache.pop(next(iter(self.cache)))
            self.cache[kid] = (now + 3600, record)
            return record


def install(app, settings=None, key_provider=None):
    """Always expose health; enable callback only with valid configuration."""
    problem = None
    if settings is None:
        try:
            settings = Settings.from_env()
        except (ValueError, TypeError):
            problem = 'CONFIGURATION_REQUIRED'
    provider = key_provider or PublicKeys()
    retention = None
    if settings is not None and (settings.mode == 'LIVE_REVIEWED' or os.getenv('EBAY_DATABASE_URL')):
        from app.marketplaces.ebay_live_store import Store
        retention = Store()
    if settings is not None:
        async def lifecycle(_app):
            await provider.start()
            heartbeat_task = None
            async def heartbeat():
                while True:
                    try:
                        if retention.pool is None:
                            await retention.start()
                        await retention.heartbeat(settings.mode)
                    except Exception:
                        print('LOTUS EBAY RETENTION | State=HEARTBEAT_FAILED', flush=True)
                    await asyncio.sleep(30)
            try:
                if retention:
                    # Keep identity signing/directory routes available if DB is down.
                    heartbeat_task = asyncio.create_task(heartbeat())
                yield
            finally:
                if heartbeat_task:
                    heartbeat_task.cancel()
                    try: await heartbeat_task
                    except asyncio.CancelledError: pass
                if retention:
                    try:
                        if retention.pool: await retention.heartbeat('STOPPED')
                    finally: await retention.close()
                await provider.close()
        app.cleanup_ctx.append(lifecycle)
    print('LOTUS EBAY NOTIFICATIONS | State=' + (('READY_'+settings.mode) if settings else problem), flush=True)

    async def health(request):
        return web.json_response({'version': 'EBAY-NOTIFY3', 'configured': settings is not None,
            'mode': settings.mode if settings else MODE, 'live_marketplace_alerts': False,
            'signature_validation': 'ECDSA_EBAY_PUBLIC_KEY',
            'production_access_verified': False}, status=200 if settings else 503)

    async def challenge(request):
        if settings is None:
            return web.json_response({'error': 'Configuration required'}, status=503)
        try:
            values = request.query.getall('challenge_code', [])
            if len(values) != 1:
                raise ValueError()
            response = settings.challenge(values[0])
        except ValueError:
            return web.json_response({'error': 'One challenge_code is required'}, status=400)
        print('LOTUS EBAY CHALLENGE | Result=RESPONDED', flush=True)
        return web.json_response({'challengeResponse': response}, headers={'Cache-Control': 'no-store'})

    async def notification(request):
        if settings is None:
            return web.Response(status=503)
        try:
            header, signature = signature_header(request.headers.get('X-EBAY-SIGNATURE'))
            raw = await request.read()
            if len(raw) > LIMIT:
                return web.Response(status=413)
            document = strict_json(raw)
            if not valid_deletion(document):
                return web.Response(status=400)
        except web.HTTPRequestEntityTooLarge:
            return web.Response(status=413)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return web.Response(status=412)
        try:
            record = await asyncio.wait_for(provider.get(header['kid']), timeout=8)
            verify_payload(raw, document, header, signature, record)
        except (VerificationUnavailable, asyncio.TimeoutError) as error:
            # Only controlled diagnostic fields: never exceptions, bodies or tokens.
            detail = {'phase': getattr(error, 'phase', 'TOTAL_TIMEOUT'),
                      'http_status': getattr(error, 'status', None),
                      'reason': getattr(error, 'reason', 'TIMEOUT')}
            print('LOTUS EBAY NOTIFICATION | Result=KEY_LOOKUP_UNAVAILABLE | ' + json.dumps(detail), flush=True)
            return web.Response(status=503, headers={'Retry-After': '30'})
        except (ValueError, TypeError, UnicodeError, InvalidSignature):
            return web.Response(status=412)
        if retention is not None:
            try:
                await asyncio.wait_for(retention.receive_deletion(document['notification']['data']), timeout=6)
            except Exception:
                print('LOTUS EBAY NOTIFICATION | Result=DELETION_QUEUE_UNAVAILABLE', flush=True)
                return web.Response(status=503, headers={'Retry-After':'30'})
            print('LOTUS EBAY NOTIFICATION | Result=VERIFIED_DELETION_QUEUED | Mode='+settings.mode, flush=True)
            return web.Response(status=202)
        # MARKET2 performs no persistence and sends no marketplace Discord posts.
        # Discard authenticated identifiers without retaining a receipt containing
        # user data. Repeated notifications are naturally idempotent. A future
        # saved-data mode must replace this with real indexed erasure before ACK.
        if settings.mode != MODE:
            return web.Response(status=503)
        print('LOTUS EBAY NOTIFICATION | Result=VERIFIED_NO_RETAINED_USER_RECORDS | Mode=PREVIEW_ONLY', flush=True)
        return web.Response(status=204)

    app.router.add_get(HEALTH_PATH, health)
    app.router.add_get(PATH, challenge)
    app.router.add_post(PATH, notification)

