"""Create the read-only analytics layer the text-to-SQL assistant queries.

Defense in depth, all enforced by Postgres (not by trusting the LLM):
- A dedicated schema ``analytics`` with views that filter every row by the
  session GUC ``app.current_user_id`` (set per-request by our code). If the GUC
  is not set, ``current_setting(..., true)`` returns NULL and the views return
  zero rows — so a leaked/forgotten setting fails closed.
- A login role ``assistant_ro`` granted SELECT only on those views (never on the
  base tables), so even crafted SQL cannot read another user's rows or write.

Idempotent and Postgres-only (no-op on SQLite).
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

# Password kept in sync with ASSISTANT_DATABASE_URL (local Docker only).
RO_ROLE = "assistant_ro"
RO_PASSWORD = "assistant_ro_pw"

SQL = f"""
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.v_transactions AS
SELECT t.id, t.kind, t.description, t.total_amount, t.repeat_type,
       t.repeat_count, t.first_competence, t.purchase_date, t.needs_review,
       c.name AS card_name, cat.name AS category_name, t.owner_id
FROM finance_transaction t
LEFT JOIN finance_card c ON c.id = t.card_id
LEFT JOIN finance_category cat ON cat.id = t.category_id
WHERE t.owner_id = current_setting('app.current_user_id', true)::int;

CREATE OR REPLACE VIEW analytics.v_installments AS
SELECT i.id, i.competence_month, i.due_date, i.amount, i.paid, i.paid_date,
       i.number, i.of_total, t.description, t.kind, t.repeat_type,
       c.name AS card_name, cat.name AS category_name, i.owner_id
FROM finance_installment i
JOIN finance_transaction t ON t.id = i.transaction_id
LEFT JOIN finance_card c ON c.id = t.card_id
LEFT JOIN finance_category cat ON cat.id = t.category_id
WHERE i.owner_id = current_setting('app.current_user_id', true)::int;

CREATE OR REPLACE VIEW analytics.v_cards AS
SELECT id, name, due_day, closing_day, "limit", owner_id
FROM finance_card
WHERE owner_id = current_setting('app.current_user_id', true)::int;

CREATE OR REPLACE VIEW analytics.v_categories AS
SELECT id, name, kind, owner_id
FROM finance_category
WHERE owner_id = current_setting('app.current_user_id', true)::int;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{RO_ROLE}') THEN
        CREATE ROLE {RO_ROLE} LOGIN PASSWORD '{RO_PASSWORD}';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA analytics TO {RO_ROLE};
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO {RO_ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO {RO_ROLE};
"""


class Command(BaseCommand):
    help = "Cria schema analytics (views por usuário) + role read-only para o assistente."

    def handle(self, *args, **opts):
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING(
                "Não é Postgres — assistente requer Postgres. Nada a fazer."
            ))
            return
        with connection.cursor() as cur:
            cur.execute(SQL)
        self.stdout.write(self.style.SUCCESS("Schema analytics + role read-only configurados."))
