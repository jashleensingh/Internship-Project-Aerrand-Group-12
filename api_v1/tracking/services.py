"""Delivery tracking (Ashwin).

In Aerrand's stack the Aerrander app writes status, position and proof to the shared `deliveries` document and the
API merges them onto the response. Here the same writes go through these functions, so webhooks, notifications
and tests exercise the real path. `simulate_driver` (management command) calls them to play a driver.
"""
from django.db import transaction
from django.utils import timezone

from api_v1.booking.models import Errand
from api_v1.common.errors import ApiError
from api_v1.common.geo import haversine_km
from api_v1.common.realtime import push_realtime
from api_v1.notices import hooks
from api_v1.reliability.outbox import emit_event

# event -> (allowed current statuses, new status, timeline state, webhook type or None)
EVENTS = {
    "accepted": ({"broadcasted"}, "accepted", "AERRANDER_ASSIGNED", "errand.accepted"),
    "arrived_pickup": ({"accepted"}, "arrived", "AT_PICKUP_LOADING", "errand.arrived_pickup"),
    "picked_up": ({"arrived"}, "picked_up", "ITEMS_COLLECTED", None),
    "in_transit": ({"arrived", "picked_up"}, "in_transit", "ROUTE_IN_PROGRESS", "errand.in_transit"),
    "arrived_dropoff": ({"in_transit"}, "arrived_dropoff", "AT_DROPOFF", "errand.arrived_dropoff"),
    "delivered": ({"arrived_dropoff"}, "delivered", "DELIVERED", "errand.delivered"),
}
DEFAULT_DRIVER = {"id": "66e0b8f1c4a2d35907ab1e44", "name": "Sam O.", "phone": "+15195550101", "image": None,
                  "rating": 4.9, "vehicle_type": "car", "vehicle_model": "Toyota Corolla", "plate_number": "CXYZ 123",
                  "total_deliveries": 218, "verified": True, "city": "Windsor"}
EDIT_WINDOW_KM = 1.0


def _z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_event(errand_id, event, driver=None, photo_url=None):
    """Move an errand forward. Compare-and-set on status, so a repeated or out-of-order event is refused (409)."""
    if event not in EVENTS:
        raise ApiError(400, "validation_failed", f"Unknown event '{event}'.", details={"event": [", ".join(EVENTS)]})
    allowed, new_status, state, hook = EVENTS[event]
    with transaction.atomic():
        e = Errand.objects.select_for_update().get(pk=errand_id)
        if e.status not in allowed:
            raise ApiError(409, "invalid_transition", f"Cannot apply '{event}' while the errand is '{e.status}'.",
                           current_status=e.status)
        now = timezone.now()
        fields = {"status": new_status, "timeline": list(e.timeline) + [{"at": _z(now), "state": state}],
                  "updated_at": now}
        if event == "accepted":
            fields.update(driver=driver or DEFAULT_DRIVER, accepted_at=now)
        if event == "in_transit":
            fields["started_at"] = now
        if event == "delivered":
            fields.update(completed_at=now, proof_of_delivery={
                "photo_url": photo_url or f"https://res.cloudinary.com/aerrand/image/upload/v1/pod/{e.id}.jpg",
                "uploaded_at": _z(now)})
        if not Errand.objects.filter(pk=e.pk, status=e.status).update(**fields):
            raise ApiError(409, "invalid_transition", "The errand changed at the same time. Try again.")
        fresh = Errand.objects.get(pk=e.pk)
        if hook:
            extra = {"proof_of_delivery": fresh.proof_of_delivery} if event == "delivered" else None
            emit_event(fresh, hook, extra=extra)
        if event == "delivered":
            hooks.on_delivered(fresh)
        push_realtime(f"errand/{fresh.id}", {"status": fresh.status})
        return fresh


def update_location(errand_id, lat, lng, heading=None):
    now = timezone.now()
    loc = {"lat": float(lat), "lng": float(lng), "heading": heading, "updated_at": _z(now)}
    n = Errand.objects.filter(pk=errand_id, status__in=["accepted", "arrived", "picked_up", "in_transit",
                                                       "arrived_dropoff"]).update(driver_location=loc, updated_at=now)
    if not n:
        raise ApiError(409, "invalid_transition", "No Aerrander is engaged on this errand.")
    push_realtime(f"errand/{errand_id}", {"driver_location": loc})


def distance_to_dropoff_km(errand):
    loc = errand.driver_location
    if not loc:
        return None
    return haversine_km(loc["lat"], loc["lng"], errand.dropoff["lat"], errand.dropoff["lng"])
