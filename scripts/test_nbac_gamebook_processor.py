#!/usr/bin/env python3
"""
File: scripts/test_nbac_gamebook_processor.py

Test the NBA.com Gamebook processor with sample files.
"""

import sys
import os
import argparse
import json
import logging
from google.cloud import storage

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from processors.nbacom.nbac_gamebook_processor import NbacGamebookProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_processor(gcs_file_path: str, load_to_bigquery: bool = False):
    """Test the processor with a specific file."""
    processor = NbacGamebookProcessor()
    storage_client = storage.Client()
    
    # Parse GCS path
    parts = gcs_file_path.replace('gs://', '').split('/')
    bucket_name = parts[0]
    file_path = '/'.join(parts[1:])
    
    # Download file
    logger.info(f"Downloading {gcs_file_path}")
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    content = blob.download_as_text()
    
    # Parse JSON
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Try eval for dict-like strings
        data = eval(content)
    
    # Validate
    logger.info("Validating data...")
    errors = processor.validate_data(data)
    if errors:
        logger.error(f"Validation errors: {errors}")
        return
    
    # Transform
    logger.info("Transforming data...")
    rows = processor.transform_data(data, file_path)
    
    logger.info(f"Transformed {len(rows)} rows:")
    
    # Show sample data
    for i, row in enumerate(rows[:3]):
        logger.info(f"Row {i+1}:")
        logger.info(f"  Player: {row['player_name']} ({row['player_status']})")
        logger.info(f"  Team: {row['team_abbr']}")
        if row['player_status'] == 'active':
            logger.info(f"  Stats: {row['points']} pts, {row['minutes']} min")
        else:
            logger.info(f"  Reason: {row['dnp_reason']}")
        if row['name_resolution_status'] != 'original':
            logger.info(f"  Name resolution: {row['name_resolution_status']}")
    
    if len(rows) > 3:
        logger.info(f"... and {len(rows) - 3} more rows")
    
    # Load to BigQuery if requested
    if load_to_bigquery:
        logger.info("Loading to BigQuery...")
        result = processor.load_data(rows)
        if result['errors']:
            logger.error(f"Load errors: {result['errors']}")
        else:
            logger.info(f"Successfully loaded {result['rows_processed']} rows")
    else:
        logger.info("Skipping BigQuery load (use --load to enable)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test NBA.com Gamebook processor')
    parser.add_argument('--gcs-file', required=True, 
                       help='GCS file path (e.g., gs://nba-scraped-data/nba-com/gamebooks-data/2021-10-19/20211019-BKNMIL.json)')
    parser.add_argument('--load', action='store_true', 
                       help='Load data to BigQuery')
    
    args = parser.parse_args()
    test_processor(args.gcs_file, args.load)