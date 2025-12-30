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

# Project configuration
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
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

    bq_client = bigquery.Client(project=PROJECT_ID)

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
        logger.error(f"Error validating grading prerequisites: {e}")
        return {
            'ready': False,
            'predictions_count': 0,
            'actuals_count': 0,
            'coverage_pct': 0.0,
            'missing_reason': f'validation_error: {str(e)}',
            'can_auto_heal': False
        }


def trigger_phase3_analytics(target_date: str) -> bool:
    """
    Trigger Phase 3 analytics to generate player_game_summary for a date.

    This is the auto-heal mechanism when grading finds no actuals.

    Args:
        target_date: Date to process (YYYY-MM-DD format)

    Returns:
        True if trigger was successful
    """
    import requests

    PHASE3_URL = "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range"

    logger.info(f"Auto-triggering Phase 3 analytics for {target_date}")

    try:
        # Trigger PlayerGameSummaryProcessor for the target date
        response = requests.post(
            PHASE3_URL,
            json={
                "start_date": target_date,
                "end_date": target_date,
                "processors": ["PlayerGameSummaryProcessor"],
                "backfill_mode": True
            },
            timeout=300  # 5 minute timeout
        )

        if response.status_code == 200:
            logger.info(f"Phase 3 analytics triggered successfully for {target_date}")
            return True
        else:
            logger.error(
                f"Phase 3 analytics trigger failed: {response.status_code} - {response.text}"
            )
            return False

    except Exception as e:
        logger.error(f"Error triggering Phase 3 analytics: {e}")
        return False


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
                # Try to trigger Phase 3 analytics
                if trigger_phase3_analytics(target_date):
                    # Wait a bit and re-check (Phase 3 takes a few minutes)
                    import time as time_module
                    time_module.sleep(10)  # Short wait before proceeding

                    # Re-validate
                    revalidation = validate_grading_prerequisites(target_date)
                    if not revalidation['ready']:
                        return {
                            'status': 'auto_heal_pending',
                            'date': target_date,
                            'predictions_found': validation['predictions_count'],
                            'actuals_found': 0,
                            'graded': 0,
                            'message': 'Phase 3 analytics triggered, grading should retry later'
                        }
                else:
                    return {
                        'status': 'no_actuals',
                        'date': target_date,
                        'predictions_found': validation['predictions_count'],
                        'actuals_found': 0,
                        'graded': 0,
                        'message': 'No actuals and auto-heal failed'
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

        # Step 2: Run system daily performance aggregation (if enabled)
        if run_aggregation and grading_result.get('status') == 'success':
            try:
                aggregation_result = run_system_daily_performance(target_date)
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
        else:
            overall_status = 'failed'
            logger.error(
                f"[{correlation_id}] Grading failed for {target_date}: {grading_result}"
            )

        # Publish completion event
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
        logger.error(f"Failed to parse Pub/Sub message: {e}")
        return {}


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
