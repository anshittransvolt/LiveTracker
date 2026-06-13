"""
Django settings for vehicletracker project.
Standalone vehicle tracking system: livetracker + globaltracker.
"""

import os
import json
import logging.handlers
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

ENV_FILE = BASE_DIR / '.env'
load_dotenv(dotenv_path=ENV_FILE, override=True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")

PROJECT_ENV = os.getenv("PROJECT_ENVIRONMENT")

if PROJECT_ENV == "dev":
    DEBUG = True
else:
    DEBUG = False

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [
    h.strip() for h in os.getenv(
        "CSRF_TRUSTED_ORIGINS",
        "http://localhost,http://127.0.0.1"
    ).split(",")
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "import_export",
    "django_celery_results",
    "django_celery_beat",
    "csp",
    "django_recaptcha",
    "dashboard",
    "email_service",
    "livenotif",
    "livetracker",
    "globaltracker",
    "roster",
    "mis",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "dashboard.middleware.ProjectURLMiddleware",
    "dashboard.middleware.UserActionLoggerMiddleware",
    "dashboard.middleware.ProjectRBACMiddleware",
]

if DEBUG:
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(3, "debug_toolbar.middleware.DebugToolbarMiddleware")

ROOT_URLCONF = "vehicletracker.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "dashboard.context_processors.project_spv_context",
                "dashboard.context_processors.rbac_context",
                "livetracker.context_processors.environment_variables",
                "livetracker.context_processors.vehicle_mapping",
            ],
        },
    },
]

WSGI_APPLICATION = "vehicletracker.wsgi.application"

# Microsoft OAuth (optional)
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID")
MICROSOFT_AUTHORITY = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}"
MICROSOFT_REDIRECT_URI = os.getenv("MICROSOFT_REDIRECT_URI")
MICROSOFT_SCOPE = ["User.Read"]

CNS_ACCESS_KEY = os.getenv("CNS_ACCESS_KEY")
CNS_BASE_URL = os.getenv("CNS_BASE_URL")
VOLTRACK_API_BASE_URL = os.getenv("VOLTRACK_API_BASE_URL")
VOLTRACK_API_TOKEN = os.getenv("VOLTRACK_API_TOKEN")
VOLTRACK_VENDOR = os.environ.get("VOLTRACK_VENDOR", "intangles")

# Database
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_SSLMODE = os.getenv("DB_SSLMODE")

if DB_NAME and DB_USER and DB_PASSWORD and DB_HOST:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": DB_NAME,
            "USER": DB_USER,
            "PASSWORD": DB_PASSWORD,
            "HOST": DB_HOST,
            "PORT": DB_PORT,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBHOOKS_TOKEN = os.getenv("WEBHOOKS_TOKEN")

ENABLE_TOAST_SERVICE = True
ENABLE_TELEGRAM_SERVICE = True
ENABLE_WEBHOOK_SERVICE = True

# CSP
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": [
            "'self'", "'unsafe-inline'", "'unsafe-eval'",
            "cdn.tailwindcss.com", "cdn.plot.ly", "cdn.jsdelivr.net",
            "cdnjs.cloudflare.com", "unpkg.com", "code.jquery.com",
            "https://lottie.host", "www.google.com", "www.gstatic.com",
        ],
        "style-src": [
            "'self'", "'unsafe-inline'", "cdn.tailwindcss.com",
            "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com",
            "fonts.googleapis.com",
        ],
        "img-src": ["'self'", "data:", "blob:", "https:"],
        "font-src": [
            "'self'", "data:", "cdn.jsdelivr.net", "cdnjs.cloudflare.com",
            "unpkg.com", "fonts.gstatic.com",
        ],
        "connect-src": [
            "'self'", "cdn.tailwindcss.com", "cdn.jsdelivr.net",
            "cdnjs.cloudflare.com", "unpkg.com", "code.jquery.com",
            "https://lottie.host", "www.google.com", "www.gstatic.com",
        ],
        "frame-src": ["'self'", "www.google.com", "www.gstatic.com"],
        "frame-ancestors": ["'self'"],
        "worker-src": ["'self'", "blob:"],
    }
}

# Jira / email service
SMARTFASTAPI_DOMAIN = os.getenv("SMARTFASTAPI_DOMAIN")
SMARTFASTAPI_ACCESS_KEY = os.getenv("SMARTFASTAPI_ACCESS_KEY")
PROCESSED_API_TOKEN = os.getenv("PROCESSED_API_TOKEN")
PROCESSED_API_BASE_URL = os.getenv("PROCESSED_API_BASE_URL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_DOMAIN = os.getenv("JIRA_DOMAIN")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")

# Vendor config
from .vendor_config import VENDOR_DISPLAY_NAMES, COMMON_VENDORS

env_vendor_names = os.getenv("VENDOR_DISPLAY_NAMES")
if env_vendor_names:
    try:
        VENDOR_DISPLAY_NAMES.update(json.loads(env_vendor_names))
    except json.JSONDecodeError:
        pass

env_common_vendors = os.getenv("COMMON_VENDORS")
if env_common_vendors:
    try:
        COMMON_VENDORS = json.loads(env_common_vendors)
    except json.JSONDecodeError:
        pass

