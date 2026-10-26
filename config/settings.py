"""Stand-alone settings so the /v1 module runs and tests without Aerrand's repo.

In Aerrand's real Django project you do NOT copy this file. You add the api_v1.* apps to INSTALLED_APPS,
the RequestIdMiddleware to MIDDLEWARE, and the API_* settings below to the existing settings.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"] if DEBUG else [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "api_v1.common",
    "api_v1.keys",
    "api_v1.booking",
    "api_v1.instructions",
    "api_v1.payments",
    "api_v1.tracking",
    "api_v1.reliability",
    "api_v1.notices",
]

MIDDLEWARE = [
    "api_v1.common.middleware.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "config.urls"
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # IMMEDIATE lets concurrent writers queue instead of failing (Django 5.1+). Real project uses MongoDB.
        "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},
        "TEST": {"NAME": BASE_DIR / "test_db.sqlite3"},
    }
}

# Rate limiting and anything else shared across workers goes through the Django cache.
# Locally it is in-memory; set REDIS_URL to use Redis (Django's built-in Redis backend), shared by all workers.
if os.environ.get("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": os.environ["REDIS_URL"]}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "api_v1.common.errors.exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

# ---- API v1 settings (these are the ones to copy into Aerrand's settings) ----
API_KEY_HASH_PEPPER = os.environ.get("API_KEY_HASH_PEPPER", "dev-pepper-change-me")   # real: secret in .env, never in git
API_RATE_PER_MIN = 60            # requests a minute per key
API_CREATE_PER_MIN = 20          # bookings a minute per key
API_QUOTE_TTL_SECONDS = 600
API_BASE_URL = "https://api.aerrand.com/v1"
PUBLIC_TRACK_URL = "https://business.aerrand.com/track"
CANCEL_FEE = "4.00"              # flat fee once an Aerrander has accepted (live keys only)
WEBHOOK_TIMEOUT_SECONDS = 10
