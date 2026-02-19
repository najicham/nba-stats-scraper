"""shared/utils/schedule_guard.py — answers "do regular-season games exist on this date?" """
import logging

logger = logging.getLogger(__name__)


def has_regular_season_games(game_date: str, project: str = 'nba-props-platform', bq_client=None) -> bool:
    """Return True if nba_reference.nba_schedule has regular-season/playoff games on game_date.

    Fails open (returns True) on any error so real game-day errors still surface.

    Args:
        game_date: Date string in YYYY-MM-DD format (e.g. "2026-02-18")
        project: GCP project ID
        bq_client: Optional existing BigQuery client (avoids creating a new one)

    Returns:
        True if regular-season or playoff games (game_id LIKE '002%' or '004%') exist;
        False if confirmed break day; True on any BQ error (fail-open).
    """
    try:
        from google.cloud import bigquery
        client = bq_client or bigquery.Client(project=project)
        query = """
        SELECT COUNT(*) as cnt
        FROM `nba_reference.nba_schedule`
        WHERE game_date = @game_date
          AND (game_id LIKE '002%' OR game_id LIKE '004%')
        """
        params = [bigquery.ScalarQueryParameter("game_date", "DATE", game_date)]
        result = list(client.query(
            query,
            job_config=bigquery.QueryJobConfig(query_parameters=params)
        ))
        return result[0].cnt > 0 if result else False
    except Exception as e:
        logger.warning(
            "schedule_guard: check failed for %s, assuming games exist: %s",
            game_date, e
        )
        return True  # Fail open — never silence real game-day errors
