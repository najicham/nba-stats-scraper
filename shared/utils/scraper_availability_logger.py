"""
Generalized Scraper Availability Logger

Tracks per-game data availability across ALL scrapers (not just BDL).
Writes to the `scraper_data_arrival` table for unified latency tracking.

Usage in any scraper:
    from shared.utils.scraper_availability_logger import log_scraper_availability

    # In transform_data() after processing:
    log_scraper_availability(
        scraper_name='bdl_box_scores',
        game_date=self.opts['date'],
        execution_id=self.run_id,
        games_data=[
            {'home_team': 'GSW', 'away_team': 'MIA', 'record_count': 24},
            {'home_team': 'LAL', 'away_team': 'BOS', 'record_count': 26},
        ],
        workflow=self.opts.get('workflow')
    )

Created: January 22, 2026
Purpose: Unified data arrival tracking for latency analysis
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GameDataStatus:
    """Represents one game's data availability status."""
    game_date: str
    home_team: str
    away_team: str
    was_available: bool
    record_count: Optional[int] = None
    data_status: str = "complete"  # complete, partial, missing, in_progress
    data_quality_score: Optional[float] = None
    game_start_time: Optional[datetime] = None
    game_id: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class ScraperAvailabilityLogger:
    """
    Logs per-game data availability for any scraper.

    Tracks:
    - Which games were expected (from schedule)
    - Which games were returned by the scraper
    - Latency from game end to data availability
    - Attempt number (how many times we've checked)
    """

    scraper_name: str
    game_date: str
    execution_id: str
    workflow: Optional[str] = None
    attempt_timestamp: Optional[datetime] = None
    source_url: Optional[str] = None

    # West coast teams (Pacific timezone)
    WEST_COAST_TEAMS: set = field(default_factory=lambda: {'GSW', 'LAL', 'LAC', 'SAC', 'POR', 'PHX'})

    def __post_init__(self):
        if self.attempt_timestamp is None:
            self.attempt_timestamp = datetime.now(timezone.utc)
        self._expected_games: Optional[List[Dict]] = None
        self._attempt_number: Optional[int] = None

    def get_expected_games(self) -> List[Dict]:
        """
        Get expected games for this date from the schedule.

        Returns list of dicts with:
        - home_team, away_team
        - game_start_time
        - game_id
        """
        if self._expected_games is not None:
            return self._expected_games

        try:
            from google.cloud import bigquery
            client = bigquery.Client()

            # Dynamic season year: Oct-Dec = current year, Jan-Sep = previous year
            query = """
            SELECT
                game_id,
                home_team_tricode AS home_team,
                away_team_tricode AS away_team,
                game_date_est AS game_start_time,
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
                {
                    "game_id": row.game_id,
                    "home_team": row.home_team,
                    "away_team": row.away_team,
                    "game_start_time": row.game_start_time,
                    "game_status": row.game_status,
                }
                for row in results
            ]

            logger.info(f"Found {len(self._expected_games)} expected games for {self.game_date}")
            return self._expected_games

        except Exception as e:
            logger.warning(f"Could not fetch expected games: {e}")
            self._expected_games = []
            return self._expected_games

    def get_attempt_number(self) -> int:
        """
        Get the attempt number for this game/scraper combination.
        Queries prior attempts from the tracking table.
        """
        if self._attempt_number is not None:
            return self._attempt_number

        try:
            from google.cloud import bigquery
            client = bigquery.Client()

            query = """
            SELECT COUNT(DISTINCT attempt_timestamp) AS prior_attempts
            FROM `nba-props-platform.nba_orchestration.scraper_data_arrival`
            WHERE scraper_name = @scraper_name
              AND game_date = @game_date
              AND attempt_timestamp < @current_attempt
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("scraper_name", "STRING", self.scraper_name),
                    bigquery.ScalarQueryParameter("game_date", "DATE", self.game_date),
                    bigquery.ScalarQueryParameter("current_attempt", "TIMESTAMP",
                                                  self.attempt_timestamp.isoformat()),
                ]
            )

            results = list(client.query(query, job_config=job_config).result())
            self._attempt_number = (results[0].prior_attempts if results else 0) + 1
            return self._attempt_number

        except Exception as e:
            logger.warning(f"Could not get attempt number: {e}")
            self._attempt_number = 1
            return self._attempt_number

    def log_availability(
        self,
        returned_games: List[Dict],
        dry_run: bool = False
    ) -> List[GameDataStatus]:
        """
        Log which games were available vs expected.

        Args:
            returned_games: List of dicts with:
                - home_team, away_team (required)
                - record_count (optional)
                - data_status: 'complete', 'partial', 'in_progress' (optional)
                - game_id (optional)
            dry_run: If True, don't write to BigQuery

        Returns:
            List of GameDataStatus records that were logged
        """
        expected = self.get_expected_games()
        attempt_number = self.get_attempt_number()

        # Build lookup of returned games
        returned_lookup = {}
        for g in returned_games:
            key = (g.get("home_team"), g.get("away_team"))
            returned_lookup[key] = g

        records = []

        # Process expected games
        for exp in expected:
            key = (exp["home_team"], exp["away_team"])
            returned = returned_lookup.get(key)

            is_west_coast = exp["home_team"] in self.WEST_COAST_TEAMS
            game_start = exp.get("game_start_time")
            estimated_end = None
            is_late_game = False

            if game_start:
                estimated_end = game_start + timedelta(hours=2, minutes=30)
                # Late game = started after 10 PM ET (22:00)
                if hasattr(game_start, 'hour'):
                    is_late_game = game_start.hour >= 22

            if returned:
                record = GameDataStatus(
                    game_date=self.game_date,
                    home_team=exp["home_team"],
                    away_team=exp["away_team"],
                    was_available=True,
                    record_count=returned.get("record_count"),
                    data_status=returned.get("data_status", "complete"),
                    data_quality_score=returned.get("data_quality_score"),
                    game_start_time=game_start,
                    game_id=exp.get("game_id") or returned.get("game_id"),
                )
            else:
                record = GameDataStatus(
                    game_date=self.game_date,
                    home_team=exp["home_team"],
                    away_team=exp["away_team"],
                    was_available=False,
                    data_status="missing",
                    game_start_time=game_start,
                    game_id=exp.get("game_id"),
                )

            records.append((record, is_west_coast, is_late_game, estimated_end))

        # Log any unexpected games (returned but not in schedule)
        expected_keys = {(e["home_team"], e["away_team"]) for e in expected}
        for key, returned in returned_lookup.items():
            if key not in expected_keys:
                home_team, away_team = key
                logger.warning(f"Unexpected game in response: {away_team} @ {home_team}")
                record = GameDataStatus(
                    game_date=self.game_date,
                    home_team=home_team,
                    away_team=away_team,
                    was_available=True,
                    record_count=returned.get("record_count"),
                    data_status=returned.get("data_status", "complete"),
                )
                is_west_coast = home_team in self.WEST_COAST_TEAMS
                records.append((record, is_west_coast, False, None))

        # Summary log
        available_count = sum(1 for r, _, _, _ in records if r.was_available)
        logger.info(
            f"{self.scraper_name} availability for {self.game_date}: "
            f"{available_count}/{len(records)} games (attempt #{attempt_number})"
        )

        # Write to BigQuery
        if not dry_run and records:
            self._write_to_bigquery(records, attempt_number)

        return [r for r, _, _, _ in records]

    def _write_to_bigquery(
        self,
        records: List[Tuple[GameDataStatus, bool, bool, Optional[datetime]]],
        attempt_number: int
    ) -> None:
        """Write availability records to BigQuery using batch loading (not streaming)."""
        try:
            from shared.config.gcp_config import get_table_id
            from shared.utils.bigquery_utils import insert_bigquery_rows

            table_id = get_table_id("nba_orchestration", "scraper_data_arrival")

            rows = []
            for record, is_west_coast, is_late_game, estimated_end in records:
                latency_minutes = None
                if estimated_end and self.attempt_timestamp:
                    # Handle timezone-aware comparison
                    attempt_ts = self.attempt_timestamp
                    if estimated_end.tzinfo is None:
                        estimated_end = estimated_end.replace(tzinfo=timezone.utc)
                    if attempt_ts.tzinfo is None:
                        attempt_ts = attempt_ts.replace(tzinfo=timezone.utc)
                    latency_minutes = int((attempt_ts - estimated_end).total_seconds() / 60)

                rows.append({
                    "attempt_timestamp": self.attempt_timestamp.isoformat(),
                    "scraper_name": self.scraper_name,
                    "workflow": self.workflow,
                    "execution_id": self.execution_id,
                    "attempt_number": attempt_number,
                    "game_date": self.game_date,
                    "home_team": record.home_team,
                    "away_team": record.away_team,
                    "game_id": record.game_id,
                    "was_available": record.was_available,
                    "record_count": record.record_count,
                    "data_status": record.data_status,
                    "data_quality_score": record.data_quality_score,
                    "game_start_time": record.game_start_time.isoformat() if record.game_start_time else None,
                    "estimated_game_end": estimated_end.isoformat() if estimated_end else None,
                    "latency_minutes": latency_minutes,
                    "is_west_coast": is_west_coast,
                    "is_late_game": is_late_game,
                    "error_message": record.error_message,
                    "source_url": self.source_url,
                })

            # Use batch loading instead of streaming to avoid 90-minute buffer conflicts
            success = insert_bigquery_rows(table_id, rows)

            if not success:
                logger.error(
                    f"BigQuery batch insert failed for scraper_data_arrival. "
                    f"Scraper: {self.scraper_name}, Date: {self.game_date}"
                )
            else:
                logger.info(f"Logged {len(rows)} availability records for {self.scraper_name}")

        except Exception as e:
            import traceback
            logger.error(
                f"Failed to log scraper availability: {e}. "
                f"Scraper: {self.scraper_name}, Date: {self.game_date}. "
                f"Traceback: {traceback.format_exc()}"
            )


