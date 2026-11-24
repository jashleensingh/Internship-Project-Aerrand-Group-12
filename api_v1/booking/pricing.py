"""Stand-in pricing engines with the same shapes as the partner document (section 1). The numbers (rates, allowances)
are placeholders: in Aerrand's repo these two functions call the existing route engine (order/business_pricing.py)
and parcel engine, and everything else in this module stays the same.

Route engine  : follows "Aerrand Business Pricing Engine Specification v2.0": trip base + drop bases, distance beyond
                3 free km, per-parcel size add-ons (L $18, XL $35), handling past 4 parcels per stop, then HST.
                No time-based part and no van surcharge. 2+ Large/XL parcels on a route need a cargo vehicle.
                Every number can be overridden through settings.AERRAND_PRICING (see route_config()).
Parcel engine : adds rush / night surcharges, optional priority multiplier, and Aerrand Guard when a declared
                value is present (the item value is held in escrow, in the total but not taxed).
"""
from datetime import datetime, timezone as dt_tz
from decimal import ROUND_HALF_UP, Decimal as D
from zoneinfo import ZoneInfo

from api_v1.common.geo import haversine_km

CURRENCY = "CAD"
HST_RATE = D("0.13")   # parcel engine
TIERS = ("small", "medium", "large", "xl")
UNITS = {"small": D("0.5"), "medium": D("1"), "large": D("2"), "xl": D("4")}
SIZE_ADDON = {"small": D("0"), "medium": D("2.00"), "large": D("5.00"), "xl": D("9.00")}   # parcel (customer) engine
ROAD_FACTOR = D("1.3")   # stand-in: straight line x 1.3 until a routing provider gives the optimized driven km
VAN_CAPACITY_UNITS = D("24")
ROUTE_DEFAULTS = {       # spec sections 9 and 10 (launch values)
    "trip_base": "8.00", "drop_base": "3.50", "free_km": "3", "per_km_rate": "1.25",
    "size_addon": {"small": "0", "medium": "2.00", "large": "18.00", "xl": "35.00"},
    "bulky_sizes": ["large", "xl"], "bulky_vehicle_threshold": 2,
    "included_parcels": 4, "handling_fee": "0.50", "hst_rate": "0.13",
    "aerrander_split_rate": "0.67", "payout_per_stop": "3.25", "payout_per_km": "0.80",
    "hold_buffer_pct": "0.10",   # spec: "per existing payments configuration" - confirm the real value
}
PARCEL_BASE = D("6.00")
FREE_KM, PER_KM = D("2.0"), D("1.10")   # parcel engine only; the route engine uses route_config()
GUARD_RATE = D("0.03")
RUSH, NIGHT, PRIORITY_MULT = D("1.00"), D("3.00"), D("1.5")
LOCAL_TZ = ZoneInfo("America/Toronto")


def q2(x):
    return D(x).quantize(D("0.01"), ROUND_HALF_UP)


def f(x):
    return float(q2(x))


def road_km(points):
    total = sum(haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:]))
    return q2(D(str(total)) * ROAD_FACTOR)


def distance_charge(km):
    return q2(max(D("0"), km - FREE_KM) * PER_KM)


def size_tier(size):
    """A tier name, or a weight in pounds."""
    if isinstance(size, str) and size.strip().lower() in TIERS:
        return size.strip().lower()
    lbs = D(str(size))
    return "small" if lbs <= 5 else "medium" if lbs <= 20 else "large" if lbs <= 50 else "xl"


def recommended_vehicle(units):
    return "scooter" if units <= D("1.5") else "motorcycle" if units <= 6 else "car" if units <= 10 else "van"


def route_config():
    """Spec defaults, overridden by settings.AERRAND_PRICING (a dict with any of the same keys)."""
    from django.conf import settings
    cfg = {**ROUTE_DEFAULTS, **getattr(settings, "AERRAND_PRICING", {})}
    cfg["size_addon"] = {**ROUTE_DEFAULTS["size_addon"], **(cfg["size_addon"] or {})}
    num = ("trip_base", "drop_base", "free_km", "per_km_rate", "handling_fee", "hst_rate", "aerrander_split_rate",
           "payout_per_stop", "payout_per_km", "hold_buffer_pct")
    out = {k: D(str(cfg[k])) for k in num}
    out["size_addon"] = {k: D(str(v)) for k, v in cfg["size_addon"].items()}
    out["bulky_sizes"] = tuple(cfg["bulky_sizes"])
    out["bulky_vehicle_threshold"] = int(cfg["bulky_vehicle_threshold"])
    out["included_parcels"] = int(cfg["included_parcels"])
    return out


