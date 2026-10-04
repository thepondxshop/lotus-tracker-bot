"""C15: bounded request evidence; no keys, signatures, cookies or body content."""
import json
import re
import time
from urllib.parse import urlsplit, parse_qs

_LAST = {}


def record_response(*, domain, url, purpose, status, auth_mode,
                    signature_headers, response_headers, body, elapsed):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    products_count = None
    shape = "NON_JSON"
    try:
        data = json.loads(body)
        shape = "JSON_OTHER"
        if isinstance(data, dict) and isinstance(data.get("products"), list):
            shape = "PRODUCTS_JSON"
            products_count = len(data["products"])
        elif isinstance(data, dict) and isinstance(data.get("collections"), list):
            shape = "COLLECTIONS_JSON"
    except (ValueError, TypeError):
        pass
    inp = signature_headers.get("Signature-Input", "")
    created = re.search(r";created=(\d+)", inp)
    expires = re.search(r";expires=(\d+)", inp)
    now = int(time.time())
    def numeric_parameter(name):
        value = query.get(name, [""])[0]
        return int(value) if re.fullmatch(r"[0-9]{1,6}", value) else None
    evidence = {
        "auth_mode": auth_mode,
        "signature_attached": bool(inp and signature_headers.get("Signature")),
        "signature_age_seconds": now-int(created.group(1)) if created else None,
        "signature_remaining_seconds": int(expires.group(1))-now if expires else None,
        "page": numeric_parameter("page"), "limit": numeric_parameter("limit"),
        "response_kind": shape, "products_count": products_count,
        "elapsed_seconds": round(max(0, elapsed), 3),
    }
    # Emit all errors; sample steady success. Always show outcome/auth changes.
    state = (status, auth_mode, shape)
    previous, last_at = _LAST.get(domain, (None, 0.0))
    clock = time.monotonic()
    if status != 200 or previous != state or clock-last_at >= 300:
        safe_purpose = str(purpose).split(":", 1)[0][:60]
        print("SHOPIFY REQUEST EVIDENCE | " + json.dumps({
            "version": "C15", "store": domain, "purpose": safe_purpose,
            "http_status": status, **evidence,
        }, sort_keys=True), flush=True)
        _LAST[domain] = (state, clock)
    return evidence
