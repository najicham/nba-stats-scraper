#!/usr/bin/env python3
"""
File: scripts/test_bdl_injuries_processor.py
Test Ball Don't Lie Injuries processor with a specific file.
"""

import argparse
import json
import logging
import sys
import os
from google.cloud import storage

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_processors.raw.balldontlie.bdl_injuries_processor import BdlInjuriesProcessor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_processor(gcs_file_path: str, load_to_bigquery: bool = False):
    """Test the processor with a specific file."""
    processor = BdlInjuriesProcessor()

    # Parse GCS path
    if not gcs_file_path.startswith('gs://'):
        logger.error("GCS path must start with gs://")
        return

    # Extract bucket and blob path
    path_parts = gcs_file_path.replace('gs://', '').split('/', 1)
    bucket_name = path_parts[0]
    blob_name = path_parts[1]

    logger.info(f"Processing file: {gcs_file_path}")

    # Download file from GCS
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    json_content = blob.download_as_text()
    data = json.loads(json_content)

    # Show metadata
    logger.info(f"Timestamp: {data.get('timestamp')}")
    logger.info(f"Row Count: {data.get('rowCount')}")
    logger.info(f"Ident: {data.get('ident')}")

    # Validate data
    errors = processor.validate_data(data)
    if errors:
        logger.error(f"Validation errors: {errors}")
        return

    logger.info("✓ Data validation passed")

    # Transform data
    rows = processor.transform_data(data, gcs_file_path)
    logger.info(f"✓ Transformed {len(rows)} injury records")

    # Show sample data
    if rows:
        logger.info("\nSample injury records:")
        for row in rows[:5]:
            logger.info(f"  - {row['player_full_name']} ({row['team_abbr']}): "
                       f"{row['injury_status_normalized'].upper()} - {row['reason_category']}")

        # Show quality metrics
        avg_confidence = sum(r['parsing_confidence'] for r in rows) / len(rows)
        with_flags = sum(1 for r in rows if r['data_quality_flags'])
        logger.info(f"\nQuality Metrics:")
        logger.info(f"  Avg Confidence: {avg_confidence:.3f}")
        logger.info(f"  Records with Flags: {with_flags}/{len(rows)}")

    # Load to BigQuery if requested
    if load_to_bigquery:
        logger.info("\nLoading to BigQuery...")
        result = processor.load_data(rows)
        if result['errors']:
            logger.error(f"Load errors: {result['errors']}")
        else:
            logger.info(f"✓ Successfully loaded {result['rows_processed']} rows to BigQuery")
    else:
        logger.info("\nDry run complete. Use --load flag to write to BigQuery")

    return rows

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test BDL Injuries processor')
    parser.add_argument(
        '--gcs-file',
        help='GCS file path (e.g., gs://nba-scraped-data/ball-dont-lie/injuries/2025-10-18/20251019_001753.json)'
    )
    parser.add_argument('--load', action='store_true', help='Load to BigQuery')
    args = parser.parse_args()

    # Use the file we just scraped if not specified
    if not args.gcs_file:
        args.gcs_file = 'gs://nba-scraped-data/ball-dont-lie/injuries/2025-10-18/20251019_001753.json'

    test_processor(args.gcs_file, args.load)
