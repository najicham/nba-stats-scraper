"""
Line Quality Self-Healing Cloud Function

Monitors predictions that used placeholder/estimated lines and automatically
regenerates them when real betting lines become available.

Problem Statement:
- Predictions generated before betting lines are available use ESTIMATED_AVG
- Later, real ACTUAL_PROP lines become available (from odds_api or bettingpros)
- Without intervention, predictions remain based on estimated lines
- This function detects this state and triggers regeneration

Detection Logic:
1. Find active predictions with line_source = 'ESTIMATED_AVG' or NULL
2. Check if real betting lines NOW exist in odds_api or bettingpros tables
3. If lines exist, mark old predictions for regeneration and trigger coordinator

Triggered by: Cloud Scheduler (recommended: every 2 hours during business hours)

Deployment:
    gcloud functions deploy line-quality-self-heal \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/line_quality_self_heal \
        --entry-point check_line_quality \
        --trigger-http \
        --allow-unauthenticated \
        --memory 512MB \
        --timeout 300s \
        --set-env-vars GCP_PROJECT=nba-props-platform

Scheduler (run every 2 hours 8 AM - 8 PM ET):
    gcloud scheduler jobs create http line-quality-self-heal-job \
        --schedule "0 8-20/2 * * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method POST \
        --location us-west2

Version: 1.0
Created: 2026-01-23
Author: Claude Code (Session: Orchestration Validation)
"""

import logging
import os
import json
import requests
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery
from google.cloud import secretmanager

import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
COORDINATOR_URL = os.environ.get(
    'COORDINATOR_URL',
    'https://prediction-coordinator-756957797294.us-west2.run.app'
)

# Thresholds
MIN_PLAYERS_FOR_REGENERATION = int(os.environ.get('MIN_PLAYERS_FOR_REGENERATION', '5'))
LOOKBACK_DAYS = int(os.environ.get('LOOKBACK_DAYS', '3'))
# Only regenerate predictions that are at least this old (avoid racing with normal flow)
MIN_AGE_HOURS = int(os.environ.get('MIN_AGE_HOURS', '2'))

# Slack webhook for alerts
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')


