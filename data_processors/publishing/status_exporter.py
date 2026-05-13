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
        """Check if predictions exist for today across NBA and MLB.

        Aggregated across both sports — system is healthy if EITHER sport
        produced predictions today. Off-season NBA + active MLB (or vice versa)
        should not register as degraded.
        """
        try:
            if not target_date:
                from zoneinfo import ZoneInfo
                et = ZoneInfo('America/New_York')
                target_date = datetime.now(et).strftime('%Y-%m-%d')

            params = [bigquery.ScalarQueryParameter("target_date", "DATE", target_date)]
            client = self._get_bq_client()

            nba_count = 0
            mlb_count = 0

            try:
                nba_result = list(client.query(
                    """
                    SELECT COUNT(*) as count
                    FROM `nba_predictions.player_prop_predictions`
                    WHERE game_date = @target_date AND is_active = TRUE
                    """,
                    job_config=bigquery.QueryJobConfig(query_parameters=params),
                ))
                nba_count = nba_result[0].count if nba_result else 0
            except Exception as e:
                logger.warning(f"NBA predictions check failed: {e}")

            try:
                mlb_result = list(client.query(
                    """
                    SELECT COUNT(*) as count
                    FROM `mlb_predictions.pitcher_strikeouts`
                    WHERE game_date = @target_date
                    """,
                    job_config=bigquery.QueryJobConfig(query_parameters=params),
                ))
                mlb_count = mlb_result[0].count if mlb_result else 0
            except Exception as e:
                logger.warning(f"MLB predictions check failed: {e}")

            total = nba_count + mlb_count
            base = {
                'predictions_count': total,
                'nba_count': nba_count,
                'mlb_count': mlb_count,
                'target_date': target_date,
            }

            if total > 0:
                parts = []
                if nba_count > 0:
                    parts.append(f'{nba_count} NBA')
                if mlb_count > 0:
                    parts.append(f'{mlb_count} MLB')
                return {
                    **base,
                    'status': 'healthy',
                    'message': f"{' + '.join(parts)} predictions available for {target_date}",
                }

            if active_break:
                headline = active_break.get('headline', 'Schedule Break')
                return {
                    **base,
                    'status': 'healthy',
                    'message': f'No predictions expected — {headline}',
                }

            return {
                **base,
                'status': 'degraded',
                'message': f'No predictions found for {target_date}',
            }

        except Exception as e:
            logger.error(f"Error checking predictions status: {e}", exc_info=True)
            return {
                'status': 'unknown',
                'message': f'Error checking status: {str(e)}'
            }

    def _check_best_bets_status(self, active_break=None) -> Dict[str, Any]:
        """Check best bets export freshness across NBA and MLB.

        System is healthy if EITHER sport produced a fresh best-bets file today.
        NBA off-season + active MLB (or vice versa) should register as healthy.
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

            from zoneinfo import ZoneInfo
            et = ZoneInfo('America/New_York')
            today_et = datetime.now(et).date()

            nba_info = self._check_sport_best_bets(
                blob_path='v1/signal-best-bets/latest.json',
                today_et=today_et,
            )
            mlb_info = self._check_sport_best_bets(
                blob_path=f'v1/mlb/best-bets/{today_et.isoformat()}.json',
                today_et=today_et,
            )

            nba_fresh = nba_info['is_fresh']
            mlb_fresh = mlb_info['is_fresh']
            total_picks = (nba_info['total_picks'] or 0) + (mlb_info['total_picks'] or 0)

            base = {
                'total_picks': total_picks,
                'nba': nba_info,
                'mlb': mlb_info,
                'last_update': nba_info['last_update'] or mlb_info['last_update'],
            }

            if nba_fresh or mlb_fresh:
                parts = []
                if nba_fresh:
                    parts.append(f"{nba_info['total_picks']} NBA")
                if mlb_fresh:
                    parts.append(f"{mlb_info['total_picks']} MLB")
                joined = ' + '.join(parts) if parts else '0'
                return {
                    **base,
                    'status': 'healthy',
                    'message': f'{joined} best bets available',
                }

            # Neither sport fresh — degraded only if neither file even exists today.
            # If files exist but are stale, this is an off-day across both sports;
            # surface as degraded so something gets investigated.
            return {
                **base,
                'status': 'degraded',
                'message': 'No fresh best bets file for today (NBA or MLB)',
            }

        except Exception as e:
            logger.error(f"Error checking best bets status: {e}", exc_info=True)
            return {
                'status': 'unknown',
                'message': f'Error checking status: {str(e)}',
                'total_picks': 0,
                'last_update': None,
            }

    def _check_sport_best_bets(self, blob_path: str, today_et) -> Dict[str, Any]:
        """Inspect one sport's best-bets file: existence, freshness, pick count."""
        bucket = self._get_storage_client().bucket('nba-props-platform-api')
        blob = bucket.blob(blob_path)

        if not blob.exists():
            return {'exists': False, 'is_fresh': False, 'total_picks': 0, 'last_update': None}

        blob.reload()
        last_update = blob.updated
        from zoneinfo import ZoneInfo
        et = ZoneInfo('America/New_York')
        last_update_et = last_update.astimezone(et).date()
        is_fresh = last_update_et >= today_et

        total_picks = 0
        try:
            import json
            data = json.loads(blob.download_as_text())
            total_picks = data.get('total_picks', 0)
            if not total_picks:
                picks_list = data.get('picks') or data.get('best_bets')
                if isinstance(picks_list, list):
                    total_picks = len(picks_list)
        except Exception as e:
            logger.warning(f"Failed to read {blob_path}: {e}")

        return {
            'exists': True,
            'is_fresh': is_fresh,
            'total_picks': total_picks,
            'last_update': last_update.isoformat(),
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

        try:
            self._maybe_send_status_alert(json_data)
        except Exception as e:
            logger.warning(f"Status alert dispatch failed (non-critical): {e}")

        return gcs_path

    # Alert state marker stored alongside the API artifacts so any CF instance
    # (live-export, daily-health-check) sees the same transition history.
    _ALERT_STATE_BLOB = 'v1/admin/status-alert-state.json'
    _ALERT_REMINDER_INTERVAL_HOURS = 24

    def _maybe_send_status_alert(self, status_json: Dict[str, Any]) -> None:
        """Send an admin email when overall status worsens, recovers, or persists.

        Rate-limit:
        - Edge-trigger on any status change.
        - While degraded/unhealthy, send at most one reminder per 24h.
        - On recovery (→ healthy), send a single recovery notice.

        Reads/writes state at gs://nba-props-platform-api/v1/admin/status-alert-state.json.
        """
        overall = status_json.get('overall_status', 'unknown')
        prev_state = self._read_alert_state()
        prev_status = prev_state.get('last_status', 'healthy')
        last_alerted_at = prev_state.get('last_alerted_at')

        now = datetime.now(timezone.utc)
        should_send = False
        reason = None

        if overall == 'healthy' and prev_status != 'healthy':
            should_send = True
            reason = 'recovered'
        elif overall != 'healthy' and prev_status == 'healthy':
            should_send = True
            reason = 'newly_degraded'
        elif overall != 'healthy' and overall != prev_status:
            should_send = True
            reason = 'escalated_or_changed'
        elif overall != 'healthy' and last_alerted_at:
            try:
                last_dt = datetime.fromisoformat(last_alerted_at.replace('Z', '+00:00'))
                if (now - last_dt).total_seconds() >= self._ALERT_REMINDER_INTERVAL_HOURS * 3600:
                    should_send = True
                    reason = 'reminder'
            except Exception:
                should_send = True
                reason = 'reminder_state_unparseable'

        # Always remember the observed status so we don't repeatedly edge-trigger
        # on the same transition if dispatch keeps failing. Only advance
        # last_alerted_at when a notification was actually delivered — that way
        # a failed dispatch still gets a retry on the next tick (reminder branch)
        # instead of being suppressed for 24h.
        new_state = {
            'last_status': overall,
            'last_alerted_at': last_alerted_at,
            'last_reason': prev_state.get('last_reason'),
        }

        if should_send:
            delivered = self._dispatch_notification(overall, status_json, reason)
            if delivered:
                new_state['last_alerted_at'] = now.isoformat()
                new_state['last_reason'] = reason

        self._write_alert_state(new_state)

    def _read_alert_state(self) -> Dict[str, Any]:
        try:
            bucket = self._get_storage_client().bucket('nba-props-platform-api')
            blob = bucket.blob(self._ALERT_STATE_BLOB)
            if not blob.exists():
                return {}
            import json
            return json.loads(blob.download_as_text())
        except Exception as e:
            logger.warning(f"Failed to read alert state: {e}")
            return {}

    def _write_alert_state(self, state: Dict[str, Any]) -> None:
        try:
            import json
            bucket = self._get_storage_client().bucket('nba-props-platform-api')
            blob = bucket.blob(self._ALERT_STATE_BLOB)
            blob.upload_from_string(json.dumps(state), content_type='application/json')
        except Exception as e:
            logger.warning(f"Failed to persist alert state: {e}")

    def _dispatch_notification(self, overall: str, status_json: Dict[str, Any], reason: str) -> bool:
        """Send a status notification. Returns True if delivered, False if any
        step failed — caller uses this to decide whether to persist
        last_alerted_at.
        """
        try:
            from shared.utils.notification_system import notify_warning, notify_error, notify_info
        except Exception as e:
            logger.warning(f"notification_system unavailable: {e}")
            return False

        services = status_json.get('services', {}) or {}
        known_issues = status_json.get('known_issues', []) or []
        details = {
            'overall_status': overall,
            'transition_reason': reason,
            'predictions': services.get('predictions', {}).get('message'),
            'best_bets': services.get('best_bets', {}).get('message'),
            'tonight_data': services.get('tonight_data', {}).get('message'),
            'live_data': services.get('live_data', {}).get('message'),
            'issue_count': len(known_issues),
            'known_issues': known_issues,
            'status_url': 'https://storage.googleapis.com/nba-props-platform-api/v1/status.json',
        }

        try:
            if overall == 'healthy':
                notify_info(
                    title='Player Props status recovered',
                    message=f'System back to healthy (was {reason}).',
                    details=details,
                    processor_name='status-exporter',
                )
            elif overall == 'unhealthy':
                notify_error(
                    title='Player Props status UNHEALTHY',
                    message=f"Pipeline reports unhealthy ({reason}). {len(known_issues)} known issue(s).",
                    details=details,
                    processor_name='status-exporter',
                )
            else:
                notify_warning(
                    title='Player Props status degraded',
                    message=f"Pipeline degraded ({reason}). {len(known_issues)} known issue(s).",
                    details=details,
                    processor_name='status-exporter',
                )
            return True
        except Exception as e:
            logger.warning(f"Status notification dispatch failed: {e}")
            return False
