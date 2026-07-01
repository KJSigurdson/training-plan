import streamlit as st

st.set_page_config(page_title="Träningsplan", layout="wide")

pages = [
    st.Page("pages/reflektera.py", title="Reflektera", icon="📝", default=True),
    st.Page("pages/oversikt.py", title="Översikt", icon="📊"),
]

st.navigation(pages).run()
