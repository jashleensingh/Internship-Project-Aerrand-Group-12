# Commit plan — Week 7 (end of Milestone 3)

The university asked for **ongoing development that is visible in Git, from everyone**. This file says which files each
person commits, in what order, with ready-to-use messages.

## Rules (please read)

1. **Read and run your own part first.** Run `py manage.py test api_v1`, open your files, and be able to explain
   every function in them. You will be asked to explain your contribution on your laptop.
2. **Commit from your own GitHub account**, on your own branch, on the day you really do the work. Do not backdate
   commits and do not make empty or filler commits — the evaluators look at the history.
3. **Commit in small steps** (the sequences below), not one giant commit. Run the tests between steps if you can.
4. **Be open about AI help.** Your team agreement says reused work must be credited. Add one line in your PR
   description such as: *"First draft generated with Claude; I reviewed, ran and understood it."* Change anything you
   disagree with — it is your part.
5. **One reviewer per pull request** (a teammate who did not write it). Never commit `.env`, keys or `db.sqlite3`
   (the `.gitignore` already blocks them).
6. Link each PR to its card in GitHub Projects and move the card when merged.

## Merge order

Each of you works with the **full folder on your laptop** (so tests run), and commits **only your files** on your branch.
The apps import each other, so CI goes green after the last PR is merged. Merge in this order:

1. Pratyush — skeleton + keys
2. Varun — reliability
3. Ashwin — payments + tracking
4. Jashleen — booking (+ `urls.py`, README)
5. Pratyush — instructions + notices (after the others, since they use tracking and reliability)

## Pratyush — API keys, instructions, notifications list

Branch `feature/api-keys`
1. `chore: Django project skeleton and settings` — `manage.py`, `config/`, `requirements.txt`, `.gitignore`, `.github/workflows/ci.yml`
2. `feat(common): business model, error format, request id middleware` — `api_v1/common/{models,errors,middleware,ids,geo,validation,realtime,dashboard,base,views,testing}.py`, `api_v1/common/migrations/`
3. `feat(keys): hashed API keys (ak_live_/ak_test_), shown once` — `api_v1/keys/{models,services}.py`, `migrations/`
4. `feat(keys): key authentication, scopes and approval gate` — `authentication.py`, `permissions.py`
5. `feat(keys): dashboard create/list/revoke endpoints and GET /v1/me` — `views.py`
6. `test(keys): hashing, scopes, revoke, tenant isolation` — `tests.py`
7. `feat(common): seed_data command` — `api_v1/common/management/`

Branch `feature/dropoff-instructions` (merge last)
1. `feat(instructions): edit window rules for drop-off and pickup` — `instructions/services.py`
2. `feat(instructions): PUT dropoff/pickup, checklist generate/attach, tags` — `views.py`, `checklist.py`
3. `test(instructions): partial update, 1 km window, locked fields` — `tests.py`
4. `feat(notices): notification model, service, dashboard list and mark-read` — `notices/{models,services,views,hooks}.py`, `migrations/`, `tests.py`

## Jashleen — quotes, booking, stacking

Branch `feature/quotes-booking`
1. `feat(booking): route and parcel pricing engines (stand-in rates)` — `booking/pricing.py`
2. `feat(booking): quote and errand models` — `booking/models.py`, `migrations/`
3. `feat(booking): request validation, server-owned fields refused` — `booking/validation.py`
4. `feat(booking): service area check and GET /v1/service-areas` — `booking/coverage.py`
5. `feat(booking): quote creation bound to inputs, single-use, expiry` — `booking/services.py` (quotes part), `selectors.py`
6. `feat(booking): create errands, multi-stop (one record per stop), price shares` — `booking/services.py`, `serializers.py`, `views.py`
7. `feat(notices): notification when a delivery is created` — `notices/on_created.py`
8. `feat: wire /v1 and /dashboard URLs` — `api_v1/urls.py`, `api_v1/dashboard_urls.py`, `config/urls.py`
9. `test(booking): pricing, quote reuse rules, stacking, service area` — `booking/tests.py`, `api_v1/tests_integration.py`
10. `docs: README` — `README.md`, `COMMIT_PLAN.md`

## Ashwin — wallet, cancellation, tracking

Branch `feature/wallet-cancel`
1. `feat(payments): wallet and transaction models with non-negative constraint` — `payments/models.py`, `migrations/`
2. `feat(payments): atomic wallet debit, refund, top-up` — `payments/services.py` (debit/credit/top_up/mark_paid)
3. `feat(payments): cancel with fee and refund (compare-and-set)` — `payments/services.py` (cancel), `views.py`
4. `feat(notices): notification when a delivery is cancelled` — `notices/on_cancelled.py`
5. `test(payments): insufficient funds, double cancel, concurrent bookings cannot overspend` — `payments/tests.py`

Branch `feature/tracking`
1. `feat(tracking): status transitions, timeline, proof of delivery` — `tracking/services.py`
2. `feat(tracking): tracking, full record and public tracking payloads` — `tracking/serializers.py`, `views.py`
3. `feat(tracking): simulate_driver command` — `tracking/management/`
4. `feat(notices): notification when a delivery is delivered` — `notices/on_delivered.py`
5. `test(tracking): journey, public page hides private fields, tenant isolation` — `tracking/tests.py`

## Varun — webhooks, rate limit, idempotency

Branch `feature/reliability`
1. `feat(reliability): models for idempotency, webhook endpoints, outbox, deliveries` — `reliability/models.py`, `migrations/`
2. `feat(reliability): per-key rate limit with X-RateLimit headers (Redis-ready)` — `reliability/ratelimit.py`
3. `feat(reliability): Idempotency-Key claim, replay, mismatch and in-progress` — `reliability/idempotency.py`
4. `feat(reliability): outbox events in the partner envelope` — `reliability/outbox.py`
5. `feat(reliability): HMAC signing (Aerrand-Signature) and verification` — `reliability/signing.py`
6. `feat(reliability): dispatcher with lease, retries and backoff + run_dispatcher command` — `dispatcher.py`, `management/`
7. `feat(reliability): dashboard webhook endpoint create/list/delete` — `views.py`
8. `test(reliability): replay, 422/409, 429, signature, retry schedule` — `tests.py`

## Before the demo

- `py manage.py test api_v1` — everyone runs it on their own laptop.
- `py manage.py migrate` then `py manage.py seed_data`, start the server, run the curl steps in the README.
- Show your own files in the commit list on GitHub and explain one function from each of your commits.
