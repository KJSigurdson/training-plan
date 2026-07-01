from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from generate_plan import _phase_from_weeks
from shared import fmt_date_long, fmt_duration, parse_date, render_plan, require_supabase

supabase = require_supabase()

PHASE_LABELS = {"base": "Bas", "build": "Uppbyggnad", "peak": "Topp", "taper": "Nedtrappning"}

st.title("Översikt")

# --- Goal header ---

st.subheader("Mål")

try:
    goal_result = supabase.table("goal").select("*").limit(1).execute()
    goal = goal_result.data[0] if goal_result.data else None
except Exception as e:
    st.error(f"Kunde inte hämta mål: {e}")
    goal = None

if not goal:
    st.info("Inget mål är satt än.")
else:
    race_date = parse_date(goal.get("race_date"))
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Lopp", goal.get("race_name") or "–")
    col2.metric("Datum", fmt_date_long(race_date) if race_date else "–")
    if race_date:
        weeks_to_race = max(0.0, (race_date - date.today()).days / 7)
        phase = _phase_from_weeks(weeks_to_race)
        col3.metric("Veckor kvar", f"{weeks_to_race:.1f}")
        col4.metric("Fas", PHASE_LABELS.get(phase, phase))
    else:
        col3.metric("Veckor kvar", "–")
        col4.metric("Fas", "–")

st.divider()

# --- Current plan ---

st.subheader("Aktuell plan")

try:
    plan_result = (
        supabase.table("plans")
        .select("*")
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
    )
    latest_plan_row = plan_result.data[0] if plan_result.data else None
except Exception as e:
    st.error(f"Kunde inte hämta plan: {e}")
    latest_plan_row = None

if not latest_plan_row:
    st.info("Ingen plan genererad än.")
else:
    render_plan({
        "summary": latest_plan_row.get("summary"),
        "days": latest_plan_row.get("plan") or [],
    })

st.divider()

# --- Training load over time ---

st.subheader("Träningsbelastning över tid")

try:
    load_result = (
        supabase.table("sessions")
        .select("start_date,training_load,muscle_group")
        .not_.is_("training_load", "null")
        .order("start_date")
        .execute()
    )
    load_sessions = load_result.data or []
except Exception as e:
    st.error(f"Kunde inte hämta träningsbelastning: {e}")
    load_sessions = []

load_rows = []
for s in load_sessions:
    d = parse_date(s.get("start_date"))
    if not d:
        continue
    iso_year, iso_week, _ = d.isocalendar()
    load_rows.append({
        "week": f"{iso_year}-v{iso_week:02d}",
        "training_load": float(s.get("training_load") or 0),
        "muscle_group": (s.get("muscle_group") or "okänd").lower(),
    })

if not load_rows:
    st.info("Ingen träningsbelastning registrerad än.")
else:
    load_df = pd.DataFrame(load_rows)
    weekly_load = (
        load_df.groupby(["week", "muscle_group"], as_index=False)["training_load"]
        .sum()
        .sort_values("week")
    )
    fig_load = px.bar(
        weekly_load,
        x="week",
        y="training_load",
        color="muscle_group",
        labels={
            "week": "Vecka",
            "training_load": "Träningsbelastning",
            "muscle_group": "Muskelgrupp",
        },
    )
    st.plotly_chart(fig_load, width="stretch")

st.divider()

# --- Session history & fatigue trend ---

try:
    recent_result = (
        supabase.table("sessions")
        .select("*")
        .order("start_date", desc=True)
        .limit(20)
        .execute()
    )
    recent_sessions = recent_result.data or []
except Exception as e:
    st.error(f"Kunde inte hämta pass: {e}")
    recent_sessions = []

qa_by_session: dict[str, dict] = {}
if recent_sessions:
    try:
        session_ids = [s["id"] for s in recent_sessions if s.get("id")]
        qa_result = (
            supabase.table("qa_responses")
            .select("session_id,feeling,tiredness")
            .in_("session_id", session_ids)
            .execute()
        )
        qa_by_session = {r["session_id"]: r for r in (qa_result.data or [])}
    except Exception as e:
        st.warning(f"Kunde inte hämta reflektioner: {e}")

st.subheader("Passhistorik")

if not recent_sessions:
    st.info("Inga pass registrerade än.")
else:
    history_rows = []
    for s in recent_sessions:
        d = parse_date(s.get("start_date"))
        qa = qa_by_session.get(s.get("id"), {})
        history_rows.append({
            "Datum": fmt_date_long(d) if d else "–",
            "Sport": s.get("sport_type") or "–",
            "Distans (km)": round((s.get("distance_m") or 0) / 1000, 1),
            "Tid": fmt_duration(s.get("moving_time_s") or 0),
            "Träningsbelastning": s.get("training_load"),
            "Känsla": qa.get("feeling"),
            "Trötthet": qa.get("tiredness"),
        })
    st.dataframe(pd.DataFrame(history_rows), width="stretch", hide_index=True)

st.divider()

st.subheader("Trötthetstrend")

trend_rows = []
for s in reversed(recent_sessions):  # oldest to newest, left to right
    d = parse_date(s.get("start_date"))
    if not d or s.get("training_load") is None:
        continue
    qa = qa_by_session.get(s.get("id"), {})
    trend_rows.append({
        "date": d,
        "training_load": float(s.get("training_load") or 0),
        "feeling": qa.get("feeling"),
        "tiredness": qa.get("tiredness"),
    })

if not trend_rows:
    st.info("Ingen data med träningsbelastning att visa trend för än.")
else:
    trend_df = pd.DataFrame(trend_rows)
    fig_trend = go.Figure()
    fig_trend.add_trace(go.Bar(
        x=trend_df["date"], y=trend_df["training_load"],
        name="Träningsbelastning", yaxis="y1", opacity=0.5,
    ))
    fig_trend.add_trace(go.Scatter(
        x=trend_df["date"], y=trend_df["feeling"],
        name="Känsla", yaxis="y2", mode="lines+markers",
    ))
    fig_trend.add_trace(go.Scatter(
        x=trend_df["date"], y=trend_df["tiredness"],
        name="Trötthet", yaxis="y2", mode="lines+markers",
    ))
    fig_trend.update_layout(
        xaxis=dict(title="Datum"),
        yaxis=dict(title="Träningsbelastning"),
        yaxis2=dict(
            title="Känsla / Trötthet (1–4)",
            overlaying="y",
            side="right",
            range=[0, 4.5],
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_trend, width="stretch")
