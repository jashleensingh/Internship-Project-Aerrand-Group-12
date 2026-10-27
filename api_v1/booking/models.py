import uuid

from django.db import models
from django.db.models import Q

from api_v1.common.ids import quote_id as new_quote_id, delivery_id as new_delivery_id


class Quote(models.Model):
    """A priced, time-limited quote. `result` is exactly what the API returned; booking reads the price from it,
    never from the client."""

    id = models.CharField(max_length=24, primary_key=True, default=new_quote_id, editable=False)
    business = models.ForeignKey("common.Business", on_delete=models.CASCADE, related_name="quotes")
    environment = models.CharField(max_length=4)
    kind = models.CharField(max_length=8, choices=[("route", "route"), ("parcel", "parcel")])
    fingerprint = models.CharField(max_length=64)   # hash of the inputs; booking must match it
    result = models.JSONField()
    amount_cents = models.IntegerField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)   # a quote books once
    created_at = models.DateTimeField(auto_now_add=True)


class Errand(models.Model):
    """One delivery record. A multi-stop route is N Errands (one per stop) sharing batch_id."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)           # errand_id
    delivery_id = models.CharField(max_length=24, default=new_delivery_id, editable=False)
    business = models.ForeignKey("common.Business", on_delete=models.CASCADE, related_name="errands")
    environment = models.CharField(max_length=4)
    quote = models.ForeignKey(Quote, null=True, on_delete=models.SET_NULL, related_name="errands")

    reference = models.CharField(max_length=255, blank=True, default="")
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    batch_index = models.PositiveSmallIntegerField(null=True, blank=True)
    batch_size = models.PositiveSmallIntegerField(null=True, blank=True)
    batch_reference = models.CharField(max_length=255, blank=True, default="")

    status = models.CharField(max_length=20, default="pending_payment", db_index=True)
    delivery_code = models.CharField(max_length=6)
    vehicle_type = models.CharField(max_length=12, blank=True, default="")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    delivery_note = models.CharField(max_length=500, blank=True, default="")
    parcel = models.JSONField(null=True, blank=True)          # single delivery
    parcels = models.JSONField(default=dict)                  # per stop counts {"small": 2}
    metadata = models.JSONField(default=dict)

    pickup = models.JSONField()     # {label, lat, lng, contact{name, phone_number, instructions, preference, email}}
    dropoff = models.JSONField()
    dropoff_instruction_id = models.UUIDField(default=uuid.uuid4)
    pickup_instruction_id = models.UUIDField(default=uuid.uuid4)
    checklist = models.JSONField(default=list)   # [{"id", "title"}]
    tags = models.JSONField(default=list)

    # money: route_price / hst / charge_total are the whole route; price is this stop's share
    route_price = models.DecimalField(max_digits=10, decimal_places=2)
    hst = models.DecimalField(max_digits=10, decimal_places=2)
    charge_total = models.DecimalField(max_digits=10, decimal_places=2)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    distance_km = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    payment = models.JSONField(default=dict)    # {method, status, checkout_url, reference, email}
    payment_status = models.BooleanField(default=False)

    # live state (the Aerrander app writes these; see tracking.services)
    driver = models.JSONField(null=True, blank=True)
    driver_location = models.JSONField(null=True, blank=True)
    timeline = models.JSONField(default=list)
    proof_of_delivery = models.JSONField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancellation = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "batch_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "environment", "reference"],
                condition=~Q(reference=""),
                name="uniq_reference_per_business_env",
            ),
        ]

    @property
    def is_multi(self):
        return self.batch_id is not None
