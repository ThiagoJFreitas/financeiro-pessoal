"""Execute validated SQL against the read-only analytics role.

The per-user isolation is enforced here + in the views: we open the read-only
connection, set ``app.current_user_id`` for this transaction only, and run the
query. The views filter by that GUC, so the query can only ever see this user's
rows — regardless of what SQL the model produced.
"""

from __future__ import annotations

import os

import psycopg2

ASSISTANT_DATABASE_URL = os.getenv("ASSISTANT_DATABASE_URL", "")


class AssistantDBError(RuntimeError):
    pass


def run_readonly(sql: str, owner_id: int):
    """Return (columns, rows) for the given user. Read-only, row-scoped."""
    if not ASSISTANT_DATABASE_URL:
        raise AssistantDBError("ASSISTANT_DATABASE_URL não configurado (requer Postgres/Docker).")
    conn = psycopg2.connect(ASSISTANT_DATABASE_URL)
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            # SET LOCAL keeps the GUC scoped to this transaction only.
            cur.execute("SET LOCAL app.current_user_id = %s", (str(owner_id),))
            cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
        conn.rollback()  # nothing to commit; release cleanly
        return columns, rows
    except psycopg2.Error as e:
        conn.rollback()
        raise AssistantDBError(str(e).strip())
    finally:
        conn.close()
