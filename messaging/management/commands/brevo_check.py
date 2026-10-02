"""Check the Brevo setup without sending anything: key, credits, verified sender, test mode."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from messaging import brevo


class Command(BaseCommand):
    help = "Check that the Brevo API key works and the sender address is verified. Sends nothing."

    def handle(self, *args, **options):
        if not settings.BREVO_API_KEY:
            raise CommandError("BREVO_API_KEY is not set. Add it to client_messaging/.env.")

        try:
            account_email, plans = brevo.account_summary()
            senders = brevo.verified_senders()
        except brevo.BrevoError as exc:
            raise CommandError(str(exc))

        ok, warn = self.style.SUCCESS, self.style.WARNING
        self.stdout.write(ok(f"API key works (Brevo account {account_email})."))
        for plan in plans:
            self.stdout.write(f"  Plan {plan}")

        sender = brevo.from_address()
        if sender in senders:
            self.stdout.write(ok(f"Sender {sender} is verified."))
        else:
            self.stdout.write(warn(
                f"Sender {sender} is NOT verified in Brevo, so emails will be rejected. "
                "Verify it in Brevo (Senders, domains & dedicated IPs) or change DEFAULT_FROM_EMAIL."
            ))
            if senders:
                self.stdout.write(f"  Verified senders: {', '.join(senders)}")

        self.stdout.write(f"Email backend: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"Daily limit: {settings.EMAIL_DAILY_LIMIT or 'none'}")
        if settings.MESSAGING_TEST_MODE:
            if settings.MESSAGING_TEST_RECIPIENT:
                self.stdout.write(warn(f"Test mode ON: every email goes to {settings.MESSAGING_TEST_RECIPIENT} via Brevo."))
            else:
                self.stdout.write(warn(
                    "Test mode ON without MESSAGING_TEST_RECIPIENT: emails are only printed, Brevo is not used. "
                    "Set MESSAGING_TEST_RECIPIENT to your own address to test real delivery."
                ))
        else:
            self.stdout.write(warn("Test mode OFF: emails go to real clients."))
