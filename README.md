# Client Messaging System

A web app for an accounting firm: the admin assigns clients to team members, and each team member emails their own clients, one at a time or in bulk. This is **V1** from `../Project_Plan_Client_Messaging_System.md`.

## Run it locally

```bash
uv sync
DJANGO_DEBUG=1 uv run python manage.py migrate
uv run python manage.py load_templates                 # starter email and SMS templates (no demo data)
DJANGO_DEBUG=1 uv run python manage.py runserver
```

Open http://localhost:8000. Create the first admin with `uv run python manage.py createsuperuser`.

Locally the app uses SQLite, and background jobs run inside the web process. To match production, start PostgreSQL and Redis with `docker compose up -d`, then set `DATABASE_URL` and `CELERY_BROKER_URL` (see `.env.example`). Run a worker with:

```bash
uv run celery -A config worker -l info
```

Run the tests:

```bash
DJANGO_DEBUG=1 uv run python manage.py test
```

## What V1 does

| Area | Features |
|---|---|
| Login | Email and password login, password reset by email, automatic logout after 30 minutes idle. Deactivated users are logged out at once. |
| Team (admin) | Add, edit and deactivate team members. Shows each person's client count and emails sent. |
| Clients | Add, edit, delete and notes, with a profession (delivery rider, taxi, restaurant, other). Search by name, business ID, email or phone. Filter by profession, language and team member; tabs for unassigned clients and clients who can't receive email, where missing emails and phones can be added inline. Business IDs are checked (Y-tunnus check digit), and phone numbers are stored as +358… |
| Import (admin) | CSV or .xlsx upload, then column matching (Finnish headers are recognised), then a preview that lists row errors and duplicates (by business ID or email) before anything is saved. |
| Assignment (admin) | Assign, move or unassign clients one at a time or in bulk. Every change is logged with who made it, from whom, to whom and when. |
| Email | Send to one client, the selected clients, or all matching clients. Choose a template or write a new message. Fields `{name}`, `{company}`, `{business_id}` and `{due_date}` are filled in, and each client gets the Finnish or English version automatically. Live preview, then a confirmation step ("Email to 142 clients"). Opted-out clients and clients without an email address are skipped and counted. Sending runs in the background. |
| Opt-out | No unsubscribe link is added to messages (service reminders only). A client who asks not to be contacted is marked "Opted out" and skipped automatically. If the firm starts sending marketing, an opt-out link is legally required again. |
| SMS | Choose Email or SMS when sending. SMS need no subject, show a live length counter ("95 characters · 1 SMS"), skip clients without a phone, and are limited to 3 SMS per message. Finnish å, ä, ö fit the standard SMS; emoji make an SMS shorter. SMS templates have their own channel. Until a provider is chosen, `messaging.sms.ConsoleBackend` only logs; a real provider is one more backend class in `messaging/sms.py`. |
| Log | All messages with status (queued, sent, failed) and error, plus a page per send. Message history stays with the client, so a new owner sees earlier messages. |

## Access rules, and where they live

- `clients/access.py`, `visible_clients(user)` is the **only** function that decides which clients a user can see: admins see all clients, team members see their own. Every client page, the message log and the send action go through it.
- A client a user may not see returns 404, not 403, so client IDs cannot be probed.
- Ownership only changes through `clients/services.py`, `assign_clients()`, which also writes the history.
- Recipients are resolved again from `visible_clients()` at the moment of sending. If a client is reassigned while someone is writing a message, the old owner cannot send to them.

## Test mode

`MESSAGING_TEST_MODE` is **on unless set to 0**. While it is on, no real client receives anything:

- **Email** goes to `MESSAGING_TEST_RECIPIENT`, with `[TEST]` added to the subject. If no test recipient is set, emails are only printed to the server log and the email provider is never contacted.
- **SMS** are only written to the server log (`SMS (not sent) to … : text`), whatever `SMS_BACKEND` says. The SMS provider is never contacted. This is free and covers V2 development and demos.

A yellow banner shows in the app while test mode is on.

## Going to production

1. Copy `.env.example` to `.env` and fill it in. `DJANGO_SECRET_KEY` is required whenever `DJANGO_DEBUG` is off.
2. Use PostgreSQL and Redis hosted in Finland or the EU (UpCloud or Hetzner Helsinki).
3. Create a Brevo account (EU) and sign its DPA. Put the API key in `BREVO_API_KEY` (in `.env` or the server's environment), verify the sender address in Brevo, set it as `DEFAULT_FROM_EMAIL`, and run `uv run python manage.py brevo_check`. The free plan sends 300 emails a day; `EMAIL_DAILY_LIMIT` stops bigger sends before anything is queued.
4. Set SPF, DKIM and DMARC on the firm's domain, or email will land in spam.
5. Run `migrate` and `collectstatic`, serve with gunicorn behind HTTPS, and run one Celery worker.
6. Turn off `MESSAGING_TEST_MODE` only after the client has approved.

## Not in V1 (planned)

- V2: a real SMS provider (Brevo, GatewayAPI or Twilio), 2FA, scheduling with quiet hours, delivery and bounce status through provider webhooks, audit log, login rate limiting.
- V3: announcements, comments, notifications, client replies inbox.
- V4: tasks and recurring deadlines, reports, GDPR export and delete tools.
- The interface is English only for now; Finnish translation of the interface is still to do.

## Going live

Production runs on Render in Frankfurt (web, background worker, PostgreSQL, Redis), described in `render.yaml` (production, branch `main`) and `render.staging.yaml` (staging, branch `staging`). GitHub Actions (`.github/workflows/ci.yml`) runs the tests on every push, and Render deploys only after they pass.

- What a person still has to do before launch: `docs/LAUNCH_CHECKLIST.md`
- Day-to-day problems and rollbacks: `docs/OPERATIONS.md`
- `/healthz/` reports whether the database and Redis answer (for uptime monitors).
- Security headers include a strict Content-Security-Policy: pages may not use inline `<script>` or `onclick=`. Use files in `static/js/` and `data-` attributes (see `data-confirm` in `app.js`).
- Errors go to Sentry when `SENTRY_DSN` is set; no request bodies or personal details are sent.
