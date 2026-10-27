"""Small validation helpers shared by booking and instructions. Errors are collected, then raised once as
400 validation_failed with details = {field: [messages]} (partner document, section 11)."""
import math
import re
from decimal import Decimal, InvalidOperation

from .errors import ApiError

TIERS = ("small", "medium", "large", "xl")
DROP_PREFS = ("leave_at_door", "meet_at_door", "meet_at_curb")
PHONE_RE = re.compile(r"^\+?[0-9 ()\-.]{7,32}$")


class Errs:
    def __init__(self):
        self.d = {}

    def add(self, field, msg):
        self.d.setdefault(field, []).append(msg)

    def __bool__(self):
        return bool(self.d)

    def raise_if_any(self):
        if self.d:
            raise ApiError(400, "validation_failed", "The request has invalid fields.", details=self.d)


def text(errs, path, value, max_len=255, required=True):
    if value is None or value == "":
        if required:
            errs.add(path, "This field is required.")
        return None
    if not isinstance(value, str):
        errs.add(path, "Must be a string.")
        return None
    value = value.strip()
    if required and not value:
        errs.add(path, "This field is required.")
        return None
    if len(value) > max_len:
        errs.add(path, f"Must be at most {max_len} characters.")
        return None
    return value


def number(errs, path, value, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        errs.add(path, "Must be a number.")
        return None
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        errs.add(path, "Must be a number.")
        return None
    if not d.is_finite() or (isinstance(value, float) and not math.isfinite(value)):
        errs.add(path, "Must be a finite number.")
        return None
    if lo is not None and d < lo:
        errs.add(path, f"Must be at least {lo}.")
        return None
    if hi is not None and d > hi:
        errs.add(path, f"Must be at most {hi}.")
        return None
    return d


def lat_lng(errs, path, lat, lng):
    """Real geocoded coordinates only: (0, 0), blank and non-numeric values are rejected."""
    la = number(errs, f"{path}.lat", lat, Decimal(-90), Decimal(90))
    ln = number(errs, f"{path}.lng", lng, Decimal(-180), Decimal(180))
    if la is not None and ln is not None and la == 0 and ln == 0:
        errs.add(path, "Coordinates (0, 0) are not a real location.")
        return None, None
    return la, ln


def contact(errs, path, raw, kind, require_all=True):
    """kind = 'pickup' | 'dropoff'. Returns the cleaned keys that were present."""
    if not isinstance(raw, dict):
        errs.add(path, "This field is required and must be an object." if require_all else "Must be an object.")
        return {}
    allowed = {"name", "phone_number", "instructions", "preference"} | ({"email"} if kind == "pickup" else set())
    for k in raw:
        if k not in allowed:
            errs.add(f"{path}.{k}", "Unknown field.")
    out = {}
    if require_all or "name" in raw:
        out["name"] = text(errs, f"{path}.name", raw.get("name"))
    if require_all or "phone_number" in raw:
        ph = text(errs, f"{path}.phone_number", raw.get("phone_number"))
        if ph is not None and not PHONE_RE.match(ph):
            errs.add(f"{path}.phone_number", "Use a phone number like +15195550188.")
            ph = None
        out["phone_number"] = ph
    if "instructions" in raw:
        out["instructions"] = text(errs, f"{path}.instructions", raw.get("instructions"), required=False)
    if kind == "pickup" and "email" in raw:
        em = text(errs, f"{path}.email", raw.get("email"), required=False)
        if em is not None and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", em):
            errs.add(f"{path}.email", "Not a valid email address.")
            em = None
        out["email"] = em
    if require_all or "preference" in raw:
        pref = raw.get("preference")
        valid = ("pickup",) if kind == "pickup" else DROP_PREFS
        if pref not in valid:
            errs.add(f"{path}.preference", "Must be one of: " + ", ".join(valid) + ".")
            pref = None
        out["preference"] = pref
    return {k: v for k, v in out.items() if not (v is None and k in ("name", "phone_number", "preference"))}


def body_object(data):
    if not isinstance(data, dict):
        raise ApiError(400, "validation_failed", "Send a JSON object.", details={"body": ["Must be a JSON object."]})
    return data