def aerrander_payout(route_price, stop_count, route_km, cfg=None):
    """Spec section 6: the higher of 67% of the pre-tax price or $3.25 x stops + $0.80 x km. Tips are never included."""
    cfg = cfg or route_config()
    floor = cfg["payout_per_stop"] * stop_count + cfg["payout_per_km"] * D(str(route_km))
    return q2(max(D(str(route_price)) * cfg["aerrander_split_rate"], floor))


def hold_amount(charge_total, cfg=None):
    """Spec section 7: card authorization = charge_total x (1 + buffer)."""
    cfg = cfg or route_config()
    return q2(D(str(charge_total)) * (1 + cfg["hold_buffer_pct"]))


def route_quote(pickup, stops):
    """pickup = (lat, lng); stops = [{"lat","lng","parcels": {tier: count}}]. Returns the response body (without id/expiry).
    Route price = drop bases + distance + size add-ons + handling (spec section 4). HST on top."""
    cfg = route_config()
    n = len(stops)
    km = road_km([pickup] + [(s["lat"], s["lng"]) for s in stops])
    base = cfg["trip_base"] + cfg["drop_base"] * (n - 1)
    dist = q2(max(D("0"), km - cfg["free_km"]) * cfg["per_km_rate"])
    size_add = sum(cfg["size_addon"][t] * c for s in stops for t, c in s["parcels"].items())
    handling = sum(max(0, sum(s["parcels"].values()) - cfg["included_parcels"]) * cfg["handling_fee"] for s in stops)
    units = sum(UNITS[t] * c for s in stops for t, c in s["parcels"].items())
    bulky = sum(c for s in stops for t, c in s["parcels"].items() if t in cfg["bulky_sizes"])
    needs_cargo = bulky >= cfg["bulky_vehicle_threshold"]
    route_price = q2(base + dist + size_add + handling)
    hst = q2(route_price * cfg["hst_rate"])
    total = route_price + hst
    return {
        "currency": CURRENCY, "stopCount": n, "mode": "single" if n == 1 else "batch",
        "totalParcels": sum(sum(s["parcels"].values()) for s in stops),
        "routeKm": f(km), "dropBaseTotal": f(base), "distanceCharge": f(dist), "sizeAddOnTotal": f(size_add),
        "handlingTotal": f(handling), "routePrice": f(route_price),
        "hstRate": float(cfg["hst_rate"]), "hst": f(hst), "chargeTotal": f(total), "amount_cents": int(total * 100),
        "holdAmount": float(hold_amount(total, cfg)),
        "recommendedVehicle": "van" if needs_cargo else recommended_vehicle(units),
        "requiresCargoVehicle": needs_cargo, "bulkyParcels": bulky,
        "totalCargoUnits": float(units), "overVanCapacity": units > VAN_CAPACITY_UNITS,
    }


def parcel_quote(pickup, dropoff, size, priority=False, declared_value=None, scheduled_at=None):
    tier = size_tier(size)
    km = road_km([pickup, dropoff])
    dist = distance_charge(km)
    size_add = SIZE_ADDON[tier]
    local = (scheduled_at or datetime.now(dt_tz.utc)).astimezone(LOCAL_TZ)
    label, rush, night = None, D("0"), D("0")
    if local.hour >= 22 or local.hour < 6:
        label, night = "night", NIGHT
    elif local.weekday() < 5 and local.hour in (7, 8, 16, 17):
        label, rush = "rush", RUSH
    core = PARCEL_BASE + dist + size_add
    if priority:
        core = q2(core * PRIORITY_MULT)
    delivery_fee = q2(core + rush + night)
    value = q2(declared_value) if declared_value else D("0")
    guard = q2(value * GUARD_RATE) if value > 0 else D("0")
    hst = q2((delivery_fee + guard) * HST_RATE)          # tax on fee + guard, not on the escrowed item value
    total = delivery_fee + guard + hst + value
    return {
        "currency": CURRENCY, "size_category": tier, "distanceKm": f(km),
        "estimatedTimeMinutes": round(float(km) * 2.0, 1),
        "deliveryFee": f(delivery_fee), "guardFee": f(guard), "itemValueHeld": f(value),
        "hstRate": float(HST_RATE), "hst": f(hst), "totalDueAtBooking": f(total), "amount_cents": int(total * 100),
        "breakdown": {
            "base": f(PARCEL_BASE), "distanceAddOn": f(dist), "sizeAddOn": f(size_add), "surchargeLabel": label,
            "rushHourSurcharge": f(rush), "nightSurcharge": f(night), "timeAddOn": 0.0,
            "priorityMultiplierApplied": bool(priority), "guardActive": value > 0,
            "guardValueBand": None if value <= 0 else "low" if value < 100 else "mid" if value < 1000 else "high",
        },
        # used by booking to price an errand (not part of the partner response shape; stripped before returning)
        "_route_price": f(delivery_fee + guard), "_km": f(km),
    }
