"""
Completeness Checker Service

Schedule-based completeness checking for historical data windows.
Compares expected games (from nbac_schedule) vs actual games (from upstream tables)
to determine if all required historical data is present.

Used by Phase 3 Analytics and Phase 4 Precompute processors during backfill.

Related Documentation:
- /docs/architecture/historical-dependency-checking-plan.md
- /docs/implementation/11-phase3-phase4-completeness-implementation-plan.md
"""

from datetime import date, timedelta, datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class CompletenessChecker:
    """
    Schedule-based completeness checking for historical windows.

    Compares expected games (from nbac_schedule) vs actual games
    (from upstream tables) to determine data completeness.

    Example Usage:
        checker = CompletenessChecker(bq_client, 'nba-props-platform')

        results = checker.check_completeness_batch(
            entity_ids=['LAL', 'GSW', 'BOS'],
            entity_type='team',
            analysis_date=date(2024, 11, 22),
            upstream_table='nba_analytics.team_defense_game_summary',
            upstream_entity_field='defending_team_abbr',
            lookback_window=15,
            window_type='games',
            season_start_date=date(2024, 10, 22)
        )

        # results = {
        #     'LAL': {
        #         'expected_count': 17,
        #         'actual_count': 15,
        #         'completeness_pct': 88.2,
        #         'missing_count': 2,
        #         'is_complete': False,
        #         'is_production_ready': False
        #     },
        #     ...
        # }
    """

    def __init__(self, bq_client, project_id: str):
        """
        Initialize completeness checker.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID (e.g., 'nba-props-platform')
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.production_ready_threshold = 90.0  # Percentage

    def check_completeness_batch(
        self,
        entity_ids: List[str],
        entity_type: str,
        analysis_date: date,
        upstream_table: str,
        upstream_entity_field: str,
        lookback_window: int,
        window_type: str = 'games',
        season_start_date: Optional[date] = None
    ) -> Dict[str, Dict]:
        """
        Check completeness for multiple entities in single query (batch operation).

        Args:
            entity_ids: List of entity IDs to check (e.g., ['LAL', 'GSW'])
            entity_type: Type of entity ('team' or 'player')
            analysis_date: Date being processed
            upstream_table: Upstream table name (e.g., 'nba_analytics.team_defense_game_summary')
            upstream_entity_field: Entity field in upstream table (e.g., 'defending_team_abbr')
            lookback_window: Window size (number of games or days)
            window_type: 'games' or 'days'
            season_start_date: Start of season (optional, for game-count windows)

        Returns:
            Dictionary mapping entity_id to completeness metrics:
            {
                'LAL': {
                    'expected_count': 17,
                    'actual_count': 15,
                    'completeness_pct': 88.2,
                    'missing_count': 2,
                    'is_complete': False,
                    'is_production_ready': False
                },
                ...
            }
        """
        logger.info(
            f"Checking completeness for {len(entity_ids)} {entity_type}s "
            f"({window_type} window: {lookback_window})"
        )

        # Query 1: Expected games from schedule
        expected_df = self._query_expected_games(
            entity_ids, entity_type, analysis_date,
            lookback_window, window_type, season_start_date
        )

        # Query 2: Actual games from upstream table
        actual_df = self._query_actual_games(
            entity_ids, upstream_table, upstream_entity_field,
            analysis_date, lookback_window, window_type, season_start_date
        )

        # Calculate completeness per entity
        results = {}
        for entity_id in entity_ids:
            expected = self._get_count(expected_df, entity_id)
            actual = self._get_count(actual_df, entity_id)

            completeness_pct = (actual / expected * 100) if expected > 0 else 0
            is_complete = actual >= expected
            is_production_ready = completeness_pct >= self.production_ready_threshold

            results[entity_id] = {
                'expected_count': expected,
                'actual_count': actual,
                'completeness_pct': round(completeness_pct, 1),
                'missing_count': max(0, expected - actual),
                'is_complete': is_complete,
                'is_production_ready': is_production_ready
            }

            logger.debug(
                f"{entity_id}: {completeness_pct:.1f}% complete "
                f"({actual}/{expected} games)"
            )

        return results

    def _query_expected_games(
        self,
        entity_ids: List[str],
        entity_type: str,
        analysis_date: date,
        lookback_window: int,
        window_type: str,
        season_start_date: Optional[date]
    ) -> 'DataFrame':
        """
        Query schedule to get expected game count per entity.

        Returns DataFrame with columns: entity_id, count
        """
        if entity_type == 'team':
            return self._query_expected_games_team(
                entity_ids, analysis_date, lookback_window, window_type, season_start_date
            )
        elif entity_type == 'player':
            return self._query_expected_games_player(
                entity_ids, analysis_date, lookback_window, window_type, season_start_date
            )
        else:
            raise ValueError(f"Unknown entity_type: {entity_type}")

    def _query_expected_games_team(
        self,
        team_ids: List[str],
        analysis_date: date,
        lookback_window: int,
        window_type: str,
        season_start_date: Optional[date]
    ) -> 'DataFrame':
        """Query expected games for teams from schedule."""

        # Build date filter
        if window_type == 'games':
            # For game-count windows, look from season start (or beginning)
            date_filter = f"game_date <= DATE('{analysis_date}')"
            if season_start_date:
                date_filter += f" AND game_date >= DATE('{season_start_date}')"
        else:  # 'days'
            # For date-based windows, use specific date range
            start_date = analysis_date - timedelta(days=lookback_window)
            date_filter = f"game_date BETWEEN DATE('{start_date}') AND DATE('{analysis_date}')"

        # Build entity filter
        team_list = "', '".join(team_ids)
        entity_filter = f"(home_team_tricode IN ('{team_list}') OR away_team_tricode IN ('{team_list}'))"

        query = f"""
        SELECT
            CASE
                WHEN home_team_tricode IN ('{team_list}') THEN home_team_tricode
                ELSE away_team_tricode
            END as entity_id,
            COUNT(DISTINCT game_date) as count
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE {date_filter}
          AND {entity_filter}
          AND game_status = 3  -- Final games only
        GROUP BY entity_id
        """

        logger.debug(f"Expected games query:\n{query}")
        return self.bq_client.query(query).to_dataframe()

    def _query_expected_games_player(
        self,
        player_lookups: List[str],
        analysis_date: date,
        lookback_window: int,
        window_type: str,
        season_start_date: Optional[date]
    ) -> 'DataFrame':
        """
        Query expected games for players from schedule.

        Approach:
        1. Find each player's current/most recent team from player_game_summary
        2. Query that team's schedule for the lookback window
        3. Use the team's game count as the player's expected count

        Assumptions:
        - Active players play in most of their team's games
        - Most recent team = current team (handles trades)
        - Conservative estimate (may over-expect for injured players)

        Note: This won't perfectly handle injuries/DNPs, but will effectively
        detect missing data for the majority case (active, healthy players).
        """
        from google.cloud import bigquery

        if window_type == 'games':
            # Get last N games from each player's current team
            query = f"""
            WITH player_current_team AS (
                -- Find each player's most recent team
                SELECT
                    player_lookup,
                    team_abbr,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_lookup
                        ORDER BY game_date DESC
                    ) as recency
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE player_lookup IN UNNEST(@players)
                    AND game_date < @analysis_date
            ),
            active_players AS (
                -- Get only the most recent team per player
                SELECT player_lookup, team_abbr
                FROM player_current_team
                WHERE recency = 1
            ),
            team_games_ranked AS (
                -- Get and rank all games for teams our players are on
                SELECT
                    team_abbr,
                    game_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY team_abbr
                        ORDER BY game_date DESC
                    ) as game_num
                FROM (
                    -- Home games
                    SELECT DISTINCT
                        home_team_tricode as team_abbr,
                        game_date
                    FROM `{self.project_id}.nba_raw.nbac_schedule`
                    WHERE game_date < @analysis_date
                        AND game_status = 3  -- Final games only
                        AND home_team_tricode IN (
                            SELECT DISTINCT team_abbr FROM active_players
                        )

                    UNION ALL

                    -- Away games
                    SELECT DISTINCT
                        away_team_tricode as team_abbr,
                        game_date
                    FROM `{self.project_id}.nba_raw.nbac_schedule`
                    WHERE game_date < @analysis_date
                        AND game_status = 3  -- Final games only
                        AND away_team_tricode IN (
                            SELECT DISTINCT team_abbr FROM active_players
                        )
                )
            ),
            team_expected_counts AS (
                -- Count games within the window for each team
                SELECT
                    team_abbr,
                    COUNT(*) as expected_count
                FROM team_games_ranked
                WHERE game_num <= @lookback_window
                GROUP BY team_abbr
            )
            -- Join back to players
            SELECT
                p.player_lookup as entity_id,
                COALESCE(t.expected_count, 0) as count
            FROM active_players p
            LEFT JOIN team_expected_counts t ON p.team_abbr = t.team_abbr
            """

        else:  # window_type == 'days'
            # Get games in last N days from each player's current team
            query = f"""
            WITH player_current_team AS (
                -- Find each player's most recent team
                SELECT
                    player_lookup,
                    team_abbr,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_lookup
                        ORDER BY game_date DESC
                    ) as recency
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE player_lookup IN UNNEST(@players)
                    AND game_date < @analysis_date
            ),
            active_players AS (
                -- Get only the most recent team per player
                SELECT player_lookup, team_abbr
                FROM player_current_team
                WHERE recency = 1
            ),
            team_scheduled_games AS (
                -- Get games in the date window for teams our players are on
                SELECT DISTINCT
                    team_abbr,
                    game_date
                FROM (
                    -- Home games
                    SELECT
                        home_team_tricode as team_abbr,
                        game_date
                    FROM `{self.project_id}.nba_raw.nbac_schedule`
                    WHERE game_date < @analysis_date
                        AND game_date >= DATE_SUB(@analysis_date, INTERVAL @lookback_window DAY)
                        AND game_status = 3  -- Final games only
                        AND home_team_tricode IN (
                            SELECT DISTINCT team_abbr FROM active_players
                        )

                    UNION ALL

                    -- Away games
                    SELECT
                        away_team_tricode as team_abbr,
                        game_date
                    FROM `{self.project_id}.nba_raw.nbac_schedule`
                    WHERE game_date < @analysis_date
                        AND game_date >= DATE_SUB(@analysis_date, INTERVAL @lookback_window DAY)
                        AND game_status = 3  -- Final games only
                        AND away_team_tricode IN (
                            SELECT DISTINCT team_abbr FROM active_players
                        )
                )
            ),
            team_expected_counts AS (
                -- Count games in the window for each team
                SELECT
                    team_abbr,
                    COUNT(*) as expected_count
                FROM team_scheduled_games
                GROUP BY team_abbr
            )
            -- Join back to players
            SELECT
                p.player_lookup as entity_id,
                COALESCE(t.expected_count, 0) as count
            FROM active_players p
            LEFT JOIN team_expected_counts t ON p.team_abbr = t.team_abbr
            """

        # Execute query with parameters
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("players", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
                bigquery.ScalarQueryParameter("lookback_window", "INT64", lookback_window)
            ]
        )

        logger.debug(f"Expected games query (player-based):\n{query}")
        df = self.bq_client.query(query, job_config=job_config).to_dataframe()

        # Log summary for debugging
        if not df.empty:
            logger.info(
                f"Player schedule check: {len(df)} players with teams, "
                f"avg expected: {df['count'].mean():.1f} games"
            )
        else:
            logger.warning(f"No team found for any of {len(player_lookups)} players")

        return df

    def _query_actual_games(
        self,
        entity_ids: List[str],
        upstream_table: str,
        upstream_entity_field: str,
        analysis_date: date,
        lookback_window: int,
        window_type: str,
        season_start_date: Optional[date]
    ) -> 'DataFrame':
        """
        Query upstream table to get actual game count per entity.

        Returns DataFrame with columns: entity_id, count
        """
        # Build date filter (same logic as expected games)
        if window_type == 'games':
            date_filter = f"game_date <= DATE('{analysis_date}')"
            if season_start_date:
                date_filter += f" AND game_date >= DATE('{season_start_date}')"
        else:  # 'days'
            start_date = analysis_date - timedelta(days=lookback_window)
            date_filter = f"game_date BETWEEN DATE('{start_date}') AND DATE('{analysis_date}')"

        # Build entity filter
        entity_list = "', '".join(entity_ids)
        entity_filter = f"{upstream_entity_field} IN ('{entity_list}')"

        query = f"""
        SELECT
            {upstream_entity_field} as entity_id,
            COUNT(DISTINCT game_date) as count
        FROM `{self.project_id}.{upstream_table}`
        WHERE {date_filter}
          AND {entity_filter}
        GROUP BY entity_id
        """

        logger.debug(f"Actual games query:\n{query}")
        return self.bq_client.query(query).to_dataframe()

    def _get_count(self, df: 'DataFrame', entity_id: str) -> int:
        """Extract count for entity from DataFrame."""
        if df is None or df.empty:
            return 0

        entity_rows = df[df['entity_id'] == entity_id]
        if entity_rows.empty:
            return 0

        return int(entity_rows['count'].iloc[0])

    def is_bootstrap_mode(
        self,
        analysis_date: date,
        season_start_date: date,
        bootstrap_days: int = 30
    ) -> bool:
        """
        Check if date is in bootstrap mode (early in season/backfill).

        During bootstrap, we allow partial data and mark for reprocessing.

        Args:
            analysis_date: Date being processed
            season_start_date: Start of season
            bootstrap_days: Number of days for bootstrap mode (default: 30)

        Returns:
            True if in bootstrap mode, False otherwise
        """
        days_since_start = (analysis_date - season_start_date).days
        return days_since_start < bootstrap_days

    def is_season_boundary(
        self,
        analysis_date: date
    ) -> bool:
        """
        Check if date is near season start/end to prevent false alerts.

        NBA season typically:
        - Starts: October 15 - November 1
        - Ends: April 15 - April 30

        Args:
            analysis_date: Date to check

        Returns:
            True if near season boundary, False otherwise
        """
        month = analysis_date.month
        day = analysis_date.day

        # Early season (October-November)
        if month in [10, 11]:
            return True

        # Late season (April)
        if month == 4:
            return True

        return False

    def calculate_backfill_progress(
        self,
        analysis_date: date,
        season_start_date: date,
        avg_completeness: float
    ) -> Dict:
        """
        Check if backfill is on track based on concrete thresholds.

        Expected Progress:
        - Day 10: 30% completeness
        - Day 20: 80% completeness
        - Day 30: 95% completeness

        Args:
            analysis_date: Current date being processed
            season_start_date: Start of season
            avg_completeness: Average completeness across all entities

        Returns:
            Dictionary with progress assessment:
            {
                'days_since_start': 25,
                'avg_completeness': 85.0,
                'expected_threshold': 80.0,
                'alert_level': 'ok',  # 'ok', 'info', 'warning', 'critical'
                'message': 'Day 25: 85.0% complete (expected 80%)'
            }
        """
        days_since_start = (analysis_date - season_start_date).days

        # Determine expected threshold based on days elapsed
        if days_since_start >= 30:
            expected_threshold = 95.0
            alert_level = 'critical' if avg_completeness < expected_threshold else 'ok'
        elif days_since_start >= 20:
            expected_threshold = 80.0
            alert_level = 'warning' if avg_completeness < expected_threshold else 'ok'
        elif days_since_start >= 10:
            expected_threshold = 30.0
            alert_level = 'info' if avg_completeness < expected_threshold else 'ok'
        else:
            expected_threshold = 0.0
            alert_level = 'ok'  # Too early to alert

        return {
            'days_since_start': days_since_start,
            'avg_completeness': avg_completeness,
            'expected_threshold': expected_threshold,
            'alert_level': alert_level,
            'message': (
                f"Day {days_since_start}: {avg_completeness:.1f}% complete "
                f"(expected {expected_threshold:.0f}%)"
            )
        }
