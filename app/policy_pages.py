"""Public policy pages Meta requires to publish a WhatsApp app: GET /privacy and GET /data-deletion.

Edit the constants below. No login or key is needed to read these pages.
"""
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

BUSINESS_NAME = "Gifter Triage"
CONTACT_EMAIL = "privacy@example.com"  # CHANGE THIS to a mailbox you read before publishing the app
RETENTION_DAYS = 90  # how long message content is kept
DELETION_DAYS = 30  # how fast a deletion request is completed
LAST_UPDATED = "October 13, 2026"

router = APIRouter()

_STYLE = (
    "body{font:16px/1.6 system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a}"
    "h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:1.8rem}a{color:#0b57d0}"
)


def _page(title: str, body: str) -> HTMLResponse:
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head><body>"
        f"<h1>{escape(title)}</h1><p><em>Last updated {escape(LAST_UPDATED)}</em></p>{body}</body></html>"
    )
    return HTMLResponse(html, status_code=200)


@router.get("/privacy", response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    name, email = escape(BUSINESS_NAME), escape(CONTACT_EMAIL)
    body = f"""
<p>{name} (&ldquo;we&rdquo;) runs a WhatsApp Business number that our gifter relations team uses to
help people who send gifts on live streams. This page explains what happens to your information when you
message that number.</p>

<h2>What we collect</h2>
<ul>
<li>Your WhatsApp phone number</li>
<li>Your WhatsApp profile name, if WhatsApp provides it</li>
<li>The content of the messages you send us</li>
<li>The time each message was sent</li>
</ul>
<p>We also keep the full technical record WhatsApp delivers to us for each message, which holds the items
above and some technical details such as the message type and our business number.</p>

<h2>How we use it</h2>
<p>We use your messages only to sort them by urgency, so that urgent problems reach a person quickly, and
so that our team can respond to you. A person on our team writes every reply. Our system does not send
automatic replies.</p>

<h2>AI processing</h2>
<p>Yes. To sort messages by topic and urgency, the text of your message is sent to a third-party artificial
intelligence language model service. Payment card numbers are masked before the text is sent. The AI only
labels the message, such as the topic and whether it looks urgent. Our own rules, not the AI, decide the
priority.</p>

<h2>Where it is stored</h2>
<p>Messages are stored with a hosted database provider and processed on a cloud hosting provider, both
located in the United States. Access is limited to our team.</p>

<h2>How long we keep it</h2>
<p>We keep the content of your messages for up to {RETENTION_DAYS} days. After that we delete the message
text and keep only the category and priority labels, which do not include your message.</p>

<h2>We do not sell your data</h2>
<p>We do not sell your information or share it for advertising.</p>

<h2>Your choices</h2>
<p>You can ask us to delete your data at any time. See our
<a href="/data-deletion">data deletion instructions</a>. You can also stop messaging us whenever you like.</p>

<h2>Contact</h2>
<p>Questions about this policy: <a href="mailto:{email}">{email}</a></p>
"""
    return _page("Privacy Policy", body)


@router.get("/data-deletion", response_class=HTMLResponse)
def data_deletion() -> HTMLResponse:
    email = escape(CONTACT_EMAIL)
    body = f"""
<p>You can ask us to delete the information we hold about you from our WhatsApp Business number.</p>

<h2>How to request deletion</h2>
<ol>
<li>Send an email to <a href="mailto:{email}?subject=Delete%20my%20data">{email}</a>.</li>
<li>Use the subject line <strong>Delete my data</strong>.</li>
<li>In the email, include the WhatsApp phone number you used to message us, with the country code, so we
can find your records.</li>
</ol>

<h2>What happens next</h2>
<p>We delete your phone number, profile name, and message content within {DELETION_DAYS} days of your
request, and we confirm by email when it is done.</p>

<p>See also our <a href="/privacy">privacy policy</a>.</p>
"""
    return _page("Data Deletion Instructions", body)
