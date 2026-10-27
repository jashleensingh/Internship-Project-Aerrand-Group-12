import json
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api_v1.booking.models import Errand
from api_v1.common.testing import ApiTestMixin, make_business, make_key, single_body
from api_v1.payments.services import credit
from api_v1.reliability import dispatcher
from api_v1.reliability.models import IdempotencyRecord, OutboxEvent, WebhookDelivery, WebhookEndpoint
from api_v1.reliability.signing import sign_payload, verify_signature
from api_v1.tracking import services as tr


class IdempotencyTests(ApiTestMixin, TestCase):
    def test_retry_returns_same_response_and_creates_one_errand(self):
        q = self.quote()
        h = {**self.h, "HTTP_IDEMPOTENCY_KEY": "5b0e2c3a-1d4f"}
        r1 = self.post("/v1/errands", single_body(q["quote_id"]), h)
        r2 = self.post("/v1/errands", single_body(q["quote_id"]), h)
        self.assertEqual((r1.status_code, r2.status_code), (201, 201))
        self.assertEqual(r1.json(), r2.json())
        self.assertEqual(r2["Idempotent-Replayed"], "true")
        self.assertNotIn("Idempotent-Replayed", r1)
        self.assertEqual(Errand.objects.count(), 1)

    def test_same_key_different_request_is_422(self):
        q = self.quote()
        h = {**self.h, "HTTP_IDEMPOTENCY_KEY": "k1"}
        self.post("/v1/errands", single_body(q["quote_id"]), h)
        r = self.post("/v1/errands", single_body(q["quote_id"], reference="OTHER"), h)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "idempotency_key_reuse"))

    def test_live_key_requires_a_key_test_key_does_not(self):
        q = self.quote()
        r = self.post("/v1/errands", single_body(q["quote_id"]))
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "idempotency_key_required"))
        _, th = make_key(self.business, "test")
        qt = self.quote(headers=th)
        self.assertEqual(self.post("/v1/errands", single_body(qt["quote_id"], "TT"), th).status_code, 201)

    def test_error_responses_are_replayed_too(self):
        h = {**self.h, "HTTP_IDEMPOTENCY_KEY": "k-err"}
        r1 = self.post("/v1/errands", single_body("qt_DOESNOTEXIST000"), h)
        r2 = self.post("/v1/errands", single_body("qt_DOESNOTEXIST000"), h)
        self.assertEqual((r1.status_code, r2.status_code), (404, 404))
        self.assertEqual(r2["Idempotent-Replayed"], "true")

    def test_in_progress_claim_returns_409(self):
        q = self.quote()
        body = single_body(q["quote_id"])
        h = {**self.h, "HTTP_IDEMPOTENCY_KEY": "busy"}
        self.assertEqual(self.post("/v1/errands", body, h).status_code, 201)
        IdempotencyRecord.objects.update(state="processing")      # pretend the first request is still running
        r = self.post("/v1/errands", body, h)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "idempotency_in_progress"))
        self.assertEqual(Errand.objects.count(), 1)

    def test_keys_are_per_api_key(self):
        q = self.quote()
        self.post("/v1/errands", single_body(q["quote_id"]), {**self.h, "HTTP_IDEMPOTENCY_KEY": "same"})
        _, h2 = make_key(make_business("Beta"))
        q2 = self.quote(headers=h2)
        r = self.post("/v1/errands", single_body(q2["quote_id"], "B1"), {**h2, "HTTP_IDEMPOTENCY_KEY": "same"})
        self.assertEqual(r.status_code, 201)
        self.assertNotIn("Idempotent-Replayed", r)


class RateLimitTests(ApiTestMixin, TestCase):
    def test_headers_then_429_with_retry_after(self):
        first = self.get("/v1/me")
        self.assertEqual(first["X-RateLimit-Limit"], "60")
        self.assertEqual(first["X-RateLimit-Remaining"], "59")
        for _ in range(59):
            last = self.get("/v1/me")
        self.assertEqual(last.status_code, 200)
        over = self.get("/v1/me")
        self.assertEqual((over.status_code, over.json()["error"]["code"]), (429, "rate_limited"))
        self.assertGreaterEqual(int(over["Retry-After"]), 1)
        self.assertEqual(over["X-RateLimit-Remaining"], "0")

    def test_limit_is_per_key(self):
        for _ in range(61):
            self.get("/v1/me")
        _, h2 = make_key(make_business("Beta"))
        self.assertEqual(self.get("/v1/me", h2).status_code, 200)

    def test_booking_has_its_own_lower_limit(self):
        from django.test.utils import override_settings
        with override_settings(API_CREATE_PER_MIN=2):
            codes = [self.post("/v1/errands", {}).status_code for _ in range(3)]
        self.assertEqual(codes[:2], [400, 400])      # reached the endpoint (validation failed)
        self.assertEqual(codes[2], 429)


class SigningTests(TestCase):
    def test_signature_round_trip_and_tamper(self):
        body = b'{"id":"evt_1"}'
        header = sign_payload("whsec_abc", body, 1_700_000_000)
        self.assertTrue(verify_signature("whsec_abc", body, header, now=1_700_000_010))
        self.assertFalse(verify_signature("whsec_abc", body + b" ", header, now=1_700_000_010))     # body changed
        self.assertFalse(verify_signature("whsec_other", body, header, now=1_700_000_010))          # wrong secret
        self.assertFalse(verify_signature("whsec_abc", body, header, now=1_700_001_000))            # too old (replay)
        self.assertFalse(verify_signature("whsec_abc", body, "garbage"))


