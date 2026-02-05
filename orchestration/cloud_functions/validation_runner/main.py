"""
Cloud Function: Validation Runner

Runs scheduled validation checks and stores results in BigQuery.
This is the cloud deployment of the Continuous Validation System.

Triggered by: Cloud Scheduler (cron)

Session: 125 (2026-02-04)
"""

import functions_framework
from flask import jsonify
import json
import os
import sys
import logging
from datetime import date, datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


@functions_framework.http
def run_validation(request):
    """
    HTTP Cloud Function entry point.

    Query Parameters:
        schedule: Validation schedule name (required)
        date: Target date in YYYY-MM-DD format (optional)

    Returns:
        JSON response with validation results
    """
    try:
        from shared.validation.continuous_validator import ContinuousValidator

        # Get parameters
        schedule = request.args.get('schedule', 'post_overnight')
        date_str = request.args.get('date')

        target_date = None
        if date_str:
            target_date = date.fromisoformat(date_str)

        logger.info(f"Running validation: schedule={schedule}, date={target_date}")

        # Run validation
        validator = ContinuousValidator()
        result = validator.run_scheduled_validation(
            schedule_name=schedule,
            target_date=target_date,
            trigger_source="cloud_scheduler"
        )

        # Build response
        response = {
            'run_id': result.run_id,
            'status': result.status.value,
            'message': result.message,
            'duration_ms': result.duration_ms,
            'checks_passed': sum(1 for c in result.checks if c.status.value == 'PASS'),
            'checks_failed': sum(1 for c in result.checks if c.status.value == 'FAIL'),
            'target_date': str(result.target_date) if result.target_date else None,
            'schedule': schedule,
            'timestamp': datetime.utcnow().isoformat(),
        }

        # Return appropriate status code
        if result.status.value == 'CRITICAL':
            return jsonify(response), 500
        elif result.status.value == 'WARNING':
            return jsonify(response), 200  # Still success, just with warnings
        else:
            return jsonify(response), 200

    except Exception as e:
        logger.error(f"Validation failed with error: {e}", exc_info=True)
        return jsonify({
            'status': 'ERROR',
            'message': str(e),
            'timestamp': datetime.utcnow().isoformat(),
        }), 500


@functions_framework.cloud_event
def run_validation_pubsub(cloud_event):
    """
    Pub/Sub triggered Cloud Function entry point.

    Message data should be JSON with:
        schedule: Validation schedule name
        date: Target date (optional)
    """
    try:
        import base64
        from shared.validation.continuous_validator import ContinuousValidator

        # Parse message
        data = {}
        if cloud_event.data.get('message', {}).get('data'):
            message_data = base64.b64decode(cloud_event.data['message']['data']).decode('utf-8')
            data = json.loads(message_data)

        schedule = data.get('schedule', 'post_overnight')
        date_str = data.get('date')

        target_date = None
        if date_str:
            target_date = date.fromisoformat(date_str)

        logger.info(f"Running validation from Pub/Sub: schedule={schedule}, date={target_date}")

        # Run validation
        validator = ContinuousValidator()
        result = validator.run_scheduled_validation(
            schedule_name=schedule,
            target_date=target_date,
            trigger_source="pubsub"
        )

        logger.info(f"Validation complete: {result.status.value} - {result.message}")

    except Exception as e:
        logger.error(f"Validation failed with error: {e}", exc_info=True)
        raise


# Requirements for this cloud function
REQUIREMENTS = """
functions-framework==3.*
google-cloud-bigquery>=3.13.0
google-cloud-firestore>=2.11.0
requests>=2.28.0
"""
