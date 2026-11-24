from decimal import Decimal

from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from api_v1.booking.models import Errand
from api_v1.common.testing import ApiTestMixin, make_business
from api_v1.payments.services import credit


class PortalTests(ApiTestMixin, TestCase):
    def booked(self):
        credit(self.business, Decimal("100.00"), "funds_added")
        return self.book_single("P1", idem="p-1", payment={"method": "wallet"}).json()["errand_id"]

    def test_page_loads_and_hands_out_the_csrf_cookie(self):
        r = Client().get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Aerrand Developers", r.content.decode())
        self.assertIn("csrftoken", r.cookies)

    def test_browser_session_calls_need_the_csrf_token(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.business.owner)
        r = c.post("/dashboard/api-keys", {"name": "x"}, content_type="application/json")
        self.assertEqual(r.status_code, 403)               # session cookie alone is not enough

    @override_settings(DEBUG=True)   # the test runner forces DEBUG off; the simulator only works with it on
    def test_simulate_walks_the_journey_and_is_tenant_scoped(self):
        eid = self.booked()
        c = APIClient()
        c.force_login(self.business.owner)
        seen = []
        for _ in range(6):
            r = c.post(f"/portal/simulate/{eid}", {}, format="json")
            self.assertEqual(r.status_code, 200)
            seen.append(r.json()["status"])
        self.assertEqual(seen, ["accepted", "arrived", "picked_up", "in_transit", "arrived_dropoff", "delivered"])
        self.assertEqual(c.post(f"/portal/simulate/{eid}", {}, format="json").status_code, 409)   # nothing left
        other = APIClient()
        other.force_login(make_business("Beta").owner)
        self.assertEqual(other.post(f"/portal/simulate/{eid}", {}, format="json").status_code, 404)

    def test_simulate_is_off_when_debug_is_off(self):
        eid = self.booked()
        c = APIClient()
        c.force_login(self.business.owner)
        with override_settings(DEBUG=False):
            self.assertEqual(c.post(f"/portal/simulate/{eid}", {}, format="json").status_code, 404)

    def test_customer_page_and_map_files_are_served_and_nothing_else(self):
        c = Client()
        r = c.get("/track/anything")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Track your delivery", r.content.decode())
        for name in ("leaflet.js", "leaflet.css", "map.js", "map.css", "app.css", "app.js"):
            self.assertEqual(c.get(f"/portal/assets/{name}").status_code, 200, name)
        for name in ("views.py", "..%2Fviews.py", "tests.py", "index.html"):
            self.assertEqual(c.get(f"/portal/assets/{name}").status_code, 404, name)

    @override_settings(DEBUG=True)
    def test_simulator_puts_the_driver_on_the_map(self):
        eid = self.booked()
        c = APIClient()
        c.force_login(self.business.owner)
        step = lambda body=None: c.post(f"/portal/simulate/{eid}", body or {}, format="json")
        self.assertEqual(step({"progress": 0.5}).status_code, 409)       # not on the road yet
        self.assertIsNone(Errand.objects.get(pk=eid).driver_location)
        step()                                                            # accepted: a couple of km from pickup
        loc = Errand.objects.get(pk=eid).driver_location
        self.assertIsNotNone(loc)
        pickup = Errand.objects.get(pk=eid).pickup
        self.assertNotEqual(round(loc["lat"], 3), round(float(pickup["lat"]), 3))
        step(); step()                                                    # at pickup, picked up
        loc = Errand.objects.get(pk=eid).driver_location
        self.assertEqual(round(loc["lat"], 4), round(float(pickup["lat"]), 4))
        step()                                                            # in transit: a little way along
        self.assertEqual(step({"progress": 0.5}).status_code, 200)
        loc = Errand.objects.get(pk=eid).driver_location
        drop = Errand.objects.get(pk=eid).dropoff
        self.assertAlmostEqual(loc["lat"], (float(pickup["lat"]) + float(drop["lat"])) / 2, places=4)
        self.assertEqual(step({"progress": "far"}).status_code, 400)
        step()                                                            # arrived at drop-off
        loc = Errand.objects.get(pk=eid).driver_location
        self.assertEqual(round(loc["lng"], 4), round(float(drop["lng"]), 4))
