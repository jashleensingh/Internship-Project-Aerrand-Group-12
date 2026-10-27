from django.db import models

from api_v1.common.ids import ntf_id


class Notification(models.Model):
    """In-app notification shown in the business dashboard (the realtime push is in common.realtime)."""

    id = models.CharField(max_length=40, primary_key=True, default=ntf_id, editable=False)
    business = models.ForeignKey("common.Business", on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30)       # errand_created | errand_cancelled | errand_delivered
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=500, blank=True, default="")
    errand_id = models.CharField(max_length=40, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
