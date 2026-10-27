from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from api_v1.booking.models import Errand
from api_v1.common.errors import ApiError
from api_v1.common.testing import ApiTestMixin, make_business, make_key, multi_body, multi_quote_body
from api_v1.payments.services import credit
from api_v1.tracking import services as tr


class TrackingTests(ApiTestMixin, TestCase):
    def booked(self, ref="T1"):
        credit(self.business, Decimal("100.00"), "funds_added")
        return self.book_single(ref, idem=f"i-{ref}", payment={"method": "wallet"}).json()["errand_id"]

    def track(self, eid):
        return self.get(f"/v1/errands/{eid}/tracking").json()

    def test_driver_is_null_until_accepted_then_fills_in(self):
        eid = self.booked()
        d = self.track(eid)["data"]
        self.assertEqual((d["status"], d["is_accepted"], d["driver"], d["driver_location"]),
                         ("broadcasted", False, None, None))
        tr.apply_event(eid, "accepted")
        tr.update_location(eid, 42.3110, -83.0250, 118.4)
        d = self.track(eid)["data"]
        self.assertTrue(self.track(eid)["status"])
        self.assertEqual((d["status"], d["is_accepted"], d["driver"]["name"]), ("accepted", True, "Sam O."))
        self.assertEqual(d["driver_location"]["lat"], 42.3110)
        self.assertEqual(d["timeline"][0]["state"], "AERRANDER_ASSIGNED")
        self.assertEqual(d["delivery_code"], Errand.objects.get().delivery_code)

    def test_full_journey_timeline_and_proof_of_delivery(self):
        eid = self.booked()
        for ev in ("accepted", "arrived_pickup", "in_transit", "arrived_dropoff", "delivered"):
            tr.apply_event(eid, ev)
        d = self.track(eid)["data"]
        self.assertEqual([t["state"] for t in d["timeline"]],
                         ["AERRANDER_ASSIGNED", "AT_PICKUP_LOADING", "ROUTE_IN_PROGRESS", "AT_DROPOFF", "DELIVERED"])
        self.assertEqual(d["status"], "delivered")
        self.assertIn("photo_url", d["proof_of_delivery"])
        self.assertIsNotNone(d["completed_at"])

    def test_events_cannot_skip_or_repeat(self):
        eid = self.booked()
        with self.assertRaises(ApiError) as cm:
            tr.apply_event(eid, "delivered")
        self.assertEqual(cm.exception.code, "invalid_transition")
        tr.apply_event(eid, "accepted")
        with self.assertRaises(ApiError):
            tr.apply_event(eid, "accepted")

    def test_full_record_has_extra_fields(self):
        eid = self.booked()
        j = self.get(f"/v1/errands/{eid}").json()
        for k in ("payment_status", "distance_km", "cancellation", "pricing", "pickup", "dropoff", "timeline"):
            self.assertIn(k, j)
        self.assertTrue(j["payment_status"])
        self.assertIsNone(j["cancellation"])

    def test_batch_stops_only_on_full_record(self):
        credit(self.business, Decimal("100.00"), "funds_added")
        q = self.post("/v1/quotes", multi_quote_body()).json()
        j = self.post("/v1/errands", multi_body(q["quote_id"], payment={"method": "wallet"}),
                      {**self.h, "HTTP_IDEMPOTENCY_KEY": "bt"}).json()
        a, b = j["stops"][0]["errand_id"], j["stops"][1]["errand_id"]
        tr.apply_event(a, "accepted")
        self.assertEqual(self.track(a)["data"]["batch"], {"id": j["batch_id"], "index": 0, "size": 2})
        self.assertEqual(self.track(b)["data"]["status"], "broadcasted")        # each stop moves on its own
        full = self.get(f"/v1/errands/{a}").json()["batch"]
        self.assertEqual(len(full["stops"]), 2)
        self.assertEqual(full["total"], str(j["pricing"]["charge_total"]))
        self.assertEqual(Decimal(full["paid_total"]), Decimal(full["total"]))

    def test_public_endpoint_has_no_key_and_hides_private_fields(self):
        eid = self.booked()
        tr.apply_event(eid, "accepted")
        tr.update_location(eid, 42.3110, -83.0250)
        r = APIClient().get(f"/v1/errands/{eid}/public")           # no API key at all
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["success"])
        d = j["data"]
        self.assertEqual(d["driver"]["plate_number"], "CXYZ 123")
        self.assertEqual((d["driver_lat"], d["driver_lng"]), ("42.311", "-83.025"))
        blob = r.content.decode()
        for secret in (Errand.objects.get().delivery_code, "charge_total", "phone_number", "+1519", "pricing"):
            self.assertNotIn(secret, blob)
        self.assertEqual(APIClient().get("/v1/errands/not-a-uuid/public").status_code, 404)

    def test_tracking_is_tenant_isolated(self):
        eid = self.booked()
        _, h2 = make_key(make_business("Beta"))
        for path in (f"/v1/errands/{eid}", f"/v1/errands/{eid}/tracking"):
            r = self.get(path, h2)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "errand_not_found"))

    def test_test_key_cannot_see_live_errands(self):
        eid = self.booked()
        _, test_h = make_key(self.business, "test")
        self.assertEqual(self.get(f"/v1/errands/{eid}/tracking", test_h).status_code, 404)

    def test_simulate_driver_command(self):
        eid = self.booked()
        call_command("simulate_driver", eid, "all")
        self.assertEqual(Errand.objects.get(pk=eid).status, "delivered")
