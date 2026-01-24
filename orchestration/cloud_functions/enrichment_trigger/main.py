"""
Prediction Line Enrichment Trigger

Cloud Function that runs the prediction line enrichment processor to backfill
betting lines into predictions that were generated before props were scraped.

Architecture:
- Triggered by: Cloud Scheduler (18:40 UTC daily, after props scraped at 18:00)
- Alternative: Can be triggered via HTTP for manual runs
- Calls: PredictionLineEnrichmentProcessor to update predictions with betting lines
- Updates: nba_predictions.player_prop_predictions table with current_points_line

Why This Is Needed:
- Predictions are generated the night before (Phase 5) when props don't exist yet
- Props are scraped on game day around 18:00 UTC
- This processor runs at 18:40 UTC to enrich predictions with actual betting lines
- Without this, predictions would have NULL current_points_line values

Version: 1.0
Created: 2026-01-14
"""

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Initialize processor (lazy)
_processor = None


def get_processor():
    """Get or create PredictionLineEnrichmentProcessor (lazy initialization)."""
    global _processor
    if _processor is None:
        try:
            from data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor import (
                PredictionLineEnrichmentProcessor
            )
            _processor = PredictionLineEnrichmentProcessor(project_id=PROJECT_ID)
            logger.info("PredictionLineEnrichmentProcessor initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PredictionLineEnrichmentProcessor: {e}")
            raise
    return _processor


@functions_framework.http
def trigger_enrichment(request):
    """
    HTTP endpoint to trigger prediction line enrichment.

    Triggered by: Cloud Scheduler at 18:40 UTC daily

    Query Parameters:
        - date: Optional date string (YYYY-MM-DD). Defaults to today.
        - dry_run: Optional boolean. If true, shows what would be updated without updating.
        - fix_recommendations: Optional boolean. If true, only fixes recommendations.

    Returns:
        JSON response with enrichment results
    """
    # Parse request parameters
    request_args = request.args

    # Get target date (default to today)
    target_date_str = request_args.get('date')
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            return json.dumps({
                'status': 'error',
                'message': f'Invalid date format: {target_date_str}. Use YYYY-MM-DD.'
            }), 400, {'Content-Type': 'application/json'}
    else:
        target_date = date.today()

    # Get dry_run flag
    dry_run = request_args.get('dry_run', 'false').lower() == 'true'

    # Get fix_recommendations flag
    fix_recommendations_only = request_args.get('fix_recommendations', 'false').lower() == 'true'

    logger.info(
        f"Enrichment triggered for {target_date} "
        f"(dry_run={dry_run}, fix_recommendations_only={fix_recommendations_only})"
    )

    try:
        processor = get_processor()

        if fix_recommendations_only:
            # Only fix recommendations for predictions that already have lines
            fixed_count = processor.fix_recommendations(target_date)

            result = {
                'status': 'success',
                'game_date': str(target_date),
                'action': 'fix_recommendations',
                'recommendations_fixed': fixed_count,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        else:
            # Full enrichment - add betting lines to predictions
            enrichment_result = processor.enrich_predictions(
                game_date=target_date,
                dry_run=dry_run
            )

            result = {
                'status': 'success',
                'game_date': str(target_date),
                'action': 'enrich_predictions',
                'dry_run': dry_run,
                'predictions_missing_lines': enrichment_result.get('predictions_missing_lines', 0),
                'props_available': enrichment_result.get('props_available', 0),
                'predictions_enriched': enrichment_result.get('predictions_enriched', 0),
                'predictions_still_missing': enrichment_result.get('predictions_still_missing', 0),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        logger.info(f"Enrichment completed: {result}")

        return json.dumps(result), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Enrichment failed for {target_date}: {e}", exc_info=True)

        return json.dumps({
            'status': 'error',
            'game_date': str(target_date),
            'message': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500, {'Content-Type': 'application/json'}


@functions_framework.http
def health(request):
    """Health check endpoint for the enrichment trigger."""
    return json.dumps({
        'status': 'healthy',
        'function': 'enrichment_trigger',
        'project': PROJECT_ID,
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Prediction Line Enrichment Trigger')
    parser.add_argument('--date', type=str, help='Game date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('--fix-recommendations', action='store_true', help='Fix recommendations only')

    args = parser.parse_args()

    # Parse date
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    else:
        target_date = date.today()

    print(f"Running enrichment for {target_date} (dry_run={args.dry_run})")

    processor = get_processor()

    if args.fix_recommendations:
        fixed_count = processor.fix_recommendations(target_date)
        print(f"Fixed {fixed_count} recommendations")
    else:
        result = processor.enrich_predictions(target_date, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
