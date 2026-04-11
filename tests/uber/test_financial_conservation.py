"""
Property-based and invariant tests for financial models.

Tests ModelReceipt, ReceiptTransaction, ReceiptItem, and PromoCode using
Hypothesis for pure-function properties and direct DB tests for aggregate
receipt invariants.
"""

import uuid
from datetime import datetime, UTC

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from uber.config import c
from uber.models import Session
from uber.models.commerce import ModelReceipt, ReceiptItem, ReceiptTransaction
from uber.models.promo_code import PromoCode


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Badge prices in whole dollars (PromoCode.calculate_discounted_price takes dollars)
badge_price = st.integers(min_value=1, max_value=500)
# Receipt amounts in cents
pos_cents = st.integers(min_value=1, max_value=1_000_000)
item_count = st.integers(min_value=1, max_value=50)


# ---------------------------------------------------------------------------
# PromoCode: calculate_discounted_price
#
# Key invariant: result is always in [0, price].
# Special case: discount=0 (or None) means "free badge" → returns 0.
# ---------------------------------------------------------------------------

class TestPromoCodeDiscountInvariants:

    @given(price=badge_price, discount=st.integers(min_value=1, max_value=1000))
    def test_fixed_discount_result_bounded(self, price, discount):
        code = PromoCode(discount=discount, discount_type=PromoCode._FIXED_DISCOUNT)
        result = code.calculate_discounted_price(price)
        assert 0 <= result <= price

    @given(price=badge_price, fixed_price=st.integers(min_value=1, max_value=1000))
    def test_fixed_price_result_bounded(self, price, fixed_price):
        code = PromoCode(discount=fixed_price, discount_type=PromoCode._FIXED_PRICE)
        result = code.calculate_discounted_price(price)
        assert 0 <= result <= price

    @given(price=badge_price, pct=st.integers(min_value=1, max_value=300))
    def test_percent_discount_result_bounded(self, price, pct):
        code = PromoCode(discount=pct, discount_type=PromoCode._PERCENT_DISCOUNT)
        result = code.calculate_discounted_price(price)
        assert 0 <= result <= price

    @given(price=badge_price, discount=st.integers(min_value=1))
    def test_fixed_discount_reduces_price_or_free(self, price, discount):
        """Fixed discount never charges MORE than the original price."""
        code = PromoCode(discount=discount, discount_type=PromoCode._FIXED_DISCOUNT)
        result = code.calculate_discounted_price(price)
        assert result <= price

    @given(price=badge_price)
    def test_discount_none_is_free_badge(self, price):
        """None discount = free badge regardless of type."""
        code = PromoCode(discount=None, discount_type=PromoCode._FIXED_DISCOUNT)
        assert code.calculate_discounted_price(price) == 0

    @given(price=badge_price)
    def test_discount_zero_is_free_badge(self, price):
        """discount=0 is treated as 'full discount' (free badge) by design."""
        for dtype in [PromoCode._FIXED_DISCOUNT, PromoCode._FIXED_PRICE, PromoCode._PERCENT_DISCOUNT]:
            code = PromoCode(discount=0, discount_type=dtype)
            assert code.calculate_discounted_price(price) == 0

    @given(price=badge_price)
    def test_100_percent_discount_is_free(self, price):
        code = PromoCode(discount=100, discount_type=PromoCode._PERCENT_DISCOUNT)
        assert code.calculate_discounted_price(price) == 0

    def test_zero_price_always_free(self):
        """Zero price → 0 regardless of discount config."""
        for dtype in [PromoCode._FIXED_DISCOUNT, PromoCode._FIXED_PRICE, PromoCode._PERCENT_DISCOUNT]:
            code = PromoCode(discount=50, discount_type=dtype)
            assert code.calculate_discounted_price(0) == 0

    @given(price=badge_price, fixed_price=st.integers(min_value=1))
    def test_fixed_price_caps_at_original(self, price, fixed_price):
        """Fixed-price discount never raises the price above original."""
        code = PromoCode(discount=fixed_price, discount_type=PromoCode._FIXED_PRICE)
        result = code.calculate_discounted_price(price)
        assert result <= price

    @given(price=badge_price, pct=st.integers(min_value=1, max_value=100))
    def test_percent_discount_reduces_price(self, price, pct):
        """A percent discount never increases the price."""
        code = PromoCode(discount=pct, discount_type=PromoCode._PERCENT_DISCOUNT)
        result = code.calculate_discounted_price(price)
        assert result <= price


# ---------------------------------------------------------------------------
# ReceiptItem: total_amount
# ---------------------------------------------------------------------------

