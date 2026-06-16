"""Business logic: turning a Transaction into Installments, and rolling
Installments back up into monthly summaries and card invoices.

Kept separate from views/models so the rules can be unit-tested in isolation
and read at a glance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.db.models import Sum

from .models import Installment, Kind, RepeatType

CENTS = Decimal("0.01")


def add_months(d: date, months: int) -> date:
    """Return ``d`` shifted by ``months``, snapped to the 1st of the month.

    Competence is always month-granular here, so day is forced to 1.
    """
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def split_amount(total: Decimal, n: int) -> list[Decimal]:
    """Split ``total`` into ``n`` parts that sum back to exactly ``total``.

    Decision: every part is floored to the cent and the LAST part absorbs the
    remaining cents. Change this single function if you prefer a different
    convention (e.g. first part larger, or spread the remainder).
    """
    if n <= 1:
        return [total.quantize(CENTS)]
    base = (total / n).quantize(CENTS, rounding=ROUND_DOWN)
    parts = [base] * (n - 1)
    parts.append(total - base * (n - 1))  # last part takes the leftover cents
    return [p.quantize(CENTS) for p in parts]


def generate_installments(transaction) -> list[Installment]:
    """Create and persist the Installment rows for a saved Transaction.

    - SINGLE      -> 1 installment with the full amount.
    - INSTALLMENT -> total split across ``repeat_count`` consecutive months.
    - RECURRING   -> the full amount repeated for ``repeat_count`` months.

    Replaces any existing installments (safe to call again after editing).
    """
    transaction.installments.all().delete()

    first = transaction.first_competence
    total = Decimal(transaction.total_amount)

    if transaction.repeat_type == RepeatType.SINGLE:
        amounts = [total.quantize(CENTS)]
    elif transaction.repeat_type == RepeatType.INSTALLMENT:
        amounts = split_amount(total, transaction.repeat_count)
    elif transaction.repeat_type == RepeatType.RECURRING:
        amounts = [total.quantize(CENTS)] * transaction.repeat_count
    else:  # pragma: no cover - defensive
        amounts = [total.quantize(CENTS)]

    rows = []
    n = len(amounts)
    for i, amount in enumerate(amounts):
        competence = add_months(first, i)
        due = _due_date_for(competence, transaction.card)
        rows.append(
            Installment(
                transaction=transaction,
                owner=transaction.owner,
                number=i + 1,
                of_total=n,
                competence_month=competence,
                due_date=due,
                amount=amount,
            )
        )
    return Installment.objects.bulk_create(rows)


def _due_date_for(competence: date, card) -> date | None:
    """Best-effort due date: the card's due_day within the competence month."""
    if card and card.due_day:
        day = min(card.due_day, 28)  # avoid invalid days for short months
        return date(competence.year, competence.month, day)
    return None


# --------------------------------------------------------------------------- #
# Read-side rollups
# --------------------------------------------------------------------------- #

@dataclass
class MonthlySummary:
    income: Decimal
    expense: Decimal

    @property
    def leftover(self) -> Decimal:  # "sobra"
        return self.income - self.expense


def monthly_summary(owner, month: date) -> MonthlySummary:
    """Total income, expense and leftover for one competence month."""
    qs = Installment.objects.filter(owner=owner, competence_month=month)
    income = qs.filter(transaction__kind=Kind.INCOME).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    expense = qs.filter(transaction__kind=Kind.EXPENSE).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    return MonthlySummary(income=income, expense=expense)


def card_invoice_total(card, month: date) -> Decimal:
    """Sum of a card's installments in a given competence month (the fatura)."""
    total = Installment.objects.filter(owner=card.owner, transaction__card=card, competence_month=month).aggregate(
        s=Sum("amount")
    )["s"]
    return total or Decimal("0")
