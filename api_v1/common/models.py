from django.conf import settings
from django.db import models

from .ids import biz_id


class Business(models.Model):
    """Stand-in for Aerrand's existing business account. In the real repo this is the existing model;
    only `approved` (and its name) are used by the /v1 module."""

    APPROVED = "approved"
    AWAITING = "awaiting_documents"
    REJECTED = "rejected"

    id = models.CharField(max_length=40, primary_key=True, default=biz_id, editable=False)
    name = models.CharField(max_length=200)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="business")
    approval_status = models.CharField(
        max_length=24,
        choices=[(APPROVED, "approved"), (AWAITING, "awaiting documents"), (REJECTED, "rejected")],
        default=AWAITING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def approved(self):
        return self.approval_status == self.APPROVED

    def __str__(self):
        return self.name
