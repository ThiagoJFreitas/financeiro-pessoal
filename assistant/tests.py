from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import override_settings

from finance.models import Installment, Kind, Transaction
from .sql_guard import MAX_ROWS, UnsafeSQL, clean_sql, validate


class SqlGuardTests(TestCase):
    def test_allows_select_over_views_and_adds_limit(self):
        sql = validate("SELECT * FROM analytics.v_installments WHERE kind='EXPENSE'")
        self.assertIn("analytics.v_installments", sql)
        self.assertIn(f"LIMIT {MAX_ROWS}", sql)

    def test_strips_markdown_fences(self):
        self.assertEqual(
            clean_sql("```sql\nSELECT 1 FROM analytics.v_cards\n```"),
            "SELECT 1 FROM analytics.v_cards",
        )

    def test_rejects_non_select(self):
        for bad in [
            "UPDATE finance_installment SET paid=true",
            "DELETE FROM analytics.v_cards",
            "DROP VIEW analytics.v_cards",
        ]:
            with self.assertRaises(UnsafeSQL):
                validate(bad)

    def test_rejects_multiple_statements(self):
        with self.assertRaises(UnsafeSQL):
            validate("SELECT 1 FROM analytics.v_cards; DROP TABLE finance_card")

    def test_rejects_base_tables(self):
        with self.assertRaises(UnsafeSQL):
            validate("SELECT * FROM finance_installment")

    def test_rejects_set_guc_injection(self):
        # A model trying to widen its own scope must be blocked.
        with self.assertRaises(UnsafeSQL):
            validate("SET app.current_user_id = 1")


def _pg():
    return connection.vendor == "postgresql"


@override_settings()
class GucIsolationTests(TestCase):
    """The analytics views must only ever return the session user's rows."""

    def setUp(self):
        if not _pg():
            self.skipTest("Isolamento via GUC requer PostgreSQL.")
        self.a = User.objects.create_user("alice", password="x")
        self.b = User.objects.create_user("bob", password="x")
        for u, amount in [(self.a, "100.00"), (self.b, "999.00")]:
            tx = Transaction.objects.create(
                owner=u, kind=Kind.EXPENSE, description="t", total_amount=Decimal(amount),
                first_competence=date(2026, 1, 1),
            )
            Installment.objects.create(
                transaction=tx, owner=u, number=1, of_total=1,
                competence_month=date(2026, 1, 1), amount=Decimal(amount),
            )
        call_command("setup_assistant_db")

    def _sum_for(self, user_id):
        with connection.cursor() as cur:
            cur.execute("SET app.current_user_id = %s", (str(user_id),))
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM analytics.v_installments")
            return cur.fetchone()[0]

    def test_user_sees_only_own_rows(self):
        self.assertEqual(self._sum_for(self.a.id), Decimal("100.00"))
        self.assertEqual(self._sum_for(self.b.id), Decimal("999.00"))

    def test_unset_guc_returns_nothing(self):
        with connection.cursor() as cur:
            cur.execute("RESET app.current_user_id")
            cur.execute("SELECT COUNT(*) FROM analytics.v_installments")
            self.assertEqual(cur.fetchone()[0], 0)  # fails closed
