# Operations runbook

| Situation | What to do |
|---|---|
| Site down | Open `/healthz/`. `database: down` = Render Postgres dashboard. `cache: down` = Render Key Value dashboard. Check Sentry and Render logs. |
| Bad release | Render > service > Events > roll back to the previous deploy. Migrations are run before the new code starts, so keep them backward-compatible (add columns as nullable; remove a column only one release after the code stops using it). |
| Emails not going out | Check the worker's logs (`cms-worker`). Check Brevo's daily limit (`EMAIL_DAILY_LIMIT`) and its dashboard. Messages in "Interrupted" can be retried from the Messages page. |
| Locked-out user | Admin sets a new password, or the user uses "Forgot password". The login lock clears itself after 15 minutes. |
| Restore data | Render Postgres > Recovery: pick a time before the problem, restore into a **new** database, point `DATABASE_URL` at it after checking. |
| Rotate a secret | Change it in the environment group; Render redeploys. Changing `DJANGO_SECRET_KEY` logs everyone out. |

Deploy flow: push to `staging` > CI passes > Render deploys staging > review > merge `staging` into `main` > CI passes > production deploys.
