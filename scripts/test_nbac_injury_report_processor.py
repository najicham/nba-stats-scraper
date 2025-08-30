#!/usr/bin/env python3
"""
File: scripts/test_nbac_injury_report_processor.py
Test NBA.com Injury Report processor with a specific file.
"""

import argparse
import json
import logging
import sys
import os
from google.cloud import storage

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processors.nbacom.nbac_injury_report_processor import NbacInjuryReportProcessor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_processor(gcs_file_path: str, load_to_bigquery: bool = False):
    """Test the processor with a specific file."""
    processor = NbacInjuryReportProcessor()
    
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
    metadata = data.get('metadata', {})
    logger.info(f"Report Date: {metadata.get('gamedate')}")
    logger.info(f"Report Hour: {metadata.get('hour24')} ({metadata.get('period', '')})")
    logger.info(f"Season: {metadata.get('season')}")
    
    # Show parsing stats
    stats = data.get('parsing_stats', {})
    logger.info(f"\nParsing Stats:")
    logger.info(f"  Total Records: {stats.get('total_records')}")
    logger.info(f"  Overall Confidence: {stats.get('overall_confidence', 0):.1%}")
    
    status_counts = stats.get('status_counts', {})
    if status_counts:
        logger.info(f"  Status Distribution:")
        for status, count in status_counts.items():
            logger.info(f"    {status}: {count}")
    
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
        logger.info("\nSample injury reports:")
        # Group by game
        games = {}
        for row in rows:
            game_key = f"{row['matchup']} ({row['game_time']})"
            if game_key not in games:
                games[game_key] = []
            games[game_key].append(row)
        
        # Show first 2 games
        for i, (game, players) in enumerate(list(games.items())[:2]):
            logger.info(f"\n  {game}:")
            for player in players[:3]:  # First 3 players per game
                logger.info(f"    - {player['player_full_name']} ({player['team']}): "
                          f"{player['injury_status'].upper()} - {player['reason_category']}")
    
    # Check for critical injuries (star players out)
    out_players = [r for r in rows if r['injury_status'] == 'out']
    if out_players:
        logger.info(f"\n⚠️  {len(out_players)} players OUT")
        for p in out_players[:5]:
            logger.info(f"  - {p['player_full_name']} ({p['team']}): {p['reason'][:50]}")
    
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
    parser = argparse.ArgumentParser(description='Test NBA.com Injury Report processor')
    parser.add_argument(
        '--gcs-file', 
        default='gs://nba-scraped-data/nba-com/injury-report-data/2021-11-23/12/20250829_071853.json',
        help='GCS file path'
    )
    parser.add_argument('--load', action='store_true', help='Load to BigQuery')
    args = parser.parse_args()
    
    test_processor(args.gcs_file, args.load)