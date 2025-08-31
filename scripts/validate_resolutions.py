#!/usr/bin/env python3
"""
Bulk validation script for name resolutions.
Usage: python scripts/validate_resolutions.py --validate resolution_id1,resolution_id2
"""

import argparse
from google.cloud import bigquery

def validate_resolutions(resolution_ids: List[str], validated_by: str, notes: str):
    """Validate multiple resolutions at once."""
    client = bigquery.Client()
    
    # Call the stored procedure
    query = """
    CALL `nba-props-platform.nba_raw.validate_name_resolution`(
        @resolution_ids, @validated_by, @notes
    )
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("resolution_ids", "STRING", resolution_ids),
            bigquery.ScalarQueryParameter("validated_by", "STRING", validated_by),
            bigquery.ScalarQueryParameter("notes", "STRING", notes)
        ]
    )
    
    result = client.query(query, job_config=job_config)
    print(f"Validated {len(resolution_ids)} resolutions")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", help="Comma-separated resolution IDs")
    parser.add_argument("--user", default="system", help="User performing validation")
    parser.add_argument("--notes", default="Bulk validation", help="Validation notes")
    
    args = parser.parse_args()
    
    if args.validate:
        resolution_ids = args.validate.split(",")
        validate_resolutions(resolution_ids, args.user, args.notes)