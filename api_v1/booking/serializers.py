"""Response shapes for create (partner document sections 2 and 3). Tracking/full-record shapes live in
tracking.serializers and build on these."""
from django.conf import settings


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def pricing_out(e):
    return {"currency": "CAD", "route_price": float(e.route_price), "hst": float(e.hst),
            "charge_total": float(e.charge_total), "amount_cents": int(e.charge_total * 100)}


def payment_out(e):
    p = e.payment
    return {"status": p.get("status", "unpaid"), "method": p.get("method"),
            "checkout_url": p.get("checkout_url"), "reference": p.get("reference")}


def tracking_links(e):
    return {"self": f"{settings.API_BASE_URL}/errands/{e.id}/tracking",
            "public_url": f"{settings.PUBLIC_TRACK_URL}/{e.id}"}


def location_out(loc):
    return {"label": loc["label"], "lat": loc["lat"], "lng": loc["lng"], "contact": loc["contact"]}


def errand_view(e):
    """Single errand, section 2 response."""
    return {
        "errand_id": str(e.id), "delivery_id": e.delivery_id, "status": e.status, "reference": e.reference,
        "created_at": iso(e.created_at), "scheduled_at": iso(e.scheduled_at), "delivery_code": e.delivery_code,
        "pricing": pricing_out(e), "payment": payment_out(e),
        "pickup": location_out(e.pickup), "dropoff": location_out(e.dropoff),
        "tracking": tracking_links(e), "metadata": e.metadata,
    }


def stop_view(e):
    return {"errand_id": str(e.id), "index": e.batch_index, "reference": e.reference, "label": e.dropoff["label"],
            "lat": e.dropoff["lat"], "lng": e.dropoff["lng"], "receiver_name": e.dropoff["contact"].get("name"),
            "status": e.status, "price": str(e.price), "payment_status": e.payment_status,
            "delivery_code": e.delivery_code}


def batch_view(errands):
    """Multi-stop route, section 3 response."""
    first = errands[0]
    return {
        "batch_id": str(first.batch_id), "status": first.status, "stop_count": len(errands),
        "created_at": iso(first.created_at), "pricing": pricing_out(first),
        "payment": {"status": first.payment.get("status", "unpaid"), "method": first.payment.get("method"),
                    "total": str(first.charge_total), "covers": [str(e.id) for e in errands]},
        "stops": [stop_view(e) for e in errands],
    }


def create_response(errands):
    return batch_view(errands) if errands[0].is_multi else errand_view(errands[0])
