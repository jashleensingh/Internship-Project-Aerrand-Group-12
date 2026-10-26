import threading
from decimal import Decimal

from django.db import connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from api_v1.booking.models import Errand
from api_v1.common.testing import ApiTestMixin, make_business, make_key, single_body
from api_v1.payments import services
from api_v1.payments.models import Wallet, WalletTransaction
from api_v1.tracking import services as tr


class WalletTests(ApiTestMixin, TestCase):
    def fund(self, amount="100.00"):
        services.credit(self.business, Decimal(amount), "funds_added")

    def test_wallet_booking_debits_once_and_marks_paid(self):
        self.fund()
        r = self.book_single("W1", payment={"method": "wallet"})
        self.assertEqual(r.status_code, 201, r.content)
        e = Errand.objects.get()
        self.assertEqual((e.status, e.payment_status), ("broadcasted", True))
        self.assertEqual(r.json()["payment"]["status"], "paid")
        self.assertEqual(services.get_wallet(self.business).balance, Decimal("100.00") - e.charge_total)
        self.assertEqual(WalletTransaction.objects.filter(type="errand_charge").count(), 1)

    def test_insufficient_funds_402_and_nothing_left_behind(self):
        r = self.book_single("W2", payment={"method": "wallet"})
        self.assertEqual(r.status_code, 402)
        e = r.json()["error"]
        self.assertEqual(e["code"], "insufficient_funds")
        self.assertIn("required", e)
        self.assertEqual(e["available"], "0.00")
        self.assertEqual(Errand.objects.count(), 0)                  # whole booking rolled back
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_test_key_never_moves_money(self):
        _, h = make_key(self.business, "test")
        r = self.book_single("W3", headers=h, payment={"method": "wallet"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(services.get_wallet(self.business).balance, Decimal("0.00"))
        self.assertEqual(Errand.objects.get().payment["status"], "paid")

    def test_multi_stop_wallet_debit_is_one_charge(self):
        from api_v1.common.testing import multi_body, multi_quote_body
        self.fund()
        q = self.post("/v1/quotes", multi_quote_body()).json()
        r = self.post("/v1/errands", multi_body(q["quote_id"], payment={"method": "wallet"}),
                      {**self.h, "HTTP_IDEMPOTENCY_KEY": "mw"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(WalletTransaction.objects.filter(type="errand_charge").count(), 1)
        self.assertEqual(services.get_wallet(self.business).balance, Decimal("100.00") - Decimal(str(q["chargeTotal"])))
        self.assertEqual(Errand.objects.filter(payment_status=True).count(), 2)

    def test_wallet_endpoint_and_topup_limits(self):
        self.fund("25.00")
        j = self.get("/v1/wallet").json()
        self.assertEqual(j["balance"], "25.00")
        c = APIClient()
        c.force_login(self.business.owner)
        self.assertEqual(c.post("/dashboard/wallet", {"amount": 5000}, format="json").status_code, 400)
        self.assertEqual(c.post("/dashboard/wallet", {"amount": 10}, format="json").status_code, 201)
        self.assertEqual(c.get("/dashboard/wallet").json()["balance"], "35.00")

    def test_database_refuses_negative_balance(self):
        from django.db import IntegrityError, transaction
        w = services.get_wallet(self.business)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(pk=w.pk).update(balance=Decimal("-1.00"))


class CancelTests(ApiTestMixin, TestCase):
    def booked(self, ref, method="wallet"):
        services.credit(self.business, Decimal("100.00"), "funds_added")
        return self.book_single(ref, idem=f"i-{ref}", payment={"method": method}).json()["errand_id"]

    def cancel(self, eid, reason=None):
        return self.post(f"/v1/errands/{eid}/cancel", {"reason": reason} if reason else {})

    def test_cancel_before_dispatch_full_refund_no_fee(self):
        eid = self.booked("X1")
        before = services.get_wallet(self.business).balance
        r = self.cancel(eid, "customer changed mind")
        self.assertEqual(r.status_code, 200, r.content)
        j = r.json()
        self.assertEqual(j["status"], "cancelled")
        self.assertEqual(j["cancellation"]["fee"], "0.00")
        self.assertEqual(Decimal(j["cancellation"]["refund"]), Errand.objects.get().price)
        self.assertEqual(services.get_wallet(self.business).balance, Decimal("100.00"))
        self.assertGreater(Decimal("100.00"), before)

    def test_cancel_after_accept_charges_fee(self):
        eid = self.booked("X2")
        tr.apply_event(eid, "accepted")
        j = self.cancel(eid).json()
        e = Errand.objects.get()
        self.assertEqual(j["cancellation"]["fee"], "4.00")
        self.assertEqual(Decimal(j["cancellation"]["refund"]), e.price - Decimal("4.00"))
        self.assertEqual(services.get_wallet(self.business).balance, Decimal("100.00") - Decimal("4.00"))

    def test_double_cancel_refunds_once(self):
        eid = self.booked("X3")
        self.assertEqual(self.cancel(eid).status_code, 200)
        r = self.cancel(eid)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "cancel_not_allowed"))
        self.assertEqual(WalletTransaction.objects.filter(type="errand_refund").count(), 1)
        self.assertEqual(services.get_wallet(self.business).balance, Decimal("100.00"))

    def test_too_late_when_at_the_door_or_delivered(self):
        eid = self.booked("X4")
        for ev in ("accepted", "arrived_pickup", "in_transit", "arrived_dropoff"):
            tr.apply_event(eid, ev)
        r = self.cancel(eid)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "cancel_not_allowed"))
        tr.apply_event(eid, "delivered")
        self.assertEqual(self.cancel(eid).status_code, 409)

    def test_invoice_errand_cancels_without_wallet_refund(self):
        eid = self.book_single("X5").json()["errand_id"]
        j = self.cancel(eid).json()
        self.assertEqual(j["cancellation"]["refund"], "0.00")
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_cancel_is_tenant_isolated_and_scoped(self):
        eid = self.booked("X6")
        _, h2 = make_key(make_business("Beta"))
        self.assertEqual(self.post(f"/v1/errands/{eid}/cancel", {}, h2).status_code, 404)
        _, ro = make_key(self.business, scopes=["errands:read"])
        r = self.post(f"/v1/errands/{eid}/cancel", {}, ro)
        self.assertEqual((r.status_code, r.json()["error"]["required_scope"]), (403, "errands:cancel"))

    def test_one_stop_of_a_route_cancels_on_its_own(self):
        from api_v1.common.testing import multi_body, multi_quote_body
        services.credit(self.business, Decimal("100.00"), "funds_added")
        q = self.post("/v1/quotes", multi_quote_body()).json()
        j = self.post("/v1/errands", multi_body(q["quote_id"], payment={"method": "wallet"}),
                      {**self.h, "HTTP_IDEMPOTENCY_KEY": "mc"}).json()
        first, second = j["stops"][0], j["stops"][1]
        self.assertEqual(self.cancel(first["errand_id"]).status_code, 200)
        self.assertEqual(Errand.objects.get(pk=second["errand_id"]).status, "broadcasted")
        self.assertEqual(self.cancel(first["errand_id"]).status_code, 409)     # already cancelled


