#!/usr/bin/env python3
"""
Backfill MLB umpire assignments for historical dates.

Uses the MLB Stats API schedule endpoint with officials hydration
to scrape umpire assignments for a date range. Processes and loads
into mlb_raw.mlb_umpire_assignments via the standard processor.

Session 465: Enables umpire signal validation against historical replays.

Usage:
    # Backfill 2025 season
    PYTHONPATH=. python scripts/mlb/backfill_umpire_assignments.py \
        --start-date 2025-03-27 --end-date 2025-10-02

    # Dry run (don't write to BQ)
    PYTHONPATH=. python scripts/mlb/backfill_umpire_assignments.py \
        --start-date 2025-03-27 --end-date 2025-04-15 --dry-run

    # Single date
    PYTHONPATH=. python scripts/mlb/backfill_umpire_assignments.py \
        --start-date 2025-06-15 --end-date 2025-06-15
"""

import argparse
import json
import logging
import os
import time
from datetime import date, datetime, timedelta

import requests
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
TABLE_ID = f'{PROJECT_ID}.mlb_raw.mlb_umpire_assignments'

MLB_SCHEDULE_URL = 'https://statsapi.mlb.com/api/v1/schedule'


def fetch_umpire_assignments(game_date: date) -> list:
    """Fetch umpire assignments from MLB Stats API for a single date."""
    params = {
        'date': game_date.isoformat(),
        'sportId': 1,
        'hydrate': 'officials',
    }
    resp = requests.get(MLB_SCHEDULE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    records = []
    for date_entry in data.get('dates', []):
        for game in date_entry.get('games', []):
            game_pk = game.get('gamePk')
            game_dt = game.get('gameDate', '')
            home = game.get('teams', {}).get('home', {}).get('team', {})
            away = game.get('teams', {}).get('away', {}).get('team', {})

            # Find home plate umpire
            for official in game.get('officials', []):
                if official.get('officialType') == 'Home Plate':
                    umpire = official.get('official', {})
                    now_ts = datetime.now(tz=None).isoformat()
                    records.append({
                        'game_date': game_date.isoformat(),
                        'game_pk': game_pk,
                        'umpire_name': umpire.get('fullName', ''),
                        'umpire_id': umpire.get('id'),
                        'home_team_abbr': home.get('abbreviation', ''),
                        'away_team_abbr': away.get('abbreviation', ''),
                        'source_file_path': f'backfill/umpire_assignments/{game_date.isoformat()}',
                        'created_at': now_ts,
                        'processed_at': now_ts,
                    })
                    break

    return records


def backfill_range(start: date, end: date, dry_run: bool = False):
    """Backfill umpire assignments for a date range."""
    client = bigquery.Client(project=PROJECT_ID) if not dry_run else None

    current = start
    total_records = 0
    total_days = 0
    errors = []

    while current <= end:
        try:
            records = fetch_umpire_assignments(current)
            total_records += len(records)
            total_days += 1

            if records:
                if dry_run:
                    logger.info(f'{current}: {len(records)} umpire assignments (dry run)')
                else:
                    # Delete existing for this date, then insert
                    try:
                        delete_q = f"DELETE FROM `{TABLE_ID}` WHERE game_date = '{current.isoformat()}'"
                        client.query(delete_q).result(timeout=30)
                    except Exception:
                        pass  # Table may not exist yet or no rows

                    job_config = bigquery.LoadJobConfig(
                        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    )
                    job = client.load_table_from_json(records, TABLE_ID, job_config=job_config)
                    job.result(timeout=60)
                    logger.info(f'{current}: {len(records)} umpire assignments loaded')
            else:
                logger.debug(f'{current}: no games')

        except Exception as e:
            logger.error(f'{current}: ERROR — {e}')
            errors.append((current, str(e)))

        current += timedelta(days=1)
        time.sleep(0.2)  # Be polite to MLB API

    logger.info(f'Done: {total_days} days, {total_records} records, {len(errors)} errors')
    if errors:
        for d, e in errors[:10]:
            logger.warning(f'  Failed: {d} — {e}')


def main():
    parser = argparse.ArgumentParser(description='Backfill MLB umpire assignments')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Fetch but do not write to BQ')
    args = parser.parse_args()

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)

    logger.info(f'Backfilling umpire assignments: {start} to {end} (dry_run={args.dry_run})')
    backfill_range(start, end, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
