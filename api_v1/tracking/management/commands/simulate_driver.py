"""Play the Aerrander app for one errand, so tracking and webhooks can be shown without a phone.

    python manage.py simulate_driver <errand_id> accepted
    python manage.py simulate_driver <errand_id> location --lat 42.3110 --lng -83.0250 --heading 118
    python manage.py simulate_driver <errand_id> all          # walks the whole journey
"""
from django.core.management.base import BaseCommand, CommandError

from api_v1.common.errors import ApiError
from api_v1.tracking import services


class Command(BaseCommand):
    help = "Simulate the driver app: accepted, arrived_pickup, picked_up, in_transit, arrived_dropoff, delivered, location, all"

    def add_arguments(self, parser):
        parser.add_argument("errand_id")
        parser.add_argument("event")
        parser.add_argument("--lat", type=float)
        parser.add_argument("--lng", type=float)
        parser.add_argument("--heading", type=float)

    def handle(self, *args, **o):
        try:
            if o["event"] == "location":
                services.update_location(o["errand_id"], o["lat"], o["lng"], o["heading"])
                self.stdout.write("location updated")
            else:
                events = list(services.EVENTS) if o["event"] == "all" else [o["event"]]
                for ev in events:
                    e = services.apply_event(o["errand_id"], ev)
                    self.stdout.write(f"{ev} -> {e.status}")
        except ApiError as err:
            raise CommandError(f"{err.code}: {err.message}")
