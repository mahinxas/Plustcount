"""The only code that hands messages to the email and SMS providers."""

import logging
from email.utils import make_msgid

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

from . import sms

logger = logging.getLogger(__name__)

CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"


def open_connection():
    """Connection for a batch of sends.

    In test mode without a test recipient, messages are only printed to the
    console and the real provider is never contacted.
    """
    if settings.MESSAGING_TEST_MODE and not (settings.MESSAGING_TEST_RECIPIENT or settings.MESSAGING_TEST_ALLOWED):
        return get_connection(CONSOLE_BACKEND)
    return get_connection()


def send_email(message, connection):
    """Send one Message and return its Message-ID. Raises on failure.

    In test mode the real client address is never used: the message goes to
    MESSAGING_TEST_RECIPIENT (see open_connection for the no-recipient case).
    """
    to = message.to_address
    subject = message.subject
    if settings.MESSAGING_TEST_MODE:
        if to.lower() not in settings.MESSAGING_TEST_ALLOWED:
            to = settings.MESSAGING_TEST_RECIPIENT or to

    message_id = make_msgid(domain=settings.DEFAULT_FROM_EMAIL.rsplit("@", 1)[-1].rstrip(">") or None)
    email = EmailMessage(
        subject=subject,
        body=message.body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        connection=connection,
        headers={"Message-ID": message_id, "X-Client-Message-Id": str(message.pk)},
    )
    email.send(fail_silently=False)
    logger.info("Email message %s sent (test_mode=%s)", message.pk, settings.MESSAGING_TEST_MODE)
    # The Brevo backend reports its own id, which its delivery webhooks refer to.
    return getattr(email, "provider_message_id", "") or message_id


def send_sms(message, backend=None):
    """Send one SMS Message and return the provider's id. Raises on failure.

    In test mode the SMS is only logged (see sms.get_backend): the real
    provider is never contacted and no client receives anything.
    """
    backend = backend or sms.get_backend()
    to, text = message.to_address, message.body
    if settings.SMS_TEST_MODE and settings.MESSAGING_TEST_PHONE and to not in settings.MESSAGING_TEST_ALLOWED:
        to = settings.MESSAGING_TEST_PHONE
    provider_id = backend.send(to, text)
    logger.info("SMS message %s handled (test_mode=%s)", message.pk, settings.MESSAGING_TEST_MODE)
    return provider_id
