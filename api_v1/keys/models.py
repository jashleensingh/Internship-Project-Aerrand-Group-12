from django.db import models

from api_v1.common.ids import key_id

SCOPES = ["quotes:write", "errands:read", "errands:write", "errands:cancel", "wallet:read"]


class ApiKey(models.Model):
    """Only a hash of the key is stored. The plain key is shown once, when it is created."""

    id = models.CharField(max_length=40, primary_key=True, default=key_id, editable=False)
    business = models.ForeignKey("common.Business", on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=120)
    environment = models.CharField(max_length=4, choices=[("live", "live"), ("test", "test")])
    scopes = models.JSONField(default=list)
    key_prefix = models.CharField(max_length=20)             # first 15 chars, safe to show in the dashboard
    key_hash = models.CharField(max_length=64, unique=True)  # HMAC-SHA256 with a server-side pepper
    status = models.CharField(max_length=8, default="active", choices=[("active", "active"), ("revoked", "revoked")])
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
