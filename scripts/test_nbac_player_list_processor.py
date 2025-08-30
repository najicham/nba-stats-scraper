#!/usr/bin/env python3
"""
File: scripts/test_nbac_player_list_processor.py
Test NBA.com Player List processor with a specific file.
"""

import argparse
import json
import logging
import sys
import os
from google.cloud import storage

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processors.nbacom.nbac_player_list_processor import NbacPlayerListProcessor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_processor(gcs_file_path: str, load_to_bigquery: bool = False):
    """Test the processor with a specific file."""
    processor = NbacPlayerListProcessor()
    
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
    
    # Validate data
    errors = processor.validate_data(data)
    if errors:
        logger.error(f"Validation errors: {errors}")
        return
    
    logger.info("✓ Data validation passed")
    
    # Transform data
    rows = processor.transform_data(data, gcs_file_path)
    logger.info(f"✓ Transformed {len(rows)} player records")
    
    # Show sample data
    if rows:
        logger.info("\nSample players:")
        for row in rows[:5]:
            logger.info(f"  - {row['player_full_name']} ({row['team_abbr']}) -> {row['player_lookup']}")
    
    # Check for duplicates
    lookups = [row['player_lookup'] for row in rows]
    duplicates = [x for x in lookups if lookups.count(x) > 1]
    if duplicates:
        logger.warning(f"Found duplicate player_lookups: {set(duplicates)}")
    
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
    parser = argparse.ArgumentParser(description='Test NBA.com Player List processor')
    parser.add_argument(
        '--gcs-file', 
        default='gs://nba-scraped-data/nba-com/player-list/2025-08-21/20250822_030045.json',
        help='GCS file path'
    )
    parser.add_argument('--load', action='store_true', help='Load to BigQuery')
    args = parser.parse_args()
    
    test_processor(args.gcs_file, args.load)