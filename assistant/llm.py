"""Thin client for a local Ollama model: question -> SQL, and rows -> answer.

Everything stays on the machine (Ollama runs in the same Docker network), so no
financial data leaves the host.
"""

from __future__ import annotations

import os

import requests

from .schema import EXAMPLES, SCHEMA_PROMPT

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
# Generous: local CPU inference of a 7B model is slow, and the very first call
# also pays the model-load cost. Ollama keeps it warm for ~5 min afterwards.
TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))


class LLMUnavailable(RuntimeError):
    pass


def _chat(messages, temperature=0.0) -> str:
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False,
                  "keep_alive": -1,  # keep the model resident between questions
                  "options": {"temperature": temperature}},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        raise LLMUnavailable(
            f"Não consegui falar com o Ollama em {OLLAMA_URL}. "
            f"Confira se o container está de pé e o modelo '{OLLAMA_MODEL}' foi baixado. ({e})"
        )
    return r.json()["message"]["content"]


def generate_sql(question: str) -> str:
    examples = "\n".join(f"P: {q}\nSQL: {s}" for q, s in EXAMPLES)
    messages = [
        {"role": "system", "content": SCHEMA_PROMPT + "\n\nExemplos:\n" + examples},
        {"role": "user", "content": question},
    ]
    return _chat(messages)


def summarize(question: str, columns, rows) -> str:
    # Keep the payload small: only a sample of rows goes to the model.
    sample = rows[:30]
    table = " | ".join(columns) + "\n" + "\n".join(
        " | ".join(str(c) for c in row) for row in sample
    )
    messages = [
        {"role": "system", "content": "Você é um assistente financeiro. Responda em "
                                      "português, de forma curta e direta, com base nos dados. "
                                      "Use R$ para valores."},
        {"role": "user", "content": f"Pergunta: {question}\n\nResultado da consulta:\n{table}\n\n"
                                    "Escreva a resposta para o usuário."},
    ]
    try:
        return _chat(messages, temperature=0.2)
    except LLMUnavailable:
        return ""  # summary is best-effort; the table is still shown
