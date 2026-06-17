"""Read-side queries. All take ``owner`` first and filter by it, so a user can
never read another user's data. Views call these instead of hitting the ORM
directly, keeping the isolation rule in one place.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Count, Max, Sum

from .models import Card, Installment, Kind, Transaction
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


# --------------------------------------------------------------------------- #
# Commitments / progress / burn-down
# --------------------------------------------------------------------------- #

def transaction_progress(tx) -> dict:
    """Payment progress for one commitment (a Transaction and its parcelas)."""
    insts = list(tx.installments.all())
    total = sum((i.amount for i in insts), Decimal("0"))
    paid = sum((i.amount for i in insts if i.paid), Decimal("0"))
    unpaid = [i for i in insts if not i.paid]
    next_installment = min(unpaid, key=lambda i: i.competence_month) if unpaid else None
    return {
        "total": total,
        "paid": paid,
        "remaining": total - paid,
        "paid_count": sum(1 for i in insts if i.paid),
        "total_count": len(insts),
        "next_installment": next_installment,
        "end_month": max((i.competence_month for i in insts), default=None),
        "settled": not unpaid,
    }


def card_burndown(card) -> dict:
    """Outstanding (unpaid) balance for a card across months — a burn-down.

    outstanding(M) = sum of UNPAID installments with competence >= M, so it
    steps down both as months pass and as parcelas get paid.
    """
    insts = list(Installment.objects.filter(owner=card.owner, transaction__card=card))
    months = sorted({i.competence_month for i in insts})
    unpaid = [i for i in insts if not i.paid]
    labels, data = [], []
    for m in months:
        outstanding = sum((i.amount for i in unpaid if i.competence_month >= m), Decimal("0"))
        labels.append(m.strftime("%m/%Y"))
        data.append(float(outstanding))
    return {"labels": labels, "data": data}


def to_pay_grouped(owner, by: str = "card", month=None, card_id=None, category_id=None) -> list[dict]:
    """Unpaid expenses grouped by card or category, with total + 'when it ends'."""
    qs = to_pay(owner, month=month, card_id=card_id, category_id=category_id, only_unpaid=True)
    key = "transaction__category__name" if by == "category" else "transaction__card__name"
    fallback = "Sem categoria" if by == "category" else "Sem cartão / Boleto"
    rows = (
        qs.values(key)
        .annotate(total=Sum("amount"), ends=Max("competence_month"), qtd=Count("id"))
        .order_by("-total")
    )
    return [{"name": r[key] or fallback, "total": r["total"], "ends": r["ends"], "qtd": r["qtd"]} for r in rows]


def monthly_statement(owner, month: date) -> dict:
    """The month as a statement, like the spreadsheet column: one line per card
    (its invoice total) and one line per non-card bill, plus income lines and
    totals. Each line carries its paid state so the UI can show a 'Paguei' toggle.
    """
    insts = (
        Installment.objects.filter(owner=owner, competence_month=month)
        .select_related("transaction", "transaction__card", "transaction__category")
    )
    cards: dict = {}
    bills, incomes = [], []
    total_expense = expense_paid = Decimal("0")
    total_income = income_received = Decimal("0")

    for i in insts:
        tx = i.transaction
        if tx.kind == Kind.INCOME:
            incomes.append(i)
            total_income += i.amount
            if i.paid:
                income_received += i.amount
        elif tx.card_id:
            c = cards.setdefault(tx.card_id, {"card": tx.card, "total": Decimal("0"), "paid_all": True})
            c["total"] += i.amount
            if not i.paid:
                c["paid_all"] = False
            total_expense += i.amount
            if i.paid:
                expense_paid += i.amount
        else:  # non-card bill (aluguel, plano de saúde, etc.)
            bills.append(i)
            total_expense += i.amount
            if i.paid:
                expense_paid += i.amount

    card_lines = sorted(cards.values(), key=lambda r: r["total"], reverse=True)
    bills.sort(key=lambda i: i.amount, reverse=True)
    incomes.sort(key=lambda i: i.amount, reverse=True)
    return {
        "card_lines": card_lines,
        "bills": bills,
        "incomes": incomes,
        "total_expense": total_expense,
        "expense_unpaid": total_expense - expense_paid,
        "total_income": total_income,
        "income_pending": total_income - income_received,
        "leftover": total_income - total_expense,
    }


def active_commitments(owner) -> list[dict]:
    """Multi-installment commitments (parcelados/recorrentes) not yet settled.

    Drives the home list that shows '1/6' and links to the detail page.
    """
    txs = (
        Transaction.objects.filter(owner=owner, repeat_count__gt=1, installments__paid=False)
        .distinct()
        .select_related("card", "category")
    )
    result = []
    for tx in txs:
        prog = transaction_progress(tx)
        if prog["settled"]:
            continue
        result.append({"tx": tx, **prog})
    result.sort(key=lambda r: r["next_installment"].competence_month if r["next_installment"] else date.max)
    return result
