"""Deliver pending webhooks.   python manage.py run_dispatcher            (loops every 5 s)
                              python manage.py run_dispatcher --once     (one pass, for cron or tests)"""
import time

from django.core.management.base import BaseCommand

from api_v1.reliability.dispatcher import dispatch_pending


class Command(BaseCommand):
    help = "Send pending webhook deliveries"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=5.0)

    def handle(self, *args, **o):
        while True:
            self.stdout.write(str(dispatch_pending()))
            if o["once"]:
                return
            time.sleep(o["interval"])
