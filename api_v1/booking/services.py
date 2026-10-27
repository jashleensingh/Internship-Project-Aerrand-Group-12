"""Quote and booking logic (Jashleen).

Booking prices from the stored quote and never from the request. One errand row is written per stop; the whole
create (quote claim, rows, wallet debit) is one transaction, so a failure leaves nothing half-done.
"""
import hashlib
import json
import uuid
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from api_v1.common import ids
from api_v1.common.errors import ApiError
from api_v1.common.validation import Errs

from . import coverage, pricing
from .models import Errand, Quote
from .validation import validate_quote


def _c(x):
    return format(Decimal(str(x)).quantize(Decimal("0.0001")), "f")


def _fp(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def route_fingerprint(pickup, stops):
    return _fp({"k": "route", "p": [_c(pickup[0]), _c(pickup[1])],
                "s": [[_c(s["lat"]), _c(s["lng"]), sorted(s["parcels"].items())] for s in stops]})


def parcel_fingerprint(pickup, dropoff, size, declared_value):
    dv = format(pricing.q2(declared_value), "f") if declared_value else "0.00"
    return _fp({"k": "parcel", "p": [_c(pickup[0]), _c(pickup[1])], "d": [_c(dropoff[0]), _c(dropoff[1])],
                "t": pricing.size_tier(size), "v": dv})


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def create_quote(api_key, data):
    parsed = validate_quote(data)
    if parsed[0] == "route":
        _, pickup, stops = parsed
        result = pricing.route_quote((pickup[0], pickup[1]), stops)
        kind, fp = "route", route_fingerprint(pickup, stops)
    else:
        _, pickup, drop, size, priority, dv, when = parsed
        result = pricing.parcel_quote((pickup[0], pickup[1]), (drop[0], drop[1]), size, priority, dv, when)
        result.pop("_route_price"), result.pop("_km")
        kind, fp = "parcel", parcel_fingerprint(pickup, drop, size, dv)
    q = Quote(business=api_key.business, environment=api_key.environment, kind=kind, fingerprint=fp,
              amount_cents=result["amount_cents"],
              expires_at=timezone.now() + timedelta(seconds=settings.API_QUOTE_TTL_SECONDS))
    q.result = {"quote_id": q.id, "expires_at": iso(q.expires_at), **result}
    q.save()
    return q


def split_total(total, n):
    """Equal shares in cents; whatever cents are left over land on the last stop, so shares add up exactly."""
    cents = int(total * 100)
    base = cents // n
    shares = [base] * n
    shares[-1] += cents - base * n
    return [Decimal(c) / 100 for c in shares]


def _load_quote(api_key, v):
    q = Quote.objects.filter(pk=v["quote_id"], business=api_key.business, environment=api_key.environment).first()
    if q is None:
        raise ApiError(404, "quote_not_found", "No quote with that id. Request a new quote.")
    if q.expires_at <= timezone.now():
        raise ApiError(409, "quote_expired", "That quote has expired. Request a new quote.")
    if q.used_at is not None:
        raise ApiError(409, "quote_used", "That quote has already been booked. Request a new quote.")
    pk = v["pickup"]
    pickup = (pk["lat"], pk["lng"])
    if q.kind == "route":
        stops = [{"lat": d["lat"], "lng": d["lng"], "parcels": d["parcels"]} for d in v["dropoffs"]]
        fp = route_fingerprint(pickup, stops)
    else:
        if v["multi"] or v["parcel"] is None:
            errs = Errs()
            errs.add("quote_id", "This is a parcel quote: book it with a single dropoff and a parcel.")
            errs.raise_if_any()
        d = v["dropoffs"][0]
        fp = parcel_fingerprint(pickup, (d["lat"], d["lng"]), v["parcel"]["size"], v["parcel"]["declared_value"])
    if fp != q.fingerprint:
        raise ApiError(409, "quote_mismatch",
                       "The addresses or parcels differ from the quote. Request a new quote for this order.")
    return q


def create_errands(api_key, v):
    """Returns the list of Errand rows (one per stop)."""
    from api_v1.notices import hooks
    from api_v1.payments import services as pay

    business = api_key.business
    quote = _load_quote(api_key, v)
    r = quote.result
    if r.get("overVanCapacity"):
        raise ApiError(400, "route_over_capacity", "This route exceeds one cargo van. Split it into two routes.")
    coverage.check(v["pickup"], v["dropoffs"])

    if quote.kind == "route":
        route_price, hst, charge = (Decimal(str(r[k])) for k in ("routePrice", "hst", "chargeTotal"))
        km = Decimal(str(r["routeKm"]))
    else:
        route_price = Decimal(str(r["deliveryFee"])) + Decimal(str(r["guardFee"]))
        hst, charge, km = Decimal(str(r["hst"])), Decimal(str(r["totalDueAtBooking"])), Decimal(str(r["distanceKm"]))

    n = len(v["dropoffs"])
    shares = split_total(charge, n)
    batch_id = uuid.uuid4() if v["multi"] else None
    method = v["payment"]["method"]
    now = timezone.now()
    errands = []
    try:
        with transaction.atomic():
            if not Quote.objects.filter(pk=quote.pk, used_at__isnull=True).update(used_at=now):
                raise ApiError(409, "quote_used", "That quote has already been booked. Request a new quote.")
            for i, d in enumerate(v["dropoffs"]):
                loc = {"label": d["label"], "lat": d["lat"], "lng": d["lng"], "contact": d["contact"]}
                checkout = (f"https://pay.aerrand.com/checkout/{batch_id or ''}" if method == "checkout_link" else None)
                errands.append(Errand.objects.create(
                    business=business, environment=api_key.environment, quote=quote,
                    reference=d.get("reference", "") if v["multi"] else v["reference"],
                    batch_id=batch_id, batch_index=i if v["multi"] else None, batch_size=n if v["multi"] else None,
                    batch_reference=v["reference"] if v["multi"] else "",
                    delivery_code=ids.delivery_code(), vehicle_type=v["vehicle_type"] or r.get("recommendedVehicle", ""),
                    scheduled_at=v["scheduled_at"], delivery_note=v["delivery_note"], parcel=v["parcel"],
                    parcels=d.get("parcels", {}), metadata=v["metadata"], pickup=v["pickup"], dropoff=loc,
                    route_price=route_price, hst=hst, charge_total=charge, price=shares[i], distance_km=km,
                    payment={"method": method, "status": "unpaid", "checkout_url": checkout, "reference": None,
                             "email": v["payment"]["email"]},
                ))
            if method == "wallet":
                pay.pay_with_wallet(api_key, errands, charge)   # raises 402 -> whole booking rolls back
            hooks.on_created(errands)
    except IntegrityError:
        raise ApiError(409, "duplicate_reference",
                       "An errand with that reference already exists. References must be unique per account.")
    return [Errand.objects.get(pk=e.pk) for e in errands]
