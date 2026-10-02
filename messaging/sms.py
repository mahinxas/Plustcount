"""SMS backends and SMS length rules.

Works like Django's email backends: settings.SMS_BACKEND names a class with a
``send(to, text)`` method that returns the provider's message id.

In test mode the configured backend is ignored and every SMS is only logged
(ConsoleBackend), so no real client can ever receive a test SMS. The in-memory
backend is for automated tests. A real provider (Brevo, GatewayAPI, Twilio)
is added as one more backend class when the firm has chosen one.
"""

import logging
import uuid

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

CONSOLE_BACKEND = "messaging.sms.ConsoleBackend"
SAFE_TEST_BACKENDS = {CONSOLE_BACKEND, "messaging.sms.LocmemBackend"}


class ConsoleBackend:
    """Logs the SMS instead of sending it. Free; used for development, demos and test mode."""

    def send(self, to, text):
        message_id = f"console-{uuid.uuid4().hex[:12]}"
        logger.info("SMS (not sent) to %s from %s, %d part(s): %s", to, settings.SMS_SENDER, segments(text), text)
        return message_id


class GammuError(Exception):
    pass


class GammuBackend:
    """Sends SMS through a GSM modem (or phone) with a SIM card, using Gammu.

    The SMS is queued with ``gammu-smsd-inject``; the gammu-smsd service owns the
    modem and does the actual sending and retries. Messages longer than one SMS
    are sent as a multipart SMS; Unicode is used when the text needs it.
    The sender shown on the phone is the SIM's own number.
    """

    def send(self, to, text):
        import subprocess

        _, parts, unicode = length_info(text)
        cmd = [settings.GAMMU_INJECT_COMMAND]
        if settings.GAMMU_CONFIG:
            cmd += ["-c", settings.GAMMU_CONFIG]
        cmd += ["TEXT", to]
        if unicode:
            cmd.append("-unicode")
        if parts > 1:
            cmd += ["-len", str(len(text))]
        cmd += ["-text", text]
        try:
            # A list of arguments, never a shell: client text can't run commands.
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        except FileNotFoundError as exc:
            raise GammuError(f"{settings.GAMMU_INJECT_COMMAND} not found. Is Gammu installed?") from exc
        except subprocess.TimeoutExpired as exc:
            raise GammuError("Gammu did not answer within 30 seconds.") from exc
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise GammuError(f"Gammu could not queue the SMS: {output[-300:] or 'exit code ' + str(result.returncode)}")
        # Success looks like: "Written message with ID /var/spool/gammu/outbox/OUTC2026...txt"
        marker = "with ID "
        return "gammu:" + (output.split(marker, 1)[1].strip().rsplit("/", 1)[-1] if marker in output else "queued")


class KdeConnectError(Exception):
    pass


class KdeConnectBackend:
    """Sends SMS through a paired Android phone with KDE Connect (the phone's own SIM and plan).

    Runs: kdeconnect-cli --device <id> --send-sms <text> --destination <number>
    The phone must be paired, reachable (same Wi-Fi or USB network) and have the
    SMS permission granted in the KDE Connect app. Good for testing and small volumes.
    """

    def send(self, to, text):
        import subprocess

        if not settings.KDECONNECT_DEVICE:
            raise KdeConnectError("KDECONNECT_DEVICE is not set. Find it with: kdeconnect-cli --list-available")
        cmd = [settings.KDECONNECT_COMMAND, "--device", settings.KDECONNECT_DEVICE,
               "--send-sms", text, "--destination", to]
        try:
            # A list of arguments, never a shell: client text can't run commands.
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        except FileNotFoundError as exc:
            raise KdeConnectError(f"{settings.KDECONNECT_COMMAND} not found. Is KDE Connect installed?") from exc
        except subprocess.TimeoutExpired as exc:
            raise KdeConnectError("The phone did not answer within 30 seconds. Is it on and connected?") from exc
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0 or "error" in output.lower() or "not reachable" in output.lower():
            raise KdeConnectError(f"KDE Connect could not send: {output[-300:] or 'exit code ' + str(result.returncode)}")
        return f"kdeconnect-{uuid.uuid4().hex[:12]}"


