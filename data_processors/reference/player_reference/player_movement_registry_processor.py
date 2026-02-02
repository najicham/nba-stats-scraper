#!/usr/bin/env python3
"""
File: data_processors/reference/player_reference/player_movement_registry_processor.py

Player Movement Registry Processor - Rapid Trade Updates

Updates nba_reference.nba_players_registry from NBA.com player movement trades.
Provides near-real-time registry updates when players are traded, without waiting
for roster scrapers to run.

Key Features:
- Processes trades from last 24 hours (configurable)
- Updates team assignments in registry
- Marks source as 'player_movement' for tracking
- Handles current season only
- Idempotent (safe to run multiple times)
- Team abbreviation normalization (BRK→BKN, CHO→CHA, PHO→PHX)

Data Flow:
1. Query recent trades from nba_raw.nbac_player_movement
2. Find matching registry records for traded players
3. Update team_abbr and source_priority
4. Update activity tracking fields
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Set, Tuple, Optional
import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

from data_processors.reference.base.registry_processor_base import (
    RegistryProcessorBase,
    TemporalOrderingError
)
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

# Team abbreviation normalization (matches roster_registry_processor.py)
TEAM_ABBR_NORMALIZATION = {
    'BRK': 'BKN',
    'CHO': 'CHA',
    'PHO': 'PHX',
}


def normalize_team_abbr(team_abbr: str) -> str:
    """Normalize team abbreviation to official NBA code."""
    normalized = TEAM_ABBR_NORMALIZATION.get(team_abbr, team_abbr)
    if normalized != team_abbr:
        logger.debug(f"Normalized team code: {team_abbr} → {normalized}")
    return normalized


class PlayerMovementRegistryProcessor(RegistryProcessorBase):
    """
    Registry processor for player movement (trade) data.

    Updates player registry from NBA.com player movement transactions,
    providing rapid team assignment updates when trades occur.
    """

    def __init__(self, test_mode: bool = False, strategy: str = "merge",
                 confirm_full_delete: bool = False,
                 enable_name_change_detection: bool = False):
        # Name change detection not needed for player movement updates
        super().__init__(test_mode, strategy, confirm_full_delete, enable_name_change_detection)

        # Set processor type for source tracking
        self.processor_type = 'player_movement'

        logger.info("Initialized Player Movement Registry Processor")

    def get_recent_trades(self, lookback_hours: int = 24) -> pd.DataFrame:
        """
        Get recent player trades from player movement data.

        Args:
            lookback_hours: How many hours back to look for trades (default 24)

        Returns:
            DataFrame with columns: player_lookup, player_full_name, team_abbr,
                                   transaction_date, transaction_description
        """
        lookback_timestamp = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        query = """
        SELECT DISTINCT
            player_lookup,
            player_full_name,
            team_abbr,
            transaction_date,
            transaction_description,
            transaction_type
        FROM `{project}.nba_raw.nbac_player_movement`
        WHERE transaction_type = 'Trade'
          AND is_player_transaction = TRUE
          AND player_lookup IS NOT NULL
          AND player_lookup != ''
          AND scrape_timestamp >= @lookback_timestamp
        ORDER BY transaction_date DESC, player_full_name
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "lookback_timestamp",
                    "TIMESTAMP",
                    lookback_timestamp
                )
            ]
        )

        logger.info(f"Querying trades from last {lookback_hours} hours (since {lookback_timestamp})")

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()
            logger.info(f"Found {len(df)} player trades")

            if not df.empty:
                logger.info(f"Players traded: {', '.join(df['player_full_name'].tolist())}")

            return df

        except Exception as e:
            logger.error(f"Error querying recent trades: {e}")
            notify_error(
                title="Player Movement Query Failed",
                message=f"Failed to query trades: {str(e)}",
                details={
                    'lookback_hours': lookback_hours,
                    'error_type': type(e).__name__
                },
                processor_name="Player Movement Registry Processor"
            )
            raise

    def get_registry_records_for_players(
        self,
        player_lookups: List[str],
        season: str
    ) -> pd.DataFrame:
        """
        Get current registry records for specific players and season.

        Args:
            player_lookups: List of player lookup keys
            season: Season string (e.g., '2025-26')

        Returns:
            DataFrame with current registry records
        """
        if not player_lookups:
            return pd.DataFrame()

        # Convert list to SQL-safe format
        player_lookups_sql = ', '.join([f"'{p}'" for p in player_lookups])

        # Query only core fields that exist in all schema versions
        # Use COALESCE for newer fields that might not exist in test tables
        query = """
        SELECT
            player_lookup,
            player_name,
            team_abbr,
            season,
            source_priority,
            processed_at
        FROM `{project}.{table}`
        WHERE season = @season
          AND player_lookup IN ({players})
        """.format(
            project=self.project_id,
            table=self.table_name,
            players=player_lookups_sql
        )

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("season", "STRING", season)
            ]
        )

        logger.info(f"Querying registry for {len(player_lookups)} players in season {season}")

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()
            logger.info(f"Found {len(df)} existing registry records")

            # Add default values for fields that might not exist
            if 'roster_update_count' not in df.columns:
                df['roster_update_count'] = 0

            return df

        except Exception as e:
            logger.error(f"Error querying registry: {e}")
            notify_error(
                title="Registry Query Failed",
                message=f"Failed to query registry: {str(e)}",
                details={
                    'season': season,
                    'player_count': len(player_lookups),
                    'error_type': type(e).__name__
                },
                processor_name="Player Movement Registry Processor"
            )
            raise

    def build_update_records(
        self,
        trades_df: pd.DataFrame,
        registry_df: pd.DataFrame,
        season: str
    ) -> List[Dict]:
        """
        Build registry update records from trade data.

        Args:
            trades_df: DataFrame of recent trades
            registry_df: DataFrame of current registry records
            season: Season string

        Returns:
            List of update records for MERGE statement
        """
        update_records = []
        current_time = datetime.now(timezone.utc)

        for _, trade in trades_df.iterrows():
            player_lookup = trade['player_lookup']
            new_team = normalize_team_abbr(trade['team_abbr'])

            # Find existing registry record
            existing = registry_df[registry_df['player_lookup'] == player_lookup]

            if existing.empty:
                logger.warning(
                    f"No registry record found for {trade['player_full_name']} "
                    f"({player_lookup}) in season {season}"
                )
                continue

            old_team = existing.iloc[0]['team_abbr']

            # Skip if already updated
            if old_team == new_team:
                logger.debug(f"{trade['player_full_name']} already shows team {new_team}")
                continue

            # Build update record (only core fields for compatibility with all schema versions)
            update_record = {
                'player_lookup': player_lookup,
                'season': season,
                'team_abbr': new_team,
                'source_priority': 'player_movement',
                'processed_at': current_time,

                # Preserve existing fields
                'player_name': existing.iloc[0]['player_name'],
            }

            update_records.append(update_record)

            logger.info(
                f"Will update {trade['player_full_name']}: {old_team} → {new_team} "
                f"(transaction: {trade['transaction_date']})"
            )

        return update_records

    def apply_updates_via_merge(
        self,
        update_records: List[Dict],
        season: str
    ) -> Dict:
        """
        Apply registry updates using MERGE statement.

        Args:
            update_records: List of update records
            season: Season string

        Returns:
            Dict with update results
        """
        if not update_records:
            logger.info("No updates to apply")
            return {
                'records_updated': 0,
                'players_updated': [],
                'status': 'no_updates_needed'
            }

        # Create temporary table with updates
        temp_table_id = f"{self.project_id}.nba_reference.player_movement_updates_temp"

        # Convert to DataFrame for loading
        updates_df = pd.DataFrame(update_records)

        try:
            # Load updates to temp table (only core fields for compatibility)
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                schema=[
                    bigquery.SchemaField("player_lookup", "STRING"),
                    bigquery.SchemaField("season", "STRING"),
                    bigquery.SchemaField("team_abbr", "STRING"),
                    bigquery.SchemaField("source_priority", "STRING"),
                    bigquery.SchemaField("processed_at", "TIMESTAMP"),
                    bigquery.SchemaField("player_name", "STRING"),
                ]
            )

            logger.info(f"Loading {len(updates_df)} updates to temp table")
            load_job = self.bq_client.load_table_from_dataframe(
                updates_df,
                temp_table_id,
                job_config=job_config
            )
            load_job.result()

            # Execute MERGE statement (only update core fields for compatibility)
            merge_query = """
            MERGE `{target}` AS target
            USING `{source}` AS source
            ON target.player_lookup = source.player_lookup
               AND target.season = source.season
            WHEN MATCHED THEN
                UPDATE SET
                    team_abbr = source.team_abbr,
                    source_priority = source.source_priority,
                    processed_at = source.processed_at
            """.format(
                target=f"{self.project_id}.{self.table_name}",
                source=temp_table_id
            )

            logger.info("Executing MERGE statement")
            merge_job = self.bq_client.query(merge_query)
            merge_job.result()

            # Get stats
            num_dml_affected_rows = merge_job.num_dml_affected_rows

            logger.info(f"MERGE complete: {num_dml_affected_rows} rows updated")

            # Clean up temp table
            try:
                self.bq_client.delete_table(temp_table_id)
                logger.debug("Cleaned up temp table")
            except Exception as e:
                logger.warning(f"Could not delete temp table: {e}")

            # Build result
            players_updated = [
                f"{rec['player_name']} → {rec['team_abbr']}"
                for rec in update_records
            ]

            return {
                'records_updated': num_dml_affected_rows,
                'players_updated': players_updated,
                'status': 'success'
            }

        except Exception as e:
            logger.error(f"Error applying updates: {e}")
            notify_error(
                title="Player Movement Update Failed",
                message=f"Failed to apply updates: {str(e)}",
                details={
                    'season': season,
                    'update_count': len(update_records),
                    'error_type': type(e).__name__
                },
                processor_name="Player Movement Registry Processor"
            )
            raise

    def process_recent_trades(
        self,
        lookback_hours: int = 24,
        season_year: int = None
    ) -> Dict:
        """
        Process recent trades and update registry.

        Main entry point for trade processing.

        Args:
            lookback_hours: How many hours back to look for trades (default 24)
            season_year: NBA season starting year (defaults to current season)

        Returns:
            Dict with processing results
        """
        if not season_year:
            current_month = date.today().month
            if current_month >= 10:
                season_year = date.today().year
            else:
                season_year = date.today().year - 1

        season_str = self.calculate_season_string(season_year)

        logger.info(f"Processing player movement trades for season {season_str}")
        logger.info(f"Looking back {lookback_hours} hours for trades")

        try:
            # Step 1: Get recent trades
            trades_df = self.get_recent_trades(lookback_hours)

            if trades_df.empty:
                logger.info("No recent trades found")
                return {
                    'status': 'success',
                    'season': season_str,
                    'trades_found': 0,
                    'records_updated': 0,
                    'players_updated': [],
                    'message': 'No trades in lookback period'
                }

            # Step 2: Get current registry records for traded players
            player_lookups = trades_df['player_lookup'].unique().tolist()
            registry_df = self.get_registry_records_for_players(
                player_lookups,
                season_str
            )

            # Step 3: Build update records
            update_records = self.build_update_records(
                trades_df,
                registry_df,
                season_str
            )

            if not update_records:
                logger.info("All traded players already have correct team assignments")
                return {
                    'status': 'success',
                    'season': season_str,
                    'trades_found': len(trades_df),
                    'records_updated': 0,
                    'players_updated': [],
                    'message': 'Registry already up to date'
                }

            # Step 4: Apply updates
            result = self.apply_updates_via_merge(update_records, season_str)

            # Step 5: Build response
            result.update({
                'season': season_str,
                'trades_found': len(trades_df),
                'lookback_hours': lookback_hours,
                'processing_run_id': self.processing_run_id
            })

            # Send notification if updates were made
            if result['records_updated'] > 0:
                notify_info(
                    title="Player Registry Updated from Trades",
                    message=f"Updated {result['records_updated']} players from trade transactions",
                    details={
                        'season': season_str,
                        'trades_processed': len(trades_df),
                        'players_updated': result['players_updated']
                    },
                    processor_name="Player Movement Registry Processor"
                )

            logger.info(f"Trade processing complete: {result['records_updated']} records updated")

            return result

        except Exception as e:
            logger.error(f"Failed to process trades: {e}")
            notify_error(
                title="Trade Processing Failed",
                message=f"Failed to process: {str(e)}",
                details={
                    'season': season_str,
                    'lookback_hours': lookback_hours,
                    'error_type': type(e).__name__
                },
                processor_name="Player Movement Registry Processor"
            )

            return {
                'status': 'failed',
                'season': season_str,
                'error': str(e),
                'error_type': type(e).__name__
            }

    def transform_data(self, raw_data: Dict, file_path: str = None) -> List[Dict]:
        """
        Transform method for base class compatibility.
        Not used for player movement processing (uses process_recent_trades instead).
        """
        raise NotImplementedError(
            "Player movement processor uses process_recent_trades() method, "
            "not transform_data()"
        )


