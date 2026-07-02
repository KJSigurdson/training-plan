import streamlit as st

st.set_page_config(page_title="Träningsplan", layout="wide")

# --- Sidebar chrome (applies to every page, since app.py runs on each nav) ---
# Streamlit doesn't expose sidebar width or nav-link styling as options, so we
# reach for CSS. Tweak the values below (width, font-size, colors, radius) to taste.
st.markdown(
    """
    <style>
    /* Sidebar width: Streamlit's default is quite wide. Narrow it down so it
       roughly hugs the nav text instead. Adjust SIDEBAR_WIDTH to taste. */
    section[data-testid="stSidebar"] {
        width: 190px !important;
        min-width: 190px !important;
        max-width: 190px !important;
    }

    /* Nav links (Reflektera, Översikt): bigger, centered text */
    [data-testid="stSidebarNavLink"] {
        justify-content: center !important;
        text-align: center !important;
        font-size: 1.05rem !important;
    }

    /* Button-like look: background fill, rounded corners, spacing */
    [data-testid="stSidebarNavLink"] {
        margin: 4px 10px !important;
        padding: 10px 14px !important;
        border-radius: 10px !important;          /* corner roundness */
        background-color: rgba(151, 166, 195, 0.15) !important;  /* subtle fill */
        transition: background-color 0.15s ease;
    }

    /* Hover state */
    [data-testid="stSidebarNavLink"]:hover {
        background-color: rgba(151, 166, 195, 0.32) !important;
    }

    /* Current/active page gets a slightly stronger fill */
    [data-testid="stSidebarNavLink"][aria-current="page"] {
        background-color: rgba(255, 75, 75, 0.15) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

pages = [
    st.Page("pages/reflektera.py", title="Reflektera", icon="📝", default=True),
    st.Page("pages/oversikt.py", title="Översikt", icon="📊"),
    st.Page("pages/installningar.py", title="Inställningar", icon="⚙️"),
]

st.navigation(pages).run()