# TWINS API
TWINS_API_URL = os.getenv("TWINS_API_URL")
TWINS_API_TOKEN = os.getenv("TWINS_API_TOKEN", "")
TWINS_VENDOR = os.getenv("TWINS_VENDOR", "intangles")
TWINS_SPV = os.getenv("TWINS_SPV", "UMT")
TWINS_LIMIT = int(os.getenv("TWINS_LIMIT", 5))

TWINS_MBMT_VENDOR = os.getenv("TWINS_MBMT_VENDOR", "intangles")
TWINS_MBMT_SPV = os.getenv("TWINS_MBMT_SPV", "MBMT")
TWINS_NAGPUR_VENDOR = os.getenv("TWINS_NAGPUR_VENDOR", "eka")
TWINS_NAGPUR_SPV = os.getenv("TWINS_NAGPUR_SPV", "nagpur")

# Telemetry API
TELEMETRY_API_URL = os.getenv("TELEMETRY_API_URL")
TELEMETRY_API_KEY = os.getenv("TELEMETRY_API_KEY")

# Webhooks
WEBHOOK_URL_ALERT = os.getenv("WEBHOOK_URL_ALERT")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY")
WEBHOOK_ENABLED = os.getenv("WEBHOOK_ENABLED", "false").lower() == "true"
WEBHOOK_TIMEOUT = int(os.getenv("WEBHOOK_TIMEOUT", "10"))
WEBHOOK_RETRY_COUNT = int(os.getenv("WEBHOOK_RETRY_COUNT", "3"))
WEBHOOK_VENDOR_NAME = os.getenv("WEBHOOK_VENDOR_NAME")
WEBHOOK_EVENT_PAGE_URL = os.getenv("WEBHOOK_EVENT_PAGE_URL")

# Vehicle master API (used by dashboard)
VEHICLE_DATABASE_URL = os.environ.get("VEHICLE_DATABASE_URL", "")
VEHICLE_MASTER_TABLE = os.environ.get("VEHICLE_MASTER_TABLE", "Vehicle_Master2")

# reCAPTCHA
RECAPTCHA_PUBLIC_KEY = os.getenv("CAPTCHA_SITE_KEY", "")
RECAPTCHA_PRIVATE_KEY = os.getenv("CAPTCHA_SECRET_KEY", "")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = os.getenv("STATIC_ROOT", str(BASE_DIR / "staticfiles"))
STATICFILES_DIRS = []

MEDIA_ROOT = os.getenv("MEDIA_ROOT", str(BASE_DIR / "media"))
MEDIA_URL = "/media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"

# Celery
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ALWAYS_EAGER = False

RAW_DATA_ROOT = os.getenv("RAW_DATA_ROOT", str(BASE_DIR / "data" / "raw"))

INTERNAL_IPS = ["127.0.0.1"]

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.getenv("REDIS_PATH", "redis://localhost:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

X_FRAME_OPTIONS = "SAMEORIGIN"

JAZZMIN_SETTINGS = {
    "site_title": "Tracker Admin",
    "site_header": "Vehicle Tracker",
    "site_brand": "Tracker",
    "welcome_sign": "Welcome to Vehicle Tracker",
    "copyright": "Transvolt Mobility",
    "show_ui_builder": False,
    "related_modal_active": False,
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-primary",
    "accent": "accent-primary",
    "navbar": "navbar-white navbar-light",
    "sidebar": "sidebar-dark-primary",
    "theme": "default",
}

# Logging
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "mis_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "mis.log"),
            "maxBytes": 20 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
        "livetracker_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "livetracker.log"),
            "maxBytes": 20 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
        "pipeline_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "mis_pipeline.log"),
            "maxBytes": 50 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("ROOT_LOG_LEVEL", "WARNING"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_REQUEST_LOG_LEVEL", "ERROR"),
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_SERVER_LOG_LEVEL", "ERROR"),
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": os.getenv("DB_LOG_LEVEL", "ERROR"),
            "propagate": False,
        },
        "mis": {
            "handlers": ["console", "mis_file"],
            "level": os.getenv("MIS_LOG_LEVEL", "DEBUG"),
            "propagate": False,
        },
        "mis.services": {
            "handlers": ["console", "mis_file"],
            "level": os.getenv("MIS_SERVICES_LOG_LEVEL", "DEBUG"),
            "propagate": False,
        },
        "mis.pipeline": {
            "handlers": ["console", "mis_file", "pipeline_file"],
            "level": "INFO",
            "propagate": False,
        },
        "livetracker": {
            "handlers": ["console", "livetracker_file"],
            "level": os.getenv("LIVETRACKER_LOG_LEVEL", "DEBUG"),
            "propagate": False,
        },
        "livenotif": {
            "handlers": ["console"],
            "level": os.getenv("LIVENOTIF_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
        "dashboard": {
            "handlers": ["console"],
            "level": os.getenv("DASHBOARD_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
    },
}

if DEBUG:
    LOGGING["loggers"]["livetracker"] = {
        "handlers": ["console"],
        "level": "INFO",
        "propagate": False,
    }
    LOGGING["loggers"]["livetracker.views"] = {
        "handlers": ["console"],
        "level": "INFO",
        "propagate": False,
    }
    LOGGING["loggers"]["livetracker.timebox"] = {
        "handlers": ["console"],
        "level": "INFO",
        "propagate": False,
    }
