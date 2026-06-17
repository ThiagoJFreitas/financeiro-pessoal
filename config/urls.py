"""Root URL configuration."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django_otp.admin import OTPAdminSite

from finance.views import force_password_change, register

# Require a verified 2FA token to access the admin (/chefao). Enroll a user with
# `manage.py setup_2fa`.
admin.site.__class__ = OTPAdminSite

urlpatterns = [
    # Admin numa URL não óbvia (dificulta bots que varrem /admin).
    path("chefao/", admin.site.urls),

    # Auth (Django built-ins + a simple register view).
    path("entrar/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("cadastro/", register, name="register"),
    path("trocar-senha/", force_password_change, name="force_password_change"),

    # Esqueci a senha (fluxo padrão do Django, por e-mail).
    path("senha/reset/", auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        email_template_name="registration/password_reset_email.html",
        subject_template_name="registration/password_reset_subject.txt",
    ), name="password_reset"),
    path("senha/reset/enviado/", auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html",
    ), name="password_reset_done"),
    path("senha/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html",
    ), name="password_reset_confirm"),
    path("senha/reset/concluido/", auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html",
    ), name="password_reset_complete"),

    path("", include("assistant.urls")),
    path("", include("finance.urls")),
]
