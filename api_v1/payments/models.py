import uuid

from django.db import models
from django.db.models import Q


class Wallet(models.Model):
    business = models.OneToOneField("common.Business", on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # the database itself refuses a negative balance, even if the code has a bug
        constraints = [models.CheckConstraint(condition=Q(balance__gte=0), name="wallet_balance_non_negative")]


class WalletTransaction(models.Model):
    TYPES = [("errand_charge", "errand_charge"), ("errand_refund", "errand_refund"), ("funds_added", "funds_added")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField(max_length=16, choices=TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)          # negative = money out
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    ref = models.CharField(max_length=80, blank=True, default="")          # errand id or batch id
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
