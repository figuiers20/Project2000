"""Flask app — 2000 Hours dashboard.

Routes:
  GET  /                -> landing / login page (Connect with Strava)
  GET  /auth/strava     -> redirects to Strava OAuth
  GET  /auth/callback   -> OAuth callback, stores token, redirects to /dashboard
  GET  /dashboard       -> main dashboard (requires session token)
  POST /refresh         -> clears cached activities, re-fetches from Strava
  GET  /logout          -> clears session
  GET  /healthz         -> liveness probe
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import date, datetime
from pathlib import Path

from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
    jsonify,
    abort,
)

import analysis
import strava

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
# Session cookie hygiene for production
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if os.environ.get("FLASK_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True

# --- Simple in-memory activity cache -----------------------------------------
# Keyed by athlete id. For a single-user app on Railway this is fine.
_ACTIVITY_CACHE: dict[int, dict] = {}
CACHE_TTL_SECONDS = 15 * 60  # 15 minutes


def _redirect_uri() -> str:
    # Railway sets RAILWAY_PUBLIC_DOMAIN; fall back to localhost for dev.
    explicit = os.environ.get("STRAVA_REDIRECT_URI")
    if explicit:
        return explicit
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        return f"https://{domain}/auth/callback"
    return "http://localhost:5000/auth/callback"


def _get_token_bundle() -> dict | None:
    bundle = session.get("strava_token")
    if not bundle:
        return None
    # Refresh if near expiry
    fresh = strava.ensure_fresh_token(bundle)
    if fresh is not bundle:
        session["strava_token"] = fresh
    return fresh


def _get_activities(force_refresh: bool = False) -> list[analysis.Activity]:
    bundle = _get_token_bundle()
    if not bundle:
        return []
    athlete_id = session.get("athlete_id") or 0
    cached = _ACTIVITY_CACHE.get(athlete_id)
    if (
        not force_refresh
        and cached
        and (time.time() - cached["fetched_at"]) < CACHE_TTL_SECONDS
    ):
        return cached["activities"]

    activities = strava.fetch_activities(bundle["access_token"])
    _ACTIVITY_CACHE[athlete_id] = {
        "fetched_at": time.time(),
        "activities": activities,
    }
    return activities


# --- Routes -------------------------------------------------------------------
@app.route("/")
def index():
    if session.get("strava_token"):
        return redirect(url_for("dashboard"))
    return render_template("login.html", goal=analysis.GOAL_HOURS)


@app.route("/auth/strava")
def auth_start():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    url = strava.build_authorize_url(_redirect_uri(), state=state)
    return redirect(url)


@app.route("/auth/callback")
def auth_callback():
    if "error" in request.args:
        return f"Strava authorization failed: {request.args.get('error')}", 400
    code = request.args.get("code")
    state = request.args.get("state", "")
    expected_state = session.pop("oauth_state", "")
    if not code:
        return "Missing authorization code", 400
    if expected_state and state != expected_state:
        return "State mismatch — possible CSRF, try again.", 400

    try:
        bundle = strava.exchange_code_for_token(code)
    except Exception as exc:  # noqa: BLE001
        return f"Token exchange failed: {exc}", 500

    session["strava_token"] = bundle
    # athlete info is included in the token response
    athlete = bundle.get("athlete") or {}
    session["athlete_id"] = athlete.get("id")
    session["athlete_name"] = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    session["athlete_profile"] = athlete.get("profile_medium") or athlete.get("profile")
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    bundle = _get_token_bundle()
    if not bundle:
        return redirect(url_for("index"))

    try:
        activities = _get_activities()
    except Exception as exc:  # noqa: BLE001
        return render_template(
            "error.html",
            message=f"Could not fetch Strava activities: {exc}",
        ), 502

    today = date.today()
    summary = analysis.build_summary(activities, today=today)

    # Decade view series
    dec_dates, dec_actual, dec_trend = analysis.build_cumulative_series(
        activities, analysis.DECADE_START, analysis.DECADE_END
    )
    # Trim decade actual to "today" for display (so line doesn't flatline past now)
    dec_actual_display = [
        v if d <= today else None for v, d in zip(dec_actual, dec_dates)
    ]

    # YTD view series
    ytd_start = max(date(today.year, 1, 1), analysis.DECADE_START)
    ytd_end = date(today.year, 12, 31)
    ytd_dates, ytd_actual, ytd_trend = analysis.build_cumulative_series(
        activities, ytd_start, ytd_end
    )
    # For YTD actual, we want cumulative starting from 0 on Jan 1 of this year,
    # which is exactly what build_cumulative_series does (window-scoped).
    ytd_actual_display = [
        v if d <= today else None for v, d in zip(ytd_actual, ytd_dates)
    ]
    # YTD target line starts at 0 on Jan 1 of this year and uses the same daily pace
    ytd_trend_from_zero = [
        round(((d - ytd_start).days + 1) * analysis.DAILY_TARGET_HOURS, 3)
        for d in ytd_dates
    ]

    chart_data = {
        "decade": {
            "dates": [d.isoformat() for d in dec_dates],
            "actual": dec_actual_display,
            "trend": dec_trend,
            "today": today.isoformat(),
        },
        "ytd": {
            "dates": [d.isoformat() for d in ytd_dates],
            "actual": ytd_actual_display,
            "trend": ytd_trend_from_zero,
            "today": today.isoformat(),
            "year": today.year,
        },
    }

    return render_template(
        "dashboard.html",
        summary=summary,
        chart_data_json=json.dumps(chart_data),
        athlete_name=session.get("athlete_name") or "Athlete",
        athlete_profile=session.get("athlete_profile"),
        last_fetched=datetime.utcfromtimestamp(
            _ACTIVITY_CACHE.get(session.get("athlete_id") or 0, {}).get(
                "fetched_at", time.time()
            )
        ).strftime("%Y-%m-%d %H:%M UTC"),
    )


@app.route("/refresh", methods=["POST", "GET"])
def refresh():
    """Force a re-fetch from Strava."""
    if not session.get("strava_token"):
        return redirect(url_for("index"))
    try:
        _get_activities(force_refresh=True)
    except Exception as exc:  # noqa: BLE001
        return render_template("error.html", message=f"Refresh failed: {exc}"), 502
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    athlete_id = session.get("athlete_id")
    if athlete_id in _ACTIVITY_CACHE:
        _ACTIVITY_CACHE.pop(athlete_id, None)
    session.clear()
    return redirect(url_for("index"))


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat()})


@app.route("/api/summary")
def api_summary():
    """JSON endpoint — handy for scripting / other dashboards."""
    bundle = _get_token_bundle()
    if not bundle:
        abort(401)
    activities = _get_activities()
    return jsonify(analysis.build_summary(activities))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("FLASK_DEBUG")))
