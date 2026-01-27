#!/usr/bin/env python3
"""
File: data_processors/reference/player_reference/roster_registry_processor.py

Roster Registry Processor - With Complete Data Protection

Maintains the NBA players registry from roster assignment data.
Enhanced with:
- Temporal ordering protection
- Season protection (current season only)
- Staleness detection
- Activity date tracking
- Team assignment authority rules

Refactored to use extracted modules:
- Source handlers for ESPN, NBA.com, Basketball Reference
- Validators for temporal, season, staleness, gamebook precedence
- Operations for registry CRUD
- Normalizer for aggregation and validation
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Set, Tuple, Optional
import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError
import uuid

from data_processors.reference.base.registry_processor_base import RegistryProcessorBase, TemporalOrderingError
from data_processors.reference.base.name_change_detection_mixin import NameChangeDetectionMixin
from data_processors.reference.base.database_strategies import DatabaseStrategiesMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Import extracted modules
from data_processors.reference.player_reference.sources.espn_source import ESPNSourceHandler
from data_processors.reference.player_reference.sources.nba_source import NBASourceHandler
from data_processors.reference.player_reference.sources.br_source import BRSourceHandler
from data_processors.reference.player_reference.validators.staleness_detector import StalenessDetector
from data_processors.reference.player_reference.validators.gamebook_precedence_validator import GamebookPrecedenceValidator
from data_processors.reference.player_reference.operations.registry_ops import RegistryOperations
from data_processors.reference.player_reference.operations.normalizer import RosterNormalizer

logger = logging.getLogger(__name__)

# Team abbreviation normalization (utility function)
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


class SourceDataMissingError(Exception):
    """Raised when required source data is not available for the requested date."""
    pass


class RosterRegistryProcessor(RegistryProcessorBase, NameChangeDetectionMixin, DatabaseStrategiesMixin):
    """
    Registry processor for roster assignment data.

    Creates registry records from roster data sources:
    - ESPN team rosters
    - NBA.com player list
    - Basketball Reference season rosters

    Provides early registry population before game participation.
    """

    def __init__(self, test_mode: bool = False, strategy: str = "merge",
                 confirm_full_delete: bool = False,
                 enable_name_change_detection: bool = True):
        super().__init__(test_mode, strategy, confirm_full_delete, enable_name_change_detection)

        # Set processor type for source tracking
        self.processor_type = 'roster'

        # Initialize source handlers
        self.espn_handler = ESPNSourceHandler(self.bq_client, self.project_id)
        self.nba_handler = NBASourceHandler(self.bq_client, self.project_id)
        self.br_handler = BRSourceHandler(self.bq_client, self.project_id)

        # Initialize validators
        self.staleness_detector = StalenessDetector(
            self.bq_client,
            self.project_id,
            self.table_name
        )
        self.gamebook_validator = GamebookPrecedenceValidator(
            self.bq_client,
            self.project_id,
            "nba_raw.processor_run_history"
        )

        # Initialize registry operations
        self.registry_ops = RegistryOperations(
            self.bq_client,
            self.project_id,
            self.table_name,
            "nba_reference.player_aliases",
            "nba_reference.unresolved_player_names",
            self.calculate_season_string
        )

        # Initialize normalizer (coordinates all the above)
        self.normalizer = RosterNormalizer(
            processor=self,
            source_handlers={
                'espn': self.espn_handler,
                'nba': self.nba_handler,
                'br': self.br_handler
            },
            staleness_detector=self.staleness_detector,
            registry_ops=self.registry_ops
        )

        logger.info("Initialized Roster Registry Processor with extracted modules")

    def get_current_roster_data(self, season_year: int = None, data_date: date = None,
                            allow_source_fallback: bool = False) -> Dict[str, Set[str]]:
        """
        Get roster data with strict date matching.

        Args:
            season_year: NBA season starting year
            data_date: Required date for source data
            allow_source_fallback: If True, use latest available if exact date missing

        Returns:
            Dictionary of roster sources and their players

        Raises:
            SourceDataMissingError: If required source data not available for date
        """
        if not season_year:
            current_month = date.today().month
            if current_month >= 10:
                season_year = date.today().year
            else:
                season_year = date.today().year - 1

        if not data_date:
            data_date = date.today()

        logger.info(f"Getting roster data for {season_year}-{season_year+1} season, date {data_date}")
        logger.info(f"Strict date matching: {'disabled (using fallback)' if allow_source_fallback else 'ENABLED'}")

        # Get data from each source with date checking - DELEGATED TO SOURCE HANDLERS
        espn_players, espn_date, espn_matched = self.espn_handler.get_roster_players(
            season_year, data_date, allow_source_fallback
        )

        nbacom_players, nbacom_date, nbacom_matched = self.nba_handler.get_roster_players(
            season_year, data_date, allow_source_fallback
        )

        br_players, br_date, br_matched = self.br_handler.get_roster_players(
            season_year, data_date, allow_source_fallback
        )

        # Track source dates used
        self.source_dates_used.update({
            'espn_roster_date': espn_date,
            'nbacom_source_date': nbacom_date,
            'br_scrape_date': br_date,
            'espn_matched': espn_matched,
            'nbacom_matched': nbacom_matched,
            'br_matched': br_matched,
            'used_fallback': not all([espn_matched, nbacom_matched, br_matched])
        })

        # Check if we have any data
        if len(espn_players) == 0 and len(nbacom_players) == 0 and len(br_players) == 0:
            error_msg = (
                f"No roster data available for {data_date}. "
                f"ESPN: {espn_date or 'missing'}, "
                f"NBA.com: {nbacom_date or 'missing'}, "
                f"BR: {br_date or 'missing'}"
            )
            logger.error(error_msg)

            notify_error(
                title="No Roster Data Available",
                message=f"Cannot process {data_date} - no source data found",
                details={
                    'requested_date': str(data_date),
                    'season_year': season_year,
                    'espn_date': str(espn_date) if espn_date else None,
                    'nbacom_date': str(nbacom_date) if nbacom_date else None,
                    'br_date': str(br_date) if br_date else None,
                    'allow_fallback': allow_source_fallback
                },
                processor_name="Roster Registry Processor"
            )

            raise SourceDataMissingError(error_msg)

        # Log what we got
        logger.info(f"ESPN rosters: {len(espn_players)} players (date: {espn_date}, matched: {espn_matched})")
        logger.info(f"NBA.com list: {len(nbacom_players)} players (date: {nbacom_date}, matched: {nbacom_matched})")
        logger.info(f"BR rosters: {len(br_players)} players (date: {br_date}, matched: {br_matched})")

        if self.source_dates_used['used_fallback']:
            logger.warning(
                f"⚠️ Using fallback data - not all sources matched requested date {data_date}"
            )

        roster_sources = {
            'espn_rosters': espn_players,
            'nba_player_list': nbacom_players,
            'basketball_reference': br_players
        }

        return roster_sources

    def get_existing_registry_players(self, season: str) -> Set[str]:
        """Get players already in registry for current season."""
        # DELEGATED TO REGISTRY_OPS
        return self.registry_ops.get_existing_registry_players(season)

    def aggregate_roster_assignments(self, roster_data: Dict[str, Set[str]], season_year: int,
                                data_date: date, allow_backfill: bool = False,
                                allow_source_fallback: bool = False) -> Tuple[List[Dict], Dict]:
        """
        Aggregate roster data into registry records with NBA.com validation and staleness checking.

        Args:
            roster_data: Dict of roster sources and their players
            season_year: NBA season starting year
            data_date: Date this roster data represents
            allow_backfill: If True, skip freshness checks for historical data
            allow_source_fallback: If True, use latest available data if exact date missing

        Returns:
            Tuple of (registry records, validation info dict)
        """
        # DELEGATED TO NORMALIZER
        season_str = self.calculate_season_string(season_year)
        return self.normalizer.aggregate_roster_assignments(
            roster_data,
            season_year,
            data_date,
            season_str,
            allow_backfill,
            allow_source_fallback
        )

    def check_gamebook_precedence(self, data_date: date, season_year: int) -> Tuple[bool, str]:
        """
        Check if gamebook processor has processed this date or any later date in the season.

        Args:
            data_date: The date being processed
            season_year: The season year being processed

        Returns:
            Tuple of (is_blocked: bool, reason: str)
        """
        # DELEGATED TO GAMEBOOK_VALIDATOR
        return self.gamebook_validator.check_precedence(data_date, season_year)

    def get_player_team_assignment(self, player_lookup: str, roster_data: Dict[str, Set[str]] = None) -> str:
        """
        Get team assignment for a player from roster data.

        Args:
            player_lookup: Player lookup key
            roster_data: Optional roster data dict (if None, fetches current)

        Returns:
            Team abbreviation or 'UNK' if not found
        """
        if roster_data is None:
            roster_data = self.get_current_roster_data()

        # Check NBA.com first (most authoritative)
        if player_lookup in roster_data.get('nba_player_list', set()):
            # Query for team from NBA.com
            query = """
            SELECT team_abbr
            FROM `{project}.nba_raw.nbac_player_list_current`
            WHERE player_lookup = @player_lookup
            ORDER BY source_file_date DESC
            LIMIT 1
            """.format(project=self.project_id)

            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
            ])

            try:
                results = self.bq_client.query(query, job_config=job_config).to_dataframe()
                if not results.empty:
                    return results.iloc[0]['team_abbr']
            except Exception as e:
                logger.warning(f"Error getting team for {player_lookup} from NBA.com: {e}")

        # Fallback to ESPN
        if player_lookup in roster_data.get('espn_rosters', set()):
            query = """
            SELECT team_abbr
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE player_lookup = @player_lookup
            ORDER BY roster_date DESC
            LIMIT 1
            """.format(project=self.project_id)

            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
            ])

            try:
                results = self.bq_client.query(query, job_config=job_config).to_dataframe()
                if not results.empty:
                    return results.iloc[0]['team_abbr']
            except Exception as e:
                logger.warning(f"Error getting team for {player_lookup} from ESPN: {e}")

        return 'UNK'

    def transform_data(self, raw_data: Dict, file_path: str = None) -> List[Dict]:
        """Transform roster data into registry records."""
        try:
            season_year = raw_data.get('season_year', date.today().year)
            data_date = raw_data.get('data_date', date.today())
            allow_backfill = raw_data.get('allow_backfill', False)
            allow_source_fallback = raw_data.get('allow_source_fallback', False)

            logger.info(f"Processing roster data for season {season_year}, date {data_date}")

            roster_data = self.get_current_roster_data(
                season_year,
                data_date=data_date,
                allow_source_fallback=allow_source_fallback
            )
            season_str = self.calculate_season_string(season_year)
            existing_players = self.get_existing_registry_players(season_str)

            all_roster_players = set()
            for source, players in roster_data.items():
                all_roster_players.update(players)

            logger.info(f"Found {len(all_roster_players)} total players")

            unknown_players = all_roster_players - existing_players
            if unknown_players:
                logger.info(f"Found {len(unknown_players)} unknown players")

                if len(unknown_players) > 50:
                    try:
                        notify_warning(
                            title="High Unknown Player Count",
                            message=f"Found {len(unknown_players)} new players",
                            details={
                                'season': season_str,
                                'unknown_count': len(unknown_players),
                                'sample': list(unknown_players)[:20]
                            },
                            processor_name=self.__class__.__name__
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")

            registry_records, validation_info = self.aggregate_roster_assignments(
                roster_data, season_year, data_date, allow_backfill=allow_backfill,
                allow_source_fallback=allow_source_fallback
            )

            logger.info(f"Created {len(registry_records)} registry records")

            self.validation_info = validation_info

            return registry_records

        except Exception as e:
            logger.error(f"Transform data failed: {e}")
            try:
                notify_error(
                    title="Roster Registry Transform Failed",
                    message=f"Failed to transform: {str(e)}",
                    details={
                        'season_year': raw_data.get('season_year'),
                        'error_type': type(e).__name__
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def _build_registry_for_season_impl(self, season: str, team: str = None,
                                   data_date: date = None, allow_backfill: bool = False,
                                   allow_source_fallback: bool = False) -> Dict:
        """Implementation of season building with source fallback support."""
        logger.info(f"Building roster registry for season {season}")

        try:
            self.new_players_discovered = set()
            self.players_seen_this_run = set()

            self.stats = {
                'players_processed': 0,
                'records_created': 0,
                'records_updated': 0,
                'seasons_processed': set(),
                'teams_processed': set(),
                'unresolved_players_found': 0,
                'alias_resolutions': 0
            }

            season_year = int(season.split('-')[0])
            data_date = data_date or date.today()

            filter_data = {
                'season_year': season_year,
                'data_date': data_date,
                'allow_backfill': allow_backfill,
                'allow_source_fallback': allow_source_fallback
            }

            rows = self.transform_data(filter_data)
            result = self.save_registry_data(rows)

            if hasattr(self, 'validation_info'):
                result.update(self.validation_info)

            result['new_players_discovered'] = list(self.new_players_discovered)
            if self.new_players_discovered:
                logger.info(f"Discovered {len(self.new_players_discovered)} new players")

            logger.info(f"Roster registry build complete for {season}")
            logger.info(f"  Records processed: {result['rows_processed']}")
            logger.info(f"  Records created: {len(rows)}")

            return {
                'season': season,
                'team_filter': team,
                'records_processed': result['rows_processed'],
                'records_created': len(rows),
                'players_processed': len(rows),
                'teams_processed': list(set(row['team_abbr'] for row in rows)) if rows else [],
                'new_players_discovered': result['new_players_discovered'],
                'validation_mode': result.get('validation_mode'),
                'validation_skipped_reason': result.get('validation_skipped_reason'),
                'source_data_freshness_days': result.get('source_data_freshness_days'),
                'errors': result.get('errors', []),
                'processing_run_id': self.processing_run_id
            }

        except Exception as e:
            logger.error(f"Failed to build roster registry: {e}")
            try:
                notify_error(
                    title="Roster Registry Build Failed",
                    message=f"Failed to build: {str(e)}",
                    details={
                        'season': season,
                        'error_type': type(e).__name__
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def process_daily_rosters(self, season_year: int = None, data_date: date = None,
                         allow_backfill: bool = False,
                         allow_source_fallback: bool = False) -> Dict:
        """
        Process daily roster updates with complete protection and strict date matching.

        Main entry point for daily processing after roster scrapers complete.

        Args:
            season_year: NBA season starting year (defaults to current season)
            data_date: Date to process (defaults to today)
            allow_backfill: If True, allow processing earlier dates (insert-only mode)
            allow_source_fallback: If True, use latest available data if exact date missing

        Returns:
            Dict with processing results and status
        """
        if not season_year:
            current_month = date.today().month
            if current_month >= 10:
                season_year = date.today().year
            else:
                season_year = date.today().year - 1

        if not data_date:
            data_date = date.today()

        season_str = self.calculate_season_string(season_year)
        logger.info(f"Processing daily rosters for {season_str}, date {data_date}")
        logger.info(f"Strict date matching: {'disabled (using fallback)' if allow_source_fallback else 'ENABLED'}")

        # =======================================================================
        # PROTECTION 1: Season Protection - Don't process historical seasons
        # =======================================================================
        current_season_year = date.today().year if date.today().month >= 10 else date.today().year - 1
        if season_year < current_season_year and not allow_backfill:
            error_msg = (
                f"Cannot process historical season {season_year}-{season_year+1}. "
                f"Current season is {current_season_year}-{current_season_year+1}. "
                f"Roster processor is for current season only. "
                f"Use --allow-backfill flag only if you need to fix historical roster data."
            )
            logger.error(error_msg)
            return {
                'status': 'blocked',
                'reason': error_msg,
                'season': season_str,
                'protection_layer': 'season_protection'
            }

        # =======================================================================
        # PROTECTION 2: Gamebook Precedence - Don't override gamebook data
        # =======================================================================
        is_blocked, block_reason = self.check_gamebook_precedence(data_date, season_year)
        if is_blocked:
            logger.error(f"Roster processing blocked by gamebook precedence: {block_reason}")
            return {
                'status': 'blocked',
                'reason': block_reason,
                'season': season_str,
                'data_date': str(data_date),
                'protection_layer': 'gamebook_precedence'
            }

        # =======================================================================
        # PROCESS
        # =======================================================================
        try:
            result = self._build_registry_for_season_impl(
                season=season_str,
                data_date=data_date,
                allow_backfill=allow_backfill,
                allow_source_fallback=allow_source_fallback
            )

            result['status'] = 'success'
            result['data_date'] = str(data_date)

            # Log source dates used
            if hasattr(self, 'source_dates_used'):
                logger.info("Source dates used:")
                for key, value in self.source_dates_used.items():
                    logger.info(f"  {key}: {value}")
                result['source_dates_used'] = self.source_dates_used

            return result

        except SourceDataMissingError as e:
            logger.error(f"Source data missing: {e}")
            return {
                'status': 'failed',
                'reason': str(e),
                'season': season_str,
                'data_date': str(data_date),
                'error_type': 'source_data_missing'
            }
        except TemporalOrderingError as e:
            logger.error(f"Temporal ordering violation: {e}")
            return {
                'status': 'blocked',
                'reason': str(e),
                'season': season_str,
                'data_date': str(data_date),
                'protection_layer': 'temporal_ordering'
            }
        except Exception as e:
            logger.error(f"Failed to process daily rosters: {e}")
            try:
                notify_error(
                    title="Daily Roster Processing Failed",
                    message=f"Failed to process: {str(e)}",
                    details={
                        'season': season_str,
                        'data_date': str(data_date),
                        'error_type': type(e).__name__
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            return {
                'status': 'failed',
                'reason': str(e),
                'season': season_str,
                'data_date': str(data_date),
                'error_type': type(e).__name__
            }

    def build_historical_registry(self, seasons: List[str] = None) -> Dict:
        """
        Build registry for historical seasons from roster data.

        Args:
            seasons: List of season strings (e.g., ["2023-2024", "2024-2025"])

        Returns:
            Dictionary with processing results
        """
        if not seasons:
            current_season_year = date.today().year if date.today().month >= 10 else date.today().year - 1
            seasons = [self.calculate_season_string(current_season_year)]

        results = {
            'seasons_processed': [],
            'total_records': 0,
            'errors': []
        }

        for season in seasons:
            try:
                logger.info(f"Building historical registry for {season}")
                result = self._build_registry_for_season_impl(
                    season=season,
                    allow_backfill=True,  # Historical data
                    allow_source_fallback=True  # Use available data
                )
                results['seasons_processed'].append(season)
                results['total_records'] += result.get('records_processed', 0)
            except Exception as e:
                logger.error(f"Failed to build historical registry for {season}: {e}")
                results['errors'].append({
                    'season': season,
                    'error': str(e)
                })

        return results


def process_daily_rosters(season_year: int = None, data_date: date = None,
                          allow_backfill: bool = False,
                          allow_source_fallback: bool = False,
                          test_mode: bool = False,
                          strategy: str = "merge") -> Dict:
    """
    Module-level function for daily roster processing.

    Args:
        season_year: NBA season starting year
        data_date: Date to process
        allow_backfill: If True, allow processing earlier dates
        allow_source_fallback: If True, use latest available if exact date missing
        test_mode: If True, run in test mode
        strategy: Database strategy ("merge" or "replace")

    Returns:
        Dictionary with processing results
    """
    processor = RosterRegistryProcessor(test_mode=test_mode, strategy=strategy)
    return processor.process_daily_rosters(
        season_year=season_year,
        data_date=data_date,
        allow_backfill=allow_backfill,
        allow_source_fallback=allow_source_fallback
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Process daily roster data")
    parser.add_argument("--season-year", type=int, help="NBA season starting year")
    parser.add_argument("--date", type=str, help="Date to process (YYYY-MM-DD)")
    parser.add_argument("--allow-backfill", action="store_true",
                       help="Allow processing historical dates")
    parser.add_argument("--allow-source-fallback", action="store_true",
                       help="Use latest available data if exact date missing")
    parser.add_argument("--test-mode", action="store_true",
                       help="Run in test mode")

    args = parser.parse_args()

    data_date = None
    if args.date:
        data_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    result = process_daily_rosters(
        season_year=args.season_year,
        data_date=data_date,
        allow_backfill=args.allow_backfill,
        allow_source_fallback=args.allow_source_fallback,
        test_mode=args.test_mode
    )

    print("\nProcessing Results:")
    print(f"Status: {result.get('status')}")
    if result.get('status') == 'success':
        print(f"Records processed: {result.get('records_processed')}")
        print(f"Season: {result.get('season')}")
    else:
        print(f"Reason: {result.get('reason')}")
