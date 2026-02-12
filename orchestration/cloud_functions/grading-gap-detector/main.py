"""
Grading Gap Detector Cloud Function

Detects incomplete grading and auto-triggers backfills.
Runs daily at 9 AM ET via Cloud Scheduler.

Session 212: Deployed as Cloud Function for automated monitoring.
"""

import functions_framework
import logging
import sys
import os

# Add repo root to path for imports
sys.path.insert(0, '/workspace')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def main(request):
    """
    HTTP Cloud Function entry point.

    Called by Cloud Scheduler daily at 9 AM ET.

    Args:
        request: HTTP request object

    Returns:
        Tuple of (response_text, status_code)
    """
    try:
        from google.cloud import bigquery
        from bin.monitoring.grading_gap_detector import (
            detect_grading_gaps,
            trigger_grading_backfill,
            format_slack_alert
        )
        from shared.utils.slack_alerts import send_slack_alert

        logger.info("Starting grading gap detection")

        # Detect gaps (last 14 days)
        client = bigquery.Client(project=os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'))
        gaps = detect_grading_gaps(client, lookback_days=14)

        if not gaps:
            logger.info("✅ No grading gaps found")
            return "✅ No grading gaps found", 200

        # Trigger backfills for gaps
        logger.warning(f"Found {len(gaps)} grading gaps, triggering backfills")
        backfill_results = []

        for gap in gaps:
            result = trigger_grading_backfill(gap['game_date'], dry_run=False)
            backfill_results.append({
                'game_date': gap['game_date'],
                'success': result['success'],
                'message': result['message']
            })

        # Send Slack alert
        alert_message = format_slack_alert(gaps, backfill_results, dry_run=False)
        if alert_message:
            send_slack_alert(alert_message, channel='#nba-alerts')

        # Return summary
        successful = sum(1 for r in backfill_results if r['success'])
        failed = len(backfill_results) - successful

        response = (
            f"Grading gap detection complete\n"
            f"Gaps found: {len(gaps)}\n"
            f"Backfills triggered: {successful} successful, {failed} failed"
        )

        logger.info(response)
        return response, 200

    except Exception as e:
        logger.error(f"Error in grading gap detector: {e}", exc_info=True)
        return f"Error: {str(e)}", 500
