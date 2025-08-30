#!/usr/bin/env python3
"""
File: processor_backfill/nbac_injury_report/nbac_injury_report_backfill_job.py

Backfill NBA.com injury reports from historical data.
Processes all hourly reports to track injury status patterns.
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from google.cloud import storage
from typing import List, Dict

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.nbacom.nbac_injury_report_processor import NbacInjuryReportProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_injury_report_files(bucket_name: str, start_date: str, end_date: str) -> List[storage.Blob]:
    """Get all injury report files in date range."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    
    all_files = []
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    current = start
    while current <= end:
        date_str = current.strftime('%Y-%m-%d')
        prefix = f'nba-com/injury-report-data/{date_str}/'
        
        # List all hour folders for this date
        blobs = bucket.list_blobs(prefix=prefix)
        json_files = [b for b in blobs if b.name.endswith('.json')]
        all_files.extend(json_files)
        
        if json_files:
            logger.info(f"Found {len(json_files)} reports for {date_str}")
        
        current += timedelta(days=1)
    
    return all_files

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com injury reports')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--batch-size', type=int, default=100, help='Files to process before logging')
    
    args = parser.parse_args()
    
    processor = NbacInjuryReportProcessor()
    bucket_name = 'nba-scraped-data'
    
    # Get all files in date range
    logger.info(f"Scanning for injury reports from {args.start_date} to {args.end_date}")
    files = get_injury_report_files(bucket_name, args.start_date, args.end_date)
    
    logger.info(f"Found {len(files)} total injury report files")
    
    if args.dry_run:
        # Show sample of files
        logger.info("Sample files (first 10):")
        for blob in files[:10]:
            logger.info(f"  - {blob.name}")
        
        # Show hourly distribution
        hour_counts = {}
        for blob in files:
            # Extract hour from path: .../YYYY-MM-DD/HH/...
            parts = blob.name.split('/')
            if len(parts) >= 4:
                hour = parts[3]
                hour_counts[hour] = hour_counts.get(hour, 0) + 1
        
        logger.info("\nHourly distribution:")
        for hour in sorted(hour_counts.keys()):
            logger.info(f"  Hour {hour}: {hour_counts[hour]} reports")
        
        return
    
    # Process files
    logger.info(f"Processing {len(files)} files...")
    
    successful = 0
    failed = 0
    total_records = 0
    
    for i, blob in enumerate(files, 1):
        try:
            # Download and parse
            data = json.loads(blob.download_as_text())
            
            # Validate
            errors = processor.validate_data(data)
            if errors:
                logger.warning(f"Validation errors for {blob.name}: {errors}")
                failed += 1
                continue
            
            # Transform
            rows = processor.transform_data(data, f"gs://{bucket_name}/{blob.name}")
            
            # Load to BigQuery
            result = processor.load_data(rows)
            if result['errors']:
                logger.error(f"Load errors for {blob.name}: {result['errors']}")
                failed += 1
            else:
                successful += 1
                total_records += result['rows_processed']
            
            # Progress logging
            if i % args.batch_size == 0:
                logger.info(f"Progress: {i}/{len(files)} files, "
                          f"{successful} successful, {failed} failed, "
                          f"{total_records} total records")
                
        except Exception as e:
            logger.error(f"Failed to process {blob.name}: {e}")
            failed += 1
            continue
    
    # Final summary
    logger.info(f"\nBackfill complete:")
    logger.info(f"  Files processed: {successful + failed}")
    logger.info(f"  Successful: {successful}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Total records loaded: {total_records}")

if __name__ == "__main__":
    main()