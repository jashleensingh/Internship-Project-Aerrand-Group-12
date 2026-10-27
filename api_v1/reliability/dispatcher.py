"""Sends pending webhook deliveries. At-least-once: receivers must de-duplicate on the event `id`.

  * a delivery is claimed with a short lease, so two dispatchers never send the same one at the same time
  * 2xx = delivered; anything else (or a network error) = retry later with backoff
  * after MAX_ATTEMPTS the delivery is marked failed (it stays in the table for support to look at)
"""
import json
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import WebhookDelivery
from .signing import sign_payload

BACKOFF = [60, 300, 1800, 7200, 21600]   # seconds before retry 1..5
MAX_ATTEMPTS = 6
LEASE_SECONDS = 60


def body_bytes(payload):
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def urllib_sender(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def dispatch_pending(sender=None, now=None, limit=50):
    sender = sender or urllib_sender
    now = now or timezone.now()
    free = Q(lease_until__isnull=True) | Q(lease_until__lt=now)
    due = (WebhookDelivery.objects.filter(status="pending", next_attempt_at__lte=now).filter(free)
           .select_related("event", "endpoint").order_by("next_attempt_at")[:limit])
    stats = {"delivered": 0, "retry": 0, "failed": 0, "skipped": 0}
    for d in due:
        claimed = (WebhookDelivery.objects.filter(pk=d.pk, status="pending").filter(free)
                   .update(lease_until=now + timedelta(seconds=LEASE_SECONDS)))
        if not claimed:
            stats["skipped"] += 1
            continue
        if not d.endpoint.active:
            WebhookDelivery.objects.filter(pk=d.pk).update(status="failed", last_error="endpoint disabled")
            stats["failed"] += 1
            continue
        body = body_bytes(d.event.payload)
        headers = {"Content-Type": "application/json", "Aerrand-Event-Id": d.event_id,
                   "Aerrand-Signature": sign_payload(d.endpoint.secret, body, int(now.timestamp())),
                   "User-Agent": "Aerrand-Webhooks/1"}
        code, err = None, ""
        try:
            code = sender(d.endpoint.url, body, headers)
        except Exception as ex:   # network error, timeout, bad URL
            err = f"{type(ex).__name__}: {ex}"[:255]
        attempts = d.attempts + 1
        if code is not None and 200 <= code < 300:
            WebhookDelivery.objects.filter(pk=d.pk).update(
                status="delivered", attempts=attempts, last_status_code=code, last_error="",
                delivered_at=now, lease_until=None)
            stats["delivered"] += 1
        elif attempts >= MAX_ATTEMPTS:
            WebhookDelivery.objects.filter(pk=d.pk).update(
                status="failed", attempts=attempts, last_status_code=code, last_error=err or f"HTTP {code}",
                lease_until=None)
            stats["failed"] += 1
        else:
            WebhookDelivery.objects.filter(pk=d.pk).update(
                attempts=attempts, last_status_code=code, last_error=err or f"HTTP {code}", lease_until=None,
                next_attempt_at=now + timedelta(seconds=BACKOFF[attempts - 1]))
            stats["retry"] += 1
    return stats
