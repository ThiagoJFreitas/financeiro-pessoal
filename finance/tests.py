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
