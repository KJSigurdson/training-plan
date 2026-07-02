"""Shared helpers used by both pages: Supabase client access, Swedish date/duration
formatting, and plan rendering."""

from datetime import date

import streamlit as st

from db import get_supabase

SV_DAYS_SHORT = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"]
SV_DAYS_LONG = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"]
SV_MONTHS_SHORT = ["jan", "feb", "mar", "apr", "maj", "jun",
                    "jul", "aug", "sep", "okt", "nov", "dec"]
SV_MONTHS_LONG = [
    "januari", "februari", "mars", "april", "maj", "juni",
    "juli", "augusti", "september", "oktober", "november", "december",
]


def require_supabase():
    """Get the shared Supabase client, or stop the page with an error."""
    try:
        return get_supabase()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()


def parse_date(value) -> date | None:
    """Parse an ISO date/datetime string (or date) into a date, or None."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m:02d}min"


def fmt_date_short(d: date) -> str:
    """e.g. 'Ons 1 jul'."""
    return f"{SV_DAYS_SHORT[d.weekday()]} {d.day} {SV_MONTHS_SHORT[d.month - 1]}"


def fmt_date_weekday(d: date) -> str:
    """e.g. 'Onsdag 1 juli'."""
    return f"{SV_DAYS_LONG[d.weekday()]} {d.day} {SV_MONTHS_LONG[d.month - 1]}"


def fmt_date_long(d: date) -> str:
    """e.g. '1 juli 2026'."""
    return f"{d.day} {SV_MONTHS_LONG[d.month - 1]} {d.year}"


# --- Plan card styling ---
# The day matching today's date gets an accent border/background instead of
# the default plain card, echoing the red accent used for the active sidebar
# nav link in app.py. Scoped via st.container(key="plan-day-today-*") so it
# doesn't affect the other (non-today) plan-day cards. Tweak colors/radius to
# taste.
_TODAY_CARD_CSS = """
    <style>
    div[data-testid="stVerticalBlock"][class*="st-key-plan-day-today-"] {
        background-color: rgba(255, 75, 75, 0.08);  /* accent background tint */
        border: 1px solid rgba(255, 75, 75, 0.6) !important;  /* accent border */
        border-radius: 12px;                                  /* corner roundness */
    }
    </style>
"""


def render_plan(plan: dict) -> None:
    """Render a plan dict with 'summary' and 'days' (list of day dicts) as
    an info box followed by a card per day. The card for today's date is
    visually highlighted with an "Idag" badge and an accent border/tint."""
    if summary := plan.get("summary"):
        st.info(summary)
    days = plan.get("days") or []
    if not days:
        st.info("Planen innehåller inga dagar.")
        return
    st.markdown(_TODAY_CARD_CSS, unsafe_allow_html=True)
    today = date.today()
    for i, day in enumerate(days):
        d = parse_date(day.get("date"))
        date_str = fmt_date_weekday(d) if d else day.get("date", "?")
        sport = day.get("sport_type", "–")
        duration = day.get("duration_min", 0)
        zone = day.get("intensity_zone", "–")
        rationale = day.get("rationale", "")
        is_today = d == today
        card_key = f"plan-day-today-{i}" if is_today else f"plan-day-{i}"
        with st.container(border=True, key=card_key):
            col1, col2 = st.columns([1, 3])
            with col1:
                if is_today:
                    st.badge("Idag", color="red")
                st.write(f"**{date_str}**")
                if sport.lower() == "rest":
                    st.write("Vila")
                else:
                    st.write(f"{sport} · {duration} min · {zone}")
            with col2:
                if rationale:
                    st.write(rationale)
