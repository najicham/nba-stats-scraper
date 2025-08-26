#!/usr/bin/env python3
"""
File: scripts/test_odds_api_props_processor.py

Test script for Odds API props processor.
Use this to validate processor logic before running backfill.
"""

import argparse
import json
import logging
from google.cloud import storage
from processors.oddsapi.odds_api_props_processor import OddsApiPropsProcessor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_processor(gcs_file_path: str, load_to_bigquery: bool = False):
    """Test the Odds API props processor with a specific file."""
    
    # Initialize processor
    processor = OddsApiPropsProcessor()
    
    # Parse GCS path
    if not gcs_file_path.startswith('gs://'):
        logger.error("File path must start with gs://")
        return
    
    # Download file from GCS
    storage_client = storage.Client()
    path_parts = gcs_file_path.replace('gs://', '').split('/', 1)
    bucket_name = path_parts[0]
    blob_path = path_parts[1]
    
    logger.info(f"Downloading from bucket: {bucket_name}")
    logger.info(f"Blob path: {blob_path}")
    
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    
    if not blob.exists():
        logger.error(f"File not found: {gcs_file_path}")
        return
    
    # Read and parse JSON
    json_content = blob.download_as_text()
    data = json.loads(json_content)
    
    # Process the data
    logger.info(f"Processing {gcs_file_path}")
    
    # Show sample of raw data
    logger.info("Raw data sample:")
    if 'data' in data:
        game_data = data['data']
        logger.info(f"  Event ID: {game_data.get('id')}")
        logger.info(f"  Home Team: {game_data.get('home_team')}")
        logger.info(f"  Away Team: {game_data.get('away_team')}")
        logger.info(f"  Commence Time: {game_data.get('commence_time')}")
        logger.info(f"  Bookmakers: {len(game_data.get('bookmakers', []))}")
    
    # Validate
    errors = processor.validate_data(data)
    if errors:
        logger.error(f"Validation errors: {errors}")
        return
    else:
        logger.info("✓ Data validation passed")
    
    # Transform
    rows = processor.transform_data(data, gcs_file_path)
    logger.info(f"✓ Transformed {len(rows)} rows")
    
    # Show statistics
    if rows:
        bookmakers = set(r['bookmaker'] for r in rows)
        players = set(r['player_name'] for r in rows)
        
        logger.info("\nTransformation Statistics:")
        logger.info(f"  Total records: {len(rows)}")
        logger.info(f"  Unique players: {len(players)}")
        logger.info(f"  Bookmakers: {', '.join(sorted(bookmakers))}")
        logger.info(f"  Game ID: {rows[0]['game_id']}")
        logger.info(f"  Minutes before tipoff: {rows[0]['minutes_before_tipoff']}")
        
        # Show sample rows
        logger.info("\nSample transformed rows (first 3):")
        for i, row in enumerate(rows[:3], 1):
            logger.info(f"\n  Row {i}:")
            logger.info(f"    Player: {row['player_name']} ({row['player_lookup']})")
            logger.info(f"    Bookmaker: {row['bookmaker']}")
            logger.info(f"    Points Line: {row['points_line']}")
            logger.info(f"    Over: {row['over_price']} ({row['over_price_american']:+d})")
            logger.info(f"    Under: {row['under_price']} ({row['under_price_american']:+d})")
            logger.info(f"    Snapshot: {row['snapshot_timestamp']}")
            logger.info(f"    Minutes before tipoff: {row['minutes_before_tipoff']}")
        
        # Full JSON output of first row for debugging
        logger.info("\nFull first row (JSON format):")
        print(json.dumps(rows[0], indent=2, default=str))
    
    # Load to BigQuery (optional)
    if load_to_bigquery:
        logger.info("\nLoading to BigQuery...")
        result = processor.load_data(rows)
        if result['errors']:
            logger.error(f"Load errors: {result['errors']}")
        else:
            logger.info(f"✓ Successfully loaded {result['rows_processed']} rows to BigQuery")
            
            # Show table name
            logger.info(f"  Table: {processor.project_id}.{processor.table_name}")
    else:
        logger.info("\nDry run complete. Use --load flag to actually load to BigQuery")


def main():
    parser = argparse.ArgumentParser(description='Test Odds API Props Processor')
    parser.add_argument(
        '--gcs-file', 
        required=True, 
        help='GCS file path to process (e.g., gs://bucket/path/to/file.json)'
    )
    parser.add_argument(
        '--load', 
        action='store_true', 
        help='Actually load to BigQuery (default: dry run only)'
    )
    
    args = parser.parse_args()
    
    try:
        test_processor(args.gcs_file, args.load)
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        exit(1)


if __name__ == "__main__":
    main()
    