from datetime import datetime, timezone

import streamlit as st

from generate_plan import (
    DEFAULT_PROMPT_TEMPLATE,
    PROMPT_PLACEHOLDERS,
    PROMPT_SETTINGS_KEY,
    get_active_prompt_template,
)
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

st.divider()

st.subheader("Planeringsprompt")
st.write(
    "Detta är hela prompten som skickas till Claude när en 7-dagarsplan genereras "
    "(från Reflektera-sidan). Allt nedan är redigerbart, inklusive reglerna och "
    "sportprioriteringen längre ner — ändra sportbias, intensitetsregler eller "
    "annat direkt i texten. Spara skriver till `app_settings` och används från "
    "nästa plangenerering."
)

with st.expander("Tillgängliga platshållare"):
    for name, desc in PROMPT_PLACEHOLDERS.items():
        st.markdown(f"- `{{{name}}}` — {desc}")

try:
    custom_row = (
        supabase.table("app_settings")
        .select("value,updated_at")
        .eq("key", PROMPT_SETTINGS_KEY)
        .limit(1)
        .execute()
    ).data or []
except Exception as e:
    st.error(f"Kunde inte hämta sparad prompt: {e}")
    custom_row = []

if custom_row:
    updated_at = custom_row[0].get("updated_at") or "?"
    st.caption(f"Använder anpassad prompt (sparad {updated_at}).")
else:
    st.caption("Använder inbyggd standardprompt (ingen anpassad version sparad).")

if "prompt_template_text" not in st.session_state:
    st.session_state.prompt_template_text = get_active_prompt_template(supabase)

# Reset must run before st.text_area() below instantiates its widget state,
# since Streamlit forbids mutating a widget's session_state key after that
# widget has been created in the same script run.
if st.button("Återställ till standard"):
    try:
        supabase.table("app_settings").delete().eq("key", PROMPT_SETTINGS_KEY).execute()
        st.session_state.prompt_template_text = DEFAULT_PROMPT_TEMPLATE
        st.success("Återställd till standardprompten.")
        st.rerun()
    except Exception as e:
        st.error(f"Kunde inte återställa: {e}")

st.text_area("Prompt-mall", key="prompt_template_text", height=500)

if st.button("Spara prompt"):
    try:
        supabase.table("app_settings").upsert(
            {
                "key": PROMPT_SETTINGS_KEY,
                "value": st.session_state.prompt_template_text,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="key",
        ).execute()
        st.success("Prompt sparad.")
    except Exception as e:
        st.error(f"Kunde inte spara prompt: {e}")
