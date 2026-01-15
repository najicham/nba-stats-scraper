#!/usr/bin/env python3
"""
Backfill Pitcher Splits Data

Fetches splits data (home/away, day/night) for all pitchers with BDL player IDs.
Stores results in BigQuery for feature population.

Usage:
    python scripts/mlb/backfill_pitcher_splits.py [--dry-run] [--limit N] [--seasons 2024,2025]
"""

import os
import sys
import json
import time
import logging
import argparse
from typing import Dict, List, Optional
from datetime import datetime
import requests
from google.cloud import bigquery

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# BDL API config
BDL_API_KEY = os.environ.get('BDL_API_KEY', '')
BDL_MLB_API_ROOT = 'https://api.balldontlie.io/mlb/v1'


def get_pitchers_with_bdl_ids(client: bigquery.Client, limit: Optional[int] = None) -> List[Dict]:
    """Get pitchers that have BDL player IDs from registry."""
    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
    SELECT DISTINCT
        r.player_lookup,
        r.player_full_name,
        r.bdl_player_id,
        r.team_abbr
    FROM `nba-props-platform.mlb_reference.mlb_players_registry` r
    WHERE r.bdl_player_id IS NOT NULL
      AND r.player_type = 'PITCHER'
    ORDER BY r.player_lookup
    {limit_clause}
    """

    result = client.query(query).result()
    return [dict(row) for row in result]


def fetch_splits(bdl_player_id: int, season: int, api_key: str) -> Optional[Dict]:
    """Fetch splits data from BDL API."""
    headers = {'Authorization': api_key}
    url = f"{BDL_MLB_API_ROOT}/players/splits"

    try:
        resp = requests.get(
            url,
            headers=headers,
            params={'player_id': bdl_player_id, 'season': season},
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    except Exception as e:
        logger.warning(f"Error fetching splits for player {bdl_player_id} season {season}: {e}")
        return None


def parse_splits(raw_data: Dict) -> Dict:
    """Parse splits data into structured format."""
    splits_data = raw_data.get("data", {})
    by_breakdown = splits_data.get("byBreakdown", []) if isinstance(splits_data, dict) else []

    # Find Home/Away/Day/Night splits
    home_split = None
    away_split = None
    day_split = None
    night_split = None

    for split in by_breakdown:
        split_name = split.get("split_name", "").lower()
        if split_name == "home":
            home_split = split
        elif split_name == "away":
            away_split = split
        elif split_name == "day":
            day_split = split
        elif split_name == "night":
            night_split = split

    # Calculate K/9 for each split
    def calc_k_per_9(split_data: dict) -> Optional[float]:
        if not split_data:
            return None
        ip = split_data.get("innings_pitched", 0)
        so = split_data.get("strikeouts_pitched", 0)
        try:
            ip_float = float(ip) if ip else 0
            return round((so / ip_float * 9), 2) if ip_float > 0 else None
        except (ValueError, TypeError):
            return None

    home_k_per_9 = calc_k_per_9(home_split)
    away_k_per_9 = calc_k_per_9(away_split)
    day_k_per_9 = calc_k_per_9(day_split)
    night_k_per_9 = calc_k_per_9(night_split)

    # Calculate diffs
    home_away_k_diff = None
    if home_k_per_9 is not None and away_k_per_9 is not None:
        home_away_k_diff = round(home_k_per_9 - away_k_per_9, 2)

    day_night_k_diff = None
    if day_k_per_9 is not None and night_k_per_9 is not None:
        day_night_k_diff = round(day_k_per_9 - night_k_per_9, 2)

    return {
        'home_k_per_9': home_k_per_9,
        'away_k_per_9': away_k_per_9,
        'home_away_k_diff': home_away_k_diff,
        'day_k_per_9': day_k_per_9,
        'night_k_per_9': night_k_per_9,
        'day_night_k_diff': day_night_k_diff,
        # Additional stats
        'home_innings': home_split.get('innings_pitched') if home_split else None,
        'home_strikeouts': home_split.get('strikeouts_pitched') if home_split else None,
        'home_era': home_split.get('era') if home_split else None,
        'away_innings': away_split.get('innings_pitched') if away_split else None,
        'away_strikeouts': away_split.get('strikeouts_pitched') if away_split else None,
        'away_era': away_split.get('era') if away_split else None,
    }


def save_splits_to_bigquery(
    client: bigquery.Client,
    splits_records: List[Dict],
    dry_run: bool = False
) -> int:
    """Save splits data to BigQuery."""
    if not splits_records:
        return 0

    if dry_run:
        logger.info(f"DRY RUN: Would save {len(splits_records)} splits records")
        return len(splits_records)

    table_id = "nba-props-platform.mlb_raw.bdl_pitcher_splits"

    # Create table if not exists
    schema = [
        bigquery.SchemaField("player_lookup", "STRING"),
        bigquery.SchemaField("bdl_player_id", "INT64"),
        bigquery.SchemaField("season", "INT64"),
        bigquery.SchemaField("home_k_per_9", "FLOAT64"),
        bigquery.SchemaField("away_k_per_9", "FLOAT64"),
        bigquery.SchemaField("home_away_k_diff", "FLOAT64"),
        bigquery.SchemaField("day_k_per_9", "FLOAT64"),
        bigquery.SchemaField("night_k_per_9", "FLOAT64"),
        bigquery.SchemaField("day_night_k_diff", "FLOAT64"),
        bigquery.SchemaField("home_innings", "FLOAT64"),
        bigquery.SchemaField("home_strikeouts", "INT64"),
        bigquery.SchemaField("home_era", "FLOAT64"),
        bigquery.SchemaField("away_innings", "FLOAT64"),
        bigquery.SchemaField("away_strikeouts", "INT64"),
        bigquery.SchemaField("away_era", "FLOAT64"),
        bigquery.SchemaField("scraped_at", "TIMESTAMP"),
    ]

    try:
        table = bigquery.Table(table_id, schema=schema)
        table = client.create_table(table, exists_ok=True)
    except Exception as e:
        logger.warning(f"Table creation note: {e}")

    # Prepare rows
    rows = []
    for record in splits_records:
        rows.append({
            'player_lookup': record['player_lookup'],
            'bdl_player_id': record['bdl_player_id'],
            'season': record['season'],
            'home_k_per_9': record.get('home_k_per_9'),
            'away_k_per_9': record.get('away_k_per_9'),
            'home_away_k_diff': record.get('home_away_k_diff'),
            'day_k_per_9': record.get('day_k_per_9'),
            'night_k_per_9': record.get('night_k_per_9'),
            'day_night_k_diff': record.get('day_night_k_diff'),
            'home_innings': float(record['home_innings']) if record.get('home_innings') else None,
            'home_strikeouts': record.get('home_strikeouts'),
            'home_era': record.get('home_era'),
            'away_innings': float(record['away_innings']) if record.get('away_innings') else None,
            'away_strikeouts': record.get('away_strikeouts'),
            'away_era': record.get('away_era'),
            'scraped_at': datetime.utcnow().isoformat(),
        })

    errors = client.insert_rows_json(table_id, rows)
    if errors:
        logger.error(f"Error inserting rows: {errors[:5]}")
        return 0

    logger.info(f"Saved {len(rows)} splits records to BigQuery")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description='Backfill pitcher splits data')
    parser.add_argument('--dry-run', action='store_true', help='Do not save to database')
    parser.add_argument('--limit', type=int, help='Limit number of pitchers to process')
    parser.add_argument('--seasons', default='2024,2025', help='Comma-separated seasons')
    parser.add_argument('--delay', type=float, default=0.2, help='Delay between API calls (seconds)')
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get('BDL_API_KEY', '')
    if not api_key:
        logger.error("BDL_API_KEY environment variable not set")
        sys.exit(1)

    seasons = [int(s.strip()) for s in args.seasons.split(',')]

    logger.info(f"Starting pitcher splits backfill for seasons: {seasons}")

    # Initialize BigQuery client
    client = bigquery.Client()

    # Get pitchers with BDL IDs
    logger.info("Fetching pitchers with BDL IDs from registry...")
    pitchers = get_pitchers_with_bdl_ids(client, args.limit)
    logger.info(f"Found {len(pitchers)} pitchers with BDL IDs")

    if not pitchers:
        logger.error("No pitchers with BDL IDs found. Run build_bdl_player_mapping.py first.")
        sys.exit(1)

    # Process each pitcher for each season
    splits_records = []
    success_count = 0
    error_count = 0

    total_requests = len(pitchers) * len(seasons)
    logger.info(f"Processing {total_requests} pitcher-season combinations...")

    for i, pitcher in enumerate(pitchers):
        player_lookup = pitcher['player_lookup']
        bdl_player_id = pitcher['bdl_player_id']

        for season in seasons:
            if (i * len(seasons) + seasons.index(season) + 1) % 100 == 0:
                logger.info(f"Progress: {i * len(seasons) + seasons.index(season) + 1}/{total_requests}")

            # Fetch splits
            raw_data = fetch_splits(bdl_player_id, season, api_key)

            if raw_data:
                parsed = parse_splits(raw_data)
                parsed['player_lookup'] = player_lookup
                parsed['bdl_player_id'] = bdl_player_id
                parsed['season'] = season
                splits_records.append(parsed)
                success_count += 1
            else:
                error_count += 1

            # Rate limiting
            time.sleep(args.delay)

    # Report results
    logger.info(f"\n=== RESULTS ===")
    logger.info(f"Success: {success_count}/{total_requests}")
    logger.info(f"Errors: {error_count}")

    # Sample output
    if splits_records:
        logger.info(f"\nSample splits data (first 5):")
        for record in splits_records[:5]:
            logger.info(
                f"  {record['player_lookup']} ({record['season']}): "
                f"home_away_diff={record.get('home_away_k_diff')}, "
                f"day_night_diff={record.get('day_night_k_diff')}"
            )

    # Save to BigQuery
    saved = save_splits_to_bigquery(client, splits_records, args.dry_run)
    logger.info(f"Saved {saved} records to BigQuery")

    # Save ALL records to JSON (for backup/debugging)
    summary = {
        'timestamp': datetime.now().isoformat(),
        'seasons': seasons,
        'pitchers_processed': len(pitchers),
        'success_count': success_count,
        'error_count': error_count,
        'records_saved': saved,
        'all_records': splits_records,  # Save ALL records
    }

    output_path = 'scripts/mlb/splits_backfill_results.json'
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary saved to {output_path}")


if __name__ == '__main__':
    main()
