"""emit_event: write the event and its per-endpoint delivery rows. Call it inside the same transaction as the change.

Envelope (partner document 7e):
  {"id": "evt_...", "type": "errand.in_transit", "created_at": "...",
   "data": {"errand_id", "batch_id", "reference", "status", "driver": {"name", "vehicle_type"}, "occurred_at", ...}}
Events: errand.payment_confirmed, accepted, arrived_pickup, in_transit, arrived_dropoff, delivered, cancelled,
dropoff_updated.
"""
from django.utils import timezone

from api_v1.common.ids import evt_id

from .models import OutboxEvent, WebhookDelivery, WebhookEndpoint

EVENT_TYPES = [
    "errand.payment_confirmed", "errand.accepted", "errand.arrived_pickup", "errand.in_transit",
    "errand.arrived_dropoff", "errand.delivered", "errand.cancelled", "errand.dropoff_updated",
]


def _z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_event(errand, event_type, extra=None):
    now = timezone.now()
    d = errand.driver
    data = {
        "errand_id": str(errand.id),
        "batch_id": str(errand.batch_id) if errand.batch_id else None,
        "reference": errand.reference or None,
        "status": errand.status,
        "driver": {"name": d.get("name"), "vehicle_type": d.get("vehicle_type")} if d else None,
        "occurred_at": _z(now),
    }
    data.update(extra or {})
    eid = evt_id()
    event = OutboxEvent.objects.create(
        id=eid, business_id=errand.business_id, environment=errand.environment, type=event_type,
        payload={"id": eid, "type": event_type, "created_at": _z(now), "data": data})
    for ep in WebhookEndpoint.objects.filter(business_id=errand.business_id, environment=errand.environment,
                                             active=True):
        if ep.wants(event_type):
            WebhookDelivery.objects.create(event=event, endpoint=ep, next_attempt_at=now)
    return event
