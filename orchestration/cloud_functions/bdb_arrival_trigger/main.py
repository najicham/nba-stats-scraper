"""
BigDataBall Arrival Trigger

Cloud Function that detects when BDB data arrives and triggers re-processing
for games that were processed without it.

Trigger: Pub/Sub message from BDB scraper OR scheduled check
Action:
    1. Check which games now have BDB data
    2. Find games that were processed without BDB (via pending_bdb_games table)
    3. For each game where rerun is safe (>2h before game):
       - Trigger Phase 3 re-run
       - Update pending_bdb_games status
    4. Log everything for audit trail

Created: Session 39 (2026-01-30)
"""

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
MIN_HOURS_BEFORE_GAME = 2  # Don't re-run if less than 2 hours before game


class BDBTrigger:
    """Handles BDB arrival detection and re-run triggering."""

    def __init__(self):
        self.bq_client = bigquery.Client()
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(PROJECT_ID, PHASE3_TOPIC)

    def check_bdb_arrivals(self, game_date: Optional[date] = None) -> List[Dict]:
        """
        Find games that now have BDB data but were processed without it.

        Returns list of games ready for re-run.
        """
        if game_date is None:
            # Check last 3 days
            end_date = date.today()
            start_date = end_date - timedelta(days=3)
            date_filter = f"BETWEEN '{start_date}' AND '{end_date}'"
        else:
            date_filter = f"= '{game_date}'"

        query = f"""
        WITH pending AS (
            SELECT
                game_date,
                game_id,
                nba_game_id,
                home_team,
                away_team,
                fallback_source,
                original_processed_at
            FROM `{PROJECT_ID}.nba_orchestration.pending_bdb_games`
            WHERE status = 'pending_bdb'
              AND game_date {date_filter}
        ),
        bdb_now_available AS (
            SELECT
                game_date,
                game_id,
                LPAD(CAST(bdb_game_id AS STRING), 10, '0') as nba_game_id,
                COUNT(*) as shot_count
            FROM `{PROJECT_ID}.nba_raw.bigdataball_play_by_play`
            WHERE game_date {date_filter}
              AND event_type = 'shot'
              AND shot_distance IS NOT NULL
              AND bdb_game_id IS NOT NULL
            GROUP BY 1, 2, 3
            HAVING COUNT(*) >= 50  -- At least 50 shots (one game)
        ),
        game_times AS (
            SELECT
                game_id,
                game_date,
                -- Estimate game start: 7 PM ET default
                TIMESTAMP(CONCAT(CAST(game_date AS STRING), ' 19:00:00'), 'America/New_York') as game_start_time
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date {date_filter}
        )
        SELECT
            p.game_date,
            p.game_id,
            p.nba_game_id,
            p.home_team,
            p.away_team,
            p.fallback_source,
            p.original_processed_at,
            b.shot_count as bdb_shots,
            gt.game_start_time,
            TIMESTAMP_DIFF(gt.game_start_time, CURRENT_TIMESTAMP(), HOUR) as hours_until_game
        FROM pending p
        INNER JOIN bdb_now_available b
            ON p.game_date = b.game_date
            AND (p.nba_game_id = b.nba_game_id OR p.game_id = b.game_id)
        LEFT JOIN game_times gt
            ON p.nba_game_id = gt.game_id
        WHERE TIMESTAMP_DIFF(gt.game_start_time, CURRENT_TIMESTAMP(), HOUR) > {MIN_HOURS_BEFORE_GAME}
           OR gt.game_start_time IS NULL  -- Allow if we don't know game time
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error checking BDB arrivals: {e}")
            return []

    def check_games_too_late_for_rerun(self, game_date: Optional[date] = None) -> List[Dict]:
        """
        Find games where BDB arrived but it's too late to re-run.

        These should be logged for the audit trail.
        """
        if game_date is None:
            end_date = date.today()
            start_date = end_date - timedelta(days=3)
            date_filter = f"BETWEEN '{start_date}' AND '{end_date}'"
        else:
            date_filter = f"= '{game_date}'"

        query = f"""
        WITH pending AS (
            SELECT game_date, game_id, nba_game_id
            FROM `{PROJECT_ID}.nba_orchestration.pending_bdb_games`
            WHERE status = 'pending_bdb'
              AND game_date {date_filter}
        ),
        bdb_now_available AS (
            SELECT
                game_date,
                LPAD(CAST(bdb_game_id AS STRING), 10, '0') as nba_game_id
            FROM `{PROJECT_ID}.nba_raw.bigdataball_play_by_play`
            WHERE game_date {date_filter}
              AND bdb_game_id IS NOT NULL
            GROUP BY 1, 2
        ),
        game_times AS (
            SELECT
                game_id,
                game_date,
                TIMESTAMP(CONCAT(CAST(game_date AS STRING), ' 19:00:00'), 'America/New_York') as game_start_time
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date {date_filter}
        )
        SELECT
            p.game_date,
            p.game_id,
            p.nba_game_id,
            TIMESTAMP_DIFF(gt.game_start_time, CURRENT_TIMESTAMP(), HOUR) as hours_until_game
        FROM pending p
        INNER JOIN bdb_now_available b ON p.nba_game_id = b.nba_game_id
        INNER JOIN game_times gt ON p.nba_game_id = gt.game_id
        WHERE TIMESTAMP_DIFF(gt.game_start_time, CURRENT_TIMESTAMP(), HOUR) <= {MIN_HOURS_BEFORE_GAME}
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error checking late arrivals: {e}")
            return []

    def trigger_phase3_rerun(self, game: Dict) -> bool:
        """Trigger Phase 3 re-processing for a game."""
        try:
            message = json.dumps({
                'game_date': str(game['game_date']),
                'game_id': game.get('game_id') or game.get('nba_game_id'),
                'trigger_reason': 'bdb_arrival',
                'original_processed_at': str(game.get('original_processed_at')),
                'is_rerun': True,
                'source': 'bdb_arrival_trigger'
            }).encode('utf-8')

            future = self.publisher.publish(self.topic_path, message)
            future.result(timeout=30)

            logger.info(
                f"Triggered Phase 3 re-run for {game['game_date']} / "
                f"{game.get('game_id') or game.get('nba_game_id')}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to trigger Phase 3 re-run: {e}")
            return False

    def update_pending_status(
        self,
        game_date: date,
        game_id: str,
        status: str,
        resolution_type: str,
        resolution_notes: str
    ) -> None:
        """Update the status of a pending BDB game."""
        query = f"""
        UPDATE `{PROJECT_ID}.nba_orchestration.pending_bdb_games`
        SET
            status = '{status}',
            resolution_type = '{resolution_type}',
            resolution_notes = '{resolution_notes}',
            bdb_detected_at = CURRENT_TIMESTAMP(),
            {'bdb_rerun_at = CURRENT_TIMESTAMP(),' if status == 'reran' else ''}
            updated_at = CURRENT_TIMESTAMP()
        WHERE game_date = '{game_date}'
          AND (game_id = '{game_id}' OR nba_game_id = '{game_id}')
        """

        try:
            self.bq_client.query(query).result()
            logger.info(f"Updated pending status for {game_date}/{game_id} to {status}")
        except Exception as e:
            logger.error(f"Failed to update pending status: {e}")

    def log_late_arrival(self, game: Dict) -> None:
        """Log that BDB arrived too late to re-run."""
        self.update_pending_status(
            game_date=game['game_date'],
            game_id=game.get('nba_game_id') or game.get('game_id'),
            status='blocked',
            resolution_type='late_bdb_arrival',
            resolution_notes=(
                f"BDB data arrived {abs(game.get('hours_until_game', 0)):.1f}h before game. "
                f"Re-run blocked (minimum {MIN_HOURS_BEFORE_GAME}h required)."
            )
        )

    def run(self, game_date: Optional[date] = None) -> Dict:
        """
        Main entry point - check for BDB arrivals and trigger re-runs.

        Returns summary stats.
        """
        stats = {
            'games_ready': 0,
            'reruns_triggered': 0,
            'games_too_late': 0,
            'errors': 0
        }

        # Find games ready for re-run
        ready_games = self.check_bdb_arrivals(game_date)
        stats['games_ready'] = len(ready_games)

        logger.info(f"Found {len(ready_games)} games ready for re-run")

        for game in ready_games:
            if self.trigger_phase3_rerun(game):
                stats['reruns_triggered'] += 1
                self.update_pending_status(
                    game_date=game['game_date'],
                    game_id=game.get('nba_game_id') or game.get('game_id'),
                    status='reran',
                    resolution_type='auto_rerun',
                    resolution_notes=(
                        f"BDB data arrived with {game.get('bdb_shots', 0)} shots. "
                        f"Auto re-run triggered {game.get('hours_until_game', 'N/A')}h before game."
                    )
                )
            else:
                stats['errors'] += 1

        # Log games where BDB arrived too late
        late_games = self.check_games_too_late_for_rerun(game_date)
        stats['games_too_late'] = len(late_games)

        for game in late_games:
            self.log_late_arrival(game)
            logger.warning(
                f"BDB arrived too late for {game['game_date']}/{game.get('nba_game_id')}: "
                f"{game.get('hours_until_game', 0):.1f}h until game"
            )

        logger.info(f"BDB Arrival Trigger complete: {stats}")
        return stats


