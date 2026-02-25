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

        # Check for active schedule breaks FIRST so service checks can use it
        active_break = self._check_active_break()

        # Get status for each service (break-aware)
        live_status = self._check_live_data_status(active_break)
        tonight_status = self._check_tonight_data_status(active_break)
        grading_status = self._check_grading_status()
        predictions_status = self._check_predictions_status(target_date, active_break)
        best_bets_status = self._check_best_bets_status(active_break)

        # Determine overall status (best_bets excluded — 0 picks is honest, not a failure)
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
            live_status, tonight_status, grading_status, predictions_status,
            best_bets_status
        )

        return {
            'updated_at': now.isoformat(),
            'overall_status': overall_status,
            'services': {
                'live_data': live_status,
                'tonight_data': tonight_status,
                'grading': grading_status,
                'predictions': predictions_status,
                'best_bets': best_bets_status,
            },
            'known_issues': known_issues,
            'maintenance_windows': self._get_maintenance_windows(),
            'active_break': active_break
        }

    def _check_live_data_status(self, active_break=None) -> Dict[str, Any]:
        """Check live data freshness and status."""
        try:
            # During a schedule break, no live data expected — healthy
            if active_break:
                headline = active_break.get('headline', 'Schedule Break')
                message = active_break.get('message', 'No games scheduled')
                return {
                    'status': 'healthy',
                    'message': f'No games — {headline} ({message})',
                    'last_update': None,
                    'is_stale': False,
                    'games_active': False,
                    'next_update_expected': None
                }

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

    def _check_tonight_data_status(self, active_break=None) -> Dict[str, Any]:
        """Check tonight's predictions data status."""
        try:
            if active_break:
                headline = active_break.get('headline', 'Schedule Break')
                message = active_break.get('message', 'No games scheduled')
                return {
                    'status': 'healthy',
                    'message': f'No games — {headline} ({message})',
                    'last_update': None,
                    'is_stale': False
                }

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

    def _check_predictions_status(self, target_date: str = None, active_break=None) -> Dict[str, Any]:
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
            elif active_break:
                # Zero predictions expected during a schedule break
                headline = active_break.get('headline', 'Schedule Break')
                return {
                    'status': 'healthy',
                    'message': f'No predictions expected — {headline}',
                    'predictions_count': 0,
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

    def _check_best_bets_status(self, active_break=None) -> Dict[str, Any]:
        """Check best bets export freshness and pick count.

        Reads the latest.json from GCS to determine:
        - Whether the file exists and is fresh (updated today)
        - How many picks were selected
        - 0 picks is reported honestly (healthy with message), not as degraded
        """
        try:
            if active_break:
                headline = active_break.get('headline', 'Schedule Break')
                return {
                    'status': 'healthy',
                    'message': f'No best bets expected — {headline}',
                    'total_picks': 0,
                    'last_update': None,
                }

            bucket = self._get_storage_client().bucket('nba-props-platform-api')
            blob = bucket.blob('v1/signal-best-bets/latest.json')

            if not blob.exists():
                return {
                    'status': 'degraded',
                    'message': 'Best bets file not found',
                    'total_picks': 0,
                    'last_update': None,
                }

            blob.reload()
            last_update = blob.updated

            # Check freshness: was it updated today (ET)?
            from zoneinfo import ZoneInfo
            et = ZoneInfo('America/New_York')
            today_et = datetime.now(et).date()
            last_update_et = last_update.astimezone(et).date()
            is_fresh = last_update_et >= today_et

            # Read the JSON to extract pick count
            total_picks = 0
            try:
                content = blob.download_as_text()
                import json
                data = json.loads(content)
                total_picks = data.get('total_picks', 0)
            except Exception as e:
                logger.warning(f"Failed to read best bets JSON content: {e}")

            if not is_fresh:
                return {
                    'status': 'degraded',
                    'message': f'Best bets file stale (last updated {last_update_et})',
                    'total_picks': total_picks,
                    'last_update': last_update.isoformat(),
                }

            if total_picks == 0:
                return {
                    'status': 'healthy',
                    'message': '0 picks today — all candidates filtered out',
                    'total_picks': 0,
                    'last_update': last_update.isoformat(),
                }

            return {
                'status': 'healthy',
                'message': f'{total_picks} best bets available',
                'total_picks': total_picks,
                'last_update': last_update.isoformat(),
            }

        except Exception as e:
            logger.error(f"Error checking best bets status: {e}", exc_info=True)
            return {
                'status': 'unknown',
                'message': f'Error checking status: {str(e)}',
                'total_picks': 0,
                'last_update': None,
            }

    def _are_games_likely_active(self) -> bool:
        """
        Check if NBA games are actually in progress by querying the schedule.

        Returns True only when games have game_status = 2 (In Progress),
        avoiding false-positive degradation before tipoff or after all games end.
        Falls back to a time-based heuristic if the query fails.
        """
        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo('America/New_York')
            today = datetime.now(et).strftime('%Y-%m-%d')

            query = """
            SELECT
                COUNTIF(game_status = 2) as in_progress
            FROM `nba_reference.nba_schedule`
            WHERE game_date = @today
            """
            params = [bigquery.ScalarQueryParameter("today", "DATE", today)]
            result = list(self._get_bq_client().query(
                query,
                job_config=bigquery.QueryJobConfig(query_parameters=params)
            ))

            if result:
                return result[0].in_progress > 0
            return False

        except Exception as e:
            logger.warning(f"Schedule query failed, falling back to time heuristic: {e}")
            # Fallback: time-based heuristic (4 PM - 1 AM ET)
            try:
                from zoneinfo import ZoneInfo
                now_et = datetime.now(ZoneInfo('America/New_York'))
            except Exception:
                now_et = datetime.now(timezone.utc)
            hour = now_et.hour
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

    def _check_active_break(self) -> Optional[Dict[str, str]]:
        """
        Check if currently in a multi-day schedule break (All-Star, holidays, etc.).

        Returns:
            Dict with break info if in a break, None otherwise.
            {
                "headline": "All-Star Break",
                "message": "Games resume Thursday, Feb 19",
                "resume_date": "2026-02-19",
                "last_game_date": "2026-02-12"
            }
        """
        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo('America/New_York')
            today = datetime.now(et).date()
            today_str = today.strftime('%Y-%m-%d')

            # Query schedule for last and next game dates.
            # Use nba_reference.nba_schedule (clean view) with regular-season/playoff filter
            # to exclude All-Star exhibitions that otherwise shrink the apparent gap.
            query = """
            WITH game_dates AS (
                SELECT DISTINCT game_date
                FROM `nba_reference.nba_schedule`
                WHERE game_date >= DATE_SUB(@today, INTERVAL 7 DAY)
                  AND game_date <= DATE_ADD(@today, INTERVAL 14 DAY)
                  AND (game_id LIKE '002%' OR game_id LIKE '004%')
            )
            SELECT
                MAX(CASE WHEN game_date <= @today THEN game_date END) as last_game_date,
                MIN(CASE WHEN game_date > @today THEN game_date END) as next_game_date
            FROM game_dates
            """
            params = [bigquery.ScalarQueryParameter("today", "DATE", today_str)]
            result = list(self._get_bq_client().query(
                query,
                job_config=bigquery.QueryJobConfig(query_parameters=params)
            ))
            if not result:
                return None

            row = result[0]
            last_game_date = row.last_game_date
            next_game_date = row.next_game_date

            # If either is None, we're not in a break
            if not last_game_date or not next_game_date:
                return None

            # Check if we're between games (in a break)
            if not (last_game_date < today < next_game_date):
                return None

            # Calculate gap in days
            gap_days = (next_game_date - last_game_date).days

            # Only show breaks for 3+ day gaps (excludes normal off-days)
            if gap_days < 3:
                return None

            # Determine break type and format message
            last_date_str = last_game_date.strftime('%Y-%m-%d')
            next_date_str = next_game_date.strftime('%Y-%m-%d')

            # Determine break name based on date or gap length
            headline = self._get_break_headline(last_game_date, next_game_date, gap_days)

            # Format resume message with day of week
            resume_day = next_game_date.strftime('%A, %b %-d')
            message = f"Games resume {resume_day}"

            return {
                'headline': headline,
                'message': message,
                'resume_date': next_date_str,
                'last_game_date': last_date_str
            }

        except Exception as e:
            logger.error(f"Error checking active break: {e}", exc_info=True)
            return None

    def _get_break_headline(self, last_date, next_date, gap_days: int) -> str:
        """
        Determine the break headline based on dates and gap length.

        Args:
            last_date: Date object of last games
            next_date: Date object of next games
            gap_days: Number of days in the gap

        Returns:
            Break headline string
        """
        # All-Star Break is typically mid-February
        if last_date.month == 2 and 10 <= last_date.day <= 18:
            return "All-Star Break"

        # Christmas break (late Dec)
        if last_date.month == 12 and last_date.day >= 24:
            return "Holiday Break"

        # Thanksgiving (late Nov)
        if last_date.month == 11 and 22 <= last_date.day <= 28:
            return "Thanksgiving Break"

        # Generic for other long breaks
        if gap_days >= 5:
            return "Extended Break"
        else:
            return "Schedule Break"

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
