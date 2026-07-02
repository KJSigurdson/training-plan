import json
import re
from collections import defaultdict
from datetime import date, timedelta

import anthropic
from dotenv import load_dotenv

from db import _get_secret, get_supabase

load_dotenv()


def _phase_from_weeks(weeks: float) -> str:
    if weeks > 16:
        return "base"
    if weeks > 8:
        return "build"
    if weeks > 3:
        return "peak"
    return "taper"


def _phase_guidance(phase: str) -> str:
    return {
        "base": "emphasize aerobic base building, mostly Z1–Z2, moderate volume",
        "build": "increase volume and introduce some Z3–Z4 work to build race-specific fitness",
        "peak": "sharpen with quality sessions (Z4–Z5), reduce volume slightly",
        "taper": "drastically reduce volume, keep some intensity to stay sharp, maximize recovery",
    }[phase]


def _build_long_term_anchor_text(
    current_week_target: dict | None,
    next_week_target: dict | None,
    completed_this_week: float,
) -> str:
    """Describe this week's long-term target (if any) so the 7-day plan can
    aim its combined load at it. Returns "" when weekly_targets has no rows
    covering the current week, in which case the daily prompt simply omits
    this section (no long-term anchor, same as today's behavior)."""
    if not current_week_target:
        return ""
    remaining = max(0.0, float(current_week_target.get("target_load") or 0) - completed_this_week)
    lines = [
        "## Long-term plan anchor",
        f"This week's target load (from the long-term plan): "
        f"{current_week_target.get('target_load')} ({current_week_target.get('phase', '?')} phase)",
        f"Already completed this week (including the trigger session): {completed_this_week:.0f}",
        f"Remaining budget to hit this week's target: {remaining:.0f}",
    ]
    if note := current_week_target.get("notes"):
        lines.append(f"This week's note: {note}")
    if next_week_target:
        lines.append(
            f"Next week's target load: {next_week_target.get('target_load')} "
            f"({next_week_target.get('phase', '?')} phase)"
        )
    lines.append(
        "Aim the 7 days' combined training_load at the remaining budget above, "
        "adjusted down if the athlete's reported feeling/tiredness calls for extra recovery."
    )
    return "\n".join(lines)


def _build_prompt(
    session: dict,
    qa: dict,
    goal: dict,
    weeks_to_race: float,
    phase: str,
    history: list[dict],
    load_by_muscle: dict,
    stress_map: list[dict],
    avail_with_dates: list[dict],
    today: date,
    long_term_anchor_text: str = "",
) -> str:
    history_lines = [
        f"  - {str(s.get('start_date', '?'))[:10]} | {s.get('sport_type', '?')} | "
        f"{(s.get('distance_m') or 0) / 1000:.1f} km | "
        f"{(s.get('moving_time_s') or 0) // 60} min | "
        f"load={float(s.get('training_load') or 0):.0f} | "
        f"muscle_group={s.get('muscle_group', '?')}"
        for s in history
    ]
    history_text = "\n".join(history_lines) or "  (no recent sessions)"

    load_text = "\n".join(
        f"  {mg}: {load:.0f}" for mg, load in sorted(load_by_muscle.items())
    ) or "  (no data)"

    stress_text = "\n".join(
        f"  {row.get('sport_type')}: {row.get('muscle_groups_stressed')}"
        for row in stress_map
    ) or "  (no data)"

    avail_text = "\n".join(
        f"  {a['date']} ({'available' if a['available'] else 'NOT available'})"
        for a in avail_with_dates
    )

    tomorrow = today + timedelta(days=1)
    day7 = today + timedelta(days=7)

    anchor_section = f"\n{long_term_anchor_text}\n" if long_term_anchor_text else ""
    anchor_rule = (
        "\n- Aim the sum of this plan's training_load (duration_min scaled by "
        "intensity_zone) at the remaining budget stated in the Long-term plan anchor section above"
        if long_term_anchor_text else ""
    )

    return f"""You are an expert endurance coach creating a personalized 7-day training plan.

## Goal
Race: {goal.get('race_name', '?')}
Race date: {goal.get('race_date', '?')}
Target: {goal.get('target', '?')}
Weeks to race: {weeks_to_race:.1f}
Periodization phase: {phase.upper()}
Phase guidance: {_phase_guidance(phase)}

## Trigger session (just completed)
Sport: {session.get('sport_type', '?')}
Date: {str(session.get('start_date', '?'))[:10]}
Distance: {(session.get('distance_m') or 0) / 1000:.1f} km
Duration: {(session.get('moving_time_s') or 0) // 60} min
Elevation: {session.get('elevation_gain_m', 0)} m
Training load: {session.get('training_load', 0)}

## Athlete reflection
How it went: {qa.get('how_it_went', '')}
Feeling (1=terrible → 4=excellent): {qa.get('feeling')}
Tiredness (1=exhausted → 4=fresh): {qa.get('tiredness')}

## Last 8 weeks of training
{history_text}

## Cumulative load by muscle group (last 8 weeks)
{load_text}

## Sport stress map
{stress_text}

## Athlete availability next 7 days (starting tomorrow {tomorrow.isoformat()})
{avail_text}
{anchor_section}
## Instructions
Create a 7-day training plan starting tomorrow ({tomorrow.isoformat()}) through {day7.isoformat()}.

Rules:
- If the athlete is NOT available on a day: assign sport_type="rest", duration_min=0, intensity_zone="rest"
- Respect the {phase.upper()} phase guidance
- Balance muscle group load against the 8-week history (avoid overloading recently stressed groups)
- If feeling ≤ 2 or tiredness ≤ 2, prioritize recovery (Z1–Z2, shorter sessions)
- No pace or interval prescriptions — only sport type, duration, and zone
- intensity_zone must be exactly one of: Z1, Z2, Z3, Z4, Z5, rest{anchor_rule}

Sport priority (Vasaloppet-specific athlete):
- The dominant modalities are Run, TrailRun, and RollerSki. The vast majority of training days must use one of these three.
- Seasonality: RollerSki is the snow-free substitute for CrossCountrySki (april–november). CrossCountrySki replaces RollerSki in winter (december–march). Choose the appropriate one based on the plan dates.
- Cross-training sports (Ride, Swim, Workout, etc.) are only acceptable when: (a) a specific muscle group is overloaded and a different modality is needed for balance, or (b) the session is a deliberate active-recovery day where lower impact is warranted. Do not use cross-training as default filler.
- If in doubt between two options, default to Run, TrailRun, or RollerSki.

Return ONLY valid JSON, no markdown, no explanation:
{{
  "summary": "<2-3 sentences of plain-text coaching rationale for this week>",
  "days": [
    {{
      "day": 1,
      "date": "YYYY-MM-DD",
      "sport_type": "<sport or rest>",
      "duration_min": <integer>,
      "intensity_zone": "<Z1-Z5 or rest>",
      "rationale": "<one concise sentence>"
    }}
  ]
}}

The days array must have exactly 7 entries. Day 1 = {tomorrow.isoformat()}, day 7 = {day7.isoformat()}.
"""


