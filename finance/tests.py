from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Card, Installment, Kind, RepeatType, Transaction
from .services import add_months, generate_installments, monthly_summary, split_amount


class SplitAmountTests(TestCase):
    def test_splits_sum_back_to_total(self):
        # 302.65 / 3 -> last installment absorbs the leftover cent.
        parts = split_amount(Decimal("302.65"), 3)
        self.assertEqual(parts, [Decimal("100.88"), Decimal("100.88"), Decimal("100.89")])
        self.assertEqual(sum(parts), Decimal("302.65"))

    def test_single_part(self):
        self.assertEqual(split_amount(Decimal("100.00"), 1), [Decimal("100.00")])


class AddMonthsTests(TestCase):
    def test_rolls_over_year(self):
        self.assertEqual(add_months(date(2025, 11, 1), 3), date(2026, 2, 1))

    def test_snaps_to_first(self):
        self.assertEqual(add_months(date(2025, 1, 15), 0), date(2025, 1, 1))


class GenerateInstallmentsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u1", password="x")

    def _tx(self, **kwargs):
        defaults = dict(
            owner=self.user, kind=Kind.EXPENSE, description="t",
            total_amount=Decimal("300.00"), first_competence=date(2026, 1, 1),
        )
        defaults.update(kwargs)
        return Transaction.objects.create(**defaults)

    def test_installment_spreads_across_months(self):
        tx = self._tx(repeat_type=RepeatType.INSTALLMENT, repeat_count=3)
        generate_installments(tx)
        insts = list(tx.installments.order_by("number"))
        self.assertEqual(len(insts), 3)
        self.assertEqual([i.competence_month for i in insts],
                         [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)])
        self.assertEqual(sum(i.amount for i in insts), Decimal("300.00"))

    def test_recurring_repeats_full_amount(self):
        tx = self._tx(repeat_type=RepeatType.RECURRING, repeat_count=3, total_amount=Decimal("100.00"))
        generate_installments(tx)
        self.assertEqual([i.amount for i in tx.installments.all()],
                         [Decimal("100.00"), Decimal("100.00"), Decimal("100.00")])

    def test_regenerate_replaces_old_installments(self):
        tx = self._tx(repeat_type=RepeatType.INSTALLMENT, repeat_count=3)
        generate_installments(tx)
        tx.repeat_count = 2
        generate_installments(tx)
        self.assertEqual(tx.installments.count(), 2)


class IsolationTests(TestCase):
    def test_summary_only_sees_owner_data(self):
        a = User.objects.create_user("a", password="x")
        b = User.objects.create_user("b", password="x")
        for u, amount in [(a, "100.00"), (b, "999.00")]:
            tx = Transaction.objects.create(
                owner=u, kind=Kind.EXPENSE, description="t", total_amount=Decimal(amount),
                first_competence=date(2026, 1, 1),
            )
            generate_installments(tx)
        summary = monthly_summary(a, date(2026, 1, 1))
        self.assertEqual(summary.expense, Decimal("100.00"))  # b's 999 not included


class BulkActionTests(TestCase):
    def setUp(self):
        from django.test import Client
        self.user = User.objects.create_user("bulk", password="x")
        self.client = Client()
        self.client.login(username="bulk", password="x")
        self.tx = Transaction.objects.create(
            owner=self.user, kind=Kind.EXPENSE, description="compra",
            total_amount=Decimal("300.00"), repeat_type=RepeatType.INSTALLMENT,
            repeat_count=3, first_competence=date(2026, 1, 1),
        )
        generate_installments(self.tx)
        self.ids = list(self.tx.installments.values_list("pk", flat=True))

    def test_bulk_pay(self):
        self.client.post("/lancamentos/acao-em-massa/", {"action": "pay", "ids": self.ids[:2]})
        self.assertEqual(Installment.objects.filter(pk__in=self.ids, paid=True).count(), 2)

    def test_bulk_delete_removes_empty_transaction(self):
        self.client.post("/lancamentos/acao-em-massa/", {"action": "delete", "ids": self.ids})
        self.assertEqual(Installment.objects.filter(pk__in=self.ids).count(), 0)
        # all parcelas gone -> the parent transaction is cleaned up too
        self.assertFalse(Transaction.objects.filter(pk=self.tx.pk).exists())

    def test_bulk_delete_keeps_transaction_with_remaining(self):
        self.client.post("/lancamentos/acao-em-massa/", {"action": "delete", "ids": self.ids[:1]})
        self.assertTrue(Transaction.objects.filter(pk=self.tx.pk).exists())
        self.assertEqual(self.tx.installments.count(), 2)

    def test_cannot_act_on_other_users_rows(self):
        other = User.objects.create_user("intruder", password="x")
        c = self.__class__.client_for(other)
        c.post("/lancamentos/acao-em-massa/", {"action": "delete", "ids": self.ids})
        self.assertEqual(Installment.objects.filter(pk__in=self.ids).count(), 3)  # untouched

    @staticmethod
    def client_for(user):
        from django.test import Client
        c = Client()
        c.force_login(user)
        return c


class CommitmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("c1", password="x")
        self.tx = Transaction.objects.create(
            owner=self.user, kind=Kind.EXPENSE, description="Geladeira",
            total_amount=Decimal("300.00"), repeat_type=RepeatType.INSTALLMENT,
            repeat_count=3, first_competence=date(2026, 1, 1),
        )
        generate_installments(self.tx)

    def test_progress_counts_paid(self):
        from finance.selectors import transaction_progress
        first = self.tx.installments.order_by("number").first()
        first.paid = True
        first.save()
        p = transaction_progress(self.tx)
        self.assertEqual(p["paid_count"], 1)
        self.assertEqual(p["total_count"], 3)
        self.assertEqual(p["remaining"], Decimal("200.00"))
        self.assertEqual(p["end_month"], date(2026, 3, 1))
        self.assertFalse(p["settled"])

    def test_settle_marks_all_paid(self):
        from finance.selectors import transaction_progress
        self.tx.installments.filter(paid=False).update(paid=True)
        self.assertTrue(transaction_progress(self.tx)["settled"])

    def test_burndown_decreases(self):
        from finance.selectors import card_burndown
        card = Card.objects.create(owner=self.user, name="X")
        self.tx.card = card
        self.tx.save()
        bd = card_burndown(card)
        # 3 unpaid months: 300 -> 200 -> 100 (stepping down)
        self.assertEqual(bd["data"], [300.0, 200.0, 100.0])

    def test_to_pay_grouped_by_card(self):
        from finance.selectors import to_pay_grouped
        card = Card.objects.create(owner=self.user, name="NUBANK")
        self.tx.card = card
        self.tx.save()
        groups = to_pay_grouped(self.user, by="card")
        self.assertEqual(groups[0]["name"], "NUBANK")
        self.assertEqual(groups[0]["total"], Decimal("300.00"))
        self.assertEqual(groups[0]["ends"], date(2026, 3, 1))
