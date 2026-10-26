from rest_framework.permissions import BasePermission

from api_v1.common.errors import ApiError


class V1Permission(BasePermission):
    """Scope check, then the approval gate for anything that changes data."""

    def has_permission(self, request, view):
        key = request.auth
        scope = getattr(view, "required_scope", None)
        if scope and scope not in key.scopes:
            raise ApiError(403, "insufficient_scope", f"This key does not have the '{scope}' scope.",
                           required_scope=scope)
        if getattr(view, "mutating", False) and not key.business.approved:
            raise ApiError(412, "business_not_approved", "Your account is still under review.")
        return True
