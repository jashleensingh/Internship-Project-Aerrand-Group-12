"""Notification when a delivery or route is created (Jashleen)."""
from .services import notify


def on_created(errands):
    first = errands[0]
    if len(errands) == 1:
        title = f"Delivery created{' (' + first.reference + ')' if first.reference else ''}"
        body = f"To {first.dropoff['label']}. Total ${first.charge_total}."
    else:
        title = f"Route created: {len(errands)} stops"
        body = f"One pickup, {len(errands)} drop-offs. Total ${first.charge_total}."
    notify(first.business, "errand_created", title, body, first.id)
