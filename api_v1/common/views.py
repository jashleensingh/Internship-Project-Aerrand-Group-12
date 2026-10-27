from django.contrib.auth import authenticate, login, logout
from rest_framework.response import Response
from rest_framework.views import APIView

from .errors import ApiError


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"status": "ok"})


class LoginView(APIView):
    """Local sign-in for the dashboard endpoints (stand-in for Aerrand's real dashboard login)."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        user = authenticate(request._request, username=request.data.get("username"), password=request.data.get("password"))
        if user is None or not hasattr(user, "business"):
            raise ApiError(401, "invalid_credentials", "Wrong username or password.")
        login(request._request, user)
        return Response({"business": {"id": user.business.id, "name": user.business.name,
                                      "approval_status": user.business.approval_status}})


class LogoutView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        logout(request._request)
        return Response({"ok": True})
