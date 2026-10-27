"""Drop-off / pickup instructions (Pratyush).

Edit window for drop-off (partner document, section 5):
    up to in_transit ........... all fields
    within 1 km of the stop .... instructions only; other changes -> 409 edit_window_closed
    delivered / cancelled ...... nothing can change -> 409 edit_window_closed
Pickup follows the same idea around the pickup stop: all fields until the Aerrander arrives, then instructions
only until the items are picked up, then locked.
"""
from django.db import transaction
from django.utils import timezone

from api_v1.booking.models import Errand
from api_v1.common.errors import ApiError
from api_v1.common.realtime import push_realtime
from api_v1.common.validation import Errs, contact
from api_v1.reliability.outbox import emit_event
from api_v1.tracking.services import EDIT_WINDOW_KM, distance_to_dropoff_km


def edit_mode(e, kind):
    """'all' | 'instructions' | 'closed'"""
    if e.status in ("delivered", "cancelled"):
        return "closed"
    if kind == "pickup":
        if e.status in ("picked_up", "in_transit", "arrived_dropoff"):
            return "closed"
        return "instructions" if e.status == "arrived" else "all"
    if e.status == "arrived_dropoff":
        return "instructions"
    km = distance_to_dropoff_km(e) if e.status in ("accepted", "arrived", "picked_up", "in_transit") else None
    return "instructions" if km is not None and km <= EDIT_WINDOW_KM else "all"


def _is_xl(e):
    return bool((e.parcels or {}).get("xl")) or (e.parcel or {}).get("size") == "xl"


def update_instruction(errand_id, kind, patch):
    """kind = 'dropoff' | 'pickup'. Partial update. Returns the data block for the response."""
    errs = Errs()
    if not isinstance(patch, dict) or not patch:
        errs.add("body", "Send at least one field to change.")
        errs.raise_if_any()
    with transaction.atomic():
        e = Errand.objects.select_for_update().get(pk=errand_id)
        loc = dict(e.pickup if kind == "pickup" else e.dropoff)
        current = dict(loc.get("contact") or {})
        # if the instruction does not exist yet, this creates it (so all required fields must be present)
        clean = contact(errs, "body", patch, kind, require_all=not current)
        errs.raise_if_any()
        if kind == "dropoff" and _is_xl(e) and "preference" in clean:
            clean["preference"] = "meet_at_curb"      # oversized parcels are curbside only

        mode = edit_mode(e, kind)
        if mode == "closed":
            raise ApiError(409, "edit_window_closed", f"This errand is {e.status}; instructions can no longer change.")
        if mode == "instructions":
            locked = [k for k, v in clean.items() if k != "instructions" and current.get(k) != v]
            if locked:
                raise ApiError(409, "edit_window_closed",
                               "The Aerrander is at or near the stop: only instructions can change now.",
                               details={"locked_fields": locked})

        current.update(clean)
        loc["contact"] = current
        field = "pickup" if kind == "pickup" else "dropoff"
        Errand.objects.filter(pk=e.pk).update(**{field: loc}, updated_at=timezone.now())
        fresh = Errand.objects.get(pk=e.pk)
        if kind == "dropoff":
            emit_event(fresh, "errand.dropoff_updated", extra={"dropoff": {
                "label": loc["label"], "name": current.get("name"), "phone_number": current.get("phone_number"),
                "instructions": current.get("instructions"), "preference": current.get("preference")}})
        # the Aerrander's phone sees the change immediately, including mid-route
        push_realtime(f"errand/{e.id}", {f"{kind}_instruction": current})
    iid = fresh.pickup_instruction_id if kind == "pickup" else fresh.dropoff_instruction_id
    data = {"id": str(iid), "name": current.get("name"), "phone_number": current.get("phone_number"),
            "instructions": current.get("instructions"), "preference": current.get("preference")}
    if kind == "pickup":
        data["email"] = current.get("email")
    return data
