"""Helpers shared by every app's tests."""
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient

from api_v1.common.models import Business
from api_v1.keys import services as key_services

PICKUP = (42.3149, -83.0364)
STOP1 = (42.3201, -83.0187)
STOP2 = (42.2789, -82.9912)


def make_business(name="Acme", approved=True):
    user = User.objects.create_user(name.lower().replace(" ", ""), password="pw-12345-xyz")
    return Business.objects.create(
        name=name, owner=user, approval_status="approved" if approved else "awaiting_documents")


def make_key(business, env="live", scopes=None):
    obj, raw = key_services.issue(business, "test key", env, scopes)
    return obj, {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def route_quote_body(stops=None):
    stops = stops or [{"lat": STOP1[0], "lng": STOP1[1], "parcels": {"small": 2, "medium": 1}}]
    return {"pickup": {"lat": PICKUP[0], "lng": PICKUP[1]}, "stops": stops}


def contact(name="Jordan Alvarez", pref="leave_at_door", **kw):
    return {"name": name, "phone_number": "+15195550188", "preference": pref, **kw}


def single_body(quote_id, reference="SHOP-1", **over):
    body = {
        "reference": reference, "quote_id": quote_id, "vehicle_type": "car",
        "parcel": {"size": "medium", "quantity": 1},
        "pickup": {"label": "500 Ouellette Ave, Windsor, ON", "lat": str(PICKUP[0]), "lng": str(PICKUP[1]),
                   "contact": contact("Store 14", "pickup")},
        "dropoff": {"label": "1823 Wyandotte St E, Windsor, ON", "lat": str(STOP1[0]), "lng": str(STOP1[1]),
                    "contact": contact()},
        "payment": {"method": "invoice"},
    }
    body.update(over)
    return body


def single_quote_body():
    """Quote body that matches single_body() (one medium parcel)."""
    return route_quote_body([{"lat": STOP1[0], "lng": STOP1[1], "parcels": {"medium": 1}}])


def multi_body(quote_id, reference="RUN-1", **over):
    body = {
        "reference": reference, "quote_id": quote_id, "vehicle_type": "van",
        "pickup": {"label": "Warehouse A, Windsor", "lat": str(PICKUP[0]), "lng": str(PICKUP[1]),
                   "contact": contact("Warehouse A", "pickup")},
        "dropoffs": [
            {"reference": "SHOP-10432", "label": "1823 Wyandotte St E", "lat": str(STOP1[0]), "lng": str(STOP1[1]),
             "parcels": {"small": 2, "medium": 1}, "contact": contact()},
            {"reference": "SHOP-10433", "label": "3100 Howard Ave", "lat": str(STOP2[0]), "lng": str(STOP2[1]),
             "parcels": {"small": 4}, "contact": contact("Priya Raman", "meet_at_door")},
        ],
        "payment": {"method": "invoice"},
    }
    body.update(over)
    return body


def multi_quote_body():
    return route_quote_body([
        {"lat": STOP1[0], "lng": STOP1[1], "parcels": {"small": 2, "medium": 1}},
        {"lat": STOP2[0], "lng": STOP2[1], "parcels": {"small": 4}},
    ])


class ApiTestMixin:
    """Mixin for TestCase / TransactionTestCase: a business, a live key, a client."""

    def setUp(self):
        cache.clear()
        self.business = make_business("Acme")
        self.key, self.h = make_key(self.business, "live")
        self.client = APIClient()

    def post(self, path, body=None, headers=None, **extra):
        return self.client.post(path, body or {}, format="json", **(headers or self.h), **extra)

    def get(self, path, headers=None):
        return self.client.get(path, **(headers or self.h))

    def put(self, path, body, headers=None):
        return self.client.put(path, body, format="json", **(headers or self.h))

    def quote(self, body=None, headers=None):
        r = self.post("/v1/quotes", body or single_quote_body(), headers)
        assert r.status_code == 200, r.content
        return r.json()

    def book_single(self, reference="SHOP-1", idem=None, headers=None, **over):
        q = self.quote(headers=headers)
        h = dict(headers or self.h)
        h["HTTP_IDEMPOTENCY_KEY"] = idem or f"idem-{reference}"
        return self.client.post("/v1/errands", single_body(q["quote_id"], reference, **over), format="json", **h)