# Cloud Function entry point
@functions_framework.cloud_event
def bdb_arrival_handler(cloud_event):
    """
    Cloud Function entry point - triggered by Pub/Sub or scheduler.

    Handles:
    - BDB scraper completion events
    - Scheduled checks (every 30 minutes)
    """
    logger.info("BDB Arrival Trigger started")

    # Parse event data
    game_date = None
    if cloud_event.data:
        try:
            data = json.loads(cloud_event.data.decode('utf-8'))
            if 'game_date' in data:
                game_date = date.fromisoformat(data['game_date'])
            logger.info(f"Event data: {data}")
        except Exception as e:
            logger.warning(f"Could not parse event data: {e}")

    trigger = BDBTrigger()
    stats = trigger.run(game_date=game_date)

    return json.dumps(stats)


# HTTP entry point for testing
@functions_framework.http
def bdb_arrival_http(request):
    """HTTP entry point for testing."""
    logger.info("BDB Arrival Trigger started (HTTP)")

    game_date = None
    if request.args.get('game_date'):
        game_date = date.fromisoformat(request.args.get('game_date'))

    trigger = BDBTrigger()
    stats = trigger.run(game_date=game_date)

    return json.dumps(stats), 200, {'Content-Type': 'application/json'}


if __name__ == '__main__':
    # Local testing
    logging.basicConfig(level=logging.INFO)
    trigger = BDBTrigger()
    stats = trigger.run()
    print(f"Stats: {stats}")
