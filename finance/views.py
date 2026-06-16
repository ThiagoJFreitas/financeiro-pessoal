"""Views. Every view that touches data filters by ``request.user`` (directly or
via the selectors module), which is what enforces account isolation.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render

from . import selectors
from .forms import CardForm, CategoryForm, InstallmentForm, TransactionForm
from .models import Card, Category, Installment, Kind, Transaction
from .services import generate_installments


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _parse_month(value: str | None) -> date | None:
    """Parse 'YYYY-MM' from the month picker into the 1st of that month."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError:
        return None


def _default_month(owner) -> date:
    """Open on the current month when possible, not the farthest future one.

    Installments can stretch years ahead (e.g. a 36x consórcio), so 'newest'
    would land on a sparse future month. Prefer the latest month with data that
    is not in the future; fall back to the earliest if everything is ahead.
    """
    months = selectors.months_with_data(owner)  # newest first
    if not months:
        return date.today().replace(day=1)
    this_month = date.today().replace(day=1)
    not_future = [m for m in months if m <= this_month]
    return not_future[0] if not_future else months[-1]


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Conta criada! Bem-vindo ao seu planejamento.")
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

@login_required
def dashboard(request):
    owner = request.user
    month = _parse_month(request.GET.get("month")) or _default_month(owner)

    summary = selectors.monthly_summary(owner, month)
    cards = selectors.cards_for_month(owner, month)
    recent = selectors.recent_months(owner, 12)

    context = {
        "month": month,
        "available_months": selectors.months_with_data(owner),
        "summary": summary,
        "cards": cards,
        "pending_review": Transaction.objects.filter(owner=owner, needs_review=True).count(),
        "bar_chart": json.dumps(selectors.income_expense_series(owner, recent)),
        "pie_chart": json.dumps(selectors.expense_by_category(owner, month)),
        "line_chart": json.dumps(selectors.leftover_series(owner, recent)),
    }
    return render(request, "finance/dashboard.html", context)


# --------------------------------------------------------------------------- #
# Transactions / Installments
# --------------------------------------------------------------------------- #

@login_required
def transaction_list(request):
    owner = request.user
    qs = Installment.objects.filter(owner=owner).select_related(
        "transaction", "transaction__card", "transaction__category"
    )

    month = _parse_month(request.GET.get("month"))
    kind = request.GET.get("kind") or ""
    card_id = request.GET.get("card") or ""
    category_id = request.GET.get("category") or ""
    status = request.GET.get("status") or ""

    if month:
        qs = qs.filter(competence_month=month)
    if kind in (Kind.EXPENSE, Kind.INCOME):
        qs = qs.filter(transaction__kind=kind)
    if card_id:
        qs = qs.filter(transaction__card_id=card_id)
    if category_id:
        qs = qs.filter(transaction__category_id=category_id)
    if status == "paid":
        qs = qs.filter(paid=True)
    elif status == "unpaid":
        qs = qs.filter(paid=False)

    review = request.GET.get("review") or ""
    if review == "pending":
        qs = qs.filter(transaction__needs_review=True)

    context = {
        "installments": qs,
        "total": selectors.queryset_total(qs),
        "available_months": selectors.months_with_data(owner),
        "cards": Card.objects.filter(owner=owner),
        "categories": Category.objects.filter(owner=owner),
        "pending_review": Transaction.objects.filter(owner=owner, needs_review=True).count(),
        "filters": {"month": request.GET.get("month", ""), "kind": kind, "card": card_id,
                    "category": category_id, "status": status, "review": review},
    }
    return render(request, "finance/transaction_list.html", context)


@login_required
def transaction_toggle_review(request, pk):
    """Clear (or set) the 'pendente de revisão' flag on a transaction."""
    tx = get_object_or_404(Transaction, pk=pk, owner=request.user)
    if request.method == "POST":
        tx.needs_review = not tx.needs_review
        tx.save(update_fields=["needs_review"])
    return redirect(request.META.get("HTTP_REFERER") or "transaction_list")


@login_required
def transactions_mark_all_reviewed(request):
    """Bulk: mark every pending transaction as reviewed."""
    if request.method == "POST":
        n = Transaction.objects.filter(owner=request.user, needs_review=True).update(needs_review=False)
        messages.success(request, f"{n} lançamentos marcados como revisados.")
    return redirect(request.META.get("HTTP_REFERER") or "transaction_list")


@login_required
def transaction_create(request):
    owner = request.user
    form = TransactionForm(request.POST or None, owner=owner)
    if request.method == "POST" and form.is_valid():
        tx = form.save(commit=False)
        tx.owner = owner
        tx.save()
        generate_installments(tx)
        messages.success(request, "Lançamento criado e parcelas geradas.")
        return redirect("transaction_list")
    return render(request, "finance/transaction_form.html", {"form": form, "title": "Novo lançamento"})


@login_required
def transaction_edit(request, pk):
    owner = request.user
    tx = get_object_or_404(Transaction, pk=pk, owner=owner)
    form = TransactionForm(request.POST or None, instance=tx, owner=owner)
    if request.method == "POST" and form.is_valid():
        tx = form.save(commit=False)
        tx.owner = owner
        tx.save()
        generate_installments(tx)  # regenerate parcelas to match the edits
        messages.success(request, "Lançamento atualizado.")
        return redirect("transaction_list")
    return render(request, "finance/transaction_form.html", {"form": form, "title": "Editar lançamento"})


