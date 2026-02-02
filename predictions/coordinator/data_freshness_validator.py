#!/usr/bin/env python3
"""
Data Freshness Validator

Validates that upstream Phase 3 and Phase 4 data is fresh before Phase 5 predictions run.
Prevents predictions from running on stale data due to pipeline timing issues.

Author: Claude Code
Created: 2026-01-18
Session: 106
"""

import logging
import os
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class DataFreshnessValidator:
    """Validates data freshness before running predictions."""

    def __init__(self, project_id: str = None):
        """
        Initialize validator.

        Args:
            project_id: GCP project ID (defaults to env var)
        """
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        from shared.clients import get_bigquery_client
        self.bq_client = get_bigquery_client(self.project_id)

    def validate_phase3_freshness(self, game_date: date, max_age_hours: int = 24) -> Tuple[bool, str, Dict]:
        """
        Validate Phase 3 (upcoming_player_game_context) has fresh data.

        Args:
            game_date: Date to generate predictions for
            max_age_hours: Maximum acceptable data age in hours

        Returns:
            (is_fresh, reason, details_dict)
        """
        try:
            # Check if upcoming_player_game_context has today's data
            query = f"""
            SELECT
                COUNT(*) as total_players,
                COUNT(DISTINCT game_date) as unique_dates,
                MIN(created_at) as oldest_record,
                MAX(created_at) as newest_record,
                COUNTIF(current_points_line IS NOT NULL) as players_with_lines
            FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = '{game_date.isoformat()}'
            """

            result = self.bq_client.query(query).result()
            row = next(result, None)

            if not row:
                return False, "No data returned from query", {}

            total_players = row.total_players
            players_with_lines = row.players_with_lines
            newest_record = row.newest_record

            details = {
                'total_players': total_players,
                'players_with_lines': players_with_lines,
                'newest_record': newest_record.isoformat() if newest_record else None,
                'game_date': game_date.isoformat()
            }

            # Validation checks
            if total_players == 0:
                return False, f"No players found for {game_date}", details

            if total_players < 50:
                return False, f"Too few players ({total_players}) for {game_date}, expected 100+", details

            if players_with_lines < 20:
                return False, f"Too few players with betting lines ({players_with_lines}), expected 40+", details

            # Check data age
            if newest_record:
                age_hours = (datetime.now(timezone.utc) - newest_record).total_seconds() / 3600
                details['data_age_hours'] = round(age_hours, 2)

                if age_hours > max_age_hours:
                    return False, f"Data is {age_hours:.1f} hours old, max allowed {max_age_hours}", details

            return True, "Phase 3 data is fresh", details

        except Exception as e:
            logger.error(f"Error validating Phase 3 freshness: {e}", exc_info=True)
            return False, f"Validation error: {str(e)}", {}

    def validate_phase4_freshness(self, game_date: date, max_age_hours: int = 24) -> Tuple[bool, str, Dict]:
        """
        Validate Phase 4 (ml_feature_store_v2) has fresh data.

        Args:
            game_date: Date to generate predictions for
            max_age_hours: Maximum acceptable data age in hours

        Returns:
            (is_fresh, reason, details_dict)
        """
        try:
            # Check if ml_feature_store_v2 has recent data
            query = f"""
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT player_lookup) as unique_players,
                MAX(created_at) as newest_record
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date = '{game_date.isoformat()}'
            """

            result = self.bq_client.query(query).result()
            row = next(result, None)

            if not row:
                return False, "No data returned from query", {}

            total_records = row.total_records
            unique_players = row.unique_players
            newest_record = row.newest_record

            details = {
                'total_records': total_records,
                'unique_players': unique_players,
                'newest_record': newest_record.isoformat() if newest_record else None,
                'game_date': game_date.isoformat()
            }

            # Validation checks
            if total_records == 0:
                return False, f"No ML features found for {game_date}", details

            if unique_players < 50:
                return False, f"Too few players in ML feature store ({unique_players}), expected 100+", details

            # Check data age
            if newest_record:
                age_hours = (datetime.now(timezone.utc) - newest_record).total_seconds() / 3600
                details['data_age_hours'] = round(age_hours, 2)

                if age_hours > max_age_hours:
                    return False, f"Data is {age_hours:.1f} hours old, max allowed {max_age_hours}", details

            return True, "Phase 4 data is fresh", details

        except Exception as e:
            logger.error(f"Error validating Phase 4 freshness: {e}", exc_info=True)
            return False, f"Validation error: {str(e)}", {}

    def validate_line_coverage(self, game_date: date, min_coverage_pct: float = 70.0) -> Tuple[bool, str, Dict]:
        """
        Validate that sufficient players have REAL betting lines (not estimated).

        This prevents predictions from running with low-quality estimated lines
        that would need to be re-run anyway once real lines arrive.

        Args:
            game_date: Date to generate predictions for
            min_coverage_pct: Minimum % of players that must have real lines (default 70%)

        Returns:
            (passes_gate, reason, details_dict)
        """
        try:
            # Query line coverage from both odds_api and bettingpros
            query = f"""
            WITH players_expected AS (
                -- Players we expect to have predictions for
                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
                WHERE game_date = '{game_date.isoformat()}'
                  AND (is_production_ready = TRUE OR has_prop_line = TRUE)
            ),
            lines_available AS (
                -- Players with real lines from any source
                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
                WHERE game_date = '{game_date.isoformat()}'
                  AND points_line IS NOT NULL

                UNION DISTINCT

                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
                WHERE game_date = '{game_date.isoformat()}'
                  AND points_line IS NOT NULL
            )
            SELECT
                (SELECT COUNT(*) FROM players_expected) as total_players,
                (SELECT COUNT(*) FROM lines_available) as players_with_real_lines,
                (SELECT COUNT(*) FROM players_expected p
                 JOIN lines_available l ON p.player_lookup = l.player_lookup) as matched_players
            """

            result = self.bq_client.query(query).result()
            row = next(result, None)

            if not row:
                return False, "No data returned from query", {}

            total_players = row.total_players or 0
            players_with_real_lines = row.players_with_real_lines or 0
            matched_players = row.matched_players or 0

            # Calculate coverage percentage
            coverage_pct = (matched_players / total_players * 100) if total_players > 0 else 0
            without_lines = total_players - matched_players

            details = {
                'game_date': game_date.isoformat(),
                'total_players_expected': total_players,
                'players_with_real_lines': players_with_real_lines,
                'players_matched_with_lines': matched_players,
                'players_without_lines': without_lines,
                'line_coverage_pct': round(coverage_pct, 1),
                'min_required_pct': min_coverage_pct
            }

            # Check if coverage meets threshold
            if total_players == 0:
                return False, f"No players found for {game_date}", details

            if coverage_pct >= min_coverage_pct:
                return True, f"Line coverage {coverage_pct:.1f}% meets {min_coverage_pct}% threshold", details
            else:
                return False, (
                    f"Line coverage {coverage_pct:.1f}% below {min_coverage_pct}% threshold "
                    f"({without_lines} players missing lines)"
                ), details

        except Exception as e:
            logger.error(f"Error validating line coverage: {e}", exc_info=True)
            return False, f"Validation error: {str(e)}", {}

    def validate_all(
        self,
        game_date: date,
        max_age_hours: int = 24,
        require_line_coverage: bool = False,
        min_line_coverage_pct: float = 70.0
    ) -> Tuple[bool, List[str], Dict]:
        """
        Validate Phase 3, Phase 4, and optionally line coverage.

        Args:
            game_date: Date to generate predictions for
            max_age_hours: Maximum acceptable data age in hours
            require_line_coverage: If True, also validate that real betting lines exist
            min_line_coverage_pct: Minimum % of players with real lines (if required)

        Returns:
            (all_valid, error_messages, details_dict)
        """
        errors = []
        all_details = {}

        # Validate Phase 3
        phase3_fresh, phase3_reason, phase3_details = self.validate_phase3_freshness(game_date, max_age_hours)
        all_details['phase3'] = phase3_details
        all_details['phase3_fresh'] = phase3_fresh
        all_details['phase3_reason'] = phase3_reason

        if not phase3_fresh:
            errors.append(f"Phase 3: {phase3_reason}")

        # Validate Phase 4
        phase4_fresh, phase4_reason, phase4_details = self.validate_phase4_freshness(game_date, max_age_hours)
        all_details['phase4'] = phase4_details
        all_details['phase4_fresh'] = phase4_fresh
        all_details['phase4_reason'] = phase4_reason

        if not phase4_fresh:
            errors.append(f"Phase 4: {phase4_reason}")

        # Validate Line Coverage (optional but logged)
        line_valid, line_reason, line_details = self.validate_line_coverage(game_date, min_line_coverage_pct)
        all_details['line_coverage'] = line_details
        all_details['line_coverage_valid'] = line_valid
        all_details['line_coverage_reason'] = line_reason

        # Always log line coverage for visibility
        coverage_pct = line_details.get('line_coverage_pct', 0)
        if line_valid:
            logger.info(f"Line coverage: {coverage_pct}% (meets {min_line_coverage_pct}% threshold)")
        else:
            logger.warning(f"Line coverage: {coverage_pct}% (below {min_line_coverage_pct}% threshold)")

        if require_line_coverage and not line_valid:
            errors.append(f"Line coverage: {line_reason}")

        # All validation passes if Phase 3 and Phase 4 are fresh
        # AND line coverage passes (if required)
        all_valid = phase3_fresh and phase4_fresh
        if require_line_coverage:
            all_valid = all_valid and line_valid

        return all_valid, errors, all_details


def get_freshness_validator() -> DataFreshnessValidator:
    """Get singleton validator instance."""
    global _validator_instance
    if '_validator_instance' not in globals():
        _validator_instance = DataFreshnessValidator()
    return _validator_instance
