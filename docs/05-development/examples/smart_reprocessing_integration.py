#!/usr/bin/env python3
"""
Smart Reprocessing Integration Example

Shows how to integrate smart reprocessing into Phase 3 processors.
This enables processors to skip processing when Phase 2 source data unchanged.

Expected Impact: 30-50% reduction in Phase 3 processing
"""

from data_processors.analytics.analytics_base import AnalyticsProcessor
from typing import List, Dict


class ExampleAnalyticsProcessor(AnalyticsProcessor):
    """Example processor with smart reprocessing integrated."""

    DEPENDENCIES = {
        'nbac_gamebook_player_stats': {
            'field_prefix': 'source_gamebook',
            'check_type': 'date_range',
            'expected_count_min': 200,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168,
            'critical': True
        },
        'bdl_player_boxscores': {
            'field_prefix': 'source_bdl',
            'check_type': 'date_range',
            'expected_count_min': 200,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168,
            'critical': True
        }
    }

    def __init__(self):
        super().__init__()
        self.table_name = "example_analytics_table"
        self.dataset_id = "nba_analytics"

        # Metrics tracking (optional but recommended)
        self.skip_count = 0
        self.process_count = 0

    def extract_raw_data(self) -> None:
        """
        Extract data with smart reprocessing.

        IMPORTANT: Base class already called check_dependencies() and track_source_usage()
        before this method, so all source_*_hash attributes are populated.
        """
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']

        # ========================================================================
        # SMART REPROCESSING: Check if we can skip processing
        # ========================================================================

        # Option 1: Check primary source only (recommended - more lenient)
        skip, reason = self.should_skip_processing(
            game_date=start_date,
            check_all_sources=False  # Only check first dependency
        )

        # Option 2: Check ALL sources (stricter - all must be unchanged)
        # skip, reason = self.should_skip_processing(
        #     game_date=start_date,
        #     check_all_sources=True  # All dependencies must be unchanged
        # )

        if skip:
            self.logger.info(f"✅ SKIPPING PROCESSING: {reason}")
            self.skip_count += 1

            # Important: Set raw_data to empty list to signal skip
            self.raw_data = []
            return

        # ========================================================================
        # PROCESS DATA: Source data changed or first time processing
        # ========================================================================

        self.logger.info(f"🔄 PROCESSING DATA: {reason}")
        self.process_count += 1

        # Continue with normal data extraction
        query = f"""
        SELECT
            game_id,
            game_date,
            player_id,
            points,
            assists,
            rebounds
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """

        results = self.bq_client.query(query).result()
        self.raw_data = [dict(row) for row in results]

        self.logger.info(f"Extracted {len(self.raw_data)} records")

    def transform_data(self) -> List[Dict]:
        """Transform data with source tracking."""

        if not self.raw_data:
            self.logger.info("No data to transform (processing skipped)")
            return []

        # Build source tracking fields (includes hashes)
        tracking_fields = self.build_source_tracking_fields()

        rows = []
        for record in self.raw_data:
            row = {
                'game_date': record['game_date'],
                'game_id': record['game_id'],
                'player_id': record['player_id'],

                # Analytics
                'computed_metric': record['points'] + record['assists'],

                # Source tracking (includes 4 fields per source)
                **tracking_fields
            }
            rows.append(row)

        return rows

    def load_data_to_bigquery(self, rows: List[Dict]) -> bool:
        """Load to BigQuery."""

        if not rows:
            # No data to load (processing skipped)
            self.logger.info("No data to load (processing skipped)")
            return True  # Not an error - successful skip

        return self.write_to_bigquery(
            rows,
            self.table_name,
            write_mode='MERGE_UPDATE'
        )

    def log_skip_metrics(self):
        """Log skip rate metrics (call at end of batch processing)."""

        total = self.skip_count + self.process_count
        if total > 0:
            skip_rate = (self.skip_count / total) * 100
            self.logger.info(f"\n{'=' * 80}")
            self.logger.info(f"SMART REPROCESSING METRICS")
            self.logger.info(f"{'=' * 80}")
            self.logger.info(f"Total Runs:     {total}")
            self.logger.info(f"Processed:      {self.process_count} ({(self.process_count/total)*100:.1f}%)")
            self.logger.info(f"Skipped:        {self.skip_count} ({skip_rate:.1f}%)")
            self.logger.info(f"Savings:        {skip_rate:.1f}% reduction in processing")
            self.logger.info(f"{'=' * 80}\n")


# =============================================================================
# USAGE PATTERNS
# =============================================================================

def pattern_1_check_primary_source():
    """
    Pattern 1: Check Primary Source Only (Recommended)

    - Fastest check (single hash comparison)
    - More lenient (skips if main source unchanged)
    - Best for processors with one critical dependency
    """
    processor = ExampleAnalyticsProcessor()
    processor.set_opts({
        'project_id': 'nba-props-platform',
        'start_date': '2024-11-20',
        'end_date': '2024-11-20'
    })
    processor.init_clients()

    # In extract_raw_data():
    skip, reason = processor.should_skip_processing(
        game_date='2024-11-20',
        check_all_sources=False  # Only check first dependency
    )

    if skip:
        print(f"✅ Skipping: {reason}")
        return []
    else:
        print(f"🔄 Processing: {reason}")
        # Continue processing...