class WebhookTests(ApiTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.dash = APIClient()
        self.dash.force_login(self.business.owner)
        r = self.dash.post("/dashboard/webhook-endpoints", {"url": "https://shop.example.com/hook"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.secret = r.json()["secret"]
        credit(self.business, Decimal("100"), "funds_added")

    def book(self, ref="H1"):
        return self.book_single(ref, idem=f"i-{ref}", payment={"method": "wallet"}).json()["errand_id"]

    def test_secret_shown_once_and_url_rules(self):
        listed = self.dash.get("/dashboard/webhook-endpoints").json()["data"][0]
        self.assertNotIn("secret", listed)
        for bad in ("http://shop.example.com/x", "https://10.0.0.5/x", "not a url"):
            r = self.dash.post("/dashboard/webhook-endpoints", {"url": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)

    def test_events_are_written_with_the_change_in_partner_envelope(self):
        eid = self.book()
        tr.apply_event(eid, "accepted")
        tr.apply_event(eid, "arrived_pickup")
        tr.apply_event(eid, "in_transit")
        types = list(OutboxEvent.objects.values_list("type", flat=True))
        self.assertEqual(types, ["errand.payment_confirmed", "errand.accepted", "errand.arrived_pickup",
                                 "errand.in_transit"])
        p = OutboxEvent.objects.get(type="errand.in_transit").payload
        self.assertTrue(p["id"].startswith("evt_"))
        self.assertEqual(set(p), {"id", "type", "created_at", "data"})
        self.assertEqual(p["data"]["status"], "in_transit")
        self.assertEqual(p["data"]["errand_id"], eid)
        self.assertEqual(p["data"]["reference"], "H1")
        self.assertEqual(p["data"]["driver"], {"name": "Sam O.", "vehicle_type": "car"})
        self.assertEqual(WebhookDelivery.objects.count(), 4)

    def test_delivery_is_signed_and_verifiable(self):
        eid = self.book()
        sent = []

        def sender(url, body, headers):
            sent.append((url, body, headers))
            return 200
        stats = dispatcher.dispatch_pending(sender=sender)
        self.assertEqual(stats["delivered"], 1)
        url, body, headers = sent[0]
        self.assertEqual(url, "https://shop.example.com/hook")
        self.assertTrue(verify_signature(self.secret, body, headers["Aerrand-Signature"]))
        self.assertEqual(json.loads(body)["type"], "errand.payment_confirmed")
        self.assertEqual(headers["Aerrand-Event-Id"], json.loads(body)["id"])
        self.assertEqual(dispatcher.dispatch_pending(sender=sender)["delivered"], 0)     # not sent twice

    def test_failures_retry_with_backoff_then_give_up(self):
        self.book()
        calls = []

        def failing(url, body, headers):
            calls.append(1)
            return 500
        t0 = timezone.now()
        dispatcher.dispatch_pending(sender=failing, now=t0)
        d = WebhookDelivery.objects.get()
        self.assertEqual((d.status, d.attempts), ("pending", 1))
        self.assertGreaterEqual(d.next_attempt_at, t0 + timedelta(seconds=59))
        self.assertEqual(dispatcher.dispatch_pending(sender=failing, now=t0 + timedelta(seconds=10))["retry"], 0)
        now = t0
        for backoff in dispatcher.BACKOFF:
            now = now + timedelta(seconds=backoff + 1)
            dispatcher.dispatch_pending(sender=failing, now=now)
        d.refresh_from_db()
        self.assertEqual((d.status, d.attempts), ("failed", dispatcher.MAX_ATTEMPTS))
        self.assertEqual(len(calls), dispatcher.MAX_ATTEMPTS)

    def test_a_network_error_counts_as_a_failed_attempt(self):
        self.book()

        def boom(url, body, headers):
            raise TimeoutError("timed out")
        dispatcher.dispatch_pending(sender=boom)
        d = WebhookDelivery.objects.get()
        self.assertEqual(d.attempts, 1)
        self.assertIn("TimeoutError", d.last_error)

    def test_a_live_lease_stops_a_second_dispatcher(self):
        self.book()
        WebhookDelivery.objects.update(lease_until=timezone.now() + timedelta(seconds=30))
        self.assertEqual(dispatcher.dispatch_pending(sender=lambda *a: 200), {"delivered": 0, "retry": 0,
                                                                              "failed": 0, "skipped": 0})

    def test_event_filter_and_environment_and_tenant(self):
        self.dash.delete(f"/dashboard/webhook-endpoints/{WebhookEndpoint.objects.get().id}")
        self.dash.post("/dashboard/webhook-endpoints",
                       {"url": "https://shop.example.com/only-cancel", "events": ["errand.cancelled"]}, format="json")
        other = make_business("Beta")
        oc = APIClient()
        oc.force_login(other.owner)
        oc.post("/dashboard/webhook-endpoints", {"url": "https://beta.example.com/h"}, format="json")
        eid = self.book("H2")
        self.assertEqual(WebhookDelivery.objects.count(), 0)          # payment_confirmed not subscribed; Beta not ours
        self.post(f"/v1/errands/{eid}/cancel", {})
        d = WebhookDelivery.objects.get()
        self.assertEqual(d.event.type, "errand.cancelled")
        self.assertEqual(d.endpoint.url, "https://shop.example.com/only-cancel")
        self.assertEqual(d.event.payload["data"]["cancellation"]["fee"], "0.00")

    def test_another_business_cannot_delete_my_endpoint(self):
        oc = APIClient()
        oc.force_login(make_business("Beta").owner)
        r = oc.delete(f"/dashboard/webhook-endpoints/{WebhookEndpoint.objects.get().id}")
        self.assertEqual(r.status_code, 404)
