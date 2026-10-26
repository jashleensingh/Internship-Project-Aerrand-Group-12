import uuid

from rest_framework.response import Response
from rest_framework.views import APIView

from api_v1.booking.models import Errand
from api_v1.booking.selectors import get_errand
from api_v1.common.base import V1View
from api_v1.common.errors import ApiError

from .serializers import full_record, public_response, tracking_response


class ErrandDetailView(V1View):
    """GET /v1/errands/<id> - full record."""

    required_scope = "errands:read"

    def get(self, request, errand_id):
        return Response(full_record(get_errand(request.auth, errand_id)))


class TrackingView(V1View):
    """GET /v1/errands/<id>/tracking - the poll call (every 5-10 s while an Aerrander is engaged, else 60 s)."""

    required_scope = "errands:read"

    def get(self, request, errand_id):
        return Response(tracking_response(get_errand(request.auth, errand_id)))


class PublicTrackingView(APIView):
    """GET /v1/errands/<id>/public - no API key. The errand id is the token, so only a safe subset is returned."""

    authentication_classes = []
    permission_classes = []

    def get(self, request, errand_id):
        try:
            e = Errand.objects.filter(pk=uuid.UUID(str(errand_id))).first()
        except ValueError:
            e = None
        if e is None:
            raise ApiError(404, "errand_not_found", "No errand with that id.")
        return Response(public_response(e))
