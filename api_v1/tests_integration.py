"""End-to-end: the whole story a customer integration would run, using only the public API plus the driver simulator."""
import json
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from api_v1.common.testing import (ApiTestMixin, multi_body, multi_quote_body, single_body)
from api_v1.payments.services import credit
from api_v1.reliability import dispatcher
from api_v1.reliability.signing import verify_signature
from api_v1.tracking import services as tr


class EndToEnd(ApiTestMixin, TestCase):
    def test_key_to_delivered_with_webhooks_and_notifications(self):
        dash = APIClient()
        dash.force_login(self.business.owner)

        # 1. developer creates a key in the dashboard and a webhook endpoint
        k = dash.post("/dashboard/api-keys", {"name": "Shopify", "environment": "live"}, format="json").json()
        h = {"HTTP_AUTHORIZATION": "Bearer " + k["key"]}
        secret = dash.post("/dashboard/webhook-endpoints", {"url": "https://shop.example.com/hook"},
                           format="json").json()["secret"]
        credit(self.business, Decimal("150"), "funds_added")

        # 2. quote -> book a 2-stop route paid from the wallet (idempotent retry in the middle)
        q = self.post("/v1/quotes", multi_quote_body(), h).json()
        hk = {**h, "HTTP_IDEMPOTENCY_KEY": "run-1"}
        first = self.post("/v1/errands", multi_body(q["quote_id"], payment={"method": "wallet"}), hk)
        retry = self.post("/v1/errands", multi_body(q["quote_id"], payment={"method": "wallet"}), hk)
        self.assertEqual((first.status_code, retry.status_code), (201, 201))
        self.assertEqual(retry["Idempotent-Replayed"], "true")
        route = first.json()
        self.assertEqual(self.get("/v1/wallet", h).json()["balance"],
                         str(Decimal("150") - Decimal(str(route["pricing"]["charge_total"]))))   # charged once
        a, b = (s["errand_id"] for s in route["stops"])

        # 3. the customer changes the drop-off instructions
        self.assertEqual(self.put(f"/v1/errands/{a}/dropoff", {"instructions": "Leave with concierge"}, h).status_code, 200)

        # 4. stop A is delivered; the customer's tracking page works without a key
        for ev in ("accepted", "arrived_pickup", "in_transit", "arrived_dropoff", "delivered"):
            tr.apply_event(a, ev)
        self.assertEqual(APIClient().get(f"/v1/errands/{a}/public").json()["data"]["status"], "delivered")
        self.assertEqual(self.get(f"/v1/errands/{a}/tracking", h).json()["data"]["status"], "delivered")

        # 5. stop B is cancelled on its own: refund, and the dashboard gets a notification
        c = self.post(f"/v1/errands/{b}/cancel", {"reason": "buyer unreachable"}, h)
        self.assertEqual(c.status_code, 200)
        self.assertEqual(c.json()["cancellation"]["refund"], route["stops"][1]["price"])
        titles = [n["kind"] for n in dash.get("/dashboard/notifications").json()["data"]]
        self.assertIn("errand_cancelled", titles)
        self.assertIn("errand_created", titles)

        # 6. webhooks: every event was written, signed, and delivered exactly once
        got = []
        stats = dispatcher.dispatch_pending(sender=lambda url, body, hd: got.append((body, hd)) or 200)
        types = [json.loads(body)["type"] for body, _ in got]
        self.assertEqual(stats["delivered"], len(got))
        for needed in ("errand.payment_confirmed", "errand.accepted", "errand.delivered", "errand.dropoff_updated",
                       "errand.cancelled"):
            self.assertIn(needed, types)
        self.assertTrue(all(verify_signature(secret, body, hd["Aerrand-Signature"]) for body, hd in got))
        self.assertEqual(dispatcher.dispatch_pending(sender=lambda *x: 200)["delivered"], 0)

        # 7. revoke the key: the very next call is refused
        dash.delete(f"/dashboard/api-keys/{k['id']}")
        self.assertEqual(self.get("/v1/me", h).status_code, 401)
