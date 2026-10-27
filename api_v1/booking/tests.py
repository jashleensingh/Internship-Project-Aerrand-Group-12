from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from api_v1.booking import pricing
from api_v1.booking.models import Errand, Quote
from api_v1.booking.services import split_total
from api_v1.common.testing import (ApiTestMixin, make_business, make_key, multi_body, multi_quote_body,
                                   route_quote_body, single_body, single_quote_body, STOP1, STOP2)
from decimal import Decimal


class PricingTests(TestCase):
    def test_route_quote_shape_and_math(self):
        q = pricing.route_quote((42.3149, -83.0364), [
            {"lat": 42.3201, "lng": -83.0187, "parcels": {"small": 2, "medium": 1}},
            {"lat": 42.2789, "lng": -82.9912, "parcels": {"small": 4}}])
        self.assertEqual(q["dropBaseTotal"], 11.50)          # 8.00 first stop + 3.50 extra stop
        self.assertEqual(q["sizeAddOnTotal"], 2.00)
        self.assertEqual(q["totalCargoUnits"], 4.0)
        self.assertEqual(q["recommendedVehicle"], "motorcycle")
        self.assertAlmostEqual(q["routePrice"] * 1.13, q["chargeTotal"], places=1)
        self.assertEqual(q["amount_cents"], round(q["chargeTotal"] * 100))
        self.assertFalse(q["overVanCapacity"])

    def test_over_van_capacity_flag(self):
        q = pricing.route_quote((42.31, -83.03), [{"lat": 42.32, "lng": -83.02, "parcels": {"xl": 7}}])
        self.assertTrue(q["overVanCapacity"])

    def test_parcel_quote_guard_and_tax(self):
        q = pricing.parcel_quote((42.3149, -83.0364), (42.2789, -82.9912), "medium", False, Decimal("400"))
        self.assertEqual(q["guardFee"], 12.00)               # 3% of declared value
        self.assertEqual(q["itemValueHeld"], 400.0)
        self.assertAlmostEqual(q["hst"], round((q["deliveryFee"] + 12.00) * 0.13, 2), places=2)   # value not taxed
        self.assertAlmostEqual(q["totalDueAtBooking"], q["deliveryFee"] + 12.00 + q["hst"] + 400.0, places=2)
        self.assertTrue(q["breakdown"]["guardActive"])

    def test_weight_maps_to_tier(self):
        self.assertEqual(pricing.size_tier(3), "small")
        self.assertEqual(pricing.size_tier(30), "large")
        self.assertEqual(pricing.size_tier("XL"), "xl")

    def test_split_total_adds_up_exactly(self):
        for total, n in ((Decimal("24.92"), 2), (Decimal("10.00"), 3), (Decimal("0.05"), 5)):
            shares = split_total(total, n)
            self.assertEqual(sum(shares), total)
            self.assertEqual(len(shares), n)


class QuoteApiTests(ApiTestMixin, TestCase):
    def test_route_quote_and_parcel_quote(self):
        r = self.post("/v1/quotes", multi_quote_body())
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["quote_id"].startswith("qt_"))
        self.assertEqual(j["stopCount"], 2)
        p = self.post("/v1/quotes", {"pickup": {"lat": 42.3149, "lng": -83.0364},
                                     "dropoff": {"lat": 42.2789, "lng": -82.9912}, "size": "medium",
                                     "declared_value": 400.0, "scheduled_at": "2026-09-23T15:00:00Z"})
        self.assertEqual(p.status_code, 200)
        self.assertIn("totalDueAtBooking", p.json())

    def test_quote_validation_details(self):
        r = self.post("/v1/quotes", {"pickup": {"lat": 0, "lng": 0}, "stops": []})
        self.assertEqual(r.status_code, 400)
        e = r.json()["error"]
        self.assertEqual(e["code"], "validation_failed")
        self.assertIn("pickup", e["details"])
        self.assertIn("stops", e["details"])

    def test_more_than_five_stops_rejected(self):
        stops = [{"lat": 42.32, "lng": -83.02, "parcels": {"small": 1}}] * 6
        self.assertEqual(self.post("/v1/quotes", route_quote_body(stops)).status_code, 400)


