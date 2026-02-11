#!/usr/bin/env python3
"""
Phase 6 Picks File Canary Check

Validates that critical Phase 6 export files exist for today's date.
Alerts if picks/{date}.json, signals/{date}.json, or predictions/{date}.json are missing.

Usage:
    python bin/monitoring/phase6_picks_canary.py [--date YYYY-MM-DD]

Integration:
    Run via Cloud Scheduler every 2 hours between 12 PM - 11 PM ET
    Alert to #phase6-alerts Slack channel if files missing
"""

import argparse
from datetime import date, datetime
from google.cloud import storage
import sys

# Critical files that must exist
CRITICAL_FILES = [
    'picks/{date}.json',
    'signals/{date}.json',
    'predictions/{date}.json',
]

# Optional files (warn but don't alert)
OPTIONAL_FILES = [
    'best-bets/{date}.json',
    'tonight/all-players.json',  # Fixed path, not date-specific
]

def check_file_exists(bucket_name: str, blob_path: str) -> tuple[bool, str]:
    """Check if a file exists in GCS."""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        
        if blob.exists():
            # Get file metadata
            blob.reload()
            size = blob.size
            updated = blob.updated
            return True, f"✅ {blob_path} ({size:,} bytes, updated {updated})"
        else:
            return False, f"❌ {blob_path} - FILE NOT FOUND"
    except Exception as e:
        return False, f"❌ {blob_path} - ERROR: {e}"

def main():
    parser = argparse.ArgumentParser(description='Check Phase 6 export files exist')
    parser.add_argument('--date', help='Date to check (YYYY-MM-DD), defaults to today')
    parser.add_argument('--bucket', default='nba-props-platform-api', help='GCS bucket name')
    args = parser.parse_args()
    
    # Determine date to check
    check_date = args.date if args.date else date.today().isoformat()
    
    print(f"=== Phase 6 Picks Canary Check for {check_date} ===\n")
    
    # Check critical files
    critical_missing = []
    critical_results = []
    
    for file_template in CRITICAL_FILES:
        file_path = f"v1/{file_template.format(date=check_date)}"
        exists, message = check_file_exists(args.bucket, file_path)
        critical_results.append(message)
        
        if not exists:
            critical_missing.append(file_path)
    
    # Check optional files
    optional_missing = []
    optional_results = []
    
    for file_template in OPTIONAL_FILES:
        if '{date}' in file_template:
            file_path = f"v1/{file_template.format(date=check_date)}"
        else:
            file_path = f"v1/{file_template}"
        
        exists, message = check_file_exists(args.bucket, file_path)
        optional_results.append(message)
        
        if not exists:
            optional_missing.append(file_path)
    
    # Print results
    print("CRITICAL FILES:")
    for result in critical_results:
        print(f"  {result}")
    
    print("\nOPTIONAL FILES:")
    for result in optional_results:
        print(f"  {result}")
    
    # Summary
    print("\n=== SUMMARY ===")
    if critical_missing:
        print(f"❌ ALERT: {len(critical_missing)} critical file(s) missing!")
        for file_path in critical_missing:
            print(f"   - {file_path}")
        print("\n🔧 REMEDIATION:")
        print(f"   gcloud scheduler jobs run phase6-tonight-picks --location=us-west2")
        sys.exit(1)
    else:
        print("✅ All critical files present")
        
    if optional_missing:
        print(f"⚠️  Warning: {len(optional_missing)} optional file(s) missing")
        sys.exit(0)
    else:
        print("✅ All optional files present")
        sys.exit(0)

if __name__ == '__main__':
    main()
