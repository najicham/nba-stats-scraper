#!/usr/bin/env python3
"""
Test script for Basketball Reference Roster Processor
Run locally to test processing logic.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processors.basketball_ref.br_roster_processor import BasketballRefRosterProcessor
from processors.utils.name_utils import normalize_name

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_with_sample_data():
    """Test with sample roster data."""
    
    # Sample data matching scraper output
    sample_data = {
        "team": "Los Angeles Lakers",
        "team_abbrev": "LAL",
        "season": "2023-24",
        "players": [
            {
                "jersey_number": "23",
                "full_name": "LeBron James",
                "last_name": "James",
                "normalized": "lebron james",
                "position": "F",
                "height": "6-9",
                "weight": "250",
                "birth_date": "December 30, 1984",
                "experience": "20 years",
                "college": "None"
            },
            {
                "jersey_number": "3",
                "full_name": "Anthony Davis",
                "last_name": "Davis",
                "normalized": "anthony davis",
                "position": "F-C",
                "height": "6-10",
                "weight": "253",
                "birth_date": "March 11, 1993",
                "experience": "11 years",
                "college": "Kentucky"
            }
        ]
    }
    
    print("=" * 50)
    print("Testing Basketball Reference Roster Processor")
    print("=" * 50)
    
    # Test name normalization
    print("\n1. Testing name normalization:")
    test_names = [
        "LeBron James",
        "P.J. Tucker",
        "De'Aaron Fox",
        "Nikola Jokić"
    ]
    for name in test_names:
        normalized = normalize_name(name)
        print(f"  {name:20} -> {normalized}")
    
    # Test processor initialization
    print("\n2. Testing processor initialization:")
    processor = BasketballRefRosterProcessor()
    print(f"  ✓ Processor created: {processor.__class__.__name__}")
    print(f"  ✓ Required opts: {processor.required_opts}")
    print(f"  ✓ Table name: {processor.table_name}")
    
    # Test data transformation
    print("\n3. Testing data transformation:")
    processor.raw_data = sample_data
    processor.opts = {
        "season_year": 2023,
        "team_abbrev": "LAL",
        "file_path": "test/sample.json"
    }
    processor.set_additional_opts()
    
    try:
        processor.transform_data()
        print(f"  ✓ Transformed {len(processor.transformed_data)} players")
        
        # Show sample transformed data
        if processor.transformed_data:
            sample = processor.transformed_data[0]
            print("\n  Sample transformed player:")
            for key in ["player_full_name", "player_lookup", "experience_years", "first_seen_date"]:
                if key in sample:
                    print(f"    {key}: {sample[key]}")
    
    except Exception as e:
        print(f"  ✗ Transform failed: {e}")
    
    # Test stats
    print("\n4. Testing processor stats:")
    stats = processor.get_processor_stats()
    print(f"  Stats: {json.dumps(stats, indent=2)}")
    
    print("\n" + "=" * 50)
    print("✓ Test completed successfully!")
    print("=" * 50)


def test_with_gcs_file(bucket_name: str, file_path: str):
    """Test with actual GCS file."""
    
    print(f"\nTesting with GCS file: gs://{bucket_name}/{file_path}")
    
    processor = BasketballRefRosterProcessor()
    
    # Extract season and team from path
    # Expected: basketball_reference/season_rosters/2023-24/LAL.json
    parts = file_path.split("/")
    season_str = parts[-2]  # "2023-24"
    team_abbrev = parts[-1].replace(".json", "")  # "LAL"
    season_year = int(season_str.split("-")[0])  # 2023
    
    opts = {
        "season_year": season_year,
        "team_abbrev": team_abbrev,
        "file_path": file_path,
        "bucket": bucket_name,
        "project_id": os.environ.get("GCP_PROJECT_ID", "nba-props-platform")
    }
    
    print(f"  Season: {season_year}")
    print(f"  Team: {team_abbrev}")
    
    success = processor.run(opts)
    
    if success:
        stats = processor.get_processor_stats()
        print(f"\n✓ Processing successful!")
        print(f"  Stats: {json.dumps(stats, indent=2)}")
    else:
        print(f"\n✗ Processing failed")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Basketball Reference Roster Processor")
    parser.add_argument("--gcs-file", help="GCS file path to test")
    parser.add_argument("--bucket", default="nba-scraped-data", help="GCS bucket name")
    
    args = parser.parse_args()
    
    # Always run sample test
    test_with_sample_data()
    
    # Optionally test with GCS file
    if args.gcs_file:
        test_with_gcs_file(args.bucket, args.gcs_file)
    else:
        print("\nTo test with GCS file, run:")
        print("  python scripts/test_br_roster_processor.py --gcs-file basketball_reference/season_rosters/2023-24/LAL.json")