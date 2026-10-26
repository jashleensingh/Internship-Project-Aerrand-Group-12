import ipaddress
import secrets
from urllib.parse import urlparse

from django.conf import settings
from rest_framework.response import Response

from api_v1.common.dashboard import DashboardView
from api_v1.common.errors import ApiError
from api_v1.common.validation import Errs, body_object

from .models import WebhookEndpoint
from .outbox import EVENT_TYPES


def _check_url(errs, url):
    if not isinstance(url, str) or not url:
        errs.add("url", "This field is required.")
        return
    p = urlparse(url)
    local = p.hostname in ("localhost", "127.0.0.1") and settings.DEBUG
    if p.scheme != "https" and not local:
        errs.add("url", "Must be an https:// URL.")
    try:
        ip = ipaddress.ip_address(p.hostname or "")
        if (ip.is_private or ip.is_loopback or ip.is_link_local) and not local:
            errs.add("url", "Private network addresses are not allowed.")
    except ValueError:
        pass   # a hostname. NOTE: production must also resolve the name and refuse private IPs (SSRF) at send time.


def endpoint_out(ep, secret=None):
    out = {"id": ep.id, "url": ep.url, "environment": ep.environment, "events": ep.events, "active": ep.active}
    if secret:
        out["secret"] = secret
        out["notice"] = "Copy this signing secret now. It is never shown again."
    return out


class WebhookEndpointListCreateView(DashboardView):
    """GET/POST /dashboard/webhook-endpoints"""

    def get(self, request):
        return Response({"data": [endpoint_out(e) for e in self.business.webhook_endpoints.filter(active=True)],
                         "event_types": EVENT_TYPES})

    def post(self, request):
        if not self.business.approved:
            raise ApiError(412, "business_not_approved", "Your account is still under review.")
        data = body_object(request.data)
        errs = Errs()
        _check_url(errs, data.get("url"))
        env = data.get("environment", "live")
        if env not in ("live", "test"):
            errs.add("environment", "Must be 'live' or 'test'.")
        events = data.get("events") or []
        if not isinstance(events, list) or any(e != "*" and e not in EVENT_TYPES for e in events):
            errs.add("events", "Must be a list of event types (or '*').")
        errs.raise_if_any()
        secret = "whsec_" + secrets.token_urlsafe(32)
        ep = WebhookEndpoint.objects.create(business=self.business, url=data["url"], environment=env,
                                            events=events, secret=secret)
        return Response(endpoint_out(ep, secret), status=201)


class WebhookEndpointDeleteView(DashboardView):
    def delete(self, request, endpoint_id):
        n = WebhookEndpoint.objects.filter(pk=endpoint_id, business=self.business, active=True).update(active=False)
        if not n:
            raise ApiError(404, "not_found", "No webhook endpoint with that id.")
        return Response({"id": endpoint_id, "active": False})
