"""
Post-Grading Picks Re-Export Cloud Function

Re-exports picks files after grading completes so that actual scores and
hit/miss results are included in the JSON served to the frontend.

The picks exporter already JOINs with player_game_summary at query time,
so re-running the export after grading populates actuals without any
re-materialization step.

Trigger: Pub/Sub topic `nba-grading-complete`
Receives messages with:
- target_date: The date that was graded (YYYY-MM-DD)
- status: Grading outcome (success, skipped, etc.)
- graded_count: Number of predictions graded

Actions on success:
1. Re-export picks/{date}.json with actuals via AllSubsetsPicksExporter
2. Refresh subsets/season.json via SeasonSubsetPicksExporter
3. Backfill actuals into signal_best_bets_picks table
4. Re-export tonight/all-players.json with actuals
5. Re-export best-bets/all.json with updated ultra_record
6. Re-export best-bets/record.json and history.json with graded results
7. Patch signal-best-bets/{date}.json with actuals and day record

Version: 1.6
Created: 2026-02-13 (Session 242)
Updated: 2026-02-14 (Session 254) - Added signal best bets grading backfill
Updated: 2026-02-15 (Session 263) - Added model_performance_daily computation
Updated: 2026-02-22 (Session 332) - Added tonight JSON re-export with actuals
Updated: 2026-02-25 (Session 342) - Added best-bets/all.json re-export for fresh ultra_record
Updated: 2026-02-25 (Session 343) - Added record.json + history.json re-export post-grading
Updated: 2026-03-01 (Session 377) - Patch signal-best-bets JSON with actuals + fallback for manual_override picks
"""

import base64
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict

# Ensure deployed package root is in Python path (Cloud Functions runtime fix)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Lazy-loaded exporters
_picks_exporter = None
_season_exporter = None


def get_picks_exporter():
    """Get or create AllSubsetsPicksExporter (lazy initialization)."""
    global _picks_exporter
    if _picks_exporter is None:
        try:
            from data_processors.publishing.all_subsets_picks_exporter import AllSubsetsPicksExporter
            _picks_exporter = AllSubsetsPicksExporter()
            logger.info("AllSubsetsPicksExporter initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize AllSubsetsPicksExporter: {e}", exc_info=True)
            raise
    return _picks_exporter


def get_season_exporter():
    """Get or create SeasonSubsetPicksExporter (lazy initialization)."""
    global _season_exporter
    if _season_exporter is None:
        try:
            from data_processors.publishing.season_subset_picks_exporter import SeasonSubsetPicksExporter
            _season_exporter = SeasonSubsetPicksExporter()
            logger.info("SeasonSubsetPicksExporter initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SeasonSubsetPicksExporter: {e}", exc_info=True)
            raise
    return _season_exporter


