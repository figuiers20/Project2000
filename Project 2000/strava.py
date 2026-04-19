"""Strava OAuth and activity fetching.

Docs: https://developers.strava.com/docs/reference/
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from typing import Any

import requests

from analysis import Activity, DECADE_START

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

# Scopes: read activities from both public and private
SCOPES = "read,activity:read_all"


class StravaConfigError(RuntimeError):
    """Raised when required Strava env vars are missing."""


def _cfg(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise StravaConfigError(
            f"Missing required env var: {key}. See .env.example for setup."
        )
    return val


def client_id() -> str:
    return _cfg("STRAVA_CLIENT_ID")


def client_secret() -> str:
    return _cfg("STRAVA_CLIENT_SECRET")


def build_authorize_url(redirect_uri: str, state: str = "") -> str:
    """URL to start the OAuth flow — user clicks 'Connect with Strava'."""
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPES,
    }
    if state:
        params["state"] = state
    query = "&".join(f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items())
    return f"{STRAVA_AUTH_URL}?{query}"


def exchange_code_for_token(code: str) -> dict[str, Any]:
    """Exchange an OAuth code for access/refresh tokens."""
    r = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id(),
            "client_secret": client_secret(),
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Refresh an expired access token."""
    r = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id(),
            "client_secret": client_secret(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def ensure_fresh_token(token_bundle: dict[str, Any]) -> dict[str, Any]:
    """If the access token is expired (or close), refresh it.

    `token_bundle` is the dict returned from exchange_code_for_token /
    refresh_access_token and stored in the session:
    {access_token, refresh_token, expires_at, ...}
    """
    expires_at = token_bundle.get("expires_at", 0)
    # Refresh if expiring in less than 2 minutes
    if expires_at - time.time() < 120:
        new_bundle = refresh_access_token(token_bundle["refresh_token"])
        # Strava returns full bundle on refresh as well
        return new_bundle
    return token_bundle


def fetch_activities(
    access_token: str,
    after: date = DECADE_START,
    per_page: int = 200,
) -> list[Activity]:
    """Fetch all activities from Strava since `after` (inclusive).

    Returns a list of Activity objects. Uses `moving_time` (seconds) to avoid
    counting paused/idle time.
    """
    after_ts = int(
        datetime(after.year, after.month, after.day, tzinfo=timezone.utc).timestamp()
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    results: list[Activity] = []
    page = 1

    while True:
        resp = requests.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers=headers,
            params={"after": after_ts, "per_page": per_page, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        for item in batch:
            try:
                start_iso = item.get("start_date_local") or item["start_date"]
                # Parse ISO timestamp to local date
                start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                start_day = start_dt.date()
                moving_seconds = int(item.get("moving_time") or 0)
                hours = moving_seconds / 3600.0
                sport = item.get("sport_type") or item.get("type") or "Other"
                name = item.get("name") or ""
                results.append(
                    Activity(
                        start_date=start_day,
                        hours=hours,
                        sport_type=sport,
                        name=name,
                    )
                )
            except (KeyError, ValueError):
                # Skip malformed entries silently
                continue

        if len(batch) < per_page:
            break
        page += 1

    return results


def fetch_athlete(access_token: str) -> dict[str, Any]:
    """Fetch basic athlete info (name, profile pic)."""
    resp = requests.get(
        f"{STRAVA_API_BASE}/athlete",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()
