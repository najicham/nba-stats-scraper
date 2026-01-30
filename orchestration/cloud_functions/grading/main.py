"""
Phase 5B Grading Cloud Function

Grades predictions against actual game results.
Runs daily at 6 AM ET (after overnight games complete and box scores are ingested).

Trigger: Pub/Sub topic `nba-grading-trigger`

Message formats:
1. Daily grading (from Cloud Scheduler):
   {"target_date": "yesterday"}

2. Specific date (from backfill or manual trigger):
   {"target_date": "2025-12-13"}

3. With aggregation (run system daily performance after grading):
   {"target_date": "yesterday", "run_aggregation": true}

Processors run:
1. PredictionAccuracyProcessor - grades individual predictions
2. SystemDailyPerformanceProcessor (optional) - aggregates daily system performance

Publishes completion to: nba-grading-complete

Version: 1.0
Created: 2025-12-20
"""

import base64
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import functions_framework
from google.cloud import pubsub_v1

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# SESSION 97 FIX: Structured logging for lock events
class StructuredLogger:
    """
    Structured logger for Cloud Logging.

    Logs events in JSON format that Cloud Logging can parse and index.
    This makes lock events easily queryable in Cloud Console.
    """

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def log_lock_event(self, event_type: str, lock_type: str, game_date: str, details: Dict):
        """
        Log lock events in structured format for Cloud Logging.

        Args:
            event_type: 'lock_acquired', 'lock_waited', 'lock_timeout', 'lock_failed'
            lock_type: 'grading', 'daily_performance', 'performance_summary'
            game_date: Date being locked
            details: Additional event details (attempts, wait_time_ms, error, etc.)
        """
        entry = {
            'event_type': event_type,
            'lock_type': lock_type,
            'game_date': game_date,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'severity': 'INFO' if event_type == 'lock_acquired' else 'WARNING',
            **details
        }
        # Cloud Logging will parse this as structured entry
        self.logger.info(json.dumps(entry))


# Initialize structured logger
structured_logger = StructuredLogger('grading-function')

# Project configuration
# NOTE: Inline project_id logic to avoid shared module dependency in Cloud Functions
PROJECT_ID = (
    os.environ.get('GCP_PROJECT_ID') or
    os.environ.get('GCP_PROJECT') or
    'nba-props-platform'
)
GRADING_COMPLETE_TOPIC = 'nba-grading-complete'

# Lazy-loaded publisher
_publisher = None