class LineQualitySelfHealer:
    """
    Self-healing component that detects and fixes predictions with placeholder lines.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)
        self._api_key = None

    @property
    def api_key(self) -> str:
        """Lazy-load coordinator API key from Secret Manager."""
        if self._api_key is None:
            try:
                client = secretmanager.SecretManagerServiceClient()
                name = f"projects/{self.project_id}/secrets/coordinator-api-key/versions/latest"
                response = client.access_secret_version(name=name)
                self._api_key = response.payload.data.decode('UTF-8')
            except Exception as e:
                logger.error(f"Failed to load API key: {e}", exc_info=True)
                self._api_key = ""
        return self._api_key

    def find_predictions_with_placeholder_lines(
        self,
        lookback_days: int = LOOKBACK_DAYS
    ) -> List[Dict]:
        """
        Find active predictions that used ESTIMATED_AVG or NULL line_source
        where real betting lines are now available.

        Returns list of {game_date, player_lookup, line_source, has_real_line_now}
        """
        cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()
        min_age_timestamp = (
            datetime.now(timezone.utc) - timedelta(hours=MIN_AGE_HOURS)
        ).isoformat()

        query = f"""
        WITH placeholder_predictions AS (
            -- Find predictions with placeholder/estimated lines
            SELECT DISTINCT
                p.game_date,
                p.player_lookup,
                p.line_source,
                p.current_points_line,
                p.created_at
            FROM `{self.project_id}.nba_predictions.player_prop_predictions` p
            WHERE p.game_date >= '{cutoff_date}'
                AND p.is_active = TRUE
                AND (
                    p.line_source IN ('ESTIMATED_AVG', 'NEEDS_BOOTSTRAP')
                    OR p.line_source IS NULL
                    OR p.current_points_line = 20.0
                )
                -- Only consider predictions old enough to avoid racing
                AND p.created_at < '{min_age_timestamp}'
        ),
        available_odds_api AS (
            -- Check which players now have lines in odds_api
            SELECT DISTINCT
                player_lookup,
                game_date
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date >= '{cutoff_date}'
        ),
        available_bettingpros AS (
            -- Check which players now have lines in bettingpros
            SELECT DISTINCT
                player_lookup,
                game_date
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE game_date >= '{cutoff_date}'
        )
        SELECT
            pp.game_date,
            pp.player_lookup,
            pp.line_source as original_line_source,
            pp.current_points_line as original_line_value,
            pp.created_at,
            CASE
                WHEN oa.player_lookup IS NOT NULL THEN 'ODDS_API'
                WHEN bp.player_lookup IS NOT NULL THEN 'BETTINGPROS'
                ELSE NULL
            END as available_source
        FROM placeholder_predictions pp
        LEFT JOIN available_odds_api oa
            ON pp.player_lookup = oa.player_lookup AND pp.game_date = oa.game_date
        LEFT JOIN available_bettingpros bp
            ON pp.player_lookup = bp.player_lookup AND pp.game_date = bp.game_date
        WHERE oa.player_lookup IS NOT NULL OR bp.player_lookup IS NOT NULL
        ORDER BY pp.game_date DESC, pp.player_lookup
        LIMIT 1000
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error finding placeholder predictions: {e}", exc_info=True)
            return []

    def get_regeneration_summary(
        self,
        predictions: List[Dict]
    ) -> Dict[str, List[str]]:
        """
        Group predictions by game_date for regeneration.

        Returns: {game_date: [player_lookup, ...]}
        """
        by_date = {}
        for pred in predictions:
            game_date = str(pred['game_date'])
            if game_date not in by_date:
                by_date[game_date] = []
            by_date[game_date].append(pred['player_lookup'])
        return by_date

    def deactivate_placeholder_predictions(
        self,
        game_date: str,
        player_lookups: List[str]
    ) -> int:
        """
        Deactivate placeholder predictions for specific players on a date.

        This allows the new predictions to become the active ones.

        Returns: Number of predictions deactivated
        """
        if not player_lookups:
            return 0

        # Build parameterized query
        placeholders = ', '.join([f'"{p}"' for p in player_lookups])

        query = f"""
        UPDATE `{self.project_id}.nba_predictions.player_prop_predictions`
        SET
            is_active = FALSE,
            updated_at = CURRENT_TIMESTAMP()
        WHERE game_date = '{game_date}'
            AND player_lookup IN ({placeholders})
            AND is_active = TRUE
            AND (
                line_source IN ('ESTIMATED_AVG', 'NEEDS_BOOTSTRAP')
                OR line_source IS NULL
                OR current_points_line = 20.0
            )
        """

        try:
            result = self.bq_client.query(query)
            result.result()  # Wait for completion
            return result.num_dml_affected_rows or 0
        except Exception as e:
            logger.error(f"Error deactivating predictions for {game_date}: {e}", exc_info=True)
            return 0

    def trigger_regeneration(
        self,
        game_date: str,
        player_lookups: Optional[List[str]] = None,
        reason: str = "line_quality_self_heal"
    ) -> Dict:
        """
        Trigger the prediction coordinator to regenerate predictions for a date.

        Args:
            game_date: Date to regenerate predictions for
            player_lookups: Optional list of specific players (if None, regenerates all)
            reason: Reason for regeneration (for logging/tracking)

        Returns:
            Response from coordinator
        """
        url = f"{COORDINATOR_URL}/start"
        headers = {
            'Content-Type': 'application/json',
            'X-API-Key': self.api_key
        }
        payload = {
            'game_date': game_date,
            'reason': reason,
        }

        # If we have specific players, we could add them to payload
        # but the coordinator currently regenerates all players for a date
        if player_lookups:
            payload['regeneration_context'] = {
                'player_count': len(player_lookups),
                'triggered_by': 'line_quality_self_heal'
            }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code in (200, 202):
                return response.json()
            else:
                logger.error(
                    f"Coordinator returned {response.status_code}: {response.text}"
                )
                return {'error': response.text, 'status_code': response.status_code}
        except Exception as e:
            logger.error(f"Error triggering regeneration: {e}", exc_info=True)
            return {'error': str(e)}

    def log_self_heal_action(
        self,
        game_date: str,
        action: str,
        details: Dict
    ):
        """Log self-heal actions to BigQuery for audit trail."""
        row = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'game_date': game_date,
            'action': action,
            'details': json.dumps(details),
            'source': 'line_quality_self_heal'
        }

        # Insert into self_heal_log table (create if not exists)
        table_id = f"{self.project_id}.nba_orchestration.self_heal_log"

        try:
            errors = self.bq_client.insert_rows_json(table_id, [row])
            if errors:
                logger.warning(f"Error logging to BigQuery: {errors}")
        except Exception as e:
            # Log table might not exist yet - that's OK
            logger.debug(f"Could not log to BigQuery: {e}")

    def send_slack_notification(
        self,
        summary: Dict,
        regenerated_dates: List[str],
        skipped_dates: List[str]
    ):
        """Send Slack notification about self-healing actions."""
        if not SLACK_WEBHOOK_URL:
            return

        total_predictions = sum(len(players) for players in summary.values())

        message = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Line Quality Self-Heal Report"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Detected:* {total_predictions} predictions with "
                            f"placeholder lines that now have real lines available\n"
                            f"*Dates regenerated:* {', '.join(regenerated_dates) or 'None'}\n"
                            f"*Dates skipped:* {', '.join(skipped_dates) or 'None'}"
                        )
                    }
                }
            ]
        }

        try:
            requests.post(SLACK_WEBHOOK_URL, json=message, timeout=10)
        except Exception as e:
            logger.warning(f"Failed to send Slack notification: {e}")

    def run(self, dry_run: bool = False) -> Dict:
        """
        Main self-healing loop.

        Args:
            dry_run: If True, detect issues but don't trigger regeneration

        Returns:
            Summary of actions taken
        """
        logger.info("Starting line quality self-heal check...")

        # Step 1: Find predictions with placeholder lines that now have real lines
        placeholder_predictions = self.find_predictions_with_placeholder_lines()

        if not placeholder_predictions:
            logger.info("No placeholder predictions found with available real lines")
            return {
                'status': 'no_action_needed',
                'placeholder_count': 0,
                'regenerated': [],
                'skipped': []
            }

        logger.info(
            f"Found {len(placeholder_predictions)} predictions with "
            "placeholder lines that could be regenerated"
        )

        # Step 2: Group by date
        by_date = self.get_regeneration_summary(placeholder_predictions)

        regenerated = []
        skipped = []

        # Step 3: Process each date
        for game_date, player_lookups in by_date.items():
            if len(player_lookups) < MIN_PLAYERS_FOR_REGENERATION:
                logger.info(
                    f"Skipping {game_date}: only {len(player_lookups)} players "
                    f"(min: {MIN_PLAYERS_FOR_REGENERATION})"
                )
                skipped.append(game_date)
                continue

            logger.info(
                f"Processing {game_date}: {len(player_lookups)} players "
                "with placeholder lines"
            )

            if dry_run:
                logger.info(f"DRY RUN: Would regenerate {game_date}")
                continue

            # Step 3a: Deactivate old placeholder predictions
            deactivated = self.deactivate_placeholder_predictions(
                game_date, player_lookups
            )
            logger.info(f"Deactivated {deactivated} placeholder predictions")

            # Step 3b: Trigger regeneration
            result = self.trigger_regeneration(
                game_date,
                player_lookups,
                reason=f"line_quality_self_heal: {len(player_lookups)} players"
            )

            if 'error' not in result:
                regenerated.append(game_date)
                self.log_self_heal_action(game_date, 'regeneration_triggered', {
                    'player_count': len(player_lookups),
                    'deactivated_count': deactivated,
                    'batch_id': result.get('batch_id')
                })
            else:
                skipped.append(game_date)
                self.log_self_heal_action(game_date, 'regeneration_failed', {
                    'error': result.get('error'),
                    'player_count': len(player_lookups)
                })

        # Step 4: Send notification
        self.send_slack_notification(by_date, regenerated, skipped)

        return {
            'status': 'completed',
            'placeholder_count': len(placeholder_predictions),
            'dates_checked': list(by_date.keys()),
            'regenerated': regenerated,
            'skipped': skipped,
            'dry_run': dry_run
        }