class TestReceiptItemInvariants:

    @given(amount=pos_cents, count=item_count)
    def test_total_amount_equals_amount_times_count(self, amount, count):
        item = ReceiptItem(amount=amount, count=count)
        assert item.total_amount == amount * count

    @given(amount=pos_cents, count=item_count)
    def test_credit_item_total_is_negative(self, amount, count):
        item = ReceiptItem(amount=-amount, count=count)
        assert item.total_amount < 0
        assert item.total_amount == -(amount * count)

    @given(amount=pos_cents, count=item_count)
    def test_total_amount_sign_matches_amount_sign(self, amount, count):
        pos_item = ReceiptItem(amount=amount, count=count)
        neg_item = ReceiptItem(amount=-amount, count=count)
        assert pos_item.total_amount > 0
        assert neg_item.total_amount < 0


# ---------------------------------------------------------------------------
# ReceiptTransaction: amount_left
# ---------------------------------------------------------------------------

class TestReceiptTransactionInvariants:

    @given(amount=pos_cents)
    def test_fresh_transaction_amount_left_equals_amount(self, amount):
        txn = ReceiptTransaction(amount=amount, refunded=0)
        assert txn.amount_left == amount

    @given(amount=pos_cents)
    def test_fully_refunded_amount_left_is_zero(self, amount):
        txn = ReceiptTransaction(amount=amount, refunded=amount)
        assert txn.amount_left == 0

    @given(amount=pos_cents, refunded=st.integers(min_value=0))
    def test_amount_left_is_non_negative_when_valid(self, amount, refunded):
        assume(refunded <= amount)
        txn = ReceiptTransaction(amount=amount, refunded=refunded)
        assert txn.amount_left >= 0
        assert txn.amount_left == amount - refunded

    @given(amount=pos_cents, partial=st.integers(min_value=1))
    def test_partial_refund_leaves_remainder(self, amount, partial):
        assume(partial < amount)
        txn = ReceiptTransaction(amount=amount, refunded=partial)
        assert txn.amount_left == amount - partial
        assert txn.amount_left > 0


# ---------------------------------------------------------------------------
# ModelReceipt: aggregate properties (require DB session)
#
# Uses the db fixture (autouse=True via conftest) for SAVEPOINT isolation.
# Each test method creates its own receipt to avoid cross-test interference.
# ---------------------------------------------------------------------------

def _make_receipt(session, items=None, pay_txns=None, refund_txns=None):
    """
    Create and flush a receipt with items and transactions.

    items: list of (amount_cents, count)
    pay_txns: list of (amount_cents,) — positive/payment transactions
    refund_txns: list of (amount_cents,) — will be stored as negative amounts
    """
    owner_id = str(uuid.uuid4())
    receipt = ModelReceipt(owner_model='Attendee', owner_id=owner_id)
    session.add(receipt)
    session.flush()

    for amount, count in (items or []):
        session.add(ReceiptItem(
            receipt_id=receipt.id,
            amount=amount,
            count=count,
            desc='test item',
            category=c.OTHER,
            department=c.OTHER_RECEIPT_ITEM,
            who='test',
        ))

    for (amount,) in (pay_txns or []):
        session.add(ReceiptTransaction(
            receipt_id=receipt.id,
            amount=amount,
            refunded=0,
            method=c.MANUAL,
            intent_id='',
            charge_id='',
            who='test',
            desc='test payment',
        ))

    for (amount,) in (refund_txns or []):
        session.add(ReceiptTransaction(
            receipt_id=receipt.id,
            amount=-amount,
            refunded=0,
            method=c.MANUAL,
            intent_id='',
            charge_id='',
            who='test',
            desc='test refund',
        ))

    session.flush()
    session.expire(receipt)
    return receipt


