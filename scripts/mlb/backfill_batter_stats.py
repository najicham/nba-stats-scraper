#!/usr/bin/env python3
"""
Backfill mlb_raw.mlbapi_batter_stats from MLB Stats API.

Replaces unreliable BDL batter data with game-level granular data
from the official MLB Stats API (free, no auth required).

Usage:
    PYTHONPATH=. python scripts/mlb/backfill_batter_stats.py \
        --start 2024-03-28 --end 2025-09-28 --sleep 0.3

    # Dry run (no BQ writes)
    PYTHONPATH=. python scripts/mlb/backfill_batter_stats.py \
        --start 2025-09-01 --end 2025-09-05 --dry-run

    # Resume from a specific date (skips dates with existing data)
    PYTHONPATH=. python scripts/mlb/backfill_batter_stats.py \
        --start 2024-03-28 --end 2025-09-28 --skip-existing
"""

import argparse
import hashlib
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCHEDULE_API = "https://statsapi.mlb.com/api/v1/schedule"
GAME_FEED_API = "https://statsapi.mlb.com/api/v1.1/game"
PROJECT_ID = "nba-props-platform"
TABLE_ID = f"{PROJECT_ID}.mlb_raw.mlbapi_batter_stats"
PITCHER_POSITION_CODE = "1"


def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"\s+(Jr\.|Sr\.|III|II|IV)$", "", name.strip())
    name = re.sub(r"[^a-zA-Z0-9]", "_", name.lower())
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def compute_hash(record: Dict) -> str:
    fields = [
        str(record.get("game_pk", "")),
        str(record.get("player_id", "")),
        str(record.get("strikeouts", "")),
        str(record.get("at_bats", "")),
        str(record.get("hits", "")),
        str(record.get("walks", "")),
        str(record.get("home_runs", "")),
        str(record.get("rbis", "")),
    ]
    return hashlib.sha256("|".join(fields).encode()).hexdigest()


def fetch_batters_for_date(date_str: str, session: requests.Session, delay: float) -> List[Dict]:
    """Fetch all batter stats for a single date from MLB Stats API."""
    schedule_url = f"{SCHEDULE_API}?date={date_str}&sportId=1&hydrate=linescore&gameTypes=R,P"
    resp = session.get(schedule_url, timeout=30)
    resp.raise_for_status()

    all_games = []
    for date_entry in resp.json().get("dates", []):
        all_games.extend(date_entry.get("games", []))

    final_games = [
        g for g in all_games
        if g.get("status", {}).get("detailedState") == "Final"
    ]

    if not final_games:
        return []

    now_iso = datetime.now(timezone.utc).isoformat()
    records = []

    for i, game in enumerate(final_games):
        game_pk = game.get("gamePk")
        if not game_pk:
            continue

        if i > 0:
            time.sleep(delay)

        feed_url = f"{GAME_FEED_API}/{game_pk}/feed/live"
        try:
            feed_resp = session.get(feed_url, timeout=30)
            feed_resp.raise_for_status()
            feed_data = feed_resp.json()
        except Exception as e:
            logger.warning("Failed game %s: %s", game_pk, e)
            continue

        game_data = feed_data.get("gameData", {})
        live_data = feed_data.get("liveData", {})
        teams_info = game_data.get("teams", {})
        home_abbr = teams_info.get("home", {}).get("abbreviation", "")
        away_abbr = teams_info.get("away", {}).get("abbreviation", "")
        game_date = game_data.get("datetime", {}).get("officialDate", date_str)
        season_year = int(game_date[:4]) if game_date else 0
        boxscore = live_data.get("boxscore", {})

        for side in ["home", "away"]:
            team_abbr = home_abbr if side == "home" else away_abbr
            opponent_abbr = away_abbr if side == "home" else home_abbr
            team_box = boxscore.get("teams", {}).get(side, {})
            players = team_box.get("players", {})
            batters_order = team_box.get("battingOrder", [])

            for order_idx, batter_id in enumerate(batters_order):
                player_key = f"ID{batter_id}"
                player_data = players.get(player_key, {})
                stats = player_data.get("stats", {}).get("batting", {})
                if not stats:
                    continue

                person = player_data.get("person", {})
                position = player_data.get("position", {})
                if position.get("code") == PITCHER_POSITION_CODE:
                    continue

                batting_order_raw = player_data.get("battingOrder")
                if batting_order_raw:
                    batting_order = int(str(batting_order_raw)[0])
                else:
                    batting_order = order_idx + 1

                player_name = person.get("fullName", "")
                strikeouts = stats.get("strikeOuts", 0)
                at_bats = stats.get("atBats", 0)
                hits = stats.get("hits", 0)
                walks = stats.get("baseOnBalls", 0)
                home_runs = stats.get("homeRuns", 0)
                rbis = stats.get("rbi", 0)
                runs = stats.get("runs", 0)
                k_rate = round(strikeouts / at_bats, 4) if at_bats > 0 else None

                row = {
                    "game_pk": game_pk,
                    "game_date": game_date,
                    "season_year": season_year,
                    "player_id": batter_id,
                    "player_name": player_name,
                    "player_lookup": normalize_name(player_name),
                    "team_abbr": team_abbr,
                    "opponent_abbr": opponent_abbr,
                    "home_away": side,
                    "batting_order": batting_order,
                    "strikeouts": strikeouts,
                    "at_bats": at_bats,
                    "hits": hits,
                    "walks": walks,
                    "home_runs": home_runs,
                    "rbis": rbis,
                    "runs": runs,
                    "k_rate": k_rate,
                    "source_file_path": f"backfill/{date_str}",
                    "data_hash": compute_hash({
                        "game_pk": game_pk, "player_id": batter_id,
                        "strikeouts": strikeouts, "at_bats": at_bats,
                        "hits": hits, "walks": walks,
                        "home_runs": home_runs, "rbis": rbis,
                    }),
                    "created_at": now_iso,
                    "processed_at": now_iso,
                }
                records.append(row)

    return records


