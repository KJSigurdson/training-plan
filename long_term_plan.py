"""Generate a week-by-week periodized plan (current week through race week) and
upsert it into weekly_targets, keyed on week_start so regenerating overwrites
current/future weeks while leaving already-elapsed weeks' rows intact.
"""

import json
import re
from collections import defaultdict
from datetime import date, timedelta

import anthropic

from db import _get_secret, get_supabase
from generate_plan import _phase_from_weeks

VALID_PHASES = {"base", "build", "peak", "taper"}
MAX_WEEKS = 104  # ~2 years; guards against a misconfigured race_date


def _week_start(d: date) -> date:
    """Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


def _recent_weekly_load(supabase, today: date) -> str:
    """Sum training_load by ISO week over the last 8 completed weeks, for
    calibrating what a realistic target_load looks like."""
    eight_weeks_ago = (today - timedelta(weeks=8)).isoformat()
    rows = (
        supabase.table("sessions")
        .select("start_date,training_load")
        .gte("start_date", eight_weeks_ago)
        .not_.is_("training_load", "null")
        .execute()
    ).data or []

    load_by_week: dict[str, float] = defaultdict(float)
    for row in rows:
        try:
            d = date.fromisoformat(str(row["start_date"])[:10])
        except (KeyError, ValueError):
            continue
        load_by_week[_week_start(d).isoformat()] += float(row.get("training_load") or 0)

    if not load_by_week:
        return "  (no recent session history)"
    return "\n".join(f"  {week}: {load:.0f}" for week, load in sorted(load_by_week.items()))


def _build_prompt(
    goal: dict, current_week_start: date, race_week_start: date, weeks_count: int,
    recent_load_text: str,
) -> str:
    return f"""You are an expert endurance coach building a long-term periodized
training plan for a 90km classic cross-country ski race.

## Goal
Race: {goal.get('race_name', '?')}
Race date: {goal.get('race_date', '?')}
Target: {goal.get('target', '?')}

## Planning window
First week (Monday): {current_week_start.isoformat()}
Race week (Monday): {race_week_start.isoformat()}
Total weeks to plan: {weeks_count}

## Recent actual weekly training load (last 8 weeks, for calibration)
Training load is zone-weighted minutes: moving_time_minutes × (sum of
pct_time_in_zone_i × i for i=1..5), or moving_time_minutes × 2 when heart-rate
zone data isn't available. Use these recent numbers to calibrate a realistic
starting target_load — don't invent a scale disconnected from actual training.
{recent_load_text}

## Periodization principles
- Build a smooth, progressive week-by-week plan from {current_week_start.isoformat()}
  to {race_week_start.isoformat()}, split into standard endurance phases:
  base (aerobic volume building), build (increasing volume + some intensity),
  peak (race-specific sharpening, slightly reduced volume), taper (drastically
  reduced volume heading into race week).
- target_load should progressively increase through base and build, plateau or
  dip slightly in peak, and drop sharply in the final 1-3 taper weeks.
- Insert a recovery week (target_load reduced by roughly 30-40% versus the
  surrounding trend) approximately every 4th week throughout base/build/peak —
  don't recovery-week during taper.
- notes should be a single concise sentence describing that week's focus.

## Output format
Return ONLY valid JSON, no markdown, no explanation: an array with exactly
{weeks_count} entries, one per week, in chronological order:
[
  {{
    "week_start": "YYYY-MM-DD",
    "target_load": <number>,
    "phase": "<base|build|peak|taper>",
    "notes": "<one concise sentence>"
  }}
]

Every week_start must be a Monday, starting at {current_week_start.isoformat()}
and incrementing by exactly 7 days, ending at {race_week_start.isoformat()}.
"""


def generate_long_term_plan() -> list[dict]:
    supabase = get_supabase()
    today = date.today()

    goals_result = supabase.table("goal").select("*").limit(1).execute()
    if not goals_result.data:
        raise RuntimeError("No goal found in the goal table.")
    goal = goals_result.data[0]

    race_date_str = str(goal.get("race_date", ""))[:10]
    try:
        race_date = date.fromisoformat(race_date_str)
    except ValueError:
        raise RuntimeError(f"Invalid race_date in goal table: {race_date_str!r}")

    current_week_start = _week_start(today)
    race_week_start = _week_start(race_date)
    weeks_count = (race_week_start - current_week_start).days // 7 + 1

    if weeks_count <= 0:
        raise RuntimeError("Race date has already passed; nothing to plan.")
    if weeks_count > MAX_WEEKS:
        raise RuntimeError(
            f"Race date is {weeks_count} weeks away, which looks wrong. Check the goal table."
        )

    recent_load_text = _recent_weekly_load(supabase, today)
    prompt = _build_prompt(goal, current_week_start, race_week_start, weeks_count, recent_load_text)

    api_key = _get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set in .env or st.secrets")

    anthropic_client = anthropic.Anthropic(api_key=api_key)
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=min(8192, 1024 + weeks_count * 100),
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.content[0].text.strip()

    clean = re.sub(r"^```(?:json)?\s*\n?", "", raw_text, flags=re.MULTILINE)
    clean = re.sub(r"\n?```\s*$", "", clean, flags=re.MULTILINE).strip()
    try:
        weeks = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not parse Claude response as JSON: {exc}\n"
            f"Response (first 500 chars): {raw_text[:500]}"
        ) from exc

    if not isinstance(weeks, list) or not weeks:
        raise RuntimeError("Claude response did not contain a non-empty JSON array.")

    # Normalize week_start to an actual Monday and dedupe (last wins) so a
    # single upsert batch never targets the same primary key twice.
    rows_by_week: dict[str, dict] = {}
    for week in weeks:
        try:
            d = date.fromisoformat(str(week["week_start"])[:10])
        except (KeyError, ValueError, TypeError):
            continue
        monday = _week_start(d)
        phase = str(week.get("phase") or "").lower()
        if phase not in VALID_PHASES:
            weeks_to_race = max(0.0, (race_date - monday).days / 7)
            phase = _phase_from_weeks(weeks_to_race)
        rows_by_week[monday.isoformat()] = {
            "week_start": monday.isoformat(),
            "target_load": round(float(week.get("target_load") or 0), 1),
            "phase": phase,
            "notes": str(week.get("notes") or ""),
        }

    if not rows_by_week:
        raise RuntimeError("Claude response contained no usable week entries.")

    rows = sorted(rows_by_week.values(), key=lambda r: r["week_start"])
    supabase.table("weekly_targets").upsert(rows, on_conflict="week_start").execute()

    return rows