def pattern_2_check_all_sources():
    """
    Pattern 2: Check All Sources (Stricter)

    - More thorough check (all hash comparisons)
    - Stricter (skips only if ALL sources unchanged)
    - Best for processors that need all dependencies fresh
    """
    processor = ExampleAnalyticsProcessor()
    processor.set_opts({
        'project_id': 'nba-props-platform',
        'start_date': '2024-11-20',
        'end_date': '2024-11-20'
    })
    processor.init_clients()

    # In extract_raw_data():
    skip, reason = processor.should_skip_processing(
        game_date='2024-11-20',
        check_all_sources=True  # Check ALL dependencies
    )

    if skip:
        print(f"✅ Skipping: {reason}")
        return []
    else:
        print(f"🔄 Processing: {reason}")
        # Continue processing...


def pattern_3_with_game_id():
    """
    Pattern 3: Per-Game Smart Reprocessing

    - Most granular (check per game)
    - Best for reprocessing individual games
    - Useful for backfill jobs
    """
    processor = ExampleAnalyticsProcessor()
    processor.set_opts({
        'project_id': 'nba-props-platform',
        'start_date': '2024-11-20',
        'end_date': '2024-11-20'
    })
    processor.init_clients()

    # Process each game individually
    game_ids = ['0022400089', '0022400090']

    for game_id in game_ids:
        skip, reason = processor.should_skip_processing(
            game_date='2024-11-20',
            game_id=game_id
        )

        if skip:
            print(f"✅ Skipping {game_id}: {reason}")
            continue
        else:
            print(f"🔄 Processing {game_id}: {reason}")
            # Process this game...


def pattern_4_batch_processing_with_metrics():
    """
    Pattern 4: Batch Processing with Metrics

    - Process multiple dates
    - Track skip rate metrics
    - Log performance summary
    """
    processor = ExampleAnalyticsProcessor()
    processor.set_opts({'project_id': 'nba-props-platform'})
    processor.init_clients()

    dates = ['2024-11-15', '2024-11-16', '2024-11-17', '2024-11-18', '2024-11-19']

    for date in dates:
        processor.set_opts({
            'project_id': 'nba-props-platform',
            'start_date': date,
            'end_date': date
        })

        # Run will call extract_raw_data which checks should_skip_processing
        processor.run({'start_date': date, 'end_date': date})

    # Log metrics at end
    processor.log_skip_metrics()


# =============================================================================
# EXPECTED RESULTS
# =============================================================================

"""
Example Log Output:

First Run (No previous data):
    🔄 PROCESSING DATA: No previous data (first time processing)
    Extracted 250 records
    Writing 250 rows to nba_analytics.example_analytics_table

Second Run (Phase 2 unchanged):
    ✅ SKIPPING PROCESSING: All 2 source(s) unchanged
    No data to transform (processing skipped)
    No data to load (processing skipped)
    ✅ Processing complete (0 rows written)

Third Run (Phase 2 changed):
    🔄 PROCESSING DATA: Sources changed: nbac_gamebook_player_stats (hash changed)
    Extracted 250 records
    Writing 250 rows to nba_analytics.example_analytics_table

Batch Processing Metrics:
    ================================================================================
    SMART REPROCESSING METRICS
    ================================================================================
    Total Runs:     10
    Processed:      5 (50.0%)
    Skipped:        5 (50.0%)
    Savings:        50.0% reduction in processing
    ================================================================================
"""


# =============================================================================
# INTEGRATION CHECKLIST
# =============================================================================

"""
To integrate smart reprocessing into your processor:

1. ✅ Schema has hash fields (source_*_hash columns)
   - Already deployed for all Phase 3 processors

2. ✅ Base class tracks hashes
   - check_dependencies() extracts hashes from Phase 2
   - track_source_usage() stores hashes as attributes
   - build_source_tracking_fields() includes hashes in output

3. ✅ Add skip check to extract_raw_data()
   ```python
   skip, reason = self.should_skip_processing(start_date)
   if skip:
       self.logger.info(f"Skipping: {reason}")
       self.raw_data = []
       return
   ```

4. ✅ Handle empty raw_data in transform_data()
   ```python
   if not self.raw_data:
       return []
   ```

5. ✅ Handle empty rows in load_data()
   ```python
   if not rows:
       return True  # Skip is success, not failure
   ```

6. ⏳ Optional: Add metrics tracking
   - Track skip_count and process_count
   - Log skip rate periodically
   - Monitor savings over time

7. ⏳ Optional: Add configuration
   - Make check_all_sources configurable
   - Add environment variable to enable/disable
   - Add flag for debugging
"""


if __name__ == "__main__":
    print("Smart Reprocessing Integration Examples")
    print("=" * 80)
    print("\nRun these patterns to see smart reprocessing in action:")
    print("  - pattern_1_check_primary_source() - Recommended default")
    print("  - pattern_2_check_all_sources() - Stricter mode")
    print("  - pattern_3_with_game_id() - Per-game granularity")
    print("  - pattern_4_batch_processing_with_metrics() - Track savings")
    print("\nExpected Impact: 30-50% reduction in Phase 3 processing")
