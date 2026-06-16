"""Validate LLM-generated SQL before it ever touches the database.

This is one layer of several (the read-only role and the per-user views are the
others). It blocks anything that isn't a single, read-only SELECT over the
``analytics`` views, and forces a row limit.
"""

from __future__ import annotations

import re

MAX_ROWS = 200

# Anything that could mutate, escalate, or chain a second statement.
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"copy|set|reset|do|call|merge|comment|vacuum|analyze|begin|commit|"
    r"rollback|savepoint|pg_sleep|pg_read_file|lo_import|lo_export)\b",
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


def validate(sql: str) -> str:
    """Return a safe, row-limited SELECT or raise UnsafeSQL."""
    sql = clean_sql(sql)
    if not sql:
        raise UnsafeSQL("SQL vazio.")
    if ";" in sql:
        raise UnsafeSQL("Apenas um comando é permitido (sem ';').")
    if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
        raise UnsafeSQL("Apenas consultas SELECT são permitidas.")
    if FORBIDDEN.search(sql):
        raise UnsafeSQL("A consulta contém uma operação não permitida.")
    # Must only reference the analytics views.
    tables = re.findall(r"\b(?:from|join)\s+([a-zA-Z0-9_\.\"]+)", sql, re.IGNORECASE)
    for t in tables:
        name = t.strip('"').lower()
        if not name.startswith("analytics.v_"):
            raise UnsafeSQL(f"Tabela não permitida: {t}. Use apenas as views analytics.v_*.")
    # Force a row cap if the model didn't add one.
    if not re.search(r"\blimit\b", sql, re.IGNORECASE):
        sql = f"{sql} LIMIT {MAX_ROWS}"
    return sql
