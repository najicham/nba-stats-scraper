"""
Prediction Line Enrichment Trigger

Cloud Function that runs the prediction line enrichment processor to backfill
betting lines into predictions that were generated before props were scraped.

Architecture:
- Triggered by: Cloud Scheduler (18:40 UTC daily, after props scraped at 18:00)
- Alternative: Can be triggered via HTTP for manual runs
- Calls: PredictionLineEnrichmentProcessor to update predictions with betting lines
- Updates: nba_predictions.player_prop_predictions table with current_points_line
- Session 241: After enrichment, triggers V9 re-predictions for players that got lines
  (V9 uses vegas_points_line as feature #25, so predictions change when lines arrive)

Why This Is Needed:
- Predictions are generated the night before (Phase 5) when props don't exist yet
- Props are scraped on game day around 18:00 UTC
- This processor runs at 18:40 UTC to enrich predictions with actual betting lines
- Without this, predictions would have NULL current_points_line values

Version: 1.1
Created: 2026-01-14
Updated: 2026-02-13 (Session 241: V9 re-prediction after enrichment)
"""

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

# Ensure deployed package root is in Python path (Cloud Functions runtime fix)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
            logger.error(f"Failed to initialize PredictionLineEnrichmentProcessor: {e}", exc_info=True)
            raise
    return _processor


COORDINATOR_URL = os.environ.get(
    'COORDINATOR_URL',
    'https://prediction-coordinator-756957797294.us-west2.run.app'
)


def _get_auth_token(audience):
    """Get identity token for authenticated service calls using metadata server."""
    import urllib.request

    metadata_url = (
        f"http://metadata.google.internal/computeMetadata/v1/"
        f"instance/service-accounts/default/identity?audience={audience}"
    )
    req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to get auth token: {e}")
        raise


def _trigger_v9_reprediction(game_date, player_lookups):
    """Trigger V9 re-predictions via coordinator /line-update endpoint.

    Session 241: After enrichment adds lines, V9 predictions need to be
    regenerated because vegas_points_line (feature #25) changed from NaN
    to a real value.

    Args:
        game_date: date object
        player_lookups: list of player_lookup strings

    Returns:
        dict with trigger results
    """
    import requests as http_requests

    if not player_lookups:
        return {'triggered': False, 'players': 0}

    logger.info(
        f"Triggering V9 re-prediction for {len(player_lookups)} players on {game_date}"
    )

    try:
        token = _get_auth_token(COORDINATOR_URL)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "game_date": str(game_date),
            "player_lookups": player_lookups,
        }

        response = http_requests.post(
            f"{COORDINATOR_URL}/line-update",
            headers=headers,
            json=payload,
            timeout=120
        )
        response.raise_for_status()

        result = response.json()
        logger.info(f"V9 re-prediction triggered: {result}")

        return {
            'triggered': True,
            'players': len(player_lookups),
            'superseded': result.get('superseded_count', 0),
            'published': result.get('requests_published', 0),
            'batch_id': result.get('batch_id'),
        }

    except Exception as e:
        logger.error(f"Failed to trigger V9 re-prediction: {e}", exc_info=True)
        return {
            'triggered': False,
            'players': len(player_lookups),
            'error': str(e),
        }


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

            # Session 241: Trigger V9 re-predictions for enriched players
            # V9 uses vegas_points_line (feature #25). NaN → real value = different prediction.
            # Only for V9 systems (V12 is vegas-free, no impact).
            line_update_result = {'triggered': False, 'players': 0}
            enriched_players = enrichment_result.get('enriched_players', [])
            if enriched_players and not dry_run:
                try:
                    v9_players = processor.get_v9_players_needing_reprediction(
                        game_date=target_date,
                        enriched_players=enriched_players
                    )
                    if v9_players:
                        v9_lookups = [p['player_lookup'] for p in v9_players]
                        line_update_result = _trigger_v9_reprediction(
                            game_date=target_date,
                            player_lookups=v9_lookups
                        )
                except Exception as e:
                    logger.error(f"V9 re-prediction trigger failed (non-fatal): {e}", exc_info=True)
                    line_update_result = {'triggered': False, 'error': str(e)}

            # Session 218: Injury recheck — deactivate predictions for OUT players
            # Runs after enrichment so OUT players don't appear in API exports
            injury_result = processor.recheck_injuries(
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
                'v9_line_update': line_update_result,
                'injury_recheck': {
                    'out_players': injury_result.get('out_players', 0),
                    'predictions_deactivated': injury_result.get('predictions_deactivated', 0),
                    'deactivated_players': injury_result.get('deactivated_players', [])
                },
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