def get_publisher():
    """Get or create Pub/Sub publisher."""
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def get_target_date(target_date_str: str) -> str:
    """
    Convert target_date string to actual date.

    Args:
        target_date_str: "today", "yesterday", or "YYYY-MM-DD"

    Returns:
        Date string in YYYY-MM-DD format
    """
    today = datetime.now(timezone.utc).date()

    if target_date_str == "today":
        return today.strftime('%Y-%m-%d')
    elif target_date_str == "yesterday":
        return (today - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        # Assume it's already a date string
        return target_date_str


def validate_grading_prerequisites(target_date: str) -> Dict:
    """
    Validate that prerequisites for grading are met.

    Checks:
    1. player_game_summary has data for the target date
    2. Predictions exist for the target date
    3. Sufficient coverage (actuals cover most predictions)

    Args:
        target_date: Date to validate (YYYY-MM-DD format)

    Returns:
        Dict with:
        - ready: bool - True if ready for grading
        - predictions_count: int
        - actuals_count: int
        - coverage_pct: float
        - missing_reason: str (if not ready)
        - can_auto_heal: bool
    """
    from google.cloud import bigquery
    from shared.clients.bigquery_pool import get_bigquery_client

    bq_client = get_bigquery_client(project_id=PROJECT_ID)

    # Check predictions
    predictions_query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{target_date}'
    """

    # Check actuals (player_game_summary)
    actuals_query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
    WHERE game_date = '{target_date}'
    """

    try:
        predictions_result = bq_client.query(predictions_query).to_dataframe()
        predictions_count = int(predictions_result.iloc[0]['cnt'])

        actuals_result = bq_client.query(actuals_query).to_dataframe()
        actuals_count = int(actuals_result.iloc[0]['cnt'])

        # Calculate coverage
        if predictions_count > 0:
            coverage_pct = (actuals_count / predictions_count) * 100
        else:
            coverage_pct = 0.0

        # Determine readiness
        if predictions_count == 0:
            return {
                'ready': False,
                'predictions_count': 0,
                'actuals_count': actuals_count,
                'coverage_pct': 0.0,
                'missing_reason': 'no_predictions',
                'can_auto_heal': False
            }

        if actuals_count == 0:
            return {
                'ready': False,
                'predictions_count': predictions_count,
                'actuals_count': 0,
                'coverage_pct': 0.0,
                'missing_reason': 'no_actuals',
                'can_auto_heal': True  # Can trigger Phase 3 analytics
            }

        # Low coverage warning (but still proceed)
        min_coverage = 50.0  # At least 50% coverage required
        if coverage_pct < min_coverage:
            logger.warning(
                f"Low actuals coverage for {target_date}: {coverage_pct:.1f}% "
                f"({actuals_count} actuals / {predictions_count} predictions)"
            )

        return {
            'ready': True,
            'predictions_count': predictions_count,
            'actuals_count': actuals_count,
            'coverage_pct': round(coverage_pct, 1),
            'missing_reason': None,
            'can_auto_heal': False
        }

    except Exception as e:
        logger.error(f"Error validating grading prerequisites: {e}", exc_info=True)
        return {
            'ready': False,
            'predictions_count': 0,
            'actuals_count': 0,
            'coverage_pct': 0.0,
            'missing_reason': f'validation_error: {str(e)}',
            'can_auto_heal': False
        }


def get_auth_token(audience: str) -> str:
    """
    Get identity token for authenticated service calls using GCP metadata server.

    This works in Cloud Run/Cloud Functions environments where the metadata
    server is available to provide identity tokens for the service account.

    Args:
        audience: The target service URL to authenticate to

    Returns:
        Identity token string

    Raises:
        Exception: If token cannot be obtained
    """
    import urllib.request

    # Use the GCP metadata server to get identity token
    metadata_url = (
        f"http://metadata.google.internal/computeMetadata/v1/"
        f"instance/service-accounts/default/identity?audience={audience}"
    )
    req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to get auth token for {audience}: {e}", exc_info=True)
        raise


def check_phase3_health() -> Dict:
    """
    Check Phase 3 analytics service health before triggering.

    Returns:
        Dict with:
        - healthy: bool - True if service is responding
        - status_code: int - HTTP status code
        - response_time_ms: float - Response time in milliseconds
        - error: str - Error message if unhealthy
    """
    import requests

    PHASE3_BASE_URL = "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
    HEALTH_ENDPOINT = f"{PHASE3_BASE_URL}/health"

    start_time = time.time()

    try:
        # SESSION 18 FIX: Try with authentication first, fall back to unauthenticated
        # Cloud Run services may require auth even for health endpoints
        headers = {}
        try:
            token = get_auth_token(PHASE3_BASE_URL)
            headers = {"Authorization": f"Bearer {token}"}
            logger.info("Health check: Using authenticated request")
        except Exception as auth_error:
            logger.warning(f"Health check: Could not get auth token, trying unauthenticated: {auth_error}")

        response = requests.get(HEALTH_ENDPOINT, headers=headers, timeout=10)
        response_time_ms = (time.time() - start_time) * 1000

        if response.status_code == 200:
            logger.info(f"Phase 3 health check passed: {response_time_ms:.0f}ms")
            return {
                'healthy': True,
                'status_code': 200,
                'response_time_ms': round(response_time_ms, 1),
                'error': None
            }
        elif response.status_code in (401, 403):
            # Auth failed - log but try to proceed anyway (trigger has its own auth)
            logger.warning(
                f"Phase 3 health check returned {response.status_code} (auth issue) - "
                f"will attempt trigger anyway with fresh auth token"
            )
            return {
                'healthy': True,  # Assume healthy, let trigger attempt with fresh token
                'status_code': response.status_code,
                'response_time_ms': round(response_time_ms, 1),
                'error': None,
                'auth_issue': True
            }
        else:
            logger.warning(f"Phase 3 health check returned {response.status_code}")
            return {
                'healthy': False,
                'status_code': response.status_code,
                'response_time_ms': round(response_time_ms, 1),
                'error': f"HTTP {response.status_code}"
            }

    except requests.exceptions.Timeout:
        logger.error("Phase 3 health check timed out", exc_info=True)
        return {
            'healthy': False,
            'status_code': None,
            'response_time_ms': None,
            'error': 'Health check timeout'
        }
    except Exception as e:
        logger.error(f"Phase 3 health check failed: {e}", exc_info=True)
        return {
            'healthy': False,
            'status_code': None,
            'response_time_ms': None,
            'error': str(e)
        }


def trigger_phase3_analytics(target_date: str, max_retries: int = 3) -> Dict:
    """
    Trigger Phase 3 analytics to generate player_game_summary for a date.

    This is the auto-heal mechanism when grading finds no actuals.
    Includes retry logic for 503 errors and health checking.

    Args:
        target_date: Date to process (YYYY-MM-DD format)
        max_retries: Maximum retry attempts for 503 errors (default: 3)

    Returns:
        Dict with:
        - success: bool - True if trigger was successful
        - status_code: int - HTTP status code
        - error: str - Error message if failed
        - retries: int - Number of retries attempted
    """
    import requests

    PHASE3_BASE_URL = "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
    PHASE3_ENDPOINT = f"{PHASE3_BASE_URL}/process-date-range"

    logger.info(f"Auto-heal: Triggering Phase 3 analytics for {target_date}")

    # Step 1: Check Phase 3 service health first
    health = check_phase3_health()
    if not health['healthy']:
        structured_logger.log_lock_event(
            event_type='phase3_trigger_failed',
            lock_type='auto_heal',
            game_date=target_date,
            details={
                'reason': 'service_unhealthy',
                'error': health['error']
            }
        )
        logger.error(f"Auto-heal: Phase 3 service unhealthy, skipping trigger: {health['error']}", exc_info=True)
        return {
            'success': False,
            'status_code': health.get('status_code'),
            'error': f"Service unhealthy: {health['error']}",
            'retries': 0
        }

    # Step 2: Get authentication token
    try:
        token = get_auth_token(PHASE3_BASE_URL)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        logger.info("Auto-heal: Successfully obtained auth token for Phase 3")
    except Exception as e:
        logger.warning(f"Auto-heal: Could not get auth token, trying without auth: {e}")
        headers = {"Content-Type": "application/json"}

    # Step 3: Trigger with retry logic for 503 errors
    retry_count = 0
    last_error = None
    backoff_seconds = 5  # Start with 5 second backoff

    while retry_count <= max_retries:
        try:
            logger.info(f"Auto-heal: Triggering Phase 3 (attempt {retry_count + 1}/{max_retries + 1})")

            response = requests.post(
                PHASE3_ENDPOINT,
                json={
                    "start_date": target_date,
                    "end_date": target_date,
                    "processors": ["PlayerGameSummaryProcessor"],
                    "backfill_mode": True
                },
                headers=headers,
                timeout=60  # Reduced timeout to 60s (was 300s)
            )

            if response.status_code == 200:
                structured_logger.log_lock_event(
                    event_type='phase3_trigger_success',
                    lock_type='auto_heal',
                    game_date=target_date,
                    details={
                        'retries': retry_count,
                        'response_time_ms': health.get('response_time_ms')
                    }
                )
                logger.info(f"Auto-heal: Phase 3 analytics triggered successfully for {target_date} after {retry_count} retries")
                return {
                    'success': True,
                    'status_code': 200,
                    'error': None,
                    'retries': retry_count
                }

            elif response.status_code == 503:
                # Service unavailable - retry with exponential backoff
                last_error = f"503 Service Unavailable: {response.text}"
                logger.warning(f"Auto-heal: Phase 3 returned 503 (attempt {retry_count + 1}/{max_retries + 1})")

                if retry_count < max_retries:
                    logger.info(f"Auto-heal: Retrying in {backoff_seconds}s...")
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2  # Exponential backoff: 5s, 10s, 20s
                    retry_count += 1
                else:
                    # Max retries exceeded
                    structured_logger.log_lock_event(
                        event_type='phase3_trigger_failed',
                        lock_type='auto_heal',
                        game_date=target_date,
                        details={
                            'reason': '503_max_retries_exceeded',
                            'retries': retry_count,
                            'error': last_error
                        }
                    )
                    logger.error(f"Auto-heal: Phase 3 trigger failed after {max_retries + 1} attempts: {last_error}", exc_info=True)
                    return {
                        'success': False,
                        'status_code': 503,
                        'error': f"503 after {retry_count} retries: {last_error}",
                        'retries': retry_count
                    }

            else:
                # Other HTTP error - don't retry
                last_error = f"HTTP {response.status_code}: {response.text}"
                structured_logger.log_lock_event(
                    event_type='phase3_trigger_failed',
                    lock_type='auto_heal',
                    game_date=target_date,
                    details={
                        'reason': f'http_{response.status_code}',
                        'error': last_error,
                        'retries': retry_count
                    }
                )
                logger.error(f"Auto-heal: Phase 3 trigger failed with {response.status_code}: {response.text}", exc_info=True)
                return {
                    'success': False,
                    'status_code': response.status_code,
                    'error': last_error,
                    'retries': retry_count
                }

        except requests.exceptions.Timeout:
            last_error = "Request timeout (60s)"
            logger.warning(f"Auto-heal: Phase 3 request timed out (attempt {retry_count + 1}/{max_retries + 1})")

            if retry_count < max_retries:
                logger.info(f"Auto-heal: Retrying after timeout in {backoff_seconds}s...")
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                retry_count += 1
            else:
                structured_logger.log_lock_event(
                    event_type='phase3_trigger_failed',
                    lock_type='auto_heal',
                    game_date=target_date,
                    details={
                        'reason': 'timeout_max_retries_exceeded',
                        'retries': retry_count,
                        'error': last_error
                    }
                )
                logger.error(f"Auto-heal: Phase 3 trigger timed out after {max_retries + 1} attempts", exc_info=True)
                return {
                    'success': False,
                    'status_code': None,
                    'error': f"Timeout after {retry_count} retries",
                    'retries': retry_count
                }

        except Exception as e:
            last_error = str(e)
            structured_logger.log_lock_event(
                event_type='phase3_trigger_failed',
                lock_type='auto_heal',
                game_date=target_date,
                details={
                    'reason': 'exception',
                    'error': last_error,
                    'retries': retry_count
                }
            )
            logger.error(f"Auto-heal: Error triggering Phase 3 analytics: {e}", exc_info=True)
            return {
                'success': False,
                'status_code': None,
                'error': f"Exception: {last_error}",
                'retries': retry_count
            }

    # Should never reach here
    return {
        'success': False,
        'status_code': None,
        'error': 'Unexpected retry loop exit',
        'retries': retry_count
    }


def run_post_grading_validation(target_date: str) -> Dict:
    """
    Run validation checks after grading completes.

    Validates:
    1. DNP voiding - no incorrectly graded DNP predictions
    2. Placeholder lines - no graded placeholder lines

    Args:
        target_date: Date that was graded (YYYY-MM-DD format)

    Returns:
        Dict with validation results
    """
    from datetime import date as date_type

    try:
        # Parse date
        year, month, day = map(int, target_date.split('-'))
        game_date = date_type(year, month, day)

        # Import validation functions
        from shared.validation.prediction_quality_validator import (
            check_dnp_voiding,
            check_placeholder_lines,
            CheckStatus,
        )
        from google.cloud import bigquery

        bq_client = bigquery.Client(project=PROJECT_ID)

        # Run DNP voiding check for just this date
        dnp_result = check_dnp_voiding(bq_client, game_date, game_date)
        placeholder_result = check_placeholder_lines(bq_client, game_date, game_date)

        validation_passed = (
            dnp_result.status in (CheckStatus.PASS, CheckStatus.WARN) and
            placeholder_result.status in (CheckStatus.PASS, CheckStatus.WARN)
        )

        issues = []
        if dnp_result.status == CheckStatus.FAIL:
            issues.extend(dnp_result.issues)
        if placeholder_result.status == CheckStatus.FAIL:
            issues.extend(placeholder_result.issues)

        result = {
            'passed': validation_passed,
            'dnp_voiding': {
                'status': dnp_result.status.value,
                'total_dnp': dnp_result.total_dnp,
                'dnp_graded': dnp_result.dnp_graded,
            },
            'placeholder_lines': {
                'status': placeholder_result.status.value,
                'total': placeholder_result.total_placeholders,
                'graded': placeholder_result.placeholders_graded,
            },
            'issues': issues,
        }

        if validation_passed:
            logger.info(f"Post-grading validation PASSED for {target_date}")
        else:
            logger.warning(f"Post-grading validation FAILED for {target_date}: {issues}")

        return result

    except Exception as e:
        logger.error(f"Post-grading validation error for {target_date}: {e}", exc_info=True)
        return {
            'passed': True,  # Don't fail grading if validation errors
            'error': str(e),
            'issues': [],
        }


def run_prediction_accuracy_grading(target_date: str, skip_validation: bool = False) -> Dict:
    """
    Run prediction accuracy grading for a specific date.

    Args:
        target_date: Date to grade (YYYY-MM-DD format)
        skip_validation: If True, skip pre-grading validation

    Returns:
        Grading result dictionary
    """
    # Import here to avoid import errors in Cloud Function
    sys.path.insert(0, '/workspace')

    from datetime import date as date_type
    from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import (
        PredictionAccuracyProcessor
    )

    # Pre-grading validation (unless skipped)
    if not skip_validation:
        validation = validate_grading_prerequisites(target_date)
        logger.info(
            f"Pre-grading validation for {target_date}: "
            f"predictions={validation['predictions_count']}, "
            f"actuals={validation['actuals_count']}, "
            f"coverage={validation['coverage_pct']}%"
        )

        if not validation['ready']:
            if validation['can_auto_heal'] and validation['missing_reason'] == 'no_actuals':
                logger.warning(
                    f"No actuals for {target_date} - attempting auto-heal via Phase 3"
                )
                # Try to trigger Phase 3 analytics with retry logic
                trigger_result = trigger_phase3_analytics(target_date, max_retries=3)

                if trigger_result['success']:
                    # Phase 3 analytics typically takes 5-10+ minutes to complete.
                    # Rather than blocking here (Cloud Functions have timeout limits),
                    # we return immediately and let the scheduled grading jobs retry.
                    # Schedulers run at 2:30 AM, 7 AM, and 11 AM ET for multiple retry windows.
                    logger.info(
                        f"Phase 3 triggered successfully after {trigger_result['retries']} retries. "
                        f"Returning auto_heal_pending - scheduled grading jobs will retry after Phase 3 completes."
                    )
                    return {
                        'status': 'auto_heal_pending',
                        'date': target_date,
                        'predictions_found': validation['predictions_count'],
                        'actuals_found': 0,
                        'graded': 0,
                        'message': f'Phase 3 analytics triggered (after {trigger_result["retries"]} retries), scheduled grading will retry after completion',
                        'auto_heal_retries': trigger_result['retries']
                    }
                else:
                    # Auto-heal failed
                    error_msg = trigger_result['error']
                    logger.error(
                        f"Auto-heal failed for {target_date}: {error_msg} "
                        f"(after {trigger_result['retries']} retries)"
                    )
                    return {
                        'status': 'auto_heal_failed',
                        'date': target_date,
                        'predictions_found': validation['predictions_count'],
                        'actuals_found': 0,
                        'graded': 0,
                        'message': f'No actuals and auto-heal failed: {error_msg}',
                        'auto_heal_error': error_msg,
                        'auto_heal_retries': trigger_result['retries'],
                        'auto_heal_status_code': trigger_result['status_code']
                    }
            else:
                # Can't auto-heal or different missing reason
                return {
                    'status': validation['missing_reason'],
                    'date': target_date,
                    'predictions_found': validation['predictions_count'],
                    'actuals_found': validation['actuals_count'],
                    'graded': 0,
                    'message': f"Cannot grade: {validation['missing_reason']}"
                }

    logger.info(f"Running prediction accuracy grading for {target_date}")

    # Parse date
    year, month, day = map(int, target_date.split('-'))
    game_date = date_type(year, month, day)

    # Initialize processor and run
    processor = PredictionAccuracyProcessor(project_id=PROJECT_ID)
    result = processor.process_date(game_date)

    logger.info(f"Grading result for {target_date}: {result}")

    return result


def run_system_daily_performance(target_date: str) -> Dict:
    """
    Run system daily performance aggregation for a specific date.

    Args:
        target_date: Date to aggregate (YYYY-MM-DD format)

    Returns:
        Aggregation result dictionary
    """
    sys.path.insert(0, '/workspace')

    from datetime import date as date_type
    from data_processors.grading.system_daily_performance.system_daily_performance_processor import (
        SystemDailyPerformanceProcessor
    )

    logger.info(f"Running system daily performance aggregation for {target_date}")

    # Parse date
    year, month, day = map(int, target_date.split('-'))
    game_date = date_type(year, month, day)

    # Initialize processor and run
    processor = SystemDailyPerformanceProcessor(project_id=PROJECT_ID)
    result = processor.process(game_date)

    logger.info(f"Aggregation result for {target_date}: {result}")

    return result


def send_duplicate_alert(target_date: str, duplicate_count: int):
    """
    Send Slack alert when duplicates are detected (SESSION 94 FIX).

    Args:
        target_date: Date that was graded
        duplicate_count: Number of duplicate business keys found
    """
    import requests
    from google.cloud import secretmanager

    try:
        # Get Slack webhook from Secret Manager
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/slack-webhook-url/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        webhook_url = response.payload.data.decode("UTF-8")

        # Send alert
        message = {
            "text": f"🔴 *Grading Duplicate Alert*\n\n"
                   f"*Date:* {target_date}\n"
                   f"*Duplicates:* {duplicate_count} business keys\n"
                   f"*Status:* Grading completed but with duplicates\n"
                   f"*Action Required:* Investigate and run deduplication\n"
                   f"*See:* SESSION-94-FIX-DESIGN.md"
        }

        # Retry logic for transient failures
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(webhook_url, json=message, timeout=10)
                if resp.status_code == 200:
                    logger.info(f"Sent duplicate alert for {target_date}")
                    break
                elif resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s
                    continue
                else:
                    logger.warning(f"Slack alert failed: {resp.status_code} - {resp.text}")
                    break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                logger.warning(f"Slack alert request failed: {e}")

    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning(f"Failed to send duplicate alert: {e}")
        # Don't fail grading if alert fails


def send_validation_failure_alert(target_date: str, issues: list):
    """
    Send Slack alert when post-grading validation fails (SESSION 31).

    Args:
        target_date: Date that was validated
        issues: List of validation issues found
    """
    import requests
    from google.cloud import secretmanager

    try:
        # Get Slack webhook from Secret Manager
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/slack-webhook-url/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        webhook_url = response.payload.data.decode("UTF-8")

        # Format issues list
        issues_text = "\n".join(f"  • {issue}" for issue in issues[:5])
        if len(issues) > 5:
            issues_text += f"\n  ... and {len(issues) - 5} more"

        # Send alert
        message = {
            "text": f"⚠️ *Validation Alert*\n\n"
                   f"*Date:* {target_date}\n"
                   f"*Status:* Validation checks failed\n"
                   f"*Issues:*\n{issues_text}\n\n"
                   f"*Action:* Review validation results and fix data issues"
        }

        # Retry logic for transient failures
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(webhook_url, json=message, timeout=10)
                if resp.status_code == 200:
                    logger.info(f"Sent validation alert for {target_date}")
                    break
                elif resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                else:
                    logger.warning(f"Slack alert failed: {resp.status_code} - {resp.text}")
                    break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                logger.warning(f"Slack alert request failed: {e}")

    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning(f"Failed to send validation alert: {e}")
        # Don't fail grading if alert fails


def send_lock_failure_alert(target_date: str, lock_type: str, reason: str):
    """
    Send CRITICAL alert when lock acquisition fails (SESSION 97 FIX).

    This indicates grading ran WITHOUT distributed lock protection,
    which means HIGH RISK of duplicates being created.

    Args:
        target_date: Date that was processed
        lock_type: Type of lock that failed ('grading', 'daily_performance', etc.)
        reason: Failure reason/error message
    """
    import requests
    from google.cloud import secretmanager

    try:
        # Get Slack webhook from Secret Manager
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/slack-webhook-url/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        webhook_url = response.payload.data.decode("UTF-8")

        # Send CRITICAL alert
        message = {
            "text": f"🔴 *CRITICAL: Lock Acquisition Failed*\n\n"
                   f"*Date:* {target_date}\n"
                   f"*Lock Type:* {lock_type}\n"
                   f"*Reason:* {reason}\n"
                   f"*Status:* Operation proceeded WITHOUT distributed lock (HIGH RISK)\n"
                   f"*Risk:* Concurrent operations may create duplicates\n\n"
                   f"*Investigation Steps:*\n"
                   f"  1. Check Firestore collection: {lock_type}_locks\n"
                   f"  2. Check for stuck locks in Firestore console\n"
                   f"  3. Check Cloud Function logs for errors\n"
                   f"  4. Verify Firestore connectivity\n\n"
                   f"*Next Step:* Manual verification required after operation completes\n"
                   f"*Check for duplicates:* Run duplicate detection query immediately"
        }

        # Retry logic for transient failures
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(webhook_url, json=message, timeout=10)
                if resp.status_code == 200:
                    logger.info(f"Sent lock failure alert for {target_date}")
                    break
                elif resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s
                    continue
                else:
                    logger.warning(f"Slack alert failed: {resp.status_code} - {resp.text}")
                    break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                logger.warning(f"Slack alert request failed: {e}")

    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning(f"Failed to send lock failure alert: {e}")
        # Don't fail grading if alert fails


@functions_framework.cloud_event
def main(cloud_event):
    """
    Handle grading trigger from Pub/Sub.

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Raises:
        Exception: Re-raised to trigger Pub/Sub retry on transient failures
    """
    start_time = time.time()

    # Parse Pub/Sub message
    message_data = parse_pubsub_message(cloud_event)

    # Extract parameters
    correlation_id = message_data.get('correlation_id', 'scheduled')
    trigger_source = message_data.get('trigger_source', 'unknown')
    target_date_str = message_data.get('target_date', 'yesterday')
    run_aggregation = message_data.get('run_aggregation', True)

    # Get actual date
    target_date = get_target_date(target_date_str)

    logger.info(
        f"[{correlation_id}] Received grading trigger from {trigger_source}: "
        f"target_date={target_date}, run_aggregation={run_aggregation}"
    )

    grading_result = None
    aggregation_result = None

    try:
        # Step 1: Run prediction accuracy grading
        grading_result = run_prediction_accuracy_grading(target_date)

        # SESSION 94 FIX: Check for duplicates and alert if found
        if grading_result.get('status') == 'success':
            duplicate_count = grading_result.get('duplicate_count', 0)
            if duplicate_count > 0:
                logger.warning(f"Duplicates detected for {target_date}: {duplicate_count} business keys")
                send_duplicate_alert(target_date, duplicate_count)

            # SESSION 97 FIX: Log successful lock acquisition
            structured_logger.log_lock_event(
                event_type='lock_acquired',
                lock_type='grading',
                game_date=target_date,
                details={
                    'graded_count': grading_result.get('graded', 0),
                    'duplicate_count': duplicate_count
                }
            )

        # SESSION 97 FIX: Check for lock failures (graceful degradation scenario)
        # If lock acquisition failed, the processor logs it but continues
        # We need to alert on this scenario even though grading "succeeded"
        lock_failure_indicator = grading_result.get('lock_acquisition_failed', False)
        if lock_failure_indicator:
            logger.error(f"Lock acquisition failed for grading {target_date} - operation ran WITHOUT lock!", exc_info=True)
            send_lock_failure_alert(target_date, 'grading', 'Lock acquisition timeout or Firestore error')

        # Step 2: Run post-grading validation (if grading succeeded)
        validation_result = None
        if grading_result.get('status') == 'success':
            try:
                validation_result = run_post_grading_validation(target_date)
                if not validation_result.get('passed', True):
                    issues = validation_result.get('issues', [])
                    logger.warning(
                        f"Post-grading validation issues for {target_date}: {issues}"
                    )
                    # Send Slack alert for validation failures (Session 31)
                    if issues:
                        send_validation_failure_alert(target_date, issues)
            except Exception as e:
                logger.warning(f"Post-grading validation failed (non-fatal): {e}")
                validation_result = {'passed': True, 'error': str(e)}

        # Step 3: Run system daily performance aggregation (if enabled)
        if run_aggregation and grading_result.get('status') == 'success':
            try:
                aggregation_result = run_system_daily_performance(target_date)

                # SESSION 97 FIX: Check aggregation for duplicates and lock failures
                if aggregation_result.get('status') == 'success':
                    agg_duplicate_count = aggregation_result.get('duplicate_count', 0)
                    if agg_duplicate_count > 0:
                        logger.warning(f"Duplicates in system_daily_performance for {target_date}: {agg_duplicate_count}")
                        send_duplicate_alert(f"{target_date} (daily_performance)", agg_duplicate_count)

                    # Log successful lock acquisition
                    structured_logger.log_lock_event(
                        event_type='lock_acquired',
                        lock_type='daily_performance',
                        game_date=target_date,
                        details={
                            'systems': aggregation_result.get('systems', 0),
                            'records_written': aggregation_result.get('records_written', 0)
                        }
                    )

                # Check for lock failures
                if aggregation_result.get('lock_acquisition_failed', False):
                    logger.error(f"Lock acquisition failed for daily_performance {target_date}", exc_info=True)
                    send_lock_failure_alert(target_date, 'daily_performance', 'Lock acquisition timeout')

            except Exception as e:
                logger.warning(f"Aggregation failed (non-fatal): {e}")
                aggregation_result = {'status': 'failed', 'error': str(e)}

        # Calculate duration
        duration_seconds = time.time() - start_time

        # Determine overall status
        if grading_result.get('status') == 'success':
            overall_status = 'success'
            logger.info(
                f"[{correlation_id}] Grading completed successfully in {duration_seconds:.1f}s: "
                f"graded={grading_result.get('graded', 0)}, "
                f"MAE={grading_result.get('mae')}"
            )
        elif grading_result.get('status') == 'no_predictions':
            overall_status = 'skipped'
            logger.info(
                f"[{correlation_id}] No predictions to grade for {target_date}"
            )
        elif grading_result.get('status') == 'no_actuals':
            overall_status = 'skipped'
            logger.info(
                f"[{correlation_id}] No actuals available for {target_date}"
            )
        elif grading_result.get('status') == 'auto_heal_pending':
            overall_status = 'auto_heal_pending'
            logger.info(
                f"[{correlation_id}] Auto-heal triggered for {target_date}, grading pending. "
                f"Retries: {grading_result.get('auto_heal_retries', 0)}"
            )
        elif grading_result.get('status') == 'auto_heal_failed':
            overall_status = 'auto_heal_failed'
            logger.error(
                f"[{correlation_id}] Auto-heal failed for {target_date}: "
                f"{grading_result.get('auto_heal_error')} "
                f"(after {grading_result.get('auto_heal_retries', 0)} retries)"
            )
        else:
            overall_status = 'failed'
            logger.error(
                f"[{correlation_id}] Grading failed for {target_date}: {grading_result}"
            )

        # Publish completion event (include validation results in message_data)
        message_data['validation_result'] = validation_result or {}
        publish_completion(
            correlation_id=correlation_id,
            target_date=target_date,
            grading_result=grading_result,
            aggregation_result=aggregation_result,
            overall_status=overall_status,
            duration_seconds=duration_seconds,
            message_data=message_data
        )

        return {
            'status': overall_status,
            'target_date': target_date,
            'grading': grading_result,
            'aggregation': aggregation_result,
            'duration_seconds': round(duration_seconds, 2)
        }

    except Exception as e:
        duration_seconds = time.time() - start_time
        logger.error(
            f"[{correlation_id}] Error in grading after {duration_seconds:.1f}s: {e}",
            exc_info=True
        )
        # Re-raise to trigger Pub/Sub retry
        raise


def publish_completion(
    correlation_id: str,
    target_date: str,
    grading_result: Dict,
    aggregation_result: Optional[Dict],
    overall_status: str,
    duration_seconds: float,
    message_data: Dict
) -> Optional[str]:
    """
    Publish completion event for monitoring and downstream triggers.

    Args:
        correlation_id: Correlation ID for tracing
        target_date: Date that was graded
        grading_result: Result from prediction accuracy grading
        aggregation_result: Result from system daily performance (optional)
        overall_status: Overall status (success, skipped, failed)
        duration_seconds: Execution time
        message_data: Original trigger message

    Returns:
        Message ID if published, None on failure
    """
    try:
        publisher = get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, GRADING_COMPLETE_TOPIC)

        completion_message = {
            'processor_name': 'Phase5BGrading',
            'phase': 'phase_5b_grading',
            'correlation_id': correlation_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'target_date': target_date,
            'status': overall_status,
            'duration_seconds': round(duration_seconds, 2),

            # Grading metrics
            'predictions_found': grading_result.get('predictions_found', 0),
            'graded_count': grading_result.get('graded', 0),
            'mae': grading_result.get('mae'),
            'bias': grading_result.get('bias'),
            'recommendation_accuracy': grading_result.get('recommendation_accuracy'),

            # Auto-heal metrics (if attempted)
            'auto_heal_attempted': grading_result.get('auto_heal_retries') is not None,
            'auto_heal_retries': grading_result.get('auto_heal_retries'),
            'auto_heal_error': grading_result.get('auto_heal_error'),
            'auto_heal_status_code': grading_result.get('auto_heal_status_code'),

            # Post-grading validation (Session 31)
            'validation_passed': message_data.get('validation_result', {}).get('passed', True),
            'validation_issues': message_data.get('validation_result', {}).get('issues', []),

            # Aggregation metrics (if run)
            'aggregation_status': aggregation_result.get('status') if aggregation_result else None,

            # Trigger metadata
            'trigger_source': message_data.get('trigger_source', 'unknown'),
        }

        future = publisher.publish(
            topic_path,
            data=json.dumps(completion_message).encode('utf-8')
        )
        message_id = future.result(timeout=10.0)

        logger.info(f"[{correlation_id}] Published grading completion event: {message_id}")
        return message_id

    except Exception as e:
        # Don't fail the grading if completion publishing fails
        logger.warning(f"[{correlation_id}] Failed to publish completion event: {e}")
        return None


