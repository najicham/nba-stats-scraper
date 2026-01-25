"""
File: shared/utils/bdl_availability_logger.py

BDL Game Availability Logger - Track per-game data availability

This module logs which specific games BDL returned on each scrape attempt,
enabling precise latency measurement. The workflow is:

1. Before scraping: Get expected games from schedule
2. After scraping: Compare expected vs returned
3. Log to BigQuery: Which games were available, which weren't

Usage in scraper:
    from shared.utils.bdl_availability_logger import BdlAvailabilityLogger

    # In transform_data():
    logger = BdlAvailabilityLogger(
        game_date=self.opts["date"],
        execution_id=self.run_id,
        workflow=self.opts.get("workflow")
    )

    # Get games returned by BDL
    returned_games = logger.extract_games_from_response(self.data["boxScores"])

    # Log availability (compares against schedule)
    logger.log_availability(returned_games)

Created: January 21, 2026
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Slack alerting for missing games
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
MISSING_GAMES_ALERT_ENABLED = os.environ.get('MISSING_GAMES_ALERT_ENABLED', 'true').lower() == 'true'


@dataclass
class GameAvailability:
    """Represents one game's availability status."""
    game_date: str
    home_team: str
    away_team: str
    was_available: bool
    player_count: Optional[int] = None
    game_status: Optional[str] = None
    bdl_game_id: Optional[int] = None
    expected_start_time: Optional[datetime] = None
    is_west_coast: bool = False


