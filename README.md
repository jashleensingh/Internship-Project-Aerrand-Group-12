# Aerrand Developer API (`/v1`) — Team KeyPort

Developer API keys plus the public delivery API for Aerrand. Django + Django REST Framework.
It follows the partner document *"Aerrand API — Request & response shapes"* (quote → book → track → webhooks).

**88 automated tests.** Run them with one command (see below).

## Run it (Windows PowerShell)

```powershell
py -m pip install -r requirements.txt
py manage.py migrate
py manage.py seed_data          # prints a live key and a test key ONCE - copy them
py manage.py runserver          # http://127.0.0.1:8000
```

In a second window (use `curl.exe`, and put JSON in files):

```powershell
$KEY = "ak_live_...paste the live key..."
curl.exe -H "Authorization: Bearer $KEY" http://127.0.0.1:8000/v1/me
curl.exe -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" --data "@examples/quote.json" http://127.0.0.1:8000/v1/quotes
```

Run all tests: `py manage.py test api_v1`

Play the driver (so tracking and webhooks move):

```powershell
py manage.py simulate_driver <errand_id> accepted
py manage.py simulate_driver <errand_id> location --lat 42.3110 --lng -83.0250
py manage.py simulate_driver <errand_id> all
py manage.py run_dispatcher --once      # sends pending webhooks
```

## Endpoints

| Call | What it does | Owner |
|---|---|---|
| `POST /v1/quotes` | route quote (`stops[]`) or parcel quote (`dropoff` + `size`); returns `quote_id` | Jashleen |
| `POST /v1/errands` | book a quote; single (`dropoff`) or up to 5 stops (`dropoffs[]`); one record per stop | Jashleen |
| `GET /v1/service-areas` | which cities are served | Jashleen |
| `GET /v1/errands/{id}` | full record | Ashwin |
| `GET /v1/errands/{id}/tracking` | status, driver, live position, timeline, proof of delivery | Ashwin |
| `GET /v1/errands/{id}/public` | no key; safe subset for your customer (no delivery code, no prices) | Ashwin |
| `POST /v1/errands/{id}/cancel` | cancel with fee and refund | Ashwin |
| `GET /v1/wallet` | balance and recent transactions | Ashwin |
| `PUT /v1/errands/{id}/dropoff` / `/pickup` | change instructions, even mid-route (1 km edit window) | Pratyush |
| `POST /v1/checklists/generate`, `/errands/{id}/checklist`, `/tags` | item checklist and tags | Pratyush |
| `GET /v1/me`, `GET /v1/health` | check a key works | Pratyush |
| `/dashboard/api-keys` | create (shown once), list, revoke keys | Pratyush |
| `/dashboard/notifications` | in-app notifications (created, cancelled, delivered) | Pratyush (list), Jashleen/Ashwin (events) |
| `/dashboard/webhook-endpoints` | add a webhook URL, get a signing secret (shown once) | Varun |
| Webhooks, rate limits, idempotency | see below | Varun |

## Who built what

| Member | Apps / files |
|---|---|
| **Pratyush** | `api_v1/keys/` (key system), `api_v1/instructions/`, `api_v1/notices/` (model, service, dashboard list), `api_v1/common/`, `config/` |
| **Jashleen** | `api_v1/booking/` (quotes, pricing, booking, stacking, service area), `notices/on_created.py` |
| **Ashwin** | `api_v1/payments/` (wallet, cancel, refund), `api_v1/tracking/`, `notices/on_cancelled.py`, `notices/on_delivered.py` |
| **Varun** | `api_v1/reliability/` (webhook outbox, signing, retries, rate limit, idempotency) |

## How the main rules work

