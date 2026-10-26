"""Service area check: is this address inside an activated city? Enforced at create time, before money moves.
Stand-in data; in Aerrand's repo this reads the existing activated-cities collection."""
from rest_framework.response import Response

from api_v1.common.base import V1View
from api_v1.common.errors import ApiError
from api_v1.common.geo import haversine_km

SERVICE_AREAS = [
    {"slug": "windsor", "name": "Windsor", "province": "ON", "lat": 42.3149, "lng": -83.0364,
     "radiusKm": 20.0, "active": True},
]
UPDATED_AT = "2026-09-02T18:41:07Z"


def locate(lat, lng):
    """Returns (inside, city_slug_or_None)."""
    for a in SERVICE_AREAS:
        if a["active"] and haversine_km(lat, lng, a["lat"], a["lng"]) <= a["radiusKm"]:
            return True, a["slug"]
    return False, None


def nearest(lat, lng):
    best = min((a for a in SERVICE_AREAS if a["active"]), key=lambda a: haversine_km(lat, lng, a["lat"], a["lng"]))
    return best, haversine_km(lat, lng, best["lat"], best["lng"])


def check(pickup, dropoffs):
    """Raise 412 service_area_unavailable (with per-address details) if any address is outside every served city."""
    p_in, p_city = locate(pickup["lat"], pickup["lng"])
    d_res = []
    for d in dropoffs:
        inside, city = locate(d["lat"], d["lng"])
        d_res.append({"inside": inside, "city": city})
    if p_in and all(r["inside"] for r in d_res):
        return
    if not p_in:
        where, (lat, lng) = "the pickup", (pickup["lat"], pickup["lng"])
    else:
        i = next(i for i, r in enumerate(d_res) if not r["inside"])
        where, (lat, lng) = f"drop-off #{i + 1}", (dropoffs[i]["lat"], dropoffs[i]["lng"])
    city, km = nearest(lat, lng)
    raise ApiError(
        412, "service_area_unavailable",
        f"Aerrand isn't available at {where} yet. The closest city we serve is {city['name']} ({round(km)} km away).",
        details={
            "pickup": {"inside": p_in, "city": p_city},
            "dropoffs": d_res,
            "nearestCity": {"slug": city["slug"], "name": city["name"], "province": city["province"],
                            "distanceKm": round(km, 1)},
        })


class ServiceAreasView(V1View):
    """GET /v1/service-areas - check coverage before offering delivery at checkout."""

    def get(self, request):
        return Response({"serviceAreas": SERVICE_AREAS, "updatedAt": UPDATED_AT})
