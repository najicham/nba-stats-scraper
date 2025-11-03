#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py

Upcoming Player Game Context Processor - Phase 3 Analytics

Generates comprehensive pre-game context for each player with a prop bet available.
Combines historical performance, fatigue metrics, prop betting context, and game
situation factors.

FIXES IN THIS VERSION:
- Fixed KeyError when handling players with no historical data (empty DataFrame)
- Made error return dict consistent with success return (includes 'players_failed')
- Fixed deprecation warnings (datetime.utcnow() → datetime.now(timezone.utc))
- Added timezone import

Input: Phase 2 raw tables only
  - nba_raw.odds_api_player_points_props (DRIVER - which players to process)
  - nba_raw.bdl_player_boxscores (PRIMARY - historical performance)
  - nba_raw.nbac_schedule (game timing and context)
  - nba_raw.odds_api_game_lines (spreads, totals)
  - nba_raw.espn_team_rosters (optional - current team)
  - nba_raw.nbac_injury_report (optional - injury status)
  - nba_reference.nba_players_registry (optional - universal player ID)

Output: nba_analytics.upcoming_player_game_context
Strategy: MERGE_UPDATE (update existing or insert new)
Frequency: Multiple times per day (morning, updates throughout day, pre-game)

Key Features:
- Calculates rest days, back-to-backs, fatigue metrics from schedule
- Aggregates historical performance (last 5, last 10, last 30 days)
- Tracks prop line movement (opening vs current)
- Calculates game situation context (spreads, totals, competitiveness)
- Handles rookies, limited history, missing data gracefully
- Quality flags for data completeness and confidence
"""

import logging
import os
import re
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery
import pandas as pd
import numpy as np

from data_processors.analytics.analytics_base import AnalyticsProcessorBase

logger = logging.getLogger(__name__)


class UpcomingPlayerGameContextProcessor(AnalyticsProcessorBase):
    """
    Process upcoming player game context from Phase 2 raw data.
    
    This processor creates pre-game context records for every player who has
    a points prop bet available. It combines historical performance, fatigue
    analysis, prop betting context, and game situation factors.
    
    Phase 3 Analytics Processor - depends only on Phase 2 raw tables
    """
    
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_analytics.upcoming_player_game_context'
        self.processing_strategy = 'MERGE_UPDATE'
        self.entity_type = 'player'
        self.entity_field = 'player_lookup'
        
        # CRITICAL: Initialize BigQuery client and project ID
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Configuration
        self.lookback_days = 30  # Historical data window
        self.min_games_for_high_quality = 10
        self.min_games_for_medium_quality = 5
        self.min_bookmakers_required = 3  # For consensus calculations
        
        # Data holders
        self.target_date = None
        self.players_to_process = []  # List of (player_lookup, game_id, team_abbr)
        self.historical_boxscores = {}  # player_lookup -> DataFrame
        self.schedule_data = {}  # game_id -> game info
        self.prop_lines = {}  # (player_lookup, game_id) -> prop info
        self.game_lines = {}  # game_id -> lines info
        self.rosters = {}  # player_lookup -> roster info
        self.injuries = {}  # player_lookup -> injury info
        self.registry = {}  # player_lookup -> universal_player_id
        
        # Source tracking (for dependency tracking pattern)
        self.source_tracking = {
            'boxscore': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'schedule': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'props': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'game_lines': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None}
        }
        
        # Processing results
        self.transformed_data = []
        self.failed_entities = []
    
    def get_dependencies(self) -> dict:
        """
        Define Phase 2 raw table dependencies.
        
        Note: Phase 3 analytics processors track raw sources but don't use
        the full dependency checking framework (that's for Phase 4 precompute).
        This method documents our Phase 2 sources for reference.
        """
        return {
            'nba_raw.odds_api_player_points_props': {
                'field_prefix': 'source_props',
                'description': 'Player prop bets (DRIVER - determines which players to process)',
                'critical': True,
                'check_type': 'date_match'
            },
            'nba_raw.bdl_player_boxscores': {
                'field_prefix': 'source_boxscore',
                'description': 'Historical player performance (last 30 days)',
                'critical': True,
                'check_type': 'lookback_days',
                'lookback_days': 30
            },
            'nba_raw.nbac_schedule': {
                'field_prefix': 'source_schedule',
                'description': 'Game schedule and timing',
                'critical': True,
                'check_type': 'date_match'
            },
            'nba_raw.odds_api_game_lines': {
                'field_prefix': 'source_game_lines',
                'description': 'Game spreads and totals',
                'critical': True,
                'check_type': 'date_match'
            }
        }
    
    def process_date(self, target_date: date, **kwargs) -> Dict:
        """
        Process all players with props for a specific date.
        
        Args:
            target_date: Date to process (game date)
            
        Returns:
            Dict with processing results
        """
        self.target_date = target_date
        logger.info(f"Processing upcoming player game context for {target_date}")
        
        try:
            # Step 1: Extract data from Phase 2 sources
            self.extract_raw_data()
            
            # Step 2: Calculate context for each player
            self.calculate_analytics()
            
            # Step 3: Save to BigQuery
            success = self.save_analytics()
            
            # Log results
            logger.info(f"Successfully processed {len(self.transformed_data)} players")
            if self.failed_entities:
                logger.warning(f"Failed to process {len(self.failed_entities)} players")
            
            return {
                'status': 'success' if success else 'failed',
                'date': target_date.isoformat(),
                'players_processed': len(self.transformed_data),
                'players_failed': len(self.failed_entities),
                'errors': [e['reason'] for e in self.failed_entities]
            }
            
        except Exception as e:
            logger.error(f"Error processing date {target_date}: {e}", exc_info=True)
            return {
                'status': 'error',
                'date': target_date.isoformat(),
                'error': str(e),
                'players_processed': 0,
                'players_failed': 0  # FIX: Include this field for consistency
            }
    
    def extract_raw_data(self) -> None:
        """
        Extract data from all Phase 2 raw sources.
        
        Order of operations:
        1. Get players with props (DRIVER)
        2. Get schedule data
        3. Get historical boxscores
        4. Get prop lines (opening + current)
        5. Get game lines (spreads + totals)
        6. Get optional data (rosters, injuries, registry)
        """
        logger.info(f"Extracting raw data for {self.target_date}")
        
        # Step 1: Get players with props (DRIVER)
        self._extract_players_with_props()
        
        if not self.players_to_process:
            logger.warning(f"No players with props found for {self.target_date}")
            return
        
        logger.info(f"Found {len(self.players_to_process)} players with props")
        
        # Step 2: Get schedule data
        self._extract_schedule_data()
        
        # Step 3: Get historical boxscores
        self._extract_historical_boxscores()
        
        # Step 4: Get prop lines
        self._extract_prop_lines()
        
        # Step 5: Get game lines
        self._extract_game_lines()
        
        # Step 6: Get optional data
        self._extract_rosters()
        self._extract_injuries()
        self._extract_registry()
        
        logger.info("Data extraction complete")
    
    def _extract_players_with_props(self) -> None:
        """
        Extract all players who have prop bets for target date.
        
        This is the DRIVER query - determines which players to process.
        Uses the most recent prop snapshot for the target date.
        """
        query = f"""
        WITH latest_props AS (
            SELECT 
                player_lookup,
                game_id,
                game_date,
                home_team_abbr,
                away_team_abbr,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_id 
                    ORDER BY snapshot_timestamp DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = '{self.target_date}'
              AND player_lookup IS NOT NULL
        )
        SELECT DISTINCT
            player_lookup,
            game_id,
            game_date,
            home_team_abbr,
            away_team_abbr
        FROM latest_props
        WHERE rn = 1
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            
            # Track source usage (FIX: use timezone-aware datetime)
            self.source_tracking['props']['rows_found'] = len(df)
            self.source_tracking['props']['last_updated'] = datetime.now(timezone.utc)
            
            # Store players to process (need to determine team_abbr later)
            for _, row in df.iterrows():
                self.players_to_process.append({
                    'player_lookup': row['player_lookup'],
                    'game_id': row['game_id'],
                    'home_team_abbr': row['home_team_abbr'],
                    'away_team_abbr': row['away_team_abbr']
                })
            
            logger.info(f"Found {len(self.players_to_process)} players with props")
            
        except Exception as e:
            logger.error(f"Error extracting players with props: {e}")
            self.source_tracking['props']['rows_found'] = 0
            raise
    
    def _extract_schedule_data(self) -> None:
        """
        Extract schedule data for all games on target date.
        
        Used for:
        - Determining home/away
        - Game start times
        - Back-to-back detection (requires looking at surrounding dates)
        """
        game_ids = list(set([p['game_id'] for p in self.players_to_process]))
        game_ids_str = "', '".join(game_ids)
        
        # Get schedule for target date plus surrounding dates for back-to-back detection
        start_date = self.target_date - timedelta(days=5)
        end_date = self.target_date + timedelta(days=5)
        
        query = f"""
        SELECT 
            game_id,
            game_date,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr,
            game_date_est,
            is_primetime,
            season_year
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        ORDER BY game_date, game_date_est
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            
            # Track source usage (count only target date games)
            # FIX: use timezone-aware datetime
            target_games = df[df['game_date'] == self.target_date]
            self.source_tracking['schedule']['rows_found'] = len(target_games)
            self.source_tracking['schedule']['last_updated'] = datetime.now(timezone.utc)
            
            # Store schedule data by game_id
            for _, row in df.iterrows():
                self.schedule_data[row['game_id']] = row.to_dict()
            
            logger.info(f"Extracted schedule for {len(target_games)} games on {self.target_date}")
            
        except Exception as e:
            logger.error(f"Error extracting schedule data: {e}")
            self.source_tracking['schedule']['rows_found'] = 0
            raise
    
    def _extract_historical_boxscores(self) -> None:
        """
        Extract historical boxscores for all players (last 30 days).
        
        Priority:
        1. nba_raw.bdl_player_boxscores (PRIMARY)
        2. nba_raw.nbac_player_boxscores (fallback)
        3. nba_raw.nbac_gamebook_player_stats (last resort)
        """
        player_lookups = [p['player_lookup'] for p in self.players_to_process]
        player_lookups_str = "', '".join(player_lookups)
        
        start_date = self.target_date - timedelta(days=self.lookback_days)
        
        # Try BDL first (PRIMARY)
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            team_abbr,
            points,
            minutes,
            assists,
            rebounds,
            field_goals_made,
            field_goals_attempted,
            three_pointers_made,
            three_pointers_attempted,
            free_throws_made,
            free_throws_attempted
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE player_lookup IN ('{player_lookups_str}')
          AND game_date >= '{start_date}'
          AND game_date < '{self.target_date}'
        ORDER BY player_lookup, game_date DESC
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            
            # Convert minutes string to decimal
            if 'minutes' in df.columns:
                df['minutes_decimal'] = df['minutes'].apply(self._parse_minutes)
            else:
                df['minutes_decimal'] = 0.0
            
            # Track source usage (FIX: use timezone-aware datetime)
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
            
            # TODO: Implement fallback to nbac_player_boxscores if BDL insufficient
            # TODO: Implement last resort fallback to nbac_gamebook_player_stats
            
        except Exception as e:
            logger.error(f"Error extracting historical boxscores: {e}")
            self.source_tracking['boxscore']['rows_found'] = 0
            raise
    
    def _extract_prop_lines(self) -> None:
        """
        Extract prop lines (opening and current) for each player.
        
        Opening line: Earliest snapshot
        Current line: Most recent snapshot
        """
        player_game_pairs = [(p['player_lookup'], p['game_id']) for p in self.players_to_process]
        
        for player_lookup, game_id in player_game_pairs:
            # Get opening line (earliest snapshot)
            opening_query = f"""
            SELECT 
                points_line,
                bookmaker,
                snapshot_timestamp
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE player_lookup = '{player_lookup}'
              AND game_id = '{game_id}'
              AND game_date = '{self.target_date}'
            ORDER BY snapshot_timestamp ASC
            LIMIT 1
            """
            
            # Get current line (latest snapshot)
            current_query = f"""
            SELECT 
                points_line,
                bookmaker,
                snapshot_timestamp
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE player_lookup = '{player_lookup}'
              AND game_id = '{game_id}'
              AND game_date = '{self.target_date}'
            ORDER BY snapshot_timestamp DESC
            LIMIT 1
            """
            
            try:
                opening_df = self.bq_client.query(opening_query).to_dataframe()
                current_df = self.bq_client.query(current_query).to_dataframe()
                
                prop_info = {
                    'opening_line': opening_df['points_line'].iloc[0] if not opening_df.empty else None,
                    'opening_source': opening_df['bookmaker'].iloc[0] if not opening_df.empty else None,
                    'current_line': current_df['points_line'].iloc[0] if not current_df.empty else None,
                    'current_source': current_df['bookmaker'].iloc[0] if not current_df.empty else None,
                }
                
                if prop_info['opening_line'] and prop_info['current_line']:
                    prop_info['line_movement'] = prop_info['current_line'] - prop_info['opening_line']
                else:
                    prop_info['line_movement'] = None
                
                self.prop_lines[(player_lookup, game_id)] = prop_info
                
            except Exception as e:
                logger.warning(f"Error extracting prop lines for {player_lookup}/{game_id}: {e}")
                self.prop_lines[(player_lookup, game_id)] = {
                    'opening_line': None,
                    'opening_source': None,
                    'current_line': None,
                    'current_source': None,
                    'line_movement': None
                }
    
    def _extract_game_lines(self) -> None:
        """
        Extract game lines (spreads and totals) for each game.
        
        Uses consensus (median) across all bookmakers.
        Opening: Earliest snapshot
        Current: Most recent snapshot
        """
        game_ids = list(set([p['game_id'] for p in self.players_to_process]))
        
        for game_id in game_ids:
            try:
                # Get spread consensus
                spread_info = self._get_game_line_consensus(game_id, 'spreads')
                
                # Get total consensus
                total_info = self._get_game_line_consensus(game_id, 'totals')
                
                self.game_lines[game_id] = {
                    **spread_info,
                    **total_info
                }
                
                # Track source usage
                self.source_tracking['game_lines']['rows_found'] += 1
                
            except Exception as e:
                logger.warning(f"Error extracting game lines for {game_id}: {e}")
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
        
        # FIX: use timezone-aware datetime
        self.source_tracking['game_lines']['last_updated'] = datetime.now(timezone.utc)
    
    def _get_game_line_consensus(self, game_id: str, market_key: str) -> Dict:
        """
        Get consensus line (median across bookmakers) for a market.
        
        Args:
            game_id: Game identifier
            market_key: 'spreads' or 'totals'
            
        Returns:
            Dict with opening, current, movement, and source
        """
        # Get opening line (earliest snapshot, median across bookmakers)
        opening_query = f"""
        WITH earliest_snapshot AS (
            SELECT MIN(snapshot_timestamp) as earliest
            FROM `{self.project_id}.nba_raw.odds_api_game_lines`
            WHERE game_id = '{game_id}'
              AND game_date = '{self.target_date}'
              AND market_key = '{market_key}'
        ),
        opening_lines AS (
            SELECT 
                outcome_point,
                bookmaker_key
            FROM `{self.project_id}.nba_raw.odds_api_game_lines` lines
            CROSS JOIN earliest_snapshot
            WHERE lines.game_id = '{game_id}'
              AND lines.game_date = '{self.target_date}'
              AND lines.market_key = '{market_key}'
              AND lines.snapshot_timestamp = earliest_snapshot.earliest
        )
        SELECT 
            PERCENTILE_CONT(outcome_point, 0.5) OVER() as median_line,
            STRING_AGG(DISTINCT bookmaker_key) as bookmakers,
            COUNT(DISTINCT bookmaker_key) as bookmaker_count
        FROM opening_lines
        LIMIT 1
        """
        
        # Get current line (latest snapshot, median across bookmakers)
        current_query = f"""
        WITH latest_snapshot AS (
            SELECT MAX(snapshot_timestamp) as latest
            FROM `{self.project_id}.nba_raw.odds_api_game_lines`
            WHERE game_id = '{game_id}'
              AND game_date = '{self.target_date}'
              AND market_key = '{market_key}'
        ),
        current_lines AS (
            SELECT 
                outcome_point,
                bookmaker_key
            FROM `{self.project_id}.nba_raw.odds_api_game_lines` lines
            CROSS JOIN latest_snapshot
            WHERE lines.game_id = '{game_id}'
              AND lines.game_date = '{self.target_date}'
              AND lines.market_key = '{market_key}'
              AND lines.snapshot_timestamp = latest_snapshot.latest
        )
        SELECT 
            PERCENTILE_CONT(outcome_point, 0.5) OVER() as median_line,
            STRING_AGG(DISTINCT bookmaker_key) as bookmakers,
            COUNT(DISTINCT bookmaker_key) as bookmaker_count
        FROM current_lines
        LIMIT 1
        """
        
        try:
            opening_df = self.bq_client.query(opening_query).to_dataframe()
            current_df = self.bq_client.query(current_query).to_dataframe()
            
            prefix = 'spread' if market_key == 'spreads' else 'total'
            
            opening_line = opening_df['median_line'].iloc[0] if not opening_df.empty else None
            current_line = current_df['median_line'].iloc[0] if not current_df.empty else None
            
            result = {
                f'opening_{prefix}': opening_line,
                f'game_{prefix}': current_line,
                f'{prefix}_movement': (current_line - opening_line) if (opening_line and current_line) else None,
                f'{prefix}_source': current_df['bookmakers'].iloc[0] if not current_df.empty else None
            }
            
            return result
            
        except Exception as e:
            logger.warning(f"Error getting {market_key} consensus for {game_id}: {e}")
            prefix = 'spread' if market_key == 'spreads' else 'total'
            return {
                f'opening_{prefix}': None,
                f'game_{prefix}': None,
                f'{prefix}_movement': None,
                f'{prefix}_source': None
            }
    
    def _extract_rosters(self) -> None:
        """Extract current roster data (optional enhancement)."""
        # TODO: Implement roster extraction from nba_raw.espn_team_rosters
        # For now, we'll determine team from recent boxscores
        pass
    
    def _extract_injuries(self) -> None:
        """Extract injury report data (optional enhancement)."""
        # TODO: Implement injury extraction from nba_raw.nbac_injury_report
        pass
    
    def _extract_registry(self) -> None:
        """Extract universal player IDs from registry (optional)."""
        # TODO: Implement registry lookup from nba_reference.nba_players_registry
        pass
    
    def calculate_analytics(self) -> None:
        """
        Calculate context for each player.
        
        For each player with a prop bet:
        1. Determine player's team
        2. Calculate fatigue metrics
        3. Calculate performance trends
        4. Assemble context record
        """
        logger.info(f"Calculating context for {len(self.players_to_process)} players")
        
        for player_info in self.players_to_process:
            try:
                player_lookup = player_info['player_lookup']
                game_id = player_info['game_id']
                
                # Calculate context
                context = self._calculate_player_context(player_info)
                
                if context:
                    self.transformed_data.append(context)
                else:
                    self.failed_entities.append({
                        'player_lookup': player_lookup,
                        'game_id': game_id,
                        'reason': 'Failed to calculate context',
                        'category': 'CALCULATION_ERROR'
                    })
                    
            except Exception as e:
                logger.error(f"Error calculating context for {player_lookup}: {e}")
                self.failed_entities.append({
                    'player_lookup': player_lookup,
                    'game_id': game_id,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR'
                })
        
        logger.info(f"Successfully calculated context for {len(self.transformed_data)} players")
    
    def _calculate_player_context(self, player_info: Dict) -> Optional[Dict]:
        """
        Calculate complete context for a single player.
        
        Args:
            player_info: Dict with player_lookup, game_id, home/away teams
            
        Returns:
            Dict with all context fields, or None if failed
        """
        player_lookup = player_info['player_lookup']
        game_id = player_info['game_id']
        
        # Get game info
        game_info = self.schedule_data.get(game_id)
        if not game_info:
            logger.warning(f"No schedule data for game {game_id}")
            return None
        
        # Determine player's team
        team_abbr = self._determine_player_team(player_lookup, game_info)
        if not team_abbr:
            logger.warning(f"Could not determine team for {player_lookup}")
            return None
        
        # Determine opponent
        opponent_team_abbr = self._get_opponent_team(team_abbr, game_info)
        
        # Get historical boxscores
        historical_data = self.historical_boxscores.get(player_lookup, pd.DataFrame())
        
        # Calculate fatigue metrics
        fatigue_metrics = self._calculate_fatigue_metrics(player_lookup, team_abbr, historical_data)
        
        # Calculate performance metrics
        performance_metrics = self._calculate_performance_metrics(historical_data)
        
        # Get prop lines
        prop_info = self.prop_lines.get((player_lookup, game_id), {})
        
        # Get game lines
        game_lines_info = self.game_lines.get(game_id, {})
        
        # Calculate data quality
        data_quality = self._calculate_data_quality(historical_data, game_lines_info)
        
        # Build context record (FIX: use timezone-aware datetime)
        context = {
            # Core identifiers
            'player_lookup': player_lookup,
            'universal_player_id': self.registry.get(player_lookup),  # TODO: implement
            'game_id': game_id,
            'game_date': self.target_date.isoformat(),
            'team_abbr': team_abbr,
            'opponent_team_abbr': opponent_team_abbr,
            
            # Prop betting context
            'current_points_line': prop_info.get('current_line'),
            'opening_points_line': prop_info.get('opening_line'),
            'line_movement': prop_info.get('line_movement'),
            'current_points_line_source': prop_info.get('current_source'),
            'opening_points_line_source': prop_info.get('opening_source'),
            
            # Game spread context
            'game_spread': game_lines_info.get('game_spread'),
            'opening_spread': game_lines_info.get('opening_spread'),
            'spread_movement': game_lines_info.get('spread_movement'),
            'game_spread_source': game_lines_info.get('spread_source'),
            'spread_public_betting_pct': None,  # TODO: future
            
            # Game total context
            'game_total': game_lines_info.get('game_total'),
            'opening_total': game_lines_info.get('opening_total'),
            'total_movement': game_lines_info.get('total_movement'),
            'game_total_source': game_lines_info.get('total_source'),
            'total_public_betting_pct': None,  # TODO: future
            
            # Pre-game context
            'pace_differential': None,  # TODO: future (needs team analytics)
            'opponent_pace_last_10': None,  # TODO: future
            'game_start_time_local': self._extract_game_time(game_info),
            'opponent_ft_rate_allowed': None,  # TODO: future
            'home_game': (team_abbr == game_info['home_team_abbr']),
            'back_to_back': fatigue_metrics['back_to_back'],
            'season_phase': self._determine_season_phase(self.target_date),
            'projected_usage_rate': None,  # TODO: future
            
            # Fatigue metrics
            **fatigue_metrics,
            
            # Travel context (all TODO: future)
            'travel_miles': None,
            'time_zone_changes': None,
            'consecutive_road_games': None,
            'miles_traveled_last_14_days': None,
            'time_zones_crossed_last_14_days': None,
            
            # Player characteristics
            'player_age': None,  # TODO: from roster
            
            # Performance metrics
            **performance_metrics,
            
            # Forward-looking schedule (TODO: future)
            'next_game_days_rest': 0,
            'games_in_next_7_days': 0,
            'next_opponent_win_pct': None,
            'next_game_is_primetime': False,
            
            # Opponent asymmetry (TODO: future)
            'opponent_days_rest': 0,
            'opponent_games_in_next_7_days': 0,
            'opponent_next_game_days_rest': 0,
            
            # Real-time updates
            'player_status': self.injuries.get(player_lookup, {}).get('status'),
            'injury_report': self.injuries.get(player_lookup, {}).get('report'),
            'questionable_teammates': None,  # TODO: future
            'probable_teammates': None,  # TODO: future
            
            # Source tracking
            **self._build_source_tracking_fields(),
            
            # Data quality
            **data_quality,
            
            # Update tracking (FIX: use timezone-aware datetime)
            'context_version': 1,  # TODO: increment for intraday updates
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }
        
        return context
    
    def _determine_player_team(self, player_lookup: str, game_info: Dict) -> Optional[str]:
        """
        Determine which team the player is on.
        
        Strategy:
        1. Check roster (TODO: not implemented yet)
        2. Use most recent boxscore
        
        Args:
            player_lookup: Player identifier
            game_info: Game information dict
            
        Returns:
            Team abbreviation or None
        """
        # TODO: Check roster first when implemented
        
        # Use most recent boxscore
        historical_data = self.historical_boxscores.get(player_lookup, pd.DataFrame())
        if not historical_data.empty:
            most_recent = historical_data.iloc[0]  # Already sorted by date DESC
            return most_recent.get('team_abbr')
        
        return None
    
    def _get_opponent_team(self, team_abbr: str, game_info: Dict) -> str:
        """Get opponent team abbreviation."""
        if team_abbr == game_info['home_team_abbr']:
            return game_info['away_team_abbr']
        else:
            return game_info['home_team_abbr']
    
    def _calculate_fatigue_metrics(self, player_lookup: str, team_abbr: str, 
                                   historical_data: pd.DataFrame) -> Dict:
        """
        Calculate fatigue-related metrics.
        
        Args:
            player_lookup: Player identifier
            team_abbr: Player's team
            historical_data: DataFrame of historical boxscores
            
        Returns:
            Dict with fatigue metrics
        """
        if historical_data.empty:
            return {
                'days_rest': None,
                'days_rest_before_last_game': None,
                'days_since_2_plus_days_rest': None,
                'games_in_last_7_days': 0,
                'games_in_last_14_days': 0,
                'minutes_in_last_7_days': 0,
                'minutes_in_last_14_days': 0,
                'avg_minutes_per_game_last_7': None,
                'back_to_backs_last_14_days': 0,
                'avg_usage_rate_last_7_games': None,  # TODO: future
                'fourth_quarter_minutes_last_7': None,  # TODO: future
                'clutch_minutes_last_7_games': None,  # TODO: future
                'back_to_back': False
            }
        
        # Get most recent game date
        last_game_date = historical_data.iloc[0]['game_date']
        
        # Days rest
        days_rest = (self.target_date - last_game_date).days
        
        # Back-to-back
        back_to_back = (days_rest == 0)
        
        # Games in windows
        last_7_days = self.target_date - timedelta(days=7)
        last_14_days = self.target_date - timedelta(days=14)
        
        games_last_7 = historical_data[historical_data['game_date'] >= last_7_days]
        games_last_14 = historical_data[historical_data['game_date'] >= last_14_days]
        
        # Minutes totals
        minutes_last_7 = games_last_7['minutes_decimal'].sum() if 'minutes_decimal' in games_last_7.columns else 0
        minutes_last_14 = games_last_14['minutes_decimal'].sum() if 'minutes_decimal' in games_last_14.columns else 0
        
        # Average minutes per game
        avg_minutes_last_7 = minutes_last_7 / len(games_last_7) if len(games_last_7) > 0 else None
        
        # Back-to-backs in last 14 days
        back_to_backs_count = 0
        if len(games_last_14) > 1:
            dates = sorted(games_last_14['game_date'].tolist())
            for i in range(len(dates) - 1):
                if (dates[i+1] - dates[i]).days == 1:
                    back_to_backs_count += 1
        
        # Days rest before last game (if have at least 2 games)
        days_rest_before_last = None
        if len(historical_data) >= 2:
            second_last_date = historical_data.iloc[1]['game_date']
            days_rest_before_last = (last_game_date - second_last_date).days
        
        # Days since 2+ days rest
        days_since_2_plus_rest = None
        for i in range(len(historical_data) - 1):
            current_date = historical_data.iloc[i]['game_date']
            next_date = historical_data.iloc[i+1]['game_date']
            days_diff = (current_date - next_date).days
            
            if days_diff >= 2:
                days_since_2_plus_rest = (self.target_date - current_date).days
                break
        
        return {
            'days_rest': days_rest,
            'days_rest_before_last_game': days_rest_before_last,
            'days_since_2_plus_days_rest': days_since_2_plus_rest,
            'games_in_last_7_days': len(games_last_7),
            'games_in_last_14_days': len(games_last_14),
            'minutes_in_last_7_days': int(minutes_last_7),
            'minutes_in_last_14_days': int(minutes_last_14),
            'avg_minutes_per_game_last_7': round(avg_minutes_last_7, 1) if avg_minutes_last_7 else None,
            'back_to_backs_last_14_days': back_to_backs_count,
            'avg_usage_rate_last_7_games': None,  # TODO: future (needs play-by-play)
            'fourth_quarter_minutes_last_7': None,  # TODO: future
            'clutch_minutes_last_7_games': None,  # TODO: future
            'back_to_back': back_to_back
        }
    
    def _calculate_performance_metrics(self, historical_data: pd.DataFrame) -> Dict:
        """
        Calculate recent performance metrics.
        
        Args:
            historical_data: DataFrame of historical boxscores
            
        Returns:
            Dict with performance metrics
        """
        if historical_data.empty:
            return {
                'points_avg_last_5': None,
                'points_avg_last_10': None,
                'prop_over_streak': 0,
                'prop_under_streak': 0,
                'star_teammates_out': None,  # TODO: future
                'opponent_def_rating_last_10': None,  # TODO: future
                'shooting_pct_decline_last_5': None,  # TODO: future
                'fourth_quarter_production_last_7': None  # TODO: future
            }
        
        # Points averages
        last_5 = historical_data.head(5)
        last_10 = historical_data.head(10)
        
        points_avg_5 = last_5['points'].mean() if len(last_5) > 0 else None
        points_avg_10 = last_10['points'].mean() if len(last_10) > 0 else None
        
        # Prop streaks (TODO: need current prop line to calculate)
        # For now, just return 0
        
        return {
            'points_avg_last_5': round(points_avg_5, 1) if points_avg_5 else None,
            'points_avg_last_10': round(points_avg_10, 1) if points_avg_10 else None,
            'prop_over_streak': 0,  # TODO: calculate based on current_points_line
            'prop_under_streak': 0,  # TODO: calculate based on current_points_line
            'star_teammates_out': None,  # TODO: future
            'opponent_def_rating_last_10': None,  # TODO: future
            'shooting_pct_decline_last_5': None,  # TODO: future
            'fourth_quarter_production_last_7': None  # TODO: future
        }
    
    def _calculate_data_quality(self, historical_data: pd.DataFrame, 
                                game_lines_info: Dict) -> Dict:
        """
        Calculate data quality metrics.
        
        Args:
            historical_data: DataFrame of historical boxscores
            game_lines_info: Dict with game lines
            
        Returns:
            Dict with quality fields
        """
        # Sample size quality tier
        games_count = len(historical_data)
        if games_count >= self.min_games_for_high_quality:
            tier = 'high'
        elif games_count >= self.min_games_for_medium_quality:
            tier = 'medium'
        else:
            tier = 'low'
        
        # Processing issues flag
        has_issues = (
            game_lines_info.get('game_spread') is None or
            game_lines_info.get('game_total') is None or
            games_count < 3
        )
        
        # Primary source used
        # TODO: Track which boxscore source was actually used
        primary_source = 'bdl_player_boxscores'  # Default for now
        
        return {
            'data_quality_tier': tier,
            'primary_source_used': primary_source,
            'processed_with_issues': has_issues
        }
    
    def _build_source_tracking_fields(self) -> Dict:
        """
        Build source tracking fields for output record.
        
        Returns:
            Dict with all source tracking fields
        """
        fields = {}
        
        # Boxscore source
        fields['source_boxscore_last_updated'] = self.source_tracking['boxscore']['last_updated'].isoformat() if self.source_tracking['boxscore']['last_updated'] else None
        fields['source_boxscore_rows_found'] = self.source_tracking['boxscore']['rows_found']
        fields['source_boxscore_completeness_pct'] = self._calculate_completeness('boxscore')
        
        # Schedule source
        fields['source_schedule_last_updated'] = self.source_tracking['schedule']['last_updated'].isoformat() if self.source_tracking['schedule']['last_updated'] else None
        fields['source_schedule_rows_found'] = self.source_tracking['schedule']['rows_found']
        fields['source_schedule_completeness_pct'] = self._calculate_completeness('schedule')
        
        # Props source
        fields['source_props_last_updated'] = self.source_tracking['props']['last_updated'].isoformat() if self.source_tracking['props']['last_updated'] else None
        fields['source_props_rows_found'] = self.source_tracking['props']['rows_found']
        fields['source_props_completeness_pct'] = self._calculate_completeness('props')
        
        # Game lines source
        fields['source_game_lines_last_updated'] = self.source_tracking['game_lines']['last_updated'].isoformat() if self.source_tracking['game_lines']['last_updated'] else None
        fields['source_game_lines_rows_found'] = self.source_tracking['game_lines']['rows_found']
        fields['source_game_lines_completeness_pct'] = self._calculate_completeness('game_lines')
        
        return fields
    
    def _calculate_completeness(self, source_key: str) -> Optional[float]:
        """
        Calculate completeness percentage for a source.
        
        Args:
            source_key: Key in source_tracking dict
            
        Returns:
            Completeness percentage or None
        """
        rows_found = self.source_tracking[source_key]['rows_found']
        
        # Expected counts based on source type
        if source_key == 'boxscore':
            # Expect roughly 1 game per day for 30 days = ~30 games per player
            # But some players may have fewer (injury, rest, etc.)
            # Use a generous threshold
            rows_expected = self.lookback_days * 0.5  # Expect at least 15 games
        elif source_key == 'schedule':
            # Expect 1 game per player (since we're processing one date)
            rows_expected = len(self.players_to_process)
        elif source_key == 'props':
            # Expect 1 prop per player
            rows_expected = len(self.players_to_process)
        elif source_key == 'game_lines':
            # Expect lines for all unique games
            unique_games = len(set([p['game_id'] for p in self.players_to_process]))
            rows_expected = unique_games
        else:
            return None
        
        if rows_expected == 0:
            return 100.0
        
        completeness = (rows_found / rows_expected) * 100
        return min(completeness, 100.0)  # Cap at 100%
    
    def save_analytics(self) -> bool:
        """
        Save results to BigQuery using MERGE strategy.
        
        Returns:
            True if successful, False otherwise
        """
        if not self.transformed_data:
            logger.warning("No data to save")
            return True
        
        table_id = f"{self.project_id}.{self.table_name}"
        
        try:
            # MERGE: Delete existing records for this date, then insert new ones
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date = '{self.target_date}'
            """
            
            self.bq_client.query(delete_query).result()
            logger.info(f"Deleted existing records for {self.target_date}")
            
            # Insert new records
            errors = self.bq_client.insert_rows_json(table_id, self.transformed_data)
            
            if errors:
                logger.error(f"BigQuery insert errors: {errors}")
                return False
            else:
                logger.info(f"Successfully inserted {len(self.transformed_data)} records")
                return True
                
        except Exception as e:
            logger.error(f"Error saving to BigQuery: {e}")
            return False
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def _parse_minutes(self, minutes_str: str) -> float:
        """
        Parse minutes string "MM:SS" to decimal.
        
        Args:
            minutes_str: Minutes in "MM:SS" format
            
        Returns:
            Decimal minutes
        """
        if not minutes_str or pd.isna(minutes_str):
            return 0.0
        
        try:
            if ':' in str(minutes_str):
                parts = str(minutes_str).split(':')
                minutes = int(parts[0])
                seconds = int(parts[1])
                return minutes + (seconds / 60.0)
            else:
                return float(minutes_str)
        except (ValueError, IndexError):
            logger.warning(f"Could not parse minutes: {minutes_str}")
            return 0.0
    
    def _extract_game_time(self, game_info: Dict) -> Optional[str]:
        """Extract game time in local timezone."""
        # TODO: Implement timezone conversion
        # For now, just return None
        return None
    
    def _determine_season_phase(self, game_date: date) -> str:
        """
        Determine season phase based on date.
        
        Args:
            game_date: Date of game
            
        Returns:
            'early', 'mid', 'late', or 'playoffs'
        """
        # TODO: Implement proper season phase detection
        # For now, use simple month-based logic
        
        month = game_date.month
        
        if month in [10, 11]:
            return 'early'
        elif month in [12, 1, 2]:
            return 'mid'
        elif month in [3, 4]:
            return 'late'
        else:
            return 'playoffs'


# Entry point for script execution
if __name__ == '__main__':
    import sys
    from datetime import date
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("Usage: python processor.py YYYY-MM-DD")
        sys.exit(1)
    
    target_date_str = sys.argv[1]
    target_date = date.fromisoformat(target_date_str)
    
    processor = UpcomingPlayerGameContextProcessor()
    result = processor.process_date(target_date)
    
    print(f"\nProcessing Result:")
    print(f"Status: {result['status']}")
    print(f"Players Processed: {result['players_processed']}")
    print(f"Players Failed: {result['players_failed']}")
    
    if result.get('errors'):
        print(f"\nErrors:")
        for error in result['errors'][:10]:  # Show first 10 errors
            print(f"  - {error}")