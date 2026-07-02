from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from generate_plan import _phase_from_weeks
from shared import fmt_date_long, fmt_duration, parse_date, render_plan, require_supabase

supabase = require_supabase()

PHASE_LABELS = {"base": "Bas", "build": "Uppbyggnad", "peak": "Topp", "taper": "Nedtrappning"}

# --- Goal cards styling ---
# Goal facts (Lopp/Datum/Veckor kvar/Fas) render as st.metric inside
# st.container(border=True, key="goal-card-...").  Passing `key=` gives each
# card's wrapper a stable `st-key-goal-card-*` class we can target precisely,
# without also styling other bordered containers on this page (e.g. the plan
# day cards from render_plan). Tweak colors/radius/font-size to taste.
st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlock"][class*="st-key-goal-card-"] {
        background-color: rgba(151, 166, 195, 0.15);  /* card background fill */
        border-radius: 12px;                          /* corner roundness */
        padding: 8px;
    }
    /* Center the metric label/value/delta inside each card */
    [class*="st-key-goal-card-"] [data-testid="stMetric"] {
        text-align: center;
    }
    [class*="st-key-goal-card-"] [data-testid="stMetricLabel"],
    [class*="st-key-goal-card-"] [data-testid="stMetricValue"] {
        justify-content: center;
    }
    /* Let the race name wrap instead of truncating with an ellipsis.
       Streamlit truncates metric values via CSS on the inner <p>, so
       override with !important and target descendants too. */
    [class*="st-key-goal-card-"] [data-testid="stMetricValue"],
    [class*="st-key-goal-card-"] [data-testid="stMetricValue"] * {
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: unset !important;
        overflow-wrap: break-word !important;
    }
    [class*="st-key-goal-card-"] [data-testid="stMetricValue"] {
        font-size: 1.5rem;  /* slightly smaller than default so long names fit */
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Översikt")

# --- Goal header ---

st.subheader("Mål")

try:
    goal_result = supabase.table("goal").select("*").limit(1).execute()
    goal = goal_result.data[0] if goal_result.data else None
except Exception as e:
    st.error(f"Kunde inte hämta mål: {e}")
    goal = None

race_date = parse_date(goal.get("race_date")) if goal else None

if not goal:
    st.info("Inget mål är satt än.")
else:
    if race_date:
        weeks_to_race = max(0.0, (race_date - date.today()).days / 7)
        phase_label = PHASE_LABELS.get(_phase_from_weeks(weeks_to_race), "–")
        weeks_label = str(round(weeks_to_race))
    else:
        phase_label = "–"
        weeks_label = "–"

    goal_facts = [
        ("Lopp", goal.get("race_name") or "–"),
        ("Datum", fmt_date_long(race_date) if race_date else "–"),
        ("Veckor kvar", weeks_label),
        ("Fas", phase_label),
    ]
    for col, (label, value) in zip(st.columns(4), goal_facts):
        with col, st.container(border=True, key=f"goal-card-{label}"):
            st.metric(label, value)

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

# --- Filters (apply to load chart, session history, and fatigue trend) ---

MUSCLE_GROUP_OPTIONS = ["lower", "upper", "full_body", "other"]
DEFAULT_WEEKS_BACK = 8

try:
    sport_type_result = supabase.table("sessions").select("sport_type").execute()
    sport_type_options = sorted({
        row["sport_type"] for row in (sport_type_result.data or []) if row.get("sport_type")
    })
except Exception as e:
    st.error(f"Kunde inte hämta sporttyper: {e}")
    sport_type_options = []

today = date.today()
default_from = today - timedelta(weeks=DEFAULT_WEEKS_BACK)

with st.expander("Filter", expanded=True):
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        date_range = st.date_input(
            "Datumintervall", value=(default_from, today), format="YYYY-MM-DD"
        )
    with filter_col2:
        selected_sports = st.multiselect(
            "Sport", options=sport_type_options, default=sport_type_options
        )
    with filter_col3:
        selected_muscle_groups = st.multiselect(
            "Muskelgrupp", options=MUSCLE_GROUP_OPTIONS, default=MUSCLE_GROUP_OPTIONS
        )

# st.date_input returns a single date while the user has only picked one
# endpoint of the range; fall back to the default range until both are set.
if isinstance(date_range, tuple) and len(date_range) == 2:
    from_date, to_date = date_range
else:
    from_date, to_date = default_from, today

# --- Shared filtered session fetch ---

if from_date > to_date or not selected_sports or not selected_muscle_groups:
    filtered_sessions = []
else:
    try:
        filtered_result = (
            supabase.table("sessions")
            .select("*")
            .gte("start_date", from_date.isoformat())
            .lt("start_date", (to_date + timedelta(days=1)).isoformat())
            .in_("sport_type", selected_sports)
            .in_("muscle_group", selected_muscle_groups)
            .order("start_date", desc=True)
            .execute()
        )
        filtered_sessions = filtered_result.data or []
    except Exception as e:
        st.error(f"Kunde inte hämta pass: {e}")
        filtered_sessions = []

qa_by_session: dict[str, dict] = {}
if filtered_sessions:
    try:
        session_ids = [s["id"] for s in filtered_sessions if s.get("id")]
        qa_result = (
            supabase.table("qa_responses")
            .select("session_id,feeling,tiredness")
            .in_("session_id", session_ids)
            .execute()
        )
        qa_by_session = {r["session_id"]: r for r in (qa_result.data or [])}
    except Exception as e:
        st.warning(f"Kunde inte hämta reflektioner: {e}")

# --- Training load over time ---

st.subheader("Träningsbelastning över tid")

load_rows = []
for s in filtered_sessions:
    if s.get("training_load") is None:
        continue
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
    st.info("Ingen träningsbelastning registrerad för valda filter.")
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
    # "YYYY-vWW" sorts lexicographically the same as chronologically; pin it
    # explicitly since separate per-color traces don't guarantee week order otherwise.
    fig_load.update_xaxes(categoryorder="category ascending")
    st.plotly_chart(fig_load, width="stretch")

st.divider()

# --- Long-term plan: actual vs. target (full period, ignores date-range filter) ---

st.subheader("Långtidsplan: faktisk vs. mål")

if not race_date:
    st.info("Inget loppdatum satt — kan inte visa långtidsgrafen.")
else:
    long_term_from_week = today - timedelta(weeks=8)
    long_term_from_week -= timedelta(days=long_term_from_week.weekday())
    long_term_to_week = race_date - timedelta(days=race_date.weekday())

    try:
        actual_query = (
            supabase.table("sessions")
            .select("start_date,training_load,muscle_group,sport_type")
            .gte("start_date", long_term_from_week.isoformat())
            .lt("start_date", (long_term_to_week + timedelta(days=7)).isoformat())
            .not_.is_("training_load", "null")
        )
        # Long-view is inherently full-period, so the date-range filter is
        # ignored here on purpose; sport/muscle filters still apply to the bars.
        if selected_sports:
            actual_query = actual_query.in_("sport_type", selected_sports)
        if selected_muscle_groups:
            actual_query = actual_query.in_("muscle_group", selected_muscle_groups)
        long_term_actual = actual_query.execute().data or []
    except Exception as e:
        st.error(f"Kunde inte hämta långsiktig träningsbelastning: {e}")
        long_term_actual = []

    try:
        target_result = (
            supabase.table("weekly_targets")
            .select("week_start,target_load")
            .gte("week_start", long_term_from_week.isoformat())
            .lte("week_start", long_term_to_week.isoformat())
            .order("week_start")
            .execute()
        )
        weekly_targets_rows = target_result.data or []
    except Exception as e:
        st.error(f"Kunde inte hämta veckomål: {e}")
        weekly_targets_rows = []

    if not long_term_actual and not weekly_targets_rows:
        st.info("Ingen data för långtidsgrafen än. Generera en långtidsplan under Inställningar.")
    else:
        actual_rows = []
        for s in long_term_actual:
            d = parse_date(s.get("start_date"))
            if not d:
                continue
            week_start = d - timedelta(days=d.weekday())
            iso_year, iso_week, _ = d.isocalendar()
            actual_rows.append({
                "week_start": week_start.isoformat(),
                "week": f"{iso_year}-v{iso_week:02d}",
                "training_load": float(s.get("training_load") or 0),
                "muscle_group": (s.get("muscle_group") or "okänd").lower(),
            })

        fig_long_term = go.Figure()
        if actual_rows:
            actual_df = pd.DataFrame(actual_rows)
            weekly_actual = (
                actual_df.groupby(["week_start", "week", "muscle_group"], as_index=False)
                ["training_load"].sum()
            )
            for mg in sorted(weekly_actual["muscle_group"].unique()):
                mg_df = weekly_actual[weekly_actual["muscle_group"] == mg].sort_values("week_start")
                fig_long_term.add_trace(go.Bar(x=mg_df["week"], y=mg_df["training_load"], name=mg))

        if weekly_targets_rows:
            target_df = pd.DataFrame(weekly_targets_rows)
            target_df["week_start_date"] = target_df["week_start"].apply(parse_date)
            target_df = target_df.dropna(subset=["week_start_date"]).sort_values("week_start_date")
            target_df["week"] = target_df["week_start_date"].apply(
                lambda d: f"{d.isocalendar()[0]}-v{d.isocalendar()[1]:02d}"
            )
            fig_long_term.add_trace(go.Scatter(
                x=target_df["week"], y=target_df["target_load"],
                name="Mål", mode="lines+markers", line=dict(color="black", width=3),
            ))

        fig_long_term.update_layout(
            barmode="stack",
            # "YYYY-vWW" sorts lexicographically the same as chronologically; pin it
            # explicitly since separate per-muscle-group bar traces plus the target
            # line don't all cover the same weeks, so trace-order default would scramble it.
            xaxis=dict(title="Vecka", categoryorder="category ascending"),
            yaxis=dict(title="Träningsbelastning"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_long_term, width="stretch")

st.divider()

# --- Session history & fatigue trend ---

st.subheader("Passhistorik")

if not filtered_sessions:
    st.info("Inga pass registrerade för valda filter.")
else:
    history_rows = []
    for s in filtered_sessions:
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
for s in reversed(filtered_sessions):  # oldest to newest, left to right
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
    st.info("Ingen data med träningsbelastning att visa trend för valda filter.")
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
