"""Request validation for POST /v1/quotes and POST /v1/errands (partner document, sections 1, 2, 3, 8, 9)."""
from datetime import datetime, timezone as dt_tz
from decimal import Decimal

from api_v1.common.validation import DROP_PREFS, TIERS, Errs, body_object, contact, lat_lng, number, text

from .pricing import size_tier

VEHICLES = ("scooter", "motorcycle", "car", "van", "truck")
METHODS = ("invoice", "checkout_link", "wallet")   # wallet is our addition for the prepaid-balance flow
# The price is the server's job. Any of these in a request is refused.
SERVER_OWNED = ("price", "route_price", "charge_total", "total", "amount_cents", "hst", "pricing",
                "status", "delivery_code", "errand_id", "batch_id", "payment_status")


def _coord_str(d):
    return format(d, "f")


def _parcels(errs, path, raw, required=True):
    if raw is None:
        if required:
            errs.add(path, "This field is required.")
        return {}
    if not isinstance(raw, dict) or not raw:
        errs.add(path, "Must be an object like {\"small\": 2, \"medium\": 1}.")
        return {}
    out = {}
    for t, c in raw.items():
        if t not in TIERS:
            errs.add(f"{path}.{t}", "Unknown size. Use small, medium, large or xl.")
        elif isinstance(c, bool) or not isinstance(c, int) or c < 0 or c > 500:
            errs.add(f"{path}.{t}", "Must be a whole number from 0 to 500.")
        elif c:
            out[t] = c
    if not out and not errs.d.get(path):
        errs.add(path, "At least one parcel is required.")
    return out


def _iso(errs, path, value):
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        errs.add(path, "Must be an ISO 8601 UTC time like 2026-09-23T15:00:00Z.")
        return None
    if dt.tzinfo is None:
        errs.add(path, "Include a timezone, e.g. a trailing Z.")
        return None
    return dt.astimezone(dt_tz.utc)


def _point(errs, path, raw):
    """Lat/lng only, as numbers or strings. Returns (lat, lng) Decimals or None."""
    if not isinstance(raw, dict):
        errs.add(path, "This field is required and must be an object with lat and lng.")
        return None
    la, ln = lat_lng(errs, path, raw.get("lat"), raw.get("lng"))
    return (la, ln) if la is not None and ln is not None else None


def validate_quote(data):
    """Returns ("route", pickup, stops) or ("parcel", pickup, dropoff, size, priority, declared_value, scheduled_at).
    Coordinates are Decimals; parcel counts are {tier: int}."""
    data = body_object(data)
    errs = Errs()
    pickup = _point(errs, "pickup", data.get("pickup"))
    if "stops" in data and "dropoff" in data:
        errs.add("stops", "Send either stops (route quote) or dropoff (parcel quote), not both.")
    if "stops" in data:
        stops_raw = data["stops"]
        stops = []
        if not isinstance(stops_raw, list) or not 1 <= len(stops_raw) <= 5:
            errs.add("stops", "Must be a list of 1 to 5 stops.")
        else:
            for i, s in enumerate(stops_raw):
                p = _point(errs, f"stops[{i}]", s)
                parcels = _parcels(errs, f"stops[{i}].parcels", s.get("parcels") if isinstance(s, dict) else None)
                if p:
                    stops.append({"lat": p[0], "lng": p[1], "parcels": parcels})
        errs.raise_if_any()
        return ("route", pickup, stops)
    if "dropoff" in data:
        drop = _point(errs, "dropoff", data["dropoff"])
        size = data.get("size")
        if size is None:
            errs.add("size", "This field is required.")
        else:
            try:
                if not isinstance(size, bool):
                    size_tier(size)
                    if isinstance(size, (int, float)) and size <= 0:
                        raise ValueError
                else:
                    raise ValueError
            except Exception:
                errs.add("size", "Use small, medium, large, xl, or a weight in pounds.")
        dv = data.get("declared_value")
        if dv is not None:
            dv = number(errs, "declared_value", dv, Decimal(0), Decimal(100000))
        pr = data.get("priority", False)
        if not isinstance(pr, bool):
            errs.add("priority", "Must be true or false.")
        when = _iso(errs, "scheduled_at", data.get("scheduled_at"))
        errs.raise_if_any()
        return ("parcel", pickup, drop, size, pr, dv, when)
    errs.add("stops", "Send stops (route quote) or dropoff with size (parcel quote).")
    errs.raise_if_any()


