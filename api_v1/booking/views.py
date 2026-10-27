from rest_framework.response import Response

from api_v1.common.base import V1View
from api_v1.common.validation import body_object
from api_v1.reliability.idempotency import run_idempotent

from . import serializers, services
from .validation import validate_create


class QuoteCreateView(V1View):
    """POST /v1/quotes - free and unmetered (counts only toward the normal per-minute limit)."""

    required_scope = "quotes:write"

    def post(self, request):
        q = services.create_quote(request.auth, body_object(request.data))
        return Response(q.result, status=200)


class ErrandCreateView(V1View):
    """POST /v1/errands - book a quote. Needs an Idempotency-Key (required for live keys)."""

    required_scope = "errands:write"
    mutating = True
    rate_kind = "create"

    def post(self, request):
        data = body_object(request.data)

        def produce():
            v = validate_create(data)
            errands = services.create_errands(request.auth, v)
            return Response(serializers.create_response(errands), status=201)

        return run_idempotent(request, produce, required=request.auth.environment == "live")
