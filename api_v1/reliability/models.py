from django.db import models

from api_v1.common.ids import evt_id, we_id


class IdempotencyRecord(models.Model):
    """One row per (key, Idempotency-Key). Claimed before work starts, so a retry or double-click cannot run twice."""

    api_key_id = models.CharField(max_length=40)
    idem_key = models.CharField(max_length=120)
    fingerprint = models.CharField(max_length=64)       # sha256(method + path + raw body)
    state = models.CharField(max_length=10, default="processing")   # processing | done
    status_code = models.IntegerField(null=True)
    body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["api_key_id", "idem_key"], name="uniq_idem_per_key")]


class WebhookEndpoint(models.Model):
    id = models.CharField(max_length=40, primary_key=True, default=we_id, editable=False)
    business = models.ForeignKey("common.Business", on_delete=models.CASCADE, related_name="webhook_endpoints")
    environment = models.CharField(max_length=4, default="live")
    url = models.URLField(max_length=500)
    secret = models.CharField(max_length=80)             # whsec_...; needed in clear to sign, shown once
    events = models.JSONField(default=list)              # [] or ["*"] = every event
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def wants(self, event_type):
        return not self.events or "*" in self.events or event_type in self.events


class OutboxEvent(models.Model):
    """Written in the SAME transaction as the change that caused it (outbox pattern), so an event is never lost
    and never sent for a change that rolled back."""

    id = models.CharField(max_length=40, primary_key=True, default=evt_id, editable=False)
    business = models.ForeignKey("common.Business", on_delete=models.CASCADE, related_name="events")
    environment = models.CharField(max_length=4)
    type = models.CharField(max_length=40)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class WebhookDelivery(models.Model):
    STATUSES = [("pending", "pending"), ("delivered", "delivered"), ("failed", "failed")]

    event = models.ForeignKey(OutboxEvent, on_delete=models.CASCADE, related_name="deliveries")
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    status = models.CharField(max_length=10, choices=STATUSES, default="pending", db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    lease_until = models.DateTimeField(null=True, blank=True)    # claimed by one dispatcher at a time
    last_status_code = models.IntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True, default="")
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "endpoint"], name="uniq_delivery_per_endpoint")]
