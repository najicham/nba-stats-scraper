#!/usr/bin/env python3
"""
Temporary script to regenerate player_daily_cache for early season dates.
Bypasses the bootstrap check by temporarily setting BOOTSTRAP_DAYS to 0.
"""

import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# CRITICAL: Set BOOTSTRAP_DAYS to 0 BEFORE importing the processor
# This bypasses the early season skip logic
import shared.validation.config as config
original_bootstrap_days = config.BOOTSTRAP_DAYS
config.BOOTSTRAP_DAYS = 0

# Now import the processor
from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor

def main():
    if len(sys.argv) < 2:
        print("Usage: python regenerate_cache_bypass_bootstrap.py YYYY-MM-DD")
        return 1

    date_str = sys.argv[1]
    analysis_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    season_year = analysis_date.year if analysis_date.month >= 10 else analysis_date.year - 1

    print(f"Processing {date_str} with BOOTSTRAP_DAYS bypassed (was {original_bootstrap_days}, now {config.BOOTSTRAP_DAYS})")

    # Initialize processor
    processor = PlayerDailyCacheProcessor()
    processor.opts = {
        'analysis_date': analysis_date,
        'season_year': season_year
    }

    try:
        # Extract data
        print("Starting data extraction...")
        processor.extract_raw_data()

        # Check if processing was skipped
        if processor.stats.get('processing_decision') == 'skipped_early_season':
            print("✗ Still skipped (bootstrap check not bypassed successfully)")
            return 1

        # Calculate cache
        print("Starting cache calculation...")
        processor.calculate_precompute()

        # Save results
        print("Saving cache to BigQuery...")
        processor.save_precompute()

        print(f"✓ Processing complete for {date_str}")
        print(f"  - Cached: {len(processor.transformed_data)} players")
        print(f"  - Failed: {len(processor.failed_entities)} players")
        return 0

    except Exception as e:
        print(f"✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    exit(main())