def generate_plan(session_id: str) -> dict:
    supabase = get_supabase()
    today = date.today()

    session = (
        supabase.table("sessions").select("*").eq("id", session_id).single().execute()
    ).data

    qa = (
        supabase.table("qa_responses")
        .select("*")
        .eq("session_id", session_id)
        .single()
        .execute()
    ).data

    goals_result = supabase.table("goal").select("*").limit(1).execute()
    if not goals_result.data:
        raise RuntimeError("No goal found in the goal table.")
    goal = goals_result.data[0]

    race_date_str = str(goal.get("race_date", ""))[:10]
    try:
        race_date = date.fromisoformat(race_date_str)
    except ValueError:
        raise RuntimeError(f"Invalid race_date in goal table: {race_date_str!r}")

    weeks_to_race = max(0.0, (race_date - today).days / 7)
    phase = _phase_from_weeks(weeks_to_race)

    eight_weeks_ago = (today - timedelta(weeks=8)).isoformat()
    history = (
        supabase.table("sessions")
        .select(
            "sport_type,start_date,moving_time_s,distance_m,"
            "elevation_gain_m,training_load,muscle_group"
        )
        .gte("start_date", eight_weeks_ago)
        .execute()
    ).data or []

    load_by_muscle: dict[str, float] = defaultdict(float)
    for s in history:
        mg = (s.get("muscle_group") or "other").lower()
        load_by_muscle[mg] += float(s.get("training_load") or 0)

    stress_map = supabase.table("sport_stress_map").select("*").execute().data or []

    current_week_start = today - timedelta(days=today.weekday())
    next_week_start = current_week_start + timedelta(days=7)
    weekly_targets = (
        supabase.table("weekly_targets")
        .select("week_start,target_load,phase,notes")
        .in_("week_start", [current_week_start.isoformat(), next_week_start.isoformat()])
        .execute()
    ).data or []
    targets_by_week = {row["week_start"]: row for row in weekly_targets}
    current_week_target = targets_by_week.get(current_week_start.isoformat())
    next_week_target = targets_by_week.get(next_week_start.isoformat())

    completed_this_week = sum(
        float(s.get("training_load") or 0)
        for s in history
        if (str(s.get("start_date", ""))[:10] or "0") >= current_week_start.isoformat()
    )
    long_term_anchor_text = _build_long_term_anchor_text(
        current_week_target, next_week_target, completed_this_week
    )

    tomorrow = today + timedelta(days=1)
    availability_raw = qa.get("availability") or [False] * 7
    avail_with_dates = [
        {
            "date": (tomorrow + timedelta(days=i)).isoformat(),
            "available": bool(availability_raw[i]),
        }
        for i in range(min(7, len(availability_raw)))
    ]
    while len(avail_with_dates) < 7:
        i = len(avail_with_dates)
        avail_with_dates.append(
            {"date": (tomorrow + timedelta(days=i)).isoformat(), "available": False}
        )

    prompt = _build_prompt(
        session, qa, goal, weeks_to_race, phase,
        history, dict(load_by_muscle), stress_map, avail_with_dates, today,
        long_term_anchor_text,
    )

    api_key = _get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set in .env or st.secrets")

    anthropic_client = anthropic.Anthropic(api_key=api_key)
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.content[0].text.strip()

    clean = re.sub(r"^```(?:json)?\s*\n?", "", raw_text, flags=re.MULTILINE)
    clean = re.sub(r"\n?```\s*$", "", clean, flags=re.MULTILINE).strip()
    try:
        plan_dict = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not parse Claude response as JSON: {exc}\n"
            f"Response (first 500 chars): {raw_text[:500]}"
        ) from exc

    supabase.table("plans").insert(
        {
            "trigger_session_id": session_id,
            "goal_snapshot": {
                "race_date": str(goal.get("race_date", "")),
                "phase": phase,
                "weeks_to_race": round(weeks_to_race, 1),
            },
            "plan": plan_dict.get("days", []),
            "summary": plan_dict.get("summary", ""),
        }
    ).execute()

    supabase.table("sessions").update({"status": "planned"}).eq(
        "id", session_id
    ).execute()

    return plan_dict
