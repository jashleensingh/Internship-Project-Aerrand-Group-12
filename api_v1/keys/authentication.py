from rest_framework.authentication import BaseAuthentication

from api_v1.common.errors import ApiError

from . import services


class ApiKeyAuthentication(BaseAuthentication):
    """Authorization: Bearer ak_live_...   (or X-Api-Key). Keys in the URL are refused: URLs end up in logs."""

    def authenticate(self, request):
        if "api_key" in request.query_params:
            raise ApiError(400, "validation_failed", "Send the key in a header, never in the URL.",
                           details={"api_key": ["Use the Authorization header."]})
        raw = None
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            raw = header[7:].strip()
        raw = raw or request.headers.get("X-Api-Key", "").strip()
        if not raw:
            raise ApiError(401, "invalid_api_key", "Missing API key. Send 'Authorization: Bearer ak_...'.")
        key = services.lookup(raw)
        if key is None:
            raise ApiError(401, "invalid_api_key", "That API key is not valid.")
        if key.status != "active":
            raise ApiError(401, "invalid_api_key", "That API key has been revoked.")
        return key.business.owner, key

    def authenticate_header(self, request):
        return 'Bearer realm="aerrand"'
