#!/usr/bin/env python3
"""
Sends a daily motivational-quote email.

Content: asks Claude to write a short, original motivational line + a
one-sentence reflection (not attributed to a real person, to avoid
misquoting/misattributing anyone). If that call fails for any reason,
falls back to a random quote from quotes.json so an email still goes out.

Delivery: Resend's HTTP API.

Required env vars:
  RESEND_API_KEY   Resend API key
  TO_EMAIL         Recipient address(es), comma-separated
  FROM_EMAIL       Verified sender, e.g. "Daily Quote <quote@yourdomain.com>"

Optional:
  ANTHROPIC_API_KEY  If unset, skips straight to the local quotes.json fallback.
"""

import json
import os
import random
import sys
from datetime import date
from pathlib import Path

import requests

QUOTES_FILE = Path(__file__).parent / "quotes.json"
CLAUDE_MODEL = "claude-haiku-4-5"  # cheapest current model; good enough for a one-line quote
RESEND_API_URL = "https://api.resend.com/emails"

QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "quote": {
            "type": "string",
            "description": "A short, original, one-sentence motivational line.",
        },
        "reflection": {
            "type": "string",
            "description": "One or two sentences expanding on the quote.",
        },
    },
    "required": ["quote", "reflection"],
    "additionalProperties": False,
}


def generate_quote_from_claude() -> dict:
    """Ask Claude for an original quote + reflection. Raises on any failure."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    today = date.today().strftime("%A, %B %d, %Y")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        # Note: no `effort` here — Haiku 4.5 doesn't support output_config.effort (400s).
        output_config={"format": {"type": "json_schema", "schema": QUOTE_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Today is {today}. Write one short, original motivational "
                    "quote (a single sentence, not a real quote attributed to "
                    "anyone) and a one-to-two sentence reflection on it. Keep "
                    "the tone warm and grounded, not cliched."
                ),
            }
        ],
    )

    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return {"quote": data["quote"], "author": "Today's reflection", "reflection": data.get("reflection", "")}


def get_fallback_quote() -> dict:
    """Pick a random quote from the local JSON file."""
    quotes = json.loads(QUOTES_FILE.read_text())
    picked = random.choice(quotes)
    return {"quote": picked["quote"], "author": picked["author"], "reflection": ""}


def get_content() -> dict:
    try:
        content = generate_quote_from_claude()
        print("Generated quote via Claude API.")
        return content
    except Exception as e:
        print(f"Claude generation failed ({e}); falling back to quotes.json.")
        return get_fallback_quote()


def render_email(content: dict) -> tuple[str, str]:
    today_str = date.today().strftime("%A, %B %d, %Y")
    reflection_html = (
        f'<p style="margin:24px 0 0; color:#555; font-size:15px; line-height:1.6;">{content["reflection"]}</p>'
        if content.get("reflection")
        else ""
    )

    html = f"""\
<div style="max-width:520px; margin:0 auto; padding:40px 24px; font-family:Georgia,'Times New Roman',serif;">
  <p style="margin:0 0 32px; color:#999; font-size:13px; letter-spacing:0.05em; text-transform:uppercase;">{today_str}</p>
  <blockquote style="margin:0; padding:0; border:none; font-size:24px; line-height:1.5; color:#1a1a1a;">
    &ldquo;{content["quote"]}&rdquo;
  </blockquote>
  <p style="margin:16px 0 0; color:#777; font-size:14px;">&mdash; {content["author"]}</p>
  {reflection_html}
</div>
"""
    subject = f"Today's quote — {date.today().strftime('%b %d')}"
    return subject, html


def send_email(subject: str, html: str) -> None:
    api_key = os.environ["RESEND_API_KEY"]
    to_email = [addr.strip() for addr in os.environ["TO_EMAIL"].split(",") if addr.strip()]
    from_email = os.environ["FROM_EMAIL"]

    resp = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": from_email, "to": to_email, "subject": subject, "html": html},
        timeout=30,
    )

    if resp.status_code >= 400:
        raise RuntimeError(f"Resend API error {resp.status_code}: {resp.text}")

    print(f"Email sent. Resend id: {resp.json().get('id')}")


def main() -> int:
    missing = [v for v in ("RESEND_API_KEY", "TO_EMAIL", "FROM_EMAIL") if not os.environ.get(v)]
    if missing:
        print(f"Missing required env var(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    content = get_content()
    subject, html = render_email(content)

    try:
        send_email(subject, html)
    except Exception as e:
        print(f"Failed to send email: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
