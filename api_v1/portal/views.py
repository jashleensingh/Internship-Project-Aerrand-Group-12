"""Browser portal (Jashleen). Pages that talk to the real /dashboard and /v1 endpoints.

Everything the portal does goes through the same API a customer would use; nothing here changes the rules.
Extras:
  * `track_page`    the customer-facing live tracking page (/track/<errand id>), no sign-in, safe fields only.
  * `asset`         serves the portal's own files (app.css, app.js, map.js, map.css) and the bundled Leaflet.
  * `SimulateView`  a test-mode stand-in for the Aerrander phone app, moves the driver (only when DEBUG is on).
"""
import math
import uuid
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.response import Response

from api_v1.booking.models import Errand
from api_v1.common.dashboard import DashboardView
from api_v1.common.errors import ApiError
from api_v1.tracking import services as tracking

HERE = Path(__file__).parent
PAGE = HERE / "index.html"
TRACK_PAGE = HERE / "track.html"
ASSETS = {"leaflet.js": "text/javascript", "leaflet.css": "text/css", "map.js": "text/javascript",
          "map.css": "text/css", "app.css": "text/css", "app.js": "text/javascript", "LICENSE-leaflet.txt": "text/plain"}
VENDORED = {"leaflet.js", "leaflet.css", "LICENSE-leaflet.txt"}   # never change, so the browser may keep them

# status -> the next thing the Aerrander app would report
NEXT_EVENT = {"broadcasted": "accepted", "accepted": "arrived_pickup", "arrived": "picked_up",
              "picked_up": "in_transit", "in_transit": "arrived_dropoff", "arrived_dropoff": "delivered"}
ENGAGED = ("accepted", "arrived", "picked_up", "in_transit", "arrived_dropoff")


def _page(path):
    return HttpResponse(path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})


@ensure_csrf_cookie
def index(request):
    return _page(PAGE)


def track_page(request, errand_id):
    """Customer page. The errand id is the token (same rule as GET /v1/errands/<id>/public)."""
    return _page(TRACK_PAGE)


def asset(request, name):
    if name not in ASSETS:
        raise Http404()
    return HttpResponse((HERE / "assets" / name).read_bytes(), content_type=ASSETS[name] + "; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=86400" if name in VENDORED else "no-cache"})


def _along(a, b, f):
    return float(a["lat"]) + (float(b["lat"]) - float(a["lat"])) * f, float(a["lng"]) + (float(b["lng"]) - float(a["lng"])) * f


def _bearing(a, b):
    la1, la2, dl = math.radians(float(a["lat"])), math.radians(float(b["lat"])), math.radians(float(b["lng"]) - float(a["lng"]))
    y, x = math.sin(dl) * math.cos(la2), math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360)


class SimulateView(DashboardView):
    """POST /portal/simulate/<errand_id>

    {}                  move the errand to its next status, as the Aerrander app would
    {"progress": 0.4}   only move the driver to 40% of the way from pickup to drop-off (while on the road)
    """

    def post(self, request, errand_id):
        if not settings.DEBUG:
            raise ApiError(404, "not_found", "Not found.")
        e = Errand.objects.filter(pk=errand_id, business=self.business).first() if _is_uuid(errand_id) else None
        if e is None:
            raise ApiError(404, "errand_not_found", "No errand with that id.")
        heading = _bearing(e.pickup, e.dropoff)
        progress = request.data.get("progress") if isinstance(request.data, dict) else None
        if progress is not None:
            try:
                f = min(1.0, max(0.0, float(progress)))
            except (TypeError, ValueError):
                raise ApiError(400, "validation_failed", "progress must be a number between 0 and 1.")
            if e.status not in ("picked_up", "in_transit"):
                raise ApiError(409, "invalid_transition", f"The driver can't be moved while the errand is '{e.status}'.",
                               current_status=e.status)
            lat, lng = _along(e.pickup, e.dropoff, f)
            tracking.update_location(e.id, lat, lng, heading)
            return Response({"errand_id": str(e.id), "status": e.status, "progress": f})
        event = NEXT_EVENT.get(e.status)
        if event is None:
            raise ApiError(409, "invalid_transition", f"Nothing further to simulate while the errand is '{e.status}'.",
                           current_status=e.status)
        e = tracking.apply_event(e.id, event)
        if e.status in ENGAGED:     # park the driver where the Aerrander app would report them
            if e.status == "accepted":      # a couple of km away, on the way to the pickup
                lat, lng = float(e.pickup["lat"]) - .012, float(e.pickup["lng"]) - .014
            elif e.status in ("arrived", "picked_up"):
                lat, lng = float(e.pickup["lat"]), float(e.pickup["lng"])
            elif e.status == "in_transit":
                lat, lng = _along(e.pickup, e.dropoff, .1)
            else:
                lat, lng = float(e.dropoff["lat"]), float(e.dropoff["lng"])
            tracking.update_location(e.id, lat, lng, heading)
        return Response({"errand_id": str(e.id), "event": event, "status": e.status})


def _is_uuid(v):
    try:
        uuid.UUID(str(v))
        return True
    except ValueError:
        return False
