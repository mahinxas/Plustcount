# Launch checklist

Code, deploy files and CI are done. This list is what only a person can do. Tick each line before going live.

## 1. Accounts and hosting
- [ ] Push this folder to a **private** GitHub repo (`main` = production, `staging` = staging). `.env` and `*.sqlite3` are git-ignored; confirm with `git status` first.
- [ ] Render: New > Blueprint > `render.staging.yaml` (branch `staging`), then `render.yaml` (branch `main`). Both are in Frankfurt.
- [ ] Check the plan names in the two yaml files still exist in Render's pricing (they change). Production is sized `standard` web/worker, `basic-1gb` Postgres with point-in-time recovery.
- [ ] GitHub: Settings > Branches > protect `main` and require the **CI** check to pass. Render deploys only after checks pass (`autoDeployTrigger: checksPass`).
- [ ] Custom domain, for example `viestit.<firm>.fi`: add it in Render, create the DNS record, wait for the certificate.

## 2. Environment variables (Render > Environment Groups > `cms-shared`)
- [ ] `DJANGO_ALLOWED_HOSTS` = the domain, no scheme
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` = `https://<the domain>`
- [ ] `BREVO_API_KEY`, `DEFAULT_FROM_EMAIL` (sender verified in Brevo)
- [ ] `SENTRY_DSN` (EU project, sentry.io). Trigger one test error and confirm the alert arrives.
- [ ] `MESSAGING_TEST_MODE=1` until the firm signs off (section 6)
- [ ] First admin: Render shell > `uv run python manage.py createsuperuser`, then `uv run python manage.py load_templates`

## 3. Email reputation (Brevo)
- [ ] Authenticate the firm's domain: DKIM and SPF records from Brevo, plus a DMARC record (`v=DMARC1; p=none; rua=mailto:<firm mailbox>` first, tighten to `quarantine` after a few weeks of clean reports).
- [ ] Send to a Gmail and an Outlook address; confirm inbox, not spam. Check headers show SPF/DKIM/DMARC pass.
- [ ] Brevo: add a webhook for hard bounces and spam complaints and watch the dashboard for the first weeks. (The app does not yet read the webhook; clients that bounce must be fixed by hand.)

## 4. Backups
- [ ] Render Postgres: confirm daily backups and point-in-time recovery are on.
- [ ] **Do one restore test** into a throwaway database and open the app against it. Write the date here: ______
- [ ] Optional: monthly `pg_dump` kept in the firm's own storage.

## 5. Monitoring
- [ ] Uptime monitor (UptimeRobot or Better Stack, free) on `https://<domain>/healthz/`, alert by email and SMS. It returns 503 if the database or Redis is down.
- [ ] Sentry alert rule: email on every new issue.
- [ ] Render: turn on deploy-failure and service-down notifications.

## 6. Legal and people
- [ ] Data processing agreements (DPA) with Render, Brevo, Sentry, and the SMS Gate provider if used. All offer a click-through DPA.
- [ ] Short privacy notice for the firm's clients: what is sent, why, who the processor is, how to opt out.
- [ ] Records of processing (GDPR art. 30) lists this system.
- [ ] Every staff member has their own account; nobody shares a login. When someone leaves, an admin deactivates them the same day.
- [ ] Demo walkthrough with the firm, then they approve in writing. Only then set `MESSAGING_TEST_MODE=0`.

## 7. Before the first real send
- [ ] Staging: send to your own addresses with real-looking data.
- [ ] Production, test mode on: import the real client list, review the preview, check the numbers.
- [ ] Switch test mode off. First real send: a small batch (10 clients) to people who expect it, then the rest.

## 8. Later
- Load test with 500+ clients and a bulk send (watch worker memory and Brevo rate).
- Read Brevo bounce webhooks into the app (mark bad addresses automatically).
- Add database indexes if the client list gets slow with filters.