class BookingApiTests(ApiTestMixin, TestCase):
    def test_single_create_matches_partner_shape(self):
        r = self.book_single("SHOP-10432")
        self.assertEqual(r.status_code, 201, r.content)
        j = r.json()
        for k in ("errand_id", "delivery_id", "status", "reference", "delivery_code", "pricing", "payment",
                  "pickup", "dropoff", "tracking", "metadata", "created_at", "scheduled_at"):
            self.assertIn(k, j)
        self.assertEqual(j["status"], "pending_payment")
        self.assertEqual(len(j["delivery_id"]), 24)
        self.assertEqual(len(j["delivery_code"]), 6)
        self.assertEqual(j["payment"], {"status": "unpaid", "method": "invoice", "checkout_url": None, "reference": None})
        self.assertTrue(j["tracking"]["public_url"].endswith(j["errand_id"]))

    def test_price_comes_from_the_quote(self):
        q = self.quote()
        r = self.post("/v1/errands", single_body(q["quote_id"]), {**self.h, "HTTP_IDEMPOTENCY_KEY": "p1"})
        self.assertEqual(r.json()["pricing"]["charge_total"], q["chargeTotal"])
        self.assertEqual(r.json()["pricing"]["route_price"], q["routePrice"])

    def test_client_supplied_price_is_refused(self):
        q = self.quote()
        r = self.post("/v1/errands", single_body(q["quote_id"], price="0.50", charge_total=1),
                      {**self.h, "HTTP_IDEMPOTENCY_KEY": "p2"})
        self.assertEqual(r.status_code, 400)
        d = r.json()["error"]["details"]
        self.assertIn("price", d)
        self.assertIn("charge_total", d)
        self.assertEqual(Errand.objects.count(), 0)

    def test_multi_stop_one_record_per_stop_and_shares_add_up(self):
        q = self.post("/v1/quotes", multi_quote_body()).json()
        r = self.post("/v1/errands", multi_body(q["quote_id"]), {**self.h, "HTTP_IDEMPOTENCY_KEY": "m1"})
        self.assertEqual(r.status_code, 201, r.content)
        j = r.json()
        self.assertEqual(j["stop_count"], 2)
        self.assertEqual(Errand.objects.count(), 2)
        self.assertEqual(len({s["errand_id"] for s in j["stops"]}), 2)
        self.assertEqual(len({s["delivery_code"] for s in j["stops"]}), 2)
        self.assertEqual(sum(Decimal(s["price"]) for s in j["stops"]), Decimal(str(j["pricing"]["charge_total"])))
        self.assertEqual(j["payment"]["covers"], [s["errand_id"] for s in j["stops"]])
        rows = list(Errand.objects.order_by("batch_index"))
        self.assertEqual({r.batch_id for r in rows}.pop().__class__.__name__, "UUID")
        self.assertEqual([(r.batch_index, r.batch_size) for r in rows], [(0, 2), (1, 2)])

    def test_stop_limit_is_five(self):
        stops = [{"reference": f"S{i}", "label": "x", "lat": str(STOP1[0]), "lng": str(STOP1[1]),
                  "parcels": {"small": 1}, "contact": {"name": "A", "phone_number": "+15195550188",
                                                       "preference": "meet_at_door"}} for i in range(6)]
        q = self.post("/v1/quotes", multi_quote_body()).json()
        r = self.post("/v1/errands", multi_body(q["quote_id"], dropoffs=stops), {**self.h, "HTTP_IDEMPOTENCY_KEY": "m2"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("dropoffs", r.json()["error"]["details"])

    def test_quote_expired_used_and_mismatch(self):
        q = self.quote()
        Quote.objects.filter(pk=q["quote_id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        r = self.post("/v1/errands", single_body(q["quote_id"]), {**self.h, "HTTP_IDEMPOTENCY_KEY": "e1"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "quote_expired"))
        ok = self.book_single("A1")
        self.assertEqual(ok.status_code, 201)
        q2 = Quote.objects.latest("created_at")
        again = self.post("/v1/errands", single_body(q2.id, "A2"), {**self.h, "HTTP_IDEMPOTENCY_KEY": "e2"})
        self.assertEqual(again.json()["error"]["code"], "quote_used")
        q3 = self.quote()
        far = single_body(q3["quote_id"], "A3")
        far["dropoff"]["lat"] = "42.2000"      # different address than the quote
        r = self.post("/v1/errands", far, {**self.h, "HTTP_IDEMPOTENCY_KEY": "e3"})
        self.assertEqual(r.json()["error"]["code"], "quote_mismatch")

    def test_changed_parcels_cannot_use_a_cheaper_quote(self):
        q = self.quote()   # one medium parcel
        body = single_body(q["quote_id"], "A4", parcel={"size": "xl", "quantity": 1})
        r = self.post("/v1/errands", body, {**self.h, "HTTP_IDEMPOTENCY_KEY": "e4"})
        self.assertEqual(r.json()["error"]["code"], "quote_mismatch")

    def test_other_business_cannot_use_my_quote(self):
        q = self.quote()
        _, h2 = make_key(make_business("Beta"))
        r = self.post("/v1/errands", single_body(q["quote_id"]), {**h2, "HTTP_IDEMPOTENCY_KEY": "x"})
        self.assertEqual(r.status_code, 404)

    def test_outside_service_area(self):
        far = {"lat": 43.6532, "lng": -79.3832}     # Toronto
        qb = route_quote_body([{**far, "parcels": {"medium": 1}}])
        q = self.post("/v1/quotes", qb).json()
        body = single_body(q["quote_id"], "T1")
        body["dropoff"].update(lat=str(far["lat"]), lng=str(far["lng"]))
        r = self.post("/v1/errands", body, {**self.h, "HTTP_IDEMPOTENCY_KEY": "t1"})
        self.assertEqual(r.status_code, 412)
        e = r.json()["error"]
        self.assertEqual(e["code"], "service_area_unavailable")
        self.assertTrue(e["details"]["pickup"]["inside"])
        self.assertFalse(e["details"]["dropoffs"][0]["inside"])
        self.assertEqual(e["details"]["nearestCity"]["slug"], "windsor")

    def test_over_van_capacity_blocks_booking(self):
        qb = route_quote_body([{"lat": STOP1[0], "lng": STOP1[1], "parcels": {"xl": 7}}])
        q = self.post("/v1/quotes", qb).json()
        self.assertTrue(q["overVanCapacity"])
        body = single_body(q["quote_id"], "V1", parcel={"size": "xl", "quantity": 7})
        r = self.post("/v1/errands", body, {**self.h, "HTTP_IDEMPOTENCY_KEY": "v1"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "route_over_capacity"))

    def test_duplicate_reference_conflict(self):
        self.assertEqual(self.book_single("DUP").status_code, 201)
        r = self.book_single("DUP", idem="other")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "duplicate_reference"))
        self.assertEqual(Errand.objects.count(), 1)

    def test_validation_lists_every_bad_field(self):
        q = self.quote()
        body = single_body(q["quote_id"])
        body["pickup"]["lat"], body["dropoff"]["contact"]["preference"] = "abc", "knock"
        body["vehicle_type"], body["metadata"] = "boat", {"n": 5}
        r = self.post("/v1/errands", body, {**self.h, "HTTP_IDEMPOTENCY_KEY": "bad"})
        d = r.json()["error"]["details"]
        for field in ("pickup.lat", "dropoff.contact.preference", "vehicle_type", "metadata"):
            self.assertIn(field, d)

    def test_metadata_and_reference_round_trip(self):
        r = self.book_single("M-1", metadata={"shopify_order_id": "6712341"})
        self.assertEqual(r.json()["metadata"], {"shopify_order_id": "6712341"})
        self.assertEqual(r.json()["reference"], "M-1")

    def test_xl_parcel_forces_meet_at_curb(self):
        qb = route_quote_body([{"lat": STOP1[0], "lng": STOP1[1], "parcels": {"xl": 1}}])
        q = self.post("/v1/quotes", qb).json()
        body = single_body(q["quote_id"], "XL1", parcel={"size": "xl", "quantity": 1})
        r = self.post("/v1/errands", body, {**self.h, "HTTP_IDEMPOTENCY_KEY": "xl"})
        self.assertEqual(r.json()["dropoff"]["contact"]["preference"], "meet_at_curb")

    def test_service_areas_endpoint(self):
        j = self.get("/v1/service-areas").json()
        self.assertEqual(j["serviceAreas"][0]["slug"], "windsor")
