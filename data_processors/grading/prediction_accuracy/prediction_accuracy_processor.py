"""
Prediction Accuracy Processor (Phase 5B - Grading)

Grades predictions against actual game results for ML training.
Compares predictions from all 5 systems to actual points scored.

Reads from:
- nba_predictions.player_prop_predictions (Phase 5A)
- nba_analytics.player_game_summary (Phase 3) for actual points
- nba_raw.nbac_injury_report (for DNP/injury correlation)

Writes to:
- nba_predictions.prediction_accuracy

Key Features:
- Grades all 5 prediction systems separately
- Computes absolute_error, signed_error (bias direction)
- Evaluates OVER/UNDER recommendation correctness
- Tracks threshold accuracy (within_3_points, within_5_points)
- Computes margin analysis for betting evaluation
- Tracks line source (has_prop_line, line_source) for no-line player analysis
- DNP/Injury voiding (v4): Marks DNP players as voided like sportsbooks void bets
"""

import json
import logging
import math
import re
import threading
from datetime import datetime, date, timezone
from typing import Dict, List, Optional

import pandas as pd
from google.cloud import bigquery
from google.api_core import exceptions as gcp_exceptions
from google.cloud.exceptions import GoogleCloudError
from shared.clients.bigquery_pool import get_bigquery_client

# SESSION 94 FIX: Import distributed lock to prevent race conditions
from predictions.shared.distributed_lock import DistributedLock, LockAcquisitionError, LOCK_TIMEOUT_SECONDS, MAX_ACQUIRE_ATTEMPTS, RETRY_DELAY_SECONDS

# Standardized error handling utility
from shared.utils.error_context import ErrorContext, log_operation_error

logger = logging.getLogger(__name__)

from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()


def _send_lock_failure_alert_async(
    game_date: str,
    lock_key: str,
    retry_attempts: int,
    timeout_duration: int,
    error_message: str
) -> None:
    """
    Send Slack alert for distributed lock failures (non-blocking).

    Runs in a separate thread to avoid blocking grading operations.
    Alert indicates grading proceeded WITHOUT lock protection (HIGH RISK of duplicates).

    Args:
        game_date: Date being graded (YYYY-MM-DD)
        lock_key: The Firestore lock key that failed
        retry_attempts: Number of retry attempts made
        timeout_duration: Total seconds spent trying to acquire lock
        error_message: Original error message from lock acquisition
    """
    def _send_alert():
        try:
            import requests
            from google.cloud import secretmanager

            # Get Slack webhook from Secret Manager
            client = secretmanager.SecretManagerServiceClient()
            secret_name = f"projects/{PROJECT_ID}/secrets/slack-webhook-url/versions/latest"
            response = client.access_secret_version(request={"name": secret_name})
            webhook_url = response.payload.data.decode("UTF-8")

            # Build alert message
            message = {
                "text": (
                    f":red_circle: *CRITICAL: Grading Lock Acquisition Failed*\n\n"
                    f"*Game Date:* {game_date}\n"
                    f"*Lock Key:* `{lock_key}`\n"
                    f"*Retry Attempts:* {retry_attempts}\n"
                    f"*Timeout Duration:* {timeout_duration} seconds\n"
                    f"*Status:* Grading proceeded WITHOUT distributed lock (HIGH RISK)\n\n"
                    f"*Error:*\n```{error_message}```\n\n"
                    f"*Risk:* Concurrent grading operations may create duplicate records\n\n"
                    f"*Investigation Steps:*\n"
                    f"  1. Check Firestore collection: `grading_locks`\n"
                    f"  2. Look for stuck lock with key: `{lock_key}`\n"
                    f"  3. Check Cloud Function logs for concurrent operations\n"
                    f"  4. Verify Firestore connectivity and quotas\n\n"
                    f"*Next Step:* Run duplicate detection query after grading completes"
                )
            }

            # Retry logic for transient failures
            max_retries = 2
            import time
            for attempt in range(max_retries + 1):
                try:
                    resp = requests.post(webhook_url, json=message, timeout=10)
                    if resp.status_code == 200:
                        logger.info(f"Sent lock failure alert for {game_date}")
                        break
                    elif resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        logger.warning(f"Slack lock failure alert failed: {resp.status_code}")
                        break
                except requests.exceptions.RequestException as e:
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
                        continue
                    logger.warning(f"Slack lock failure alert request failed: {e}")

        except Exception as e:
            # Log but don't fail grading if alert fails
            logger.warning(f"Failed to send lock failure alert for {game_date}: {e}")

    # Run in background thread to avoid blocking grading
    thread = threading.Thread(target=_send_alert, daemon=True)
    thread.start()


def _send_lock_timeout_alert_async(
    game_date: str,
    lock_key: str,
    elapsed_seconds: int
) -> None:
    """
    Send Slack alert when lock times out (non-blocking).

    This is different from acquisition failure - this is when we held the lock
    but the operation took longer than the lock timeout.

    Args:
        game_date: Date being graded (YYYY-MM-DD)
        lock_key: The Firestore lock key
        elapsed_seconds: How long the operation took
    """
    def _send_alert():
        try:
            import requests
            from google.cloud import secretmanager

            # Get Slack webhook from Secret Manager
            client = secretmanager.SecretManagerServiceClient()
            secret_name = f"projects/{PROJECT_ID}/secrets/slack-webhook-url/versions/latest"
            response = client.access_secret_version(request={"name": secret_name})
            webhook_url = response.payload.data.decode("UTF-8")

            # Build alert message
            message = {
                "text": (
                    f":warning: *Grading Lock Timeout Warning*\n\n"
                    f"*Game Date:* {game_date}\n"
                    f"*Lock Key:* `{lock_key}`\n"
                    f"*Operation Duration:* {elapsed_seconds} seconds\n"
                    f"*Lock Timeout:* {LOCK_TIMEOUT_SECONDS} seconds\n\n"
                    f"*Status:* Operation exceeded lock timeout\n"
                    f"*Note:* Lock may have expired during operation, increasing duplicate risk\n\n"
                    f"*Action:* Consider increasing LOCK_TIMEOUT_SECONDS if operations consistently exceed timeout"
                )
            }

            # Send with retry
            max_retries = 2
            import time
            for attempt in range(max_retries + 1):
                try:
                    resp = requests.post(webhook_url, json=message, timeout=10)
                    if resp.status_code == 200:
                        logger.info(f"Sent lock timeout alert for {game_date}")
                        break
                    elif resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        logger.warning(f"Slack lock timeout alert failed: {resp.status_code}")
                        break
                except requests.exceptions.RequestException as e:
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
                        continue
                    logger.warning(f"Slack lock timeout alert request failed: {e}")

        except Exception as e:
            logger.warning(f"Failed to send lock timeout alert for {game_date}: {e}")

    # Run in background thread
    thread = threading.Thread(target=_send_alert, daemon=True)
    thread.start()


