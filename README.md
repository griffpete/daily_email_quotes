# Daily Founder Fuel — Peregrine.dev

A daily motivation email for a solo freelance dev founder, sent every morning
via GitHub Actions + Resend.

Each email has three parts:

1. **A quote** — original, written fresh by Claude, about startups/founders/
   the solo grind.
2. **A money fact** — a real, positive statistic connecting money to
   startups/founders/freelance developers, pulled from `facts.json`, a
   hand-verified local list (not LLM-generated — see note below).
3. **Today's task** — one concrete thing to work on, geared toward growing a
   solo dev business (prospecting, outreach, portfolio, pricing, etc.).

## How it works

1. GitHub Actions runs `send_quote.py` on a daily cron schedule.
2. The script makes one small Claude call (structured JSON output) to write
   the quote + task, and picks today's money fact from `facts.json` —
   rotating by day-of-year so it cycles through every entry before
   repeating. If the Claude call fails for any reason, it falls back to a
   fully bundled entry from `quotes.json` instead, so an email still goes
   out either way.
3. The script sends the email through [Resend](https://resend.com)'s HTTP API.

**Why the fact isn't researched live anymore:** an earlier version had
Claude use web search to look up a fresh statistic every day, which sounds
appealing but the search tool bills $10 per 1,000 searches on top of token
costs — that was the entire cost of each email (~2¢), while the Haiku calls
themselves cost a fraction of a cent. A static, pre-checked list keeps the
facts just as real (they're all hand-verified, cited, and in `facts.json`
for you to review or edit) for a small fraction of the price — the tradeoff
is that facts repeat every 20 days instead of being freshly sourced daily.
Add more entries to `facts.json` any time to widen the rotation.

## One-time setup

### 1. Resend (email delivery)

1. Create a free account at [resend.com](https://resend.com) (3,000 emails/mo free).
2. Grab an API key: **Dashboard → API Keys → Create API Key**.
3. Sender address — two options:
   - **Fastest to start:** use Resend's shared test domain, `onboarding@resend.dev`,
     as `FROM_EMAIL`. It only delivers to the email address on your Resend
     account, which is fine since you're emailing yourself.
   - **For a real "from" address** (e.g. `quote@peregrine.dev`): **Dashboard →
     Domains → Add Domain**, then add the DNS records Resend gives you
     (SPF/DKIM) wherever `peregrine.dev`'s DNS is managed. Verification
     usually takes a few minutes.

### 2. Anthropic (content)

Grab an API key from [console.anthropic.com](https://console.anthropic.com) →
**API Keys**. Content generation is one small Haiku call — well under a
tenth of a cent per email.

### 3. GitHub repo secrets

Push this project to a GitHub repo, then add these under
**Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | from console.anthropic.com |
| `RESEND_API_KEY` | from resend.com |
| `TO_EMAIL` | the address(es) to send to (comma-separated for more than one) |
| `FROM_EMAIL` | e.g. `Daily Quote <onboarding@resend.dev>` or your verified domain address |

### 4. Turn it on

- The workflow (`.github/workflows/daily-quote.yml`) already has a schedule:
  `0 13 * * *` (13:00 UTC / 9am ET — edit the cron line to change the time).
- Once secrets are set, go to the **Actions** tab → **Daily motivational
  quote** → **Run workflow** to send a test email immediately, without
  waiting for the schedule.
- GitHub Actions cron can run a few minutes late; that's normal.

## Local testing

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in your keys
export $(grep -v '^#' .env | xargs)
python send_quote.py
```

## Files

- `send_quote.py` — generates content and sends the email
- `facts.json` — hand-verified money facts, rotated daily (edit/expand any time)
- `quotes.json` — fully bundled fallback entries used if the Claude API call fails
- `.github/workflows/daily-quote.yml` — the cron schedule
