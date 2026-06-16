from django.contrib import admin

from .models import Card, Category, Installment, Transaction


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("description", "kind", "owner", "card", "total_amount", "repeat_type", "first_competence")
    list_filter = ("kind", "repeat_type", "owner", "card")
    search_fields = ("description",)
    inlines = [InstallmentInline]


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ("label", "owner", "competence_month", "amount", "paid")
    list_filter = ("paid", "owner", "competence_month")
    search_fields = ("transaction__description",)


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "due_day", "closing_day", "limit")
    list_filter = ("owner",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "owner")
    list_filter = ("kind", "owner")
