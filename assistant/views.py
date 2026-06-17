"""Chatbot page: natural-language question -> safe SQL -> answer.

Pipeline: generate_sql (Ollama) -> validate (sql_guard) -> run_readonly
(read-only role + per-user views) -> summarize (Ollama). Each failure mode is
caught and shown to the user instead of 500-ing.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import llm
from .runner import AssistantDBError, run_readonly
from .schema import EXAMPLES
from .sql_guard import UnsafeSQL, validate


@login_required
def chat(request):
    context = {"examples": [q for q, _ in EXAMPLES]}

    if request.method == "POST":
        question = (request.POST.get("question") or "").strip()
        context["question"] = question
        if question:
            context.update(_answer(question, request.user.id))

    return render(request, "assistant/chat.html", context)


MAX_ATTEMPTS = 2  # first try + one self-correction


def _answer(question: str, owner_id: int) -> dict:
    prior_sql, last_error = None, None

    for _ in range(MAX_ATTEMPTS):
        try:
            raw_sql = llm.generate_sql(question, prior_sql=prior_sql, error=last_error)
        except llm.LLMUnavailable as e:
            return {"error": str(e)}

        try:
            sql = validate(raw_sql)
        except UnsafeSQL as e:
            prior_sql, last_error = raw_sql, str(e)
            continue  # show the model the error and let it retry

        try:
            columns, rows = run_readonly(sql, owner_id)
        except AssistantDBError as e:
            prior_sql, last_error = sql, str(e)
            continue

        if not rows:
            return {"summary": "Nenhum resultado encontrado para essa pergunta."}
        # Natural-language answer; fall back to a plain rendering if the model
        # that writes the summary is unavailable, so the user always sees text.
        summary = llm.summarize(question, columns, rows) or _fallback_text(columns, rows)
        return {"summary": summary}

    # Both attempts failed — be honest and helpful instead of dumping SQL.
    return {"error": (
        "Não consegui montar uma consulta confiável para essa pergunta. "
        "Tente reformular de forma mais direta — por exemplo, citando um período "
        "('em 2026'), uma categoria ou um cartão."
    )}


def _fallback_text(columns, rows) -> str:
    """Readable text from raw rows when the LLM summary is unavailable."""
    if len(columns) == 1 and len(rows) == 1:
        return f"{columns[0]}: {rows[0][0]}"
    lines = []
    for row in rows[:20]:
        lines.append(", ".join(f"{c}: {v}" for c, v in zip(columns, row)))
    return "\n".join(lines)
