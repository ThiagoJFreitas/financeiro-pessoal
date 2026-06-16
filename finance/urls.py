from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    # Lançamentos
    path("lancamentos/", views.transaction_list, name="transaction_list"),
    path("lancamentos/novo/", views.transaction_create, name="transaction_create"),
    path("lancamentos/<int:pk>/editar/", views.transaction_edit, name="transaction_edit"),
    path("lancamentos/<int:pk>/excluir/", views.transaction_delete, name="transaction_delete"),
    path("lancamentos/<int:pk>/revisado/", views.transaction_toggle_review, name="transaction_toggle_review"),
    path("lancamentos/revisar-todos/", views.transactions_mark_all_reviewed, name="transactions_mark_all_reviewed"),

    # Parcelas
    path("parcelas/<int:pk>/editar/", views.installment_edit, name="installment_edit"),
    path("parcelas/<int:pk>/pago/", views.installment_toggle_paid, name="installment_toggle_paid"),

    # Cartões
    path("cartoes/", views.card_list, name="card_list"),
    path("cartoes/novo/", views.card_create, name="card_create"),
    path("cartoes/<int:pk>/", views.card_detail, name="card_detail"),
    path("cartoes/<int:pk>/editar/", views.card_edit, name="card_edit"),
    path("cartoes/<int:pk>/excluir/", views.card_delete, name="card_delete"),

    # Categorias
    path("categorias/", views.category_list, name="category_list"),
    path("categorias/nova/", views.category_create, name="category_create"),
    path("categorias/<int:pk>/editar/", views.category_edit, name="category_edit"),
    path("categorias/<int:pk>/excluir/", views.category_delete, name="category_delete"),

    # Relatórios
    path("relatorios/a-pagar/", views.report_to_pay, name="report_to_pay"),
]
