from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from api_v1.common.testing import ApiTestMixin, make_business
from api_v1.notices.models import Notification
from api_v1.payments.services import credit
from api_v1.tracking import services as tr


class NotificationTests(ApiTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.dash = APIClient()
        self.dash.force_login(self.business.owner)
        credit(self.business, Decimal("100"), "funds_added")

    def test_create_notifies(self):
        self.book_single("N1")
        n = self.dash.get("/dashboard/notifications").json()
        self.assertEqual(n["unread"], 1)
        self.assertEqual(n["data"][0]["kind"], "errand_created")
        self.assertIn("N1", n["data"][0]["title"])

    def test_cancel_notifies_with_fee_and_reason(self):
        eid = self.book_single("N2", payment={"method": "wallet"}).json()["errand_id"]
        tr.apply_event(eid, "accepted")
        self.post(f"/v1/errands/{eid}/cancel", {"reason": "customer changed mind"})
        n = Notification.objects.filter(kind="errand_cancelled").get()
        self.assertEqual(n.errand_id, eid)
        self.assertIn("Fee $4.00", n.body)
        self.assertIn("customer changed mind", n.body)

    def test_delivery_notifies(self):
        eid = self.book_single("N3", payment={"method": "wallet"}).json()["errand_id"]
        for ev in ("accepted", "arrived_pickup", "in_transit", "arrived_dropoff", "delivered"):
            tr.apply_event(eid, ev)
        self.assertEqual(Notification.objects.filter(kind="errand_delivered").count(), 1)

    def test_mark_read_and_unread_filter(self):
        self.book_single("N4")
        nid = self.dash.get("/dashboard/notifications").json()["data"][0]["id"]
        self.assertEqual(self.dash.post(f"/dashboard/notifications/{nid}/read").status_code, 200)
        self.assertEqual(self.dash.post(f"/dashboard/notifications/{nid}/read").status_code, 200)   # idempotent
        j = self.dash.get("/dashboard/notifications?unread=1").json()
        self.assertEqual((j["unread"], j["data"]), (0, []))

    def test_notifications_are_private_to_the_business(self):
        self.book_single("N5")
        nid = Notification.objects.get().id
        other = APIClient()
        other.force_login(make_business("Beta").owner)
        self.assertEqual(other.get("/dashboard/notifications").json()["data"], [])
        self.assertEqual(other.post(f"/dashboard/notifications/{nid}/read").status_code, 404)
        self.assertEqual(APIClient().get("/dashboard/notifications").status_code, 401)

    def test_a_failed_booking_leaves_no_notification(self):
        self.book_single("N6", payment={"method": "wallet"})       # 100 funded: succeeds
        Notification.objects.all().delete()
        from api_v1.payments.models import Wallet
        Wallet.objects.update(balance=Decimal("0"))
        r = self.book_single("N7", idem="n7", payment={"method": "wallet"})
        self.assertEqual(r.status_code, 402)
        self.assertEqual(Notification.objects.count(), 0)
