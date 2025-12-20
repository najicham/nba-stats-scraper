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


def run_prediction_accuracy_grading(target_date: str) -> Dict:
    """
    Run prediction accuracy grading for a specific date.

    Args:
        target_date: Date to grade (YYYY-MM-DD format)

    Returns:
        Grading result dictionary
    """
    # Import here to avoid import errors in Cloud Function
    sys.path.insert(0, '/workspace')

    from datetime import date as date_type
    from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import (
        PredictionAccuracyProcessor
    )

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