def process_recent_trades(
    lookback_hours: int = 24,
    season_year: int = None,
    test_mode: bool = False,
    strategy: str = "merge"
) -> Dict:
    """
    Module-level function for player movement processing.

    Args:
        lookback_hours: How many hours back to look for trades (default 24)
        season_year: NBA season starting year
        test_mode: If True, run in test mode
        strategy: Database strategy ("merge" only - replace not supported)

    Returns:
        Dictionary with processing results
    """
    processor = PlayerMovementRegistryProcessor(
        test_mode=test_mode,
        strategy=strategy
    )
    return processor.process_recent_trades(
        lookback_hours=lookback_hours,
        season_year=season_year
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Update player registry from recent trades"
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=24,
        help="How many hours back to look for trades (default: 24)"
    )
    parser.add_argument(
        "--season-year",
        type=int,
        help="NBA season starting year (e.g., 2025 for 2025-26)"
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run in test mode"
    )

    args = parser.parse_args()

    result = process_recent_trades(
        lookback_hours=args.lookback_hours,
        season_year=args.season_year,
        test_mode=args.test_mode
    )

    print("\nProcessing Results:")
    print(f"Status: {result.get('status')}")
    print(f"Season: {result.get('season')}")
    print(f"Trades found: {result.get('trades_found', 0)}")
    print(f"Records updated: {result.get('records_updated', 0)}")

    if result.get('players_updated'):
        print("\nPlayers updated:")
        for player in result['players_updated']:
            print(f"  - {player}")

    if result.get('status') == 'failed':
        print(f"\nError: {result.get('error')}")
