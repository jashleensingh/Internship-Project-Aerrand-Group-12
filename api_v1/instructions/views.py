import uuid

from django.db import transaction
from rest_framework.response import Response

from api_v1.booking.models import Errand
from api_v1.booking.selectors import get_errand
from api_v1.common.base import V1View
from api_v1.common.errors import ApiError
from api_v1.common.validation import Errs, body_object, number, text

from . import checklist as ai
from . import services


class DropoffView(V1View):
    """PUT /v1/errands/<id>/dropoff - partial update; reaches the Aerrander's app immediately."""

    required_scope = "errands:write"
    mutating = True

    def put(self, request, errand_id):
        e = get_errand(request.auth, errand_id)
        data = services.update_instruction(e.id, "dropoff", request.data)
        return Response({"status": True, "message": "Dropoff instruction updated", "data": data})


class PickupView(V1View):
    """PUT /v1/errands/<id>/pickup - same shape as drop-off, plus an optional email."""

    required_scope = "errands:write"
    mutating = True

    def put(self, request, errand_id):
        e = get_errand(request.auth, errand_id)
        data = services.update_instruction(e.id, "pickup", request.data)
        return Response({"status": True, "message": "Pickup instruction updated", "data": data})


class ChecklistGenerateView(V1View):
    """POST /v1/checklists/generate - never fails a booking: unavailable model -> 200 with empty lists."""

    required_scope = "errands:write"

    def post(self, request):
        data = body_object(request.data)
        errs = Errs()
        desc = text(errs, "description", data.get("description"), max_len=1000)
        qty = data.get("quantity")
        if qty is not None and (isinstance(qty, bool) or not isinstance(qty, int) or qty < 1):
            errs.add("quantity", "Must be a whole number.")
        size = data.get("size")
        if size is not None and size not in ai.SIZES:
            errs.add("size", "Must be one of: " + ", ".join(ai.SIZES) + ".")
        price = data.get("price")
        if price is not None:
            price = number(errs, "price", price, 0)
        errs.raise_if_any()
        return Response(ai.generate(desc, qty, size, float(price) if price is not None else None))


def _attach(request, errand_id, key, field, allowed=None):
    """Shared by checklist and tags: list of strings, de-duplicated, safe to call twice."""
    e = get_errand(request.auth, errand_id)
    data = body_object(request.data)
    errs = Errs()
    raw = data.get(key)
    items = []
    if not isinstance(raw, list) or not raw or len(raw) > 20:
        errs.add(key, "Must be a list of 1 to 20 strings.")
    else:
        for i, s in enumerate(raw):
            t = text(errs, f"{key}[{i}]", s, max_len=255)
            if t and allowed is not None and t not in allowed:
                errs.add(f"{key}[{i}]", "Not in the tag list: " + ", ".join(allowed) + ".")
            elif t:
                items.append(t)
    errs.raise_if_any()
    if e.status in ("delivered", "cancelled"):
        raise ApiError(409, "edit_window_closed", f"This errand is {e.status}; it can no longer change.")
    with transaction.atomic():
        e = Errand.objects.select_for_update().get(pk=e.pk)
        stored = list(getattr(e, field))
        by_title = {x["title"]: x for x in stored}
        out = []
        for t in dict.fromkeys(items):
            if t not in by_title:
                by_title[t] = {"id": str(uuid.uuid4()), "title": t}
                stored.append(by_title[t])
            out.append(by_title[t])
        Errand.objects.filter(pk=e.pk).update(**{field: stored})
    return out


class ChecklistAttachView(V1View):
    required_scope = "errands:write"
    mutating = True

    def post(self, request, errand_id):
        out = _attach(request, errand_id, "checklists", "checklist")
        return Response({"status": True, "message": "Checklists added successfully", "data": out})


class TagsAttachView(V1View):
    required_scope = "errands:write"
    mutating = True

    def post(self, request, errand_id):
        out = _attach(request, errand_id, "tags", "tags", allowed=ai.TAGS)
        return Response({"status": True, "message": "Tags added successfully", "data": out})
