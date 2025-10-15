#!/usr/bin/env python3
"""
File: monitoring/processor_execution_monitoring/execution_monitor_job.py

Processor Execution Monitor - Cloud Run Job

Monitors processor execution history to detect missing runs, failures, and staleness.

Usage:
  # Check last 7 days
  python execution_monitor_job.py
  
  # Check specific date range
  python execution_monitor_job.py --date=2025-10-02 --lookback-days=14
  
  # Check specific processors only
  python execution_monitor_job.py --processors=gamebook_processor,roster_processor
  
  # Dry run (no alerts)
  python execution_monitor_job.py --dry-run
"""

import argparse
import logging
import json
from datetime import date, timedelta
from typing import List

from config.processor_config import validate_config
from utils.execution_monitor import ProcessorExecutionMonitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Monitor processor execution history for gaps and failures'
    )
    
    parser.add_argument(
        '--date',
        type=str,
        help='End date to check (YYYY-MM-DD), defaults to today'
    )
    
    parser.add_argument(
        '--lookback-days',
        type=int,
        default=7,
        help='Number of days to check (default: 7)'
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
    
    # Initialize monitor
    monitor = ProcessorExecutionMonitor()
    
    # Run checks
    logger.info(f"\n{'='*60}")
    logger.info(f"Checking execution history: {check_date} (lookback: {args.lookback_days} days)")
    logger.info(f"{'='*60}")
    
    results = monitor.check_all_processors(
        check_date=check_date,
        lookback_days=args.lookback_days,
        processors=processors
    )
    
    # Output summary
    logger.info("\n" + "="*60)
    logger.info("PROCESSOR EXECUTION MONITOR - COMPLETE")
    logger.info("="*60)
    logger.info(f"Date Range: {results['start_date']} to {results['check_date']}")
    logger.info(f"Processors checked: {results['total_processors_checked']}")
    logger.info(f"Issues found: {results['issues_found']}")
    
    if results['issues_found'] > 0:
        logger.warning(f"⚠️  {results['issues_found']} processor(s) have issues - review alerts")
    else:
        logger.info("✅ All processors executed successfully")
    
    logger.info("="*60)
    
    # JSON output if requested
    if args.json_output:
        output = {
            'summary': {
                'date_range': f"{results['start_date']} to {results['check_date']}",
                'lookback_days': args.lookback_days,
                'processors_checked': results['total_processors_checked'],
                'issues_found': results['issues_found'],
                'processors_filter': processors,
                'dry_run': args.dry_run
            },
            'results': results
        }
        print(json.dumps(output, indent=2))
    
    # Exit code: 0 if no issues, 1 if issues found
    return 1 if results['issues_found'] > 0 else 0


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