class PredictionAccuracyProcessor:
    """
    Processor to grade predictions against actual results.

    For each prediction, computes:
    - absolute_error: |predicted - actual|
    - signed_error: predicted - actual (positive = over-predicted)
    - prediction_correct: Whether OVER/UNDER recommendation was right
    - predicted_margin: predicted_points - line_value
    - actual_margin: actual_points - line_value
    - within_3_points: abs(predicted - actual) <= 3
    - within_5_points: abs(predicted - actual) <= 5
    """

    def __init__(self, project_id: str = PROJECT_ID, dataset_prefix: str = ''):
        self._math = math
        self.project_id = project_id
        self.dataset_prefix = dataset_prefix
        self.bq_client = get_bigquery_client(project_id=project_id)

        # Construct table names with optional prefix
        predictions_dataset = f"{dataset_prefix}_nba_predictions" if dataset_prefix else "nba_predictions"
        analytics_dataset = f"{dataset_prefix}_nba_analytics" if dataset_prefix else "nba_analytics"
        raw_dataset = f"{dataset_prefix}_nba_raw" if dataset_prefix else "nba_raw"

        self.predictions_table = f'{project_id}.{predictions_dataset}.player_prop_predictions'
        self.actuals_table = f'{project_id}.{analytics_dataset}.player_game_summary'
        self.accuracy_table = f'{project_id}.{predictions_dataset}.prediction_accuracy'
        self.injury_table = f'{project_id}.{raw_dataset}.nbac_injury_report'

        # Cache for injury status lookups (populated per-date)
        self._injury_cache: Dict[str, Dict] = {}

        logger.info(f"Initialized PredictionAccuracyProcessor (dataset_prefix: {dataset_prefix or 'production'})")

    def _is_nan(self, value) -> bool:
        """Check if value is NaN (handles float, numpy, pandas)."""
        if value is None:
            return False
        try:
            return self._math.isnan(float(value))
        except (TypeError, ValueError):
            return False

    def _safe_float(self, value) -> Optional[float]:
        """Convert to float, returning None for NaN or invalid values."""
        if value is None:
            return None
        try:
            f = float(value)
            if self._math.isnan(f) or self._math.isinf(f):
                return None
            return f
        except (TypeError, ValueError):
            return None

    def _safe_string(self, value) -> Optional[str]:
        """Sanitize string for JSON compatibility.

        Removes control characters that break JSON parsing and ensures
        proper encoding for BigQuery load_table_from_json.
        """
        if value is None:
            return None
        try:
            s = str(value)
            # Remove ALL control characters including tab/newline
            # BigQuery load_table_from_json can't handle these in strings
            s = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', s)
            # Also remove any backslash-quote sequences that might cause issues
            s = s.replace('\\"', '"').replace('\\', '')
            # Remove any stray quotes that could break JSON
            s = s.replace('"', "'")
            # Limit length to prevent oversized values
            return s[:500] if len(s) > 500 else s
        except (TypeError, ValueError):
            return None

    def _compute_quality_tier(self, quality_score: Optional[float]) -> Optional[str]:
        """
        Compute quality tier from feature_quality_score.

        Session 125 analysis shows significant hit rate differences by tier:
        - High (80+): 60.6% hit rate
        - Medium (70-80): 39.1% hit rate
        - Low (<70): Very poor performance

        Args:
            quality_score: Feature quality score (0-100)

        Returns:
            Quality tier string: 'HIGH', 'MEDIUM', 'LOW', or None
        """
        if quality_score is None:
            return None
        try:
            score = float(quality_score)
            if score >= 80:
                return 'HIGH'
            elif score >= 70:
                return 'MEDIUM'
            else:
                return 'LOW'
        except (TypeError, ValueError):
            return None

    def load_injury_status_for_date(self, game_date: date) -> Dict[str, Dict]:
        """
        Load injury status for all players on a game date.

        Returns dict mapping player_lookup -> {
            'injury_status': 'OUT', 'DOUBTFUL', 'QUESTIONABLE', etc.
            'reason': injury reason text
        }

        Uses the latest report for each player on the game date.
        """
        query = f"""
        SELECT
            player_lookup,
            injury_status,
            reason
        FROM (
            SELECT
                player_lookup,
                UPPER(injury_status) as injury_status,
                reason,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_id
                    ORDER BY report_date DESC, report_hour DESC
                ) as rn
            FROM `{self.injury_table}`
            WHERE game_date = '{game_date}'
        )
        WHERE rn = 1
        """

        try:
            with ErrorContext(
                "load_injury_status",
                game_date=str(game_date),
                table=self.injury_table
            ):
                result = self.bq_client.query(query).to_dataframe()
                injury_map = {}
                for _, row in result.iterrows():
                    injury_map[row['player_lookup']] = {
                        'injury_status': row['injury_status'],
                        'reason': row['reason']
                    }
                logger.info(f"  Loaded {len(injury_map)} injury reports for {game_date}")
                return injury_map
        except (gcp_exceptions.BadRequest, gcp_exceptions.NotFound,
                gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded,
                GoogleCloudError) as e:
            # Error already logged by ErrorContext with structured fields
            return {}
        except Exception as e:
            # Error already logged by ErrorContext with structured fields
            return {}

    def get_injury_status(self, player_lookup: str, game_date: date) -> Optional[Dict]:
        """
        Get injury status for a player on a game date.

        Returns:
            Dict with 'injury_status' and 'reason', or None if no injury report
        """
        cache_key = game_date.isoformat()
        if cache_key not in self._injury_cache:
            self._injury_cache[cache_key] = self.load_injury_status_for_date(game_date)

        return self._injury_cache.get(cache_key, {}).get(player_lookup)

    def detect_dnp_voiding(
        self,
        actual_points: Optional[int],
        minutes_played: Optional[float],
        player_lookup: str,
        game_date: date,
        is_dnp: bool = False,
        captured_injury_status: Optional[str] = None,
        captured_injury_flag: Optional[bool] = None,
        captured_injury_reason: Optional[str] = None
    ) -> Dict:
        """
        Detect if a prediction should be voided due to DNP (Did Not Play).

        Like sportsbooks, we void bets when a player doesn't play.
        This prevents DNP games from counting against prediction accuracy.

        Session 212: Updated to accept is_dnp flag directly and handle actual_points = None.

        Args:
            actual_points: Points scored (0 for DNP, None if DNP with no boxscore)
            minutes_played: Minutes played (0 or None for DNP)
            player_lookup: Player identifier
            game_date: Game date for injury lookup
            is_dnp: DNP flag from player_game_summary (Session 212)
            captured_injury_status: Injury status captured at prediction time (v3.4)
            captured_injury_flag: Injury flag captured at prediction time (v3.4)
            captured_injury_reason: Injury reason captured at prediction time (v3.4)

        Returns:
            Dict with voiding fields:
            - is_voided: True if should be excluded from accuracy metrics
            - void_reason: 'dnp_injury_confirmed', 'dnp_late_scratch', 'dnp_unknown'
            - pre_game_injury_flag: True if injury was known pre-game
            - pre_game_injury_status: The injury status if flagged
            - injury_confirmed_postgame: True if DNP matched a pre-game injury flag
        """
        # Default: not voided
        result = {
            'is_voided': False,
            'void_reason': None,
            'pre_game_injury_flag': False,
            'pre_game_injury_status': None,
            'injury_confirmed_postgame': False
        }

        # Session 212: Check for DNP using is_dnp flag (preferred) or infer from points/minutes
        # DNP if: explicit is_dnp flag OR (0 points AND no minutes) OR (None points - missing boxscore)
        dnp_detected = (
            is_dnp or
            (actual_points == 0 and (minutes_played is None or minutes_played == 0)) or
            actual_points is None
        )

        if not dnp_detected:
            return result

        # Player DNP'd - determine injury status
        result['is_voided'] = True

        # v3.4: Use captured injury status if available (more accurate - what we knew at prediction time)
        # Otherwise fall back to retroactive lookup for historical predictions
        if captured_injury_status is not None or captured_injury_flag is not None:
            # Use captured status from prediction time
            injury_status = captured_injury_status.upper() if captured_injury_status else None
            had_injury_flag = captured_injury_flag or False

            result['pre_game_injury_status'] = injury_status

            if had_injury_flag:
                result['pre_game_injury_flag'] = True
                if injury_status in ('OUT', 'DOUBTFUL'):
                    # Expected void - injury was flagged pre-game
                    result['void_reason'] = 'dnp_injury_confirmed'
                    result['injury_confirmed_postgame'] = True
                elif injury_status in ('QUESTIONABLE', 'PROBABLE'):
                    # Player was questionable but ended up not playing
                    result['void_reason'] = 'dnp_late_scratch'
                    result['injury_confirmed_postgame'] = True
                else:
                    # Had a flag but unknown status
                    result['void_reason'] = 'dnp_unknown'
                    result['injury_confirmed_postgame'] = False
            else:
                # No injury flag at prediction time - this is a surprise DNP
                result['void_reason'] = 'dnp_unknown'
                result['injury_confirmed_postgame'] = False
        else:
            # Fall back to retroactive lookup (for historical predictions without captured status)
            injury_info = self.get_injury_status(player_lookup, game_date)

            if injury_info:
                injury_status = injury_info.get('injury_status', '').upper()
                result['pre_game_injury_status'] = injury_status

                if injury_status in ('OUT', 'DOUBTFUL'):
                    # Injury was flagged pre-game (based on retroactive lookup)
                    result['void_reason'] = 'dnp_injury_confirmed'
                    result['pre_game_injury_flag'] = True
                    result['injury_confirmed_postgame'] = True
                elif injury_status in ('QUESTIONABLE', 'PROBABLE'):
                    # Player was questionable but ended up not playing
                    result['void_reason'] = 'dnp_late_scratch'
                    result['pre_game_injury_flag'] = True
                    result['injury_confirmed_postgame'] = True
                else:
                    # Injury report exists but status was available/unknown
                    result['void_reason'] = 'dnp_unknown'
                    result['injury_confirmed_postgame'] = False
            else:
                # No injury report - unexpected DNP (late scratch, coach decision, etc.)
                result['void_reason'] = 'dnp_unknown'

        return result

    def get_predictions_for_date(self, game_date: date) -> List[Dict]:
        """
        Load all predictions for a specific game date (with deduplication).

        Returns predictions from all 5 systems:
        - moving_average_baseline_v1
        - zone_matchup_v1
        - similarity_balanced_v1
        - xgboost_v1
        - ensemble_v1

        v5.0: Added deduplication to handle duplicate predictions in source table.
        Uses ROW_NUMBER to keep only the latest prediction per business key
        (player_lookup, game_id, system_id, line_value).
        """
        query = f"""
        WITH predictions_raw AS (
            SELECT
                player_lookup,
                game_id,
                game_date,
                system_id,
                predicted_points,
                confidence_score,
                recommendation,
                current_points_line as line_value,
                pace_adjustment,
                similar_games_count as similarity_sample_size,
                model_version,
                -- Line source tracking (for no-line player analysis)
                COALESCE(has_prop_line, TRUE) as has_prop_line,
                COALESCE(line_source, 'ACTUAL_PROP') as line_source,
                estimated_line_value,
                -- Confidence tier filtering (v3.4 - shadow tracking)
                COALESCE(is_actionable, TRUE) as is_actionable,
                filter_reason,
                -- v3.4: Pre-game injury tracking (captured at prediction time)
                injury_status_at_prediction,
                injury_flag_at_prediction,
                injury_reason_at_prediction,
                injury_checked_at,
                -- v3.5: Invalidation tracking (for postponed/cancelled games)
                invalidation_reason,
                created_at
            FROM `{self.predictions_table}`
            WHERE game_date = '{game_date}'
                -- v3.10: Only grade active predictions (exclude deactivated duplicates)
                AND is_active = TRUE
                -- PHASE 1 FIX: Exclude placeholder lines from grading
                -- v3.8: Added BETTINGPROS as valid line source (fallback when odds_api unavailable)
                -- v4.1 FIX: Removed has_prop_line filter - line_source is authoritative
                -- v5.2: Include NO_PROP_LINE for MAE grading (predicted vs actual points)
                -- Hit rate grading still requires a line (prediction_correct = NULL for NO_PROP_LINE)
                AND (
                    (line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS') AND current_points_line IS NOT NULL AND current_points_line != 20.0)
                    OR line_source = 'NO_PROP_LINE'
                )
                -- v3.5: Skip invalidated predictions (postponed/cancelled games)
                -- These predictions should not be graded as they would skew accuracy metrics
                AND invalidation_reason IS NULL
        ),
        -- v5.0: Deduplicate by business key, keeping the latest prediction
        -- v5.1: Cast line_value to STRING for partitioning (FLOAT64 not allowed)
        deduped AS (
            SELECT * EXCEPT(rn) FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_lookup, game_id, system_id, CAST(line_value AS STRING)
                        ORDER BY created_at DESC
                    ) as rn
                FROM predictions_raw
            )
            WHERE rn = 1
        )
        SELECT * EXCEPT(created_at) FROM deduped
        """

        try:
            with ErrorContext(
                "load_predictions_for_grading",
                game_date=str(game_date),
                table=self.predictions_table
            ):
                result = self.bq_client.query(query).to_dataframe()
                return result.to_dict('records')
        except (gcp_exceptions.BadRequest, gcp_exceptions.NotFound,
                gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded,
                GoogleCloudError) as e:
            # Error already logged by ErrorContext with structured fields
            return []
        except Exception as e:
            # Error already logged by ErrorContext with structured fields
            return []

    def get_actuals_for_date(self, game_date: date) -> Dict[str, Dict]:
        """
        Load actual game data for all players on a game date.

        Returns dict mapping player_lookup -> {actual_points, team_abbr, opponent_team_abbr, minutes_played, is_dnp}
        """
        query = f"""
        SELECT
            player_lookup,
            points as actual_points,
            team_abbr,
            opponent_team_abbr,
            minutes_played,
            is_dnp
        FROM `{self.actuals_table}`
        WHERE game_date = '{game_date}'
        """

        try:
            with ErrorContext(
                "load_actuals_for_grading",
                game_date=str(game_date),
                table=self.actuals_table
            ):
                result = self.bq_client.query(query).to_dataframe()
                # Return dict of dicts with all player context
                # Note: Use pd.notna() to handle both None and pandas NAType
                return {
                    row['player_lookup']: {
                        'actual_points': int(row['actual_points']) if pd.notna(row['actual_points']) else None,
                        'team_abbr': row['team_abbr'] if pd.notna(row['team_abbr']) else None,
                        'opponent_team_abbr': row['opponent_team_abbr'] if pd.notna(row['opponent_team_abbr']) else None,
                        'minutes_played': self._safe_float(row['minutes_played']),
                        'is_dnp': bool(row['is_dnp']) if pd.notna(row['is_dnp']) else False
                    }
                    for _, row in result.iterrows()
                }
        except (gcp_exceptions.BadRequest, gcp_exceptions.NotFound,
                gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded,
                GoogleCloudError, KeyError, TypeError, ValueError) as e:
            # Error already logged by ErrorContext with structured fields
            return {}
        except Exception as e:
            # Error already logged by ErrorContext with structured fields
            return {}

    def compute_prediction_correct(
        self,
        recommendation: str,
        line_value: Optional[float],
        actual_points: int
    ) -> Optional[bool]:
        """
        Determine if OVER/UNDER recommendation was correct.

        Args:
            recommendation: 'OVER', 'UNDER', 'PASS', 'HOLD', or 'NO_LINE'
            line_value: The betting line
            actual_points: Actual points scored

        Returns:
            True if correct, False if wrong, None if can't be evaluated
            (PASS/HOLD/NO_LINE recommendations or missing line)
        """
        # Can't evaluate PASS, HOLD, or NO_LINE recommendations
        # NO_LINE means there was no real prop line - can't evaluate betting performance
        if recommendation in ('PASS', 'HOLD', 'NO_LINE', None):
            return None

        # Need a line to evaluate against
        if line_value is None:
            return None

        # Exactly hitting the line is a push (neither correct nor incorrect)
        if actual_points == line_value:
            return None

        went_over = actual_points > line_value
        recommended_over = recommendation == 'OVER'

        return bool(went_over == recommended_over)  # Ensure Python bool

    def compute_confidence_decile(self, confidence_score: Optional[float]) -> Optional[int]:
        """
        Compute confidence decile (1-10) for calibration curves.

        Args:
            confidence_score: 0.0-1.0 confidence value

        Returns:
            Integer 1-10 representing the decile bucket, or None if no score
        """
        if confidence_score is None:
            return None
        # Bucket: 0.00-0.09 → 1, 0.10-0.19 → 2, ..., 0.90-1.00 → 10
        return min(10, int(float(confidence_score) * 10) + 1)

    def grade_prediction(
        self,
        prediction: Dict,
        actual_data: Dict,
        game_date: date
    ) -> Dict:
        """
        Grade a single prediction against actual results.

        Args:
            prediction: Dict with predicted_points, confidence_score, etc.
            actual_data: Dict with actual_points, team_abbr, opponent_team_abbr, minutes_played
            game_date: Game date for injury lookup

        Returns:
            Dict ready for insertion into prediction_accuracy table
        """
        actual_points = actual_data.get('actual_points')  # Session 212: Can be None for DNP
        predicted_points = prediction.get('predicted_points')
        line_value = prediction.get('line_value')
        recommendation = prediction.get('recommendation')
        confidence_score = prediction.get('confidence_score')
        minutes_played = actual_data.get('minutes_played')
        is_dnp = actual_data.get('is_dnp', False)  # Session 212: Get DNP flag
        player_lookup = prediction['player_lookup']

        # v3.4: Get captured injury status from prediction (if available)
        captured_injury_status = prediction.get('injury_status_at_prediction')
        captured_injury_flag = prediction.get('injury_flag_at_prediction')
        captured_injury_reason = prediction.get('injury_reason_at_prediction')

        # Detect DNP voiding (v4) - uses captured injury status if available
        # Session 212: Pass is_dnp flag and handle actual_points = None
        voiding_info = self.detect_dnp_voiding(
            actual_points=actual_points,
            minutes_played=minutes_played,
            player_lookup=player_lookup,
            game_date=game_date,
            is_dnp=is_dnp,
            captured_injury_status=captured_injury_status,
            captured_injury_flag=captured_injury_flag,
            captured_injury_reason=captured_injury_reason
        )

        # Compute errors
        if predicted_points is not None and actual_points is not None:
            absolute_error = abs(float(predicted_points) - int(actual_points))
            signed_error = float(predicted_points) - int(actual_points)  # positive = over-predicted
            within_3 = bool(absolute_error <= 3.0)  # Ensure Python bool, not numpy bool
            within_5 = bool(absolute_error <= 5.0)
        else:
            absolute_error = None
            signed_error = None
            within_3 = None
            within_5 = None

        # Compute margins
        if predicted_points is not None and line_value is not None:
            predicted_margin = predicted_points - line_value
        else:
            predicted_margin = None

        if line_value is not None and actual_points is not None:
            actual_margin = actual_points - line_value
        else:
            actual_margin = None

        # Evaluate recommendation correctness
        # v4.1: If voided (DNP), don't calculate prediction_correct - treat like sportsbook void
        # Also skip if actual_points is None (missing data)
        if voiding_info['is_voided'] or actual_points is None:
            prediction_correct = None
        else:
            prediction_correct = self.compute_prediction_correct(
                recommendation, line_value, actual_points
            )

        # Helper to round floats for BigQuery NUMERIC compatibility
        def round_numeric(val, decimals=4):
            if val is None:
                return None
            return round(float(val), decimals)

        # Normalize confidence_score to 0-1 range
        # CatBoost V8 uses 0-100 percentage format, other systems use 0-1
        normalized_confidence = confidence_score
        if confidence_score is not None and confidence_score > 1:
            normalized_confidence = confidence_score / 100.0

        return {
            'player_lookup': self._safe_string(prediction['player_lookup']),
            'game_id': self._safe_string(prediction['game_id']),
            'game_date': prediction['game_date'].isoformat() if hasattr(prediction['game_date'], 'isoformat') else str(prediction['game_date']),
            'system_id': self._safe_string(prediction['system_id']),

            # Team context (new in v3)
            'team_abbr': self._safe_string(actual_data.get('team_abbr')),
            'opponent_team_abbr': self._safe_string(actual_data.get('opponent_team_abbr')),

            # Prediction snapshot - round for NUMERIC compatibility
            'predicted_points': round_numeric(predicted_points, 2),
            'confidence_score': round_numeric(normalized_confidence, 4),  # Normalized to 0-1 range
            'confidence_decile': self.compute_confidence_decile(normalized_confidence),  # new in v3
            'recommendation': self._safe_string(recommendation),
            'line_value': round_numeric(line_value, 2),

            # Feature inputs (for ML analysis)
            'referee_adjustment': None,  # Not stored in predictions table
            'pace_adjustment': round_numeric(self._safe_float(prediction.get('pace_adjustment')), 4),
            'similarity_sample_size': int(prediction.get('similarity_sample_size')) if prediction.get('similarity_sample_size') is not None and not self._is_nan(prediction.get('similarity_sample_size')) else None,

            # Actual result
            'actual_points': int(actual_points) if actual_points is not None else None,
            'minutes_played': self._safe_float(actual_data.get('minutes_played')),  # new in v3

            # Core accuracy metrics - round for NUMERIC compatibility
            'absolute_error': round_numeric(absolute_error, 2),
            'signed_error': round_numeric(signed_error, 2),
            'prediction_correct': prediction_correct,

            # Margin analysis - round for NUMERIC compatibility
            'predicted_margin': round_numeric(predicted_margin, 2),
            'actual_margin': round_numeric(actual_margin, 2),

            # Threshold accuracy
            'within_3_points': within_3,
            'within_5_points': within_5,

            # Line source tracking (for no-line player analysis)
            # Enables segmented accuracy analysis by whether player had real betting line
            'has_prop_line': bool(prediction.get('has_prop_line', True)),
            'line_source': self._safe_string(prediction.get('line_source', 'ACTUAL_PROP')),
            'estimated_line_value': round_numeric(self._safe_float(prediction.get('estimated_line_value')), 1),

            # Bookmaker tracking (Session 60 - for per-bookmaker hit rate analysis)
            'line_bookmaker': self._safe_string(prediction.get('sportsbook')),
            'line_source_api': self._safe_string(prediction.get('line_source_api')),

            # Confidence tier filtering (v3.4 - shadow tracking)
            # Enables tracking of filtered picks' actual performance
            'is_actionable': bool(prediction.get('is_actionable', True)),
            'filter_reason': self._safe_string(prediction.get('filter_reason')),

            # Data quality tracking (Session 125 - enables hit rate by quality analysis)
            # High quality (80+) has 60.6% hit rate vs Medium (70-80) at 39.1%
            'feature_quality_score': round_numeric(self._safe_float(prediction.get('feature_quality_score')), 2),
            'data_quality_tier': self._compute_quality_tier(prediction.get('feature_quality_score')),

            # DNP/Injury Voiding (v4) - Treat DNP like sportsbook voided bets
            'is_voided': voiding_info['is_voided'],
            'void_reason': voiding_info['void_reason'],
            'pre_game_injury_flag': voiding_info['pre_game_injury_flag'],
            'pre_game_injury_status': voiding_info['pre_game_injury_status'],
            'injury_confirmed_postgame': voiding_info['injury_confirmed_postgame'],

            # Metadata
            'model_version': self._safe_string(prediction.get('model_version')),
            'graded_at': datetime.now(timezone.utc).isoformat()
        }

    def _sanitize_record(self, record: Dict) -> Dict:
        """Sanitize a single record for JSON compatibility.

        Handles NaN, Inf, and other non-JSON-serializable values.
        """
        sanitized = {}
        for key, value in record.items():
            if value is None:
                sanitized[key] = None
            elif isinstance(value, float):
                if self._math.isnan(value) or self._math.isinf(value):
                    sanitized[key] = None
                else:
                    sanitized[key] = value
            elif isinstance(value, bool):
                sanitized[key] = value  # Keep as bool, not int
            elif isinstance(value, (int, str)):
                sanitized[key] = value
            else:
                # Try to convert to string for safety
                try:
                    sanitized[key] = str(value)
                except Exception as e:
                    logger.debug(f"Failed to convert {key}={value} to string: {e}")
                    sanitized[key] = None
        return sanitized

    def _check_for_duplicates(self, game_date: date) -> int:
        """
        Check for duplicate business keys after grading (SESSION 94 FIX).

        Business key: (player_lookup, game_id, system_id, line_value)

        Args:
            game_date: Date to check for duplicates

        Returns:
            Number of duplicate business keys found
        """
        game_date_str = game_date.isoformat()

        validation_query = f"""
        SELECT COUNT(*) as duplicate_count
        FROM (
            SELECT
                player_lookup,
                game_id,
                system_id,
                line_value,
                COUNT(*) as occurrence_count
            FROM `{self.accuracy_table}`
            WHERE game_date = '{game_date}'
            GROUP BY player_lookup, game_id, system_id, line_value
            HAVING COUNT(*) > 1
        )
        """

        try:
            query_job = self.bq_client.query(validation_query)
            result = query_job.result(timeout=30)
            row = next(iter(result), None)
            duplicate_count = row.duplicate_count if row else 0

            if duplicate_count > 0:
                # Get details for investigation
                logger.error(f"  ❌ DUPLICATE DETECTION: Found {duplicate_count} duplicate business keys for {game_date}")

                details_query = f"""
                SELECT
                    player_lookup,
                    game_id,
                    system_id,
                    line_value,
                    COUNT(*) as count,
                    ARRAY_AGG(graded_at ORDER BY graded_at) as graded_timestamps
                FROM `{self.accuracy_table}`
                WHERE game_date = '{game_date}'
                GROUP BY player_lookup, game_id, system_id, line_value
                HAVING COUNT(*) > 1
                LIMIT 20
                """

                details_result = self.bq_client.query(details_query).result(timeout=30)
                logger.error(f"  Duplicate details for {game_date}:")
                for row in details_result:
                    logger.error(
                        f"    - {row.player_lookup} / {row.system_id} / "
                        f"line={row.line_value}: {row.count}x "
                        f"(timestamps: {row.graded_timestamps})"
                    )
            else:
                logger.info(f"  ✅ Validation passed: No duplicates for {game_date}")

            return duplicate_count

        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error checking for duplicates: {e}")
            return -1  # -1 = validation error
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found checking for duplicates: {e}")
            return -1
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable checking for duplicates: {e}")
            return -1
        except GoogleCloudError as e:
            logger.error(f"GCP error checking for duplicates: {e}")
            return -1
        except Exception as e:
            logger.error(f"Unexpected error checking for duplicates: {type(e).__name__}: {e}")
            # Don't fail grading if validation fails
            return -1  # -1 = validation error

    def _write_with_validation(
        self,
        graded_results: List[Dict],
        game_date: date
    ) -> int:
        """
        Internal method: DELETE + INSERT + VALIDATE (SESSION 94 FIX).

        This method is called INSIDE the lock context.

        Args:
            graded_results: Sanitized grading records
            game_date: Date being graded

        Returns:
            Number of rows written
        """
        game_date_str = game_date.isoformat()

        # Sanitize all records to ensure JSON compatibility
        sanitized_results = []
        for i, record in enumerate(graded_results):
            try:
                sanitized = self._sanitize_record(record)
                # Validate JSON serialization
                json.dumps(sanitized)
                sanitized_results.append(sanitized)
            except (TypeError, ValueError) as e:
                logger.warning(f"Skipping record {i} due to JSON error: {e}, player={record.get('player_lookup')}")
                continue

        if not sanitized_results:
            logger.error("No valid records after sanitization")
            return 0

        graded_results = sanitized_results

        try:
            # Use ErrorContext for structured error logging on critical write operation
            with ErrorContext(
                "write_graded_results",
                game_date=str(game_date),
                record_count=len(graded_results),
                table=self.accuracy_table,
                alert_on_failure=True  # Alert on grading write failures
            ):
                # STEP 1: DELETE existing records for this date
                delete_query = f"""
                DELETE FROM `{self.accuracy_table}`
                WHERE game_date = '{game_date}'
                """
                delete_job = self.bq_client.query(delete_query)
                delete_job.result(timeout=60)
                deleted_count = delete_job.num_dml_affected_rows or 0

                if deleted_count > 0:
                    logger.info(f"  Deleted {deleted_count} existing graded records for {game_date}")

                # STEP 2: INSERT new records using batch loading
                table_ref = self.bq_client.get_table(self.accuracy_table)
                job_config = bigquery.LoadJobConfig(
                    schema=table_ref.schema,
                    autodetect=False,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    ignore_unknown_values=True
                )

                load_job = self.bq_client.load_table_from_json(
                    graded_results,
                    self.accuracy_table,
                    job_config=job_config
                )
                load_job.result(timeout=60)

                if load_job.errors:
                    logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

                rows_written = load_job.output_rows or len(graded_results)

                # STEP 3: VALIDATE no duplicates created (Layer 2 defense)
                logger.info(f"  Running post-grading validation for {game_date}...")
                duplicate_count = self._check_for_duplicates(game_date)

                if duplicate_count > 0:
                    logger.error(
                        f"  VALIDATION FAILED: {duplicate_count} duplicate business keys detected "
                        f"for {game_date} despite distributed lock!"
                    )
                    # Don't raise exception - log and alert, but don't fail grading
                    # Alerting system will notify operators
                elif duplicate_count == 0:
                    logger.info(f"  Validation passed: No duplicates for {game_date}")

                return rows_written

        except (gcp_exceptions.BadRequest, gcp_exceptions.NotFound,
                gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded,
                gcp_exceptions.Conflict, GoogleCloudError, TypeError, ValueError) as e:
            # Error already logged by ErrorContext with structured fields
            return 0
        except Exception as e:
            # Error already logged by ErrorContext with structured fields
            return 0

    def write_graded_results(
        self,
        graded_results: List[Dict],
        game_date: date,
        use_lock: bool = True  # SESSION 94 FIX: Enable distributed locking by default
    ) -> int:
        """
        Write graded results to BigQuery with distributed locking (SESSION 94 FIX).

        Prevents race conditions that cause duplicates when multiple grading
        operations run concurrently for the same date.

        Args:
            graded_results: List of graded prediction dictionaries
            game_date: Date being graded
            use_lock: If True, acquire distributed lock (default: True)

        Returns:
            Number of rows written
        """
        if not graded_results:
            return 0

        # Sanitize all records to ensure JSON compatibility
        sanitized_results = []
        for i, record in enumerate(graded_results):
            try:
                sanitized = self._sanitize_record(record)
                # Validate JSON serialization
                json.dumps(sanitized)
                sanitized_results.append(sanitized)
            except (TypeError, ValueError) as e:
                logger.warning(f"Skipping record {i} due to JSON error: {e}, player={record.get('player_lookup')}")
                continue

        if not sanitized_results:
            logger.error("No valid records after sanitization")
            return 0

        graded_results = sanitized_results
        game_date_str = game_date.isoformat()

        # SESSION 94 FIX: Use distributed lock to prevent concurrent grading
        if use_lock:
            import time as time_module
            try:
                lock = DistributedLock(project_id=self.project_id, lock_type="grading")
                lock_key = f"grading_{game_date_str}"
                logger.info(f"Acquiring grading lock for game_date={game_date_str}")

                with lock.acquire(game_date=game_date_str, operation_id=f"grading_{game_date_str}"):
                    # Lock acquired - run grading inside locked context
                    logger.info(f"✅ Grading lock acquired for {game_date_str}")
                    operation_start = time_module.time()

                    result = self._write_with_validation(graded_results, game_date)

                    # Check if operation exceeded lock timeout (risk of lock expiration)
                    operation_duration = int(time_module.time() - operation_start)
                    if operation_duration > LOCK_TIMEOUT_SECONDS:
                        logger.warning(
                            f"⚠️  Grading operation exceeded lock timeout: {operation_duration}s > {LOCK_TIMEOUT_SECONDS}s"
                        )
                        # Send lock timeout alert (non-blocking)
                        _send_lock_timeout_alert_async(
                            game_date=game_date_str,
                            lock_key=lock_key,
                            elapsed_seconds=operation_duration
                        )

                    return result

            except LockAcquisitionError as e:
                # Failed to acquire lock after max retries
                error_msg = f"Cannot acquire grading lock for {game_date_str}: {e}"
                logger.error(error_msg)

                # Calculate lock acquisition details for alert
                lock_key = f"grading_{game_date_str}"
                max_wait_seconds = MAX_ACQUIRE_ATTEMPTS * RETRY_DELAY_SECONDS

                # Send Slack alert (non-blocking) for lock acquisition failure
                _send_lock_failure_alert_async(
                    game_date=game_date_str,
                    lock_key=lock_key,
                    retry_attempts=MAX_ACQUIRE_ATTEMPTS,
                    timeout_duration=max_wait_seconds,
                    error_message=str(e)
                )

                # Don't fail grading - try without lock (log warning)
                logger.warning(f"⚠️  Proceeding with grading WITHOUT lock for {game_date_str}")
                return self._write_with_validation(graded_results, game_date)

        else:
            # Testing mode or lock disabled - no lock
            logger.warning(f"Grading WITHOUT lock for {game_date_str} (use_lock=False)")
            return self._write_with_validation(graded_results, game_date)

    def process_date(self, game_date: date) -> Dict:
        """
        Grade all predictions for a specific date.

        Args:
            game_date: Date to process

        Returns:
            Dict with status and statistics
        """
        logger.info(f"Grading predictions for {game_date}")

        # Load predictions
        predictions = self.get_predictions_for_date(game_date)
        if not predictions:
            return {
                'status': 'no_predictions',
                'date': game_date.isoformat(),
                'predictions_found': 0,
                'graded': 0
            }

        # Load actual results
        actuals = self.get_actuals_for_date(game_date)
        if not actuals:
            return {
                'status': 'no_actuals',
                'date': game_date.isoformat(),
                'predictions_found': len(predictions),
                'graded': 0
            }

        # Grade each prediction
        graded_results = []
        missing_actuals = 0
        null_actuals = 0

        for pred in predictions:
            player_lookup = pred['player_lookup']
            actual_data = actuals.get(player_lookup)

            if actual_data is None:
                missing_actuals += 1
                continue

            # Session 212: Grade ALL predictions, even DNP (actual_points = None)
            # DNP predictions will be marked as is_voided=True by detect_dnp_voiding
            # This gives us complete audit trail like sportsbooks (void the bet, track it)
            if actual_data.get('actual_points') is None:
                null_actuals += 1
                # Continue grading - will be voided, but we want the record

            graded = self.grade_prediction(pred, actual_data, game_date)
            graded_results.append(graded)

        # Write to BigQuery (with distributed lock - SESSION 94 FIX)
        written = self.write_graded_results(graded_results, game_date)

        # Check for duplicates after grading (SESSION 94 FIX)
        duplicate_count = self._check_for_duplicates(game_date) if written > 0 else 0

        # Compute summary statistics
        if graded_results:
            # Overall stats (including voided)
            errors = [r['absolute_error'] for r in graded_results if r['absolute_error'] is not None]
            mae = sum(errors) / len(errors) if errors else None

            signed_errors = [r['signed_error'] for r in graded_results if r['signed_error'] is not None]
            bias = sum(signed_errors) / len(signed_errors) if signed_errors else None

            correct_count = sum(1 for r in graded_results if r['prediction_correct'] is True)
            incorrect_count = sum(1 for r in graded_results if r['prediction_correct'] is False)
            accuracy = correct_count / (correct_count + incorrect_count) if (correct_count + incorrect_count) > 0 else None

            # Voiding stats (v4)
            voided_count = sum(1 for r in graded_results if r.get('is_voided', False))
            voided_injury = sum(1 for r in graded_results if r.get('void_reason') == 'dnp_injury_confirmed')
            voided_scratch = sum(1 for r in graded_results if r.get('void_reason') == 'dnp_late_scratch')
            voided_unknown = sum(1 for r in graded_results if r.get('void_reason') == 'dnp_unknown')

            # Net accuracy (excluding voided) - this is the "real" accuracy like sportsbooks
            non_voided = [r for r in graded_results if not r.get('is_voided', False)]
            net_correct = sum(1 for r in non_voided if r['prediction_correct'] is True)
            net_incorrect = sum(1 for r in non_voided if r['prediction_correct'] is False)
            net_accuracy = net_correct / (net_correct + net_incorrect) if (net_correct + net_incorrect) > 0 else None

            if voided_count > 0:
                logger.info(f"  Voided {voided_count} predictions (injury: {voided_injury}, scratch: {voided_scratch}, unknown: {voided_unknown})")
        else:
            mae = None
            bias = None
            accuracy = None
            voided_count = 0
            voided_injury = 0
            voided_scratch = 0
            voided_unknown = 0
            net_accuracy = None

        return {
            'status': 'success' if written > 0 else 'failed',
            'date': game_date.isoformat(),
            'predictions_found': len(predictions),
            'actuals_found': len(actuals),
            'missing_actuals': missing_actuals,
            'graded': written,
            'mae': round(mae, 2) if mae is not None else None,
            'bias': round(bias, 2) if bias is not None else None,
            'recommendation_accuracy': round(accuracy * 100, 1) if accuracy is not None else None,
            # Voiding stats (v4)
            'voided_count': voided_count,
            'voided_injury': voided_injury,
            'voided_scratch': voided_scratch,
            'voided_unknown': voided_unknown,
            'net_accuracy': round(net_accuracy * 100, 1) if net_accuracy is not None else None,
            # SESSION 94 FIX: Return duplicate count for alerting
            'duplicate_count': duplicate_count
        }

    def check_predictions_exist(self, game_date: date) -> Dict:
        """Check if predictions exist for a date."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT player_lookup) as players,
            COUNT(DISTINCT system_id) as systems
        FROM `{self.predictions_table}`
        WHERE game_date = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            row = result.iloc[0]
            return {
                'exists': int(row['total']) > 0,
                'total_predictions': int(row['total']),
                'unique_players': int(row['players']),
                'systems': int(row['systems'])
            }
        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error checking predictions: {e}")
            return {'exists': False, 'error': str(e)}
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found checking predictions: {e}")
            return {'exists': False, 'error': str(e)}
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable checking predictions: {e}")
            return {'exists': False, 'error': str(e)}
        except GoogleCloudError as e:
            logger.error(f"GCP error checking predictions: {e}")
            return {'exists': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"Unexpected error checking predictions: {type(e).__name__}: {e}", exc_info=True)
            return {'exists': False, 'error': str(e)}

    def check_actuals_exist(self, game_date: date) -> Dict:
        """Check if actual results exist for a date."""
        query = f"""
        SELECT COUNT(*) as players
        FROM `{self.actuals_table}`
        WHERE game_date = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            count = int(result['players'].iloc[0])
            return {
                'exists': count > 0,
                'players': count
            }
        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error checking actuals: {e}")
            return {'exists': False, 'error': str(e)}
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found checking actuals: {e}")
            return {'exists': False, 'error': str(e)}
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable checking actuals: {e}")
            return {'exists': False, 'error': str(e)}
        except GoogleCloudError as e:
            logger.error(f"GCP error checking actuals: {e}")
            return {'exists': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"Unexpected error checking actuals: {type(e).__name__}: {e}", exc_info=True)
            return {'exists': False, 'error': str(e)}
