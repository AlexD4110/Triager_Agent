# Setup Guide: from zero to a message landing in the database

This is the exact sequence needed to get an inbound WhatsApp message stored in Supabase through a Railway-hosted webhook. Placeholders in angle brackets, such as `<your-domain>`, are values you create along the way. Never paste real secrets into chat, screenshots, issues, or commits.

Total time: about one to two hours, most of it Meta setup.

## What you need first

- A computer with Python 3.12 and git
- A GitHub account
- A Meta account that can create a business portfolio and a developer app
- A Supabase account (hosted Postgres)
- A Railway account (hosting)
- A key for the language model service used by the classifier
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
4. Open the Supabase **SQL editor**, paste the contents of `sql/schema.sql`, and run it once. It creates `raw_payloads`, `messages`, and `jobs`, and turns on row level security with no policies, so Supabase's public API cannot read gifter messages.
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

You should see your message with your real profile name and a current timestamp. The matching row in `jobs` has status `new`, waiting for the worker built in the next phase.

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

## Keeping private files private

The taxonomy (`categories.yaml`), classifier prompts (`triage/prompts/`), and labeled data (`data/labeled_messages.csv`) are not meant for a public repository. A workable setup is two repositories: a public one with only the code, and a private one that also holds those files and is the one Railway deploys from. The webhook runs without those files. The classifier and priority code, run in the next phase, do need them.

## Security checklist

- Keep `.env` out of git. Check with `git ls-files | grep env`, which should list only `.env.example`.
- Rotate any secret that was pasted into a chat, a screenshot, or a log.
- Keep Supabase row level security on. The app connects directly and is unaffected by it.
- Use synthetic data in tests and fixtures. Never real gifter messages.
