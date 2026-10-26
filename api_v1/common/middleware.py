import re
import secrets

_OK = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdMiddleware:
    """Gives every request an id (echoed in X-Request-Id and in error bodies) and adds safe response headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = request.headers.get("X-Request-Id", "")
        if not _OK.match(rid):
            rid = "req_" + secrets.token_hex(8)
        request.request_id = rid
        response = self.get_response(request)
        response["X-Request-Id"] = rid
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
