"""Create sample businesses so the API can be tried on a laptop.   python manage.py seed_data

Prints a live key and a test key for the approved business ONCE (only hashes are stored)."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from api_v1.common.models import Business
from api_v1.keys import services as keys
from api_v1.payments import services as pay

PASSWORD = "Welcome123!"


class Command(BaseCommand):
    help = "Create sample businesses, a wallet balance and API keys"

    def handle(self, *args, **opts):
        for username, name, status in (("acme", "Acme Co.", "approved"), ("newco", "Newco (awaiting approval)", "awaiting_documents")):
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password(PASSWORD)
                user.save()
            Business.objects.get_or_create(owner=user, defaults={"name": name, "approval_status": status})
        acme = Business.objects.get(owner__username="acme")
        if pay.get_wallet(acme).balance == 0:
            pay.credit(acme, Decimal("200.00"), "funds_added", note="Seed balance")
        _, live = keys.issue(acme, "Local live key", "live")
        _, test = keys.issue(acme, "Local test key", "test")
        self.stdout.write(f"Sign in to /dashboard/login as acme / {PASSWORD}  (newco is not approved yet)")
        self.stdout.write(f"live key: {live}")
        self.stdout.write(f"test key: {test}")
