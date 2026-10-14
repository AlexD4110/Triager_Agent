# Setup Guide: from zero to a triaged message with a Slack alert

This is the exact sequence needed to get an inbound WhatsApp message stored in Supabase through a Railway-hosted webhook (Steps 1 to 9), then labeled by the model, given a priority, announced in Slack, and shown on the dashboard (Steps 10 to 16). Placeholders in angle brackets, such as `<your-domain>`, are values you create along the way. Never paste real secrets into chat, screenshots, issues, or commits.

Total time: about two to three hours, most of it Meta setup.

## What you need first

- A computer with Python 3.12 and git
- A GitHub account
- A Meta account that can create a business portfolio and a developer app
- A Supabase account (hosted Postgres)
- A Railway account (hosting)
- A key and endpoint address for the language model service used by the classifier (Qwen)
- A Slack workspace where you can create channels and incoming webhooks
- A phone with WhatsApp, to send the test message

## Step 1: Get the code and run the tests

```bash
git clone <your-repo-url> gifter-triage
cd gifter-triage
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
```

Copy `.env.example` to `.env`. Every value below goes in `.env` locally, and the three webhook values also go into Railway later. `.env` is gitignored. Never commit it.

## Step 2: Set up the database (Supabase)

1. Create a Supabase project.
2. Open **Project Settings, Database** and copy the connection string. Use the **pooler** string (host contains `pooler.supabase.com`), which looks like `postgresql://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres`.
3. Put it in `.env` as `DATABASE_URL`, with these three rules:
   - Replace the password placeholder with your real **database password**, not an API key.
   - **Remove the square brackets** around the password. The template shows `[YOUR-PASSWORD]`, and the brackets are not part of the password.
   - URL-encode special characters (`@ : / ? # %`). A password of only letters and digits avoids this.
4. Open the Supabase **SQL editor**, paste the contents of `sql/schema.sql`, and run it once. It creates every table the project uses and turns on row level security with no policies, so Supabase's public API cannot read gifter messages. If you already ran an earlier version of this file, run the migrations you are missing instead, in order: `sql/phase3.sql`, `sql/phase4.sql`, `sql/realset.sql`, `sql/phase5.sql`. All are safe to run twice, and the worker fails on every job if its tables are missing.
5. Test the connection:

```bash
.venv/bin/python -c "
from triage.config import load_dotenv; load_dotenv()
from app import store
with store.connect() as c:
    print(c.postgres, c.execute('select count(*) from messages').fetchone())
"
```

Expect `True (0,)`. If you reset the database password, wait a minute and use the new one in every place that holds the URL.

## Step 3: Meta account and app setup

These steps happen in the Meta for Developers dashboard (`developers.facebook.com`) and in Meta Business Settings (`business.facebook.com/settings`).

### 3a. Business portfolio and developer account

1. Sign in with a Facebook account and register as a Meta developer.
2. Create or choose a **business portfolio** in Business Settings. The WhatsApp account and the app both live under it.

### 3b. Create the app

1. In the developer dashboard, choose **Create app**.
2. Choose the use case **Connect with customers through WhatsApp** (or add the **WhatsApp** product to a Business-type app).
3. Attach the app to your business portfolio.

Meta provisions a **test WhatsApp Business Account** with a free **test phone number**, and some layouts call this API Setup.

### 3c. Collect the IDs from API Setup

Open **WhatsApp, API Setup** (or **Use cases, Customize, API Setup**) and note:

- **Phone number ID**: goes in `WHATSAPP_PHONE_NUMBER_ID`
- **WhatsApp Business Account ID**: needed in Step 8
- **From** number: the number your phone will message in Step 9

### 3d. Allow your own phone to message the test number

In API Setup, under **To**, add your phone number and verify it with the code WhatsApp sends. A test number only accepts messages from numbers on this list.

### 3e. Copy the app secret

Open **App settings, Basic**, choose **Show** next to **App secret**, and put it in `.env` as `WHATSAPP_APP_SECRET`. It must be the secret of the same app that owns the test number. The server uses it to verify that every incoming request really came from Meta.

### 3f. Create an access token

The temporary token on API Setup expires in about 24 hours. For anything lasting, create a **system user** token:

1. In Business Settings, open **Users, System users** and add a system user.
2. Choose **Add assets** and give it your app and your WhatsApp account (full control).
3. Choose **Generate token**, select your app, and grant `whatsapp_business_messaging` and `whatsapp_business_management`.
4. Put it in `.env` as `WHATSAPP_ACCESS_TOKEN`.

