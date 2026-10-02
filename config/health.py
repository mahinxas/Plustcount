import logging

from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
@never_cache
@login_not_required
def healthz(request):
    """Used by the host and uptime monitors: 200 only if the database and cache both answer."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        logger.exception("Health check: database unreachable")
        checks["database"] = "down"
    try:
        cache.set("healthz", "1", 10)
        checks["cache"] = "ok" if cache.get("healthz") == "1" else "down"
    except Exception:
        logger.exception("Health check: cache unreachable")
        checks["cache"] = "down"
    healthy = all(v == "ok" for v in checks.values())
    return JsonResponse({"status": "ok" if healthy else "unavailable", **checks}, status=200 if healthy else 503)
