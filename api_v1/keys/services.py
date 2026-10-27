import hashlib
import hmac
import secrets

from django.conf import settings
from django.utils import timezone

from api_v1.common.errors import ApiError
from api_v1.common.validation import Errs, text

from .models import SCOPES, ApiKey

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
PREFIX_LEN = 15


def generate_key(environment):
    """ak_live_<40 base62>  or  ak_test_<40 base62>  (the format used in the partner document)."""
    return f"ak_{environment}_" + "".join(secrets.choice(BASE62) for _ in range(40))


def hash_key(raw):
    return hmac.new(settings.API_KEY_HASH_PEPPER.encode(), raw.encode(), hashlib.sha256).hexdigest()


def issue(business, name, environment="live", scopes=None):
    """Create a key without the approval check (used by tests/seed). Returns (ApiKey, plain_key)."""
    raw = generate_key(environment)
    obj = ApiKey.objects.create(
        business=business, name=name, environment=environment, scopes=list(scopes or SCOPES),
        key_prefix=raw[:PREFIX_LEN], key_hash=hash_key(raw),
    )
    return obj, raw


def create_key(business, data):
    """Dashboard path: only approved businesses get keys."""
    if not business.approved:
        raise ApiError(412, "business_not_approved", "Your account is still under review. Keys unlock after approval.")
    errs = Errs()
    name = text(errs, "name", data.get("name"), max_len=120)
    env = data.get("environment", "live")
    if env not in ("live", "test"):
        errs.add("environment", "Must be 'live' or 'test'.")
    scopes = data.get("scopes") or SCOPES
    if not isinstance(scopes, list) or any(s not in SCOPES for s in scopes) or not scopes:
        errs.add("scopes", "Must be a non-empty list from: " + ", ".join(SCOPES) + ".")
    errs.raise_if_any()
    return issue(business, name, env, scopes)


def revoke_key(business, key_id):
    updated = ApiKey.objects.filter(pk=key_id, business=business, status="active").update(
        status="revoked", revoked_at=timezone.now())
    if not updated:
        # same answer whether it never existed, belongs to someone else, or is already revoked
        raise ApiError(404, "key_not_found", "No active key with that id.")


def lookup(raw):
    return ApiKey.objects.select_related("business").filter(key_hash=hash_key(raw)).first()