This token is not used to receive messages, which only needs the app secret. You need it for Step 8 and for sending replies in a later phase.

### 3g. Invent a verify token

Make up any random string, for example with `python3 -c "import secrets;print(secrets.token_hex(16))"`. Put it in `.env` as `WHATSAPP_VERIFY_TOKEN`. You will paste the same value into Meta in Step 7.

## Step 4: Edit the policy pages

Meta requires a privacy policy and data deletion instructions before an app can be published. The app serves them at `/privacy` and `/data-deletion`.

1. Open `app/policy_pages.py`.
2. Set `CONTACT_EMAIL` to a mailbox you read. Check that `RETENTION_DAYS` and `DELETION_DAYS` are promises you can keep. No code deletes data automatically yet.
3. Read the text and make sure it matches what the code does.

## Step 5: Deploy on Railway

1. Push the code to a GitHub repository. Use a private repository if it contains anything you do not want public (see the last section).
2. In Railway choose **New Project, Deploy from GitHub repo** and select it. Railway reads `requirements.txt`, `.python-version`, and the `Procfile` (`uvicorn app.webhook:app`).
3. In the service's **Variables**, set exactly these three:
   - `WHATSAPP_APP_SECRET`
   - `WHATSAPP_VERIFY_TOKEN`
   - `DATABASE_URL`

   Railway keeps its own copy of variables. Changing `.env` locally does not change Railway. Do not set `PORT`.
4. Open **Settings, Networking** and choose **Generate Domain**.
5. Wait for the deploy to turn green, then check these:

```bash
curl -s https://<your-domain>/health
```

Expect `{"status":"ok"}`. Also open `https://<your-domain>/privacy` and `/data-deletion` in a browser.

### Check the verify handshake yourself

This is what Meta does when you register the webhook:

```bash
set -a; . ./.env; set +a
curl -s "https://<your-domain>/webhook?hub.mode=subscribe&hub.verify_token=$WHATSAPP_VERIFY_TOKEN&hub.challenge=777"
```

Expect `777`. If you get nothing, Railway's verify token differs from `.env`.

### Check a signed message and the database path (optional)

Send a signed synthetic payload and confirm a row appears. Expect HTTP 200, and 403 for an unsigned request. A 500 means the database rejected the connection. Check `DATABASE_URL` in **Railway**, not only locally.

## Step 6: Fill in the Meta app settings and publish

1. In **App settings, Basic**, set the **Privacy Policy URL** to `https://<your-domain>/privacy`.
2. Set the **User data deletion** option to **Data deletion instructions URL**, and use `https://<your-domain>/data-deletion`.
3. Complete any other required fields and switch the app to **Live** when Meta allows it.

## Step 7: Register the webhook

1. Open **WhatsApp, Configuration** (or **Use cases, Customize, Configuration**).
2. In the **Webhook** section choose **Edit**.
3. **Callback URL**: `https://<your-domain>/webhook` (note the `/webhook` at the end).
4. **Verify token**: the value of `WHATSAPP_VERIFY_TOKEN`.
5. Choose **Verify and save**.
6. In the **Webhook fields** table directly below, switch **messages** to **Subscribe**.
7. Choose **Test** on the `messages` row. Meta sends a canned sample. Check the Railway logs for `POST /webhook` with 200, and check the database. The sample's text is "this is a text message" with a 2017 timestamp.

A passing Test only proves the callback URL, the secret, and storage. It does **not** prove that real phone messages will arrive. That is Step 8.

## Step 8: Subscribe your app to the WhatsApp account (the easy-to-miss step)

The Test button sends from your app's own settings. Real messages are delivered only to apps **subscribed to the WhatsApp Business Account**. A new account may be subscribed only to a Meta-owned app, and then your webhook receives samples but never real messages.

Check which apps are subscribed:

```bash
set -a; . ./.env; set +a
curl -s "https://graph.facebook.com/v21.0/<waba-id>/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN"
```

If your app is not in the list, subscribe it:

```bash
curl -s -X POST "https://graph.facebook.com/v21.0/<waba-id>/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN"
```

Expect `{"success":true}`, then repeat the GET and confirm your app appears. If Meta returns a permission error, assign the WhatsApp account to the system user (Step 3f) and retry. You can also add the app to the account in Business Settings under **Accounts, WhatsApp accounts, Apps**.

## Step 9: Send a real message and check the database

1. On your phone, open WhatsApp and start a chat with the **From** number from API Setup. Send "test 1".
2. Within a few seconds, run:

