"""Wallet payment, cancellation and refunds (Ashwin).

Money rules:
  * The wallet is debited with ONE conditional UPDATE (balance >= amount). Two requests at the same time cannot both
    spend the same dollars, and the balance can never go below zero (also enforced by a database CHECK).
  * Test keys never move money.
  * Cancelling is a compare-and-set on the errand status, so two cancels cannot both refund.
"""
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from api_v1.booking.models import Errand
from api_v1.common.errors import ApiError
from api_v1.common.realtime import push_realtime
from api_v1.notices import hooks
from api_v1.reliability.outbox import emit_event

from .models import Wallet, WalletTransaction

CANCELLABLE = ("pending_payment", "pending", "broadcasted", "accepted", "arrived", "picked_up", "in_transit")
FEE_STATUSES = ("accepted", "arrived", "picked_up", "in_transit")   # an Aerrander is already engaged


def get_wallet(business):
    return Wallet.objects.get_or_create(business=business)[0]


def _record(wallet, type_, amount, ref, note=""):
    wallet.refresh_from_db()
    return WalletTransaction.objects.create(wallet=wallet, type=type_, amount=amount,
                                            balance_after=wallet.balance, ref=ref, note=note)


def debit(business, amount, ref, note=""):
    wallet = get_wallet(business)
    updated = Wallet.objects.filter(pk=wallet.pk, balance__gte=amount).update(balance=F("balance") - amount)
    if not updated:
        wallet.refresh_from_db()
        raise ApiError(402, "insufficient_funds", "Your wallet balance is too low for this booking.",
                       required=str(amount), available=str(wallet.balance))
    return _record(wallet, "errand_charge", -amount, ref, note)


def credit(business, amount, type_, ref="", note=""):
    wallet = get_wallet(business)
    Wallet.objects.filter(pk=wallet.pk).update(balance=F("balance") + amount)
    return _record(wallet, type_, amount, ref, note)


def top_up(business, amount):
    """Stand-in for a Stripe (test mode) top-up. The real flow confirms the payment first."""
    if amount <= 0 or amount > Decimal("1000"):
        raise ApiError(400, "validation_failed", "Top-up must be between 0.01 and 1000.00.",
                       details={"amount": ["Must be between 0.01 and 1000.00."]})
    with transaction.atomic():
        return credit(business, amount, "funds_added", note="Top-up (test mode)")


def mark_paid(errands, reference=None):
    """Payment verified: promote pending_payment -> broadcasted and tell the customer's webhook."""
    now = timezone.now()
    for e in errands:
        pay = dict(e.payment)
        pay.update(status="paid", reference=reference)
        n = Errand.objects.filter(pk=e.pk, status="pending_payment").update(
            status="broadcasted", payment_status=True, payment=pay, updated_at=now)
        if n:
            fresh = Errand.objects.get(pk=e.pk)
            emit_event(fresh, "errand.payment_confirmed")
            push_realtime(f"business/{fresh.business_id}", {"errand_id": str(fresh.id), "status": fresh.status})


def pay_with_wallet(api_key, errands, total):
    """Called inside the booking transaction. Live key: debit the wallet. Test key: no money moves."""
    ref = str(errands[0].batch_id or errands[0].id)
    if api_key.environment == "live":
        debit(api_key.business, total, ref, "Delivery booking")
    mark_paid(errands, reference=f"wallet:{ref}")


def cancel_policy(errand):
    """Returns the fee for cancelling an errand in its current status."""
    if errand.environment == "test" or errand.status not in FEE_STATUSES:
        return Decimal("0.00")
    return min(Decimal(settings.CANCEL_FEE), errand.price)


def cancel_errand(errand_id, business, environment, reason=""):
    for _ in range(2):   # one retry if another request changes the status between our read and our update
        with transaction.atomic():
            e = Errand.objects.select_for_update().filter(pk=errand_id, business=business,
                                                          environment=environment).first()
            if e is None:
                raise ApiError(404, "errand_not_found", "No errand with that id.")
            if e.status not in CANCELLABLE:
                msg = ("This errand is already cancelled." if e.status == "cancelled" else
                       "Too late to cancel: the Aerrander is at the stop or it is already delivered.")
                raise ApiError(409, "cancel_not_allowed", msg, current_status=e.status)
            fee = cancel_policy(e)
            refund = Decimal("0.00")
            paid_by_wallet = e.payment_status and e.payment.get("method") == "wallet" and e.environment == "live"
            if paid_by_wallet:
                refund = e.price - fee
            now = timezone.now()
            cancellation = {"cancelled_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "cancelled_by": "business",
                            "reason": reason or None, "fee": str(fee), "refund": str(refund)}
            timeline = list(e.timeline) + [{"at": cancellation["cancelled_at"], "state": "CANCELLED"}]
            changed = Errand.objects.filter(pk=e.pk, status=e.status).update(
                status="cancelled", cancellation=cancellation, timeline=timeline, completed_at=now, updated_at=now)
            if not changed:
                continue
            if refund > 0:
                credit(business, refund, "errand_refund", ref=str(e.id), note="Cancelled errand refund")
            fresh = Errand.objects.get(pk=e.pk)
            emit_event(fresh, "errand.cancelled", extra={"cancellation": cancellation})
            hooks.on_cancelled(fresh, cancellation)
            push_realtime(f"business/{business.id}", {"errand_id": str(e.id), "status": "cancelled"})
            return fresh
    raise ApiError(409, "cancel_not_allowed", "The errand changed while cancelling. Try again.")
