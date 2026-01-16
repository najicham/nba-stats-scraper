#!/usr/bin/env python3
"""
MLB BettingPros Props Processor

Processes MLB player prop data from BettingPros API (via GCS) to BigQuery.
Handles both historical backfill data and live daily scraper output.

GCS Paths:
  - Historical: bettingpros-mlb/historical/{market_name}/{date}/props.json
  - Live/Daily: bettingpros-mlb/{market_name}/{date}/props.json

Target Tables:
  - mlb_raw.bp_pitcher_props (markets: pitcher-strikeouts, pitcher-earned-runs-allowed)
  - mlb_raw.bp_batter_props (9 batter markets)

Key Features:
- BettingPros projections (projection_value, projection_side, projection_ev) - used by V1.6 model
- Performance trends (perf_last_5_over/under, perf_season_over/under)
- Actual outcomes (actual_value, is_scored, is_push) - available for historical, null for live
- Deduplication via source_file_path

Data Sources:
- Historical: scripts/mlb/historical_bettingpros_backfill/ (4 years: 2022-2025)
- Live: scrapers/bettingpros/bp_mlb_player_props.py (daily during season)

Created: 2026-01-15
Updated: 2026-01-16 - Added support for live scraper output path
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.utils.player_name_normalizer import normalize_name_for_lookup
from shared.config.sport_config import get_raw_dataset

logger = logging.getLogger(__name__)


# Market definitions
PITCHER_MARKETS = {285: 'pitcher-strikeouts', 290: 'pitcher-earned-runs-allowed'}
BATTER_MARKETS = {
    287: 'batter-hits', 288: 'batter-runs', 289: 'batter-rbis',
    291: 'batter-doubles', 292: 'batter-triples', 293: 'batter-total-bases',
    294: 'batter-stolen-bases', 295: 'batter-singles', 299: 'batter-home-runs'
}


class MlbBpHistoricalPropsProcessor(ProcessorBase):
    """
    MLB BettingPros Historical Props Processor

    Processes historical prop data from GCS to BigQuery.
    Handles both pitcher and batter props with actual outcomes.

    Processing Strategy: CHECK_BEFORE_INSERT
    - Checks source_file_path to avoid duplicate processing
    - Safe for re-runs during backfill
    """

    def __init__(self, prop_type: str = 'pitcher'):
        """
        Initialize processor.

        Args:
            prop_type: 'pitcher' or 'batter' - determines target table
        """
        self.prop_type = prop_type
        self.dataset_id = get_raw_dataset()
        super().__init__()

        # Set table based on prop type
        if prop_type == 'pitcher':
            self.table_name = 'bp_pitcher_props'
        else:
            self.table_name = 'bp_batter_props'

        self.processing_strategy = 'CHECK_BEFORE_INSERT'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load BettingPros historical data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def file_already_processed(self, file_path: str) -> bool:
        """Check if this GCS file has already been processed."""
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        query = f"""
        SELECT COUNT(*) as count
        FROM `{table_id}`
        WHERE source_file_path = @file_path
        LIMIT 1
        """

        try:
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("file_path", "STRING", file_path)
                ]
            )
            query_job = self.bq_client.query(query, job_config=job_config)
            results = list(query_job.result(timeout=30))
            return results and results[0].count > 0
        except Exception as e:
            # Table might not exist yet - that's OK
            logger.debug(f"Check file processed query failed (table may not exist): {e}")
            return False

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []

        if not data:
            errors.append("Empty data")
            return errors

        if 'meta' not in data:
            errors.append("Missing 'meta' field")

        if 'props' not in data:
            errors.append("Missing 'props' field")
        elif not isinstance(data['props'], list):
            errors.append("'props' is not a list")

        return errors

    def transform_data(self) -> None:
        """Transform raw BettingPros data into rows for BigQuery."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []

        try:
            # Validate structure
            errors = self.validate_data(raw_data)
            if errors:
                logger.warning(f"Validation errors for {file_path}: {errors}")
                self.transformed_data = []
                return

            # Extract metadata
            meta = raw_data.get('meta', {})
            game_date = meta.get('date')
            market_id = meta.get('market_id')
            market_name = meta.get('market_name', '')
            scraped_at = meta.get('scraped_at')

            # Process timestamp
            processed_at = datetime.now(timezone.utc).isoformat()

            # Process each prop
            for prop in raw_data.get('props', []):
                try:
                    # Create normalized player lookup
                    player_name = prop.get('player_name', '')
                    player_lookup = normalize_name_for_lookup(player_name) if player_name else None

                    row = {
                        # Identifiers
                        'game_date': game_date,
                        'market_id': market_id,
                        'market_name': market_name,
                        'event_id': prop.get('event_id'),

                        # Player info
                        'player_id': prop.get('player_id'),
                        'player_name': player_name,
                        'player_lookup': player_lookup,
                        'team': prop.get('team'),
                        'position': prop.get('position'),

                        # Over line
                        'over_line': prop.get('over_line'),
                        'over_odds': prop.get('over_odds'),
                        'over_book_id': prop.get('over_book_id'),
                        'over_consensus_line': prop.get('over_consensus_line'),

                        # Under line
                        'under_line': prop.get('under_line'),
                        'under_odds': prop.get('under_odds'),
                        'under_book_id': prop.get('under_book_id'),
                        'under_consensus_line': prop.get('under_consensus_line'),

                        # BettingPros projections (KEY FEATURES!)
                        'projection_value': prop.get('projection_value'),
                        'projection_side': prop.get('projection_side'),
                        'projection_ev': prop.get('projection_ev'),
                        'projection_rating': prop.get('projection_rating'),

                        # Actual outcome (KEY FOR TRAINING!)
                        'actual_value': prop.get('actual_value'),
                        'is_scored': prop.get('is_scored'),
                        'is_push': prop.get('is_push'),

                        # Performance trends (FEATURES!)
                        'perf_last_5_over': prop.get('perf_last_5_over'),
                        'perf_last_5_under': prop.get('perf_last_5_under'),
                        'perf_last_10_over': prop.get('perf_last_10_over'),
                        'perf_last_10_under': prop.get('perf_last_10_under'),
                        'perf_season_over': prop.get('perf_season_over'),
                        'perf_season_under': prop.get('perf_season_under'),

                        # Context
                        'opposing_pitcher': prop.get('opposing_pitcher'),
                        'opposition_rank': prop.get('opposition_rank'),

                        # Metadata
                        'source_file_path': file_path,
                        'scraped_at': scraped_at,
                        'processed_at': processed_at,
                    }

                    rows.append(row)

                except Exception as e:
                    logger.warning(f"Error processing prop: {e}")
                    continue

            logger.info(
                f"Transformed {len(rows)} {self.prop_type} props "
                f"for {game_date} from {market_name}"
            )

            self.transformed_data = rows

        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            notify_error(
                title=f"MLB BP {self.prop_type.title()} Props Transform Failed",
                message=f"Error: {str(e)[:200]}",
                details={
                    'file_path': file_path,
                    'error_type': type(e).__name__,
                },
                processor_name="MlbBpHistoricalPropsProcessor"
            )
            raise

    def save_data(self) -> None:
        """Save transformed data to BigQuery using batch loading."""
        rows = self.transformed_data

        if not rows:
            logger.info("No rows to save")
            self.stats['rows_inserted'] = 0
            return

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        try:
            # Get target table schema
            try:
                target_table = self.bq_client.get_table(table_id)
            except Exception as e:
                if 'not found' in str(e).lower():
                    logger.error(f"Table {table_id} not found - run schema SQL first")
                    raise
                raise

            # Configure batch load
            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )

            # Batch load
            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=120)

            if load_job.errors:
                logger.error(f"BigQuery load errors: {load_job.errors[:3]}")
                notify_error(
                    title=f"MLB BP {self.prop_type.title()} Props Load Errors",
                    message=f"Encountered {len(load_job.errors)} errors",
                    details={
                        'table': self.table_name,
                        'rows_attempted': len(rows),
                        'errors': str(load_job.errors)[:500],
                    },
                    processor_name="MlbBpHistoricalPropsProcessor"
                )
                return

            self.stats['rows_inserted'] = len(rows)

            # Summary
            scored_count = sum(1 for r in rows if r.get('is_scored'))
            unique_players = len(set(r.get('player_lookup') for r in rows if r.get('player_lookup')))

            logger.info(
                f"Loaded {len(rows)} {self.prop_type} props to {table_id} "
                f"({scored_count} scored, {unique_players} unique players)"
            )

        except Exception as e:
            logger.error(f"Failed to save data: {e}", exc_info=True)
            self.stats['rows_inserted'] = 0
            notify_error(
                title=f"MLB BP {self.prop_type.title()} Props Save Failed",
                message=f"Error: {str(e)[:200]}",
                details={
                    'table': self.table_name,
                    'rows_attempted': len(rows),
                    'error_type': type(e).__name__,
                },
                processor_name="MlbBpHistoricalPropsProcessor"
            )
            raise

    def run(self, opts: Dict) -> bool:
        """
        Run the processor with CHECK_BEFORE_INSERT logic.

        Args:
            opts: Dictionary with 'bucket' and 'file_path' keys

        Returns:
            True if successful, False otherwise
        """
        self.opts = opts
        file_path = opts.get('file_path', '')

        # Check if already processed
        if self.file_already_processed(file_path):
            logger.info(f"File already processed, skipping: {file_path}")
            self.stats['rows_inserted'] = 0
            self.stats['skipped'] = True
            return True

        # Run standard processing
        return super().run(opts)

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'skipped': self.stats.get('skipped', False),
            'prop_type': self.prop_type,
            'table': self.table_name,
        }


# Convenience classes for specific prop types
class MlbBpPitcherPropsProcessor(MlbBpHistoricalPropsProcessor):
    """Processor specifically for pitcher props."""
    def __init__(self):
        super().__init__(prop_type='pitcher')


class MlbBpBatterPropsProcessor(MlbBpHistoricalPropsProcessor):
    """Processor specifically for batter props."""
    def __init__(self):
        super().__init__(prop_type='batter')


# CLI entry point for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Process MLB BettingPros historical props')
    parser.add_argument('--bucket', default='nba-scraped-data', help='GCS bucket')
    parser.add_argument('--file-path', required=True, help='Path to JSON file in GCS')
    parser.add_argument('--prop-type', choices=['pitcher', 'batter'], default='pitcher',
                        help='Type of props to process')

    args = parser.parse_args()

    processor = MlbBpHistoricalPropsProcessor(prop_type=args.prop_type)
    success = processor.run({
        'bucket': args.bucket,
        'file_path': args.file_path,
    })

    print(f"Processing {'succeeded' if success else 'failed'}")
    print(f"Stats: {processor.get_processor_stats()}")
