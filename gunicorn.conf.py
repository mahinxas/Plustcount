"""Gunicorn settings. Render sets PORT; WEB_CONCURRENCY can override the worker count."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", 3))
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1000  # recycle workers now and then to keep memory flat
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
# The host's proxy sets X-Forwarded-For; gunicorn only trusts it from there.
forwarded_allow_ips = "*"
