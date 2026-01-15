#!/usr/bin/env python3
"""
Load BettingPros MLB Props from GCS to BigQuery

Reads JSON files from gs://nba-scraped-data/bettingpros-mlb/historical/
and loads them into mlb_raw.bp_pitcher_props table.

Usage:
    python scripts/mlb/load_bp_props_to_bigquery.py [--market pitcher-strikeouts] [--limit N]
"""

import os
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Optional
from google.cloud import bigquery, storage
from data_processors.raw.utils.name_utils import normalize_name

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

GCS_BUCKET = "nba-scraped-data"
GCS_PREFIX = "bettingpros-mlb/historical"
TABLE_ID = "nba-props-platform.mlb_raw.bp_pitcher_props"


def list_gcs_files(storage_client: storage.Client, market: str) -> List[str]:
    """List all JSON files for a given market in GCS."""
    bucket = storage_client.bucket(GCS_BUCKET)
    prefix = f"{GCS_PREFIX}/{market}/"

    files = []
    blobs = bucket.list_blobs(prefix=prefix)
    for blob in blobs:
        if blob.name.endswith('.json'):
            files.append(blob.name)

    return sorted(files)


def load_json_from_gcs(storage_client: storage.Client, blob_name: str) -> Optional[Dict]:
    """Load JSON content from GCS."""
    try:
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(blob_name)
        content = blob.download_as_string()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Error loading {blob_name}: {e}")
        return None


def transform_props(data: Dict, source_file: str) -> List[Dict]:
    """Transform BettingPros props JSON into BigQuery rows."""
    rows = []

    meta = data.get('meta', {})
    game_date = meta.get('date')
    market_id = meta.get('market_id')
    market_name = meta.get('market_name')

    if not game_date:
        logger.warning(f"No game_date in {source_file}")
        return []

    for prop in data.get('props', []):
        player_name = prop.get('player_name', '')
        player_lookup = normalize_name(player_name)

        row = {
            'game_date': game_date,
            'market_id': market_id,
            'market_name': market_name,
            'player_lookup': player_lookup,
            'player_name': player_name,
            'bp_player_id': str(prop.get('player_id', '')),
            'team': prop.get('team'),
            'position': prop.get('position'),
            'over_line': prop.get('over_line'),
            'over_odds': prop.get('over_odds'),
            'over_book_id': prop.get('over_book_id'),
            'over_consensus_line': prop.get('over_consensus_line'),
            'under_line': prop.get('under_line'),
            'under_odds': prop.get('under_odds'),
            'under_book_id': prop.get('under_book_id'),
            'under_consensus_line': prop.get('under_consensus_line'),
            'projection_value': prop.get('projection_value'),
            'projection_side': prop.get('projection_side'),
            'projection_ev': prop.get('projection_ev'),
            'projection_rating': prop.get('projection_rating'),
            'actual_value': prop.get('actual_value'),
            'is_scored': prop.get('is_scored'),
            'is_push': prop.get('is_push'),
            'perf_last_5_over': prop.get('perf_last_5_over'),
            'perf_last_5_under': prop.get('perf_last_5_under'),
            'perf_last_10_over': prop.get('perf_last_10_over'),
            'perf_last_10_under': prop.get('perf_last_10_under'),
            'perf_season_over': prop.get('perf_season_over'),
            'perf_season_under': prop.get('perf_season_under'),
            'opposing_pitcher': prop.get('opposing_pitcher'),
            'opposition_rank': prop.get('opposition_rank'),
            'event_id': prop.get('event_id'),
            'source_file_path': f"gs://{GCS_BUCKET}/{source_file}",
            'created_at': datetime.utcnow().isoformat(),
        }
        rows.append(row)

    return rows


def check_already_loaded(bq_client: bigquery.Client, source_file: str) -> bool:
    """Check if a file has already been loaded."""
    query = f"""
    SELECT COUNT(*) as cnt
    FROM `{TABLE_ID}`
    WHERE source_file_path = @source_file
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("source_file", "STRING", f"gs://{GCS_BUCKET}/{source_file}")
        ]
    )
    try:
        result = list(bq_client.query(query, job_config=job_config).result())
        return result[0].cnt > 0
    except Exception:
        return False


def load_to_bigquery(bq_client: bigquery.Client, rows: List[Dict]) -> int:
    """Load rows to BigQuery using batch loading."""
    if not rows:
        return 0

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ignore_unknown_values=True
    )

    try:
        load_job = bq_client.load_table_from_json(rows, TABLE_ID, job_config=job_config)
        load_job.result(timeout=120)

        if load_job.errors:
            logger.error(f"BigQuery errors: {load_job.errors[:3]}")
            return 0

        return len(rows)
    except Exception as e:
        logger.error(f"Load failed: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description='Load BettingPros MLB props to BigQuery')
    parser.add_argument('--market', default='pitcher-strikeouts', help='Market to load')
    parser.add_argument('--limit', type=int, help='Limit number of files to process')
    parser.add_argument('--skip-existing', action='store_true', default=True, help='Skip already loaded files')
    args = parser.parse_args()

    logger.info(f"Loading BettingPros {args.market} data to BigQuery")

    storage_client = storage.Client()
    bq_client = bigquery.Client()

    # List all files
    logger.info(f"Listing files from gs://{GCS_BUCKET}/{GCS_PREFIX}/{args.market}/")
    files = list_gcs_files(storage_client, args.market)
    logger.info(f"Found {len(files)} JSON files")

    if args.limit:
        files = files[:args.limit]
        logger.info(f"Limited to {args.limit} files")

    total_rows = 0
    files_processed = 0
    files_skipped = 0

    for i, blob_name in enumerate(files):
        if (i + 1) % 50 == 0:
            logger.info(f"Progress: {i + 1}/{len(files)} files ({files_processed} processed, {files_skipped} skipped)")

        # Skip if already loaded
        if args.skip_existing and check_already_loaded(bq_client, blob_name):
            files_skipped += 1
            continue

        # Load and transform
        data = load_json_from_gcs(storage_client, blob_name)
        if not data:
            continue

        rows = transform_props(data, blob_name)
        if not rows:
            continue

        # Load to BigQuery
        loaded = load_to_bigquery(bq_client, rows)
        total_rows += loaded
        files_processed += 1

    logger.info(f"\n=== RESULTS ===")
    logger.info(f"Files processed: {files_processed}")
    logger.info(f"Files skipped (already loaded): {files_skipped}")
    logger.info(f"Total rows loaded: {total_rows}")


if __name__ == '__main__':
    main()
