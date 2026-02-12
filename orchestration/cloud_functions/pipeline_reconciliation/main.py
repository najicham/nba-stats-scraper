"""
R-007: Pipeline Data Reconciliation

Cloud Function that runs daily to verify data completeness across all pipeline phases.
Catches data gaps that individual phase fixes might miss.

Architecture:
- Runs at 6:00 AM ET daily (after overnight processing)
- Checks Phase 1 (raw) through Phase 5 (predictions)
- Cross-phase consistency validation
- Sends Slack alert if gaps detected

Phases Checked:
- Phase 1: Schedule, BDL boxscores
- Phase 2: Raw data (rosters, odds)
- Phase 3: Analytics (player_game_summary)
- Phase 4: Precompute (ML features, daily cache)
- Phase 5: Predictions

Deployment:
    gcloud functions deploy pipeline-reconciliation \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/pipeline_reconciliation \
        --entry-point reconcile_pipeline \
        --trigger-http \
        --allow-unauthenticated \
        --memory 512MB \
        --timeout 120s \
        --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=<webhook>

Scheduler:
    gcloud scheduler jobs create http pipeline-reconciliation-job \
        --schedule "0 6 * * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method GET \
        --location us-west2

Version: 1.0
Created: 2026-01-15 (Session 65)
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
import functions_framework
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Timezone
ET = ZoneInfo("America/New_York")

# Thresholds for alerts
MIN_PLAYERS_PER_GAME = 8  # Minimum players expected per game (starters + key bench)
MIN_PREDICTIONS_PER_PLAYER = 2  # At minimum, points and one other prop


class PipelineReconciler:
    """Reconciles data across all pipeline phases."""

    def __init__(self):
        self.client = get_bigquery_client(project_id=PROJECT_ID)
        self.gaps: List[Dict] = []  # List of detected gaps
        self.warnings: List[str] = []  # Non-critical warnings
        self.stats: Dict = {}  # Statistics per phase

    def run_query(self, query: str, timeout: int = 60) -> List[Dict]:
        """Run a BigQuery query and return results."""
        try:
            result = self.client.query(query).result(timeout=timeout)
            return [dict(row) for row in result]
        except Exception as e:
            logger.warning(f"Query error: {e}")
            return []

    def check_phase1_schedule(self, date: str) -> Dict:
        """Phase 1: Check schedule data for a date."""
        query = f"""
        SELECT
            COUNT(*) as total_games,
            COUNTIF(game_status_text = 'Final') as final_games,
            COUNTIF(game_status_text != 'Final') as pending_games
        FROM `{PROJECT_ID}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        return results[0] if results else {'total_games': 0, 'final_games': 0, 'pending_games': 0}

    def check_phase1_boxscores(self, date: str) -> Dict:
        """Phase 1: Check BDL boxscores for a date."""
        query = f"""
        SELECT
            COUNT(DISTINCT game_id) as games_with_data,
            COUNT(*) as player_records,
            COUNT(DISTINCT player_id) as unique_players
        FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        return results[0] if results else {'games_with_data': 0, 'player_records': 0, 'unique_players': 0}

    def check_phase2_rosters(self, date: str) -> Dict:
        """Phase 2: Check roster data for a date."""
        query = f"""
        SELECT
            COUNT(DISTINCT team_abbr) as teams_with_rosters,
            COUNT(*) as player_records
        FROM `{PROJECT_ID}.nba_raw.espn_team_rosters`
        WHERE roster_date = '{date}'
        """
        results = self.run_query(query)
        return results[0] if results else {'teams_with_rosters': 0, 'player_records': 0}

    def check_phase2_odds(self, date: str) -> Dict:
        """Phase 2: Check player props odds for a date."""
        query = f"""
        SELECT
            COUNT(DISTINCT player_lookup) as players_with_odds,
            COUNT(*) as total_lines
        FROM `{PROJECT_ID}.nba_raw.oddsapi_player_props_all`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        return results[0] if results else {'players_with_odds': 0, 'total_lines': 0}

    def check_phase3_analytics(self, date: str) -> Dict:
        """Phase 3: Check player_game_summary for a date."""
        query = f"""
        SELECT
            COUNT(DISTINCT game_id) as games_with_analytics,
            COUNT(*) as player_records,
            COUNT(DISTINCT player_lookup) as unique_players
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        return results[0] if results else {'games_with_analytics': 0, 'player_records': 0, 'unique_players': 0}

    def check_phase3_games_with_zero_active(self, date: str) -> Dict:
        """Phase 3: Check for games with 0 active players (R-009 detection)."""
        query = f"""
        SELECT
            COUNT(*) as total_games_checked,
            COUNTIF(active_count = 0) as games_with_zero_active,
            ARRAY_AGG(IF(active_count = 0, game_id, NULL) IGNORE NULLS) as zero_active_games
        FROM (
            SELECT
                game_id,
                COUNTIF(is_active = TRUE) as active_count
            FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
            WHERE game_date = '{date}'
            GROUP BY game_id
        )
        """
        results = self.run_query(query)
        if results:
            row = results[0]
            return {
                'total_games_checked': row.get('total_games_checked', 0),
                'games_with_zero_active': row.get('games_with_zero_active', 0),
                'zero_active_games': row.get('zero_active_games', []) or []
            }
        return {'total_games_checked': 0, 'games_with_zero_active': 0, 'zero_active_games': []}

    def check_phase4_precompute(self, date: str) -> Dict:
        """Phase 4: Check precompute tables for a date."""
        # Check multiple Phase 4 tables
        # NOTE: ml_feature_store_v2 is in nba_predictions, not nba_precompute
        tables_to_check = [
            ('nba_predictions', 'ml_feature_store_v2', 'game_date'),
            ('nba_precompute', 'player_daily_cache', 'cache_date'),
            ('nba_precompute', 'player_composite_factors', 'game_date'),
        ]

        results = {}
        for dataset, table, date_col in tables_to_check:
            query = f"""
            SELECT COUNT(*) as records
            FROM `{PROJECT_ID}.{dataset}.{table}`
            WHERE {date_col} = '{date}'
            """
            result = self.run_query(query)
            results[table] = result[0]['records'] if result else 0

        return results

    def check_phase5_predictions(self, date: str) -> Dict:
        """Phase 5: Check predictions for a date."""
        query = f"""
        SELECT
            COUNT(*) as total_predictions,
            COUNT(DISTINCT player_lookup) as unique_players,
            COUNT(DISTINCT system_id) as systems,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{date}' AND is_active = TRUE
        """
        results = self.run_query(query)
        return results[0] if results else {'total_predictions': 0, 'unique_players': 0, 'systems': 0, 'actionable': 0}

    def reconcile(self, date: str) -> Dict:
        """
        Run full reconciliation for a date.

        Returns:
            Dict with reconciliation results
        """
        logger.info(f"R-007: Starting pipeline reconciliation for {date}")

        # Collect stats from all phases
        schedule = self.check_phase1_schedule(date)
        boxscores = self.check_phase1_boxscores(date)
        rosters = self.check_phase2_rosters(date)
        odds = self.check_phase2_odds(date)
        analytics = self.check_phase3_analytics(date)
        zero_active = self.check_phase3_games_with_zero_active(date)  # R-009 check
        precompute = self.check_phase4_precompute(date)
        predictions = self.check_phase5_predictions(date)

        # Store stats
        self.stats = {
            'date': date,
            'phase1_schedule': schedule,
            'phase1_boxscores': boxscores,
            'phase2_rosters': rosters,
            'phase2_odds': odds,
            'phase3_analytics': analytics,
            'phase3_zero_active': zero_active,  # R-009 check
            'phase4_precompute': precompute,
            'phase5_predictions': predictions,
        }

        # Run consistency checks
        final_games = schedule.get('final_games', 0)

        # Check 1: Games with boxscores vs schedule
        if final_games > 0:
            games_with_boxscores = boxscores.get('games_with_data', 0)
            if games_with_boxscores < final_games:
                self.gaps.append({
                    'phase': 'Phase 1',
                    'check': 'Boxscores vs Schedule',
                    'expected': final_games,
                    'actual': games_with_boxscores,
                    'severity': 'HIGH',
                    'message': f"Missing boxscores: {final_games - games_with_boxscores} games"
                })

        # Check 2: Player records in analytics vs boxscores
        boxscore_players = boxscores.get('unique_players', 0)
        analytics_players = analytics.get('unique_players', 0)
        if boxscore_players > 0 and analytics_players < boxscore_players * 0.8:
            self.gaps.append({
                'phase': 'Phase 3',
                'check': 'Analytics vs Boxscores',
                'expected': boxscore_players,
                'actual': analytics_players,
                'severity': 'MEDIUM',
                'message': f"Analytics missing players: expected ~{boxscore_players}, got {analytics_players}"
            })

        # Check 3: ML features should exist if analytics exist
        ml_features = precompute.get('ml_feature_store_v2', 0)
        if analytics_players > 0 and ml_features == 0:
            self.gaps.append({
                'phase': 'Phase 4',
                'check': 'ML Features',
                'expected': 'Non-zero',
                'actual': 0,
                'severity': 'HIGH',
                'message': f"No ML features for {date} despite {analytics_players} players in analytics"
            })

        # Check 4: Predictions should exist if ML features exist
        prediction_players = predictions.get('unique_players', 0)
        if ml_features > 0 and prediction_players == 0:
            self.gaps.append({
                'phase': 'Phase 5',
                'check': 'Predictions',
                'expected': 'Non-zero',
                'actual': 0,
                'severity': 'HIGH',
                'message': f"No predictions for {date} despite {ml_features} ML feature records"
            })

        # Check 5: Prediction coverage (players with predictions vs analytics)
        if analytics_players > 0 and prediction_players > 0:
            coverage = prediction_players / analytics_players * 100
            if coverage < 50:
                self.gaps.append({
                    'phase': 'Phase 5',
                    'check': 'Prediction Coverage',
                    'expected': '50%+',
                    'actual': f"{coverage:.1f}%",
                    'severity': 'MEDIUM',
                    'message': f"Low prediction coverage: only {prediction_players}/{analytics_players} players ({coverage:.1f}%)"
                })

        # Check 6: Daily cache should have records
        daily_cache = precompute.get('player_daily_cache', 0)
        if analytics_players > 0 and daily_cache == 0:
            self.gaps.append({
                'phase': 'Phase 4',
                'check': 'Daily Cache',
                'expected': 'Non-zero',
                'actual': 0,
                'severity': 'MEDIUM',
                'message': f"No daily cache records for {date}"
            })

        # Check 7: Games with 0 active players (R-009 detection)
        games_with_zero_active = zero_active.get('games_with_zero_active', 0)
        total_games_checked = zero_active.get('total_games_checked', 0)
        if games_with_zero_active > 0:
            zero_active_game_ids = zero_active.get('zero_active_games', [])
            self.gaps.append({
                'phase': 'Phase 3',
                'check': 'Games with 0 Active Players',
                'expected': 'All games should have >= 1 active player',
                'actual': f"{games_with_zero_active}/{total_games_checked} games have 0 active",
                'severity': 'HIGH',
                'message': f"Found {games_with_zero_active} games with 0 active players: {zero_active_game_ids[:5]}"  # Limit to 5 game IDs
            })

        # Summary
        result = {
            'date': date,
            'gaps_found': len(self.gaps),
            'gaps': self.gaps,
            'stats': self.stats,
            'status': 'FAIL' if self.gaps else 'PASS'
        }

        if self.gaps:
            logger.warning(f"R-007: Found {len(self.gaps)} gaps for {date}")
            for gap in self.gaps:
                logger.warning(f"  [{gap['severity']}] {gap['phase']}: {gap['message']}")
        else:
            logger.info(f"R-007: All reconciliation checks passed for {date}")

        return result


def send_reconciliation_alert(result: Dict) -> bool:
    """Send Slack alert for reconciliation failures."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping alert")
        return False

    date = result['date']
    gaps = result['gaps']
    stats = result['stats']

    # Format gaps
    gap_text = "\n".join([
        f"• [{g['severity']}] {g['phase']}: {g['message']}"
        for g in gaps
    ])

    # Format stats
    schedule = stats.get('phase1_schedule', {})
    predictions = stats.get('phase5_predictions', {})

    try:
        payload = {
            "attachments": [{
                "color": "#FF0000" if any(g['severity'] == 'HIGH' for g in gaps) else "#FFA500",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f":warning: R-007: Pipeline Reconciliation Failed - {date}",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Found {len(gaps)} data gaps across pipeline phases*"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Gaps Detected:*\n```{gap_text}```"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Games (Final):*\n{schedule.get('final_games', 0)}"},
                            {"type": "mrkdwn", "text": f"*Predictions:*\n{predictions.get('total_predictions', 0)}"},
                        ]
                    },
                    {
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": "Review individual phase logs to identify root cause. Data may need manual reprocessing."
                        }]
                    }
                ]
            }]
        }

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Reconciliation alert sent for {date}")
        return True

    except Exception as e:
        logger.error(f"Failed to send reconciliation alert: {e}", exc_info=True)
        return False


@functions_framework.http
def reconcile_pipeline(request):
    """
    HTTP entry point for pipeline reconciliation.

    Query params:
        date: Optional date to check (defaults to yesterday)

    Returns:
        JSON with reconciliation results
    """
    try:
        # Get date to check (default: yesterday)
        now = datetime.now(ET)
        yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        date_str = request.args.get('date', yesterday)

        # Resolve special date keywords
        if date_str.upper() == 'TODAY':
            date = now.strftime('%Y-%m-%d')
        elif date_str.upper() == 'YESTERDAY':
            date = yesterday
        elif date_str.upper() == 'TOMORROW':
            date = (now + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            date = date_str

        logger.info(f"R-007: Pipeline reconciliation triggered for {date}")

        # Run reconciliation
        reconciler = PipelineReconciler()
        result = reconciler.reconcile(date)

        # Send alert if gaps found
        if result['gaps']:
            send_reconciliation_alert(result)

        return json.dumps(result, indent=2, default=str), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"R-007: Reconciliation failed: {e}", exc_info=True)
        return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}


# Pub/Sub trigger alternative (if using scheduler with Pub/Sub)
@functions_framework.cloud_event
def reconcile_pipeline_event(cloud_event):
    """Cloud Event entry point for Pub/Sub triggered reconciliation."""
    import base64

    try:
        # Parse message data if present
        data = {}
        if cloud_event.data and 'message' in cloud_event.data:
            message_data = cloud_event.data['message'].get('data', '')
            if message_data:
                data = json.loads(base64.b64decode(message_data).decode())

        # Get date from message or use yesterday
        now = datetime.now(ET)
        yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        date_str = data.get('date', yesterday)

        # Resolve special date keywords
        if date_str.upper() == 'TODAY':
            date = now.strftime('%Y-%m-%d')
        elif date_str.upper() == 'YESTERDAY':
            date = yesterday
        elif date_str.upper() == 'TOMORROW':
            date = (now + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            date = date_str

        logger.info(f"R-007: Pipeline reconciliation triggered (event) for {date}")

        # Run reconciliation
        reconciler = PipelineReconciler()
        result = reconciler.reconcile(date)

        # Send alert if gaps found
        if result['gaps']:
            send_reconciliation_alert(result)

        return result

    except Exception as e:
        logger.error(f"R-007: Reconciliation failed: {e}", exc_info=True)
        raise


@functions_framework.http
def health(request):
    """Health check endpoint for pipeline_reconciliation."""
    return json.dumps({
        'status': 'healthy',
        'function': 'pipeline_reconciliation',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
