"""ONBOARD1: report signing readiness without requests or credential output."""
def signing_status(domain):
    try:
        from lotus_bot_auth import allowed_stores, operator_request_headers
        if domain == 'thepondx.com':
            return {'state': 'MERCHANT_PATH', 'note': 'Uses its separate merchant signing configuration.'}
        if domain not in allowed_stores():
            return {'state': 'NOT_ALLOWLISTED', 'note': 'Append this domain to LOTUS_BOT_AUTH_STORES on the tracker service; preserve existing domains, then deploy.'}
        headers = operator_request_headers('https://' + domain + '/products.json', domain)
        if headers.get('Signature') and headers.get('Signature-Input'):
            return {'state': 'HEADERS_READY', 'note': 'Signing configured; live access and delivery are not verified.'}
        return {'state': 'SIGNING_DISABLED', 'note': 'Check LOTUS_BOT_AUTH_ENABLED on the tracker service.'}
    except Exception:
        return {'state': 'CONFIG_ERROR', 'note': 'Check signing configuration; no credential values are shown.'}


def onboarding_note(domain):
    result = signing_status(domain)
    return '\nSigning: `' + result['state'] + '`\n' + result['note']
