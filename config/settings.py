"""
Django settings for the personal finance project.

Reads configuration from environment variables so the same code runs
locally (SQLite) and in the cloud (Postgres). See .env.example.
"""

import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load a local .env file if present (no-op in production where env vars are set
# by the hosting platform).
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


# SECURITY: in production set SECRET_KEY via environment.
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-_&*9x5gvks8di@4ki@c$^@x&y-86yj^$91#7i=658uw%88m@$-",
)

# Default to False for safety: a deploy that forgets to set DEBUG stays locked
# down. Local development opts back in via .env (DEBUG=True).
DEBUG = env_bool("DEBUG", False)

# Comma-separated list, e.g. "meuapp.onrender.com,localhost"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

# Render/other proxies need the external host trusted for CSRF on POST.
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]


INSTALLED_APPS = [
    # finance first so its templates/registration/* override the copies that
    # ship with django.contrib.admin (the password-reset pages).
    "finance",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "assistant",
    # Admin hardening.
    "axes",                          # login rate-limiting / lockout
    "django_otp",                    # 2FA framework
    "django_otp.plugins.otp_totp",   # TOTP (Google Authenticator etc.)
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files in production without a separate web server.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",   # must come after AuthenticationMiddleware
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",        # must be last
]

# Authentication backends: Axes wraps the standard backend to count failures.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # checks lockout, delegates auth below
    "django.contrib.auth.backends.ModelBackend",
]

# --- Login rate-limiting (django-axes) ---
AXES_FAILURE_LIMIT = 5                 # tentativas erradas antes de travar
AXES_COOLOFF_TIME = 0.5                # destrava sozinho após 30 min
AXES_LOCKOUT_PARAMETERS = ["username"] # trava por usuário (não por IP)
AXES_RESET_ON_SUCCESS = True           # zera o contador ao logar certo
# Axes precisa do request no authenticate, o que quebra client.login() nos testes.
if "test" in sys.argv:
    AXES_ENABLED = False

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database: SQLite by default; DATABASE_URL (Postgres) overrides in the cloud.
# Treat an empty DATABASE_URL the same as unset (falls back to SQLite).
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization — Brazilian Portuguese / São Paulo.
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True


# Static files (WhiteNoise compresses + hashes them in production).
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Auth flow redirects.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Email (used by the "forgot password" reset). Locally, the console backend
# prints the reset link to the server logs so you can test without SMTP. In
# production, set EMAIL_HOST/EMAIL_HOST_USER/EMAIL_HOST_PASSWORD (and the
# backend switches to SMTP automatically).
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND") or (
    "django.core.mail.backends.smtp.EmailBackend"
    if os.getenv("EMAIL_HOST")
    else "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Financeiro Pessoal <no-reply@financeiro.local>")
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # link válido por 24h

# Production hardening (enabled only when DEBUG is off).
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # HTTP Strict Transport Security: force HTTPS for a year (incl. subdomains).
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    X_FRAME_OPTIONS = "DENY"

# Test-only: admin pages use {% static %}; the manifest storage needs
# collectstatic, which doesn't run under tests — use the plain storage instead.
if "test" in sys.argv:
    STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"
