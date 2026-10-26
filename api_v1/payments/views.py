from decimal import Decimal, InvalidOperation

from rest_framework.response import Response

from api_v1.booking.selectors import get_errand
from api_v1.common.base import V1View
from api_v1.common.dashboard import DashboardView
from api_v1.common.errors import ApiError
from api_v1.common.validation import Errs, body_object, text
from api_v1.tracking.serializers import full_record

from . import services


def wallet_out(business):
    w = services.get_wallet(business)
    txs = [{"id": str(t.id), "type": t.type, "amount": str(t.amount), "balance_after": str(t.balance_after),
            "ref": t.ref, "created_at": t.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")}
           for t in w.transactions.all()[:20]]
    return {"currency": "CAD", "balance": str(w.balance), "transactions": txs}


class WalletView(V1View):
    """GET /v1/wallet"""

    required_scope = "wallet:read"

    def get(self, request):
        return Response(wallet_out(request.auth.business))


class CancelView(V1View):
    """POST /v1/errands/<id>/cancel - body optional: {"reason": "..."}. Fee and refund are in `cancellation`."""

    required_scope = "errands:cancel"
    mutating = True

    def post(self, request, errand_id):
        e = get_errand(request.auth, errand_id)
        data = request.data if isinstance(request.data, dict) else {}
        errs = Errs()
        reason = text(errs, "reason", data.get("reason"), required=False) or ""
        errs.raise_if_any()
        e = services.cancel_errand(e.id, request.auth.business, request.auth.environment, reason)
        return Response(full_record(e))


class DashboardWalletView(DashboardView):
    """GET /dashboard/wallet, POST /dashboard/wallet (top up, test mode)"""

    def get(self, request):
        return Response(wallet_out(self.business))

    def post(self, request):
        data = body_object(request.data)
        try:
            amount = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise ApiError(400, "validation_failed", "Amount must be a number.", details={"amount": ["Must be a number."]})
        services.top_up(self.business, amount)
        return Response(wallet_out(self.business), status=201)