def parse_pubsub_message(cloud_event) -> Dict:
    """
    Parse Pub/Sub CloudEvent and extract message data.

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Returns:
        Dictionary with message data
    """
    try:
        pubsub_message = cloud_event.data.get('message', {})

        if 'data' in pubsub_message:
            message_data = json.loads(
                base64.b64decode(pubsub_message['data']).decode('utf-8')
            )
        else:
            message_data = {}

        return message_data

    except Exception as e:
        logger.error(f"Failed to parse Pub/Sub message: {e}", exc_info=True)
        return {}


# ============================================================================
# HTTP ENDPOINTS (for health checks)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the grading function."""
    return json.dumps({
        'status': 'healthy',
        'function': 'grading'
    }), 200, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Phase 5B Grading')
    parser.add_argument('--date', type=str, default='yesterday', help='Target date')
    parser.add_argument('--no-aggregation', action='store_true', help='Skip aggregation')

    args = parser.parse_args()

    target_date = get_target_date(args.date)
    print(f"Grading predictions for {target_date}...")

    grading_result = run_prediction_accuracy_grading(target_date)
    print(f"Grading result: {json.dumps(grading_result, indent=2, default=str)}")

    if not args.no_aggregation and grading_result.get('status') == 'success':
        print(f"Running aggregation for {target_date}...")
        aggregation_result = run_system_daily_performance(target_date)
        print(f"Aggregation result: {json.dumps(aggregation_result, indent=2, default=str)}")