def write_to_bq(client: bigquery.Client, records: List[Dict], game_date: str) -> int:
    """Write records to BQ, deleting existing data for the date first."""
    if not records:
        return 0

    # Delete existing data for this date
    try:
        delete_q = f"DELETE FROM `{TABLE_ID}` WHERE game_date = '{game_date}'"
        client.query(delete_q).result(timeout=60)
    except Exception as e:
        if "not found" not in str(e).lower():
            logger.warning("Delete failed for %s: %s", game_date, e)

    table = client.get_table(TABLE_ID)
    job_config = bigquery.LoadJobConfig(
        schema=table.schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_json(records, TABLE_ID, job_config=job_config)
    job.result(timeout=120)

    if job.errors:
        logger.error("BQ errors for %s: %s", game_date, job.errors[:3])
        return 0

    return len(records)


def get_existing_dates(client: bigquery.Client) -> set:
    """Get dates that already have data in mlbapi_batter_stats."""
    try:
        q = f"SELECT DISTINCT game_date FROM `{TABLE_ID}` WHERE game_date >= '2024-01-01'"
        result = client.query(q).result()
        return {str(row.game_date) for row in result}
    except Exception:
        return set()


def main():
    parser = argparse.ArgumentParser(description="Backfill mlbapi_batter_stats from MLB Stats API")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--sleep", type=float, default=0.3, help="Delay between game API calls (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't write to BQ")
    parser.add_argument("--skip-existing", action="store_true", help="Skip dates that already have data")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    client = None if args.dry_run else bigquery.Client(project=PROJECT_ID)
    existing_dates = set()
    if args.skip_existing and client:
        existing_dates = get_existing_dates(client)
        logger.info("Found %d dates with existing data", len(existing_dates))

    session = requests.Session()
    session.headers.update({"User-Agent": "mlb-batter-backfill/1.0", "Accept": "application/json"})

    total_dates = (end - start).days + 1
    total_records = 0
    dates_processed = 0
    dates_skipped = 0

    current = start
    while current <= end:
        date_str = current.isoformat()

        if date_str in existing_dates:
            dates_skipped += 1
            current += timedelta(days=1)
            continue

        try:
            records = fetch_batters_for_date(date_str, session, args.sleep)

            if records:
                if args.dry_run:
                    logger.info("[DRY RUN] %s: %d batters from %d games",
                               date_str, len(records),
                               len(set(r["game_pk"] for r in records)))
                else:
                    written = write_to_bq(client, records, date_str)
                    total_records += written
                    logger.info("%s: wrote %d batters (%d/%d dates)",
                               date_str, written, dates_processed + 1, total_dates)
            else:
                logger.info("%s: no final games", date_str)

            dates_processed += 1

        except Exception as e:
            logger.error("%s: FAILED - %s", date_str, e)

        # Brief delay between dates to be polite
        time.sleep(0.2)
        current += timedelta(days=1)

    logger.info("=" * 60)
    logger.info("Backfill complete: %d records across %d dates (%d skipped)",
                total_records, dates_processed, dates_skipped)


if __name__ == "__main__":
    main()
