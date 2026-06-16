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


def _answer(question: str, owner_id: int) -> dict:
    try:
        raw_sql = llm.generate_sql(question)
    except llm.LLMUnavailable as e:
        return {"error": str(e)}

    try:
        sql = validate(raw_sql)
    except UnsafeSQL as e:
        return {"error": f"Consulta gerada foi bloqueada por segurança: {e}", "raw_sql": raw_sql}

    try:
        columns, rows = run_readonly(sql, owner_id)
    except AssistantDBError as e:
        return {"error": f"Erro ao executar a consulta: {e}", "sql": sql}

    summary = llm.summarize(question, columns, rows) if rows else "Nenhum resultado encontrado."
    return {"sql": sql, "columns": columns, "rows": rows, "summary": summary}
