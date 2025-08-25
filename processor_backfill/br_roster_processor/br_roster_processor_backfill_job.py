#!/usr/bin/env python3
"""
Basketball Reference Roster Processor Backfill Job
Processes historical roster data from GCS.
Matches the scraper backfill job patterns.
"""

import os
import sys
import logging
import argparse
from datetime import datetime
from google.cloud import storage
from typing import List, Dict

# Add parent directories to path (matching scraper pattern)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.basketball_ref.br_roster_processor import BasketballRefRosterProcessor

# Configure logging (matching scraper pattern)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# NBA team abbreviations (matching scrapers)
NBA_TEAMS = [
    "ATL", "BOS", "BRK", "CHO", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
]


def get_roster_files(bucket_name: str, season_year: int, teams: List[str]) -> List[str]:
    """
    Find roster files in GCS for given season and teams.
    Path pattern: basketball_reference/season_rosters/{season}/{team}.json
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    # Build season string (e.g., 2023 -> "2023-24")
    season_str = f"{season_year}-{str(season_year + 1)[2:]}"
    prefix = f"basketball_reference/season_rosters/{season_str}/"
    
    files = []
    blobs = bucket.list_blobs(prefix=prefix)
    
    for blob in blobs:
        # Check if this team is in our list
        if teams == ["all"] or any(f"/{team}." in blob.name for team in teams):
            files.append(blob.name)
            logger.info(f"Found file: {blob.name}")
    
    return sorted(files)


def process_roster_file(processor: BasketballRefRosterProcessor, 
                       bucket_name: str, 
                       file_path: str,
                       season_year: int) -> Dict:
    """Process a single roster file."""
    
    # Extract team from file path
    # Path like: basketball_reference/season_rosters/2023-24/LAL.json
    team_abbrev = file_path.split("/")[-1].replace(".json", "")
    
    opts = {
        "season_year": season_year,
        "team_abbrev": team_abbrev,
        "file_path": file_path,
        "bucket": bucket_name,
        "project_id": os.environ.get("GCP_PROJECT_ID", "nba-props-platform")
    }
    
    logger.info(f"Processing {team_abbrev} for {season_year} season")
    
    try:
        success = processor.run(opts)
        stats = processor.get_processor_stats()
        
        return {
            "file": file_path,
            "team": team_abbrev,
            "status": "success" if success else "failed",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Error processing {file_path}: {e}")
        return {
            "file": file_path,
            "team": team_abbrev,
            "status": "error",
            "error": str(e)
        }


def main():
    """Main backfill function."""
    parser = argparse.ArgumentParser(
        description='Backfill Basketball Reference roster data'
    )
    parser.add_argument(
        '--season', 
        type=int, 
        required=True,
        help='Season year (e.g., 2023 for 2023-24 season)'
    )
    parser.add_argument(
        '--teams', 
        nargs='+', 
        default=['all'],
        help='Team abbreviations or "all" (default: all)'
    )
    parser.add_argument(
        '--bucket', 
        default='nba-scraped-data',
        help='GCS bucket name (default: nba-scraped-data)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='List files without processing'
    )
    
    args = parser.parse_args()
    
    # Validate teams
    if args.teams != ['all']:
        invalid_teams = [t for t in args.teams if t not in NBA_TEAMS]
        if invalid_teams:
            logger.error(f"Invalid teams: {invalid_teams}")
            logger.info(f"Valid teams: {NBA_TEAMS}")
            sys.exit(1)
    
    # Get project ID
    project_id = os.environ.get('GCP_PROJECT_ID')
    if not project_id:
        logger.error("GCP_PROJECT_ID environment variable not set")
        sys.exit(1)
    
    logger.info(f"Starting backfill for season {args.season}")
    logger.info(f"Teams: {args.teams}")
    logger.info(f"Bucket: {args.bucket}")
    logger.info(f"Project: {project_id}")
    
    # Find files to process
    files = get_roster_files(args.bucket, args.season, args.teams)
    
    if not files:
        logger.warning(f"No files found for season {args.season}")
        sys.exit(0)
    
    logger.info(f"Found {len(files)} files to process")
    
    if args.dry_run:
        logger.info("DRY RUN - Files that would be processed:")
        for f in files:
            print(f"  - {f}")
        sys.exit(0)
    
    # Process files
    processor = BasketballRefRosterProcessor()
    results = []
    
    for i, file_path in enumerate(files, 1):
        logger.info(f"Processing file {i}/{len(files)}: {file_path}")
        result = process_roster_file(processor, args.bucket, file_path, args.season)
        results.append(result)
        
        # Log progress
        if result["status"] == "success":
            logger.info(f"✓ {result['team']}: {result['stats']}")
        else:
            logger.error(f"✗ {result['team']}: {result.get('error', 'Failed')}")
    
    # Summary
    successful = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] != "success")
    
    logger.info("")
    logger.info("=" * 50)
    logger.info(f"Backfill Complete for Season {args.season}")
    logger.info(f"Successful: {successful}/{len(files)}")
    logger.info(f"Failed: {failed}/{len(files)}")
    
    if failed > 0:
        logger.error("Failed files:")
        for r in results:
            if r["status"] != "success":
                logger.error(f"  - {r['file']}: {r.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()