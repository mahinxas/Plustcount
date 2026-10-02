from pathlib import Path

from django.conf import settings

_ASSETS = [Path(settings.BASE_DIR) / "static" / "css" / "app.css", Path(settings.BASE_DIR) / "static" / "js" / "app.js"]


def messaging_settings(request):
    return {
        "MESSAGING_TEST_MODE": settings.MESSAGING_TEST_MODE,
        "SMS_TEST_MODE": settings.SMS_TEST_MODE,
        "ASSET_VERSION": _asset_version(),
    }


def _asset_version():
    # Production uses hashed file names (ManifestStaticFilesStorage); in development
    # the file change time keeps browsers from showing an old stylesheet.
    if not settings.DEBUG:
        return ""
    return str(int(max(p.stat().st_mtime for p in _ASSETS if p.exists())))
