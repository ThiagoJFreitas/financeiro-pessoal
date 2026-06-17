"""Force a password change before letting a flagged user do anything else.

Used for seed accounts created with a temporary password (e.g. user/pass): on
first login the user is redirected to the change-password page until they set a
real one. Self-registered users are never flagged.
"""

from django.shortcuts import redirect
from django.urls import reverse

from .models import Profile


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            must_change = Profile.objects.filter(user=user, must_change_password=True).exists()
            if must_change:
                allowed = {reverse("force_password_change"), reverse("logout")}
                if request.path not in allowed and not request.path.startswith("/static/"):
                    return redirect("force_password_change")
        return self.get_response(request)
