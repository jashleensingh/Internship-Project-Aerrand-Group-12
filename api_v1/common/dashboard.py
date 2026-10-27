"""Dashboard (browser) endpoints use the signed-in session, not an API key. In Aerrand's real project this is
the existing dashboard login; here a tiny login view exists so the module runs on its own."""
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .errors import ApiError


class DashboardSessionAuth(SessionAuthentication):
    """Session cookie + CSRF check. 401 (not 403) when not signed in."""

    def authenticate(self, request):
        res = super().authenticate(request)
        if res is None:
            return None
        user = res[0]
        if not hasattr(user, "business"):
            raise ApiError(403, "forbidden", "This account has no business.")
        return user, None

    def authenticate_header(self, request):
        return "Session"


class DashboardView(APIView):
    authentication_classes = [DashboardSessionAuth]
    permission_classes = [IsAuthenticated]

    @property
    def business(self):
        return self.request.user.business
