"""Tracking shapes (partner document, section 7): poll, full record, and the safe public subset."""
from api_v1.booking.models import Errand
from api_v1.booking.serializers import errand_view, iso


def _driver(d):
    if not d:
        return None
    keys = ("id", "name", "phone", "image", "rating", "vehicle_type", "total_deliveries", "verified", "city")
    return {k: d.get(k) for k in keys}


def _batch_short(e):
    return {"id": str(e.batch_id), "index": e.batch_index, "size": e.batch_size} if e.batch_id else None


def tracking_core(e):
    return {
        "errand_id": str(e.id), "delivery_id": e.delivery_id, "status": e.status, "workflow_phase": e.status,
        "is_accepted": e.accepted_at is not None, "driver": _driver(e.driver), "driver_location": e.driver_location,
        "delivery_code": e.delivery_code, "accepted_at": iso(e.accepted_at), "started_at": iso(e.started_at),
        "completed_at": iso(e.completed_at), "updated_at": iso(e.updated_at), "timeline": e.timeline,
        "proof_of_delivery": e.proof_of_delivery, "batch": _batch_short(e),
    }


def tracking_response(e):
    return {"status": True, "data": tracking_core(e)}


def full_record(e):
    """GET /v1/errands/<id>: everything from create + tracking + payment_status, distance, cancellation, batch stops."""
    out = {**errand_view(e), **tracking_core(e)}
    out.update(payment_status=e.payment_status, distance_km=str(e.distance_km), cancellation=e.cancellation,
               parcel=e.parcel, delivery_note=e.delivery_note, checklist=e.checklist, tags=e.tags)
    if e.batch_id:
        stops = list(Errand.objects.filter(batch_id=e.batch_id).order_by("batch_index"))
        out["batch"] = {
            "id": str(e.batch_id), "index": e.batch_index, "size": e.batch_size,
            "total": str(e.charge_total),
            "paid_total": str(sum((s.price for s in stops if s.payment_status), 0) or "0.00"),
            "stops": [{"errand_id": str(s.id), "index": s.batch_index, "label": s.dropoff["label"],
                       "receiver_name": s.dropoff["contact"].get("name"), "status": s.status,
                       "price": str(s.price), "payment_status": s.payment_status} for s in stops],
        }
    return out


def public_response(e):
    """Tokenless customer view. No delivery_code, no pricing, no contact details."""
    d = e.driver or {}
    loc = e.driver_location or {}
    return {"success": True, "data": {
        "errand_id": str(e.id), "status": e.status,
        "pickup": {"label": e.pickup["label"], "lat": e.pickup["lat"], "lng": e.pickup["lng"]},
        "dropoff": {"label": e.dropoff["label"], "lat": e.dropoff["lat"], "lng": e.dropoff["lng"]},
        "driver": ({"name": d.get("name"), "image": d.get("image"), "vehicle_model": d.get("vehicle_model"),
                    "vehicle_type": d.get("vehicle_type"), "plate_number": d.get("plate_number")} if d else None),
        "driver_lat": str(loc["lat"]) if loc else None, "driver_lng": str(loc["lng"]) if loc else None,
        "timeline": e.timeline, "created_at": iso(e.created_at),
    }}
