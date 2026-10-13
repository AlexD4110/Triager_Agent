# Gifter Triage Agent

Reads inbound WhatsApp messages from live-stream gifters, labels each one with a category and a priority (P0 critical to P3 low), and alerts a human. It is receive-only: a person sends every reply.

## Status

| Phase | What | State |
| --- | --- | --- |
| 0 | Taxonomy and labeled dataset | Done (kept local, see below) |
| 1 | Offline classifier, priority rules, evaluation script | Done |
| 2 | WhatsApp webhook and storage | Built, being deployed |
| 3 | Worker, Slack alerts, gifter and live-status tables | Not started |
| 4 | Streamlit queue and correction loop | Not started |
| 5 | Production monitoring and retention | Not started |

## How it works

```
Gifter (WhatsApp) -> Meta Cloud API -> FastAPI webhook -> Postgres (messages + jobs)
                                                              |
                                                     worker (Phase 3) polls jobs
                                                              v
                                   rules -> model labels -> prioritize() -> alerts
```

- **Webhook** (`app/webhook.py`): verifies Meta's signature, saves the raw payload, ignores a message ID (`wamid`) it has seen before, and returns 200 right away. No model calls happen here.
- **Rules** (`triage/rules.py`): masks card numbers, filters noise, and flags safety and security keywords before the model runs. These flags can be added to, never removed.
- **Classifier** (`triage/classify.py`): the model returns a category, flags, summary, and confidence as JSON, checked with Pydantic. It never returns a priority. If the main model fails or is unsure, it retries without the sender's history, then a backup model runs.
- **Priority** (`triage/prioritize.py`): plain code turns the label into P0 to P3 and a response deadline. Anything flagged for safety or security is always P0, and modifiers (top-tier gifter, host live, repeat sender) never raise a message to P0.
- **Receive-only**: the code makes no outbound WhatsApp calls and does not mark messages as read.

## What is not in this repository

The taxonomy (`categories.yaml`), the classifier prompts (`triage/prompts/`), and the labeled evaluation data (`data/labeled_messages.csv`) are kept private on purpose. The webhook does not need them. The classifier, `prioritize()`, and `eval.py` do, so you must supply your own copies to run those.

## Setup

Requires Python 3.12.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in the values
.venv/bin/pytest -q
```

### Environment variables

Secrets live in `.env` (never committed). `.env.example` lists the names.

| Name | Used for |
| --- | --- |
| `WHATSAPP_APP_SECRET` | Meta app secret, used to verify webhook signatures |
| `WHATSAPP_VERIFY_TOKEN` | A string you invent; Meta sends it back when you register the webhook |
| `DATABASE_URL` | Supabase Postgres connection string. If empty, local SQLite is used |
| `SQLITE_PATH` | SQLite file for local development (default `data/triage.db`) |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Unused until replies exist in Phase 6 |
| `QWEN_API_KEY`, `QWEN_BASE_URL` | Model endpoint for the classifier. The base URL ends in `/compatible-mode/v1`; the app calls `<base>/chat/completions` with the standard library, no model SDK |
| `CLASSIFIER_MODEL`, `BACKUP_MODEL` | Main and backup model names |
| `CONFIDENCE_CUTOFF` | Below this confidence the backup model re-checks (default 0.6) |
| `THINKING_MODE`, `BACKUP_THINKING_MODE` | `on`, `off`, or `budget`: whether the main and backup models reason before answering (default `on`) |
| `THINKING_BUDGET`, `MAX_OUTPUT_TOKENS` | Reasoning token cap used by `budget` mode (default 256), and the reply token limit (default 2000) |

## Database (Supabase)

1. Create a Supabase project and copy the Postgres connection string (Project Settings, Database).
2. Put it in `DATABASE_URL` with the real password and **no square brackets** around it. Special characters in the password must be URL-encoded.
3. Open the Supabase SQL editor, paste `sql/schema.sql`, and run it once. It creates `raw_payloads`, `messages`, and `jobs`, and turns on row level security with no policies so Supabase's public API cannot read gifter messages. The app connects directly as the database owner, which is unaffected.

## Run locally

```bash
.venv/bin/uvicorn app.webhook:app --port 8000
curl localhost:8000/health
```

## Deploy to Railway

1. Push this repository to GitHub.
2. In Railway, choose **New Project, Deploy from GitHub repo**, and pick this repository. Railway reads `requirements.txt`, `.python-version`, and the `Procfile` (`uvicorn app.webhook:app`), so no build settings are needed.
3. In the service's **Variables**, set `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, and `DATABASE_URL`. Do not set `PORT`; Railway provides it.
4. Under **Settings, Networking**, choose **Generate Domain** to get a public HTTPS URL.
5. Check `https://<your-domain>/health`. It should return `{"status":"ok"}`.
6. Local SQLite is wiped on every Railway deploy, so use `DATABASE_URL` (Supabase) for anything you want to keep.

## Register the webhook with Meta

1. In the Meta developer app, open **WhatsApp, Configuration, Webhook, Edit**.
2. Set **Callback URL** to `https://<your-domain>/webhook` and **Verify token** to your `WHATSAPP_VERIFY_TOKEN`. Choose **Verify and save**.
3. Subscribe to the **messages** field.
4. Send a WhatsApp message to your test number. A row should appear in the `messages` table within about 2 seconds.

A GET request with the wrong verify token returns 403, and a POST with a missing or wrong signature returns 403 and stores nothing.

## Safety notes

- Never commit `.env`. It is listed in `.gitignore`.
- All test data and fixtures must be synthetic. Card numbers are masked before any text reaches the model.
- Messages can contain names, spend, and payment details. Plan a retention limit before going live.