def validate_create(data):
    """Returns a clean dict. dropoffs is always a list (a single dropoff becomes a list of one)."""
    data = body_object(data)
    errs = Errs()
    for k in SERVER_OWNED:
        if k in data:
            errs.add(k, "Not accepted. The server sets this; send quote_id and the server prices the errand.")
    quote_id = text(errs, "quote_id", data.get("quote_id"), max_len=40)
    reference = text(errs, "reference", data.get("reference"), required=False) or ""
    veh = data.get("vehicle_type")
    if veh is not None and veh not in VEHICLES:
        errs.add("vehicle_type", "Must be one of: " + ", ".join(VEHICLES) + ".")
    when = _iso(errs, "scheduled_at", data.get("scheduled_at"))
    note = text(errs, "delivery_note", data.get("delivery_note"), max_len=500, required=False) or ""

    # pickup
    pk_raw = data.get("pickup")
    pickup = None
    if not isinstance(pk_raw, dict):
        errs.add("pickup", "This field is required and must be an object.")
    else:
        la, ln = lat_lng(errs, "pickup", pk_raw.get("lat"), pk_raw.get("lng"))
        label = text(errs, "pickup.label", pk_raw.get("label"))
        c = contact(errs, "pickup.contact", pk_raw.get("contact"), "pickup")
        if la is not None and ln is not None:
            pickup = {"label": label, "lat": _coord_str(la), "lng": _coord_str(ln), "contact": c}

    # drop-off(s)
    has_one, has_many = "dropoff" in data, "dropoffs" in data
    multi = has_many
    parcel = None
    dropoffs = []
    if has_one == has_many:
        errs.add("dropoff", "Send exactly one of dropoff (single delivery) or dropoffs (1 to 5 stops).")
    elif has_one:
        raw = data["dropoff"]
        # parcel (single delivery)
        pr = data.get("parcel")
        if pr is not None and not isinstance(pr, dict):
            errs.add("parcel", "Must be an object.")
        elif isinstance(pr, dict):
            size = pr.get("size")
            ok = size is not None and not isinstance(size, bool)
            if ok:
                try:
                    size_tier(size)
                    ok = not (isinstance(size, (int, float)) and size <= 0)
                except Exception:
                    ok = False
            if not ok:
                errs.add("parcel.size", "Use small, medium, large, xl, or a weight in pounds.")
            qty = pr.get("quantity", 1)
            if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 500:
                errs.add("parcel.quantity", "Must be a whole number from 1 to 500.")
                qty = 1
            dv = pr.get("declared_value")
            if dv is not None:
                dv = number(errs, "parcel.declared_value", dv, Decimal(0), Decimal(100000))
            desc = text(errs, "parcel.description", pr.get("description"), required=False)
            if ok:
                parcel = {"size": size, "quantity": qty, "description": desc,
                          "declared_value": float(dv) if dv is not None else None}
        else:
            errs.add("parcel", "This field is required for a single drop-off.")
        if not isinstance(raw, dict):
            errs.add("dropoff", "Must be an object.")
        else:
            d = _location(errs, "dropoff", raw)
            if d and parcel:
                d["parcels"] = {size_tier(parcel["size"]): parcel["quantity"]}
            if d:
                dropoffs.append(d)
    else:
        raw = data["dropoffs"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 5:
            errs.add("dropoffs", "Must be a list of 1 to 5 drop-offs.")
        else:
            for i, r in enumerate(raw):
                if not isinstance(r, dict):
                    errs.add(f"dropoffs[{i}]", "Must be an object.")
                    continue
                d = _location(errs, f"dropoffs[{i}]", r)
                parcels = _parcels(errs, f"dropoffs[{i}].parcels", r.get("parcels"))
                ref = text(errs, f"dropoffs[{i}].reference", r.get("reference"), required=False) or ""
                if d:
                    d["parcels"], d["reference"] = parcels, ref
                    dropoffs.append(d)

    # xl parcels are curbside: force meet_at_curb
    for d in dropoffs:
        if d.get("parcels", {}).get("xl"):
            d["contact"]["preference"] = "meet_at_curb"

    pay_raw = data.get("payment") or {}
    method, email = "invoice", None
    if not isinstance(pay_raw, dict):
        errs.add("payment", "Must be an object.")
    else:
        method = pay_raw.get("method", "invoice")
        if method not in METHODS:
            errs.add("payment.method", "Must be one of: " + ", ".join(METHODS) + ".")
        email = text(errs, "payment.email", pay_raw.get("email"), required=False)

    meta = data.get("metadata") or {}
    if not isinstance(meta, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in meta.items()):
        errs.add("metadata", "Must be an object with string keys and string values.")
        meta = {}
    elif len(meta) > 50 or any(len(k) > 100 or len(v) > 500 for k, v in meta.items()):
        errs.add("metadata", "At most 50 keys; keys up to 100 and values up to 500 characters.")

    errs.raise_if_any()
    return {"quote_id": quote_id, "reference": reference, "vehicle_type": veh or "", "scheduled_at": when,
            "delivery_note": note, "pickup": pickup, "dropoffs": dropoffs, "multi": multi, "parcel": parcel,
            "payment": {"method": method, "email": email}, "metadata": meta}


def _location(errs, path, raw):
    la, ln = lat_lng(errs, path, raw.get("lat"), raw.get("lng"))
    label = text(errs, f"{path}.label", raw.get("label"))
    c = contact(errs, f"{path}.contact", raw.get("contact"), "dropoff")
    if la is None or ln is None or label is None:
        return None
    return {"label": label, "lat": _coord_str(la), "lng": _coord_str(ln), "contact": c}