- **Keys**: `ak_live_` / `ak_test_` + 40 random characters. Only an HMAC-SHA256 hash is stored; the key is shown once. Revoking works on the very next request. Keys in the URL are refused. Scopes: `quotes:write`, `errands:read`, `errands:write`, `errands:cancel`, `wallet:read`.
- **Approval gate**: a business that is not approved cannot create keys or book (`412 business_not_approved`).
- **Tenant isolation**: someone else's errand looks exactly like one that does not exist (`404 errand_not_found`). Test keys cannot see live data.
- **The server sets the price**: a booking takes `quote_id`, never a price. Sending `price`, `charge_total`, etc. is refused. A quote can be booked once, expires after 10 minutes, and must match the addresses and parcels it was made for (otherwise `409 quote_mismatch`), so nobody can book a cheap quote for a heavier job.
- **Stacking**: one pickup, up to 5 drop-offs. One errand record per stop (own id, own delivery code, own status, own share of the price; shares add up to the cent). One payment. Each stop can be cancelled or delivered on its own.
- **Checks before money moves**: service area (`412 service_area_unavailable`), van capacity (`400 route_over_capacity`), quote expiry (`409 quote_expired`), approval, wallet funds (`402 insufficient_funds`).
- **Wallet**: debited with one conditional update, so two bookings at the same moment can never spend the same money; the database also refuses a negative balance. A failed booking rolls back completely. Test keys never move money. *(Wallet is our own payment method next to the partner's `invoice` / `checkout_link`.)*
- **Cancel**: allowed until the Aerrander reaches the drop-off. Fee is $4.00 once an Aerrander has accepted; the rest of that stop's price is refunded to the wallet. Cancelling twice refunds once.
- **Idempotency**: send `Idempotency-Key` (required for live keys). A retry returns the first response with `Idempotent-Replayed: true`; same key with a different request is `422`.
- **Rate limits**: 60 requests a minute per key, 20 bookings a minute. Every response has `X-RateLimit-*`; a `429` adds `Retry-After`. With `REDIS_URL` set the counters live in Redis, shared by all workers.
- **Webhooks**: events are written in the same transaction as the change (outbox), signed `Aerrand-Signature: t=<unix>,v1=<hmac>`, sent at least once, retried with backoff (1 m, 5 m, 30 m, 2 h, 6 h), then marked failed. Receivers de-duplicate on `id`. Events: `errand.payment_confirmed`, `accepted`, `arrived_pickup`, `in_transit`, `arrived_dropoff`, `delivered`, `cancelled`, `dropoff_updated`.
- **Notifications**: in-app notification (and a realtime push hook) when a delivery is created, cancelled (the partner asked for this) or delivered.
- **Errors**: one shape, `{"error": {"code", "message", "details", "request_id"}}`.

## What is a stand-in (replace when joining Aerrand's repo)

| Stand-in here | Aerrand's real thing |
|---|---|
| SQLite | MongoDB |
| `booking/pricing.py` (placeholder rates) | the existing route and parcel pricing engines |
| `booking/coverage.py` (Windsor only) | the activated-cities data |
| `tracking/services.py` + `simulate_driver` | the Aerrander app writing the `deliveries` document |
| `common/realtime.py` (logs only) | Firebase Realtime Database push |
| `checklist.py` (keyword rules) | the item-checklist model |
| `Business` model, `/dashboard/login` | the existing business account and dashboard login |
| Top-up without payment | Stripe (test mode) |

## Questions to confirm with Aerrand

1. A quote can be booked once and must match the addresses/parcels. Is that what they want, or may one quote be reused?
2. Is a wallet balance an allowed payment method next to `invoice` and `checkout_link`?
3. The document's sample books a single drop-off with a *route* quote. We accept that, and also parcel quotes (single drop-off + `parcel`). Both OK?
4. Pickup edit window: we allow all fields until the Aerrander arrives, instructions only until pickup, then locked. Correct?
5. Should live keys always require `Idempotency-Key`? (We do.)
6. Scope names and default scopes for new keys.

## Try the whole flow (examples/)

```powershell
curl.exe -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" --data "@examples/quote.json" http://127.0.0.1:8000/v1/quotes
# copy quote_id into examples/book_route.json, then:
curl.exe -H "Authorization: Bearer $KEY" -H "Idempotency-Key: run-1" -H "Content-Type: application/json" --data "@examples/book_route.json" http://127.0.0.1:8000/v1/errands
curl.exe -H "Authorization: Bearer $KEY" http://127.0.0.1:8000/v1/errands/<errand_id>/tracking
curl.exe http://127.0.0.1:8000/v1/errands/<errand_id>/public
```
Run the booking call twice: the second answer has `Idempotent-Replayed: true` and nothing is charged again.