class BdlAvailabilityLogger:
    """
    Logs per-game BDL data availability to BigQuery.

    This enables answering: "When did BDL first return data for game X?"
    by tracking each scrape attempt and which games were in the response.
    """

    # West coast teams (Pacific timezone)
    WEST_COAST_TEAMS = {'GSW', 'LAL', 'LAC', 'SAC', 'POR', 'PHX'}

    def __init__(
        self,
        game_date: str,
        execution_id: str,
        workflow: Optional[str] = None,
        scrape_timestamp: Optional[datetime] = None
    ):
        """
        Initialize the logger.

        Args:
            game_date: Date being scraped (YYYY-MM-DD)
            execution_id: Links to scraper_execution_log
            workflow: Which workflow triggered this (e.g., 'post_game_window_2')
            scrape_timestamp: When scrape occurred (defaults to now)
        """
        self.game_date = game_date
        self.execution_id = execution_id
        self.workflow = workflow
        self.scrape_timestamp = scrape_timestamp or datetime.now(timezone.utc)

        self._expected_games: Optional[List[Tuple[str, str, datetime]]] = None

    def extract_games_from_response(
        self,
        box_scores: List[Dict]
    ) -> Dict[Tuple[str, str], Dict]:
        """
        Extract unique games from BDL box scores response.

        Args:
            box_scores: List of player box score rows from BDL

        Returns:
            Dict mapping (home_team, away_team) -> game info
        """
        games = {}

        for row in box_scores:
            game = row.get("game", {})
            if not game:
                continue

            home_team = game.get("home_team", {}).get("abbreviation")
            away_team = game.get("visitor_team", {}).get("abbreviation")

            if not home_team or not away_team:
                continue

            key = (home_team, away_team)

            if key not in games:
                games[key] = {
                    "bdl_game_id": game.get("id"),
                    "game_status": game.get("status"),
                    "player_count": 0,
                }

            games[key]["player_count"] += 1

        return games

    def get_expected_games(self) -> List[Tuple[str, str, Optional[datetime]]]:
        """
        Get expected games for this date from the schedule.

        Note: We include ALL games (not just Final), because when scraping at
        1 AM or 2 AM ET, games may still be showing as In Progress in the
        schedule even though they've finished and BDL has the data.

        Returns:
            List of (home_team, away_team, start_time) tuples
        """
        if self._expected_games is not None:
            return self._expected_games

        try:
            from google.cloud import bigquery
            client = bigquery.Client()

            # FIXED: Removed game_status = 3 filter
            # When scraping at 10 PM, 1 AM, 2 AM ET, games may not yet be
            # marked as Final in the schedule. We want to track ALL scheduled
            # games and compare against what BDL returns.
            # Dynamic season year: Oct-Dec = current year, Jan-Sep = previous year
            query = """
            SELECT
                home_team_tricode,
                away_team_tricode,
                game_date_est,
                game_status
            FROM `nba-props-platform.nba_raw.nbac_schedule`
            WHERE game_date = @game_date
              AND season_year = CASE
                  WHEN EXTRACT(MONTH FROM @game_date) >= 10
                  THEN EXTRACT(YEAR FROM @game_date)
                  ELSE EXTRACT(YEAR FROM @game_date) - 1
                END
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", self.game_date)
                ]
            )

            results = client.query(query, job_config=job_config).result()

            self._expected_games = [
                (row.home_team_tricode, row.away_team_tricode, row.game_date_est)
                for row in results
            ]

            logger.info(f"Found {len(self._expected_games)} expected games for {self.game_date}")
            return self._expected_games

        except Exception as e:
            logger.warning(f"Could not fetch expected games from schedule: {e}")
            self._expected_games = []
            return self._expected_games

    def log_availability(
        self,
        returned_games: Dict[Tuple[str, str], Dict],
        dry_run: bool = False
    ) -> List[GameAvailability]:
        """
        Log which games were available vs expected.

        Args:
            returned_games: Games returned by BDL (from extract_games_from_response)
            dry_run: If True, don't write to BigQuery (for testing)

        Returns:
            List of GameAvailability records that were logged
        """
        expected = self.get_expected_games()
        records = []

        # Track which returned games match expected
        matched_returned = set()

        # Log expected games (whether available or not)
        for home_team, away_team, start_time in expected:
            key = (home_team, away_team)
            returned = returned_games.get(key)

            is_west_coast = home_team in self.WEST_COAST_TEAMS
            estimated_end = None
            if start_time:
                from datetime import timedelta
                estimated_end = start_time + timedelta(hours=2, minutes=30)

            record = GameAvailability(
                game_date=self.game_date,
                home_team=home_team,
                away_team=away_team,
                was_available=returned is not None,
                player_count=returned.get("player_count") if returned else None,
                game_status=returned.get("game_status") if returned else None,
                bdl_game_id=returned.get("bdl_game_id") if returned else None,
                expected_start_time=start_time,
                is_west_coast=is_west_coast,
            )
            records.append(record)

            if returned:
                matched_returned.add(key)

        # Log any unexpected games (in BDL but not in schedule)
        for key, game_info in returned_games.items():
            if key not in matched_returned:
                home_team, away_team = key
                record = GameAvailability(
                    game_date=self.game_date,
                    home_team=home_team,
                    away_team=away_team,
                    was_available=True,
                    player_count=game_info.get("player_count"),
                    game_status=game_info.get("game_status"),
                    bdl_game_id=game_info.get("bdl_game_id"),
                    expected_start_time=None,  # Not in schedule
                    is_west_coast=home_team in self.WEST_COAST_TEAMS,
                )
                records.append(record)
                logger.warning(f"Unexpected game in BDL response: {away_team} @ {home_team}")

        # Log summary
        available_count = sum(1 for r in records if r.was_available)
        missing_count = len(records) - available_count
        logger.info(
            f"BDL availability for {self.game_date}: "
            f"{available_count}/{len(records)} games available"
        )

        # Alert on missing games and queue for auto-retry
        if missing_count > 0 and MISSING_GAMES_ALERT_ENABLED:
            missing_records = [r for r in records if not r.was_available]
            self._send_missing_games_alert(missing_records)
            # Queue missing games for auto-retry
            self._queue_missing_games_for_retry(missing_records)

        # Write to BigQuery
        if not dry_run and records:
            self._write_to_bigquery(records)

        return records

    def _send_missing_games_alert(self, missing_records: List[GameAvailability]) -> bool:
        """
        Send Slack alert when games are missing from BDL response.

        Uses send_slack_webhook_with_retry for automatic retry on transient failures.

        Args:
            missing_records: List of GameAvailability records for missing games

        Returns:
            True if alert sent successfully, False otherwise
        """
        if not SLACK_WEBHOOK_URL:
            logger.debug("SLACK_WEBHOOK_URL not configured, skipping missing games alert")
            return False

        if not missing_records:
            return False

        try:
            from shared.utils.slack_retry import send_slack_webhook_with_retry

            missing_games_str = "\n".join([
                f"• {r.away_team}@{r.home_team}" +
                (f" (expected start: {r.expected_start_time.strftime('%I:%M %p ET')})" if r.expected_start_time else "")
                for r in missing_records
            ])

            payload = {
                "attachments": [{
                    "color": "#FF9800",  # Orange for warning
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": ":warning: BDL API Missing Games",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{len(missing_records)} game(s) expected but NOT returned by BDL API*"
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Date:*\n{self.game_date}"},
                                {"type": "mrkdwn", "text": f"*Workflow:*\n{self.workflow or 'manual'}"},
                            ]
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*Missing Games:*\n{missing_games_str}"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [{
                                "type": "mrkdwn",
                                "text": ":bulb: These games may not have completed yet, or BDL API may be delayed. Check back later or use alternative source (NBA.com)."
                            }]
                        }
                    ]
                }]
            }

            success = send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, payload)
            if success:
                logger.info(f"Missing games alert sent for {self.game_date}: {len(missing_records)} games")
            return success

        except Exception as e:
            logger.warning(f"Failed to send missing games alert: {e}")
            return False

    def _queue_missing_games_for_retry(self, missing_records: List[GameAvailability]) -> int:
        """
        Queue missing games for auto-retry in the failed_processor_queue.

        This enables the auto_retry_processor cloud function to automatically
        retry fetching missing games after a delay.

        Args:
            missing_records: List of GameAvailability records for missing games

        Returns:
            Number of games successfully queued for retry
        """
        if not missing_records:
            return 0

        AUTO_RETRY_ENABLED = os.environ.get('AUTO_RETRY_MISSING_GAMES', 'true').lower() == 'true'
        if not AUTO_RETRY_ENABLED:
            logger.debug("Auto-retry for missing games is disabled")
            return 0

        try:
            from google.cloud import bigquery
            from datetime import timedelta
            import uuid

            client = bigquery.Client()

            # Queue each missing game for retry
            rows_to_insert = []
            now = datetime.now(timezone.utc)
            # First retry after 30 minutes (games may still be finishing)
            next_retry = now + timedelta(minutes=30)

            for record in missing_records:
                game_key = f"{record.away_team}@{record.home_team}"

                # Check if already queued (avoid duplicates)
                check_query = f"""
                SELECT COUNT(*) as cnt
                FROM `nba_orchestration.failed_processor_queue`
                WHERE game_date = '{self.game_date}'
                  AND processor_name = 'bdl_player_box_scores'
                  AND status IN ('pending', 'retrying')
                  AND JSON_EXTRACT_SCALAR(metadata, '$.game_key') = '{game_key}'
                """

                try:
                    result = list(client.query(check_query).result())
                    if result and result[0].cnt > 0:
                        logger.debug(f"Game {game_key} already queued for retry, skipping")
                        continue
                except Exception as e:
                    logger.warning(f"Could not check for existing queue entry: {e}")

                rows_to_insert.append({
                    "id": str(uuid.uuid4()),
                    "game_date": self.game_date,
                    "phase": "phase_2",
                    "processor_name": "bdl_player_box_scores",
                    "error_message": f"Game {game_key} not returned by BDL API",
                    "error_type": "missing_game",
                    "retry_count": 0,
                    "max_retries": 3,
                    "first_failure_at": now.isoformat(),
                    "next_retry_at": next_retry.isoformat(),
                    "status": "pending",
                    "correlation_id": self.execution_id,
                    "metadata": json.dumps({
                        "game_key": game_key,
                        "home_team": record.home_team,
                        "away_team": record.away_team,
                        "workflow": self.workflow,
                        "expected_start_time": record.expected_start_time.isoformat() if record.expected_start_time else None,
                        "is_west_coast": record.is_west_coast
                    }),
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat()
                })

            if not rows_to_insert:
                logger.debug("No new games to queue for retry (all already queued)")
                return 0

            # Insert into failed_processor_queue
            table_ref = client.dataset("nba_orchestration").table("failed_processor_queue")

            errors = client.insert_rows_json(table_ref, rows_to_insert)

            if errors:
                logger.warning(f"Errors inserting retry queue entries: {errors}")
                return 0

            logger.info(
                f"Queued {len(rows_to_insert)} missing games for auto-retry "
                f"(next retry at {next_retry.strftime('%H:%M:%S UTC')})"
            )
            return len(rows_to_insert)

        except Exception as e:
            logger.warning(f"Failed to queue missing games for retry: {e}")
            return 0

    def _write_to_bigquery(self, records: List[GameAvailability]) -> None:
        """Write availability records to BigQuery using batch loading (not streaming)."""
        try:
            from shared.config.gcp_config import get_table_id
            from shared.utils.bigquery_utils import insert_bigquery_rows

            table_id = get_table_id("nba_orchestration", "bdl_game_scrape_attempts")

            rows = []
            for r in records:
                estimated_end = None
                if r.expected_start_time:
                    from datetime import timedelta
                    estimated_end = r.expected_start_time + timedelta(hours=2, minutes=30)

                rows.append({
                    "scrape_timestamp": self.scrape_timestamp.isoformat(),
                    "execution_id": self.execution_id,
                    "workflow": self.workflow,
                    "game_date": self.game_date,
                    "home_team": r.home_team,
                    "away_team": r.away_team,
                    "was_available": r.was_available,
                    "player_count": r.player_count,
                    "game_status": r.game_status,
                    "bdl_game_id": r.bdl_game_id,
                    "was_expected": r.expected_start_time is not None,
                    "expected_start_time": r.expected_start_time.isoformat() if r.expected_start_time else None,
                    "estimated_end_time": estimated_end.isoformat() if estimated_end else None,
                    "is_west_coast": r.is_west_coast,
                })

            # Use batch loading instead of streaming to avoid 90-minute buffer conflicts
            success = insert_bigquery_rows(table_id, rows)

            if not success:
                logger.error(
                    f"BigQuery batch insert failed for bdl_game_scrape_attempts. "
                    f"Table: {table_id}, Rows attempted: {len(rows)}, "
                    f"Game date: {self.game_date}, Workflow: {self.workflow}"
                )
            else:
                logger.info(f"Logged {len(rows)} game availability records to BigQuery")

        except Exception as e:
            # Log detailed error for debugging - this helps identify why 0 rows
            import traceback
            logger.error(
                f"Failed to log BDL availability to BigQuery: {e}. "
                f"Table: nba-props-platform.nba_orchestration.bdl_game_scrape_attempts, "
                f"Game date: {self.game_date}, Workflow: {self.workflow}, "
                f"Records to write: {len(records)}. "
                f"Traceback: {traceback.format_exc()}"
            )


def log_bdl_game_availability(
    game_date: str,
    execution_id: str,
    box_scores: List[Dict],
    workflow: Optional[str] = None,
    dry_run: bool = False
) -> List[GameAvailability]:
    """
    Convenience function to log BDL game availability.

    Usage in scraper transform_data():
        from shared.utils.bdl_availability_logger import log_bdl_game_availability

        log_bdl_game_availability(
            game_date=self.opts["date"],
            execution_id=self.run_id,
            box_scores=self.data["boxScores"],
            workflow=self.opts.get("workflow")
        )
    """
    logger = BdlAvailabilityLogger(
        game_date=game_date,
        execution_id=execution_id,
        workflow=workflow
    )

    returned_games = logger.extract_games_from_response(box_scores)
    return logger.log_availability(returned_games, dry_run=dry_run)
