"""Django settings for the Client Messaging System.

All environment-specific values come from environment variables so that
secrets never live in the code. See .env.example for the full list.
"""

import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Secrets live in client_messaging/.env (never committed). Real environment
# variables, as set on a server, win over the file.
load_dotenv(BASE_DIR / ".env", override=False)


# `manage.py test` always runs jobs in-process and uses a private cache, whatever the
# environment says, so a developer's or CI's Redis never changes test results.
TESTING = sys.argv[1:2] == ["test"]


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")
    SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "clients",
    "messaging",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page requires login unless the view is marked @login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "messaging.context_processors.messaging_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite for local development; set DATABASE_URL to PostgreSQL everywhere else.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Automatic logout after inactivity: the session expires this many seconds
# after the last request.
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_IDLE_TIMEOUT_SECONDS", 30 * 60))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Content-Security-Policy: scripts and styles only from our own files, so an injected
# <script> never runs. Inline style="" attributes are allowed (progress bars, chart widths).
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF],
    "style-src-attr": [CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 60 * 60 * 24 * 30))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    # /healthz is called over plain HTTP by the platform's health checker.
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("fi", "Suomi")]
TIME_ZONE = "Europe/Helsinki"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if not DEBUG:
    # File names carry a content hash, so browsers never keep an old stylesheet after a release.
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uploads (client import files) are read in memory and never stored on disk.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --- Email -------------------------------------------------------------------
# With BREVO_API_KEY set, email goes through the Brevo API. Without it,
# development prints emails to the console and production uses SMTP.
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "").strip()
BREVO_API_URL = os.environ.get("BREVO_API_URL", "https://api.brevo.com/v3").rstrip("/")
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "messaging.brevo.BrevoEmailBackend" if BREVO_API_KEY
    else "django.core.mail.backends.console.EmailBackend" if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
# Most emails the provider accepts per day (Brevo free plan: 300). 0 = no limit.
# Sends that would go over it are stopped before anything is queued.
EMAIL_DAILY_LIMIT = int(os.environ.get("EMAIL_DAILY_LIMIT", 300))
# Timezone in which the provider's day starts (its limit resets at midnight there).
# Brevo does not document it; UTC until Brevo support confirms otherwise.
EMAIL_LIMIT_TIMEZONE = os.environ.get("EMAIL_LIMIT_TIMEZONE", "UTC")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp-relay.brevo.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Tilitoimisto <noreply@example.fi>")

# --- Messaging -----------------------------------------------------------------
# Test mode: no real client ever receives a message. Every outgoing message is
# redirected to MESSAGING_TEST_RECIPIENT (or only printed/logged when empty)
# and its subject is marked [TEST]. It is ON unless explicitly turned off.
MESSAGING_TEST_MODE = env_bool("MESSAGING_TEST_MODE", True)
MESSAGING_TEST_RECIPIENT = os.environ.get("MESSAGING_TEST_RECIPIENT", "")
# In test mode, these addresses (your own test clients) receive their emails directly
# instead of being redirected to MESSAGING_TEST_RECIPIENT. Comma separated.
MESSAGING_TEST_ALLOWED = {a.lower() for a in env_list("MESSAGING_TEST_ALLOWED")}
# In test mode, every SMS goes to this number (your own phone) through the real SMS
# backend. Empty = SMS are only logged. Numbers in MESSAGING_TEST_ALLOWED get their own SMS.
MESSAGING_TEST_PHONE = os.environ.get("MESSAGING_TEST_PHONE", "").replace(" ", "")
# SMS can go live separately from email: SMS_TEST_MODE=0 sends SMS to real numbers
# while email stays in test mode. Defaults to MESSAGING_TEST_MODE.
SMS_TEST_MODE = env_bool("SMS_TEST_MODE", MESSAGING_TEST_MODE)

# SMS: the backend class that sends SMS. Until a provider is chosen, the console
# backend only logs messages. In test mode every SMS is only logged, whatever is set here.
SMS_BACKEND = os.environ.get("SMS_BACKEND", "messaging.sms.ConsoleBackend")
# Sender name shown on the phone: letters and digits, at most 11 characters
# (a phone network limit). Set it to the firm's short name.
SMS_SENDER = os.environ.get("SMS_SENDER", "Kirjanpito")
if not (1 <= len(SMS_SENDER) <= 11 and SMS_SENDER.replace(" ", "").isalnum()):
    raise ImproperlyConfigured("SMS_SENDER must be 1-11 letters or digits.")

# Gammu (SMS through our own GSM modem + SIM): set SMS_BACKEND=messaging.sms.GammuBackend.
GAMMU_INJECT_COMMAND = os.environ.get("GAMMU_INJECT_COMMAND", "gammu-smsd-inject")
GAMMU_CONFIG = os.environ.get("GAMMU_CONFIG", "")  # e.g. /etc/gammu-smsdrc; empty = Gammu's default

# KDE Connect (SMS through a paired Android phone): SMS_BACKEND=messaging.sms.KdeConnectBackend.
KDECONNECT_COMMAND = os.environ.get("KDECONNECT_COMMAND", "kdeconnect-cli")
KDECONNECT_DEVICE = os.environ.get("KDECONNECT_DEVICE", "")  # id from: kdeconnect-cli --list-available

# SMS Gate (Android phone as SMS gateway, sms-gate.app): SMS_BACKEND=messaging.sms.SmsGateBackend
SMSGATE_URL = os.environ.get("SMSGATE_URL", "https://api.sms-gate.app/3rdparty/v1/messages")
SMSGATE_USERNAME = os.environ.get("SMSGATE_USERNAME", "")
SMSGATE_PASSWORD = os.environ.get("SMSGATE_PASSWORD", "")
# Pause between SMS in one send, so the carrier doesn't flag the SIM as spam (100 SMS ~ 5 min).
SMS_SEND_DELAY_SECONDS = float(os.environ.get("SMS_SEND_DELAY_SECONDS", 3))
# Optional cap on SMS per day from our SIM. SMS Gate has no limit, so 0 (no limit) is the default.
SMS_DAILY_LIMIT = int(os.environ.get("SMS_DAILY_LIMIT", 0))

# --- Cache -----------------------------------------------------------------------
# The login throttle counts failures in the cache, so it must be shared by all web
# processes: Redis in production (REDIS_URL), local memory for development and tests.
REDIS_URL = os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL", "")
if REDIS_URL and not TESTING:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }

# --- Error tracking --------------------------------------------------------------
# Set SENTRY_DSN (an EU-region project) to get an alert for every crash. Request
# bodies, cookies and user details are not sent: clients' personal data stays out.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("RENDER_GIT_COMMIT", None),
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", 0)),
    )

# --- Background jobs -------------------------------------------------------------
# Without a broker, tasks run immediately in the web process (fine for local
# development and tests). In production set CELERY_BROKER_URL to Redis.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "")
CELERY_TASK_ALWAYS_EAGER = TESTING or not CELERY_BROKER_URL
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
