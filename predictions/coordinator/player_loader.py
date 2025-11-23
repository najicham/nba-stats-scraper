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

Version: 1.1 (Merged - adds validation and debugging utilities)
"""

from typing import Dict, List, Optional
from google.cloud import bigquery
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)


class PlayerLoader:
    """
    Loads players scheduled to play on a given date
    
    Queries Phase 3 upcoming_player_game_context table and creates
    prediction request messages for the worker.
    """
    
    def __init__(self, project_id: str):
        """
        Initialize player loader
        
        Args:
            project_id: GCP project ID (e.g., 'nba-props-platform')
        """
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        
        logger.info(f"Initialized PlayerLoader for project {project_id}")
    
    # ========================================================================
    # MAIN API
    # ========================================================================
    
    def create_prediction_requests(
        self,
        game_date: date,
        min_minutes: int = 15,
        use_multiple_lines: bool = False
    ) -> List[Dict]:
        """
        Create prediction requests for all players with games on given date
        
        Args:
            game_date: Date to get players for
            min_minutes: Minimum projected minutes (default: 15)
            use_multiple_lines: If True, test multiple betting lines (default: False)
        
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
        logger.info(f"Creating prediction requests for {game_date} (min_minutes={min_minutes})")
        
        # Validate date before querying
        if not validate_game_date(game_date):
            logger.error(f"Invalid game date: {game_date}")
            return []
        
        # Get all players with games on this date
        players = self._query_players_for_date(game_date, min_minutes)
        
        if not players:
            logger.warning(f"No players found for {game_date}")
            return []
        
        logger.info(f"Found {len(players)} players for {game_date}")
        
        # Create prediction requests
        requests = []
        for player in players:
            request = self._create_request_for_player(
                player,
                game_date,
                use_multiple_lines
            )
            requests.append(request)
        
        return requests
    
    def get_summary_stats(self, game_date: date) -> Dict:
        """
        Get summary statistics for games on given date
        
        Includes breakdown by position for validation
        
        Args:
            game_date: Date to get stats for
        
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
        query = """
        SELECT
            COUNT(DISTINCT game_id) as total_games,
            COUNT(DISTINCT player_lookup) as total_players,
            COUNT(DISTINCT team_abbr) as teams_playing,
            AVG(projected_minutes) as avg_projected_minutes,
            MIN(projected_minutes) as min_projected_minutes,
            MAX(projected_minutes) as max_projected_minutes,

            -- Players by position (for validation)
            COUNTIF(position = 'PG') as pg_count,
            COUNTIF(position = 'SG') as sg_count,
            COUNTIF(position = 'SF') as sf_count,
            COUNTIF(position = 'PF') as pf_count,
            COUNTIF(position = 'C') as c_count,

            -- Completeness tracking (Phase 5)
            COUNTIF(is_production_ready = TRUE) as production_ready_count,
            COUNTIF(is_production_ready = FALSE OR is_production_ready IS NULL) as not_ready_count,
            AVG(completeness_percentage) as avg_completeness_pct
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = @game_date
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result()
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
                'players_by_position': {
                    'PG': row.pg_count or 0,
                    'SG': row.sg_count or 0,
                    'SF': row.sf_count or 0,
                    'PF': row.pf_count or 0,
                    'C': row.c_count or 0
                },
                'completeness': {
                    'production_ready_count': int(row.production_ready_count or 0),
                    'not_ready_count': int(row.not_ready_count or 0),
                    'avg_completeness_pct': round(float(row.avg_completeness_pct or 0), 2)
                }
            }
            
            logger.info(
                f"Summary for {game_date}: {summary['total_games']} games, "
                f"{summary['total_players']} players "
                f"({summary['completeness']['production_ready_count']} production ready, "
                f"avg completeness: {summary['completeness']['avg_completeness_pct']}%)"
            )
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting summary stats for {game_date}: {e}")
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
    
    def _query_players_for_date(
        self,
        game_date: date,
        min_minutes: int
    ) -> List[Dict]:
        """
        Query BigQuery for all players with games on given date
        
        Filters out:
        - Players below minimum minutes threshold
        - Inactive players
        - Injured players (OUT or DOUBTFUL status)
        
        Args:
            game_date: Date to query
            min_minutes: Minimum projected minutes
        
        Returns:
            List of player dicts with game context
        """
        query = """
        SELECT
            player_lookup,
            universal_player_id,
            game_id,
            game_date,
            team_abbr,
            opponent_team_abbr,
            is_home,
            days_rest,
            back_to_back,
            projected_minutes,
            is_active,
            injury_status,
            position
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = @game_date
          AND projected_minutes >= @min_minutes
          AND is_active = TRUE
          AND (injury_status IS NULL OR injury_status NOT IN ('OUT', 'DOUBTFUL'))
          AND is_production_ready = TRUE  -- Only process players with complete upstream data
        ORDER BY projected_minutes DESC
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("min_minutes", "INT64", min_minutes)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result()
            
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
                    'projected_minutes': float(row.projected_minutes),
                    'is_active': row.is_active,
                    'injury_status': row.injury_status,
                    'position': row.position
                }
                players.append(player)
            
            logger.info(f"Queried {len(players)} players for {game_date}")
            return players
            
        except Exception as e:
            logger.error(f"Error querying players for {game_date}: {e}")
            return []
    
    def _create_request_for_player(
        self,
        player: Dict,
        game_date: date,
        use_multiple_lines: bool
    ) -> Dict:
        """
        Create prediction request message for a single player
        
        Args:
            player: Player dict from query
            game_date: Game date
            use_multiple_lines: Whether to test multiple lines
        
        Returns:
            Prediction request dict
        """
        # Get betting lines for this player
        lines = self._get_betting_lines(
            player['player_lookup'],
            game_date,
            use_multiple_lines
        )
        
        # Create request message
        request = {
            'player_lookup': player['player_lookup'],
            'game_date': game_date.isoformat(),
            'game_id': player['game_id'],
            'line_values': lines,
            
            # Optional context (for debugging/monitoring)
            'team_abbr': player['team_abbr'],
            'opponent_team_abbr': player['opponent_team_abbr'],
            'is_home': player['is_home'],
            'projected_minutes': player['projected_minutes'],
            'position': player.get('position')
        }
        
        return request
    
    def _get_betting_lines(
        self,
        player_lookup: str,
        game_date: date,
        use_multiple_lines: bool
    ) -> List[float]:
        """
        Get betting lines for player
        
        Strategy:
        1. Try to query from odds_player_props table (Phase 2)
        2. If no odds available, use estimated line based on season average
        3. If use_multiple_lines=True, generate +/- 2 points from base line
        
        Args:
            player_lookup: Player identifier
            game_date: Game date
            use_multiple_lines: Whether to generate multiple lines
        
        Returns:
            List of line values (e.g., [25.5] or [23.5, 24.5, 25.5, 26.5, 27.5])
        """
        # Try to get actual betting line from odds data
        actual_line = self._query_actual_betting_line(player_lookup, game_date)
        
        if actual_line is not None:
            base_line = actual_line
            logger.debug(f"Using actual betting line {base_line} for {player_lookup}")
        else:
            # Fallback: Estimate from season average
            base_line = self._estimate_betting_line(player_lookup)
            logger.debug(f"Using estimated line {base_line} for {player_lookup}")
        
        # Generate multiple lines if requested
        if use_multiple_lines:
            # Generate 5 lines: base_line ± 2 in 1-point increments
            lines = [
                round(base_line - 2.0, 1),
                round(base_line - 1.0, 1),
                round(base_line, 1),
                round(base_line + 1.0, 1),
                round(base_line + 2.0, 1)
            ]
        else:
            lines = [round(base_line, 1)]
        
        return lines
    
    def _query_actual_betting_line(
        self,
        player_lookup: str,
        game_date: date
    ) -> Optional[float]:
        """
        Query actual betting line from odds_player_props table
        
        Gets the most recent line for this player/date
        
        Args:
            player_lookup: Player identifier
            game_date: Game date
        
        Returns:
            float: Betting line or None if not found
        """
        query = """
        SELECT
            line_value
        FROM `{project}.nba_raw.odds_player_props`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
          AND market = 'player_points'
          AND bookmaker = 'draftkings'  -- Use DraftKings as default
        ORDER BY snapshot_timestamp DESC
        LIMIT 1
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result()
            row = next(results, None)
            
            if row is not None and row.line_value is not None:
                return float(row.line_value)
            
            return None
            
        except Exception as e:
            logger.debug(f"No betting line found for {player_lookup}: {e}")
            return None
    
    def _estimate_betting_line(self, player_lookup: str) -> float:
        """
        Estimate betting line from player's season average
        
        Uses most recent season average from player_game_summary
        
        Args:
            player_lookup: Player identifier
        
        Returns:
            float: Estimated line (defaults to 15.5 if no data)
        """
        query = """
        SELECT
            points_avg_season
        FROM `{project}.nba_analytics.player_game_summary`
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
            results = self.client.query(query, job_config=job_config).result()
            row = next(results, None)
            
            if row is not None and row.points_avg_season is not None:
                # Round to nearest 0.5 (common for betting lines)
                avg = float(row.points_avg_season)
                return round(avg * 2) / 2.0
            
            # Default fallback
            logger.warning(f"No season average found for {player_lookup}, using default 15.5")
            return 15.5
            
        except Exception as e:
            logger.error(f"Error estimating line for {player_lookup}: {e}")
            return 15.5
    
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
          AND is_active = TRUE
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result()
            row = next(results, None)
            return row.count > 0 if row else False
        except Exception as e:
            logger.error(f"Error validating player {player_lookup}: {e}")
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
            projected_minutes,
            position,
            injury_status
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE game_id = @game_id
          AND is_active = TRUE
        ORDER BY team_abbr, projected_minutes DESC
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_id", "STRING", game_id)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result()
            
            players = []
            for row in results:
                players.append({
                    'player_lookup': row.player_lookup,
                    'team_abbr': row.team_abbr,
                    'opponent_team_abbr': row.opponent_team_abbr,
                    'projected_minutes': float(row.projected_minutes),
                    'position': row.position,
                    'injury_status': row.injury_status
                })
            
            logger.info(f"Found {len(players)} players for game {game_id}")
            return players
            
        except Exception as e:
            logger.error(f"Error getting players for game {game_id}: {e}")
            return []
    
    # ========================================================================
    # BATCH OPERATIONS (Future optimization)
    # ========================================================================
    
    def get_players_with_stale_predictions(
        self,
        game_date: date,
        stale_threshold_minutes: int = 60
    ) -> List[str]:
        """
        Get players whose predictions are stale (betting lines changed significantly)
        
        Used for real-time updates when lines move
        
        Args:
            game_date: Game date
            stale_threshold_minutes: How old before predictions are stale
        
        Returns:
            List of player_lookups needing updated predictions
        """
        # TODO: Implement when Phase 6 is ready
        # Compare current lines vs lines used in predictions
        # Return players where line moved >1 point
        logger.info("get_players_with_stale_predictions not yet implemented")
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
    
    # Can't be in the past (more than 1 day ago)
    if game_date < today:
        logger.warning(f"Game date {game_date} is in the past")
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