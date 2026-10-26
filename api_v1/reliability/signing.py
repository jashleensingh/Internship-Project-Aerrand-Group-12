"""Aerrand-Signature: t=<unix>,v1=<hex hmac_sha256(secret, t + "." + raw_body)>

Receivers verify with the RAW request bytes (not re-serialised JSON) and reject old timestamps."""
import hashlib
import hmac
import time


def sign_payload(secret, body, timestamp=None):
    t = int(timestamp if timestamp is not None else time.time())
    mac = hmac.new(secret.encode(), str(t).encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify_signature(secret, body, header, tolerance=300, now=None):
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
        given = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), str(t).encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given)
