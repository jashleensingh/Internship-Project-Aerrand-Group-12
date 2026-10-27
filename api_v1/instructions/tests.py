from django.test import TestCase

from api_v1.booking.models import Errand
from api_v1.common.testing import ApiTestMixin, STOP1
from api_v1.tracking import services as tr


def advance(errand_id, *events):
    for ev in events:
        tr.apply_event(errand_id, ev)


class DropoffTests(ApiTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.book_single("D1").status_code, 201)   # unpaid invoice errand, always editable

    def test_partial_update_matches_partner_shape(self):
        eid = Errand.objects.first().id
        r = self.put(f"/v1/errands/{eid}/dropoff", {"instructions": "Changed: leave with the concierge."})
        self.assertEqual(r.status_code, 200, r.content)
        j = r.json()
        self.assertTrue(j["status"])
        self.assertEqual(j["message"], "Dropoff instruction updated")
        self.assertEqual(set(j["data"]), {"id", "name", "phone_number", "instructions", "preference"})
        self.assertEqual(j["data"]["name"], "Jordan Alvarez")       # untouched fields stay
        self.assertEqual(j["data"]["instructions"], "Changed: leave with the concierge.")

    def test_validation(self):
        eid = Errand.objects.first().id
        for body in ({}, {"preference": "knock"}, {"name": "x" * 300}, {"colour": "red"}):
            r = self.put(f"/v1/errands/{eid}/dropoff", body)
            self.assertEqual(r.status_code, 400, body)
            self.assertEqual(r.json()["error"]["code"], "validation_failed")

    def test_within_1km_only_instructions_can_change(self):
        from api_v1.payments.services import credit
        from decimal import Decimal
        credit(self.business, Decimal("100"), "funds_added")
        eid = self.book_single("D3", idem="d3", payment={"method": "wallet"}).json()["errand_id"]
        advance(eid, "accepted", "arrived_pickup", "in_transit")
        far = self.put(f"/v1/errands/{eid}/dropoff", {"preference": "meet_at_door"})
        self.assertEqual(far.status_code, 200)                      # driver not close yet: all fields editable
        tr.update_location(eid, STOP1[0] + 0.002, STOP1[1], 90)     # ~220 m from the stop
        locked = self.put(f"/v1/errands/{eid}/dropoff", {"preference": "leave_at_door"})
        self.assertEqual(locked.status_code, 409)
        self.assertEqual(locked.json()["error"]["code"], "edit_window_closed")
        self.assertEqual(locked.json()["error"]["details"]["locked_fields"], ["preference"])
        ok = self.put(f"/v1/errands/{eid}/dropoff", {"instructions": "Buzzer is broken, call me."})
        self.assertEqual(ok.status_code, 200)

    def test_nothing_changes_after_delivery_or_cancel(self):
        from api_v1.payments.services import credit
        from decimal import Decimal
        credit(self.business, Decimal("100"), "funds_added")
        eid = self.book_single("D4", idem="d4", payment={"method": "wallet"}).json()["errand_id"]
        advance(eid, "accepted", "arrived_pickup", "in_transit", "arrived_dropoff", "delivered")
        r = self.put(f"/v1/errands/{eid}/dropoff", {"instructions": "too late"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "edit_window_closed"))

    def test_pickup_has_email_and_same_shape(self):
        eid = Errand.objects.first().id
        r = self.put(f"/v1/errands/{eid}/pickup", {"email": "store14@example.com", "instructions": "Dock 3"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["email"], "store14@example.com")
        self.assertEqual(r.json()["message"], "Pickup instruction updated")
        bad = self.put(f"/v1/errands/{eid}/pickup", {"preference": "leave_at_door"})
        self.assertEqual(bad.status_code, 400)

    def test_other_business_gets_404(self):
        from api_v1.common.testing import make_business, make_key
        _, h2 = make_key(make_business("Beta"))
        eid = Errand.objects.first().id
        self.assertEqual(self.put(f"/v1/errands/{eid}/dropoff", {"instructions": "x"}, h2).status_code, 404)

    def test_instructions_reach_the_driver_app_and_webhook_outbox(self):
        from api_v1.reliability.models import OutboxEvent
        eid = Errand.objects.first().id
        self.put(f"/v1/errands/{eid}/dropoff", {"instructions": "new"})
        ev = OutboxEvent.objects.filter(type="errand.dropoff_updated").first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.payload["data"]["dropoff"]["instructions"], "new")


class ChecklistTests(ApiTestMixin, TestCase):
    def test_generate_never_fails(self):
        r = self.post("/v1/checklists/generate", {"description": "65 inch Samsung QLED TV, wall mounted",
                                                  "price": 450.0})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertLessEqual(len(j["checklist"]), 5)
        self.assertTrue(all(len(c) <= 80 for c in j["checklist"]))
        self.assertEqual(j["suggested_size"], "xlarge")
        self.assertTrue(set(j["suggested_tags"]) <= {"Marketplace", "Food", "Electronics", "Documents", "Clothing",
                                                     "Groceries", "Furniture", "Gifts", "Medical", "Fragile"})
        unknown = self.post("/v1/checklists/generate", {"description": "mystery thing"}).json()
        self.assertEqual(unknown, {"checklist": [], "suggested_size": None, "suggested_tags": []})
        self.assertEqual(self.post("/v1/checklists/generate", {}).status_code, 400)

    def test_attach_checklist_and_tags_are_deduplicated(self):
        eid = self.book_single("C1").json()["errand_id"]
        a = self.post(f"/v1/errands/{eid}/checklist", {"checklists": ["Check the screen", "Check the ports"]}).json()
        b = self.post(f"/v1/errands/{eid}/checklist", {"checklists": ["Check the screen"]}).json()
        self.assertEqual(b["data"][0]["id"], a["data"][0]["id"])           # same item, same id
        self.assertEqual(len(Errand.objects.get(pk=eid).checklist), 2)
        t = self.post(f"/v1/errands/{eid}/tags", {"tags": ["Electronics", "Fragile", "Electronics"]}).json()
        self.assertEqual([x["title"] for x in t["data"]], ["Electronics", "Fragile"])
        bad = self.post(f"/v1/errands/{eid}/tags", {"tags": ["Weapons"]})
        self.assertEqual(bad.status_code, 400)
