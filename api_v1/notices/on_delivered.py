"""Notification when a delivery is completed (Ashwin)."""
from .services import notify


def on_delivered(errand):
    ref = f" ({errand.reference})" if errand.reference else ""
    notify(errand.business, "errand_delivered", f"Delivered{ref}", f"Delivered to {errand.dropoff['label']}.", errand.id)
