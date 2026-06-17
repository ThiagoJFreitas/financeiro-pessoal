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

    def test_rejects_destructive_and_admin_commands(self):
        attacks = [
            "DROP DATABASE financeiro",
            "DROP TABLE finance_installment",
            "TRUNCATE finance_installment",
            "ALTER USER thiago WITH PASSWORD 'hacked'",
            "ALTER ROLE assistant_ro SUPERUSER",
            "CREATE ROLE hacker LOGIN PASSWORD 'x'",
            "GRANT ALL ON finance_installment TO assistant_ro",
            "UPDATE auth_user SET password='x'",
        ]
        for sql in attacks:
            with self.assertRaises(UnsafeSQL, msg=sql):
                validate(sql)

    def test_rejects_set_config_isolation_bypass(self):
        # Calling set_config inside a SELECT could change the per-user GUC and
        # leak another user's rows — must be blocked.
        with self.assertRaises(UnsafeSQL):
            validate("SELECT set_config('app.current_user_id','999',false), * FROM analytics.v_installments")

    def test_rejects_data_modifying_cte(self):
        with self.assertRaises(UnsafeSQL):
            validate("WITH x AS (DELETE FROM finance_installment RETURNING *) SELECT * FROM x")

    def test_rejects_file_and_exfil_functions(self):
        for sql in [
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT * FROM dblink('host=evil', 'select 1') AS t(x int)",
            "SELECT pg_sleep(10)",
        ]:
            with self.assertRaises(UnsafeSQL, msg=sql):
                validate(sql)

    def test_rejects_comments(self):
        with self.assertRaises(UnsafeSQL):
            validate("SELECT 1 FROM analytics.v_cards -- DROP TABLE x")

    def test_allows_keyword_inside_string_literal(self):
        # 'drop'/'delete' as DATA (inside quotes) must NOT be blocked.
        sql = validate("SELECT SUM(amount) FROM analytics.v_installments "
                       "WHERE description = 'pagamento do drop e delete'")
        self.assertIn("analytics.v_installments", sql)

    def test_allows_legit_functions(self):
        # EXTRACT(... FROM CURRENT_DATE) and replace() are legitimate.
        sql = validate("SELECT EXTRACT(year FROM CURRENT_DATE), "
                       "replace(description,'a','b') FROM analytics.v_installments")
        self.assertIn("analytics.v_installments", sql)


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
