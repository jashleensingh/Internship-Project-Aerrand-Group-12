"""Idempotency-Key handling for POST /v1/errands.

  same key + same request  -> the original response again, header `Idempotent-Replayed: true`, nothing charged twice
  same key + other request -> 422 idempotency_key_reuse
  same key while the first is still running -> 409 idempotency_in_progress
  live keys must send a key (400 idempotency_key_required)

The key is CLAIMED (a unique row) before any work happens, which is what stops two simultaneous retries from both
running. Error responses (4xx) are stored and replayed too; a 5xx/crash releases the claim so the client can retry.
"""
import hashlib

from django.db import IntegrityError, transaction
from rest_framework.response import Response

from api_v1.common.errors import ApiError, error_payload

from .models import IdempotencyRecord


def run_idempotent(request, producer, required=False):
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        if required:
            raise ApiError(400, "idempotency_key_required",
                           "Send an Idempotency-Key header (any unique string, e.g. a UUID) with live bookings.")
        return producer()
    if len(key) > 120:
        raise ApiError(400, "validation_failed", "Idempotency-Key is too long.",
                       details={"Idempotency-Key": ["At most 120 characters."]})

    raw = getattr(request._request, "raw_body", b"")
    fingerprint = hashlib.sha256(request.method.encode() + b"\n" + request.path.encode() + b"\n" + raw).hexdigest()
    api_key_id = request.auth.id
    try:
        with transaction.atomic():
            rec = IdempotencyRecord.objects.create(api_key_id=api_key_id, idem_key=key, fingerprint=fingerprint)
    except IntegrityError:
        existing = IdempotencyRecord.objects.get(api_key_id=api_key_id, idem_key=key)
        if existing.fingerprint != fingerprint:
            raise ApiError(422, "idempotency_key_reuse",
                           "That Idempotency-Key was already used with a different request.")
        if existing.state != "done":
            raise ApiError(409, "idempotency_in_progress", "The first request with this key is still running.")
        return Response(existing.body, status=existing.status_code, headers={"Idempotent-Replayed": "true"})

    try:
        response = producer()
    except ApiError as e:
        if e.status_code < 500:
            IdempotencyRecord.objects.filter(pk=rec.pk).update(
                state="done", status_code=e.status_code,
                body=error_payload(e.code, e.message, e.details, None, **e.extra))
        else:
            rec.delete()
        raise
    except Exception:
        rec.delete()
        raise
    IdempotencyRecord.objects.filter(pk=rec.pk).update(state="done", status_code=response.status_code, body=response.data)
    return response