def log_scraper_availability(
    scraper_name: str,
    game_date: str,
    execution_id: str,
    games_data: List[Dict],
    workflow: Optional[str] = None,
    source_url: Optional[str] = None,
    dry_run: bool = False
) -> List[GameDataStatus]:
    """
    Convenience function to log scraper data availability.

    Args:
        scraper_name: Name of the scraper (e.g., 'bdl_box_scores', 'nbac_gamebook')
        game_date: Date being scraped (YYYY-MM-DD)
        execution_id: Links to scraper_execution_log
        games_data: List of dicts with game data:
            - home_team, away_team (required)
            - record_count (optional)
            - data_status: 'complete', 'partial', 'in_progress' (optional)
        workflow: Which workflow triggered this scrape
        source_url: The URL/endpoint that was scraped
        dry_run: If True, don't write to BigQuery

    Returns:
        List of GameDataStatus records

    Example:
        log_scraper_availability(
            scraper_name='bdl_box_scores',
            game_date='2026-01-21',
            execution_id='abc12345',
            games_data=[
                {'home_team': 'GSW', 'away_team': 'MIA', 'record_count': 24},
                {'home_team': 'LAL', 'away_team': 'BOS', 'record_count': 26},
            ],
            workflow='post_game_window_2'
        )
    """
    logger_instance = ScraperAvailabilityLogger(
        scraper_name=scraper_name,
        game_date=game_date,
        execution_id=execution_id,
        workflow=workflow,
        source_url=source_url,
    )

    return logger_instance.log_availability(games_data, dry_run=dry_run)


def extract_games_from_boxscores(
    box_scores: List[Dict],
    home_team_path: str = "game.home_team.abbreviation",
    away_team_path: str = "game.visitor_team.abbreviation",
) -> List[Dict]:
    """
    Helper to extract unique games from box score data.

    Args:
        box_scores: List of player box score rows
        home_team_path: Dot-notation path to home team abbrev in each row
        away_team_path: Dot-notation path to away team abbrev in each row

    Returns:
        List of unique games with home_team, away_team, record_count
    """
    def get_nested(obj: Dict, path: str) -> Any:
        """Get nested value using dot notation."""
        for key in path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(key, {})
            else:
                return None
        return obj if obj != {} else None

    games = {}
    for row in box_scores:
        home = get_nested(row, home_team_path)
        away = get_nested(row, away_team_path)

        if not home or not away:
            continue

        key = (home, away)
        if key not in games:
            games[key] = {
                "home_team": home,
                "away_team": away,
                "record_count": 0,
            }
        games[key]["record_count"] += 1

    return list(games.values())


# Exports
__all__ = [
    'ScraperAvailabilityLogger',
    'GameDataStatus',
    'log_scraper_availability',
    'extract_games_from_boxscores',
]
