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

from shared.utils.player_name_normalizer import normalize_name_for_lookup

logger = logging.getLogger(__name__)


class DependencyError(Exception):
    """
    Raised when dependency checks fail in strict mode.

    This exception is raised by the CompletenessChecker when:
    - Required upstream data is missing
    - Data completeness is below required thresholds
    - Upstream processors have failed

    Attributes:
        message (str): Description of the dependency failure
        details (dict): Additional context about what failed
    """

    def __init__(self, message: str, details: Optional[Dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self):
        return f"DependencyError: {self.message}"


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
        # Lowered from 90 to 70 to account for BDL API data gaps
        # BDL API missing some west coast late games (see BOXSCORE-GAPS-AND-CIRCUIT-BREAKERS.md)
        self.production_ready_threshold = 70.0  # Percentage

    def check_completeness_batch(
        self,
        entity_ids: List[str],
        entity_type: str,
        analysis_date: date,
        upstream_table: str,
        upstream_entity_field: str,
        lookback_window: int,
        window_type: str = 'games',
        season_start_date: Optional[date] = None,
        fail_on_incomplete: bool = False,
        completeness_threshold: float = 90.0
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
            fail_on_incomplete: If True, raise DependencyError when completeness below threshold
            completeness_threshold: Minimum completeness % required (default: 90.0)

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

        Raises:
            DependencyError: If fail_on_incomplete=True and any entity below threshold
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

        # Strict mode: Fail if any entity below threshold
        if fail_on_incomplete:
            incomplete_entities = [
                entity_id for entity_id, metrics in results.items()
                if metrics['completeness_pct'] < completeness_threshold
            ]

            if incomplete_entities:
                # Calculate summary stats for error message
                avg_completeness = sum(r['completeness_pct'] for r in results.values()) / len(results)
                total_missing = sum(r['missing_count'] for r in results.values())

                error_details = {
                    'upstream_table': upstream_table,
                    'analysis_date': str(analysis_date),
                    'threshold': completeness_threshold,
                    'incomplete_entities': incomplete_entities,
                    'avg_completeness': round(avg_completeness, 1),
                    'total_missing_games': total_missing,
                    'results': {k: results[k] for k in incomplete_entities}
                }

                raise DependencyError(
                    f"Incomplete data: {len(incomplete_entities)}/{len(results)} entities "
                    f"below {completeness_threshold}% threshold (avg: {avg_completeness:.1f}%)",
                    details=error_details
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

    def check_date_range_completeness(
        self,
        table: str,
        date_column: str,
        start_date: date,
        end_date: date
    ) -> Dict:
        """
        Check for gaps in a continuous date range.

        This method detects missing dates between start_date and end_date
        in a given table. Useful for verifying backfill completeness.

        Args:
            table: Fully qualified table name (e.g., 'nba_analytics.player_game_summary')
            date_column: Column name containing dates
            start_date: Start of range to check
            end_date: End of range to check

        Returns:
            Dictionary with gap analysis:
            {
                'has_gaps': bool,
                'missing_dates': List[date],
                'gap_count': int,
                'coverage_pct': float,
                'date_range': (start_date, end_date),
                'is_continuous': bool
            }

        Example:
            >>> checker.check_date_range_completeness(
            ...     table='nba_analytics.player_game_summary',
            ...     date_column='game_date',
            ...     start_date=date(2023, 10, 1),
            ...     end_date=date(2023, 10, 31)
            ... )
            {
                'has_gaps': True,
                'missing_dates': [date(2023, 10, 5), date(2023, 10, 11)],
                'gap_count': 2,
                'coverage_pct': 93.5,
                'is_continuous': False
            }
        """
        from google.cloud import bigquery

        query = f"""
        WITH expected_dates AS (
            SELECT date
            FROM UNNEST(GENERATE_DATE_ARRAY(@start_date, @end_date, INTERVAL 1 DAY)) as date
        ),
        actual_dates AS (
            SELECT DISTINCT DATE({date_column}) as date
            FROM `{self.project_id}.{table}`
            WHERE DATE({date_column}) >= @start_date
              AND DATE({date_column}) <= @end_date
        )
        SELECT e.date as missing_date
        FROM expected_dates e
        LEFT JOIN actual_dates a ON e.date = a.date
        WHERE a.date IS NULL
        ORDER BY e.date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )

        # Wait for completion with timeout to prevent indefinite hangs
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
        missing_dates = [row.missing_date for row in result]

        expected_days = (end_date - start_date).days + 1
        actual_days = expected_days - len(missing_dates)
        coverage_pct = (actual_days / expected_days) * 100 if expected_days > 0 else 0

        logger.info(
            f"Gap check: {table} ({start_date} to {end_date}) - "
            f"{coverage_pct:.1f}% coverage ({len(missing_dates)} gaps)"
        )

        return {
            'has_gaps': len(missing_dates) > 0,
            'missing_dates': missing_dates,
            'gap_count': len(missing_dates),
            'coverage_pct': round(coverage_pct, 1),
            'date_range': (start_date, end_date),
            'is_continuous': len(missing_dates) == 0
        }

    def check_upstream_processor_status(
        self,
        processor_name: str,
        data_date: date
    ) -> Dict:
        """
        Check if upstream processor succeeded for a given date.

        Queries processor_run_history to check for failures. This prevents
        processing with incomplete upstream data.

        Args:
            processor_name: Name of upstream processor (e.g., 'PlayerBoxscoreProcessor')
            data_date: Date to check

        Returns:
            Dictionary with processor status:
            {
                'processor_succeeded': bool,
                'status': str,  # 'success', 'failed', 'not_found'
                'safe_to_process': bool,
                'error_message': Optional[str],
                'run_id': Optional[str]
            }

        Example:
            >>> checker.check_upstream_processor_status(
            ...     processor_name='PlayerBoxscoreProcessor',
            ...     data_date=date(2023, 10, 15)
            ... )
            {
                'processor_succeeded': False,
                'status': 'failed',
                'safe_to_process': False,
                'error_message': 'BigQuery timeout',
                'run_id': 'abc123'
            }
        """
        from google.cloud import bigquery
        import json

        query = """
        SELECT
            status,
            run_id,
            started_at,
            errors,
            skipped,
            skip_reason
        FROM `{project}.nba_reference.processor_run_history`
        WHERE processor_name = @processor_name
          AND data_date = @data_date
        ORDER BY started_at DESC
        LIMIT 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("processor_name", "STRING", processor_name),
                bigquery.ScalarQueryParameter("data_date", "DATE", data_date),
            ]
        )

        # Wait for completion with timeout to prevent indefinite hangs
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
        row = next(iter(result), None)

        if not row:
            logger.warning(
                f"No run found for {processor_name} on {data_date}"
            )
            return {
                'processor_succeeded': False,
                'status': 'not_found',
                'safe_to_process': False,
                'error_message': f'No run found for {processor_name} on {data_date}',
                'run_id': None
            }

        succeeded = row.status == 'success'

        # Extract error message if failed
        error_message = None
        if row.errors:
            try:
                errors = json.loads(row.errors) if isinstance(row.errors, str) else row.errors
                if isinstance(errors, list) and len(errors) > 0:
                    error_message = errors[0].get('message') if isinstance(errors[0], dict) else str(errors[0])
                else:
                    error_message = str(errors)
            except (json.JSONDecodeError, TypeError, AttributeError, KeyError) as e:
                logger.debug(f"Could not parse error JSON: {e}")
                error_message = str(row.errors)

        status_msg = "✅ succeeded" if succeeded else f"❌ {row.status}"
        logger.info(
            f"Upstream check: {processor_name} on {data_date} - {status_msg}"
        )

        return {
            'processor_succeeded': succeeded,
            'status': row.status,
            'safe_to_process': succeeded,
            'error_message': error_message,
            'run_id': row.run_id
        }

    def check_daily_completeness_fast(
        self,
        entity_ids: List[str],
        entity_type: str,
        target_date: date,
        upstream_table: str,
        upstream_entity_field: str,
        date_field: str = 'game_date'
    ) -> Dict[str, Dict]:
        """
        FAST daily completeness check - optimized for daily orchestration.

        This method is much faster than check_completeness_batch() because:
        - No complex CTEs or window functions
        - Simple single-date check: "Does player have data on target_date?"
        - One efficient query instead of full 10-game history analysis

        Use this for daily orchestration. Use check_completeness_batch() for
        production quality gates that need full history analysis.

        Performance: ~1-2 seconds vs 600+ seconds for check_completeness_batch()

        Args:
            entity_ids: List of entity IDs (player_lookup or team_abbr)
            entity_type: 'player' or 'team'
            target_date: The specific date to check (e.g., yesterday's games)
            upstream_table: Table to check (e.g., 'nba_analytics.player_game_summary')
            upstream_entity_field: Field containing entity ID
            date_field: Date column name (default: 'game_date')

        Returns:
            Dict mapping entity_id to completeness info:
            {
                'entity_id': {
                    'has_data': bool,      # True if data exists for target_date
                    'is_production_ready': bool,  # Alias for has_data
                    'target_date': date
                }
            }

        Example:
            >>> checker.check_daily_completeness_fast(
            ...     entity_ids=['lebron_james', 'stephen_curry'],
            ...     entity_type='player',
            ...     target_date=date(2024, 11, 22),
            ...     upstream_table='nba_analytics.player_game_summary',
            ...     upstream_entity_field='player_lookup'
            ... )
            {
                'lebron_james': {'has_data': True, 'is_production_ready': True},
                'stephen_curry': {'has_data': True, 'is_production_ready': True}
            }
        """
        from google.cloud import bigquery

        if not entity_ids:
            return {}

        # Simple, fast query: just check which entities have data on target_date
        query = f"""
        SELECT DISTINCT {upstream_entity_field} as entity_id
        FROM `{self.project_id}.{upstream_table}`
        WHERE {upstream_entity_field} IN UNNEST(@entity_ids)
          AND DATE({date_field}) = @target_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("entity_ids", "STRING", entity_ids),
                bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            ]
        )

        logger.debug(f"Fast daily completeness query for {len(entity_ids)} entities on {target_date}")
        # Wait for completion with timeout to prevent indefinite hangs
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)

        # Build set of entities that have data
        entities_with_data = {row.entity_id for row in result}

        # Build results dict
        results = {}
        for entity_id in entity_ids:
            has_data = entity_id in entities_with_data
            results[entity_id] = {
                'has_data': has_data,
                'is_production_ready': has_data,
                'target_date': target_date,
                'completeness_pct': 100.0 if has_data else 0.0
            }

        found_count = len(entities_with_data)
        logger.info(
            f"Fast daily check: {found_count}/{len(entity_ids)} entities "
            f"have data on {target_date}"
        )

        return results

    def check_raw_boxscore_for_player(
        self,
        player_lookup: str,
        game_date: date
    ) -> bool:
        """
        Check if a player appears in raw box score data for a given date.

        This determines if the player actually played (and we're missing data)
        vs the player didn't play (DNP - expected).

        Used by classify_failure() to distinguish between:
        - DATA_GAP: Player in raw data but missing from analytics (correctable)
        - PLAYER_DNP: Player not in raw data (expected, not correctable)

        Args:
            player_lookup: Player lookup key (e.g., 'lebron_james' or 'lebronjames')
                          Auto-normalized to BDL format (no underscores)
            game_date: Date to check

        Returns:
            True if player appears in raw box score for that date, False otherwise
        """
        from google.cloud import bigquery

        # Normalize player_lookup to BDL format (removes underscores, spaces, etc.)
        normalized_lookup = normalize_name_for_lookup(player_lookup)

        # Use bdl_player_boxscores which has player_lookup directly
        query = f"""
        SELECT COUNT(*) > 0 as player_in_game
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date = @game_date
          AND player_lookup = @player_lookup
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", normalized_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            # Wait for completion with timeout to prevent indefinite hangs
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
            row = next(iter(result), None)
            return row.player_in_game if row else False
        except Exception as e:
            logger.warning(f"Error checking raw boxscore for {player_lookup} on {game_date}: {e}")
            return False

    def check_raw_boxscore_batch(
        self,
        player_lookups: List[str],
        game_dates: List[date]
    ) -> Dict[str, List[date]]:
        """
        Batch check which players appear in raw box scores for given dates.

        More efficient than calling check_raw_boxscore_for_player() multiple times.

        Args:
            player_lookups: List of player lookup keys (any format, will be normalized)
            game_dates: List of dates to check

        Returns:
            Dict mapping player_lookup (normalized) to list of dates they appear in raw data
            e.g., {'lebronjames': [date(2021,12,25), date(2021,12,28)]}
        """
        from google.cloud import bigquery

        if not player_lookups or not game_dates:
            return {}

        # Normalize all player lookups to BDL format
        normalized_lookups = [normalize_name_for_lookup(p) for p in player_lookups]
        # Create mapping from normalized back to original
        norm_to_original = {normalize_name_for_lookup(p): p for p in player_lookups}

        # Use bdl_player_boxscores which has player_lookup directly
        query = f"""
        SELECT
          player_lookup,
          game_date
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE player_lookup IN UNNEST(@player_lookups)
          AND game_date IN UNNEST(@game_dates)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", normalized_lookups),
                bigquery.ArrayQueryParameter("game_dates", "DATE", game_dates),
            ]
        )

        try:
            # Wait for completion with timeout to prevent indefinite hangs
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)

            # Return results keyed by normalized lookup (what BDL uses)
            player_dates: Dict[str, List[date]] = {p: [] for p in normalized_lookups}
            for row in result:
                if row.player_lookup in player_dates:
                    player_dates[row.player_lookup].append(row.game_date)

            return player_dates
        except Exception as e:
            logger.warning(f"Error in batch raw boxscore check: {e}")
            return {}

    def classify_failure(
        self,
        player_lookup: str,
        analysis_date: date,
        expected_games: List[date],
        actual_games: List[date],
        check_raw_data: bool = True
    ) -> dict:
        """
        Classify a completeness failure as DNP vs Data Gap.

        This is the core function for enhanced failure tracking. It determines
        WHY a player has missing data:

        - PLAYER_DNP: Player didn't play in the game (expected, not correctable)
        - DATA_GAP: Player played but data is missing (unexpected, correctable)
        - MIXED: Some DNP, some data gaps
        - INSUFFICIENT_HISTORY: Not enough season history yet (early season)
        - UNKNOWN: Could not determine

        Args:
            player_lookup: Player lookup key
            analysis_date: Date being analyzed
            expected_games: List of game dates player's team had scheduled
            actual_games: List of game dates player has data for
            check_raw_data: If True, query raw box scores to verify DNP vs gap

        Returns:
            {
                'failure_type': 'PLAYER_DNP' | 'DATA_GAP' | 'MIXED' | 'INSUFFICIENT_HISTORY' | 'UNKNOWN',
                'is_correctable': bool | None,
                'expected_count': int,
                'actual_count': int,
                'missing_dates': List[date],
                'dnp_dates': List[date],
                'data_gap_dates': List[date],
                'raw_data_checked': bool
            }

        Example:
            >>> checker.classify_failure(
            ...     player_lookup='zach_lavine',
            ...     analysis_date=date(2021, 12, 31),
            ...     expected_games=[date(2021,12,25), date(2021,12,28), date(2021,12,31)],
            ...     actual_games=[date(2021,12,25)],
            ... )
            {
                'failure_type': 'PLAYER_DNP',
                'is_correctable': False,
                'expected_count': 3,
                'actual_count': 1,
                'missing_dates': [date(2021,12,28), date(2021,12,31)],
                'dnp_dates': [date(2021,12,28), date(2021,12,31)],
                'data_gap_dates': [],
                'raw_data_checked': True
            }
        """
        expected_set = set(expected_games) if expected_games else set()
        actual_set = set(actual_games) if actual_games else set()
        missing_dates = sorted(expected_set - actual_set)

        # Base result
        result = {
            'failure_type': 'UNKNOWN',
            'is_correctable': None,
            'expected_count': len(expected_set),
            'actual_count': len(actual_set),
            'missing_dates': missing_dates,
            'dnp_dates': [],
            'data_gap_dates': [],
            'raw_data_checked': False
        }

        # No missing dates = not actually a failure
        if not missing_dates:
            result['failure_type'] = 'COMPLETE'
            result['is_correctable'] = False
            return result

        # Check if this is early season (insufficient history expected)
        if len(expected_set) < 5:
            result['failure_type'] = 'INSUFFICIENT_HISTORY'
            result['is_correctable'] = False
            return result

        # If not checking raw data, return with what we have
        if not check_raw_data:
            # Assume DNP for early season dates (conservative)
            result['failure_type'] = 'UNKNOWN'
            return result

        # Check raw box scores to determine DNP vs Data Gap
        result['raw_data_checked'] = True

        dnp_dates = []
        data_gap_dates = []

        for missing_date in missing_dates:
            raw_exists = self.check_raw_boxscore_for_player(player_lookup, missing_date)
            if raw_exists:
                # Player was in the game but analytics data missing = DATA_GAP
                data_gap_dates.append(missing_date)
            else:
                # No raw data = Player didn't play = DNP
                dnp_dates.append(missing_date)

        result['dnp_dates'] = dnp_dates
        result['data_gap_dates'] = data_gap_dates

        # Classify overall failure
        if data_gap_dates and not dnp_dates:
            result['failure_type'] = 'DATA_GAP'
            result['is_correctable'] = True
        elif dnp_dates and not data_gap_dates:
            result['failure_type'] = 'PLAYER_DNP'
            result['is_correctable'] = False
        elif data_gap_dates and dnp_dates:
            result['failure_type'] = 'MIXED'
            result['is_correctable'] = True  # Some can be fixed
        else:
            result['failure_type'] = 'UNKNOWN'

        logger.debug(
            f"Classified failure for {player_lookup}: {result['failure_type']} "
            f"(DNP: {len(dnp_dates)}, gaps: {len(data_gap_dates)})"
        )

        return result

    def classify_failures_batch(
        self,
        player_failures: Dict[str, dict],
        check_raw_data: bool = True
    ) -> Dict[str, dict]:
        """
        Batch classify multiple player failures efficiently.

        More efficient than calling classify_failure() for each player because
        it batches the raw box score queries.

        Args:
            player_failures: Dict mapping player_lookup to failure info:
                {
                    'lebron_james': {
                        'analysis_date': date(2021, 12, 31),
                        'expected_games': [date(...), ...],
                        'actual_games': [date(...), ...]
                    },
                    ...
                }
            check_raw_data: If True, query raw box scores

        Returns:
            Dict mapping player_lookup to classification result
        """
        results = {}

        # First pass: identify all players/dates that need raw data checks
        all_missing_dates = set()
        players_with_missing = []

        for player_lookup, failure_info in player_failures.items():
            expected = set(failure_info.get('expected_games', []))
            actual = set(failure_info.get('actual_games', []))
            missing = expected - actual

            if missing:
                players_with_missing.append(player_lookup)
                all_missing_dates.update(missing)

        # Batch query raw data if needed
        raw_data_lookup = {}
        if check_raw_data and players_with_missing and all_missing_dates:
            raw_data_lookup = self.check_raw_boxscore_batch(
                players_with_missing,
                list(all_missing_dates)
            )

        # Second pass: classify each failure
        for player_lookup, failure_info in player_failures.items():
            expected = failure_info.get('expected_games', [])
            actual = failure_info.get('actual_games', [])
            expected_set = set(expected)
            actual_set = set(actual)
            missing_dates = sorted(expected_set - actual_set)

            result = {
                'failure_type': 'UNKNOWN',
                'is_correctable': None,
                'expected_count': len(expected_set),
                'actual_count': len(actual_set),
                'missing_dates': missing_dates,
                'dnp_dates': [],
                'data_gap_dates': [],
                'raw_data_checked': check_raw_data
            }

            if not missing_dates:
                result['failure_type'] = 'COMPLETE'
                result['is_correctable'] = False
            elif len(expected_set) < 5:
                result['failure_type'] = 'INSUFFICIENT_HISTORY'
                result['is_correctable'] = False
            elif check_raw_data:
                # Use batch results to classify (lookup by normalized name)
                normalized_lookup = normalize_name_for_lookup(player_lookup)
                player_raw_dates = set(raw_data_lookup.get(normalized_lookup, []))

                dnp_dates = []
                data_gap_dates = []

                for missing_date in missing_dates:
                    if missing_date in player_raw_dates:
                        data_gap_dates.append(missing_date)
                    else:
                        dnp_dates.append(missing_date)

                result['dnp_dates'] = dnp_dates
                result['data_gap_dates'] = data_gap_dates

                if data_gap_dates and not dnp_dates:
                    result['failure_type'] = 'DATA_GAP'
                    result['is_correctable'] = True
                elif dnp_dates and not data_gap_dates:
                    result['failure_type'] = 'PLAYER_DNP'
                    result['is_correctable'] = False
                elif data_gap_dates and dnp_dates:
                    result['failure_type'] = 'MIXED'
                    result['is_correctable'] = True

            results[player_lookup] = result

        logger.info(
            f"Batch classified {len(results)} failures: "
            f"DNP={sum(1 for r in results.values() if r['failure_type'] == 'PLAYER_DNP')}, "
            f"GAP={sum(1 for r in results.values() if r['failure_type'] == 'DATA_GAP')}, "
            f"MIXED={sum(1 for r in results.values() if r['failure_type'] == 'MIXED')}"
        )

        return results

    def get_player_game_dates(
        self,
        player_lookup: str,
        analysis_date: date,
        lookback_days: int = 14
    ) -> dict:
        """
        Get expected and actual game dates for a player in the lookback window.

        This is the key method for enriching INCOMPLETE_DATA failures with
        DNP vs DATA_GAP classification. It queries:
        - actual_games: Dates player appears in raw box scores
        - expected_games: Dates player's team had scheduled games (from schedule)

        The difference allows classify_failure() to determine if missing data
        is due to DNP (player didn't play) or a data gap (player played but missing).

        Args:
            player_lookup: Player lookup key (any format, auto-normalized)
            analysis_date: Date being analyzed (end of lookback window)
            lookback_days: Days to look back from analysis_date (default 14)

        Returns:
            {
                'player_lookup': str,           # Normalized format
                'team_abbr': str or None,       # Player's current team
                'actual_games': List[date],     # Dates player in raw box scores
                'expected_games': List[date],   # Dates team had scheduled games
                'lookback_start': date,
                'lookback_end': date,
                'error': str or None            # Error message if query failed
            }

        Example:
            >>> checker.get_player_game_dates('zach_lavine', date(2021, 12, 31), 14)
            {
                'player_lookup': 'zachlavine',
                'team_abbr': 'CHI',
                'actual_games': [date(2021,12,20), date(2021,12,22), date(2021,12,25)],
                'expected_games': [date(2021,12,20), date(2021,12,22), date(2021,12,25),
                                   date(2021,12,28), date(2021,12,31)],
                'lookback_start': date(2021,12,17),
                'lookback_end': date(2021,12,31),
                'error': None
            }
        """
        from google.cloud import bigquery

        normalized_lookup = normalize_name_for_lookup(player_lookup)
        lookback_start = analysis_date - timedelta(days=lookback_days)

        result = {
            'player_lookup': normalized_lookup,
            'team_abbr': None,
            'actual_games': [],
            'expected_games': [],
            'lookback_start': lookback_start,
            'lookback_end': analysis_date,
            'error': None
        }

        try:
            # Step 1: Get player's games AND team from raw box scores in one query
            actual_query = f"""
            SELECT DISTINCT
                game_date,
                team_abbr
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE player_lookup = @player_lookup
              AND game_date >= @lookback_start
              AND game_date <= @analysis_date
            ORDER BY game_date
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("player_lookup", "STRING", normalized_lookup),
                    bigquery.ScalarQueryParameter("lookback_start", "DATE", lookback_start),
                    bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
                ]
            )

            # Wait for completion with timeout to prevent indefinite hangs
            actual_result = self.bq_client.query(actual_query, job_config=job_config).result(timeout=60)

            actual_games = []
            team_abbr = None
            for row in actual_result:
                actual_games.append(row.game_date)
                team_abbr = row.team_abbr  # Last team the player was on

            result['actual_games'] = actual_games
            result['team_abbr'] = team_abbr

            # Step 2: If we have a team, get expected games from schedule
            # Note: nbac_schedule is partitioned on game_date column
            if team_abbr:
                expected_query = f"""
                SELECT DISTINCT game_date
                FROM `{self.project_id}.nba_raw.nbac_schedule`
                WHERE (home_team_tricode = @team_abbr OR away_team_tricode = @team_abbr)
                  AND game_date >= @lookback_start
                  AND game_date <= @analysis_date
                  AND game_status_text = 'Final'
                ORDER BY game_date
                """

                expected_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                        bigquery.ScalarQueryParameter("lookback_start", "DATE", lookback_start),
                        bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
                    ]
                )

                # Wait for completion with timeout to prevent indefinite hangs
                expected_result = self.bq_client.query(expected_query, job_config=expected_config).result(timeout=60)
                result['expected_games'] = [row.game_date for row in expected_result]

            logger.debug(
                f"get_player_game_dates({normalized_lookup}, {analysis_date}): "
                f"team={team_abbr}, actual={len(actual_games)}, "
                f"expected={len(result['expected_games'])}"
            )

        except Exception as e:
            logger.warning(f"Error getting game dates for {player_lookup}: {e}")
            result['error'] = str(e)

        return result

    def get_player_game_dates_batch(
        self,
        player_lookups: List[str],
        analysis_date: date,
        lookback_days: int = 14
    ) -> Dict[str, dict]:
        """
        Batch get expected and actual game dates for multiple players.

        More efficient than calling get_player_game_dates() for each player.
        Uses two queries (one for actuals, one for expected) instead of 2N.

        Args:
            player_lookups: List of player lookup keys
            analysis_date: Date being analyzed
            lookback_days: Days to look back

        Returns:
            Dict mapping player_lookup (normalized) to game dates info
        """
        from google.cloud import bigquery

        if not player_lookups:
            return {}

        normalized_lookups = [normalize_name_for_lookup(p) for p in player_lookups]
        lookback_start = analysis_date - timedelta(days=lookback_days)

        # Initialize results
        results = {
            p: {
                'player_lookup': p,
                'team_abbr': None,
                'actual_games': [],
                'expected_games': [],
                'lookback_start': lookback_start,
                'lookback_end': analysis_date,
                'error': None
            }
            for p in normalized_lookups
        }

        try:
            # Step 1: Batch query for all players' actual games and teams
            actual_query = f"""
            SELECT
                player_lookup,
                game_date,
                team_abbr
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date >= @lookback_start
              AND game_date <= @analysis_date
            ORDER BY player_lookup, game_date
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("player_lookups", "STRING", normalized_lookups),
                    bigquery.ScalarQueryParameter("lookback_start", "DATE", lookback_start),
                    bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
                ]
            )

            # Wait for completion with timeout to prevent indefinite hangs
            actual_result = self.bq_client.query(actual_query, job_config=job_config).result(timeout=60)

            # Collect teams for each player
            player_teams = {}
            for row in actual_result:
                player = row.player_lookup
                if player in results:
                    results[player]['actual_games'].append(row.game_date)
                    player_teams[player] = row.team_abbr  # Last team

            # Update team_abbr in results
            for player, team in player_teams.items():
                results[player]['team_abbr'] = team

            # Step 2: Get unique teams and their scheduled games
            # Note: nbac_schedule is partitioned on game_date column
            unique_teams = list(set(player_teams.values()))
            if unique_teams:
                expected_query = f"""
                SELECT
                    home_team_tricode as team_abbr,
                    game_date,
                    'home' as venue
                FROM `{self.project_id}.nba_raw.nbac_schedule`
                WHERE home_team_tricode IN UNNEST(@teams)
                  AND game_date >= @lookback_start
                  AND game_date <= @analysis_date
                  AND game_status_text = 'Final'
                UNION ALL
                SELECT
                    away_team_tricode as team_abbr,
                    game_date,
                    'away' as venue
                FROM `{self.project_id}.nba_raw.nbac_schedule`
                WHERE away_team_tricode IN UNNEST(@teams)
                  AND game_date >= @lookback_start
                  AND game_date <= @analysis_date
                  AND game_status_text = 'Final'
                """

                expected_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ArrayQueryParameter("teams", "STRING", unique_teams),
                        bigquery.ScalarQueryParameter("lookback_start", "DATE", lookback_start),
                        bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
                    ]
                )

                # Wait for completion with timeout to prevent indefinite hangs
                expected_result = self.bq_client.query(expected_query, job_config=expected_config).result(timeout=60)

                # Build team -> game dates mapping
                team_games = {t: set() for t in unique_teams}
                for row in expected_result:
                    if row.team_abbr in team_games:
                        team_games[row.team_abbr].add(row.game_date)

                # Assign expected games to each player based on their team
                for player, team in player_teams.items():
                    if team in team_games:
                        results[player]['expected_games'] = sorted(team_games[team])

            logger.info(
                f"Batch get_player_game_dates: {len(player_lookups)} players, "
                f"{len(unique_teams)} teams"
            )

        except Exception as e:
            logger.warning(f"Error in batch get_player_game_dates: {e}")
            for player in results:
                results[player]['error'] = str(e)

        return results
