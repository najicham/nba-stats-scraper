#!/usr/bin/env python3
"""
File: monitoring/processing_gap_detection/processing_gap_monitor_job.py

Processing Gap Monitor - Cloud Run Job

Monitors GCS files to ensure they've been processed into BigQuery.
Runs on schedule to detect processing failures.

Usage:
  # Check today's processing
  python processing_gap_monitor_job.py
  
  # Check specific date
  python processing_gap_monitor_job.py --date=2025-10-02
  
  # Check specific processors only
  python processing_gap_monitor_job.py --processors=nbac_player_list,br_roster
  
  # Check multiple days
  python processing_gap_monitor_job.py --lookback-days=7
  
  # Dry run (no alerts)
  python processing_gap_monitor_job.py --dry-run
"""

import argparse
import logging
import json
from datetime import date, timedelta
from typing import List

from config.processor_config import validate_config
from utils.gap_detector import ProcessingGapDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Monitor processing gaps between GCS files and BigQuery'
    )
    
    parser.add_argument(
        '--date',
        type=str,
        help='Specific date to check (YYYY-MM-DD), defaults to today'
    )
    
    parser.add_argument(
        '--lookback-days',
        type=int,
        default=1,
        help='Number of days to check (default: 1)'
    )
    
    parser.add_argument(
        '--processors',
        type=str,
        help='Comma-separated list of specific processors to check (default: all enabled)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run checks but do not send alerts'
    )
    
    parser.add_argument(
        '--json-output',
        action='store_true',
        help='Output results as JSON (for programmatic consumption)'
    )
    
    return parser.parse_args()


def main():
    """Main entry point for Cloud Run job."""
    args = parse_args()
    
    # Validate configuration
    try:
        validate_config()
        logger.info("✅ Configuration validation passed")
    except Exception as e:
        logger.error(f"❌ Configuration validation failed: {e}")
        return 1
    
    # Parse arguments
    if args.date:
        try:
            check_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
            return 1
    else:
        check_date = date.today()
    
    processors = args.processors.split(',') if args.processors else None
    
    if args.dry_run:
        logger.warning("🔍 DRY RUN MODE: Alerts will be suppressed")
    
    # Initialize detector
    detector = ProcessingGapDetector()
    
    # Check dates
    all_results = []
    total_gaps = 0
    
    for days_back in range(args.lookback_days):
        target_date = check_date - timedelta(days=days_back)
        logger.info(f"\n{'='*60}")
        logger.info(f"Checking date: {target_date}")
        logger.info(f"{'='*60}")
        
        results = detector.check_all_processors(
            check_date=target_date,
            processors=processors
        )
        
        all_results.append(results)
        total_gaps += results['gaps_found']
    
    # Output summary
    logger.info("\n" + "="*60)
    logger.info("PROCESSING GAP MONITOR - COMPLETE")
    logger.info("="*60)
    logger.info(f"Dates checked: {args.lookback_days}")
    logger.info(f"Total gaps found: {total_gaps}")
    
    if total_gaps > 0:
        logger.warning(f"⚠️  {total_gaps} processing gap(s) detected - review alerts")
    else:
        logger.info("✅ No processing gaps detected - all systems operational")
    
    logger.info("="*60)
    
    # JSON output if requested
    if args.json_output:
        output = {
            'summary': {
                'dates_checked': args.lookback_days,
                'total_gaps': total_gaps,
                'processors_filter': processors,
                'dry_run': args.dry_run
            },
            'results': all_results
        }
        print(json.dumps(output, indent=2))
    
    # Exit code: 0 if no gaps, 1 if gaps found
    return 1 if total_gaps > 0 else 0


if __name__ == "__main__":
    try:
        exit_code = main()
        exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        exit(130)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
        exit(1)