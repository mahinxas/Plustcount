"""Brevo transactional email API as a Django email backend.

Enabled automatically when BREVO_API_KEY is set (see settings.EMAIL_BACKEND).
API reference: POST {BREVO_API_URL}/smtp/email with an "api-key" header;
201 returns {"messageId": "<...>"}.
"""

import logging
import re
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15

# Plain-language reasons for the errors people actually hit.
_REASONS = {
    401: "Brevo rejected the API key. Check BREVO_API_KEY in .env.",
    402: "Brevo daily limit or credits used up. Try again tomorrow or upgrade the plan.",
    429: "Brevo is rate limiting requests. Try again in a minute.",
}


class BrevoError(Exception):
    pass


def _address(value):
    name, email = parseaddr(value)
    item = {"email": email}
    if name:
        item["name"] = name
    return item


def api_headers():
    if not settings.BREVO_API_KEY:
        raise ImproperlyConfigured("BREVO_API_KEY is not set.")
    return {"api-key": settings.BREVO_API_KEY, "accept": "application/json", "content-type": "application/json"}


class BrevoEmailBackend(BaseEmailBackend):
    """Sends each message with one API call and stores Brevo's id on it as ``provider_message_id``."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.session = None

    def open(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update(api_headers())
            return True
        return False

    def close(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        opened_here = self.open()
        sent = 0
        try:
            for message in email_messages:
                try:
                    message.provider_message_id = self._send(message)
                    sent += 1
                except Exception:
                    if not self.fail_silently:
                        raise
        finally:
            if opened_here:
                self.close()
        return sent

    def _send(self, message):
        payload = {
            "sender": _address(message.from_email or settings.DEFAULT_FROM_EMAIL),
            "to": [_address(a) for a in message.to],
            "subject": message.subject,
            "textContent": message.body,
            "tags": ["client-messaging"],
        }
        if message.cc:
            payload["cc"] = [_address(a) for a in message.cc]
        if message.reply_to:
            payload["replyTo"] = _address(message.reply_to[0])
        client_id = message.extra_headers.get("X-Client-Message-Id")
        if client_id:
            # Brevo returns X-Mailin-custom in its delivery webhooks, so status updates can be matched later.
            payload["headers"] = {"X-Mailin-custom": f"message:{client_id}"}

        try:
            response = self.session.post(f"{settings.BREVO_API_URL}/smtp/email", json=payload, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise BrevoError(f"Could not reach Brevo: {exc.__class__.__name__}") from exc

        if response.status_code == 201:
            return response.json().get("messageId", "")
        raise BrevoError(_describe_error(response))


def _describe_error(response):
    reason = _REASONS.get(response.status_code)
    try:
        detail = response.json().get("message", "")
    except ValueError:
        detail = ""
    if response.status_code == 401 and "ip address" in detail.lower():
        # The key is fine; Brevo's "Authorised IPs" security setting blocks this machine.
        found = re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", detail)
        ip = found.group(0) if found else "this computer's address"
        return (
            f"Brevo blocked the request from IP address {ip}. The API key itself is fine. "
            "Allow this IP in Brevo (Security > Authorised IPs: https://app.brevo.com/security/authorised_ips), "
            "or turn off IP blocking there."
        )
    if reason:
        return f"{reason} ({detail})" if detail else reason
    return f"Brevo error {response.status_code}: {detail or response.text[:200]}"


def account_summary():
    """Read-only check of the key: returns (company email, list of plan descriptions)."""
    response = requests.get(f"{settings.BREVO_API_URL}/account", headers=api_headers(), timeout=TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise BrevoError(_describe_error(response))
    data = response.json()
    plans = [
        f"{p.get('type', 'plan')}: {p.get('credits', '?')} {p.get('creditsType', 'credits')}" for p in data.get("plan", [])
    ]
    return data.get("email", ""), plans


def verified_senders():
    """Sender addresses Brevo will accept in the "from" field."""
    response = requests.get(f"{settings.BREVO_API_URL}/senders", headers=api_headers(), timeout=TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise BrevoError(_describe_error(response))
    return [s.get("email", "").lower() for s in response.json().get("senders", []) if s.get("active", True)]


def from_address():
    return parseaddr(settings.DEFAULT_FROM_EMAIL)[1].lower()


def emails_sent_today(day):
    """Emails Brevo has accepted from this account today (all tags). Cached for 60 seconds."""
    from django.core.cache import cache

    day = day.isoformat()
    key = f"brevo-requests-{day}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    response = requests.get(
        f"{settings.BREVO_API_URL}/smtp/statistics/aggregatedReport",
        params={"startDate": day, "endDate": day},
        headers=api_headers(),
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise BrevoError(_describe_error(response))
    count = int(response.json().get("requests") or 0)
    cache.set(key, count, 60)
    return count
