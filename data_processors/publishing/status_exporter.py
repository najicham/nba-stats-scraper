"""
Status Exporter for Phase 6 Publishing

Exports a status.json file that provides real-time visibility into
the health of all data pipelines. Frontend can poll this to:
- Show "Data updating..." vs "Data may be stale"
- Display known issues or maintenance windows
- Verify data freshness before showing to users

Updated every time live data is exported.
"""

import logging
import os
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

from google.cloud import storage, bigquery
from shared.clients.bigquery_pool import get_bigquery_client

from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)

# Freshness thresholds (in minutes)
LIVE_DATA_STALE_THRESHOLD = 10  # During games, data should update every 3 min
TONIGHT_DATA_STALE_THRESHOLD = 60  # Tonight data updates hourly


class StatusExporter(BaseExporter):
    """
    Export pipeline status to JSON for frontend visibility.

    Output file:
    - status.json - Current pipeline health status

    JSON structure:
    {
        "updated_at": "2025-12-28T23:57:26Z",
        "overall_status": "healthy",  // healthy | degraded | unhealthy
        "services": {
            "live_data": { ... },
            "tonight_data": { ... },
            "grading": { ... },
            "predictions": { ... }
        },
        "known_issues": [],
        "maintenance_windows": []
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._gcs_storage_client = None
        self._bigquery_client = None

    def _get_storage_client(self):
        """Get or create storage client via pool."""
        if self._gcs_storage_client is None:
            from shared.clients import get_storage_client
            self._gcs_storage_client = get_storage_client(self.project_id)
        return self._gcs_storage_client

    def _get_bq_client(self):
        """Get or create BigQuery client."""
        if self._bigquery_client is None:
            self._bigquery_client = get_bigquery_client(project_id=self.project_id)
        return self._bigquery_client

    def generate_json(self, target_date: str = None) -> Dict[str, Any]:
        """
        Generate status JSON.

        Args:
            target_date: Optional date for context (defaults to today ET)

        Returns:
            Dictionary ready for JSON serialization
        """
        now = datetime.now(timezone.utc)

        # Get status for each service
        live_status = self._check_live_data_status()
        tonight_status = self._check_tonight_data_status()
        grading_status = self._check_grading_status()
        predictions_status = self._check_predictions_status(target_date)

        # Determine overall status
        statuses = [
            live_status.get('status', 'unknown'),
            tonight_status.get('status', 'unknown'),
            predictions_status.get('status', 'unknown')
        ]

        if 'unhealthy' in statuses:
            overall_status = 'unhealthy'
        elif 'degraded' in statuses or 'unknown' in statuses:
            overall_status = 'degraded'
        else:
            overall_status = 'healthy'

        # Build known issues list
        known_issues = self._build_known_issues(
            live_status, tonight_status, grading_status, predictions_status
        )

        return {
            'updated_at': now.isoformat(),
            'overall_status': overall_status,
            'services': {
                'live_data': live_status,
                'tonight_data': tonight_status,
                'grading': grading_status,
                'predictions': predictions_status
            },
            'known_issues': known_issues,
            'maintenance_windows': self._get_maintenance_windows()
        }

    def _check_live_data_status(self) -> Dict[str, Any]:
        """Check live data freshness and status."""
        try:
            bucket = self._get_storage_client().bucket('nba-props-platform-api')
            blob = bucket.blob('v1/live/latest.json')

            if not blob.exists():
                return {
                    'status': 'unhealthy',
                    'message': 'Live data file not found',
                    'last_update': None,
                    'is_stale': True
                }

            # Get last modified time
            blob.reload()
            last_update = blob.updated

            # Check if stale
            age_minutes = (datetime.now(timezone.utc) - last_update).total_seconds() / 60
            is_stale = age_minutes > LIVE_DATA_STALE_THRESHOLD

            # Determine status based on staleness and whether games are active
            # During off-hours, stale is expected and OK
            games_likely_active = self._are_games_likely_active()

            if is_stale and games_likely_active:
                status = 'degraded'
                message = f'Data is {int(age_minutes)} minutes old during game hours'
            elif is_stale:
                status = 'healthy'
                message = 'No games currently active'
            else:
                status = 'healthy'
                message = 'Data is fresh'

            # Calculate next expected update (every 3 min during games)
            if games_likely_active:
                next_update = last_update + timedelta(minutes=3)
            else:
                next_update = None

            return {
                'status': status,
                'message': message,
                'last_update': last_update.isoformat(),
                'age_minutes': round(age_minutes, 1),
                'is_stale': is_stale and games_likely_active,
                'games_active': games_likely_active,
                'next_update_expected': next_update.isoformat() if next_update else None
            }

        except Exception as e:
            logger.error(f"Error checking live data status: {e}", exc_info=True)
            return {
                'status': 'unknown',
                'message': f'Error checking status: {str(e)}',
                'last_update': None,
                'is_stale': None
            }

    def _check_tonight_data_status(self) -> Dict[str, Any]:
        """Check tonight's predictions data status."""
        try:
            bucket = self._get_storage_client().bucket('nba-props-platform-api')
            blob = bucket.blob('v1/tonight/all-players.json')

            if not blob.exists():
                return {
                    'status': 'unhealthy',
                    'message': 'Tonight data file not found',
                    'last_update': None,
                    'is_stale': True
                }

            blob.reload()
            last_update = blob.updated
            age_minutes = (datetime.now(timezone.utc) - last_update).total_seconds() / 60
            is_stale = age_minutes > TONIGHT_DATA_STALE_THRESHOLD

            return {
                'status': 'healthy' if not is_stale else 'degraded',
                'message': 'Data is fresh' if not is_stale else f'Data is {int(age_minutes)} minutes old',
                'last_update': last_update.isoformat(),
                'age_minutes': round(age_minutes, 1),
                'is_stale': is_stale
            }

        except Exception as e:
            logger.error(f"Error checking tonight data status: {e}", exc_info=True)
            return {
                'status': 'unknown',
                'message': f'Error checking status: {str(e)}',
                'last_update': None
            }

    def _check_grading_status(self) -> Dict[str, Any]:
        """Check live grading status."""
        try:
            bucket = self._get_storage_client().bucket('nba-props-platform-api')
            blob = bucket.blob('v1/live-grading/latest.json')

            if not blob.exists():
                return {
                    'status': 'degraded',
                    'message': 'Grading data file not found',
                    'last_update': None
                }

            blob.reload()
            last_update = blob.updated

            return {
                'status': 'healthy',
                'message': 'Grading data available',
                'last_update': last_update.isoformat()
            }

        except Exception as e:
            logger.error(f"Error checking grading status: {e}", exc_info=True)
            return {
                'status': 'unknown',
                'message': f'Error checking status: {str(e)}'
            }

    def _check_predictions_status(self, target_date: str = None) -> Dict[str, Any]:
        """Check if predictions exist for today/tomorrow."""
        try:
            if not target_date:
                from zoneinfo import ZoneInfo
                et = ZoneInfo('America/New_York')
                target_date = datetime.now(et).strftime('%Y-%m-%d')

            query = """
            SELECT COUNT(*) as count
            FROM `nba_predictions.player_prop_predictions`
            WHERE game_date = @target_date
              AND is_active = TRUE
            """
            params = [bigquery.ScalarQueryParameter("target_date", "DATE", target_date)]

            result = list(self._get_bq_client().query(query, job_config=bigquery.QueryJobConfig(
                query_parameters=params
            )))

            count = result[0].count if result else 0

            if count > 0:
                return {
                    'status': 'healthy',
                    'message': f'{count} predictions available for {target_date}',
                    'predictions_count': count,
                    'target_date': target_date
                }
            else:
                return {
                    'status': 'degraded',
                    'message': f'No predictions found for {target_date}',
                    'predictions_count': 0,
                    'target_date': target_date
                }

        except Exception as e:
            logger.error(f"Error checking predictions status: {e}", exc_info=True)
            return {
                'status': 'unknown',
                'message': f'Error checking status: {str(e)}'
            }

    def _are_games_likely_active(self) -> bool:
        """
        Check if NBA games are likely in progress based on current time.
        Games typically run 4 PM - 1 AM ET.
        """
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            import pytz
            et = pytz.timezone('America/New_York')
            now_et = datetime.now(et)
        else:
            et = ZoneInfo('America/New_York')
            now_et = datetime.now(et)

        hour = now_et.hour

        # Games typically active from 4 PM (16) to 1 AM (1)
        # This is a heuristic - could be improved by checking actual schedule
        return 16 <= hour <= 23 or 0 <= hour <= 1

    def _build_known_issues(self, *service_statuses) -> List[Dict[str, str]]:
        """Build list of known issues from service statuses."""
        issues = []

        for status in service_statuses:
            if isinstance(status, dict):
                if status.get('status') in ('degraded', 'unhealthy'):
                    issues.append({
                        'severity': status.get('status'),
                        'message': status.get('message', 'Unknown issue'),
                        'detected_at': datetime.now(timezone.utc).isoformat()
                    })

        return issues

    def _get_maintenance_windows(self) -> List[Dict[str, Any]]:
        """Get any scheduled maintenance windows."""
        # Could be populated from a config file or database
        # For now, return empty list
        return []

    def export(self, target_date: str = None) -> str:
        """
        Generate and upload status JSON.

        Args:
            target_date: Optional target date for predictions check

        Returns:
            GCS path of the exported file
        """
        logger.info("Exporting pipeline status")

        json_data = self.generate_json(target_date)

        # Upload with short cache (1 minute for status)
        path = 'status.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=60')

        overall = json_data.get('overall_status', 'unknown')
        issues = len(json_data.get('known_issues', []))
        logger.info(f"Exported status: {overall}, {issues} issues")

        return gcs_path
