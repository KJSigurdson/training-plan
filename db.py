import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_client: Client | None = None


def _get_secret(key: str) -> str | None:
    try:
        import streamlit as st
        return st.secrets[key]
    except Exception:
        return os.getenv(key)


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = _get_secret("SUPABASE_URL")
        key = _get_secret("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env or st.secrets"
            )
        _client = create_client(url, key)
    return _client
