"""
Dependency Validator - Phase 2 Dependency Checking

Validates that required Phase 2 data sources are available and fresh.

Extracted from upcoming_team_game_context_processor.py for maintainability.
"""

import logging

logger = logging.getLogger(__name__)


class DependencyValidator:
    """
    Validator for Phase 2 data dependencies.

    Checks availability and freshness of upstream data sources.
    """

    @staticmethod
    def get_dependencies() -> dict:
        """
        Define Phase 2 source requirements following Dependency Tracking v4.0.

        Returns:
            dict: Dependency configuration for each source table
        """
        return {
            'nba_raw.nbac_schedule': {
                'field_prefix': 'source_nbac_schedule',
                'description': 'Game schedule and matchups',
                'check_type': 'date_range',

                # Data requirements
                'expected_count_min': 20,  # ~10 games × 2 teams per day

                # Freshness thresholds
                'max_age_hours_warn': 12,  # Warn if schedule >12h old
                'max_age_hours_fail': 36,  # Fail if schedule >36h old

                # Early season handling
                'early_season_days': 0,  # No early season for schedule
                'early_season_behavior': 'CONTINUE',

                'critical': True  # Cannot process without schedule
            },

            'nba_raw.odds_api_game_lines': {
                'field_prefix': 'source_odds_lines',
                'description': 'Betting lines (spreads and totals)',
                'check_type': 'date_range',

                # Data requirements (more lenient - optional source)
                'expected_count_min': 40,  # Multiple bookmakers × games

                # Freshness thresholds (more strict - lines change fast)
                'max_age_hours_warn': 4,   # Warn if lines >4h old
                'max_age_hours_fail': 12,  # Fail if lines >12h old

                'critical': False  # Can process without betting lines
            },

            'nba_raw.nbac_injury_report': {
                'field_prefix': 'source_injury_report',
                'description': 'Player injury and availability status',
                'check_type': 'date_range',

                # Data requirements (variable by day)
                'expected_count_min': 10,  # 0-50 injured players typical

                # Freshness thresholds
                'max_age_hours_warn': 8,   # Warn if report >8h old
                'max_age_hours_fail': 24,  # Fail if report >24h old

                'critical': False  # Can process without injury data
            }
        }

    @staticmethod
    def get_upstream_data_check_query(start_date: str, end_date: str, project_id: str) -> str:
        """
        Check if upstream data is available for circuit breaker auto-reset.

        For upcoming games, verifies:
        1. Schedule data exists for the target date range
        2. There are scheduled games to process

        Args:
            start_date: Start of date range (YYYY-MM-DD)
            end_date: End of date range (YYYY-MM-DD)
            project_id: GCP project ID

        Returns:
            SQL query that returns {data_available: boolean}
        """
        return f"""
        SELECT
            COUNT(*) > 0 AS data_available
        FROM `{project_id}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND game_status IN (1, 2)  -- Scheduled or In Progress
        """
