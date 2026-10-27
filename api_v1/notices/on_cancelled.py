"""Notification when a delivery is cancelled (Ashwin). The business partner asked for this one specifically."""
from .services import notify


def on_cancelled(errand, cancellation):
    ref = f" ({errand.reference})" if errand.reference else ""
    body = f"Fee ${cancellation['fee']}, refunded ${cancellation['refund']}."
    if cancellation.get("reason"):
        body += f" Reason: {cancellation['reason']}"
    notify(errand.business, "errand_cancelled", f"Delivery cancelled{ref}", body, errand.id)
