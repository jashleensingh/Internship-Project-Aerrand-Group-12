"""Base class for every API-key endpoint under /v1.

Order of work for a request: authenticate the key -> check scope and approval -> rate limit -> the view.
Subclasses set `required_scope`, `mutating` (needs an approved business) and `rate_kind` ("default"/"create").
"""
from rest_framework.views import APIView

from api_v1.keys.authentication import ApiKeyAuthentication
from api_v1.keys.permissions import V1Permission
from api_v1.reliability import ratelimit


class V1View(APIView):
    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [V1Permission]
    required_scope = None
    mutating = False
    rate_kind = "default"
    rate_headers = {}

    def initial(self, request, *args, **kwargs):
        # Keep the raw bytes: idempotency fingerprints them (must be read before the body is parsed).
        request._request.raw_body = request.body
        super().initial(request, *args, **kwargs)
        self.rate_headers = ratelimit.enforce(request, self.rate_kind)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        for k, v in (self.rate_headers or {}).items():
            response[k] = v
        return response

    @property
    def business(self):
        return self.request.auth.business
