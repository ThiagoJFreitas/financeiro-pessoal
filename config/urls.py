"""Root URL configuration."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from finance.views import register

urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth (Django built-ins + a simple register view).
    path("entrar/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("cadastro/", register, name="register"),

    path("", include("assistant.urls")),
    path("", include("finance.urls")),
]
