#!/usr/bin/env python3
"""
Backfill MLB Schedule Table

Fetches historical MLB schedule data (2022-2025) and loads to BigQuery.
Uses the MLB Stats API which is free and cloud-friendly.

Usage:
    PYTHONPATH=. python scripts/mlb/backfill_mlb_schedule.py --year 2025
    PYTHONPATH=. python scripts/mlb/backfill_mlb_schedule.py --all
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# MLB season date ranges (Opening Day to end of regular season)
MLB_SEASONS = {
    2022: ("2022-04-07", "2022-10-05"),
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-28", "2024-09-29"),
    2025: ("2025-03-27", "2025-09-28"),
}

API_BASE = "https://statsapi.mlb.com/api/v1/schedule"
HYDRATE = "probablePitcher,team,venue,linescore"
PROJECT_ID = "nba-props-platform"
TABLE_ID = f"{PROJECT_ID}.mlb_raw.mlb_schedule"


def fetch_schedule_for_date_range(start_date: str, end_date: str, max_retries: int = 3) -> List[Dict]:
    """Fetch schedule from MLB Stats API for a date range with retry."""
    url = f"{API_BASE}?sportId=1&hydrate={HYDRATE}&startDate={start_date}&endDate={end_date}&gameTypes=R,P"

    logger.info(f"Fetching {start_date} to {end_date}")

    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 10
                logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                raise

    data = response.json()
    games = []

    for date_entry in data.get("dates", []):
        date_str = date_entry.get("date")
        for game in date_entry.get("games", []):
            transformed = transform_game(game, date_str)
            if transformed:
                games.append(transformed)

    return games


def transform_game(game: Dict, date_str: str) -> Optional[Dict]:
    """Transform a single game record."""
    game_pk = game.get("gamePk")
    if not game_pk:
        return None

    teams = game.get("teams", {})
    away = teams.get("away", {})
    home = teams.get("home", {})

    away_team = away.get("team", {})
    home_team = home.get("team", {})

    away_pitcher = away.get("probablePitcher", {})
    home_pitcher = home.get("probablePitcher", {})

    venue = game.get("venue", {})
    status = game.get("status", {})
    linescore = game.get("linescore", {})
    teams_linescore = linescore.get("teams", {})

    return {
        "game_pk": game_pk,
        "game_date": date_str,
        "game_time_utc": game.get("gameDate"),
        "season": game.get("season") or int(date_str[:4]),
        "game_type": game.get("gameType", "R"),

        "away_team_id": away_team.get("id"),
        "away_team_name": away_team.get("name", ""),
        "away_team_abbr": away_team.get("abbreviation", ""),
        "home_team_id": home_team.get("id"),
        "home_team_name": home_team.get("name", ""),
        "home_team_abbr": home_team.get("abbreviation", ""),

        "away_probable_pitcher_id": away_pitcher.get("id"),
        "away_probable_pitcher_name": away_pitcher.get("fullName"),
        "away_probable_pitcher_number": away_pitcher.get("primaryNumber"),
        "home_probable_pitcher_id": home_pitcher.get("id"),
        "home_probable_pitcher_name": home_pitcher.get("fullName"),
        "home_probable_pitcher_number": home_pitcher.get("primaryNumber"),

        "venue_id": venue.get("id"),
        "venue_name": venue.get("name"),
        "day_night": game.get("dayNight"),
        "series_description": game.get("seriesDescription"),
        "games_in_series": game.get("gamesInSeries"),
        "series_game_number": game.get("seriesGameNumber"),

        "status_code": status.get("statusCode"),
        "status_detailed": status.get("detailedState"),
        "is_final": status.get("statusCode") == "F",

        "away_score": teams_linescore.get("away", {}).get("runs"),
        "home_score": teams_linescore.get("home", {}).get("runs"),
        "away_hits": teams_linescore.get("away", {}).get("hits"),
        "home_hits": teams_linescore.get("home", {}).get("hits"),

        "source_file_path": f"backfill/{date_str}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def load_to_bigquery(games: List[Dict], year: int):
    """Load games to BigQuery using batch load."""
    if not games:
        logger.warning(f"No games to load for {year}")
        return

    client = bigquery.Client(project=PROJECT_ID)

    # Delete existing data for this year first
    delete_query = f"""
    DELETE FROM `{TABLE_ID}`
    WHERE EXTRACT(YEAR FROM game_date) = {year}
    """
    try:
        client.query(delete_query).result(timeout=120)
        logger.info(f"Deleted existing {year} data")
    except Exception as e:
        if "not found" not in str(e).lower():
            logger.warning(f"Delete failed: {e}")

    # Get table schema
    table = client.get_table(TABLE_ID)

    job_config = bigquery.LoadJobConfig(
        schema=table.schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )

    # Load in batches of 5000
    batch_size = 5000
    total_loaded = 0

    for i in range(0, len(games), batch_size):
        batch = games[i:i + batch_size]
        load_job = client.load_table_from_json(batch, TABLE_ID, job_config=job_config)
        load_job.result(timeout=300)
        total_loaded += len(batch)
        logger.info(f"Loaded batch {i//batch_size + 1}: {len(batch)} games (total: {total_loaded})")

    logger.info(f"✅ Loaded {total_loaded} games for {year}")


def backfill_year(year: int):
    """Backfill schedule for a single year."""
    if year not in MLB_SEASONS:
        logger.error(f"Unknown year: {year}")
        return

    start_date, end_date = MLB_SEASONS[year]
    logger.info(f"Backfilling {year} season: {start_date} to {end_date}")

    # Fetch in monthly chunks to avoid timeout
    from datetime import date, timedelta
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    all_games = []

    while current <= end:
        # Get 30-day chunks
        chunk_end = min(current + timedelta(days=30), end)

        games = fetch_schedule_for_date_range(
            current.isoformat(),
            chunk_end.isoformat()
        )
        all_games.extend(games)
        logger.info(f"  {current.isoformat()} to {chunk_end.isoformat()}: {len(games)} games")

        current = chunk_end + timedelta(days=1)
        time.sleep(0.5)  # Rate limiting

    logger.info(f"Total games fetched for {year}: {len(all_games)}")

    # Count games with pitchers
    with_pitchers = sum(
        1 for g in all_games
        if g.get('away_probable_pitcher_id') or g.get('home_probable_pitcher_id')
    )
    logger.info(f"Games with probable pitchers: {with_pitchers}")

    load_to_bigquery(all_games, year)


def main():
    parser = argparse.ArgumentParser(description='Backfill MLB Schedule')
    parser.add_argument('--year', type=int, help='Single year to backfill')
    parser.add_argument('--all', action='store_true', help='Backfill all years (2022-2025)')
    parser.add_argument('--dry-run', action='store_true', help='Fetch but do not load')

    args = parser.parse_args()

    if args.all:
        years = sorted(MLB_SEASONS.keys())
    elif args.year:
        years = [args.year]
    else:
        parser.print_help()
        sys.exit(1)

    for year in years:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing {year}")
        logger.info(f"{'='*50}")
        backfill_year(year)
        time.sleep(1)  # Rate limiting between years

    # Final count
    client = bigquery.Client(project=PROJECT_ID)
    result = client.query(f"SELECT COUNT(*) as cnt FROM `{TABLE_ID}`").result()
    total = list(result)[0].cnt
    logger.info(f"\n✅ Backfill complete. Total rows in mlb_schedule: {total}")


if __name__ == "__main__":
    main()
