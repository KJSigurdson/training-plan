import streamlit as st

from long_term_plan import generate_long_term_plan
from shared import fmt_date_long, parse_date, require_supabase

supabase = require_supabase()

st.title("Inställningar")

st.subheader("Långtidsplan")
st.write(
    "Genererar en veckovis periodiserad plan (målbelastning, fas, anteckning) "
    "från innevarande vecka fram till loppveckan, baserat på målet i `goal`-tabellen "
    "och den senaste träningshistoriken. Sparas i `weekly_targets` och används dels "
    "för att rita faktisk-mot-mål-grafen på Översikt, dels för att förankra den "
    "kommande 7-dagarsplanen mot veckans målbelastning."
)

try:
    existing = (
        supabase.table("weekly_targets")
        .select("week_start")
        .order("week_start")
        .execute()
    ).data or []
except Exception as e:
    st.error(f"Kunde inte hämta befintlig långtidsplan: {e}")
    existing = []

if existing:
    first = parse_date(existing[0]["week_start"])
    last = parse_date(existing[-1]["week_start"])
    st.caption(
        f"Nuvarande långtidsplan: {len(existing)} veckor, "
        f"{fmt_date_long(first) if first else '?'} – {fmt_date_long(last) if last else '?'}."
    )
else:
    st.caption("Ingen långtidsplan genererad än.")

if st.button("Generera långtidsplan"):
    try:
        with st.spinner("Genererar långtidsplan…"):
            rows = generate_long_term_plan()
        st.success(f"Långtidsplan sparad: {len(rows)} veckor skrivna till weekly_targets.")
    except Exception as e:
        st.error(f"Kunde inte generera långtidsplan: {e}")
