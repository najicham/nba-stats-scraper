#!/usr/bin/env python3
"""
GCS Referee Files Audit Script
Analyzes which dates have files and identifies issues

Usage:
    python scripts/audit/gcs_referee_audit.py
"""

import sys
from datetime import date, timedelta
from collections import defaultdict
from google.cloud import storage

# Expected date ranges from backfill document
EXPECTED_RANGES = [
    ('2021-10-19', '2022-06-16'),  # 2021-22 season
    ('2022-10-18', '2023-06-12'),  # 2022-23 season
    ('2023-10-24', '2024-06-19'),  # 2023-24 season
    ('2024-10-24', '2025-06-19'),  # 2024-25 season
]

BUCKET_NAME = 'nba-scraped-data'
BASE_PATH = 'nba-com/referee-assignments'

def get_expected_dates():
    """Get all expected dates from the date ranges."""
    expected = set()
    for start_str, end_str in EXPECTED_RANGES:
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
        current = start
        while current <= end:
            expected.add(current)
            current += timedelta(days=1)
    return expected

def audit_gcs_files():
    """Audit all referee assignment files in GCS."""
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    
    print("🔍 Auditing GCS referee assignment files...")
    print(f"Bucket: gs://{BUCKET_NAME}/{BASE_PATH}/")
    print("=" * 70)
    print()
    
    # Get all files
    blobs = bucket.list_blobs(prefix=f"{BASE_PATH}/")
    
    files_by_date = defaultdict(list)
    file_sizes = defaultdict(list)
    
    for blob in blobs:
        if blob.name.endswith('.json'):
            # Extract date from path: nba-com/referee-assignments/2024-10-24/file.json
            parts = blob.name.split('/')
            if len(parts) >= 3:
                date_str = parts[2]
                try:
                    file_date = date.fromisoformat(date_str)
                    files_by_date[file_date].append(blob.name)
                    file_sizes[file_date].append(blob.size)
                except ValueError:
                    continue
    
    # Get expected dates
    expected_dates = get_expected_dates()
    
    # Categorize dates
    dates_with_files = set(files_by_date.keys())
    missing_dates = expected_dates - dates_with_files
    
    # Analyze file sizes
    suspicious_files = {}  # dates with very small files
    for file_date, sizes in file_sizes.items():
        avg_size = sum(sizes) / len(sizes)
        if avg_size < 500:  # Less than 500 bytes is suspicious
            suspicious_files[file_date] = {
                'count': len(sizes),
                'avg_size': avg_size,
                'sizes': sizes
            }
    
    # Print summary
    print("📊 SUMMARY")
    print("=" * 70)
    print(f"Expected dates (all seasons): {len(expected_dates):,}")
    print(f"Dates with files:             {len(dates_with_files):,}")
    print(f"Missing dates:                {len(missing_dates):,}")
    print(f"Suspicious files (< 500B):    {len(suspicious_files):,}")
    print()
    
    # Coverage by season
    print("📅 COVERAGE BY SEASON")
    print("=" * 70)
    for start_str, end_str in EXPECTED_RANGES:
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
        
        season_dates = {d for d in expected_dates if start <= d <= end}
        season_files = {d for d in dates_with_files if start <= d <= end}
        season_missing = season_dates - season_files
        
        coverage_pct = (len(season_files) / len(season_dates) * 100) if season_dates else 0
        
        print(f"{start_str} to {end_str}:")
        print(f"  Expected: {len(season_dates):,} days")
        print(f"  Have files: {len(season_files):,} days ({coverage_pct:.1f}%)")
        print(f"  Missing: {len(season_missing):,} days")
        print()
    
    # Suspicious files details
    if suspicious_files:
        print("⚠️  SUSPICIOUS FILES (< 500 bytes)")
        print("=" * 70)
        print("These files may be empty responses or errors:")
        print()
        
        # Show first 20
        for file_date in sorted(suspicious_files.keys())[:20]:
            info = suspicious_files[file_date]
            print(f"  {file_date}: {info['count']} files, avg {info['avg_size']:.0f} bytes")
        
        if len(suspicious_files) > 20:
            print(f"  ... and {len(suspicious_files) - 20} more dates")
        print()
    
    # Missing dates by month
    print("📆 MISSING DATES BY MONTH")
    print("=" * 70)
    missing_by_month = defaultdict(list)
    for missing_date in sorted(missing_dates):
        month_key = missing_date.strftime('%Y-%m')
        missing_by_month[month_key].append(missing_date)
    
    for month_key in sorted(missing_by_month.keys(), reverse=True)[:12]:
        dates = missing_by_month[month_key]
        print(f"{month_key}: {len(dates)} missing dates")
        if len(dates) <= 10:
            date_strs = [d.strftime('%Y-%m-%d') for d in dates]
            print(f"  {', '.join(date_strs)}")
        else:
            print(f"  First 5: {', '.join([d.strftime('%Y-%m-%d') for d in dates[:5]])}")
            print(f"  Last 5:  {', '.join([d.strftime('%Y-%m-%d') for d in dates[-5:]])}")
        print()
    
    # Action items
    print("🎯 RECOMMENDED ACTIONS")
    print("=" * 70)
    
    if suspicious_files:
        print("1. Validate suspicious files:")
        print("   python scripts/audit/validate_referee_files.py")
        print()
    
    if missing_dates:
        print("2. Scrape missing dates:")
        print(f"   # {len(missing_dates):,} dates need scraping")
        
        # Group missing dates into ranges
        ranges = []
        sorted_missing = sorted(missing_dates)
        if sorted_missing:
            range_start = sorted_missing[0]
            range_end = sorted_missing[0]
            
            for d in sorted_missing[1:]:
                if (d - range_end).days == 1:
                    range_end = d
                else:
                    ranges.append((range_start, range_end))
                    range_start = d
                    range_end = d
            ranges.append((range_start, range_end))
        
        print("   # Missing date ranges (first 10):")
        for start, end in ranges[:10]:
            if start == end:
                print(f"   #   {start}")
            else:
                days = (end - start).days + 1
                print(f"   #   {start} to {end} ({days} days)")
        
        if len(ranges) > 10:
            print(f"   #   ... and {len(ranges) - 10} more ranges")
        print()
    
    print("3. Process existing valid files:")
    if len(dates_with_files) - len(suspicious_files) > 0:
        print(f"   # {len(dates_with_files) - len(suspicious_files):,} dates ready to process")
        print("   # Deploy new processor and run backfill")
    print()
    
    # Generate date list file for missing dates
    if missing_dates:
        output_file = 'missing_referee_dates.txt'
        with open(output_file, 'w') as f:
            for missing_date in sorted(missing_dates):
                f.write(f"{missing_date}\n")
        print(f"📝 Written missing dates to: {output_file}")
        print()
    
    # Generate date list for suspicious files
    if suspicious_files:
        output_file = 'suspicious_referee_dates.txt'
        with open(output_file, 'w') as f:
            for susp_date in sorted(suspicious_files.keys()):
                f.write(f"{susp_date}\n")
        print(f"📝 Written suspicious dates to: {output_file}")
        print()

if __name__ == '__main__':
    try:
        audit_gcs_files()
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