```bash
.venv/bin/python -c "
from triage.config import load_dotenv; load_dotenv()
from app import store
with store.connect() as c:
    for r in c.execute('select id, text, profile_name, sent_at, received_at from messages order by id desc limit 3').fetchall(): print(r)
"
```

You should see your message with your real profile name and a current timestamp. The matching row in `jobs` has status `new`, waiting for the worker you set up in Step 13.

## Step 10: Create the Slack alert webhooks

Alerts use Slack incoming webhooks, which are plain URLs created in the browser.

1. Create two channels, for example `#p0-alerts` (reserve it for critical messages, so every ping gets attention) and a team channel.
2. Go to `api.slack.com/apps`, choose **Create New App, From scratch**, open **Incoming Webhooks**, and switch it on.
3. Choose **Add New Webhook to Workspace** once per channel and copy each URL (they start with `https://hooks.slack.com/services/`).
4. Put them in `.env` as `SLACK_P0_WEBHOOK_URL` and `SLACK_TEAM_WEBHOOK_URL`. Optionally add a third for system notices as `SLACK_BUILDER_WEBHOOK_URL`. Treat these URLs as secrets: anyone who has one can post to your channel.

P0 messages post with `@channel` to the first webhook, and P1 messages post with `@here` to the second. P2 and P3 only appear on the dashboard.

## Step 11: Configure the model endpoint

1. Set `QWEN_API_KEY` to your key.
2. Set `QWEN_BASE_URL` to the chat completions base, which ends in `/compatible-mode/v1`. The code calls `<base>/chat/completions` directly, so the older Anthropic-style address will not work.
3. Set `CLASSIFIER_MODEL` and `BACKUP_MODEL` to your fast and strong model names. The backup model re-checks low-confidence answers and takes over when the main model fails.
4. Optionally set `THINKING_MODE` (`on`, `off`, or `budget`; default `budget`) and `BACKUP_THINKING_MODE` (default `on`). Test results on the project's own labeled set showed full thinking off dropped a P0, while `budget` kept P0 recall with lower cost. Change this only after running the evaluation.
5. Test the endpoint:

```bash
.venv/bin/python -c "
from triage.config import get_settings; s = get_settings()
from triage.qwen import QwenClient
r = QwenClient(s.api_key, s.base_url).complete(s.classifier_model, 'Reply with one word.', 'Say ok', 50, {'enable_thinking': False})
print(repr(r.text), r.finish_reason)
"
```

Expect `'ok' stop`. An HTTP error here names the problem, such as a wrong key or address.

## Step 12: Load gifter tiers and live hosts

The worker needs a `gifters` table (tier and linked hosts) and a `live_status` table (which hosts are live). Load the invented mock data, or your own:

```bash
.venv/bin/python -m app.seed                               # mock tiers and live hosts
.venv/bin/python -m app.seed tier <whatsapp-number> top "Name"   # make a number top-tier
.venv/bin/python -m app.seed live <host> on                # mark a host live (or off)
```

A top-tier gifter moves from P2 to P1 and gets a shorter P1 deadline. A live host moves a VIP request to P1 and shortens a failed gift to 10 minutes. Keep `live_status` current: the monitoring silence alert only runs while a host is marked live.

## Step 13: Deploy the worker (second Railway service)

1. In the same Railway project, add a second service from your **private** repository (the worker needs the taxonomy, prompts, and labeled data that the public repository leaves out).
2. Set its start command to `python -m app.worker`.
3. Give it these variables: `DATABASE_URL`, `QWEN_API_KEY`, `QWEN_BASE_URL`, `CLASSIFIER_MODEL`, `BACKUP_MODEL`, `SLACK_P0_WEBHOOK_URL`, `SLACK_TEAM_WEBHOOK_URL`. Add `SLACK_BUILDER_WEBHOOK_URL` and the thinking settings if you use them.
4. Open its logs. You should see `worker started` and no `model_down` or `relation ... does not exist` errors.

## Step 14: Test the triage end to end

From your phone, send these to the test number and check the result. (Your phone is a "standard" tier gifter unless you changed it in Step 12.)

| Message | Expected category | Priority | Slack |
| --- | --- | --- | --- |
| Got charged twice for 7,000 coins | payment_issue | P1, 30 min | team channel |
| Someone is messaging hosts pretending to be me | account_security | P0, 5 min | `#p0-alerts` with @channel |
| What time does she go live Friday? | general_question | P2, 4 hours | none (dashboard only) |
| Last night's stream was amazing | positive_feedback | P3 | none |

Then read the results:

