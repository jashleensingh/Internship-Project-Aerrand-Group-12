"""Notification core (Pratyush). The per-event wording lives in hooks.py, one function per owner."""
from django.utils import timezone

from api_v1.common.realtime import push_realtime

from .models import Notification


def notify(business, kind, title, body="", errand_id=""):
    n = Notification.objects.create(business=business, kind=kind, title=title, body=body, errand_id=str(errand_id))
    push_realtime(f"business/{business.id}/notifications", {"id": n.id, "kind": kind, "title": title})
    return n


def mark_read(business, notification_id):
    return Notification.objects.filter(pk=notification_id, business=business, read_at__isnull=True).update(
        read_at=timezone.now())