class TestReceiptAggregateInvariants:

    @given(
        items=st.lists(st.tuples(pos_cents, item_count), min_size=1, max_size=8),
    )
    @settings(max_examples=20)
    def test_item_total_equals_sum_of_items(self, items):
        expected = sum(a * c for a, c in items)
        with Session() as session:
            receipt = _make_receipt(session, items=items)
            assert receipt.item_total == expected

    @given(amount=pos_cents, count=item_count)
    @settings(max_examples=20)
    def test_exact_payment_zeroes_amount_owed(self, amount, count):
        total = amount * count
        with Session() as session:
            receipt = _make_receipt(
                session,
                items=[(amount, count)],
                pay_txns=[(total,)],
            )
            assert receipt.current_amount_owed == 0

    @given(
        items=st.lists(st.tuples(pos_cents, item_count), min_size=1, max_size=5),
        payment=pos_cents,
    )
    @settings(max_examples=20)
    def test_current_amount_owed_never_negative(self, items, payment):
        with Session() as session:
            receipt = _make_receipt(session, items=items, pay_txns=[(payment,)])
            assert receipt.current_amount_owed >= 0

    @given(amount=pos_cents, count=item_count)
    @settings(max_examples=20)
    def test_overpayment_does_not_create_debt(self, amount, count):
        total = amount * count
        with Session() as session:
            receipt = _make_receipt(
                session,
                items=[(amount, count)],
                pay_txns=[(total + 100,)],  # Overpay by $1
            )
            assert receipt.current_amount_owed == 0

    @given(amount=pos_cents, count=item_count)
    @settings(max_examples=20)
    def test_underpayment_leaves_correct_balance(self, amount, count):
        assume(amount * count > 1)
        total = amount * count
        with Session() as session:
            receipt = _make_receipt(
                session,
                items=[(amount, count)],
                pay_txns=[(total - 1,)],  # Underpay by 1 cent
            )
            assert receipt.current_amount_owed == 1

    @given(
        items=st.lists(st.tuples(pos_cents, item_count), min_size=1, max_size=5),
    )
    @settings(max_examples=20)
    def test_no_payment_full_amount_owed(self, items):
        expected = sum(a * c for a, c in items)
        with Session() as session:
            receipt = _make_receipt(session, items=items)
            assert receipt.current_amount_owed == expected

    @given(payment=pos_cents, refund=st.integers(min_value=1))
    @settings(max_examples=20)
    def test_partial_refund_conservation(self, payment, refund):
        assume(refund < payment)
        with Session() as session:
            receipt = _make_receipt(
                session,
                items=[(payment, 1)],
                pay_txns=[(payment,)],
                refund_txns=[(refund,)],
            )
            assert receipt.payment_total == payment
            assert receipt.refund_total == refund
            assert receipt.txn_total == payment - refund

    @given(
        payments=st.lists(pos_cents, min_size=2, max_size=5),
    )
    @settings(max_examples=15)
    def test_multiple_payments_sum_correctly(self, payments):
        total = sum(payments)
        with Session() as session:
            receipt = _make_receipt(
                session,
                items=[(total, 1)],
                pay_txns=[(p,) for p in payments],
            )
            assert receipt.payment_total == total
            assert receipt.txn_total == total
            assert receipt.current_amount_owed == 0

    def test_cancelled_transaction_excluded_from_payment_total(self):
        """Cancelled transactions don't count toward payment_total."""
        with Session() as session:
            owner_id = str(uuid.uuid4())
            receipt = ModelReceipt(owner_model='Attendee', owner_id=owner_id)
            session.add(receipt)
            session.flush()

            # Normal payment
            pay_txn = ReceiptTransaction(
                receipt_id=receipt.id,
                amount=1000,
                refunded=0,
                method=c.MANUAL,
                intent_id='',
                charge_id='',
                who='test',
                desc='payment',
            )
            session.add(pay_txn)

            # Cancelled payment
            cancelled_txn = ReceiptTransaction(
                receipt_id=receipt.id,
                amount=500,
                refunded=0,
                method=c.MANUAL,
                intent_id='',
                charge_id='',
                who='test',
                desc='cancelled',
                cancelled=datetime.now(UTC),
            )
            session.add(cancelled_txn)
            session.flush()
            session.expire(receipt)

            assert receipt.payment_total == 1000  # cancelled txn excluded
            assert receipt.txn_total == 1000

    def test_item_total_with_credits(self):
        """Credits (negative items) reduce item_total."""
        with Session() as session:
            owner_id = str(uuid.uuid4())
            receipt = ModelReceipt(owner_model='Attendee', owner_id=owner_id)
            session.add(receipt)
            session.flush()

            session.add(ReceiptItem(
                receipt_id=receipt.id, amount=1000, count=1,
                desc='charge', category=c.OTHER, department=c.OTHER_RECEIPT_ITEM, who='test',
            ))
            session.add(ReceiptItem(
                receipt_id=receipt.id, amount=-200, count=1,
                desc='credit', category=c.OTHER, department=c.OTHER_RECEIPT_ITEM, who='test',
            ))
            session.flush()
            session.expire(receipt)

            assert receipt.item_total == 800
            assert receipt.current_amount_owed == 800

    def test_open_receipt_items_excludes_closed(self):
        """open_receipt_items excludes items with a closed datetime."""
        with Session() as session:
            owner_id = str(uuid.uuid4())
            receipt = ModelReceipt(owner_model='Attendee', owner_id=owner_id)
            session.add(receipt)
            session.flush()

            open_item = ReceiptItem(
                receipt_id=receipt.id, amount=500, count=1,
                desc='open', category=c.OTHER, department=c.OTHER_RECEIPT_ITEM, who='test',
            )
            closed_item = ReceiptItem(
                receipt_id=receipt.id, amount=500, count=1,
                desc='closed', category=c.OTHER, department=c.OTHER_RECEIPT_ITEM, who='test',
                closed=datetime.now(UTC),
            )
            session.add(open_item)
            session.add(closed_item)
            session.flush()
            session.expire(receipt)

            assert len(receipt.receipt_items) == 2
            assert len(receipt.open_receipt_items) == 1
            assert receipt.open_receipt_items[0].desc == 'open'
