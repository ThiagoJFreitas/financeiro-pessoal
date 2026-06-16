"""Domain models for the personal finance planner.

Core idea: a ``Transaction`` (a purchase / income event) expands into one or
more ``Installment`` rows (parcelas). Everything the dashboards show — a card's
monthly invoice, the monthly leftover ("sobra") — is computed by summing
``Installment`` rows, never stored, so the numbers can't drift out of sync.

Every record carries ``owner`` so each user only ever sees their own planning.
"""

from django.conf import settings
from django.db import models


class Kind(models.TextChoices):
    EXPENSE = "EXPENSE", "Despesa"
    INCOME = "INCOME", "Receita"


class RepeatType(models.TextChoices):
    SINGLE = "SINGLE", "Único"
    INSTALLMENT = "INSTALLMENT", "Parcelado"   # total split across N months
    RECURRING = "RECURRING", "Fixo/Recorrente"  # same amount every month


class OwnedQuerySet(models.QuerySet):
    """Convenience for the pervasive ``filter(owner=user)`` pattern."""

    def owned_by(self, user):
        return self.filter(owner=user)


class Category(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.EXPENSE)
    color = models.CharField(max_length=7, default="#6c757d", help_text="Hex usado nos gráficos")

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        unique_together = ("owner", "name", "kind")
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Card(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cards")
    name = models.CharField(max_length=80)
    closing_day = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Dia do fechamento da fatura")
    due_day = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Dia do vencimento da fatura")
    limit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        unique_together = ("owner", "name")

    def __str__(self):
        return self.name


class Transaction(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.EXPENSE)
    description = models.CharField(max_length=160)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions")
    # card == null means a non-card bill (aluguel, luz, água...).
    card = models.ForeignKey(Card, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions")
    purchase_date = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    repeat_type = models.CharField(max_length=12, choices=RepeatType.choices, default=RepeatType.SINGLE)
    repeat_count = models.PositiveSmallIntegerField(default=1, help_text="Nº de parcelas (parcelado) ou meses (recorrente)")
    # First competence month (always stored as the 1st of the month).
    first_competence = models.DateField()
    notes = models.TextField(blank=True)
    # Imported from the spreadsheet -> flagged so the user can verify/fix values.
    needs_review = models.BooleanField(default=False, help_text="Pendente de revisão (importado da planilha)")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ["-first_competence", "description"]

    def __str__(self):
        return f"{self.description} ({self.get_kind_display()})"


class Installment(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="installments")
    # Denormalised so list/report queries can filter without joining Transaction.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="installments")
    number = models.PositiveSmallIntegerField(default=1)
    of_total = models.PositiveSmallIntegerField(default=1)
    competence_month = models.DateField(help_text="Mês da fatura/competência (sempre dia 1)")
    due_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid = models.BooleanField(default=False)
    paid_date = models.DateField(null=True, blank=True)

    objects = OwnedQuerySet.as_manager()

    class Meta:
        ordering = ["competence_month", "number"]
        indexes = [
            models.Index(fields=["owner", "competence_month"]),
        ]

    @property
    def label(self):
        if self.of_total > 1:
            return f"{self.transaction.description} {self.number}/{self.of_total}"
        return self.transaction.description

    def __str__(self):
        return f"{self.label} - {self.amount}"