@functions_framework.http
def check_line_quality(request):
    """
    HTTP Cloud Function entry point.

    Query parameters:
    - dry_run: If 'true', detect issues but don't trigger regeneration
    - lookback_days: Override default lookback (default: 3)
    """
    # Parse request
    dry_run = request.args.get('dry_run', 'false').lower() == 'true'

    if request.args.get('lookback_days'):
        global LOOKBACK_DAYS
        LOOKBACK_DAYS = int(request.args.get('lookback_days'))

    logger.info(f"Line quality self-heal triggered (dry_run={dry_run})")

    # Run self-healing
    healer = LineQualitySelfHealer(PROJECT_ID)
    result = healer.run(dry_run=dry_run)

    logger.info(f"Self-heal complete: {result}")

    return (
        json.dumps(result, indent=2, default=str),
        200,
        {'Content-Type': 'application/json'}
    )


# Allow local testing
if __name__ == '__main__':
    import sys
    dry_run = '--dry-run' in sys.argv
    healer = LineQualitySelfHealer()
    result = healer.run(dry_run=dry_run)
    print(json.dumps(result, indent=2, default=str))


@functions_framework.http
def health(request):
    """Health check endpoint for line_quality_self_heal."""
    return json.dumps({
        'status': 'healthy',
        'function': 'line_quality_self_heal',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
