# Daily Work Hard / Play Hard — Peregrine.dev

A daily email sent every morning via GitHub Actions + Resend. The motto is
work hard / play hard, so every email pushes the businesses *and* the life.

Each email has four parts:

1. **A quote** — original, written fresh by Claude.
2. **Work hard** — one concrete task for whichever business is up today:
   Peregrine.dev or Prizm.
3. **Play hard** — one concrete thing to do today for whichever hobby is up:
   rock climbing, chess, the dogs, an adventure with Dani, or NFL.
4. **A money fact** — a real, positive statistic connecting money to
   startups/founders/freelance developers, pulled from `facts.json`, a
   hand-verified local list (not LLM-generated — see note below).

## What it talks about, and how to change it

Everything about *you* lives in **`profile.json`** — edit that file, not the
script. Each business and hobby is a "track" with a short context paragraph
Claude reads before writing the task:

- `weight` — how often a track comes up, relative to the others. Peregrine.dev
  is weighted 2 against Prizm's 1, so it lands roughly twice as often.
- `boost_days` — multiplies the weight on certain weekdays. NFL is boosted on
  Sunday, Monday and Thursday; adventures with Dani on Friday and Saturday.
- `season` — limits a track to part of the year. NFL only comes up between
  Sept 1 and Feb 15.
- `fallback_play_tasks` — hand-written hobby tasks, per track, used only if
  the Claude call fails.

To add a hobby or a third business, copy an existing track, give it a new
`id`, and write its context paragraph. No code changes needed.

## How it stays fresh

Repetition was the original problem, and three things fix it:

- **Memory.** Every send is appended to `history.json`, and the last 21 days
  of quotes and tasks are handed back to Claude as an explicit do-not-repeat
  list. The workflow commits `history.json` back to the repo after each run,
  which is what makes that memory survive between runs — if you ever want a
  clean slate, delete the file.
- **Rotation.** Hobbies that came up in the last 2 days are skipped
  outright. The same business can repeat (the weights decide the mix) but
  never more than 3 days running, so neither business goes quiet for long.
- **Day awareness.** Claude is told the weekday and sizes tasks to it — a
  Tuesday evening gets something short, a Saturday gets room for a real
  adventure.

## How it works

1. GitHub Actions runs `send_quote.py` on a daily cron schedule.
2. The script picks today's work and play tracks from `profile.json`, then
   makes one small Claude call (structured JSON output) to write the quote +
   both tasks, and picks today's money fact from `facts.json` —
   rotating by day-of-year so it cycles through every entry before
   repeating. If the Claude call fails for any reason, it falls back to a
   fully bundled entry from `quotes.json` plus a hand-written play task from
   `profile.json` instead, so an email still goes out either way.
3. The script sends the email through [Resend](https://resend.com)'s HTTP API.

**Why the fact isn't researched live anymore:** an earlier version had
Claude use web search to look up a fresh statistic every day, which sounds
appealing but the search tool bills $10 per 1,000 searches on top of token
costs — that was the entire cost of each email (~2¢), while the model calls
themselves cost well under a cent. A static, pre-checked list keeps the
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
**API Keys**. Content generation is one small Claude Sonnet 5 call — about
half a cent per email, or roughly $1.50 a year. (It used to run on Haiku 4.5
at a tenth of that; the better model writes noticeably less repetitive tasks.
To switch back, change `CLAUDE_MODEL` and the two pricing constants at the
top of `send_quote.py` — note Haiku doesn't support `output_config.effort`,
so drop that line too.)

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
  `0 13 * * *` (13:00 UTC = 7am Utah time in summer, 6am in winter — edit the
  cron line to change it; cron is always UTC and does not shift with DST).
- The workflow needs write access to commit `history.json` back. That's
  already declared (`permissions: contents: write`), but if the push step
  fails, check **Settings → Actions → General → Workflow permissions** is set
  to "Read and write permissions".
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

DRY_RUN=1 python send_quote.py   # prints the content, writes preview.html, sends nothing
python send_quote.py             # actually sends, and records to history.json
```

`DRY_RUN=1` needs only `ANTHROPIC_API_KEY`, and deliberately does not touch
`history.json`, so you can preview as many times as you like.

## Files

- `send_quote.py` — picks today's tracks, generates content, sends the email
- `profile.json` — who the email is for and what it may talk about (**edit this**)
- `history.json` — what has already been sent; the do-not-repeat memory (written by the script)
- `facts.json` — hand-verified money facts, rotated daily (edit/expand any time)
- `quotes.json` — fully bundled fallback entries used if the Claude API call fails
- `.github/workflows/daily-quote.yml` — the cron schedule and the history commit
