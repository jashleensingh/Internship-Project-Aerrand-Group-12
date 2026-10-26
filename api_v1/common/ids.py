"""Id helpers. Named functions (not lambdas) so migrations can reference them."""
import secrets

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_id(prefix, n_hex=20):
    return prefix + secrets.token_hex(n_hex // 2)


def biz_id():
    return new_id("biz_")


def key_id():
    return new_id("key_")


def evt_id():
    return new_id("evt_")


def we_id():
    return new_id("we_")


def ntf_id():
    return new_id("ntf_")


def quote_id():
    # looks like qt_01J8S3M4K9YV7B2R (16 chars)
    return "qt_" + "".join(secrets.choice(CROCKFORD) for _ in range(16))


def delivery_id():
    """24-char hex, the record the Aerrander's app works from."""
    return secrets.token_hex(12)


def delivery_code():
    """6-char handover code the receiver gives the Aerrander."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
