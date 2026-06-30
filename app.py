import os
from datetime import date, timedelta

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    st.error("SUPABASE_URL och SUPABASE_SERVICE_ROLE_KEY måste finnas i .env-filen.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# --- Helpers ---

def fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m:02d}min"


def upcoming_day_labels() -> list[str]:
    """Return labels for tomorrow through 7 days out, e.g. 'Ons 1 jul'."""
    sv_days = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"]
    sv_months = ["jan", "feb", "mar", "apr", "maj", "jun",
                 "jul", "aug", "sep", "okt", "nov", "dec"]
    labels = []
    tomorrow = date.today() + timedelta(days=1)
    for i in range(7):
        d = tomorrow + timedelta(days=i)
        labels.append(f"{sv_days[d.weekday()]} {d.day} {sv_months[d.month - 1]}")
    return labels


def fetch_awaiting_sessions() -> list[dict]:
    result = (
        supabase.table("sessions")
        .select("*")
        .eq("status", "awaiting_input")
        .order("start_date", desc=True)
        .execute()
    )
    return result.data or []


def has_existing_response(session_id: str) -> bool:
    result = (
        supabase.table("qa_responses")
        .select("id")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    return bool(result.data)


def insert_response(session_id: str, how_it_went: str, feeling: int,
                    tiredness: int, availability: list[bool]) -> None:
    supabase.table("qa_responses").insert({
        "session_id": session_id,
        "how_it_went": how_it_went,
        "feeling": feeling,
        "tiredness": tiredness,
        "availability": availability,
    }).execute()


def mark_session_ready(session_id: str) -> None:
    supabase.table("sessions").update({"status": "ready_for_plan"}).eq("id", session_id).execute()


# --- UI ---

st.title("Träningsreflektion")

try:
    sessions = fetch_awaiting_sessions()
except Exception as e:
    st.error(f"Kunde inte hämta pass: {e}")
    st.stop()

if not sessions:
    st.info("Inga pass att reflektera över just nu.")
    st.stop()

day_labels = upcoming_day_labels()

feeling_options = {1: "1 – Hemskt", 2: "2 – Okej", 3: "3 – Bra", 4: "4 – Utmärkt"}
tiredness_options = {1: "1 – Utmattad", 2: "2 – Trött", 3: "3 – Pigg", 4: "4 – Fräsch"}

for session in sessions:
    sid = session["id"]

    # Guard: skip if a response already exists
    try:
        if has_existing_response(sid):
            continue
    except Exception as e:
        st.warning(f"Kunde inte kontrollera befintligt svar för pass {sid}: {e}")
        continue

    # Format display values
    sport = session.get("sport_type", "–")
    raw_date = session.get("start_date", "")
    try:
        parsed = date.fromisoformat(raw_date[:10])
        sv_months_long = ["januari", "februari", "mars", "april", "maj", "juni",
                          "juli", "augusti", "september", "oktober", "november", "december"]
        readable_date = f"{parsed.day} {sv_months_long[parsed.month - 1]} {parsed.year}"
    except Exception:
        readable_date = raw_date

    distance_km = (session.get("distance_m") or 0) / 1000
    duration_str = fmt_duration(session.get("moving_time_s") or 0)
    elevation = session.get("elevation_gain_m") or 0
    load = session.get("training_load")
    load_str = str(round(load)) if load is not None else "–"

    with st.container(border=True):
        st.subheader(f"{sport} — {readable_date}")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Distans", f"{distance_km:.1f} km")
        col2.metric("Tid", duration_str)
        col3.metric("Höjdmeter", f"{elevation} m")
        col4.metric("Träningsbelastning", load_str)

        with st.form(key=f"form_{sid}"):
            how_it_went = st.text_area("Hur kändes passet?", key=f"how_{sid}")

            feeling_label = st.radio(
                "Känsla efter passet",
                options=list(feeling_options.keys()),
                format_func=lambda x: feeling_options[x],
                horizontal=True,
                key=f"feeling_{sid}",
            )

            tiredness_label = st.radio(
                "Trötthet efter passet",
                options=list(tiredness_options.keys()),
                format_func=lambda x: tiredness_options[x],
                horizontal=True,
                key=f"tiredness_{sid}",
            )

            st.write("Tillgänglighet kommande 7 dagar")
            avail_cols = st.columns(7)
            availability = []
            for i, label in enumerate(day_labels):
                checked = avail_cols[i].checkbox(label, key=f"avail_{sid}_{i}")
                availability.append(checked)

            submitted = st.form_submit_button("Spara reflektion")

        if submitted:
            try:
                insert_response(sid, how_it_went, feeling_label, tiredness_label, availability)
            except Exception as e:
                st.error(f"Kunde inte spara reflektion: {e}")
                continue

            try:
                mark_session_ready(sid)
            except Exception as e:
                st.error(
                    f"Reflektionen sparades men status på passet kunde inte uppdateras: {e}. "
                    "Kontakta support eller uppdatera manuellt."
                )
                continue

            st.success("Reflektion sparad!")
            st.rerun()
