#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/loaders/game_data_loaders.py

Game Data Loader - Extracted from upcoming_player_game_context_processor.py

This module contains game data extraction methods that were moved out of the main
processor to reduce file size and improve maintainability.

Methods extracted:
- _extract_schedule_data() (~97 lines)
- _extract_historical_boxscores() (~77 lines)
- _extract_prop_lines() (~30 lines)
- _extract_game_lines() (~58 lines)
- _extract_rosters() (~71 lines)
- _extract_injuries() (~125 lines)
- _extract_registry() (~45 lines)
"""

import logging
from datetime import datetime, timedelta, timezone, date
from typing import Dict, List, Optional
import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded

# Import utilities
from shared.utils.nba_team_mapper import get_nba_team_mapper, get_team_info
from shared.utils.player_registry import RegistryReader
from ..player_stats import parse_minutes

logger = logging.getLogger(__name__)


class GameDataLoader:
    """
    Handles extraction of game-related data for upcoming game context processing.

    This class contains methods for extracting schedule, historical stats,
    betting lines, rosters, injuries, and player registry data.
    """

    def __init__(self, bq_client, project_id, target_date, lookback_days=30):
        """
        Initialize the game data loader.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            target_date: Date to process (date object)
            lookback_days: Number of days to look back for historical data
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.target_date = target_date
        self.lookback_days = lookback_days

        # Data holders (populated by extraction methods)
        self.schedule_data = {}
        self.historical_boxscores = {}
        self.prop_lines = {}
        self.game_lines = {}
        self.rosters = {}
        self.roster_ages = {}
        self.injuries = {}
        self.registry = {}

        # Source tracking
        self.source_tracking = {
            'schedule': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'boxscore': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'game_lines': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'injuries': {'last_updated': None, 'rows_found': 0, 'players_with_status': 0}
        }

        # Registry reader for universal player ID lookup
        self.registry_reader = RegistryReader(
            source_name='upcoming_player_game_context',
            cache_ttl_seconds=300
        )
        self.registry_stats = {
            'players_found': 0,
            'players_not_found': 0
        }

    def _extract_schedule_data(self, players_to_process: List[Dict]) -> None:
        """
        Extract schedule data for all games on target date.

        Used for:
        - Determining home/away
        - Game start times
        - Back-to-back detection (requires looking at surrounding dates)

        Args:
            players_to_process: List of player dicts with game_id
        """
        game_ids = list(set([p['game_id'] for p in players_to_process if p.get('game_id')]))

        # Get schedule for target date plus surrounding dates for back-to-back detection
        start_date = self.target_date - timedelta(days=5)
        end_date = self.target_date + timedelta(days=5)

        # FIXED: Use standard game_id format (YYYYMMDD_AWAY_HOME) instead of NBA official ID
        query = f"""
        SELECT
            CONCAT(
                FORMAT_DATE('%Y%m%d', game_date),
                '_',
                away_team_tricode,
                '_',
                home_team_tricode
            ) as game_id,
            game_date,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr,
            game_date_est,
            is_primetime,
            season_year
        FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date >= @start_date
          AND game_date <= @end_date
        ORDER BY game_date, game_date_est
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()

            # Track source usage (count only target date games)
            target_games = df[df['game_date'] == self.target_date]
            self.source_tracking['schedule']['rows_found'] = len(target_games)
            self.source_tracking['schedule']['last_updated'] = datetime.now(timezone.utc)

            # Use NBATeamMapper for comprehensive abbreviation handling
            team_mapper = get_nba_team_mapper()

            def get_all_abbr_variants(abbr: str) -> list:
                """Return all known abbreviation variants for a team using NBATeamMapper."""
                team_info = get_team_info(abbr)
                if team_info:
                    # Return all tricode variants (nba, br, espn)
                    variants = list(set([
                        team_info.nba_tricode,
                        team_info.br_tricode,
                        team_info.espn_tricode
                    ]))
                    return variants
                # Fallback: just return the original
                return [abbr]

            # Store schedule data by game_id (vectorized)
            # ALSO create lookups using date-based format (YYYYMMDD_AWAY_HOME) to match props table
            for row in df.itertuples():
                row_dict = df.loc[row.Index].to_dict()
                # Store with official NBA game_id
                self.schedule_data[row.game_id] = row_dict

                # Create all variant game_id keys to handle inconsistent abbreviations
                game_date_str = str(row.game_date).replace('-', '')
                away_variants = get_all_abbr_variants(row.away_team_abbr)
                home_variants = get_all_abbr_variants(row.home_team_abbr)

                # Store all combinations of away/home abbreviation variants
                for away_abbr in away_variants:
                    for home_abbr in home_variants:
                        date_based_id = f"{game_date_str}_{away_abbr}_{home_abbr}"
                        self.schedule_data[date_based_id] = row_dict

            logger.info(f"Extracted schedule for {len(target_games)} games on {self.target_date}")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting schedule data: {e}")
            self.source_tracking['schedule']['rows_found'] = 0
            raise
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting schedule data: {e}")
            self.source_tracking['schedule']['rows_found'] = 0
            raise

    def _extract_historical_boxscores(self, players_to_process: List[Dict]) -> None:
        """
        Extract historical boxscores for all players (last 30 days).

        Priority:
        1. nba_raw.bdl_player_boxscores (PRIMARY)
        2. nba_raw.nbac_player_boxscores (fallback)
        3. nba_raw.nbac_gamebook_player_stats (last resort)

        Args:
            players_to_process: List of player dicts with player_lookup
        """
        player_lookups = [p['player_lookup'] for p in players_to_process]

        start_date = self.target_date - timedelta(days=self.lookback_days)

        # Try BDL first (PRIMARY), enriched with usage_rate from player_game_summary
        # Session 52: Added LEFT JOIN with player_game_summary to get usage_rate
        # which is needed for avg_usage_rate_last_7_games calculation
        query = f"""
        SELECT
            bdl.player_lookup,
            bdl.game_date,
            bdl.team_abbr,
            bdl.points,
            bdl.minutes,
            bdl.assists,
            bdl.rebounds,
            bdl.field_goals_made,
            bdl.field_goals_attempted,
            bdl.three_pointers_made,
            bdl.three_pointers_attempted,
            bdl.free_throws_made,
            bdl.free_throws_attempted,
            pgs.usage_rate
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores` bdl
        LEFT JOIN `{self.project_id}.nba_analytics.player_game_summary` pgs
          ON bdl.player_lookup = pgs.player_lookup AND bdl.game_date = pgs.game_date
        WHERE bdl.player_lookup IN UNNEST(@player_lookups)
          AND bdl.game_date >= @start_date
          AND bdl.game_date < @target_date
        ORDER BY bdl.player_lookup, bdl.game_date DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("target_date", "DATE", self.target_date),
            ]
        )

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()

            # Convert minutes string to decimal
            if 'minutes' in df.columns:
                df['minutes_decimal'] = df['minutes'].apply(parse_minutes)
            else:
                df['minutes_decimal'] = 0.0

            # Track source usage
            self.source_tracking['boxscore']['rows_found'] = len(df)
            self.source_tracking['boxscore']['last_updated'] = datetime.now(timezone.utc)

            # FIX: Handle empty DataFrame properly to avoid KeyError
            # Store by player_lookup
            for player_lookup in player_lookups:
                if df.empty or 'player_lookup' not in df.columns:
                    # No data available - store empty DataFrame
                    self.historical_boxscores[player_lookup] = pd.DataFrame()
                else:
                    player_data = df[df['player_lookup'] == player_lookup].copy()
                    self.historical_boxscores[player_lookup] = player_data

            logger.info(f"Extracted {len(df)} historical boxscore records for {len(player_lookups)} players")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting historical boxscores: {e}")
            self.source_tracking['boxscore']['rows_found'] = 0
            raise
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting historical boxscores: {e}")
            self.source_tracking['boxscore']['rows_found'] = 0
            raise

    def _extract_prop_lines(self, players_to_process: List[Dict], betting_extractor) -> None:
        """
        Extract prop lines (opening and current) for each player.

        Opening line: Earliest snapshot
        Current line: Most recent snapshot

        FALLBACK LOGIC (v3.1):
        - Uses same source as driver query (self._props_source)
        - Odds API has snapshot_timestamp for line history
        - BettingPros has opening_line field and bookmaker_last_update

        Args:
            players_to_process: List of player dicts with player_lookup and game_id
            betting_extractor: BettingDataExtractor instance from processor
        """
        player_game_pairs = [(p['player_lookup'], p['game_id']) for p in players_to_process]

        # Use the same source as the driver query (need to get from parent)
        # For now, default to odds_api - caller should pass _props_source
        use_bettingpros = getattr(self, '_props_source', 'odds_api') == 'bettingpros'

        if use_bettingpros:
            logger.info(f"Extracting prop lines from BettingPros for {len(player_game_pairs)} players")
            self.prop_lines = betting_extractor.extract_prop_lines_from_bettingpros(
                player_game_pairs, self.target_date
            )
        else:
            logger.info(f"Extracting prop lines from Odds API for {len(player_game_pairs)} players")
            self.prop_lines = betting_extractor.extract_prop_lines_from_odds_api(
                player_game_pairs, self.target_date
            )

    def _extract_game_lines(self, players_to_process: List[Dict], betting_extractor) -> None:
        """
        Extract game lines (spreads and totals) for each game.

        Uses consensus (median) across all bookmakers.
        Opening: Earliest snapshot
        Current: Most recent snapshot

        Args:
            players_to_process: List of player dicts with game_id
            betting_extractor: BettingDataExtractor instance from processor
        """
        game_ids = list(set([p['game_id'] for p in players_to_process]))

        for game_id in game_ids:
            try:
                # Get spread consensus
                spread_info = betting_extractor.get_game_line_consensus(
                    game_id, 'spreads', self.target_date, self.schedule_data
                )

                # Get total consensus
                total_info = betting_extractor.get_game_line_consensus(
                    game_id, 'totals', self.target_date, self.schedule_data
                )

                self.game_lines[game_id] = {
                    **spread_info,
                    **total_info
                }

                # Track source usage
                self.source_tracking['game_lines']['rows_found'] += 1

            except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
                logger.warning(f"BigQuery error extracting game lines for {game_id}: {e}")
                self.game_lines[game_id] = {
                    'game_spread': None,
                    'opening_spread': None,
                    'spread_movement': None,
                    'spread_source': None,
                    'game_total': None,
                    'opening_total': None,
                    'total_movement': None,
                    'total_source': None
                }
            except (KeyError, AttributeError, TypeError) as e:
                logger.warning(f"Data error extracting game lines for {game_id}: {e}")
                self.game_lines[game_id] = {
                    'game_spread': None,
                    'opening_spread': None,
                    'spread_movement': None,
                    'spread_source': None,
                    'game_total': None,
                    'opening_total': None,
                    'total_movement': None,
                    'total_source': None
                }

        self.source_tracking['game_lines']['last_updated'] = datetime.now(timezone.utc)

    def _extract_rosters(self, players_to_process: List[Dict]) -> None:
        """
        Extract current roster data including player age.

        Loads the latest roster data from espn_team_rosters for player demographics.
        Stores in self.roster_ages as {player_lookup: age}.

        Args:
            players_to_process: List of player dicts with player_lookup
        """
        if not players_to_process:
            logger.info("No players to lookup roster data for")
            return

        unique_players = list(set(p['player_lookup'] for p in players_to_process))
        logger.info(f"Extracting roster data for {len(unique_players)} players")

        # Query for latest roster entry per player with age
        query = f"""
            WITH latest_roster AS (
                SELECT
                    player_lookup,
                    age,
                    birth_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_lookup
                        ORDER BY roster_date DESC, scrape_hour DESC
                    ) as rn
                FROM `{self.project_id}.nba_raw.espn_team_rosters`
                WHERE roster_date <= @target_date
                  AND player_lookup IN UNNEST(@player_lookups)
            )
            SELECT player_lookup, age, birth_date
            FROM latest_roster
            WHERE rn = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("target_date", "DATE", self.target_date),
                bigquery.ArrayQueryParameter("player_lookups", "STRING", unique_players),
            ]
        )

        try:
            results = self.bq_client.query(query, job_config=job_config).result()

            for row in results:
                player_lookup = row.player_lookup
                age = row.age

                # If age is None but birth_date exists, calculate age
                if age is None and row.birth_date:
                    try:
                        birth = row.birth_date
                        if isinstance(birth, str):
                            birth = date.fromisoformat(birth)
                        age = (self.target_date - birth).days // 365
                    except (ValueError, TypeError, AttributeError):
                        pass

                if age is not None:
                    self.roster_ages[player_lookup] = age

            logger.info(f"Loaded roster ages for {len(self.roster_ages)} players")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error loading roster data: {e}")
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error loading roster data: {e}")

    def _extract_injuries(self, players_to_process: List[Dict]) -> None:
        """
        Extract injury report data from NBA.com injury report.

        Gets the latest injury status for each player for the target game date.
        Stores results in self.injuries as {player_lookup: {'status': ..., 'report': ...}}.

        Args:
            players_to_process: List of player dicts with player_lookup
        """
        if not players_to_process:
            logger.info("No players to lookup injuries for")
            return

        # Get unique player lookups for matching
        unique_players = list(set(p['player_lookup'] for p in players_to_process))

        logger.info(f"Extracting injury data for {len(unique_players)} players")

        query = f"""
        WITH latest_report AS (
            SELECT
                player_lookup,
                injury_status,
                reason,
                reason_category,
                report_date,
                processed_at,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_date DESC, processed_at DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.nbac_injury_report`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date = @target_date
        )
        SELECT
            player_lookup,
            injury_status,
            reason,
            reason_category,
            processed_at
        FROM latest_report
        WHERE rn = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", unique_players),
                bigquery.ScalarQueryParameter("target_date", "DATE", self.target_date.isoformat()),
            ]
        )

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if df.empty:
                logger.info("No injury report data found for target date")
                self.source_tracking['injuries'] = {
                    'last_updated': None,
                    'rows_found': 0,
                    'players_with_status': 0
                }
                return

            # Track latest update time for source tracking
            latest_processed = df['processed_at'].max() if 'processed_at' in df.columns else None

            # Build injuries dict (vectorized with apply)
            def build_report(row):
                """Build meaningful report string from reason fields."""
                reason = row['reason']
                reason_category = row['reason_category']

                if reason and str(reason).lower() not in ('unknown', 'nan', 'none', ''):
                    return reason
                elif reason_category and str(reason_category).lower() not in ('unknown', 'nan', 'none', ''):
                    return reason_category
                return None

            # Create report column
            df['report'] = df.apply(build_report, axis=1)

            # Build injuries dict from DataFrame
            self.injuries = {
                row.player_lookup: {
                    'status': row.injury_status,
                    'report': row.report
                }
                for row in df.itertuples()
            }

            # Log summary by status
            status_counts = {}
            for info in self.injuries.values():
                status = info['status']
                status_counts[status] = status_counts.get(status, 0) + 1

            logger.info(
                f"Extracted injury data for {len(self.injuries)} players: "
                f"{', '.join(f'{k}={v}' for k, v in sorted(status_counts.items()))}"
            )

            # Track in source_tracking for observability
            self.source_tracking['injuries'] = {
                'last_updated': latest_processed,
                'rows_found': len(df),
                'players_with_status': len(self.injuries),
                'status_breakdown': status_counts
            }

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error extracting injury data: {e}. Continuing without injury info.")
            self.source_tracking['injuries'] = {
                'last_updated': None,
                'rows_found': 0,
                'players_with_status': 0,
                'error': str(e)
            }
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error extracting injury data: {e}. Continuing without injury info.")
            self.source_tracking['injuries'] = {
                'last_updated': None,
                'rows_found': 0,
                'players_with_status': 0,
                'error': str(e)
            }

    def _extract_registry(self, players_to_process: List[Dict]) -> None:
        """
        Extract universal player IDs from registry using batch lookup.

        Populates self.registry dict with {player_lookup: universal_player_id}.
        Uses RegistryReader for efficient batch lookups with caching.

        Args:
            players_to_process: List of player dicts with player_lookup
        """
        if not players_to_process:
            logger.info("No players to lookup in registry")
            return

        # Get unique player lookups
        unique_players = list(set(p['player_lookup'] for p in players_to_process))
        logger.info(f"Looking up {len(unique_players)} unique players in registry")

        try:
            # Batch lookup all players at once
            uid_map = self.registry_reader.get_universal_ids_batch(
                unique_players,
                skip_unresolved_logging=True
            )

            # Store results in self.registry
            self.registry = uid_map

            # Track stats
            self.registry_stats['players_found'] = len(uid_map)
            self.registry_stats['players_not_found'] = len(unique_players) - len(uid_map)

            logger.info(
                f"Registry lookup complete: {self.registry_stats['players_found']} found, "
                f"{self.registry_stats['players_not_found']} not found"
            )

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error in registry lookup: {e}. Continuing without universal IDs.")
            self.registry = {}
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error in registry lookup: {e}. Continuing without universal IDs.")
            self.registry = {}
