# 2000 Hours

A personal dashboard that tracks progress toward **2000 hours of sport across a decade** (Jan 1, 2025 – Dec 31, 2034). Pulls activity data from Strava and shows cumulative hours against a linear pace target.

## What it shows

- **Decade-to-date** cumulative hours vs. a straight-line pace target (2000 hrs ÷ 3652 days ≈ 0.548 hrs/day)
- **Year-to-date** cumulative hours vs. the same daily pace
- Headline metrics: +/- hours vs. pace (today, year), % of 2000 complete, projected decade total at current pace
- Sport breakdown table (Run, Ride, Swim, Tennis, etc.)

## Local development

1. Create a Strava API app at https://www.strava.com/settings/api
   - Set **Authorization Callback Domain** to `localhost` for local dev
2. Install deps:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your Strava client ID/secret + a Flask secret key.
4. Run:
   ```bash
   export $(grep -v '^#' .env | xargs)
   python app.py
   ```
5. Open http://localhost:5000 and click **Connect with Strava**.

## Deploy to Railway

1. Push this repo to GitHub.
2. In Railway, **New Project → Deploy from GitHub repo** and pick this repo.
3. In the Railway project's **Variables** tab, add:
   - `STRAVA_CLIENT_ID`
   - `STRAVA_CLIENT_SECRET`
   - `FLASK_SECRET_KEY` (generate with `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `FLASK_ENV=production`
4. In Railway **Settings → Networking**, generate a public domain (or attach a custom one).
5. Copy that domain (e.g. `my-app.up.railway.app`) and:
   - In your Strava API settings, set **Authorization Callback Domain** to that hostname (no `https://` prefix).
   - Railway auto-exposes `RAILWAY_PUBLIC_DOMAIN` to the app, so the redirect URI resolves automatically. If you use a custom domain, set `STRAVA_REDIRECT_URI=https://your.domain/auth/callback` explicitly.
6. Redeploy. Visit the URL, click **Connect with Strava**, authorize, done.

## Architecture

```
app.py         → Flask routes + in-memory activity cache (15 min TTL)
strava.py      → OAuth + paginated /athlete/activities fetch
analysis.py    → Pace math, cumulative series, summary metrics
templates/     → Jinja2 templates (login, dashboard, error)
static/        → CSS
```

Activity hours use Strava's `moving_time` field (so paused/idle time doesn't count).

## Tweaks you might want later

- Persist tokens in a SQLite/Postgres table (currently kept in Flask session — works for single-user but you re-auth after cookie expires).
- Write daily snapshots to a DB so you have a record independent of Strava.
- Add a deload/taper overlay, weekly histogram, or year-over-year comparison.
- Exclude specific activity types (e.g. if you don't want walks counted).

## Goal math

- Goal: 2000 hours
- Window: 2025-01-01 → 2034-12-31 (3652 days inclusive — 8 regular years + 2 leap years)
- Daily pace: 2000 / 3652 ≈ **0.5476 hrs/day** (~32 min 51 sec/day)
