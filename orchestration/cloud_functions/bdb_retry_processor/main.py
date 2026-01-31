"""
BigDataBall Retry Processor Cloud Function

Cloud Function that processes games waiting for BDB data and triggers re-processing
when data becomes available.

Trigger: Pub/Sub message from bdb-retry-trigger topic (scheduled every 6 hours)
Action:
    1. Query pending_bdb_games for games needing retry
    2. Check if BDB data is now available
    3. Trigger Phase 3 re-run when data available
    4. Update check counts and status
    5. Mark as failed after max retries (72 checks = 3 days)

Created: Session 53 (2026-01-31)
"""

import base64
import json
import logging
import os
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional

import functions_framework
from google.cloud import bigquery
from google.cloud import pubsub_v1

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
PHASE3_TOPIC = 'nba-phase3-trigger'
MIN_SHOTS_PER_GAME = 50  # Minimum shots for "complete" BDB data
MAX_CHECK_COUNT = 72  # 72 checks × 6 hours = 18 days max wait


class BDBRetryProcessor:
    """Process pending BDB games and trigger re-runs when data available."""

    def __init__(self):
        self.bq_client = bigquery.Client()
        try:
            self.publisher = pubsub_v1.PublisherClient()
            self.topic_path = self.publisher.topic_path(PROJECT_ID, PHASE3_TOPIC)
        except Exception as e:
            logger.warning(f"Could not initialize Pub/Sub: {e}")
            self.publisher = None

    def get_pending_games(self, max_age_days: int = 14) -> List[Dict]:
        """Get games from pending_bdb_games that need retry."""
        cutoff_date = date.today() - timedelta(days=max_age_days)
        logger.info(f"Querying pending games with cutoff_date={cutoff_date}, max_age_days={max_age_days}")

        query = f"""
        SELECT
            game_date,
            game_id,
            nba_game_id,
            home_team,
            away_team,
            fallback_source,
            original_processed_at,
            status,
            quality_before_rerun,
            shot_zones_complete_before,
            bdb_check_count,
            last_bdb_check_at
        FROM `{PROJECT_ID}.nba_orchestration.pending_bdb_games`
        WHERE status = 'pending_bdb'
          AND bdb_check_count < {MAX_CHECK_COUNT}
          AND game_date >= '{cutoff_date}'
        ORDER BY game_date ASC, bdb_check_count ASC
        LIMIT 50
        """

        try:
            logger.info(f"Running query against project {PROJECT_ID}")
            job = self.bq_client.query(query)
            result = job.result()  # Wait for query to complete
            rows = list(result)
            logger.info(f"Query returned {len(rows)} rows")

            # Convert to list of dicts manually
            games = []
            for row in rows:
                games.append(dict(row))

            logger.info(f"Found {len(games)} games pending BDB retry")
            return games
        except Exception as e:
            logger.error(f"Error querying pending games: {e}", exc_info=True)
            return []

    def check_bdb_availability(self, game_id: str, game_date) -> Dict:
        """Check if BDB data is now available for a game."""
        # Normalize game_id format
        if isinstance(game_id, str) and game_id.isdigit():
            game_id_padded = game_id.zfill(10)
        else:
            game_id_padded = str(game_id).zfill(10)

        query = f"""
        SELECT
            COUNT(*) as total_events,
            COUNTIF(event_type = 'shot') as shot_count,
            COUNTIF(event_type = 'shot' AND shot_distance IS NOT NULL) as shots_with_distance
        FROM `{PROJECT_ID}.nba_raw.bigdataball_play_by_play`
        WHERE LPAD(CAST(bdb_game_id AS STRING), 10, '0') = '{game_id_padded}'
          AND game_date = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            if result.empty:
                return {'available': False, 'shot_count': 0, 'shots_with_distance': 0}

            row = result.iloc[0]
            shots_with_distance = int(row['shots_with_distance']) if row['shots_with_distance'] else 0

            return {
                'available': shots_with_distance >= MIN_SHOTS_PER_GAME,
                'shot_count': int(row['shot_count']) if row['shot_count'] else 0,
                'shots_with_distance': shots_with_distance
            }
        except Exception as e:
            logger.error(f"Error checking BDB availability for {game_id}: {e}")
            return {'available': False, 'shot_count': 0, 'shots_with_distance': 0, 'error': str(e)}

    def trigger_phase3_rerun(self, game: Dict) -> bool:
        """Trigger Phase 3 re-processing for a game."""
        if not self.publisher:
            logger.warning("Pub/Sub not available, cannot trigger re-run")
            return False

        try:
            game_id = game.get('nba_game_id') or game.get('game_id')
            game_date = game['game_date']
            if hasattr(game_date, 'isoformat'):
                game_date = game_date.isoformat()

            message = json.dumps({
                'game_date': str(game_date),
                'game_id': game_id,
                'trigger_reason': 'bdb_data_available',
                'source': 'bdb_retry_processor',
                'original_quality': game.get('quality_before_rerun', 'unknown'),
                'priority': 'normal'
            }).encode('utf-8')

            future = self.publisher.publish(self.topic_path, message)
            future.result(timeout=30)
            logger.info(f"Triggered Phase 3 re-run for {game_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger Phase 3 re-run: {e}")
            return False

    def update_game_status(self, game: Dict, new_status: str, bdb_info: Optional[Dict] = None) -> None:
        """Update the status of a game in pending_bdb_games table."""
        game_id = game.get('nba_game_id') or game.get('game_id')
        game_date = game['game_date']

        # Build update fields
        update_fields = []
        if new_status != 'pending_bdb':
            update_fields.append(f"status = '{new_status}'")
            update_fields.append("completed_at = CURRENT_TIMESTAMP()")

        # Always increment check count
        update_fields.append("bdb_check_count = bdb_check_count + 1")
        update_fields.append("last_bdb_check_at = CURRENT_TIMESTAMP()")
        update_fields.append("updated_at = CURRENT_TIMESTAMP()")

        # Add BDB info if available
        if bdb_info:
            update_fields.append(f"bdb_shots_found = {bdb_info.get('shots_with_distance', 0)}")
            if bdb_info.get('available'):
                update_fields.append("bdb_available_at = CURRENT_TIMESTAMP()")

        update_sql = ", ".join(update_fields)

        query = f"""
        UPDATE `{PROJECT_ID}.nba_orchestration.pending_bdb_games`
        SET {update_sql}
        WHERE game_date = '{game_date}'
          AND (game_id = '{game_id}' OR nba_game_id = '{game_id}')
          AND status = 'pending_bdb'
        """

        try:
            self.bq_client.query(query).result()
            logger.info(f"Updated {game_id} -> {new_status} (check #{game.get('bdb_check_count', 0) + 1})")
        except Exception as e:
            logger.error(f"Failed to update game {game_id}: {e}")

    def run(self, max_age_days: int = 14) -> Dict:
        """Main processing loop."""
        logger.info("=" * 60)
        logger.info(f"BDB RETRY PROCESSOR - {datetime.now().isoformat()}")
        logger.info("=" * 60)

        stats = {
            'games_checked': 0,
            'games_available': 0,
            'games_still_pending': 0,
            'games_failed': 0,
            'phase3_triggered': 0
        }

        # Get pending games
        games = self.get_pending_games(max_age_days)

        if not games:
            logger.info("No games pending BDB retry")
            return stats

        stats['games_checked'] = len(games)

        # Process each game
        for game in games:
            game_id = game.get('nba_game_id') or game.get('game_id')
            check_num = (game.get('bdb_check_count') or 0) + 1

            logger.info(f"Checking {game['game_date']} {game.get('away_team', '')}@{game.get('home_team', '')} "
                       f"(check #{check_num}/{MAX_CHECK_COUNT})")

            # Check if BDB data is now available
            bdb_info = self.check_bdb_availability(game_id, game['game_date'])

            if bdb_info.get('available'):
                # SUCCESS: BDB data is now available
                logger.info(f"  BDB data available ({bdb_info['shots_with_distance']} shots)")
                stats['games_available'] += 1

                # Trigger Phase 3 re-run
                if self.trigger_phase3_rerun(game):
                    stats['phase3_triggered'] += 1
                    self.update_game_status(game, 'completed_bdb', bdb_info)
                else:
                    # Failed to trigger, keep pending
                    self.update_game_status(game, 'pending_bdb', bdb_info)
                    stats['games_still_pending'] += 1

            elif check_num >= MAX_CHECK_COUNT:
                # FAILED: Hit max retry count
                logger.warning(f"  Max retries reached ({MAX_CHECK_COUNT} checks)")
                stats['games_failed'] += 1
                self.update_game_status(game, 'failed_max_retries', bdb_info)

            else:
                # PENDING: Still waiting for BDB data
                logger.info(f"  BDB data not available yet ({bdb_info.get('shots_with_distance', 0)} shots)")
                stats['games_still_pending'] += 1
                self.update_game_status(game, 'pending_bdb', bdb_info)

        logger.info("=" * 60)
        logger.info(f"SUMMARY: {stats}")
        logger.info("=" * 60)

        return stats


# Cloud Function entry point - Pub/Sub trigger
@functions_framework.cloud_event
def bdb_retry_handler(cloud_event):
    """
    Cloud Function entry point - triggered by Pub/Sub.

    Triggered by: bdb-retry-trigger topic (scheduled every 6 hours)
    """
    logger.info("BDB Retry Processor started (Pub/Sub trigger)")

    # Parse event data if present
    max_age_days = 14
    try:
        if cloud_event.data:
            pubsub_message = cloud_event.data.get('message', {})
            if 'data' in pubsub_message:
                message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
                data = json.loads(message_data)
                max_age_days = data.get('max_age_days', 14)
                logger.info(f"Event data: {data}")
    except Exception as e:
        logger.warning(f"Could not parse event data, using defaults: {e}")

    processor = BDBRetryProcessor()
    stats = processor.run(max_age_days=max_age_days)

    logger.info(f"BDB Retry Processor complete: {stats}")
    return json.dumps(stats)


# HTTP entry point for testing
@functions_framework.http
def bdb_retry_http(request):
    """HTTP entry point for testing."""
    logger.info("BDB Retry Processor started (HTTP)")

    max_age_days = int(request.args.get('max_age_days', 14))

    processor = BDBRetryProcessor()
    stats = processor.run(max_age_days=max_age_days)

    return json.dumps(stats), 200, {'Content-Type': 'application/json'}


if __name__ == '__main__':
    # Local testing
    logging.basicConfig(level=logging.INFO)
    processor = BDBRetryProcessor()
    stats = processor.run()
    print(f"Stats: {stats}")
