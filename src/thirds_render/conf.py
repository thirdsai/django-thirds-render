"""Settings.

THIRDS_API_KEY
    Your thirds.ai API key. If the setting is missing or empty, the THIRDS_API_KEY
    environment variable is used. Keep it out of settings files: read it from the
    environment, for example ``THIRDS_API_KEY = os.environ.get("THIRDS_API_KEY")``.

THIRDS_RENDER
    Optional dict: BASE_URL (default "https://thirds.ai"), TIMEOUT (seconds per
    HTTP request, default 60), DEADLINE (seconds to wait for one render, default 120),
    POLL_INTERVAL (seconds, default 1.0).
"""

import os

from django.conf import settings

DEFAULTS = {
    "BASE_URL": "https://thirds.ai",
    "TIMEOUT": 60,
    "DEADLINE": 120,
    "POLL_INTERVAL": 1.0,
}


def api_key():
    key = getattr(settings, "THIRDS_API_KEY", None) or os.environ.get("THIRDS_API_KEY") or ""
    return key.strip()


def option(name):
    return {**DEFAULTS, **getattr(settings, "THIRDS_RENDER", {})}[name]
