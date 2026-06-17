"""Views. Every view that touches data filters by ``request.user`` (directly or
via the selectors module), which is what enforces account isolation.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from . import selectors
from .forms import CardForm, CategoryForm, InstallmentForm, RegisterForm, TransactionForm
from .models import Card, Category, Installment, Kind, Profile, Transaction
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


def _safe_next(request, *candidates, fallback="transaction_list"):
    """Redirect target that only allows same-site URLs (prevents open redirect)."""
    for cand in candidates:
        if cand and url_has_allowed_host_and_scheme(
            cand, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return cand
    return fallback


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Conta criada! Bem-vindo ao seu planejamento.")
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


@login_required
def force_password_change(request):
    """Seed accounts (user/pass) must set a real password before anything else."""
    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)  # don't log the user out
        Profile.objects.update_or_create(user=request.user, defaults={"must_change_password": False})
        messages.success(request, "Senha definida! Bem-vindo.")
        return redirect("dashboard")
    return render(request, "registration/force_password_change.html", {"form": form})


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
        "statement": selectors.monthly_statement(owner, month),
        "month_str": month.strftime("%Y-%m"),
        "bar_chart": selectors.income_expense_series(owner, recent),
        "pie_chart": selectors.expense_by_category(owner, month),
        "line_chart": selectors.leftover_series(owner, recent),
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
    return redirect(_safe_next(request, request.META.get("HTTP_REFERER")))


@login_required
def transactions_mark_all_reviewed(request):
    """Bulk: mark every pending transaction as reviewed."""
    if request.method == "POST":
        n = Transaction.objects.filter(owner=request.user, needs_review=True).update(needs_review=False)
        messages.success(request, f"{n} lançamentos marcados como revisados.")
    return redirect(_safe_next(request, request.META.get("HTTP_REFERER")))


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
def transaction_detail(request, pk):
    """Commitment detail: remaining months, progress and actions."""
    owner = request.user
    tx = get_object_or_404(Transaction, pk=pk, owner=owner)
    installments = tx.installments.all()
    progress = selectors.transaction_progress(tx)
    # Mini burn-down: outstanding (unpaid) balance falling month by month.
    unpaid = [i for i in installments if not i.paid]
    months = [i.competence_month for i in installments]
    burndown = {
        "labels": [m.strftime("%m/%Y") for m in months],
        "data": [float(sum((j.amount for j in unpaid if j.competence_month >= m), Decimal("0"))) for m in months],
    }
    return render(request, "finance/transaction_detail.html", {
        "tx": tx, "installments": installments, "progress": progress, "burndown": burndown,
    })


@login_required
def transaction_settle(request, pk):
    """Quitar: mark every remaining (unpaid) parcela of this commitment as paid."""
    tx = get_object_or_404(Transaction, pk=pk, owner=request.user)
    if request.method == "POST":
        n = tx.installments.filter(paid=False).update(paid=True, paid_date=date.today())
        messages.success(request, f"{n} parcelas quitadas.")
    return redirect("transaction_detail", pk=tx.pk)


@login_required
def installment_edit(request, pk):
    inst = get_object_or_404(Installment, pk=pk, owner=request.user)
    form = InstallmentForm(request.POST or None, instance=inst)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Parcela atualizada.")
        return redirect(_safe_next(request, request.GET.get("next")))
    return render(request, "finance/installment_form.html", {"form": form, "installment": inst})


@login_required
def installment_toggle_paid(request, pk):
    inst = get_object_or_404(Installment, pk=pk, owner=request.user)
    if request.method == "POST":
        inst.paid = not inst.paid
        inst.paid_date = date.today() if inst.paid else None
        inst.save(update_fields=["paid", "paid_date"])
    return redirect(_safe_next(request, request.META.get("HTTP_REFERER")))


@login_required
def installments_bulk(request):
    """Bulk action over selected installments: confirm payment or delete.

    Owner-scoped (a user can only act on their own rows). The confirmation
    prompt happens in the browser before this is called.
    """
    if request.method == "POST":
        ids = request.POST.getlist("ids")
        action = request.POST.get("action")
        qs = Installment.objects.filter(owner=request.user, pk__in=ids)

        if action == "pay":
            n = qs.update(paid=True, paid_date=date.today())
            messages.success(request, f"{n} lançamento(s) marcados como pagos.")
        elif action == "delete":
            tx_ids = set(qs.values_list("transaction_id", flat=True))
            n = qs.count()
            qs.delete()
            # Drop parent transactions that no longer have any installments.
            Transaction.objects.filter(owner=request.user, pk__in=tx_ids, installments__isnull=True).delete()
            messages.success(request, f"{n} lançamento(s) excluído(s).")

    return redirect(_safe_next(request, request.META.get("HTTP_REFERER")))


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
def card_pay_month(request, pk):
    """'Paguei' for a whole card invoice in a month: toggle all its parcelas."""
    card = get_object_or_404(Card, pk=pk, owner=request.user)
    month = _parse_month(request.GET.get("month"))
    if request.method == "POST" and month:
        qs = Installment.objects.filter(owner=request.user, transaction__card=card, competence_month=month)
        if qs.filter(paid=False).exists():
            qs.update(paid=True, paid_date=date.today())   # pay the remainder
        else:
            qs.update(paid=False, paid_date=None)            # undo
    return redirect(_safe_next(request, request.META.get("HTTP_REFERER"), fallback="dashboard"))


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
    unpaid = [i for i in installments if not i.paid]
    summary = {
        "remaining": sum((i.amount for i in unpaid), Decimal("0")),
        "ends": max((i.competence_month for i in unpaid), default=None),
    }
    return render(request, "finance/card_detail.html", {
        "card": card, "grouped": grouped, "summary": summary,
        "burndown": selectors.card_burndown(card),
    })


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

    # Group totals by card or category (user toggles), with "when it ends".
    group_by = request.GET.get("group_by") if request.GET.get("group_by") in ("card", "category") else "card"
    groups = selectors.to_pay_grouped(owner, by=group_by, month=month, card_id=card_id, category_id=category_id)

    context = {
        "installments": qs,
        "total": selectors.queryset_total(qs),
        "available_months": selectors.months_with_data(owner),
        "cards": Card.objects.filter(owner=owner),
        "categories": Category.objects.filter(owner=owner, kind=Kind.EXPENSE),
        "group_by": group_by,
        "groups": groups,
        "group_chart": {"labels": [g["name"] for g in groups], "data": [float(g["total"]) for g in groups]},
        "filters": {"month": request.GET.get("month", ""), "card": card_id or "",
                    "category": category_id or "", "status": request.GET.get("status", "unpaid")},
    }
    return render(request, "finance/report_to_pay.html", context)
