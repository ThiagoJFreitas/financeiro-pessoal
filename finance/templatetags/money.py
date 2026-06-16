"""Currency formatting for templates: {{ value|brl }} -> 'R$ 1.234,56'."""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def brl(value):
    try:
        value = Decimal(str(value or 0))
    except (InvalidOperation, TypeError):
        return value
    # Format with US grouping, then swap separators to pt-BR style.
    formatted = f"{value:,.2f}"  # 1,234.56
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"
