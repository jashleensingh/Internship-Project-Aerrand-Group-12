"""Stand-in pricing engines with the same shapes as the partner document (section 1). The numbers (rates, allowances)
are placeholders: in Aerrand's repo these two functions call the existing route engine (order/business_pricing.py)
and parcel engine, and everything else in this module stays the same.

Route engine  : trip base, base per extra stop, distance beyond a free allowance, size add-ons, handling past the
                included parcel count, flat van-on-volume surcharge, then HST. No time-of-day component.
Parcel engine : adds rush / night surcharges, optional priority multiplier, and Aerrand Guard when a declared
                value is present (the item value is held in escrow, in the total but not taxed).
"""
from datetime import datetime, timezone as dt_tz
from decimal import ROUND_HALF_UP, Decimal as D
from zoneinfo import ZoneInfo

from api_v1.common.geo import haversine_km

CURRENCY = "CAD"
HST_RATE = D("0.13")
TIERS = ("small", "medium", "large", "xl")
UNITS = {"small": D("0.5"), "medium": D("1"), "large": D("2"), "xl": D("4")}
SIZE_ADDON = {"small": D("0"), "medium": D("2.00"), "large": D("5.00"), "xl": D("9.00")}
FIRST_STOP, EXTRA_STOP = D("8.00"), D("3.50")
FREE_KM, PER_KM, ROAD_FACTOR = D("2.0"), D("1.10"), D("1.3")
INCLUDED_PARCELS, HANDLING_FEE = 5, D("1.00")
VAN_ON_VOLUME_UNITS, VAN_CAPACITY_UNITS, VOLUME_SURCHARGE = D("10"), D("24"), D("15.00")
PARCEL_BASE = D("6.00")
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


def route_quote(pickup, stops):
    """pickup = (lat, lng); stops = [{"lat","lng","parcels": {tier: count}}]. Returns the response body (without id/expiry)."""
    n = len(stops)
    km = road_km([pickup] + [(s["lat"], s["lng"]) for s in stops])
    base = FIRST_STOP + EXTRA_STOP * (n - 1)
    dist = distance_charge(km)
    size_add = sum(SIZE_ADDON[t] * c for s in stops for t, c in s["parcels"].items())
    handling = sum(max(0, sum(s["parcels"].values()) - INCLUDED_PARCELS) * HANDLING_FEE for s in stops)
    units = sum(UNITS[t] * c for s in stops for t, c in s["parcels"].items())
    volume = VOLUME_SURCHARGE if VAN_ON_VOLUME_UNITS < units <= VAN_CAPACITY_UNITS else D("0")
    route_price = q2(base + dist + size_add + handling + volume)
    hst = q2(route_price * HST_RATE)
    total = route_price + hst
    return {
        "currency": CURRENCY, "stopCount": n,
        "totalParcels": sum(sum(s["parcels"].values()) for s in stops),
        "routeKm": f(km), "dropBaseTotal": f(base), "distanceCharge": f(dist), "sizeAddOnTotal": f(size_add),
        "handlingTotal": f(handling), "volumeSurcharge": f(volume), "routePrice": f(route_price),
        "hstRate": float(HST_RATE), "hst": f(hst), "chargeTotal": f(total), "amount_cents": int(total * 100),
        "recommendedVehicle": recommended_vehicle(units), "requiresCargoVehicle": units > VAN_ON_VOLUME_UNITS,
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