class SmsGateError(Exception):
    pass


class SmsGateBackend:
    """Sends SMS through an Android phone running the SMS Gate app (sms-gate.app cloud server).

    POST {SMSGATE_URL} with Basic auth and {"textMessage": {"text": ...}, "phoneNumbers": [...]}.
    The phone must be on, online and have the SMS Gate service running. The sender is the
    phone's own number. ``delay_seconds`` spaces out bulk sends so the carrier doesn't block the SIM.
    """

    @property
    def delay_seconds(self):
        return settings.SMS_SEND_DELAY_SECONDS

    def send(self, to, text):
        import requests

        if not (settings.SMSGATE_USERNAME and settings.SMSGATE_PASSWORD):
            raise SmsGateError("SMSGATE_USERNAME and SMSGATE_PASSWORD are not set in .env.")
        try:
            response = requests.post(
                settings.SMSGATE_URL,
                json={"textMessage": {"text": text}, "phoneNumbers": [to]},
                auth=(settings.SMSGATE_USERNAME, settings.SMSGATE_PASSWORD),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise SmsGateError(f"Could not reach SMS Gate: {exc.__class__.__name__}") from exc
        if response.status_code == 401:
            raise SmsGateError("SMS Gate rejected the username or password.")
        if response.status_code not in (200, 201, 202):
            raise SmsGateError(f"SMS Gate error {response.status_code}: {response.text[:200]}")
        try:
            return "smsgate:" + str(response.json().get("id", "queued"))
        except ValueError:
            return "smsgate:queued"

    def status(self, provider_id):
        """(state, error) for an SMS this backend sent, e.g. ("Delivered", "")."""
        import requests

        message_id = provider_id.removeprefix("smsgate:")
        base = settings.SMSGATE_URL.rstrip("/")
        response = requests.get(f"{base}/{message_id}", auth=(settings.SMSGATE_USERNAME, settings.SMSGATE_PASSWORD), timeout=10)
        if response.status_code != 200:
            raise SmsGateError(f"SMS Gate status error {response.status_code}")
        data = response.json()
        errors = [r.get("error") for r in data.get("recipients", []) if r.get("error")]
        return data.get("state", ""), "; ".join(errors)


outbox = []


class LocmemBackend:
    """Keeps sent SMS in messaging.sms.outbox, for automated tests."""

    def send(self, to, text):
        message_id = f"locmem-{len(outbox) + 1}"
        outbox.append({"to": to, "text": text, "sender": settings.SMS_SENDER, "id": message_id})
        return message_id


def get_backend():
    path = settings.SMS_BACKEND
    if settings.SMS_TEST_MODE and not settings.MESSAGING_TEST_PHONE and path not in SAFE_TEST_BACKENDS:
        path = CONSOLE_BACKEND
    return import_string(path)()


# --- Length ---------------------------------------------------------------------------
# Standard SMS (GSM 03.38) holds 160 characters, or 153 per part when split.
# Finnish å, ä, ö are in the standard set. Any other character (emoji, most
# symbols) switches the whole SMS to Unicode: 70 characters, or 67 per part.

_GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXTENDED = set("^{}\\[~]|€")  # each counts as two characters

MAX_PARTS = 3  # keeps a single reminder from costing more than three SMS


def is_gsm(text):
    return all(ch in _GSM_BASIC or ch in _GSM_EXTENDED for ch in text)


def length_info(text):
    """Return (characters counted, parts, is_unicode) for an SMS text."""
    if is_gsm(text):
        count = sum(2 if ch in _GSM_EXTENDED else 1 for ch in text)
        single, multi, unicode = 160, 153, False
    else:
        count = len(text.encode("utf-16-le")) // 2
        single, multi, unicode = 70, 67, True
    if count == 0:
        return 0, 0, unicode
    parts = 1 if count <= single else -(-count // multi)
    return count, parts, unicode


def segments(text):
    return length_info(text)[1]
