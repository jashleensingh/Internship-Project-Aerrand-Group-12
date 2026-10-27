from rest_framework.response import Response

from api_v1.common.dashboard import DashboardView
from api_v1.common.errors import ApiError

from . import services


def out(n):
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "errand_id": n.errand_id or None,
            "read": n.read_at is not None, "created_at": n.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")}


class NotificationListView(DashboardView):
    """GET /dashboard/notifications[?unread=1]"""

    def get(self, request):
        qs = self.business.notifications.all()
        if request.query_params.get("unread"):
            qs = qs.filter(read_at__isnull=True)
        return Response({"unread": self.business.notifications.filter(read_at__isnull=True).count(),
                         "data": [out(n) for n in qs[:50]]})


class NotificationReadView(DashboardView):
    """POST /dashboard/notifications/<id>/read"""

    def post(self, request, notification_id):
        if not services.mark_read(self.business, notification_id):
            if not self.business.notifications.filter(pk=notification_id).exists():
                raise ApiError(404, "not_found", "No notification with that id.")
        return Response({"id": notification_id, "read": True})
