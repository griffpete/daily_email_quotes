#!/usr/bin/env python3
"""
Sends a daily motivation email for a solo freelance dev founder (Peregrine.dev).

Content, three parts:
  1. An original quote about startups/founders (not attributed to a real
     person, to avoid misquoting anyone).
  2. A real, positive, money-related fact about startups/founders/freelance
     developers. To keep this honest, Claude looks it up via web search
     rather than recalling a number from memory (LLMs can produce
     plausible-sounding but fabricated statistics) and cites a source.
  3. One concrete task to work on today.

This runs as two Claude calls: one with web search to research the fact,
one (structured JSON output) to compose the final email content using that
researched fact plus an original quote and task. If either call fails,
falls back to a curated entry from quotes.json so an email still goes out
(those fallback facts are hand-checked by us, not live-searched).

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
CLAUDE_MODEL = "claude-haiku-4-5"  # cheapest current model; plenty for this
RESEND_API_URL = "https://api.resend.com/emails"

FOUNDER_CONTEXT = (
    "The reader is a solo freelance web developer who runs their own "
    "one-person dev shop called Peregrine.dev."
)

RESEARCH_PROMPT = (
    "Search the web for one real, verifiable, POSITIVE statistic that "
    "connects money to startups, founders, or freelance/independent "
    "software developers — for example typical freelance developer rates, "
    "the size of the freelance economy, startup funding or exit trends, or "
    "a well-known bootstrapped/solo success story with real revenue or "
    "acquisition numbers. It must be a genuine figure you can find via "
    "search and cite — do not estimate or invent one. State the fact in "
    "one sentence, then on a new line write 'Source: <publication or "
    "organization name>'."
)

EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "quote": {
            "type": "string",
            "description": (
                "A short, original, one-sentence motivational quote about "
                "startups, founders, or the solo/freelance grind. Not "
                "attributed to any real person."
            ),
        },
        "money_fact": {
            "type": "string",
            "description": "The researched fact, tightened to one crisp sentence.",
        },
        "money_fact_source": {
            "type": "string",
            "description": "Short source name for the fact, e.g. 'Upwork Freelance Forward 2024'.",
        },
        "task": {
            "type": "string",
            "description": (
                "One concrete, specific task to work on today to grow a solo "
                "freelance dev business — e.g. prospecting, outreach, "
                "portfolio work, pricing, or client follow-up. Should read "
                "like a to-do item, not vague advice."
            ),
        },
    },
    "required": ["quote", "money_fact", "money_fact_source", "task"],
    "additionalProperties": False,
}


def research_money_fact(client) -> str:
    """Web-search for a real, citable money fact. Returns raw text. Raises on failure."""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        messages=[{"role": "user", "content": RESEARCH_PROMPT}],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("web search call returned no text")
    return text


def compose_email_content(client, researched_fact: str) -> dict:
    """Turn the researched fact + a fresh quote/task into structured email content."""
    today = date.today().strftime("%A, %B %d, %Y")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        # Note: no `effort` here — Haiku 4.5 doesn't support output_config.effort (400s).
        output_config={"format": {"type": "json_schema", "schema": EMAIL_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Today is {today}. {FOUNDER_CONTEXT}\n\n"
                    "Here is a researched fact to use as-is (do not invent a "
                    f"different one, just tighten the wording):\n{researched_fact}\n\n"
                    "Write:\n"
                    "1. An original one-sentence quote about startups/founders/"
                    "the solo grind — warm and grounded, not cliched.\n"
                    "2. That money fact, tightened to one sentence, plus its source.\n"
                    "3. One specific, concrete task for today to grow a solo "
                    "freelance dev business."
                ),
            }
        ],
    )

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def generate_content_from_claude() -> dict:
    """Runs both Claude calls. Raises on any failure (caller falls back)."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    researched_fact = research_money_fact(client)
    return compose_email_content(client, researched_fact)


def get_fallback_content() -> dict:
    """Pick a random hand-curated entry from the local JSON file."""
    entries = json.loads(QUOTES_FILE.read_text())
    return random.choice(entries)


def get_content() -> dict:
    try:
        content = generate_content_from_claude()
        print("Generated content via Claude API (with web search).")
        return content
    except Exception as e:
        print(f"Claude generation failed ({e}); falling back to quotes.json.")
        return get_fallback_content()


def render_email(content: dict) -> tuple[str, str]:
    today_str = date.today().strftime("%A, %B %d, %Y")

    html = f"""\
<div style="max-width:560px; margin:0 auto; padding:40px 24px; font-family:Georgia,'Times New Roman',serif;">
  <p style="margin:0 0 32px; color:#999; font-size:13px; letter-spacing:0.05em; text-transform:uppercase;">{today_str} &middot; Peregrine.dev</p>

  <blockquote style="margin:0; padding:0; border:none; font-size:24px; line-height:1.5; color:#1a1a1a;">
    &ldquo;{content["quote"]}&rdquo;
  </blockquote>

  <div style="margin:32px 0 0; padding:20px; background:#f7f5f0; border-radius:8px;">
    <p style="margin:0; color:#333; font-size:15px; line-height:1.6;">💰 {content["money_fact"]}</p>
    <p style="margin:8px 0 0; color:#999; font-size:12px;">Source: {content["money_fact_source"]}</p>
  </div>

  <div style="margin:24px 0 0; padding:20px; background:#eef4f0; border-radius:8px;">
    <p style="margin:0 0 4px; color:#1a1a1a; font-size:13px; font-weight:bold; letter-spacing:0.03em; text-transform:uppercase;">Today's focus</p>
    <p style="margin:0; color:#333; font-size:15px; line-height:1.6;">{content["task"]}</p>
  </div>
</div>
"""
    subject = f"Founder fuel — {date.today().strftime('%b %d')}"
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
