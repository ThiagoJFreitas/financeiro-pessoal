"""Create a demo account (teste/teste) with random, fictitious data — handy for
screenshots and trying the app out.

    python manage.py seed_demo

Re-running wipes and recreates the demo account's data.
"""

import random
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from finance.models import Card, Category, Kind, RepeatType, Transaction
from finance.services import add_months, generate_installments

USERNAME = "teste"
PASSWORD = "teste"

EXPENSE_CATS = [
    ("Moradia", "#0d6efd"), ("Alimentação", "#198754"), ("Transporte", "#fd7e14"),
    ("Saúde", "#dc3545"), ("Lazer", "#ffc107"), ("Educação", "#20c997"),
    ("Compras", "#d63384"), ("Serviços", "#6c757d"),
]
INCOME_CATS = [("Salário", "#198754"), ("Freelance", "#0dcaf0"), ("Investimentos", "#6610f2")]

CARDS = ["Nubank", "Inter", "C6 Bank"]

RECURRING_BILLS = [  # (descrição, valor, categoria)
    ("Aluguel", 1800, "Moradia"), ("Conta de Luz", 185, "Moradia"),
    ("Internet Fibra", 120, "Serviços"), ("Plano de Saúde", 460, "Saúde"),
    ("Academia", 99, "Saúde"), ("Streaming", 55, "Lazer"), ("Faculdade", 720, "Educação"),
]
INSTALLMENTS = [  # (descrição, total, nº parcelas, categoria)
    ("Notebook Dell", 4500, 10, "Compras"), ("Geladeira Brastemp", 3600, 12, "Compras"),
    ("Viagem Praia", 2400, 6, "Lazer"), ("iPhone 15", 6000, 12, "Compras"),
    ("Sofá Retrátil", 1800, 6, "Compras"), ("Curso de Inglês", 900, 3, "Educação"),
    ("Pneus do Carro", 2000, 4, "Transporte"),
]
SINGLE_EXPENSES = [  # (descrição, valor aprox, categoria)
    ("Supermercado", 480, "Alimentação"), ("Restaurante", 130, "Alimentação"),
    ("Gasolina", 250, "Transporte"), ("Uber", 45, "Transporte"),
    ("Farmácia", 92, "Saúde"), ("Cinema", 70, "Lazer"), ("iFood", 78, "Alimentação"),
    ("Presente", 150, "Compras"),
]
INCOMES = [("Salário", 7500, "Salário"), ("Freelance Projeto X", 2200, "Freelance"),
           ("Dividendos", 380, "Investimentos")]


class Command(BaseCommand):
    help = "Cria a conta teste/teste com dados fictícios para demonstração."

    def handle(self, *args, **opts):
        random.seed(42)  # reproduzível
        user, _ = User.objects.get_or_create(username=USERNAME)
        user.set_password(PASSWORD)
        user.save()
        Transaction.objects.filter(owner=user).delete()

        cats = {name: Category.objects.get_or_create(
            owner=user, name=name, kind=Kind.EXPENSE, defaults={"color": color})[0]
            for name, color in EXPENSE_CATS}
        for name, color in INCOME_CATS:
            cats[name] = Category.objects.get_or_create(
                owner=user, name=name, kind=Kind.INCOME, defaults={"color": color})[0]
        cards = {n: Card.objects.get_or_create(owner=user, name=n,
                 defaults={"due_day": random.choice([5, 10, 15, 20])})[0] for n in CARDS}

        this_month = date.today().replace(day=1)
        start = add_months(this_month, -4)  # começa 4 meses atrás

        def jitter(v):
            return Decimal(str(round(v * random.uniform(0.92, 1.08), 2)))

        # Receitas recorrentes + avulsas
        self._tx(user, Kind.INCOME, "Salário", jitter(7500), RepeatType.RECURRING, 9, start,
                 cats["Salário"], None)
        for desc, val, cat in INCOMES[1:]:
            self._tx(user, Kind.INCOME, desc, jitter(val), RepeatType.SINGLE, 1,
                     add_months(this_month, random.randint(-2, 0)), cats[cat], None)

        # Contas recorrentes (sem cartão)
        for desc, val, cat in RECURRING_BILLS:
            self._tx(user, Kind.EXPENSE, desc, jitter(val), RepeatType.RECURRING, 9, start,
                     cats[cat], None)

        # Compras parceladas (no cartão)
        for desc, total, n, cat in INSTALLMENTS:
            self._tx(user, Kind.EXPENSE, desc, Decimal(total), RepeatType.INSTALLMENT, n,
                     add_months(this_month, random.randint(-3, 0)),
                     cats[cat], random.choice(list(cards.values())))

        # Despesas avulsas espalhadas nos últimos meses
        for m in range(-3, 1):
            for desc, val, cat in random.sample(SINGLE_EXPENSES, k=random.randint(3, 5)):
                self._tx(user, Kind.EXPENSE, desc, jitter(val), RepeatType.SINGLE, 1,
                         add_months(this_month, m), cats[cat],
                         random.choice(list(cards.values()) + [None, None]))

        # Marca como pago a maioria das parcelas de meses passados
        from finance.models import Installment
        for inst in Installment.objects.filter(owner=user, competence_month__lt=this_month):
            if random.random() < 0.85:
                inst.paid = True
                inst.paid_date = inst.competence_month
                inst.save(update_fields=["paid", "paid_date"])

        n = Transaction.objects.filter(owner=user).count()
        self.stdout.write(self.style.SUCCESS(
            f"Conta '{USERNAME}/{PASSWORD}' criada com {n} lançamentos fictícios."))

    def _tx(self, user, kind, desc, amount, rtype, count, competence, category, card):
        tx = Transaction.objects.create(
            owner=user, kind=kind, description=desc, total_amount=amount,
            repeat_type=rtype, repeat_count=count, first_competence=competence,
            category=category, card=card,
        )
        generate_installments(tx)
        return tx
