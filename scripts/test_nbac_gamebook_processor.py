#!/usr/bin/env python3
"""
File: scripts/test_nbac_gamebook_processor.py

Test script for NBA.com gamebook processor.
Use this to test processing of individual files before running full backfill.
"""

import argparse
import json
import logging
import sys
import os
from google.cloud import storage
from pprint import pprint

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from processors.nbacom.nbac_gamebook_processor import NbacGamebookProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_processor(gcs_file_path: str, load_to_bigquery: bool = False, verbose: bool = False):
    """Test the processor with a specific file.
    
    Args:
        gcs_file_path: Full GCS path like gs://bucket/path/to/file.json
        load_to_bigquery: Whether to actually load data to BigQuery
        verbose: Print detailed output
    """
    # Parse GCS path
    if not gcs_file_path.startswith('gs://'):
        logger.error("GCS path must start with gs://")
        return False
    
    path_parts = gcs_file_path[5:].split('/', 1)
    if len(path_parts) != 2:
        logger.error("Invalid GCS path format")
        return False
    
    bucket_name = path_parts[0]
    blob_path = path_parts[1]
    
    logger.info(f"Testing processor with file: {gcs_file_path}")
    
    # Initialize processor
    processor = NbacGamebookProcessor()
    
    # Download file
    logger.info("Downloading file from GCS...")
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    
    if not blob.exists():
        logger.error(f"File not found: {gcs_file_path}")
        return False
    
    content = blob.download_as_text()
    
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
        return False
    
    # Extract metadata from path
    logger.info("Extracting metadata from path...")
    opts = processor.extract_opts_from_path(blob_path)
    if verbose:
        print("\nExtracted metadata:")
        pprint(opts)
    
    # Validate data
    logger.info("Validating data structure...")
    errors = processor.validate_data(data)
    if errors:
        logger.error(f"Validation errors: {errors}")
        return False
    
    # Count players by type
    active_count = len(data.get('active_players', []))
    dnp_count = len(data.get('dnp_players', []))
    inactive_count = len(data.get('inactive_players', []))
    
    logger.info(f"Player counts: {active_count} active, {dnp_count} DNP, {inactive_count} inactive")
    
    # Transform data
    logger.info("Transforming data...")
    rows = processor.transform_data(data, blob_path)
    logger.info(f"Transformed {len(rows)} rows")
    
    if verbose and rows:
        print("\nSample transformed rows (first 3):")
        for i, row in enumerate(rows[:3], 1):
            print(f"\n--- Row {i} ---")
            print(f"Player: {row['player_name']} ({row['player_status']})")
            print(f"Team: {row['team_abbr']}")
            if row['player_status'] == 'active':
                print(f"Stats: {row['points']} pts, {row['total_rebounds']} reb, {row['assists']} ast")
            else:
                print(f"DNP Reason: {row['dnp_reason']}")
            if row.get('name_resolution_status'):
                print(f"Name Resolution: {row['name_resolution_status']}")
    
    # Check for name resolution issues
    resolution_issues = [r for r in rows if r.get('name_resolution_status') in ['multiple_matches', 'not_found']]
    if resolution_issues:
        logger.warning(f"Found {len(resolution_issues)} name resolution issues:")
        for issue in resolution_issues[:5]:
            logger.warning(f"  - {issue['player_name_original']} ({issue['team_abbr']}): {issue['name_resolution_status']}")
    
    # Load to BigQuery if requested
    if load_to_bigquery:
        logger.info("Loading data to BigQuery...")
        result = processor.load_data(rows)
        
        if result.get('errors'):
            logger.error(f"Load errors: {result['errors']}")
            return False
        else:
            logger.info(f"Successfully loaded {result['rows_processed']} rows to BigQuery")
    else:
        logger.info("Skipping BigQuery load (use --load to enable)")
    
    # Summary statistics
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    print(f"File: {gcs_file_path}")
    print(f"Game ID: {opts.get('game_id', 'Unknown')}")
    print(f"Date: {opts.get('game_date', 'Unknown')}")
    print(f"Teams: {opts.get('away_team_abbr', 'UNK')} @ {opts.get('home_team_abbr', 'UNK')}")
    print(f"Total rows: {len(rows)}")
    print(f"  - Active players: {len([r for r in rows if r['player_status'] == 'active'])}")
    print(f"  - DNP players: {len([r for r in rows if r['player_status'] == 'dnp'])}")
    print(f"  - Inactive players: {len([r for r in rows if r['player_status'] == 'inactive'])}")
    print(f"Name resolution issues: {len(resolution_issues)}")
    
    return True

def test_sample_data():
    """Test with sample data structure."""
    sample_data = {
        "game_code": "20231219/MEMNOP",
        "active_players": [{
            "name": "Ja Morant",
            "team": "Memphis Grizzlies",
            "status": "active",
            "stats": {
                "minutes": "34:46",
                "points": 34,
                "field_goals_made": 13,
                "field_goals_attempted": 22,
                "total_rebounds": 7,
                "assists": 8
            }
        }],
        "dnp_players": [{
            "name": "Derrick Rose",
            "team": "Memphis Grizzlies",
            "status": "did_not_play",
            "dnp_reason": "DNP - Injury/Illness - Left Hamstring; Strain"
        }],
        "inactive_players": [{
            "name": "Adams",
            "team": "Memphis Grizzlies",
            "status": "inactive",
            "reason": "Injury/Illness - Right Knee; PCL Surgery"
        }]
    }
    
    processor = NbacGamebookProcessor()
    
    # Test with sample path
    sample_path = "nba-com/gamebooks-data/2023-12-19/20231219-MEMNOP"
    
    print("Testing with sample data...")
    print("Validating...")
    errors = processor.validate_data(sample_data)
    if errors:
        print(f"Validation errors: {errors}")
        return False
    
    print("Transforming...")
    rows = processor.transform_data(sample_data, sample_path)
    print(f"Generated {len(rows)} rows")
    
    for row in rows:
        print(f"  - {row['player_name']} ({row['player_status']})")
    
    return True

def main():
    parser = argparse.ArgumentParser(description='Test NBA.com gamebook processor')
    parser.add_argument('--gcs-file', 
                       help='GCS file path (e.g., gs://bucket/path/file.json)')
    parser.add_argument('--load', 
                       action='store_true',
                       help='Load transformed data to BigQuery')
    parser.add_argument('--verbose', 
                       action='store_true',
                       help='Show detailed output')
    parser.add_argument('--sample', 
                       action='store_true',
                       help='Test with sample data (no GCS required)')
    
    args = parser.parse_args()
    
    if args.sample:
        success = test_sample_data()
    elif args.gcs_file:
        success = test_processor(args.gcs_file, args.load, args.verbose)
    else:
        parser.print_help()
        sys.exit(1)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()