@login_required
def transaction_delete(request, pk):
    tx = get_object_or_404(Transaction, pk=pk, owner=request.user)
    if request.method == "POST":
        tx.delete()
        messages.success(request, "Lançamento excluído.")
        return redirect("transaction_list")
    return render(request, "finance/confirm_delete.html", {"object": tx, "title": "Excluir lançamento"})


@login_required
def installment_edit(request, pk):
    inst = get_object_or_404(Installment, pk=pk, owner=request.user)
    form = InstallmentForm(request.POST or None, instance=inst)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Parcela atualizada.")
        return redirect(request.GET.get("next") or "transaction_list")
    return render(request, "finance/installment_form.html", {"form": form, "installment": inst})


@login_required
def installment_toggle_paid(request, pk):
    inst = get_object_or_404(Installment, pk=pk, owner=request.user)
    if request.method == "POST":
        inst.paid = not inst.paid
        inst.paid_date = date.today() if inst.paid else None
        inst.save(update_fields=["paid", "paid_date"])
    return redirect(request.META.get("HTTP_REFERER") or "transaction_list")


# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #

@login_required
def card_list(request):
    return render(request, "finance/card_list.html", {"cards": Card.objects.filter(owner=request.user)})


@login_required
def card_create(request):
    form = CardForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        card = form.save(commit=False)
        card.owner = request.user
        card.save()
        messages.success(request, "Cartão criado.")
        return redirect("card_list")
    return render(request, "finance/card_form.html", {"form": form, "title": "Novo cartão"})


@login_required
def card_edit(request, pk):
    card = get_object_or_404(Card, pk=pk, owner=request.user)
    form = CardForm(request.POST or None, instance=card)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cartão atualizado.")
        return redirect("card_list")
    return render(request, "finance/card_form.html", {"form": form, "title": "Editar cartão"})


@login_required
def card_delete(request, pk):
    card = get_object_or_404(Card, pk=pk, owner=request.user)
    if request.method == "POST":
        card.delete()
        messages.success(request, "Cartão excluído.")
        return redirect("card_list")
    return render(request, "finance/confirm_delete.html", {"object": card, "title": "Excluir cartão"})


@login_required
def card_detail(request, pk):
    """Per-card invoice view: parcelas spread across months, like the xlsx tab."""
    owner = request.user
    card = get_object_or_404(Card, pk=pk, owner=owner)
    installments = (
        Installment.objects.filter(owner=owner, transaction__card=card)
        .select_related("transaction")
        .order_by("competence_month", "transaction__description")
    )
    # Group by competence month.
    months: dict[date, list] = {}
    for inst in installments:
        months.setdefault(inst.competence_month, []).append(inst)
    grouped = [
        {"month": m, "items": items, "total": sum(i.amount for i in items)}
        for m, items in sorted(months.items())
    ]
    return render(request, "finance/card_detail.html", {"card": card, "grouped": grouped})


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #

@login_required
def category_list(request):
    return render(request, "finance/category_list.html", {"categories": Category.objects.filter(owner=request.user)})


@login_required
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cat = form.save(commit=False)
        cat.owner = request.user
        cat.save()
        messages.success(request, "Categoria criada.")
        return redirect("category_list")
    return render(request, "finance/category_form.html", {"form": form, "title": "Nova categoria"})


@login_required
def category_edit(request, pk):
    cat = get_object_or_404(Category, pk=pk, owner=request.user)
    form = CategoryForm(request.POST or None, instance=cat)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Categoria atualizada.")
        return redirect("category_list")
    return render(request, "finance/category_form.html", {"form": form, "title": "Editar categoria"})


@login_required
def category_delete(request, pk):
    cat = get_object_or_404(Category, pk=pk, owner=request.user)
    if request.method == "POST":
        cat.delete()
        messages.success(request, "Categoria excluída.")
        return redirect("category_list")
    return render(request, "finance/confirm_delete.html", {"object": cat, "title": "Excluir categoria"})


# --------------------------------------------------------------------------- #
# Report: A Pagar
# --------------------------------------------------------------------------- #

@login_required
def report_to_pay(request):
    owner = request.user
    month = _parse_month(request.GET.get("month"))
    card_id = request.GET.get("card") or None
    category_id = request.GET.get("category") or None
    only_unpaid = request.GET.get("status", "unpaid") != "all"

    qs = selectors.to_pay(owner, month=month, card_id=card_id, category_id=category_id, only_unpaid=only_unpaid)

    # Totals grouped by card for the report's chart/summary.
    by_card: dict[str, float] = {}
    for inst in qs:
        name = inst.transaction.card.name if inst.transaction.card else "Sem cartão / Boleto"
        by_card[name] = by_card.get(name, 0.0) + float(inst.amount)

    context = {
        "installments": qs,
        "total": selectors.queryset_total(qs),
        "available_months": selectors.months_with_data(owner),
        "cards": Card.objects.filter(owner=owner),
        "categories": Category.objects.filter(owner=owner, kind=Kind.EXPENSE),
        "filters": {"month": request.GET.get("month", ""), "card": card_id or "",
                    "category": category_id or "", "status": request.GET.get("status", "unpaid")},
        "card_chart": json.dumps({"labels": list(by_card.keys()), "data": list(by_card.values())}),
    }
    return render(request, "finance/report_to_pay.html", context)