```bash
.venv/bin/python -c "
from triage.config import load_dotenv; load_dotenv()
from app import store
with store.connect() as c:
    for r in c.execute('select substr(m.text,1,40), r.category, r.priority, r.deadline_minutes, r.alert_status, r.fallback from triage_results r join messages m on m.id = r.message_id order by r.id desc limit 6').fetchall(): print(r)
"
```

A `fallback` value of `model_down`, `model_empty`, or `parse_failed` means the model path failed for that message. Anything with a safety or security keyword is P0 regardless of the model.

## Step 15: Open the dashboard

```bash
.venv/bin/streamlit run dashboard/app.py --server.address localhost
```

Open `http://localhost:8501`. The queue is sorted by priority then deadline, with overdue items in red. **Mark replied** closes a sender's open items and, together with the worker, drives the repeat-sender rule (3 or more unreplied messages in 10 minutes lifts a message one level, never to P0). **Correct label** records the right answer for review. The dashboard has no login, so keep `--server.address localhost` and never put it on a public address. To look at it with invented data first, run `.venv/bin/python tools/demo_queue.py` and use the command it prints.

## Step 16: Turn on the production safeguards

- **Monitoring** runs inside the worker and needs no setup beyond Slack. It alerts on a stalled queue, on silence while a host is live, and on a model error rate above 5%.
- **Retention:** run `.venv/bin/python -m app.retention status`. The privacy page promises message text is removed after 90 days. The worker only does this daily if you set `RETENTION_ENABLED=true`, which permanently deletes text, so try `purge` (a dry run) first.
- **Deletion requests:** when someone emails "Delete my data", run `.venv/bin/python -m app.retention delete-sender <number> --apply` within 30 days and confirm by email.
- **Real labeled set (optional):** corrections can be turned into a de-identified test set kept in the private database, reviewed by a person on the dashboard's second page. See the README.

## Troubleshooting

| What you see | Likely cause | Fix |
| --- | --- | --- |
| Database check fails with "password authentication failed" | Brackets still around the password, a stale or reset password, or Railway holding an older `DATABASE_URL` | Remove the brackets, reset the password and wait a minute, update both `.env` and Railway |
| Signed test returns 500 only on Railway | Railway's `DATABASE_URL` differs from `.env` | Update the variable in Railway and wait for the redeploy |
| `POST /webhook` returns 403 in the logs | App secret in Railway does not match the app that owns the number | Re-copy it from App settings, Basic |
| Verify and save fails | Verify token or URL mismatch | Re-run the handshake check in Step 5 |
| Test button works, real messages never arrive | Your app is not subscribed to the WhatsApp account | Step 8 |
| Messages from your phone are ignored | Phone is not on the **To** list, or you messaged the wrong number | Step 3d and check the **From** number |
| Graph API says the session has expired | Temporary token expired | Generate a system user token (Step 3f) |
| Policy URL rejected by Meta | Contact email is still a placeholder | Step 4 |
| Worker logs `relation ... does not exist`, or every job fails | A migration was not run in Supabase | Run the missing `sql/*.sql` files (Step 2) |
| Messages get `model_down` | Wrong `QWEN_BASE_URL` (the old Anthropic-style address), a bad key, or the endpoint is down | Steps 11 and the worker logs |
| Messages get `model_empty` or the model times out | The model spent its whole token budget thinking | Keep `THINKING_MODE=budget` or `off`; the code already retries without history, then the backup model |
| Alert shows `alert_status = failed` | Slack webhook URL missing or wrong | Step 10; failed alerts are retried automatically |
| A "silence" notice in Slack on a quiet line | A host is marked live but nobody is messaging | Turn the host off with `app.seed live <host> off` |
| Dashboard says "Could not load the queue" | `DATABASE_URL` wrong, or the Phase 3 and 4 tables are missing | Step 2 |

## Keeping private files private

The taxonomy (`categories.yaml`), classifier prompts (`triage/prompts/`), and labeled data (`data/labeled_messages.csv`) are not meant for a public repository. A workable setup is two repositories: a public one with only the code, and a private one that also holds those files and is the one Railway deploys from. The webhook runs without those files. The worker, the classifier, and the priority code do need them, so deploy the worker from the private repository (Step 13).

## Security checklist

- Keep `.env` out of git. Check with `git ls-files | grep env`, which should list only `.env.example`.
- Rotate any secret that was pasted into a chat, a screenshot, or a log.
- Keep Supabase row level security on. The app connects directly and is unaffected by it.
- Use synthetic data in tests and fixtures. Never real gifter messages.
- Run the dashboard on localhost only. It has no login.
- Slack webhook URLs are secrets. Anyone with one can post to your channel.
