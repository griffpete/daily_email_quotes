#!/usr/bin/env python3
"""
Sends Griffin's daily "work hard / play hard" email.

Content, four parts:
  1. An original quote (not attributed to a real person, to avoid misquoting
     anyone) — generated fresh by Claude.
  2. WORK HARD: one concrete task for whichever business is up today —
     Peregrine.dev or Prizm, rotated by weight in profile.json.
  3. PLAY HARD: one concrete task for whichever hobby is up today — climbing,
     chess, the dogs, an adventure with Dani, or NFL — also rotated, with
     NFL limited to the season and weekend tracks boosted on weekends.
  4. A real, positive, money-related fact about startups/founders/freelance
     developers — picked from facts.json, a hand-verified local list, rotated
     by day-of-year so it cycles through every entry before repeating.
     (An earlier version had Claude research this live via web search each
     day, but the search tool's per-query fee made that the dominant cost —
     a static, pre-checked list keeps the facts just as real for a fraction
     of the price.)

Staying fresh: every send is appended to history.json, and the last few weeks
of quotes and tasks are handed back to Claude as a do-not-repeat list. The
GitHub Actions workflow commits history.json back to the repo after each run,
which is what makes the memory survive between runs.

Who the email is for and what it may talk about lives in profile.json — edit
that file, not this one, to change the mix.

If the Claude call fails for any reason, falls back to a curated entry in
quotes.json plus a play task from profile.json, so an email still goes out.

Delivery: Resend's HTTP API.

Required env vars:
  RESEND_API_KEY   Resend API key
  TO_EMAIL         Recipient address(es), comma-separated
  FROM_EMAIL       Verified sender, e.g. "Daily Quote <quote@yourdomain.com>"

Optional:
  ANTHROPIC_API_KEY  If unset, skips straight to the local quotes.json fallback.
  DRY_RUN=1          Print the email and skip Resend (and skip writing history).
"""

import json
import os
import random
import sys
from datetime import date, datetime
from pathlib import Path

import requests

HERE = Path(__file__).parent
FACTS_FILE = HERE / "facts.json"
QUOTES_FILE = HERE / "quotes.json"
PROFILE_FILE = HERE / "profile.json"
HISTORY_FILE = HERE / "history.json"

CLAUDE_MODEL = "claude-sonnet-5"
RESEND_API_URL = "https://api.resend.com/emails"

# claude-sonnet-5 pricing, $/1M tokens — update if Anthropic's pricing changes.
MODEL_INPUT_PER_M = 2.00
MODEL_OUTPUT_PER_M = 10.00

HISTORY_KEEP = 90  # entries retained in history.json
HISTORY_SHOWN = 21  # recent entries handed to Claude as a do-not-repeat list
# With only two businesses, excluding yesterday's pick outright would force a
# strict every-other-day alternation and ignore the weights in profile.json. So
# work repeats are allowed — the weighting decides the mix — but a run of the
# same business is capped so the other one never goes quiet for long. Hobbies
# have enough tracks to simply skip the recent ones.
WORK_MAX_STREAK = 3  # after this many days on one business, switch
AVOID_LAST_PLAY = 2  # don't pick the same hobby as the last N days

CONTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "quote": {
            "type": "string",
            "description": (
                "A short, original, one-sentence line that would land for a "
                "hungry young founder who lives by 'work hard / play hard'. "
                "Warm and grounded, not a cliche, not corporate. Not "
                "attributed to any real person."
            ),
        },
        "work_task": {
            "type": "string",
            "description": (
                "One concrete task for TODAY on the assigned business. Names "
                "the specific thing to do, like a to-do item he could start "
                "in the next hour — not vague advice, not a multi-week "
                "project. One or two sentences."
            ),
        },
        "play_task": {
            "type": "string",
            "description": (
                "One concrete thing to do TODAY for the assigned hobby, sized "
                "to the day of the week. Encouraging and specific. One or two "
                "sentences."
            ),
        },
    },
    "required": ["quote", "work_task", "play_task"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- selection


def load_profile() -> dict:
    return json.loads(PROFILE_FILE.read_text())


def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except json.JSONDecodeError:
        print("history.json is unreadable; starting a fresh history.")
        return []


def in_season(track: dict, today: date) -> bool:
    """True if today falls inside a track's season window (MM-DD, may wrap)."""
    season = track.get("season")
    if not season:
        return True
    today_md = today.strftime("%m-%d")
    start, end = season["start"], season["end"]
    if start <= end:
        return start <= today_md <= end
    return today_md >= start or today_md <= end  # wraps past New Year


def pick_track(
    tracks: list,
    history: list,
    key: str,
    today: date,
    avoid_last: int = 0,
    max_streak: int = 0,
) -> dict:
    """Weighted random pick, skipping out-of-season tracks and recent repeats.

    avoid_last — exclude anything picked in the last N days.
    max_streak — exclude a track that has been picked N days running.
    """
    weekday = today.strftime("%A")
    eligible = [t for t in tracks if in_season(t, today)]

    blocked = set(entry.get(key) for entry in history[-avoid_last:]) if avoid_last else set()
    if max_streak:
        tail = [entry.get(key) for entry in history[-max_streak:]]
        if len(tail) == max_streak and len(set(tail)) == 1:
            blocked.add(tail[0])

    pool = [t for t in eligible if t["id"] not in blocked] or eligible

    weights = [
        max(t.get("weight", 1) * t.get("boost_days", {}).get(weekday, 1), 0.01) for t in pool
    ]
    return random.choices(pool, weights=weights, k=1)[0]


def get_daily_fact() -> dict:
    """Pick today's money fact from facts.json, rotating by day-of-year."""
    facts = json.loads(FACTS_FILE.read_text())
    idx = (date.today().timetuple().tm_yday - 1) % len(facts)
    return facts[idx]


# ---------------------------------------------------------------- generation


def log_usage(response) -> None:
    """Print the exact token usage and cost for this one API call."""
    u = response.usage
    cost = (u.input_tokens / 1_000_000) * MODEL_INPUT_PER_M + (
        u.output_tokens / 1_000_000
    ) * MODEL_OUTPUT_PER_M
    print(f"Claude usage: {u.input_tokens} input + {u.output_tokens} output tokens -> ~${cost:.6f}")


def format_recent(history: list) -> str:
    """Render recent sends as a do-not-repeat list for the prompt."""
    recent = history[-HISTORY_SHOWN:]
    if not recent:
        return "Nothing has been sent yet — this is the first email."

    lines = []
    for entry in recent:
        lines.append(f"- {entry.get('date', '?')}")
        lines.append(f"  quote: {entry.get('quote', '')}")
        lines.append(f"  work ({entry.get('work_track', '?')}): {entry.get('work_task', '')}")
        lines.append(f"  play ({entry.get('play_track', '?')}): {entry.get('play_task', '')}")
    return "\n".join(lines)


def build_prompt(profile: dict, work_track: dict, play_track: dict, history: list) -> str:
    today = date.today()
    return f"""Today is {today.strftime('%A, %B %d, %Y')}.

You write a short daily email for {profile['owner']}. His motto this year is "{profile['motto']}" — the email encourages him to work hard AND to actually live his life.

WHAT DRIVES HIM
{profile['drive']}

TODAY'S WORK FOCUS — {work_track['name']}
{work_track['context']}

TODAY'S PLAY FOCUS — {play_track['name']}
{play_track['context']}

ALREADY SENT (last {HISTORY_SHOWN} emails — do not repeat these, or close variations of them; find a different angle)
{format_recent(history)}

Write three things:
1. quote — one original sentence, no attribution.
2. work_task — one concrete task for today on {work_track['name']}, and only that business.
3. play_task — one concrete thing to do today for {play_track['name']}.

Rules:
- Be specific. Name the actual action, not the category. "Email the three garage door distributors Kalar introduced you to and ask for 15 minutes each" beats "do some outreach".
- Size both tasks to a real {today.strftime('%A')}: a weekday evening is short, a weekend has room for something bigger.
- Assume he is doing this alone today unless the track says otherwise.
- No preamble, no praise, no explaining the task's importance — just the task.
- Do not reuse the phrasing, structure or opening words of anything in the already-sent list."""


def generate_content(profile: dict, work_track: dict, play_track: dict, history: list) -> dict:
    """Ask Claude for today's quote + both tasks. Raises on any failure."""
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic()

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        output_config={
            "format": {"type": "json_schema", "schema": CONTENT_SCHEMA},
            "effort": "low",  # short creative task; keeps cost and latency down
        },
        messages=[{"role": "user", "content": build_prompt(profile, work_track, play_track, history)}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")

    log_usage(response)
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def get_fallback_content(profile: dict, play_track: dict, history: list) -> dict:
    """Hand-curated quote + work task from quotes.json, play task from profile.json."""
    entry = random.choice(json.loads(QUOTES_FILE.read_text()))
    by_track = profile["fallback_play_tasks"]
    options = by_track.get(play_track["id"]) or [t for v in by_track.values() for t in v]
    recent = {e.get("play_task") for e in history[-10:]}
    fresh = [t for t in options if t not in recent] or options
    return {
        "quote": entry["quote"],
        "work_task": entry["task"],
        "play_task": random.choice(fresh),
    }


# ---------------------------------------------------------------- output


def render_email(content: dict, work_track: dict, play_track: dict, source: str) -> tuple[str, str]:
    today_str = date.today().strftime("%A, %B %d, %Y")
    # Fallback work tasks come from the generic quotes.json list, so they aren't
    # about the track we picked — don't label them with its name.
    work_label = f" &middot; {work_track['name']}" if source == "claude" else ""

    html = f"""\
<div style="max-width:560px; margin:0 auto; padding:40px 24px; font-family:Georgia,'Times New Roman',serif;">
  <p style="margin:0 0 32px; color:#999; font-size:13px; letter-spacing:0.05em; text-transform:uppercase;">{today_str} &middot; Work hard / play hard</p>

  <blockquote style="margin:0; padding:0; border:none; font-size:24px; line-height:1.5; color:#1a1a1a;">
    &ldquo;{content["quote"]}&rdquo;
  </blockquote>

  <div style="margin:32px 0 0; padding:20px; background:#eef4f0; border-radius:8px;">
    <p style="margin:0 0 4px; color:#1a1a1a; font-size:13px; font-weight:bold; letter-spacing:0.03em; text-transform:uppercase;">Work hard{work_label}</p>
    <p style="margin:0; color:#333; font-size:15px; line-height:1.6;">{content["work_task"]}</p>
  </div>

  <div style="margin:16px 0 0; padding:20px; background:#f3eef4; border-radius:8px;">
    <p style="margin:0 0 4px; color:#1a1a1a; font-size:13px; font-weight:bold; letter-spacing:0.03em; text-transform:uppercase;">Play hard &middot; {play_track["name"]}</p>
    <p style="margin:0; color:#333; font-size:15px; line-height:1.6;">{content["play_task"]}</p>
  </div>

  <div style="margin:24px 0 0; padding:20px; background:#f7f5f0; border-radius:8px;">
    <p style="margin:0; color:#333; font-size:15px; line-height:1.6;">&#128176; {content["money_fact"]}</p>
    <p style="margin:8px 0 0; color:#999; font-size:12px;">Source: {content["money_fact_source"]}</p>
  </div>
</div>
"""
    work_name = work_track["name"] if source == "claude" else "Work hard"
    subject = f"{work_name} + {play_track['name']} — {date.today().strftime('%b %d')}"
    return subject, html


def record_history(history: list, content: dict, work_track: dict, play_track: dict, source: str) -> None:
    history.append(
        {
            "date": date.today().isoformat(),
            "sent_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": source,
            "work_track": work_track["id"],
            "play_track": play_track["id"],
            "quote": content["quote"],
            "work_task": content["work_task"],
            "play_task": content["play_task"],
        }
    )
    HISTORY_FILE.write_text(json.dumps(history[-HISTORY_KEEP:], indent=2) + "\n")


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
    dry_run = os.environ.get("DRY_RUN") == "1"

    if not dry_run:
        missing = [v for v in ("RESEND_API_KEY", "TO_EMAIL", "FROM_EMAIL") if not os.environ.get(v)]
        if missing:
            print(f"Missing required env var(s): {', '.join(missing)}", file=sys.stderr)
            return 1

    profile = load_profile()
    history = load_history()
    today = date.today()

    work_track = pick_track(
        profile["work_tracks"], history, "work_track", today, max_streak=WORK_MAX_STREAK
    )
    play_track = pick_track(
        profile["play_tracks"], history, "play_track", today, avoid_last=AVOID_LAST_PLAY
    )
    print(f"Today: work={work_track['id']}, play={play_track['id']}")

    try:
        content = generate_content(profile, work_track, play_track, history)
        source = "claude"
        print("Generated quote/tasks via Claude API; fact from local list.")
    except Exception as e:
        content = get_fallback_content(profile, play_track, history)
        source = "fallback"
        print(f"Claude generation failed ({e}); falling back to quotes.json.")

    content.update(get_daily_fact())
    subject, html = render_email(content, work_track, play_track, source)

    if dry_run:
        print(f"\n--- DRY RUN ---\nSubject: {subject}\n")
        print(f'"{content["quote"]}"\n')
        work_name = work_track["name"] if source == "claude" else "generic fallback"
        print(f"WORK HARD ({work_name}): {content['work_task']}\n")
        print(f"PLAY HARD ({play_track['name']}): {content['play_task']}\n")
        print(f"MONEY FACT: {content['money_fact']}")
        (HERE / "preview.html").write_text(html)
        print("\nFull email written to preview.html (history not recorded).")
        return 0

    try:
        send_email(subject, html)
    except Exception as e:
        print(f"Failed to send email: {e}", file=sys.stderr)
        return 1

    record_history(history, content, work_track, play_track, source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
