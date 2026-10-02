"""Lotus operator Web Bot Auth. No Discord or database imports.

Commands: serve | check | probe STORE | keygen
Signing in the monitor is OFF unless LOTUS_BOT_AUTH_ENABLED=true.
Only explicitly listed LOTUS_BOT_AUTH_STORES are signed.
Implements the structured-string Signature-Agent profile documented by
Shopify's linked Cloudflare guide, with Ed25519 HTTP Message Signatures.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

DIRECTORY_PATH = '/.well-known/http-message-signatures-directory'
MEDIA_TYPE = 'application/http-message-signatures-directory+json'
VERSION = '1.0.6-C14'


class BotAuthConfigError(ValueError):
    """Only fixed, non-secret messages may be passed to this exception."""


def b64url(data):
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def checked_host(value):
    value = value.strip().lower()
    labels = value.split('.')
    if (len(value) > 253 or len(labels) < 2 or value.endswith('.internal')
            or all(label.isdigit() for label in labels)
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels)):
        raise BotAuthConfigError('Expected a public DNS hostname without a scheme, path, or port')
    return value


def checked_origin(value):
    try:
        parsed = urlsplit(value.strip())
        if (parsed.scheme != 'https' or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError
        return 'https://' + checked_host(parsed.hostname)
    except ValueError:
        raise BotAuthConfigError('LOTUS_BOT_AUTH_ORIGIN must be an HTTPS origin with no path or port') from None


def configured_origin():
    origin = os.environ.get('LOTUS_BOT_AUTH_ORIGIN', '').strip()
    if not origin:
        public_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').strip()
        if public_domain:
            origin = 'https://' + checked_host(public_domain)
    if not origin:
        raise BotAuthConfigError('Set LOTUS_BOT_AUTH_ORIGIN or generate the identity service public domain')
    return checked_origin(origin)


def allowed_stores():
    return {checked_host(item) for item in os.environ.get('LOTUS_BOT_AUTH_STORES', '').split(',') if item.strip()}


@dataclass(repr=False)
class Signer:
    origin: str
    private_key: object = field(repr=False)
    public_jwk: dict
    key_id: str

    @classmethod
    def from_env(cls):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        origin = configured_origin()
        try:
            raw = base64.b64decode(os.environ.get('LOTUS_BOT_AUTH_PRIVATE_KEY', '').strip(), validate=True)
            if len(raw) != 32:
                raise ValueError
            key = Ed25519PrivateKey.from_private_bytes(raw)
        except (ValueError, TypeError):
            raise BotAuthConfigError('LOTUS_BOT_AUTH_PRIVATE_KEY must contain one base64-encoded 32-byte key') from None
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        jwk = {'crv': 'Ed25519', 'kty': 'OKP', 'x': b64url(public)}
        canonical = json.dumps(jwk, sort_keys=True, separators=(',', ':')).encode('ascii')
        return cls(origin, key, jwk, b64url(hashlib.sha256(canonical).digest()))

    def sign(self, components, tag, lifetime, *, now=None, nonce=None):
        now = int(time.time()) if now is None else int(now)
        nonce = secrets.token_urlsafe(18) if nonce is None else nonce
        component_list = '(' + ' '.join(name for name, _ in components) + ')'
        params = (component_list + f';created={now};expires={now + lifetime}'
                  + f';keyid="{self.key_id}";alg="ed25519";nonce="{nonce}";tag="{tag}"')
        base = '\n'.join(f'{name}: {value}' for name, value in components)
        base += '\n"@signature-params": ' + params
        signature = base64.b64encode(self.private_key.sign(base.encode('ascii'))).decode('ascii')
        return {'Signature-Input': 'lotus=' + params, 'Signature': 'lotus=:' + signature + ':'}

    def request_headers(self, host):
        host = checked_host(host)
        agent = json.dumps(self.origin)
        headers = self.sign([('"@authority"', host), ('"signature-agent"', agent)], 'web-bot-auth', 60)
        headers['Signature-Agent'] = agent
        headers['User-Agent'] = f'LotusTrackerBot/1.0 (+{self.origin})'
        return headers

    def directory_response(self):
        # Publish only the public key. No private JWK member (d).
        body = json.dumps({'keys': [dict(self.public_jwk, kid=self.key_id)]}, separators=(',', ':')).encode('ascii')
        digest = 'sha-256=:' + base64.b64encode(hashlib.sha256(body).digest()).decode('ascii') + ':'
        host = urlsplit(self.origin).netloc
        headers = self.sign([
            ('"@authority";req', host),
            ('"content-type"', MEDIA_TYPE),
            ('"content-digest"', digest),
        ], 'http-message-signatures-directory', 300)
        headers.update({'Content-Type': MEDIA_TYPE, 'Content-Digest': digest,
                        'Cache-Control': 'public, max-age=60'})
        return body, headers


_CACHED_SIGNER = None


def operator_request_headers(url, store_domain):
    """Sign only explicit stores and only their original HTTPS authority."""
    global _CACHED_SIGNER
    if os.environ.get('LOTUS_BOT_AUTH_ENABLED', '').strip().lower() != 'true':
        return {}
    # ThePondX always retains the independent merchant signature path.
    if store_domain == 'thepondx.com':
        return {}
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != store_domain
                or parsed.netloc != store_domain or parsed.username is not None
                or parsed.password is not None):
            return {}
        if store_domain not in allowed_stores():
            return {}
    except ValueError:
        raise BotAuthConfigError('Invalid operator signing store configuration') from None
    if _CACHED_SIGNER is None:
        _CACHED_SIGNER = Signer.from_env()
    # Fresh timestamp and nonce for EVERY HTTP attempt, including 5xx retries.
    return _CACHED_SIGNER.request_headers(store_domain)


def create_app():
    from aiohttp import web
    app = web.Application(client_max_size=4096)
    try:
        signer = Signer.from_env()
    except BotAuthConfigError as error:
        signer = None
        print('LOTUS IDENTITY SETUP | ' + str(error), flush=True)

    async def health(request):
        return web.json_response({'service': 'lotus-bot-identity', 'ready': signer is not None})

    async def directory(request):
        if signer is None:
            return web.json_response({'error': 'Identity configuration incomplete'}, status=503)
        # Never sign an attacker-controlled host or trust forwarded host input.
        if request.headers.get('Host', '').lower() != urlsplit(signer.origin).netloc:
            return web.Response(status=421, text='Unexpected identity host')
        body, headers = signer.directory_response()
        return web.Response(body=body, headers=headers)

    async def profile(request):
        return web.json_response({
            'name': 'Lotus Tracker Bot', 'operator': 'ThePondX',
            'website': 'https://thepondx.com/',
            'purpose': 'Public product availability and price monitoring for collectible alerts.',
            'key_directory': DIRECTORY_PATH,
        })

    app.router.add_get('/health', health)
    app.router.add_get(DIRECTORY_PATH, directory)
    app.router.add_get('/', profile)
    return app


async def check_directory(signer, session):
    """Fetch only our public directory and verify its signed response."""
    from cryptography.exceptions import InvalidSignature
    result = {'origin': signer.origin, 'key_id': signer.key_id}
    async with session.get(signer.origin + DIRECTORY_PATH, allow_redirects=False) as response:
        result['http_status'] = response.status
        body = bytearray()
        async for chunk in response.content.iter_chunked(4096):
            body.extend(chunk)
            if len(body) > 16384:
                raise BotAuthConfigError('Public identity directory exceeds expected size')
        if response.status != 200:
            raise BotAuthConfigError('Public identity directory did not return HTTP 200')
        expected_digest = 'sha-256=:' + base64.b64encode(hashlib.sha256(body).digest()).decode('ascii') + ':'
        if response.headers.get('Content-Type') != MEDIA_TYPE or response.headers.get('Content-Digest') != expected_digest:
            raise BotAuthConfigError('Public directory content type or digest mismatch')
        data = json.loads(body)
        if data != {'keys': [dict(signer.public_jwk, kid=signer.key_id)]}:
            raise BotAuthConfigError('Public directory key does not match this service signing key')
        value = response.headers.get('Signature-Input', '')
        prefix = 'lotus=("@authority";req "content-type" "content-digest")'
        if not value.startswith(prefix):
            raise BotAuthConfigError('Unexpected public directory signature components')
        created = re.search(r';created=(\d+)', value)
        expires = re.search(r';expires=(\d+)', value)
        now = time.time()
        if (not created or not expires or int(created.group(1)) > now + 5
                or int(expires.group(1)) <= now
                or f';keyid="{signer.key_id}"' not in value
                or ';tag="http-message-signatures-directory"' not in value):
            raise BotAuthConfigError('Public directory signature is stale or mismatched')
        base = (f'"@authority";req: {urlsplit(signer.origin).netloc}\n'
                + f'"content-type": {MEDIA_TYPE}\n'
                + f'"content-digest": {expected_digest}\n'
                + '"@signature-params": ' + value.split('=', 1)[1])
        raw_signature = response.headers.get('Signature', '')
        match = re.fullmatch(r'lotus=:([A-Za-z0-9+/]+={0,2}):', raw_signature)
        if not match:
            raise BotAuthConfigError('Public directory signature format is invalid')
        try:
            signer.private_key.public_key().verify(base64.b64decode(match.group(1), validate=True), base.encode('ascii'))
        except (InvalidSignature, ValueError):
            raise BotAuthConfigError('Public directory signature verification failed') from None
    result['directory_verified'] = True
    return result


async def diagnostic(store=None):
    import aiohttp
    signer = Signer.from_env()
    if store is not None:
        store = checked_host(store)
        if store == 'thepondx.com' or store not in allowed_stores():
            raise BotAuthConfigError('Probe store must be explicitly listed in LOTUS_BOT_AUTH_STORES; ThePondX is excluded')
    timeout = aiohttp.ClientTimeout(total=25, connect=10)
    async with aiohttp.ClientSession(timeout=timeout, cookie_jar=aiohttp.DummyCookieJar(), trust_env=False) as session:
        print('LOTUS DIRECTORY CHECK | ' + json.dumps(await check_directory(signer, session)), flush=True)
        if store is None:
            return
        # Exactly one store request, no redirects or automatic retries.
        url = f'https://{store}/products.json?limit=1&page=1'
        headers = signer.request_headers(store)
        headers['Accept'] = 'application/json'
        async with session.get(url, headers=headers, allow_redirects=False) as response:
            result = {'at_utc': datetime.now(timezone.utc).isoformat(), 'store': store,
                      'url': url, 'http_status': response.status, 'key_id': signer.key_id,
                      'signature_headers_attached': True, 'valid_products_response': False,
                      'automatic_retries': 0}
            result['response_headers'] = {key: re.sub(r'[\r\n]', ' ', response.headers[key])[:200]
                for key in ('X-Request-ID', 'CF-Ray', 'Retry-After', 'Content-Type') if key in response.headers}
            body = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                body.extend(chunk)
                if len(body) > 262144:
                    break
            if response.status == 200 and len(body) <= 262144:
                try:
                    payload = json.loads(body)
                    if isinstance(payload, dict) and isinstance(payload.get('products'), list):
                        result['valid_products_response'] = True
                        result['products_returned'] = len(payload['products'])
                except (ValueError, UnicodeError):
                    pass
            # Do not print request signatures, private keys, cookies or bodies.
            print('LOTUS OPERATOR TEST | ' + json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['serve', 'check', 'probe', 'keygen'])
    parser.add_argument('store', nargs='?')
    args = parser.parse_args()
    if args.command == 'keygen':
        # Run interactively on your own computer, never as a service start command.
        print(base64.b64encode(secrets.token_bytes(32)).decode('ascii'))
        return
    try:
        if args.command == 'serve':
            from aiohttp import web
            print('LOTUS IDENTITY SERVICE | Version=' + VERSION, flush=True)
            web.run_app(create_app(), host='0.0.0.0', port=int(os.environ.get('PORT', '8080')), access_log=None)
        else:
            if args.command == 'probe' and not args.store:
                parser.error('probe requires a store hostname')
            asyncio.run(diagnostic(args.store if args.command == 'probe' else None))
    except BotAuthConfigError as error:
        print('LOTUS AUTH CONFIG ERROR | ' + str(error), flush=True)
        sys.exit(1)
    except Exception as error:
        # Network/client exceptions can carry request headers; print only type.
        print('LOTUS AUTH ERROR | ' + type(error).__name__, flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
