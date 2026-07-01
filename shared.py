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


def render_plan(plan: dict) -> None:
    """Render a plan dict with 'summary' and 'days' (list of day dicts) as
    an info box followed by a card per day."""
    if summary := plan.get("summary"):
        st.info(summary)
    days = plan.get("days") or []
    if not days:
        st.info("Planen innehåller inga dagar.")
        return
    for day in days:
        d = parse_date(day.get("date"))
        date_str = fmt_date_weekday(d) if d else day.get("date", "?")
        sport = day.get("sport_type", "–")
        duration = day.get("duration_min", 0)
        zone = day.get("intensity_zone", "–")
        rationale = day.get("rationale", "")
        with st.container(border=True):
            col1, col2 = st.columns([1, 3])
            with col1:
                st.write(f"**{date_str}**")
                if sport.lower() == "rest":
                    st.write("Vila")
                else:
                    st.write(f"{sport} · {duration} min · {zone}")
            with col2:
                if rationale:
                    st.write(rationale)
