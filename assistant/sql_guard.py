"""Validate LLM-generated SQL before it ever touches the database.

This is one layer of several. The strongest guarantees come from the database
itself: the assistant connects with a read-only role that can only SELECT the
``analytics`` views — it cannot write, DROP, ALTER, change passwords, read files
or even see the base tables. This module is defense-in-depth on top of that, and
also closes the one gap the role can't: a query calling ``set_config`` to change
the per-user GUC and peek at another user's rows.

Approach: scan a copy of the SQL with string literals and comments removed (so
real data like a description 'pagamento do drop' never trips a keyword), and
require a single read-only SELECT over the analytics views.
"""

from __future__ import annotations

import re

MAX_ROWS = 200

# Dangerous tokens. Most can't even run inside a SELECT, but we block them as
# belt-and-suspenders. The genuinely important ones are the function-callable
# risks that CAN appear inside a SELECT: set_config (isolation bypass), the
# pg_*/lo_* file & admin functions, dblink (exfiltration), and setval/nextval.
FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|copy|"
    r"set_config|"
    r"pg_sleep|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|"
    r"pg_rotate_logfile|pg_read_file|pg_read_binary_file|pg_stat_file|pg_ls_dir|"
    r"lo_import|lo_export|lo_unlink|dblink|setval|nextval|password"
    r")\b",
    re.IGNORECASE,
)

# Base / system tables the assistant must never touch (the views expose only the
# data it is allowed to see). The read-only role also blocks these.
FORBIDDEN_TABLES = re.compile(
    r"\b(finance_\w+|auth_\w+|django_\w+|pg_\w+|pg_catalog|information_schema)\b",
    re.IGNORECASE,
)


class UnsafeSQL(ValueError):
    pass


def clean_sql(raw: str) -> str:
    """Strip markdown fences/labels the model often adds around the SQL."""
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
    text = text.replace("```", "").strip()
    # Some models prefix "SQL:"; drop it.
    text = re.sub(r"^\s*sql\s*:", "", text, flags=re.IGNORECASE).strip()
    return text.rstrip(";").strip()


def _strip_literals(sql: str) -> str:
    """Remove single-quoted string literals so their CONTENT can't trip a
    keyword/table check. Quoted identifiers ("...") are kept so a quoted base
    table like "finance_user" is still caught.
    """
    return re.sub(r"'(?:''|[^'])*'", " ", sql)


def validate(sql: str) -> str:
    """Return a safe, row-limited SELECT or raise UnsafeSQL."""
    sql = clean_sql(sql)
    if not sql:
        raise UnsafeSQL("SQL vazio.")

    scan = _strip_literals(sql)  # check keywords/tables ignoring string data

    if ";" in scan:
        raise UnsafeSQL("Apenas um comando é permitido (sem ';').")
    if "--" in scan or "/*" in scan:
        raise UnsafeSQL("Comentários não são permitidos na consulta.")
    if not re.match(r"^\s*(select|with)\b", scan, re.IGNORECASE):
        raise UnsafeSQL("Apenas consultas SELECT são permitidas.")
    if FORBIDDEN.search(scan):
        raise UnsafeSQL("A consulta contém uma operação não permitida.")
    if FORBIDDEN_TABLES.search(scan):
        raise UnsafeSQL("A consulta referencia tabelas não permitidas. Use apenas as views analytics.v_*.")

    # Force a row cap if the model didn't add one.
    if not re.search(r"\blimit\b", scan, re.IGNORECASE):
        sql = f"{sql} LIMIT {MAX_ROWS}"
    return sql
