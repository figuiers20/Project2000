"""Cumulative hours analysis and pace calculations.

Goal: 2000 hours of sport from 2025-01-01 through 2034-12-31.
Pace target is a straight line from (2025-01-01, 0) to (2034-12-31, 2000).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

# --- Goal constants -----------------------------------------------------------
GOAL_HOURS = 2000
DECADE_START = date(2025, 1, 1)
DECADE_END = date(2034, 12, 31)
TOTAL_DAYS = (DECADE_END - DECADE_START).days + 1  # inclusive
DAILY_TARGET_HOURS = GOAL_HOURS / TOTAL_DAYS  # ~0.5475 hours/day


@dataclass
class Activity:
    """Minimal Strava activity representation."""
    start_date: date
    hours: float
    sport_type: str
    name: str


# --- Helpers ------------------------------------------------------------------
def target_hours_on(day: date) -> float:
    """Hours you 'should' have accumulated by end-of-day `day` under linear pace."""
    if day < DECADE_START:
        return 0.0
    if day > DECADE_END:
        return float(GOAL_HOURS)
    days_elapsed = (day - DECADE_START).days + 1  # +1 so end of Jan 1 = 1 day's target
    return days_elapsed * DAILY_TARGET_HOURS


def daterange(start: date, end: date) -> Iterable[date]:
    """Inclusive day-by-day date range."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def build_cumulative_series(
    activities: list[Activity],
    start: date,
    end: date,
) -> tuple[list[date], list[float], list[float]]:
    """Return (dates, cumulative_actual, trendline_target) between start and end inclusive.

    `activities` may include entries outside [start, end]; those outside are ignored
    for the plotted series but this function does NOT carry prior cumulative forward
    unless the caller passes activities beginning at `start`.
    """
    # Daily sum of hours within window
    daily_hours: dict[date, float] = {}
    for a in activities:
        if start <= a.start_date <= end:
            daily_hours[a.start_date] = daily_hours.get(a.start_date, 0.0) + a.hours

    dates: list[date] = []
    cumulative: list[float] = []
    trend: list[float] = []
    running = 0.0
    for day in daterange(start, end):
        running += daily_hours.get(day, 0.0)
        dates.append(day)
        cumulative.append(round(running, 3))
        trend.append(round(target_hours_on(day), 3))
    return dates, cumulative, trend


def total_hours_through(activities: list[Activity], through: date) -> float:
    """Sum of hours for all activities with start_date <= `through`."""
    return round(
        sum(a.hours for a in activities if DECADE_START <= a.start_date <= through),
        3,
    )


def build_summary(activities: list[Activity], today: date | None = None) -> dict:
    """Build a summary dict with headline metrics the dashboard will render."""
    today = today or date.today()
    if today > DECADE_END:
        today = DECADE_END
    if today < DECADE_START:
        today = DECADE_START

    actual_total = total_hours_through(activities, today)
    target_total = target_hours_on(today)
    delta_decade = actual_total - target_total

    # Year-to-date
    ytd_start = date(today.year, 1, 1)
    if ytd_start < DECADE_START:
        ytd_start = DECADE_START
    ytd_actual = round(
        sum(a.hours for a in activities if ytd_start <= a.start_date <= today),
        3,
    )
    # For YTD target, use the same linear daily pace
    days_ytd = (today - ytd_start).days + 1
    ytd_target = round(days_ytd * DAILY_TARGET_HOURS, 3)
    delta_ytd = round(ytd_actual - ytd_target, 3)

    # Sport breakdown
    sport_breakdown: dict[str, float] = {}
    for a in activities:
        if DECADE_START <= a.start_date <= today:
            sport_breakdown[a.sport_type] = (
                sport_breakdown.get(a.sport_type, 0.0) + a.hours
            )
    sport_breakdown = {
        k: round(v, 2)
        for k, v in sorted(sport_breakdown.items(), key=lambda kv: -kv[1])
    }

    # Projections
    days_in = (today - DECADE_START).days + 1
    pace_per_day = actual_total / days_in if days_in > 0 else 0.0
    projected_decade_total = round(pace_per_day * TOTAL_DAYS, 1)

    return {
        "today": today.isoformat(),
        "decade_start": DECADE_START.isoformat(),
        "decade_end": DECADE_END.isoformat(),
        "goal_hours": GOAL_HOURS,
        "daily_target_hours": round(DAILY_TARGET_HOURS, 4),
        "actual_total_hours": round(actual_total, 2),
        "target_total_hours": round(target_total, 2),
        "delta_decade_hours": round(delta_decade, 2),
        "ytd_actual_hours": round(ytd_actual, 2),
        "ytd_target_hours": round(ytd_target, 2),
        "delta_ytd_hours": round(delta_ytd, 2),
        "pct_complete": round(100 * actual_total / GOAL_HOURS, 2),
        "projected_decade_total_hours": projected_decade_total,
        "sport_breakdown": sport_breakdown,
        "activity_count": sum(
            1 for a in activities if DECADE_START <= a.start_date <= today
        ),
    }
