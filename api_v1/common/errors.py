"""One error shape for the whole API:

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "req_..."}}

Codes follow the partner document (section 11): validation_failed, route_over_capacity, invalid_api_key,
errand_not_found, quote_expired, edit_window_closed, cancel_not_allowed, business_not_approved,
service_area_unavailable, rate_limited.
"""
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import set_rollback


class ApiError(APIException):
    def __init__(self, status, code, message, details=None, headers=None, **extra):
        self.status_code = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}
        self.extra = extra
        super().__init__(detail=message, code=code)


def error_payload(code, message, details=None, request_id=None, **extra):
    err = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    err.update(extra)
    if request_id:
        err["request_id"] = request_id
    return {"error": err}


def exception_handler(exc, context):
    request = context.get("request")
    rid = getattr(request, "request_id", None)
    headers = {}
    details = None
    extra = {}
    if isinstance(exc, ApiError):
        status, code, msg = exc.status_code, exc.code, exc.message
        details, extra, headers = exc.details, exc.extra, exc.headers
    elif isinstance(exc, Http404):
        status, code, msg = 404, "not_found", "Not found."
    elif isinstance(exc, drf.ParseError):
        status, code, msg = 400, "validation_failed", "Request body is not valid JSON."
        details = {"body": ["Send a valid JSON object."]}
    elif isinstance(exc, drf.UnsupportedMediaType):
        status, code, msg = 415, "unsupported_media_type", "Send Content-Type: application/json."
    elif isinstance(exc, drf.NotAuthenticated):
        status, code, msg = exc.status_code, "authentication_required", "Sign in to continue."
    elif isinstance(exc, drf.PermissionDenied):
        status, code, msg = 403, "forbidden", "You do not have permission to do that."
    elif isinstance(exc, drf.MethodNotAllowed):
        status, code, msg = 405, "method_not_allowed", "That method is not allowed on this endpoint."
    elif isinstance(exc, APIException):
        status, code, msg = exc.status_code, "error", str(exc.detail)
    else:
        return None  # unexpected: let Django return a 500 (and log it)
    set_rollback()
    return Response(error_payload(code, msg, details, rid, **extra), status=status, headers=headers)
