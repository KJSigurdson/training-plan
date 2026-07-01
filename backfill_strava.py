"""One-time backfill: import the last 8 weeks of Strava activities into the
sessions table (status='planned') so training load history has real data.

Zone/training-load logic mirrors the fetch-activity Supabase Edge Function
(the live pipeline that processes new activities one at a time).

Usage:
    python backfill_strava.py
"""

import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from db import _get_secret, get_supabase

load_dotenv()

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
WEEKS_BACK = 8
PER_PAGE = 100
ZONE_KEYS = ["pct_z1", "pct_z2", "pct_z3", "pct_z4", "pct_z5"]


class RateLimited(Exception):
    pass


def get_strava_credentials() -> tuple[str, str, str]:
    client_id = _get_secret("STRAVA_CLIENT_ID")
    client_secret = _get_secret("STRAVA_CLIENT_SECRET")
    refresh_token = _get_secret("STRAVA_REFRESH_TOKEN")
    missing = [
        name for name, val in [
            ("STRAVA_CLIENT_ID", client_id),
            ("STRAVA_CLIENT_SECRET", client_secret),
            ("STRAVA_REFRESH_TOKEN", refresh_token),
        ] if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing Strava credentials: {', '.join(missing)} (set in .env or st.secrets)"
        )
    return client_id, client_secret, refresh_token


def refresh_access_token() -> str:
    client_id, client_secret, refresh_token = get_strava_credentials()
    resp = requests.post(
        STRAVA_TOKEN_URL,
        json={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Token refresh failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def strava_get(url: str, access_token: str, params: dict | None = None) -> requests.Response:
    resp = requests.get(
        url, headers={"Authorization": f"Bearer {access_token}"}, params=params, timeout=30
    )
    if resp.status_code == 429:
        raise RateLimited(f"429 from {url}")
    return resp


def fetch_activities(access_token: str, after_ts: int) -> list[dict]:
    activities = []
    page = 1
    while True:
        resp = strava_get(
            f"{STRAVA_API_BASE}/athlete/activities",
            access_token,
            params={"after": after_ts, "per_page": PER_PAGE, "page": page},
        )
        if not resp.ok:
            raise RuntimeError(f"Activity list fetch failed: {resp.status_code} {resp.text}")
        batch = resp.json()
        if not batch:
            break
        activities.extend(batch)
        print(f"  page {page}: {len(batch)} activities")
        page += 1
    return activities


def fetch_hr_zone_pcts(access_token: str, activity_id: int) -> tuple[bool, dict]:
    """Mirrors fetch-activity/index.ts: exactly-5 HR buckets required, else no zones."""
    pcts = dict.fromkeys(ZONE_KEYS, None)
    resp = strava_get(f"{STRAVA_API_BASE}/activities/{activity_id}/zones", access_token)
    if not resp.ok:
        return False, pcts
    zones_data = resp.json()
    hr_zone = next(
        (z for z in zones_data if isinstance(z, dict) and z.get("type") == "heartrate"), None
    )
    buckets = (hr_zone or {}).get("distribution_buckets")
    if not buckets or len(buckets) != 5:
        return False, pcts
    total_time = sum(b["time"] for b in buckets)
    if total_time <= 0:
        return False, pcts
    for key, bucket in zip(ZONE_KEYS, buckets):
        pcts[key] = bucket["time"] / total_time
    return True, pcts


def compute_training_load(moving_time_s: int, has_hr_zones: bool, pcts: dict) -> float:
    moving_time_min = moving_time_s / 60
    if has_hr_zones:
        weighted = sum((pcts[f"pct_z{i}"] or 0) * i for i in range(1, 6))
        return moving_time_min * weighted
    return moving_time_min * 2  # fallback intensity factor, matches fetch-activity


def build_muscle_group_map(supabase) -> dict[str, str]:
    rows = supabase.table("sport_stress_map").select("sport_type,muscle_group").execute().data or []
    return {row["sport_type"]: row["muscle_group"] for row in rows}


def lookup_muscle_group(muscle_map: dict[str, str], sport_type: str) -> str:
    return muscle_map.get(sport_type) or muscle_map.get("default") or "other"


def main() -> None:
    supabase = get_supabase()

    print("Refreshing Strava access token…")
    access_token = refresh_access_token()

    after_ts = int((datetime.now(timezone.utc) - timedelta(weeks=WEEKS_BACK)).timestamp())
    since = datetime.fromtimestamp(after_ts, tz=timezone.utc).date().isoformat()
    print(f"Fetching activities since {since}…")

    try:
        activities = fetch_activities(access_token, after_ts)
    except RateLimited as e:
        print(f"Rate limited while listing activities: {e}")
        print("Summary: fetched=0 inserted=0 skipped=0 (stopped before processing any activities)")
        sys.exit(1)

    print(f"Fetched {len(activities)} activities from Strava.\n")

    existing_ids = {
        row["strava_activity_id"]
        for row in (supabase.table("sessions").select("strava_activity_id").execute().data or [])
        if row.get("strava_activity_id") is not None
    }
    muscle_map = build_muscle_group_map(supabase)

    inserted = 0
    skipped = 0
    rate_limited_at = None

    for i, activity in enumerate(activities, start=1):
        activity_id = activity["id"]
        sport_type = activity.get("sport_type", "Unknown")
        label = f"[{i}/{len(activities)}] {sport_type} {str(activity.get('start_date'))[:10]} (id={activity_id})"

        if activity_id in existing_ids:
            print(f"{label} — already present, skipping")
            skipped += 1
            continue

        try:
            has_hr_zones, pcts = fetch_hr_zone_pcts(access_token, activity_id)
        except RateLimited as e:
            print(f"{label} — rate limited: {e}")
            rate_limited_at = i
            break

        moving_time_s = activity.get("moving_time") or 0
        training_load = compute_training_load(moving_time_s, has_hr_zones, pcts)
        muscle_group = lookup_muscle_group(muscle_map, sport_type)

        row = {
            "strava_activity_id": activity_id,
            "status": "planned",
            "sport_type": sport_type,
            "start_date": activity.get("start_date"),
            "moving_time_s": moving_time_s,
            "distance_m": activity.get("distance") or 0,
            "elevation_gain_m": activity.get("total_elevation_gain") or 0,
            "average_speed_mps": activity.get("average_speed") or 0,
            "has_hr_zones": has_hr_zones,
            "training_load": round(training_load, 2),
            "muscle_group": muscle_group,
            **pcts,
        }

        try:
            supabase.table("sessions").upsert(
                row, on_conflict="strava_activity_id", ignore_duplicates=True
            ).execute()
            inserted += 1
            existing_ids.add(activity_id)
            print(
                f"{label} — inserted (load={training_load:.0f}, "
                f"muscle_group={muscle_group}, hr_zones={has_hr_zones})"
            )
        except Exception as e:
            print(f"{label} — ERROR inserting: {e}")

    print("\n--- Summary ---")
    print(f"Fetched:  {len(activities)}")
    print(f"Inserted: {inserted}")
    print(f"Skipped (already present): {skipped}")
    if rate_limited_at is not None:
        remaining = len(activities) - rate_limited_at
        print(
            f"Stopped early: Strava rate limit hit after activity {rate_limited_at}/{len(activities)} "
            f"({remaining} not processed). Re-run later — already-inserted activities are skipped."
        )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
