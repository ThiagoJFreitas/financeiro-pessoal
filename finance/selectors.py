"""Read-side queries. All take ``owner`` first and filter by it, so a user can
never read another user's data. Views call these instead of hitting the ORM
directly, keeping the isolation rule in one place.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Sum

from .models import Card, Installment, Kind
from .services import add_months, card_invoice_total, monthly_summary


def months_with_data(owner) -> list[date]:
    """Distinct competence months that have any installment, newest first."""
    qs = (
        Installment.objects.filter(owner=owner)
        .values_list("competence_month", flat=True)
        .distinct()
        .order_by("-competence_month")
    )
    return list(qs)


def cards_for_month(owner, month: date) -> list[dict]:
    """Each card with its invoice total + due day for the given month."""
    result = []
    for card in Card.objects.filter(owner=owner):
        total = card_invoice_total(card, month)
        if total:
            result.append({"card": card, "total": total, "due_day": card.due_day})
    return sorted(result, key=lambda r: r["total"], reverse=True)


def income_expense_series(owner, months: list[date]) -> dict:
    """Labels + income/expense lists for the bar chart over several months."""
    labels, income, expense = [], [], []
    for m in months:
        s = monthly_summary(owner, m)
        labels.append(m.strftime("%m/%Y"))
        income.append(float(s.income))
        expense.append(float(s.expense))
    return {"labels": labels, "income": income, "expense": expense}


def expense_by_category(owner, month: date) -> dict:
    """Expense totals grouped by category for the pie chart of one month."""
    rows = (
        Installment.objects.filter(owner=owner, competence_month=month, transaction__kind=Kind.EXPENSE)
        .values("transaction__category__name", "transaction__category__color")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    labels, data, colors = [], [], []
    for r in rows:
        labels.append(r["transaction__category__name"] or "Sem categoria")
        data.append(float(r["total"]))
        colors.append(r["transaction__category__color"] or "#6c757d")
    return {"labels": labels, "data": data, "colors": colors}


def leftover_series(owner, months: list[date]) -> dict:
    """Sobra (leftover) per month for the line chart, oldest first."""
    labels, data = [], []
    for m in months:
        s = monthly_summary(owner, m)
        labels.append(m.strftime("%m/%Y"))
        data.append(float(s.leftover))
    return {"labels": labels, "data": data}


def recent_months(owner, count: int = 12) -> list[date]:
    """Up to ``count`` months that contain data, returned oldest -> newest."""
    months = months_with_data(owner)[:count]
    return list(reversed(months))


def to_pay(owner, month: date | None = None, card_id=None, category_id=None, only_unpaid=True):
    """Filtered installment queryset for the 'A Pagar' report."""
    qs = Installment.objects.filter(owner=owner, transaction__kind=Kind.EXPENSE).select_related(
        "transaction", "transaction__card", "transaction__category"
    )
    if month:
        qs = qs.filter(competence_month=month)
    if card_id:
        qs = qs.filter(transaction__card_id=card_id)
    if category_id:
        qs = qs.filter(transaction__category_id=category_id)
    if only_unpaid:
        qs = qs.filter(paid=False)
    return qs


def queryset_total(qs) -> Decimal:
    return qs.aggregate(s=Sum("amount"))["s"] or Decimal("0")
