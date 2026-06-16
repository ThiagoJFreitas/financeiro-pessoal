"""Create a starter set of categories and auto-assign them to transactions by
keyword. Only fills transactions that don't have a category yet, so it's safe to
re-run and never overrides a manual choice.

    python manage.py seed_categories --user thiago
"""

from __future__ import annotations

import unicodedata

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from finance.models import Category, Kind, Transaction


def _norm(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper()


# (name, kind, color, [keywords]) — first matching keyword wins, top to bottom.
# Palavras-chave genéricas (não personalizadas). Ajuste para a sua realidade.
CATEGORY_DEFS = [
    # Expenses
    ("Moradia", Kind.EXPENSE, "#0d6efd", ["ALUGUEL", "CONDOMINIO", "LUZ", "ENERGIA", "AGUA", "GAS", "IPTU"]),
    ("Saúde", Kind.EXPENSE, "#dc3545", ["FARMACIA", "DROGARIA", "REMEDIO", "DENTISTA", "MEDICO",
                                        "HOSPITAL", "CLINICA", "EXAME", "PLANO DE SAUDE", "PSICOLOGO"]),
    ("Alimentação", Kind.EXPENSE, "#198754", ["MERCADO", "SUPERMERCADO", "PADARIA", "RESTAURANTE",
                                              "LANCHE", "IFOOD", "ALMOCO", "ACOUGUE", "HORTIFRUTI"]),
    ("Transporte", Kind.EXPENSE, "#fd7e14", ["GASOLINA", "COMBUSTIVEL", "UBER", "ESTACIONAMENTO",
                                             "PEDAGIO", "IPVA", "ONIBUS", "METRO", "MECANICO"]),
    ("Telefonia/Internet", Kind.EXPENSE, "#6610f2", ["INTERNET", "CELULAR", "TELEFONE", "TV"]),
    ("Educação", Kind.EXPENSE, "#20c997", ["FACULDADE", "CURSO", "ESCOLA", "LIVRO", "MATERIAL", "MENSALIDADE"]),
    ("Compras", Kind.EXPENSE, "#d63384", ["AMAZON", "MERCADO LIVRE", "ALIEXPRESS", "SHOPEE", "SHEIN",
                                          "ROUPA", "LOJA", "PRESENTE", "ELETRONICO"]),
    ("Lazer/Viagem", Kind.EXPENSE, "#ffc107", ["VIAGEM", "HOTEL", "PASSAGEM", "CINEMA", "STREAMING",
                                               "ACADEMIA", "BAR", "SHOW"]),
    ("Serviços/Financeiro", Kind.EXPENSE, "#6c757d", ["BANCO", "TARIFA", "JUROS", "SEGURO", "CONSORCIO",
                                                      "IMPOSTO", "ASSINATURA", "ADVOGADO", "CONTADOR"]),
    ("Família", Kind.EXPENSE, "#0dcaf0", ["FRALDA", "CRECHE", "BABA", "BRINQUEDO", "PET"]),
    # Income
    ("Salário", Kind.INCOME, "#198754", ["SALARIO", "PAGAMENTO", "PRO LABORE"]),
    ("Renda - Extra", Kind.INCOME, "#20c997", ["FREELANCE", "BONUS", "DECIMO", "FERIAS", "EXTRA"]),
    ("Renda - Aluguel", Kind.INCOME, "#0d6efd", ["ALUGUEL"]),
]


class Command(BaseCommand):
    help = "Cria categorias iniciais e classifica lançamentos sem categoria."

    def add_arguments(self, parser):
        parser.add_argument("--user", default="thiago")

    def handle(self, *args, **opts):
        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"Usuário '{opts['user']}' não existe.")

        # Build categories and an ordered keyword index per kind.
        rules = []  # (kind, keyword_norm, category)
        for name, kind, color, keywords in CATEGORY_DEFS:
            cat, _ = Category.objects.get_or_create(owner=user, name=name, kind=kind, defaults={"color": color})
            if cat.color != color:
                cat.color = color
                cat.save(update_fields=["color"])
            for kw in keywords:
                rules.append((kind, _norm(kw), cat))

        assigned = 0
        for tx in Transaction.objects.filter(owner=user, category__isnull=True):
            desc = _norm(tx.description)
            for kind, kw, cat in rules:
                if tx.kind == kind and kw in desc:
                    tx.category = cat
                    tx.save(update_fields=["category"])
                    assigned += 1
                    break

        total = Category.objects.filter(owner=user).count()
        uncategorized = Transaction.objects.filter(owner=user, category__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"{total} categorias garantidas. {assigned} lançamentos categorizados. "
            f"{uncategorized} ainda sem categoria."
        ))
