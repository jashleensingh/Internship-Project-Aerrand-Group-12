from django.test import TestCase
from rest_framework.test import APIClient

from api_v1.common.testing import ApiTestMixin, make_business, make_key
from api_v1.keys.models import ApiKey


class KeyTests(ApiTestMixin, TestCase):
    def test_format_and_only_hash_stored(self):
        obj, raw = __import__("api_v1.keys.services", fromlist=["x"]).issue(self.business, "k", "live")
        self.assertRegex(raw, r"^ak_live_[0-9A-Za-z]{40}$")
        self.assertEqual(obj.key_prefix, raw[:15])
        self.assertEqual(len(obj.key_hash), 64)
        self.assertNotIn(raw, str(list(ApiKey.objects.values())))

    def test_dashboard_create_shows_key_once_and_list_hides_it(self):
        c = APIClient()
        c.force_login(self.business.owner)
        r = c.post("/dashboard/api-keys", {"name": "Shopify", "environment": "test"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["key"].startswith("ak_test_"))
        listed = c.get("/dashboard/api-keys").json()["data"]
        self.assertTrue(all("key" not in k for k in listed))

    def test_dashboard_requires_sign_in(self):
        self.assertEqual(APIClient().get("/dashboard/api-keys").status_code, 401)

    def test_unapproved_business_cannot_create_key_or_book(self):
        b = make_business("Newco", approved=False)
        c = APIClient()
        c.force_login(b.owner)
        r = c.post("/dashboard/api-keys", {"name": "x"}, format="json")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (412, "business_not_approved"))
        _, h = make_key(b)   # a key that somehow exists still cannot change data
        self.assertEqual(self.post("/v1/errands", {}, h).status_code, 412)

    def test_bad_missing_and_query_keys(self):
        self.assertEqual(APIClient().get("/v1/me").json()["error"]["code"], "invalid_api_key")
        bad = {"HTTP_AUTHORIZATION": "Bearer ak_live_" + "x" * 40}
        self.assertEqual(self.get("/v1/me", bad).status_code, 401)
        r = self.client.get("/v1/me?api_key=" + "x" * 20, **self.h)
        self.assertEqual(r.status_code, 400)

    def test_scope_is_enforced(self):
        _, h = make_key(self.business, scopes=["errands:read"])
        r = self.post("/v1/quotes", {}, h)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["required_scope"], "quotes:write")

    def test_revoke_takes_effect_immediately_and_is_tenant_scoped(self):
        self.assertEqual(self.get("/v1/me").status_code, 200)
        c = APIClient()
        other = make_business("Beta")
        c.force_login(other.owner)
        self.assertEqual(c.delete(f"/dashboard/api-keys/{self.key.id}").status_code, 404)   # not theirs
        c.force_login(self.business.owner)
        self.assertEqual(c.delete(f"/dashboard/api-keys/{self.key.id}").status_code, 200)
        r = self.get("/v1/me")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "invalid_api_key"))

    def test_responses_carry_request_id(self):
        r = self.get("/v1/me")
        self.assertTrue(r["X-Request-Id"])
        err = APIClient().get("/v1/me", HTTP_X_REQUEST_ID="trace-12345678")
        self.assertEqual(err.json()["error"]["request_id"], "trace-12345678")
