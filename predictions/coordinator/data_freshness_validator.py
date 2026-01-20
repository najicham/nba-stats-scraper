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
        self.bq_client = bigquery.Client(project=self.project_id)

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
            logger.error(f"Error validating Phase 3 freshness: {e}")
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
            logger.error(f"Error validating Phase 4 freshness: {e}")
            return False, f"Validation error: {str(e)}", {}

    def validate_all(self, game_date: date, max_age_hours: int = 24) -> Tuple[bool, List[str], Dict]:
        """
        Validate both Phase 3 and Phase 4 data freshness.

        Args:
            game_date: Date to generate predictions for
            max_age_hours: Maximum acceptable data age in hours

        Returns:
            (all_fresh, error_messages, details_dict)
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

        all_fresh = phase3_fresh and phase4_fresh

        return all_fresh, errors, all_details


def get_freshness_validator() -> DataFreshnessValidator:
    """Get singleton validator instance."""
    global _validator_instance
    if '_validator_instance' not in globals():
        _validator_instance = DataFreshnessValidator()
    return _validator_instance