class WalletRaceTests(TransactionTestCase):
    """Many bookings at once against a small balance: the wallet can never overspend."""

    def test_concurrent_bookings_cannot_overspend(self):
        from django.core.cache import cache
        cache.clear()
        b = make_business("Racers")
        _, h = make_key(b)
        c = APIClient()
        quotes = []
        for _ in range(8):
            r = c.post("/v1/quotes", {"pickup": {"lat": 42.3149, "lng": -83.0364}, "stops": [
                {"lat": 42.3201, "lng": -83.0187, "parcels": {"medium": 1}}]}, format="json", **h)
            quotes.append(r.json())
        charge = Decimal(str(quotes[0]["chargeTotal"]))
        services.credit(b, charge * 3 + Decimal("0.50"), "funds_added")      # enough for exactly three
        results = []

        def go(i):
            try:
                body = single_body(quotes[i]["quote_id"], reference=f"R{i}", payment={"method": "wallet"})
                r = APIClient().post("/v1/errands", body, format="json", HTTP_IDEMPOTENCY_KEY=f"race-{i}", **h)
                results.append(r.status_code)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        ok = results.count(201)
        self.assertEqual(ok + results.count(402), 8, results)
        self.assertEqual(ok, 3, results)
        bal = services.get_wallet(b).balance
        self.assertEqual(bal, Decimal("0.50"))
        self.assertEqual(WalletTransaction.objects.filter(type="errand_charge").count(), 3)
        self.assertEqual(Errand.objects.filter(payment_status=True).count(), 3)
        self.assertEqual(Errand.objects.count(), 3)    # the 402s left no errand behind