def backfill_signal_best_bets(target_date: str) -> int:
    """
    Backfill actual_points and prediction_correct into signal_best_bets_picks
    from prediction_accuracy after grading completes.

    Args:
        target_date: Date that was graded (YYYY-MM-DD)

    Returns:
        Number of rows updated
    """
    from google.cloud import bigquery
    from shared.clients.bigquery_pool import get_bigquery_client

    bq_client = get_bigquery_client(project_id=PROJECT_ID)

    # Check if any signal best bets exist for this date
    check_query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
    WHERE game_date = @target_date
    """
    check_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    check_result = bq_client.query(check_query, job_config=check_config).result()
    row = next(check_result, None)
    if not row or row.cnt == 0:
        logger.info(f"No signal best bets found for {target_date}, skipping backfill")
        return 0

    # Update with actuals from prediction_accuracy
    # First pass: match on system_id (normal picks)
    update_query = f"""
    UPDATE `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` sbp
    SET
      actual_points = pa.actual_points,
      prediction_correct = pa.prediction_correct
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
    WHERE sbp.player_lookup = pa.player_lookup
      AND sbp.game_id = pa.game_id
      AND sbp.game_date = pa.game_date
      AND pa.system_id = sbp.system_id
      AND sbp.game_date = @target_date
      AND pa.prediction_correct IS NOT NULL
    """
    update_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    job = bq_client.query(update_query, job_config=update_config)
    job.result(timeout=60)
    rows_updated = job.num_dml_affected_rows or 0

    # Second pass: backfill picks with non-standard system_ids (e.g. manual_override)
    # that couldn't match on system_id — use player_game_summary actuals instead
    fallback_query = f"""
    UPDATE `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` sbp
    SET
      actual_points = pgs.points,
      prediction_correct = CASE
        WHEN sbp.recommendation = 'OVER' AND pgs.points > sbp.line_value THEN TRUE
        WHEN sbp.recommendation = 'UNDER' AND pgs.points < sbp.line_value THEN TRUE
        WHEN pgs.points = sbp.line_value THEN NULL
        ELSE FALSE
      END
    FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
    WHERE sbp.player_lookup = pgs.player_lookup
      AND sbp.game_date = pgs.game_date
      AND sbp.game_date = @target_date
      AND sbp.actual_points IS NULL
      AND pgs.points IS NOT NULL
    """
    fallback_job = bq_client.query(fallback_query, job_config=update_config)
    fallback_job.result(timeout=60)
    fallback_updated = fallback_job.num_dml_affected_rows or 0

    if fallback_updated > 0:
        logger.info(f"Fallback backfilled {fallback_updated} signal best bets for {target_date}")
        rows_updated += fallback_updated

    logger.info(f"Backfilled {rows_updated} signal best bets for {target_date}")
    return rows_updated


def parse_pubsub_message(cloud_event) -> Dict:
    """Parse Pub/Sub CloudEvent and extract message data."""
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


@functions_framework.cloud_event
def main(cloud_event):
    """
    Handle grading completion event and re-export picks with actuals.

    Args:
        cloud_event: CloudEvent from Pub/Sub (nba-grading-complete topic)
    """
    start_time = datetime.now(timezone.utc)
    logger.info("Post-grading export triggered")

    # Parse incoming message
    message_data = parse_pubsub_message(cloud_event)

    target_date = message_data.get('target_date')
    status = message_data.get('status')
    graded_count = message_data.get('graded_count', 0)
    correlation_id = message_data.get('correlation_id', 'unknown')

    if not target_date:
        logger.error("No target_date in grading completion message")
        return

    logger.info(
        f"[{correlation_id}] Post-grading export for {target_date} "
        f"(status={status}, graded_count={graded_count})"
    )

    # Only re-export on successful grading
    if status != 'success':
        logger.info(
            f"[{correlation_id}] Skipping re-export — grading status was '{status}', not 'success'"
        )
        return

    if graded_count == 0:
        logger.info(f"[{correlation_id}] Skipping re-export — 0 predictions graded")
        return

    results = {}

    # 1. Re-export picks/{date}.json with actuals
    try:
        exporter = get_picks_exporter()
        picks_path = exporter.export(target_date, trigger_source='post-grading')
        results['picks_path'] = picks_path
        logger.info(f"[{correlation_id}] Re-exported picks to {picks_path}")
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to re-export picks for {target_date}: {e}",
            exc_info=True
        )
        results['picks_error'] = str(e)

    # 2. Refresh subsets/season.json
    try:
        season_exporter = get_season_exporter()
        season_path = season_exporter.export()
        results['season_path'] = season_path
        logger.info(f"[{correlation_id}] Refreshed season.json at {season_path}")
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to refresh season.json: {e}",
            exc_info=True
        )
        results['season_error'] = str(e)

    # 3. Backfill actuals into signal_best_bets_picks
    try:
        backfilled = backfill_signal_best_bets(target_date)
        results['signal_backfill'] = backfilled
        logger.info(
            f"[{correlation_id}] Backfilled {backfilled} signal best bets for {target_date}"
        )
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to backfill signal best bets for {target_date}: {e}",
            exc_info=True
        )
        results['signal_backfill_error'] = str(e)

    # 4. Compute signal health for the graded date (Session 259)
    try:
        from ml.signals.signal_health import compute_signal_health, write_health_rows
        from shared.clients.bigquery_pool import get_bigquery_client as _get_bq

        bq = _get_bq(project_id=PROJECT_ID)
        health_rows = compute_signal_health(bq, target_date)
        if health_rows:
            written = write_health_rows(bq, health_rows)
            results['signal_health'] = written
            logger.info(
                f"[{correlation_id}] Computed signal health for {target_date}: "
                f"{written} signals"
            )
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to compute signal health for {target_date}: {e}",
            exc_info=True
        )
        results['signal_health_error'] = str(e)

    # 5. Compute model performance daily metrics (Session 263)
    try:
        from datetime import date as date_type
        from ml.analysis.model_performance import compute_for_date as compute_perf, write_rows as write_perf_rows
        from shared.clients.bigquery_pool import get_bigquery_client as _get_bq2

        bq2 = _get_bq2(project_id=PROJECT_ID)
        perf_rows = compute_perf(bq2, date_type.fromisoformat(target_date))
        if perf_rows:
            written = write_perf_rows(bq2, perf_rows)
            results['model_performance'] = written
            logger.info(
                f"[{correlation_id}] Computed model performance for {target_date}: "
                f"{written} models"
            )
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to compute model performance for {target_date}: {e}",
            exc_info=True
        )
        results['model_performance_error'] = str(e)

    # 6. Re-export tonight/all-players.json with actuals (Session 332)
    try:
        from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
        tonight_exporter = TonightAllPlayersExporter()
        tonight_path = tonight_exporter.export(target_date)
        results['tonight_path'] = tonight_path
        logger.info(
            f"[{correlation_id}] Re-exported tonight JSON with actuals: {tonight_path}"
        )
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to re-export tonight JSON for {target_date}: {e}",
            exc_info=True
        )
        results['tonight_error'] = str(e)

    # 7. Re-export best-bets/all.json with updated grading (Session 342)
    try:
        from data_processors.publishing.best_bets_all_exporter import BestBetsAllExporter
        all_exporter = BestBetsAllExporter()
        all_path = all_exporter.export(target_date)
        results['best_bets_all_path'] = all_path
        logger.info(f"[{correlation_id}] Re-exported best-bets/all.json: {all_path}")
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to re-export best-bets/all.json for {target_date}: {e}",
            exc_info=True
        )
        results['best_bets_all_error'] = str(e)

    # 8. Re-export best-bets/record.json and history.json with graded results (Session 343)
    try:
        from data_processors.publishing.best_bets_record_exporter import BestBetsRecordExporter
        record_exporter = BestBetsRecordExporter()
        record_paths = record_exporter.export(target_date)
        results['best_bets_record_path'] = record_paths.get('record', '')
        results['best_bets_history_path'] = record_paths.get('history', '')
        logger.info(
            f"[{correlation_id}] Re-exported best-bets record+history: {record_paths}"
        )
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to re-export best-bets record for {target_date}: {e}",
            exc_info=True
        )
        results['best_bets_record_error'] = str(e)

    # 9. Patch signal-best-bets/{date}.json with actuals from signal_best_bets_picks (Session 377)
    try:
        from google.cloud import storage as gcs_storage
        from google.cloud import bigquery as bq_module
        from shared.clients.bigquery_pool import get_bigquery_client as _get_bq3

        bq3 = _get_bq3(project_id=PROJECT_ID)
        actuals_query = f"""
        SELECT player_lookup, actual_points, prediction_correct
        FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
        WHERE game_date = @target_date
          AND actual_points IS NOT NULL
        """
        actuals_config = bq_module.QueryJobConfig(
            query_parameters=[
                bq_module.ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )
        actuals_rows = {
            row.player_lookup: {'actual': row.actual_points, 'correct': row.prediction_correct}
            for row in bq3.query(actuals_query, job_config=actuals_config).result()
        }

        if actuals_rows:
            bucket_name = 'nba-props-platform-api'
            blob_path = f'v1/signal-best-bets/{target_date}.json'
            client = gcs_storage.Client(project=PROJECT_ID)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            if blob.exists():
                bb_data = json.loads(blob.download_as_text())
                wins, losses = 0, 0
                for pick in bb_data.get('picks', []):
                    lookup = pick.get('player_lookup')
                    if lookup in actuals_rows:
                        pick['actual'] = actuals_rows[lookup]['actual']
                        pick['result'] = 'WIN' if actuals_rows[lookup]['correct'] else 'LOSS'
                        if actuals_rows[lookup]['correct']:
                            wins += 1
                        else:
                            losses += 1

                # Update record
                total = wins + losses
                bb_data['record'] = {
                    'season': bb_data.get('record', {}).get('season', {}),
                    'month': bb_data.get('record', {}).get('month', {}),
                    'week': bb_data.get('record', {}).get('week', {}),
                    'day': {
                        'wins': wins,
                        'losses': losses,
                        'pct': round(wins / total, 3) if total > 0 else 0.0,
                    },
                }
                bb_data['graded_at'] = datetime.now(timezone.utc).isoformat()

                blob.upload_from_string(
                    json.dumps(bb_data, indent=2, default=str),
                    content_type='application/json'
                )
                results['signal_best_bets_patched'] = f'{wins}W-{losses}L'
                logger.info(
                    f"[{correlation_id}] Patched signal-best-bets JSON for {target_date}: "
                    f"{wins}W-{losses}L"
                )
            else:
                logger.info(f"[{correlation_id}] No signal-best-bets JSON found for {target_date}")
        else:
            logger.info(f"[{correlation_id}] No actuals to patch for {target_date}")
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to patch signal-best-bets JSON for {target_date}: {e}",
            exc_info=True
        )
        results['signal_best_bets_error'] = str(e)

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(
        f"[{correlation_id}] Post-grading export complete for {target_date} "
        f"in {duration:.1f}s: {results}"
    )
