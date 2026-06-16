"""Forms. The key detail: card/category dropdowns are scoped to the logged-in
user, so you can never accidentally attach your transaction to someone else's
card. ``owner`` is set in the view, never trusted from the form.
"""

from django import forms

from .models import Card, Category, Installment, Transaction


class BootstrapMixin:
    """Adds Bootstrap classes to every widget without repeating ourselves."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class TransactionForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Transaction
        fields = [
            "kind", "description", "category", "card", "purchase_date",
            "total_amount", "repeat_type", "repeat_count", "first_competence", "notes",
        ]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"type": "date"}),
            "first_competence": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "kind": "Tipo",
            "description": "Descrição",
            "category": "Categoria",
            "card": "Cartão (deixe vazio se for conta/boleto)",
            "purchase_date": "Data da compra",
            "total_amount": "Valor total",
            "repeat_type": "Repetição",
            "repeat_count": "Nº de parcelas/meses",
            "first_competence": "Mês inicial (competência)",
            "notes": "Observações",
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        if owner is not None:
            self.fields["category"].queryset = Category.objects.filter(owner=owner)
            self.fields["card"].queryset = Card.objects.filter(owner=owner)

    def clean(self):
        data = super().clean()
        # first_competence is month-granular; force day 1.
        fc = data.get("first_competence")
        if fc:
            data["first_competence"] = fc.replace(day=1)
        if data.get("repeat_type") == "SINGLE":
            data["repeat_count"] = 1
        elif (data.get("repeat_count") or 0) < 1:
            self.add_error("repeat_count", "Informe um número maior ou igual a 1.")
        return data


class CardForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Card
        fields = ["name", "closing_day", "due_day", "limit"]
        labels = {"name": "Nome", "closing_day": "Dia do fechamento", "due_day": "Dia do vencimento", "limit": "Limite"}


class CategoryForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "kind", "color"]
        labels = {"name": "Nome", "kind": "Tipo", "color": "Cor"}
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class InstallmentForm(BootstrapMixin, forms.ModelForm):
    """Edit a single parcela (value can vary month to month) and its status."""

    class Meta:
        model = Installment
        fields = ["amount", "competence_month", "due_date", "paid", "paid_date"]
        widgets = {
            "competence_month": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "paid_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "amount": "Valor", "competence_month": "Competência", "due_date": "Vencimento",
            "paid": "Pago?", "paid_date": "Data do pagamento",
        }
