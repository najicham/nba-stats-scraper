# predictions/coordinator/player_loader.py

"""
Player Loader for Phase 5 Coordinator

Queries BigQuery to get players with games scheduled for a given date
and creates prediction request messages for the worker.

Responsibilities:
- Query upcoming_player_game_context for players with games today
- Filter by projected minutes (exclude low-minute players)
- Filter by injury status (exclude OUT/DOUBTFUL players)
- Get betting lines (from odds data or use default)
- Create prediction request messages
- Provide summary statistics

Performance:
- Single query for all players (~10-50ms)
- Efficient filtering in SQL
- Minimal data transfer

Version: 3.10 (No estimated lines - only real betting lines from sportsbooks)
"""

from typing import Dict, List, Optional, Tuple, Any
from google.cloud import bigquery
from datetime import date, datetime
import logging
import sys
import os

# Add parent path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from shared.config.orchestration_config import get_orchestration_config
from shared.utils.bigquery_retry import retry_on_transient

logger = logging.getLogger(__name__)


class PlayerLoader:
    """
    Loads players scheduled to play on a given date
    
    Queries Phase 3 upcoming_player_game_context table and creates
    prediction request messages for the worker.
    """
    
    def __init__(self, project_id: str, location: str = 'us-west2', dataset_prefix: str = ''):
        """
        Initialize player loader

        Args:
            project_id: GCP project ID (e.g., 'nba-props-platform')
            location: BigQuery location (default: us-west2)
            dataset_prefix: Optional dataset prefix for test isolation (e.g., "test")
        """
        self.project_id = project_id
        self.location = location
        self.dataset_prefix = dataset_prefix
        from shared.clients import get_bigquery_client
        self.client = get_bigquery_client(project_id)

        logger.info(f"Initialized PlayerLoader for project {project_id} (location: {location}, dataset_prefix: {dataset_prefix or 'production'})")
    
    # ========================================================================
    # MAIN API
    # ========================================================================
    
    @retry_on_transient
    def create_prediction_requests(
        self,
        game_date: date,
        min_minutes: int = 15,
        use_multiple_lines: bool = False,
        dataset_prefix: str = None,
        require_real_lines: bool = False
    ) -> List[Dict]:
        """
        Create prediction requests for all players with games on given date

        Args:
            game_date: Date to get players for
            min_minutes: Minimum projected minutes (default: 15)
            use_multiple_lines: If True, test multiple betting lines (default: False)
            dataset_prefix: Optional dataset prefix override (defaults to instance prefix)
            require_real_lines: If True, only include players WITH real betting lines (Session 74).
                              Players with NO_PROP_LINE will be filtered out.
                              Used for early prediction runs when real lines are available.

        Returns:
            List of prediction request dicts, one per player

        Example Return:
            [
                {
                    'player_lookup': 'lebron-james',
                    'game_date': '2025-11-08',
                    'game_id': '20251108_LAL_GSW',
                    'line_values': [25.5]  # or [23.5, 24.5, 25.5, 26.5, 27.5]
                },
                # ... more players
            ]
        """
        # Use provided dataset_prefix or fall back to instance default
        prefix = dataset_prefix if dataset_prefix is not None else self.dataset_prefix

        mode_desc = "REAL_LINES_ONLY" if require_real_lines else "ALL_PLAYERS"
        logger.info(f"Creating prediction requests for {game_date} (min_minutes={min_minutes}, mode={mode_desc}, dataset_prefix={prefix or 'production'})")

        # Validate date before querying
        if not validate_game_date(game_date):
            logger.error(f"Invalid game date: {game_date}", exc_info=True)
            return []

        # Get all players with games on this date
        players = self._query_players_for_date(game_date, min_minutes, dataset_prefix=prefix)

        if not players:
            logger.warning(f"No players found for {game_date}")
            return []

        logger.info(f"Found {len(players)} players for {game_date}")

        # Create prediction requests, filtering based on mode
        requests = []
        bootstrap_skipped = 0
        no_prop_line_count = 0
        no_prop_line_filtered = 0
        for player in players:
            request = self._create_request_for_player(
                player,
                game_date,
                use_multiple_lines
            )
            # Only skip players who need bootstrap (new players without history)
            if request.get('needs_bootstrap', False):
                bootstrap_skipped += 1
                logger.debug(f"Skipping {player['player_lookup']} - needs bootstrap")
                continue

            # Track/filter no-prop-line players based on mode (Session 74)
            if request.get('line_source') == 'NO_PROP_LINE':
                no_prop_line_count += 1
                if require_real_lines:
                    # Filter out players without real lines (early prediction mode)
                    no_prop_line_filtered += 1
                    logger.debug(f"Filtering {player['player_lookup']} - no real betting line (require_real_lines=True)")
                    continue

            requests.append(request)

        if bootstrap_skipped > 0:
            logger.info(f"Skipped {bootstrap_skipped} players needing bootstrap")
        if no_prop_line_count > 0:
            if require_real_lines:
                logger.info(f"Filtered {no_prop_line_filtered}/{no_prop_line_count} players without real lines (REAL_LINES_ONLY mode)")
            else:
                logger.info(f"Including {no_prop_line_count} players without betting lines (for accuracy tracking)")

        return requests
    
    @retry_on_transient
    def get_summary_stats(self, game_date: date, dataset_prefix: str = None) -> Dict:
        """
        Get summary statistics for games on given date

        Includes breakdown by position for validation

        Args:
            game_date: Date to get stats for
            dataset_prefix: Optional dataset prefix override (defaults to instance prefix)

        Returns:
            Dict with summary stats
            
        Example Return:
            {
                'game_date': '2025-11-08',
                'total_games': 15,
                'total_players': 450,
                'teams_playing': 30,
                'avg_projected_minutes': 28.5,
                'players_by_position': {'PG': 90, 'SG': 90, ...}
            }
        """
        # v3.2: Added has_prop_line stats for all-player predictions
        query = """
        SELECT
            COUNT(DISTINCT game_id) as total_games,
            COUNT(DISTINCT player_lookup) as total_players,
            COUNT(DISTINCT team_abbr) as teams_playing,
            AVG(avg_minutes_per_game_last_7) as avg_projected_minutes,
            MIN(avg_minutes_per_game_last_7) as min_projected_minutes,
            MAX(avg_minutes_per_game_last_7) as max_projected_minutes,

            -- Completeness tracking (Phase 5)
            COUNTIF(is_production_ready = TRUE) as production_ready_count,
            COUNTIF(is_production_ready = FALSE OR is_production_ready IS NULL) as not_ready_count,
            AVG(completeness_percentage) as avg_completeness_pct,

            -- Prop line tracking (v3.2 - All-Player Predictions)
            COUNTIF(has_prop_line = TRUE) as with_prop_line_count,
            COUNTIF(has_prop_line = FALSE OR has_prop_line IS NULL) as without_prop_line_count
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = @game_date
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            row = next(results, None)
            
            if row is None:
                logger.warning(f"No data found for {game_date}")
                return {
                    'game_date': game_date.isoformat(),
                    'total_games': 0,
                    'total_players': 0,
                    'teams_playing': 0,
                    'avg_projected_minutes': 0.0
                }
            
            summary = {
                'game_date': game_date.isoformat(),
                'total_games': int(row.total_games or 0),
                'total_players': int(row.total_players or 0),
                'teams_playing': int(row.teams_playing or 0),
                'avg_projected_minutes': round(float(row.avg_projected_minutes or 0), 1),
                'min_projected_minutes': round(float(row.min_projected_minutes or 0), 1),
                'max_projected_minutes': round(float(row.max_projected_minutes or 0), 1),
                'completeness': {
                    'production_ready_count': int(row.production_ready_count or 0),
                    'not_ready_count': int(row.not_ready_count or 0),
                    'avg_completeness_pct': round(float(row.avg_completeness_pct or 0), 2)
                },
                # v3.2: All-player predictions prop line coverage
                'prop_line_coverage': {
                    'with_prop_line': int(row.with_prop_line_count or 0),
                    'without_prop_line': int(row.without_prop_line_count or 0)
                }
            }

            logger.info(
                f"Summary for {game_date}: {summary['total_games']} games, "
                f"{summary['total_players']} players "
                f"({summary['completeness']['production_ready_count']} production ready, "
                f"avg completeness: {summary['completeness']['avg_completeness_pct']}%, "
                f"prop line: {summary['prop_line_coverage']['with_prop_line']}/{summary['total_players']})"
            )
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting summary stats for {game_date}: {e}", exc_info=True)
            return {
                'game_date': game_date.isoformat(),
                'total_games': 0,
                'total_players': 0,
                'teams_playing': 0,
                'error': str(e)
            }
    
    # ========================================================================
    # INTERNAL METHODS
    # ========================================================================
    
    @retry_on_transient
    def _query_players_for_date(
        self,
        game_date: date,
        min_minutes: int,
        dataset_prefix: str = ''
    ) -> List[Dict]:
        """
        Query BigQuery for all players with games on given date

        Filters out:
        - Players below minimum minutes threshold (unless they have a prop line - v3.7)
        - Inactive players
        - Injured players (OUT or DOUBTFUL status)

        v3.7: Players with betting prop lines are included even if returning from injury
        (NULL avg_minutes_per_game_last_7). This ensures we make predictions for all
        players that sportsbooks expect to play.

        Args:
            game_date: Date to query
            min_minutes: Minimum projected minutes
            dataset_prefix: Optional dataset prefix for test isolation

        Returns:
            List of player dicts with game context
        """
        # Construct dataset name with optional prefix
        dataset = f"{dataset_prefix}_nba_analytics" if dataset_prefix else "nba_analytics"

        # v3.2 CHANGE: Added has_prop_line and current_points_line for all-player predictions
        # v3.5 FIX: Added deduplication to handle duplicate rows in Phase 3
        # Phase 3 can create multiple rows per player when re-run. Pick the most recent one.
        query = """
        SELECT
            player_lookup,
            universal_player_id,
            game_id,
            game_date,
            team_abbr,
            opponent_team_abbr,
            home_game as is_home,
            days_rest,
            back_to_back,
            COALESCE(avg_minutes_per_game_last_7, 0) as projected_minutes,  -- v3.7: Default to 0 for injury-return players
            player_status as injury_status,
            COALESCE(has_prop_line, FALSE) as has_prop_line,  -- v3.2: Track if player has betting line
            current_points_line  -- v3.2: Pass through actual betting line if available
        FROM `{project}.{dataset}.upcoming_player_game_context`
        WHERE game_date = @game_date
          AND (avg_minutes_per_game_last_7 >= @min_minutes OR has_prop_line = TRUE)  -- v3.7: Include players with prop lines even if returning from injury
          AND (player_status IS NULL OR player_status NOT IN ('OUT', 'DOUBTFUL'))
          AND (is_production_ready = TRUE OR has_prop_line = TRUE)  -- v3.11: Allow players with prop lines even if data incomplete - sportsbooks validated they'll play
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY created_at DESC) = 1
        ORDER BY avg_minutes_per_game_last_7 DESC
        LIMIT 500  -- Memory optimization: Cap at 500 players per day (covers ~20 games)
        """.format(project=self.project_id, dataset=dataset)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("min_minutes", "INT64", min_minutes)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            
            players = []
            for row in results:
                player = {
                    'player_lookup': row.player_lookup,
                    'universal_player_id': row.universal_player_id,
                    'game_id': row.game_id,
                    'game_date': row.game_date.isoformat(),
                    'team_abbr': row.team_abbr,
                    'opponent_team_abbr': row.opponent_team_abbr,
                    'is_home': row.is_home,
                    'days_rest': row.days_rest,
                    'back_to_back': row.back_to_back,
                    'projected_minutes': float(row.projected_minutes or 0),  # v3.7: Handle NULL for injury-return players
                    'injury_status': row.injury_status,
                    # v3.2: All-player predictions support
                    'has_prop_line': bool(row.has_prop_line) if row.has_prop_line is not None else False,
                    'current_points_line': float(row.current_points_line) if row.current_points_line else None
                }
                players.append(player)
            
            logger.info(f"Queried {len(players)} players for {game_date}")
            return players
            
        except Exception as e:
            logger.error(f"Error querying players for {game_date}: {e}", exc_info=True)
            return []
    
    def _create_request_for_player(
        self,
        player: Dict,
        game_date: date,
        use_multiple_lines: bool
    ) -> Dict:
        """
        Create prediction request message for a single player

        v3.2 CHANGE: Now includes line source tracking for all-player predictions.

        Args:
            player: Player dict from query
            game_date: Game date
            use_multiple_lines: Whether to test multiple lines

        Returns:
            Prediction request dict with line source tracking
        """
        # Get betting lines for this player (now returns dict with source info)
        line_info = self._get_betting_lines(
            player['player_lookup'],
            game_date,
            use_multiple_lines
        )

        # Session 79: Query Kalshi prediction market data
        # Use the base line (Vegas or estimated) to find closest Kalshi line
        vegas_line = line_info.get('base_line')
        kalshi_info = self._query_kalshi_line(
            player['player_lookup'],
            game_date,
            vegas_line
        )

        # Create request message with line source tracking (v3.2, v3.3)
        request = {
            'player_lookup': player['player_lookup'],
            'game_date': game_date.isoformat(),
            'game_id': player['game_id'],
            'line_values': line_info['line_values'],

            # Optional context (for debugging/monitoring)
            'team_abbr': player['team_abbr'],
            'opponent_team_abbr': player['opponent_team_abbr'],
            'is_home': player['is_home'],
            'projected_minutes': player['projected_minutes'],

            # v3.2/v3.10: All-player predictions support with line source tracking
            # v3.10 FIX: has_prop_line should be based on line_source, not player's default
            'has_prop_line': line_info['line_source'] == 'ACTUAL_PROP',  # True only when we have a real line
            # Session 170: Use fresh odds base_line when available, fall back to stale Phase 3 current_points_line.
            # This eliminates the root cause of Session 169's UNDER bias: coordinator was sending NULL
            # actual_prop_line from Phase 3's stale current_points_line while fresh odds existed in line_values.
            'actual_prop_line': line_info.get('base_line') if line_info.get('line_source') == 'ACTUAL_PROP' else player.get('current_points_line'),
            'line_source': line_info['line_source'],  # 'ACTUAL_PROP', 'NO_PROP_LINE', or 'NEEDS_BOOTSTRAP'
            # v3.10: Always populate estimated_line_value as player's baseline (L5 avg) for reference
            # This allows tracking "did we beat the player's average?" even when we have real lines
            'estimated_line_value': self._get_player_baseline(player['player_lookup']),
            'estimation_method': line_info['estimation_method'],  # 'points_avg_last_5', 'points_avg_last_10', None

            # v3.3: Line source API and sportsbook tracking
            'line_source_api': line_info.get('line_source_api'),  # 'ODDS_API', 'BETTINGPROS', 'ESTIMATED'
            'sportsbook': line_info.get('sportsbook'),  # 'DRAFTKINGS', 'FANDUEL', etc.
            'was_line_fallback': line_info.get('was_line_fallback', False),  # True if not primary sportsbook

            # v3.6: Line timing tracking (how close to closing line)
            'line_minutes_before_game': line_info.get('line_minutes_before_game'),  # Minutes before tipoff

            # Issue 3: New player handling
            'needs_bootstrap': line_info.get('needs_bootstrap', False),

            # Session 79: Kalshi prediction market data
            'kalshi_available': kalshi_info.get('kalshi_available', False) if kalshi_info else False,
            'kalshi_line': kalshi_info.get('kalshi_line') if kalshi_info else None,
            'kalshi_yes_price': kalshi_info.get('kalshi_yes_price') if kalshi_info else None,
            'kalshi_no_price': kalshi_info.get('kalshi_no_price') if kalshi_info else None,
            'kalshi_liquidity': kalshi_info.get('kalshi_liquidity') if kalshi_info else None,
            'kalshi_market_ticker': kalshi_info.get('kalshi_market_ticker') if kalshi_info else None,
            'line_discrepancy': kalshi_info.get('line_discrepancy') if kalshi_info else None,
        }

        return request
    
    def _get_betting_lines(
        self,
        player_lookup: str,
        game_date: date,
        use_multiple_lines: bool
    ) -> Dict[str, Any]:
        """
        Get betting lines for player with source tracking (v3.2, v3.3)

        Strategy:
        1. Try to query from odds_api_player_points_props table (Phase 2) with sportsbook fallback
        2. If no odds available, use estimated line based on season average
        3. If use_multiple_lines=True, generate +/- 2 points from base line

        v3.2 CHANGE: Now returns dict with line source information for tracking
        when predictions were made with estimated vs actual lines.

        v3.3 CHANGE: Added line_source_api, sportsbook, was_line_fallback fields
        for granular tracking of which API/sportsbook provided the line.

        Args:
            player_lookup: Player identifier
            game_date: Game date
            use_multiple_lines: Whether to generate multiple lines

        Returns:
            Dict with:
                'line_values': List of line values
                'line_source': 'ACTUAL_PROP' or 'ESTIMATED_AVG'
                'base_line': The base line used
                'estimation_method': How line was estimated (if applicable)
                'line_source_api': 'ODDS_API', 'BETTINGPROS', or 'ESTIMATED' (v3.3)
                'sportsbook': 'DRAFTKINGS', 'FANDUEL', etc. (v3.3)
                'was_line_fallback': True if not primary sportsbook (v3.3)
        """
        # Try to get actual betting line from odds data (now returns dict with sportsbook info)
        line_result = self._query_actual_betting_line(player_lookup, game_date)

        if line_result is not None:
            base_line = line_result['line_value']
            line_source = 'ACTUAL_PROP'
            estimation_method = None
            line_source_api = line_result['line_source_api']
            sportsbook = line_result['sportsbook']
            was_line_fallback = line_result['was_fallback']
            # v3.6: Track how many minutes before game the line was captured
            line_minutes_before_game = line_result.get('line_minutes_before_game')
            logger.debug(f"Using actual betting line {base_line} ({sportsbook}, {line_minutes_before_game}min before) for {player_lookup}")
        else:
            # v3.10: Check if estimated lines are disabled
            config = get_orchestration_config()
            if config.prediction_mode.disable_estimated_lines:
                # No actual betting line found, and estimation is disabled
                # Still create prediction (for learning/accuracy tracking) but without a line
                # Use a placeholder line value for the prediction request, but mark as NO_PROP_LINE
                # The worker will still predict points, but recommendation will be NO_LINE
                logger.info(f"NO_PROP_LINE: {player_lookup} has no betting line, will predict without line")
                return {
                    'line_values': [None],  # Placeholder - worker handles None line
                    'line_source': 'NO_PROP_LINE',
                    'base_line': None,
                    'estimation_method': None,
                    'needs_bootstrap': False,  # Still generate prediction
                    'line_source_api': None,
                    'sportsbook': None,
                    'was_line_fallback': False,
                    'line_minutes_before_game': None
                }

            # Legacy behavior: Estimate from season average (when disable_estimated_lines=False)
            base_line, estimation_method = self._estimate_betting_line_with_method(player_lookup)

            # Issue 3: Handle new players who need bootstrap
            if base_line is None:
                logger.info(f"Player {player_lookup} needs bootstrap, skipping prediction")
                return {
                    'line_values': [],
                    'line_source': 'NEEDS_BOOTSTRAP',
                    'base_line': None,
                    'estimation_method': estimation_method,
                    'needs_bootstrap': True,
                    'line_source_api': 'ESTIMATED',
                    'sportsbook': None,
                    'was_line_fallback': False,
                    'line_minutes_before_game': None  # v3.6: No timing for bootstrap players
                }

            line_source = 'ESTIMATED_AVG'
            line_source_api = 'ESTIMATED'
            sportsbook = None
            was_line_fallback = False
            line_minutes_before_game = None  # v3.6: No timing for estimated lines
            logger.debug(f"Using estimated line {base_line} ({estimation_method}) for {player_lookup}")

        # Generate multiple lines if requested
        config = get_orchestration_config()
        if use_multiple_lines:
            # Generate lines: base_line ± range in increments (from config)
            line_range = config.prediction_mode.line_range_points
            line_increment = config.prediction_mode.line_increment
            lines = []
            current = base_line - line_range
            while current <= base_line + line_range:
                rounded = round(current, 1)
                # v3.11: Skip exactly 20.0 - it's flagged as placeholder by validation
                if rounded != 20.0:
                    lines.append(rounded)
                current += line_increment
        else:
            lines = [round(base_line, 1)]
            # v3.11: If single line is exactly 20.0, adjust it
            if lines[0] == 20.0:
                lines[0] = 20.5 if base_line >= 20.0 else 19.5

        return {
            'line_values': lines,
            'line_source': line_source,
            'base_line': round(base_line, 1),
            'estimation_method': estimation_method,
            'needs_bootstrap': False,
            'line_source_api': line_source_api,
            'sportsbook': sportsbook,
            'was_line_fallback': was_line_fallback,
            'line_minutes_before_game': line_minutes_before_game  # v3.6: How close to game time
        }

    def _query_actual_betting_line(
        self,
        player_lookup: str,
        game_date: date
    ) -> Optional[Dict[str, Any]]:
        """
        Query actual betting line with sportsbook-priority fallback.

        Prioritizes sportsbook quality over data source:
        - For each preferred sportsbook (DraftKings, FanDuel), try OddsAPI first, then BettingPros
        - Then try secondary sportsbooks from either source

        This ensures we get DraftKings/FanDuel lines when available from ANY source,
        rather than settling for a lesser sportsbook just because it's in OddsAPI.

        v3.3: Now returns dict with line_value, sportsbook, and was_fallback
        v3.8: Added bettingpros fallback when odds_api has no data
        v3.9: Sportsbook-priority fallback - DK/FD from any source before other books

        Args:
            player_lookup: Player identifier
            game_date: Game date

        Returns:
            Dict with line_value, sportsbook, was_fallback, line_source_api
            or None if no line found
        """
        # Preferred sportsbooks - try both sources before moving to next book
        preferred_sportsbooks = ['draftkings', 'fanduel']
        # Secondary sportsbooks - only try if preferred not found
        secondary_sportsbooks = ['betmgm', 'pointsbet', 'caesars']

        # Phase 1: Try preferred sportsbooks (DraftKings, FanDuel) from both sources
        for sportsbook in preferred_sportsbooks:
            # Try OddsAPI first for this sportsbook
            result = self._query_odds_api_betting_line_for_book(player_lookup, game_date, sportsbook)
            if result is not None:
                self._track_line_source(f'odds_api_{sportsbook}', player_lookup)
                logger.debug(f"LINE_SOURCE: {player_lookup} -> OddsAPI {sportsbook.upper()}")
                return result

            # Try BettingPros for this sportsbook
            result = self._query_bettingpros_betting_line_for_book(player_lookup, game_date, sportsbook)
            if result is not None:
                self._track_line_source(f'bettingpros_{sportsbook}', player_lookup)
                logger.info(f"LINE_SOURCE: {player_lookup} -> BettingPros {sportsbook.upper()} (OddsAPI {sportsbook} unavailable)")
                return result

        # Phase 2: Try secondary sportsbooks from OddsAPI
        for sportsbook in secondary_sportsbooks:
            result = self._query_odds_api_betting_line_for_book(player_lookup, game_date, sportsbook)
            if result is not None:
                self._track_line_source(f'odds_api_{sportsbook}', player_lookup)
                logger.info(f"LINE_SOURCE: {player_lookup} -> OddsAPI {sportsbook.upper()} (preferred books unavailable)")
                return result

        # Phase 3: Try secondary sportsbooks from BettingPros
        for sportsbook in secondary_sportsbooks:
            result = self._query_bettingpros_betting_line_for_book(player_lookup, game_date, sportsbook)
            if result is not None:
                self._track_line_source(f'bettingpros_{sportsbook}', player_lookup)
                logger.info(f"LINE_SOURCE: {player_lookup} -> BettingPros {sportsbook.upper()} (all other options exhausted)")
                return result

        # Phase 4: Try BettingPros consensus/any book as last resort
        result = self._query_bettingpros_betting_line(player_lookup, game_date)
        if result is not None:
            self._track_line_source('bettingpros_any', player_lookup)
            logger.warning(f"LINE_SOURCE: {player_lookup} -> BettingPros ANY (no specific book found)")
            return result

        # Neither source had data — log diagnostic details
        self._track_line_source('no_line_data', player_lookup)
        self._track_no_line_reason(player_lookup, game_date)
        return None

    def _query_odds_api_betting_line_for_book(
        self,
        player_lookup: str,
        game_date: date,
        sportsbook: str
    ) -> Optional[Dict[str, Any]]:
        """
        Query OddsAPI for a specific sportsbook.

        Args:
            player_lookup: Player identifier
            game_date: Game date
            sportsbook: Specific sportsbook to query (lowercase)

        Returns:
            Dict with line info or None
        """
        query = """
        SELECT
            points_line as line_value,
            bookmaker,
            minutes_before_tipoff
        FROM `{project}.nba_raw.odds_api_player_points_props`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
          AND LOWER(bookmaker) = @sportsbook
        ORDER BY snapshot_timestamp DESC
        LIMIT 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("sportsbook", "STRING", sportsbook.lower())
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=30)
            row = next(results, None)

            if row is not None and row.line_value is not None:
                return {
                    'line_value': float(row.line_value),
                    'sportsbook': row.bookmaker.upper() if row.bookmaker else sportsbook.upper(),
                    'was_fallback': sportsbook.lower() != 'draftkings',
                    'line_source_api': 'ODDS_API',
                    'line_minutes_before_game': int(row.minutes_before_tipoff) if row.minutes_before_tipoff else None
                }
            return None
        except Exception as e:
            logger.warning(f"No {sportsbook} line in odds_api for {player_lookup}: {e}")
            return None

    def _query_bettingpros_betting_line_for_book(
        self,
        player_lookup: str,
        game_date: date,
        sportsbook: str
    ) -> Optional[Dict[str, Any]]:
        """
        Query BettingPros for a specific sportsbook.

        Args:
            player_lookup: Player identifier
            game_date: Game date
            sportsbook: Specific sportsbook to query (case-insensitive)

        Returns:
            Dict with line info or None
        """
        # BettingPros uses title case for bookmaker names
        sportsbook_mapping = {
            'draftkings': 'DraftKings',
            'fanduel': 'FanDuel',
            'betmgm': 'BetMGM',
            'caesars': 'Caesars',
            'pointsbet': 'PointsBet'
        }
        bp_sportsbook = sportsbook_mapping.get(sportsbook.lower(), sportsbook)

        query = """
        SELECT
            points_line as line_value,
            bookmaker,
            created_at
        FROM `{project}.nba_raw.bettingpros_player_points_props`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
          AND bookmaker = @sportsbook
          AND market_type = 'points'
          AND bet_side = 'over'
          AND is_active = TRUE
        ORDER BY created_at DESC
        LIMIT 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("sportsbook", "STRING", bp_sportsbook)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=30)
            row = next(results, None)

            if row is not None and row.line_value is not None:
                return {
                    'line_value': float(row.line_value),
                    'sportsbook': row.bookmaker.upper() if row.bookmaker else sportsbook.upper(),
                    'was_fallback': sportsbook.lower() != 'draftkings',
                    'line_source_api': 'BETTINGPROS',
                    'line_minutes_before_game': None
                }
            return None
        except Exception as e:
            logger.warning(f"No {sportsbook} line in bettingpros for {player_lookup}: {e}")
            return None

    def _query_kalshi_line(
        self,
        player_lookup: str,
        game_date: date,
        vegas_line: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Query Kalshi prediction market for player prop lines.

        Session 79: Kalshi offers multiple lines per player (e.g., 19.5, 24.5, 29.5).
        We find the line closest to the Vegas line for comparison.

        Args:
            player_lookup: Player identifier
            game_date: Game date
            vegas_line: Vegas line to find closest Kalshi line to

        Returns:
            Dict with kalshi_line, kalshi_yes_price, kalshi_no_price,
            kalshi_liquidity, kalshi_market_ticker, line_discrepancy
            or None if no Kalshi data
        """
        try:
            # Query Kalshi data - find the line closest to Vegas line
            if vegas_line is not None:
                # Find the Kalshi line closest to Vegas line
                query = """
                    SELECT
                        line_value,
                        yes_bid,
                        no_bid,
                        liquidity_score,
                        market_ticker,
                        ABS(line_value - @vegas_line) as line_diff
                    FROM `{project}.nba_raw.kalshi_player_props`
                    WHERE game_date = @game_date
                      AND player_lookup = @player_lookup
                      AND prop_type = 'points'
                      AND market_status = 'active'
                    ORDER BY line_diff ASC
                    LIMIT 1
                """.format(project=self.project_id)

                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                        bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                        bigquery.ScalarQueryParameter("vegas_line", "FLOAT64", vegas_line),
                    ]
                )
            else:
                # No Vegas line - just get the first available Kalshi line
                query = """
                    SELECT
                        line_value,
                        yes_bid,
                        no_bid,
                        liquidity_score,
                        market_ticker
                    FROM `{project}.nba_raw.kalshi_player_props`
                    WHERE game_date = @game_date
                      AND player_lookup = @player_lookup
                      AND prop_type = 'points'
                      AND market_status = 'active'
                    ORDER BY total_volume DESC
                    LIMIT 1
                """.format(project=self.project_id)

                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                        bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                    ]
                )

            results = self.bq_client.query(query, job_config=job_config).result(timeout=30)
            row = next(results, None)

            if row is not None and row.line_value is not None:
                kalshi_line = float(row.line_value)
                line_discrepancy = round(kalshi_line - vegas_line, 1) if vegas_line else None

                return {
                    'kalshi_available': True,
                    'kalshi_line': kalshi_line,
                    'kalshi_yes_price': int(row.yes_bid) if row.yes_bid else None,
                    'kalshi_no_price': int(row.no_bid) if row.no_bid else None,
                    'kalshi_liquidity': row.liquidity_score,
                    'kalshi_market_ticker': row.market_ticker,
                    'line_discrepancy': line_discrepancy
                }
            return None
        except Exception as e:
            logger.debug(f"No Kalshi line for {player_lookup}: {e}")
            return None

    def _track_no_line_reason(self, player_lookup: str, game_date: date):
        """
        Session 175: Diagnostic logging when no betting line found for a player.
        Checks OddsAPI raw data to distinguish: no data at all vs player name mismatch.
        """
        try:
            # Check if OddsAPI has ANY data for this player on this date
            query = """
            SELECT COUNT(*) as cnt
            FROM `{project}.nba_raw.odds_api_player_points_props`
            WHERE player_lookup = @player_lookup AND game_date = @game_date
            """.format(project=self.project_id)
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ])
            result = next(self.client.query(query, job_config=job_config).result(timeout=10))
            if result.cnt > 0:
                logger.warning(
                    f"NO_LINE_DIAGNOSTIC: {player_lookup} has {result.cnt} OddsAPI rows on {game_date} "
                    f"but none matched sportsbook filters — possible bookmaker name mismatch"
                )
            else:
                logger.warning(
                    f"NO_LINE_DIAGNOSTIC: {player_lookup} has ZERO OddsAPI rows on {game_date} — "
                    f"player not offered as prop or name format mismatch"
                )
        except Exception as e:
            logger.warning(f"NO_LINE_DIAGNOSTIC: Could not diagnose {player_lookup}: {e}")

    def diagnose_odds_api_coverage(self, game_date: date, player_lookups: list = None):
        """
        Session 175: Batch-level OddsAPI availability diagnostic.
        Run once per batch to understand overall coverage.

        Returns dict with coverage stats and logs warnings.
        """
        try:
            query = """
            SELECT
              COUNT(DISTINCT player_lookup) as oddsapi_players,
              COUNT(DISTINCT bookmaker) as bookmakers,
              COUNT(*) as total_rows,
              ARRAY_AGG(DISTINCT LOWER(bookmaker) ORDER BY LOWER(bookmaker)) as bookmaker_list
            FROM `{project}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
            """.format(project=self.project_id)
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ])
            result = next(self.client.query(query, job_config=job_config).result(timeout=30))

            coverage = {
                'oddsapi_players': result.oddsapi_players,
                'bookmakers': result.bookmakers,
                'total_rows': result.total_rows,
                'bookmaker_list': list(result.bookmaker_list) if result.bookmaker_list else [],
            }

            if player_lookups:
                coverage['requested_players'] = len(player_lookups)
                coverage['coverage_pct'] = round(100 * result.oddsapi_players / len(player_lookups), 1) if player_lookups else 0

            logger.info(
                f"ODDS_API_COVERAGE: {game_date} — {result.oddsapi_players} players, "
                f"{result.bookmakers} bookmakers, {result.total_rows} rows, "
                f"books={coverage['bookmaker_list']}"
            )

            if result.oddsapi_players == 0:
                logger.error(f"ODDS_API_COVERAGE: ZERO players in OddsAPI for {game_date} — scraper may have failed")
            elif player_lookups and result.oddsapi_players < len(player_lookups) * 0.3:
                logger.warning(
                    f"ODDS_API_COVERAGE: Only {result.oddsapi_players}/{len(player_lookups)} players "
                    f"({coverage.get('coverage_pct', 0)}%) in OddsAPI for {game_date}"
                )

            return coverage
        except Exception as e:
            logger.error(f"ODDS_API_COVERAGE: Diagnostic query failed: {e}")
            return {'error': str(e)}

    def _track_line_source(self, source: str, player_lookup: str):
        """
        Track line source usage for monitoring/alerting.

        v3.9: Extended to track sportsbook-specific sources
        Sources: odds_api_draftkings, odds_api_fanduel, bettingpros_draftkings, etc.
        """
        if not hasattr(self, '_line_source_stats'):
            self._line_source_stats = {
                'by_source': {},  # Detailed: odds_api_draftkings, bettingpros_fanduel, etc.
                'by_api': {'odds_api': 0, 'bettingpros': 0},  # Aggregated by API
                'by_sportsbook': {},  # Aggregated by sportsbook
                'no_line_data': 0,
                'players': {}
            }

        # Track detailed source
        self._line_source_stats['by_source'][source] = self._line_source_stats['by_source'].get(source, 0) + 1

        # Parse and aggregate
        if source == 'no_line_data':
            self._line_source_stats['no_line_data'] += 1
            self._line_source_stats['players'][player_lookup] = source
        elif source.startswith('odds_api_'):
            self._line_source_stats['by_api']['odds_api'] += 1
            sportsbook = source.replace('odds_api_', '')
            self._line_source_stats['by_sportsbook'][sportsbook] = self._line_source_stats['by_sportsbook'].get(sportsbook, 0) + 1
        elif source.startswith('bettingpros_'):
            self._line_source_stats['by_api']['bettingpros'] += 1
            sportsbook = source.replace('bettingpros_', '')
            self._line_source_stats['by_sportsbook'][sportsbook] = self._line_source_stats['by_sportsbook'].get(sportsbook, 0) + 1
            # Track bettingpros usage for monitoring
            self._line_source_stats['players'][player_lookup] = source

    def get_line_source_stats(self) -> dict:
        """
        Get line source statistics for the current session.

        Returns:
            Dict with:
            - by_source: Detailed counts (odds_api_draftkings, bettingpros_fanduel, etc.)
            - by_api: Aggregated by API (odds_api, bettingpros)
            - by_sportsbook: Aggregated by sportsbook (draftkings, fanduel, etc.)
            - no_line_data: Count of players with no lines
            - summary: Calculated percentages and health indicators
        """
        if not hasattr(self, '_line_source_stats'):
            return {
                'by_source': {},
                'by_api': {'odds_api': 0, 'bettingpros': 0},
                'by_sportsbook': {},
                'no_line_data': 0,
                'players': {},
                'summary': {}
            }

        stats = {
            'by_source': self._line_source_stats['by_source'].copy(),
            'by_api': self._line_source_stats['by_api'].copy(),
            'by_sportsbook': self._line_source_stats['by_sportsbook'].copy(),
            'no_line_data': self._line_source_stats['no_line_data'],
            'players': self._line_source_stats['players'].copy()
        }

        # Calculate summary stats
        total_api = stats['by_api']['odds_api'] + stats['by_api']['bettingpros']
        total = total_api + stats['no_line_data']

        if total > 0:
            # Preferred sportsbook coverage
            dk_count = stats['by_sportsbook'].get('draftkings', 0)
            fd_count = stats['by_sportsbook'].get('fanduel', 0)
            preferred_count = dk_count + fd_count

            stats['summary'] = {
                'total_players': total,
                'with_lines': total_api,
                'no_lines': stats['no_line_data'],
                'odds_api_pct': round(100 * stats['by_api']['odds_api'] / total, 1) if total else 0,
                'bettingpros_pct': round(100 * stats['by_api']['bettingpros'] / total, 1) if total else 0,
                'preferred_sportsbook_pct': round(100 * preferred_count / total, 1) if total else 0,
                'draftkings_pct': round(100 * dk_count / total, 1) if total else 0,
                'fanduel_pct': round(100 * fd_count / total, 1) if total else 0,
            }

            # Health alerts
            if stats['no_line_data'] > total * 0.1:
                logger.warning(f"LINE_HEALTH: {stats['no_line_data']}/{total} ({round(100*stats['no_line_data']/total,1)}%) players have NO betting lines")
            if stats['by_api']['bettingpros'] > stats['by_api']['odds_api']:
                logger.warning(f"LINE_HEALTH: More BettingPros ({stats['by_api']['bettingpros']}) than OddsAPI ({stats['by_api']['odds_api']}) - check OddsAPI health")
            if preferred_count < total * 0.5:
                logger.warning(f"LINE_HEALTH: Only {preferred_count}/{total} ({stats['summary']['preferred_sportsbook_pct']}%) using DraftKings/FanDuel")
        else:
            stats['summary'] = {}

        return stats

    def _query_odds_api_betting_line(
        self,
        player_lookup: str,
        game_date: date
    ) -> Optional[Dict[str, Any]]:
        """
        Query betting line from odds_api_player_points_props table.

        Gets the most recent line for this player/date.
        Fallback order: DraftKings -> FanDuel -> BetMGM

        Args:
            player_lookup: Player identifier
            game_date: Game date

        Returns:
            Dict with line_value, sportsbook, was_fallback, line_source_api
            or None if no line found
        """
        sportsbook_priority = ['draftkings', 'fanduel', 'betmgm', 'pointsbet', 'caesars']

        query = """
        SELECT
            points_line as line_value,
            bookmaker,
            minutes_before_tipoff
        FROM `{project}.nba_raw.odds_api_player_points_props`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
          AND bookmaker IN UNNEST(@sportsbooks)
        ORDER BY
            CASE bookmaker
                WHEN 'draftkings' THEN 1
                WHEN 'fanduel' THEN 2
                WHEN 'betmgm' THEN 3
                WHEN 'pointsbet' THEN 4
                WHEN 'caesars' THEN 5
                ELSE 99
            END,
            snapshot_timestamp DESC
        LIMIT 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ArrayQueryParameter("sportsbooks", "STRING", sportsbook_priority)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            row = next(results, None)

            if row is not None and row.line_value is not None:
                sportsbook = row.bookmaker.upper() if row.bookmaker else 'UNKNOWN'
                was_fallback = row.bookmaker and row.bookmaker.lower() != 'draftkings'

                return {
                    'line_value': float(row.line_value),
                    'sportsbook': sportsbook,
                    'was_fallback': was_fallback,
                    'line_source_api': 'ODDS_API',
                    'line_minutes_before_game': int(row.minutes_before_tipoff) if row.minutes_before_tipoff else None
                }

            return None

        except Exception as e:
            logger.warning(f"No betting line found in odds_api for {player_lookup}: {e}")
            return None

    def _query_bettingpros_betting_line(
        self,
        player_lookup: str,
        game_date: date
    ) -> Optional[Dict[str, Any]]:
        """
        Query betting line from bettingpros_player_points_props table (v3.8 fallback).

        Gets the best line for this player/date from bettingpros data.
        Prefers DraftKings, then falls back to other bookmakers.

        Args:
            player_lookup: Player identifier
            game_date: Game date

        Returns:
            Dict with line_value, sportsbook, was_fallback, line_source_api
            or None if no line found
        """
        sportsbook_priority = ['DraftKings', 'FanDuel', 'BetMGM', 'Caesars', 'PointsBet']

        query = """
        SELECT
            points_line as line_value,
            bookmaker,
            created_at
        FROM `{project}.nba_raw.bettingpros_player_points_props`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
          AND market_type = 'points'
          AND bet_side = 'over'  -- Only need one side for the line value
          AND is_active = TRUE
        ORDER BY
            CASE bookmaker
                WHEN 'DraftKings' THEN 1
                WHEN 'FanDuel' THEN 2
                WHEN 'BetMGM' THEN 3
                WHEN 'Caesars' THEN 4
                WHEN 'PointsBet' THEN 5
                ELSE 99
            END,
            created_at DESC
        LIMIT 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            row = next(results, None)

            if row is not None and row.line_value is not None:
                sportsbook = row.bookmaker.upper() if row.bookmaker else 'BETTINGPROS'
                was_fallback = True  # Bettingpros is always a fallback source

                return {
                    'line_value': float(row.line_value),
                    'sportsbook': sportsbook,
                    'was_fallback': was_fallback,
                    'line_source_api': 'BETTINGPROS',
                    'line_minutes_before_game': None  # Bettingpros doesn't track this
                }

            return None

        except Exception as e:
            logger.warning(f"No betting line found in bettingpros for {player_lookup}: {e}")
            return None
    
    def _estimate_betting_line(self, player_lookup: str) -> float:
        """
        Estimate betting line from player's season average (legacy method)

        Uses most recent season average from player_game_summary

        Args:
            player_lookup: Player identifier

        Returns:
            float: Estimated line (defaults to 15.5 if no data)
        """
        line, _ = self._estimate_betting_line_with_method(player_lookup)
        return line

    def _estimate_betting_line_with_method(self, player_lookup: str) -> Tuple[Optional[float], str]:
        """
        Estimate betting line with method tracking (v3.2)

        Uses most recent season average from upcoming_player_game_context
        Returns both the estimated line and the method used.

        Issue 3 Enhancement: No longer uses default 15.5 for new players.
        Returns None if player doesn't have sufficient history, marking them
        as needs_bootstrap.

        Args:
            player_lookup: Player identifier

        Returns:
            Tuple of (estimated_line, estimation_method)
            Methods: 'points_avg_last_5', 'points_avg_last_10', 'needs_bootstrap', 'config_default'
            Returns (None, 'needs_bootstrap') for new players without history
        """
        config = get_orchestration_config()

        # Use upcoming_player_game_context which has the actual averages
        query = """
        SELECT
            points_avg_last_5,
            points_avg_last_10,
            l10_games_used as games_played
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE player_lookup = @player_lookup
        ORDER BY game_date DESC
        LIMIT 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            row = next(results, None)

            if row is not None:
                # Check if player has minimum games (Issue 3: new player handling)
                games_played = row.games_played or 0
                if games_played < config.new_player.min_games_required:
                    logger.info(
                        f"Player {player_lookup} has only {games_played} games "
                        f"(min required: {config.new_player.min_games_required}), "
                        f"marking as needs_bootstrap"
                    )
                    if config.new_player.use_default_line:
                        return config.new_player.default_line_value, 'config_default'
                    return None, 'needs_bootstrap'

                # Prefer L5 average, fallback to L10
                if row.points_avg_last_5 is not None:
                    avg = float(row.points_avg_last_5)
                    # Round to nearest 0.5 (common for betting lines)
                    estimated = round(avg * 2) / 2.0
                    # v3.9: Avoid exact 20.0 which is flagged as placeholder
                    # Slightly adjust to 20.5 or 19.5 based on actual average
                    if estimated == 20.0:
                        estimated = 20.5 if avg >= 20.0 else 19.5
                        logger.debug(f"Adjusted estimated line from 20.0 to {estimated} for {player_lookup}")
                    return estimated, 'points_avg_last_5'
                elif row.points_avg_last_10 is not None:
                    avg = float(row.points_avg_last_10)
                    estimated = round(avg * 2) / 2.0
                    # v3.9: Avoid exact 20.0 which is flagged as placeholder
                    if estimated == 20.0:
                        estimated = 20.5 if avg >= 20.0 else 19.5
                        logger.debug(f"Adjusted estimated line from 20.0 to {estimated} for {player_lookup}")
                    return estimated, 'points_avg_last_10'

            # No data found - mark as needs_bootstrap (Issue 3)
            logger.info(f"No historical data found for {player_lookup}, marking as needs_bootstrap")
            if config.new_player.use_default_line:
                return config.new_player.default_line_value, 'config_default'
            return None, 'needs_bootstrap'

        except Exception as e:
            logger.error(f"Error estimating line for {player_lookup}: {e}", exc_info=True)
            if config.new_player.use_default_line:
                return config.new_player.default_line_value, 'config_default'
            return None, 'needs_bootstrap'

    def _get_player_baseline(self, player_lookup: str) -> Optional[float]:
        """
        Get player's L5 points average as baseline reference (v3.10).

        This is always populated for reference, even when we have real betting lines.
        Allows tracking "did we beat the player's average?" and comparing
        how far Vegas was from the baseline.

        Args:
            player_lookup: Player identifier

        Returns:
            float: Player's L5 average rounded to nearest 0.5 (like betting lines)
            None: If no data available
        """
        query = """
        SELECT points_avg_last_5
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE player_lookup = @player_lookup
        ORDER BY game_date DESC
        LIMIT 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=30)
            row = next(results, None)
            if row and row.points_avg_last_5:
                avg = float(row.points_avg_last_5)
                # Round to nearest 0.5 (matches betting line increments)
                return round(avg * 2) / 2.0
            return None
        except Exception as e:
            logger.debug(f"Could not get baseline for {player_lookup}: {e}")
            return None

    # ========================================================================
    # VALIDATION & DEBUGGING UTILITIES
    # ========================================================================
    
    def validate_player_exists(self, player_lookup: str, game_date: date) -> bool:
        """
        Check if player has a game on the specified date
        
        Useful for validating manual prediction requests
        
        Args:
            player_lookup: Player identifier
            game_date: Game date
        
        Returns:
            bool: True if player has game, False otherwise
        """
        query = """
        SELECT COUNT(*) as count
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            row = next(results, None)
            return row.count > 0 if row else False
        except Exception as e:
            logger.error(f"Error validating player {player_lookup}: {e}", exc_info=True)
            return False
    
    def get_players_for_game(self, game_id: str) -> List[Dict]:
        """
        Get all players for a specific game
        
        Useful for debugging or targeted predictions for a single game
        
        Args:
            game_id: Game identifier (e.g., '20251108_LAL_GSW')
        
        Returns:
            List of player dicts for that game
        """
        query = """
        SELECT
            player_lookup,
            team_abbr,
            opponent_team_abbr,
            COALESCE(avg_minutes_per_game_last_7, 0) as projected_minutes,  -- v3.7: Default to 0 for injury-return players
            player_status as injury_status
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE game_id = @game_id
        ORDER BY team_abbr, avg_minutes_per_game_last_7 DESC
        LIMIT 50  -- Memory optimization: Single game has max ~30 players, 50 is safe upper bound
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_id", "STRING", game_id)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            
            players = []
            for row in results:
                players.append({
                    'player_lookup': row.player_lookup,
                    'team_abbr': row.team_abbr,
                    'opponent_team_abbr': row.opponent_team_abbr,
                    'projected_minutes': float(row.projected_minutes or 0),  # v3.7: Handle NULL for injury-return players
                    'injury_status': row.injury_status
                })
            
            logger.info(f"Found {len(players)} players for game {game_id}")
            return players
            
        except Exception as e:
            logger.error(f"Error getting players for game {game_id}: {e}", exc_info=True)
            return []
    
    # ========================================================================
    # BATCH OPERATIONS (Future optimization)
    # ========================================================================
    
    def get_players_with_stale_predictions(
        self,
        game_date: date,
        line_change_threshold: float = 1.0
    ) -> List[str]:
        """
        Get players whose predictions are stale (betting lines changed significantly)

        Compares current betting lines vs lines used when predictions were made.
        Returns players where line moved >= threshold (default 1.0 point).

        This is a Phase 6 feature for real-time prediction updates when betting
        markets move significantly. It prevents serving predictions based on
        outdated lines that could mislead users.

        Implementation:
        - Queries latest lines from bettingpros_player_points_props
        - Compares with lines stored in player_prop_predictions
        - Returns players where ABS(current_line - prediction_line) >= threshold
        - Uses QUALIFY for efficient deduplication

        Integration Example (in coordinator.py):
            # Before generating new predictions, check for stale ones
            stale_players = player_loader.get_players_with_stale_predictions(
                game_date=today,
                line_change_threshold=1.0
            )
            if stale_players:
                logger.info(f"Regenerating {len(stale_players)} stale predictions")
                # Create requests only for stale players
                for player_lookup in stale_players:
                    publish_prediction_request(player_lookup, today)

        Args:
            game_date: Game date to check
            line_change_threshold: Minimum line change to trigger regeneration (default: 1.0 point)

        Returns:
            List of player_lookup values needing prediction regeneration

        Example:
            >>> loader = PlayerLoader('nba-props-platform')
            >>> stale = loader.get_players_with_stale_predictions(
            ...     game_date=date(2026, 1, 24),
            ...     line_change_threshold=1.0
            ... )
            >>> print(stale)
            ['klaythompson', 'tyresemaxey', 'nazreid']
        """
        query = """
        WITH current_lines AS (
            -- Get most recent betting line for each player
            SELECT
                player_lookup,
                points_line as current_line,
                created_at
            FROM `{project}.nba_raw.bettingpros_player_points_props`
            WHERE game_date = @game_date
              AND bet_side = 'over'
              AND is_active = TRUE
              AND points_line IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY created_at DESC
            ) = 1
        ),
        prediction_lines AS (
            -- Get lines used in predictions (deduplicated by player)
            SELECT
                player_lookup,
                current_points_line as prediction_line,
                created_at
            FROM `{project}.nba_predictions.player_prop_predictions`
            WHERE game_date = @game_date
              AND current_points_line IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY created_at DESC
            ) = 1
        )
        SELECT DISTINCT
            p.player_lookup,
            p.prediction_line,
            c.current_line,
            ABS(c.current_line - p.prediction_line) as line_change
        FROM prediction_lines p
        JOIN current_lines c
            ON p.player_lookup = c.player_lookup
        WHERE ABS(c.current_line - p.prediction_line) >= @threshold
        ORDER BY line_change DESC
        LIMIT 500  -- Memory optimization: Cap stale predictions check at 500 players
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("threshold", "FLOAT64", line_change_threshold)
            ]
        )

        try:
            result = self.client.query(query, job_config=job_config).result(timeout=30)
            stale_players = [row.player_lookup for row in result]

            if stale_players:
                logger.info(
                    f"Found {len(stale_players)} players with stale predictions "
                    f"(line changes >= {line_change_threshold} points) for {game_date}"
                )
                # Log details for debugging
                result = self.client.query(query, job_config=job_config).result(timeout=30)
                for row in list(result)[:5]:  # Log first 5 for debugging
                    logger.debug(
                        f"  {row.player_lookup}: prediction_line={row.prediction_line:.1f}, "
                        f"current_line={row.current_line:.1f}, change={row.line_change:.1f}"
                    )
                if len(stale_players) > 5:
                    logger.debug(f"  ... and {len(stale_players) - 5} more")
            else:
                logger.info(f"No stale predictions found for {game_date} (threshold={line_change_threshold})")

            return stale_players

        except Exception as e:
            logger.error(f"Error detecting stale predictions for {game_date}: {e}", exc_info=True)
            return []

    def get_players_with_new_lines(
        self,
        game_date: date
    ) -> List[str]:
        """
        Session 152: Detect players predicted WITHOUT lines who now have lines available.

        Used by /check-lines endpoint to trigger targeted re-prediction when
        betting lines arrive for players who were previously predicted without them.

        Args:
            game_date: Game date to check

        Returns:
            List of player_lookup values needing re-prediction due to new lines
        """
        query = """
        WITH predicted_without_lines AS (
            SELECT DISTINCT player_lookup
            FROM `{project}.nba_predictions.player_prop_predictions`
            WHERE game_date = @game_date
              AND is_active = TRUE
              AND system_id = 'catboost_v9'
              AND (current_points_line IS NULL
                   OR vegas_line_source = 'none'
                   OR vegas_line_source IS NULL)
        ),
        raw_lines_now AS (
            SELECT DISTINCT player_lookup FROM (
                SELECT player_lookup FROM `{project}.nba_raw.odds_api_player_points_props`
                WHERE game_date = @game_date
                  AND points_line IS NOT NULL AND points_line > 0
                UNION DISTINCT
                SELECT player_lookup FROM `{project}.nba_raw.bettingpros_player_points_props`
                WHERE game_date = @game_date
                  AND market_type = 'points'
                  AND points_line IS NOT NULL AND points_line > 0
            )
        )
        SELECT p.player_lookup
        FROM predicted_without_lines p
        INNER JOIN raw_lines_now r ON p.player_lookup = r.player_lookup
        LIMIT 500
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            result = self.client.query(query, job_config=job_config).result(timeout=30)
            new_line_players = [row.player_lookup for row in result]

            if new_line_players:
                logger.info(
                    f"Found {len(new_line_players)} players with new lines available "
                    f"(previously predicted without lines) for {game_date}"
                )
                for p in new_line_players[:5]:
                    logger.debug(f"  New line available: {p}")
                if len(new_line_players) > 5:
                    logger.debug(f"  ... and {len(new_line_players) - 5} more")
            else:
                logger.info(f"No new lines found for players predicted without lines on {game_date}")

            return new_line_players

        except Exception as e:
            logger.error(f"Error detecting new lines for {game_date}: {e}", exc_info=True)
            return []

    def close(self):
        """Close BigQuery client connection"""
        self.client.close()
        logger.info("Closed BigQuery client connection")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def validate_game_date(game_date: date) -> bool:
    """
    Validate game date is reasonable

    Prevents querying dates too far in past or future

    Args:
        game_date: Date to validate

    Returns:
        bool: True if valid, False otherwise
    """
    today = date.today()

    # Allow dates up to 90 days in the past (extended for Phase 4 XGBoost regeneration)
    # TEMPORARY: Increased from 30 to 90 days to allow Nov 2025 regeneration
    if (today - game_date).days > 90:
        logger.warning(f"Game date {game_date} is too far in the past (>90 days)")
        return False

    # Can't be too far in the future (more than 14 days)
    if (game_date - today).days > 14:
        logger.warning(f"Game date {game_date} is too far in the future")
        return False

    return True


def get_nba_season(game_date: date) -> str:
    """
    Get NBA season for a given date
    
    NBA seasons are YYYY-YY format (e.g., '2024-25')
    Season starts in October
    
    Args:
        game_date: Date to get season for
    
    Returns:
        str: Season string (e.g., '2024-25')
    """
    year = game_date.year
    
    # If before July, season started previous year
    if game_date.month < 7:
        season_start_year = year - 1
    else:
        season_start_year = year
    
    season_end_year = str(season_start_year + 1)[-2:]  # Last 2 digits
    
    return f"{season_start_year}-{season_end_year}"


def create_manual_prediction_request(
    player_lookup: str,
    game_date: date,
    game_id: str,
    line_values: List[float]
) -> Dict:
    """
    Create a manual prediction request for testing
    
    Useful for testing worker with specific players/scenarios
    
    Args:
        player_lookup: Player identifier
        game_date: Game date
        game_id: Game identifier
        line_values: List of line values to test
    
    Returns:
        dict: Prediction request ready for Pub/Sub
    """
    return {
        'player_lookup': player_lookup,
        'game_date': game_date.isoformat() if isinstance(game_date, date) else game_date,
        'game_id': game_id,
        'line_values': line_values
    }