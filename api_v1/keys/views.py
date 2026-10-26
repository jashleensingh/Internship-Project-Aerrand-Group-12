from rest_framework.response import Response

from api_v1.common.base import V1View
from api_v1.common.dashboard import DashboardView
from api_v1.common.validation import body_object

from . import services


def key_out(k):
    return {"id": k.id, "name": k.name, "environment": k.environment, "scopes": k.scopes,
            "prefix": k.key_prefix, "status": k.status,
            "created_at": k.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "revoked_at": k.revoked_at.strftime("%Y-%m-%dT%H:%M:%SZ") if k.revoked_at else None}


class MeView(V1View):
    """GET /v1/me - who this key belongs to (handy first call to check a key works)."""

    def get(self, request):
        from api_v1.payments.services import get_wallet
        b, k = request.auth.business, request.auth
        return Response({
            "business": {"id": b.id, "name": b.name, "approval_status": b.approval_status},
            "key": {"id": k.id, "name": k.name, "environment": k.environment, "scopes": k.scopes, "prefix": k.key_prefix},
            "wallet": {"currency": "CAD", "balance": str(get_wallet(b).balance)},
        })


class KeyListCreateView(DashboardView):
    """GET /dashboard/api-keys, POST /dashboard/api-keys (the plain key is in this one response only)."""

    def get(self, request):
        return Response({"data": [key_out(k) for k in self.business.api_keys.all()]})

    def post(self, request):
        obj, raw = services.create_key(self.business, body_object(request.data))
        return Response({**key_out(obj), "key": raw,
                         "notice": "Copy this key now. For your safety it is never shown again."}, status=201)


class KeyRevokeView(DashboardView):
    """DELETE /dashboard/api-keys/<id> - takes effect on the very next request."""

    def delete(self, request, key_id):
        services.revoke_key(self.business, key_id)
        return Response({"id": key_id, "status": "revoked"})
