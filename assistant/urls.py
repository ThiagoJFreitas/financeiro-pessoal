from django.urls import path

from . import views

urlpatterns = [
    path("assistente/", views.chat, name="assistant_chat"),
]
