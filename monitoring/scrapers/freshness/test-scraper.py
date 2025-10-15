#!/usr/bin/env python3
"""
File: monitoring/scrapers/freshness/test-scraper.py

Test freshness checking for a specific scraper.
Useful for debugging individual scraper configurations.
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime
import argparse
import yaml

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from google.cloud import storage
from monitoring.scrapers.freshness.core.freshness_checker import FreshnessChecker
from monitoring.scrapers.freshness.core.season_manager import SeasonManager
from monitoring.scrapers.freshness.utils.nba_schedule_api import has_games_today_cached

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_scraper(scraper_name, config_dir, verbose=False):
    """
    Test a specific scraper's freshness check.
    
    Args:
        scraper_name: Name of scraper to test
        config_dir: Path to config directory
        verbose: Enable verbose output
    """
    print("=" * 80)
    print(f"Testing Scraper: {scraper_name}")
    print("=" * 80)
    print()
    
    # Load config
    config_path = config_dir / 'monitoring_config.yaml'
    with open(config_path, 'r') as f:
        monitoring_config = yaml.safe_load(f)
    
    scrapers = monitoring_config.get('scrapers', {})
    
    if scraper_name not in scrapers:
        print(f"Error: Scraper '{scraper_name}' not found in config")
        print()
        print("Available scrapers:")
        for name in sorted(scrapers.keys()):
            print(f"  - {name}")
        sys.exit(1)
    
    scraper_config = scrapers[scraper_name]
    
    # Display configuration
    print("Configuration:")
    print(f"  Enabled: {scraper_config.get('enabled', True)}")
    print(f"  Bucket: {scraper_config.get('gcs', {}).get('bucket')}")
    print(f"  Path Pattern: {scraper_config.get('gcs', {}).get('path_pattern')}")
    print(f"  Schedule: {scraper_config.get('schedule', {}).get('cron')}")
    print()
    
    # Get season info
    season_manager = SeasonManager(str(config_dir / 'nba_schedule_config.yaml'))
    season_summary = season_manager.get_summary()
    
    print("Season Context:")
    print(f"  Season: {season_summary['season_label']}")
    print(f"  Phase: {season_summary['current_phase']}")
    print(f"  Date: {season_summary['check_date']}")
    print()
    
    # Check games today
    has_games = has_games_today_cached()
    print(f"  Games Today: {has_games}")
    print()
    
    # Get freshness thresholds
    freshness_config = scraper_config.get('freshness', {}).get('max_age_hours', {})
    current_threshold = freshness_config.get(season_summary['current_phase'], 24)
    
    print("Freshness Thresholds:")
    for phase, hours in freshness_config.items():
        marker = " <- CURRENT" if phase == season_summary['current_phase'] else ""
        print(f"  {phase}: {hours}h{marker}")
    print()
    
    # Run freshness check
    print("Running Freshness Check...")
    print("-" * 80)
    
    checker = FreshnessChecker()
    result = checker.check_scraper(
        scraper_name=scraper_name,
        config=scraper_config,
        current_season=season_summary['current_phase'],
        has_games_today=has_games
    )
    
    print()
    print("=" * 80)
    print("Results")
    print("=" * 80)
    print()
    
    # Status with color
    status_colors = {
        'ok': '\033[92m',      # Green
        'warning': '\033[93m',  # Yellow
        'critical': '\033[91m', # Red
        'skipped': '\033[94m',  # Blue
        'error': '\033[91m'     # Red
    }
    reset = '\033[0m'
    
    status_color = status_colors.get(result.status.value, '')
    print(f"Status: {status_color}{result.status.value.upper()}{reset}")
    print(f"Message: {result.message}")
    print()
    
    if result.details:
        print("Details:")
        for key, value in result.details.items():
            print(f"  {key}: {value}")
        print()
    
    # Recommendations
    if result.status.value == 'critical':
        print("⚠️  CRITICAL: Immediate action required")
        print()
        print("Recommended actions:")
        print("  1. Check if scraper is running")
        print("  2. Verify GCS bucket and path")
        print("  3. Check scraper logs for errors")
        print("  4. Manually trigger scraper if needed")
    
    elif result.status.value == 'warning':
        print("⚠️  WARNING: Should be investigated")
        print()
        print("Recommended actions:")
        print("  1. Check scraper schedule")
        print("  2. Verify data is being generated")
        print("  3. Consider adjusting thresholds if appropriate")
    
    elif result.status.value == 'skipped':
        print("ℹ️  Skipped (expected based on configuration)")
    
    elif result.status.value == 'ok':
        print("✅ All good!")
    
    print()
    
    # GCS inspection details
    if verbose and result.details.get('file_path'):
        print("=" * 80)
        print("Detailed File Information")
        print("=" * 80)
        print()
        
        file_path = result.details['file_path']
        print(f"File Path: {file_path}")
        print(f"File Age: {result.details.get('file_age_hours', 0):.2f} hours")
        print(f"File Size: {result.details.get('file_size_mb', 0):.3f} MB")
        print(f"Updated At: {result.details.get('updated_at', 'N/A')}")
        print()
        
        # Show threshold comparison
        max_age = result.details.get('max_age_hours', current_threshold)
        file_age = result.details.get('file_age_hours', 0)
        
        print("Age Threshold Comparison:")
        print(f"  File Age: {file_age:.1f}h")
        print(f"  Warning Threshold: {max_age:.1f}h")
        print(f"  Critical Threshold: {max_age * 2:.1f}h")
        
        if file_age < max_age:
            print(f"  ✅ Within threshold ({file_age/max_age*100:.1f}% of limit)")
        elif file_age < max_age * 2:
            print(f"  ⚠️  Exceeds warning threshold")
        else:
            print(f"  🔴 Exceeds critical threshold")
        
        print()


def list_scrapers(config_dir):
    """List all configured scrapers."""
    config_path = config_dir / 'monitoring_config.yaml'
    with open(config_path, 'r') as f:
        monitoring_config = yaml.safe_load(f)
    
    scrapers = monitoring_config.get('scrapers', {})
    
    print("=" * 80)
    print(f"Available Scrapers ({len(scrapers)} total)")
    print("=" * 80)
    print()
    
    for name, config in sorted(scrapers.items()):
        enabled = config.get('enabled', True)
        status = "✅" if enabled else "⏸️ "
        description = config.get('description', 'No description')
        print(f"{status} {name}")
        print(f"    {description}")
        print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Test freshness monitoring for a specific scraper'
    )
    parser.add_argument(
        'scraper',
        nargs='?',
        help='Name of scraper to test (omit to list all)'
    )
    parser.add_argument(
        '--config-dir',
        type=str,
        default=None,
        help='Path to config directory (default: auto-detect)'
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--list',
        '-l',
        action='store_true',
        help='List all available scrapers'
    )
    
    args = parser.parse_args()
    
    # Determine config directory
    if args.config_dir:
        config_dir = Path(args.config_dir)
    else:
        config_dir = Path(__file__).parent / 'config'
    
    if not config_dir.exists():
        print(f"Error: Config directory not found: {config_dir}")
        sys.exit(1)
    
    # List or test
    if args.list or not args.scraper:
        list_scrapers(config_dir)
    else:
        test_scraper(args.scraper, config_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
