#!/usr/bin/env python3
"""
Postponement Detection Module

Detects postponed/rescheduled games through multiple signals:
1. "Final" status with NULL scores (should never happen)
2. Same game_id appearing on multiple dates (rescheduled)
3. News articles mentioning postponement keywords
4. Final games without any boxscore data

This module is designed to be imported by both:
- bin/validation/detect_postponements.py (CLI tool)
- orchestration/cloud_functions/daily_health_summary/main.py (Cloud Function)

Usage:
    from shared.utils.postponement_detector import PostponementDetector, get_affected_predictions

    detector = PostponementDetector(sport="NBA")
    anomalies = detector.detect_all(date.today())

    for anomaly in anomalies:
        if anomaly['severity'] == 'CRITICAL':
            # Handle critical anomaly
            pass

Created: 2026-01-25
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class PostponementDetector:
    """Detects postponed/rescheduled games through multiple signals."""

    POSTPONEMENT_KEYWORDS = [
        'postpone', 'postponed', 'postponement',
        'cancel', 'cancelled', 'canceled',
        'reschedule', 'rescheduled',
        'delay', 'delayed',
        'moved to', 'move to'
    ]

    def __init__(self, sport: str = "NBA", bq_client: Optional[bigquery.Client] = None):
        """
        Initialize the detector.

        Args:
            sport: Sport to check (NBA or MLB)
            bq_client: Optional BigQuery client (creates one if not provided)
        """
        self.sport = sport
        self.client = bq_client or bigquery.Client()
        self.anomalies: List[Dict[str, Any]] = []
        self._handled_game_ids: set = set()  # Cache of already-handled games

    def _get_handled_game_ids(self, check_date: date) -> set:
        """
        Get game_ids that are already tracked in game_postponements table.

        Games with status 'confirmed' or 'resolved' are considered handled
        and will be filtered from detection results (unless include_handled=True).

        Args:
            check_date: Date to check around (looks ±7 days)

        Returns:
            Set of game_ids that are already handled
        """
        query = """
        SELECT DISTINCT game_id
        FROM `nba_orchestration.game_postponements`
        WHERE sport = @sport
          AND original_date >= DATE_SUB(@check_date, INTERVAL 7 DAY)
          AND original_date <= DATE_ADD(@check_date, INTERVAL 7 DAY)
          AND status IN ('confirmed', 'resolved')
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("sport", "STRING", self.sport),
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result()
            handled = {row.game_id for row in results}
            logger.info(f"Found {len(handled)} already-handled postponements in tracking table")
            return handled
        except Exception as e:
            logger.warning(f"Failed to query game_postponements table: {e}")
            return set()

    def detect_all(self, check_date: date, include_handled: bool = False) -> List[Dict[str, Any]]:
        """
        Run all detection methods for a given date.

        Args:
            check_date: Date to check for anomalies
            include_handled: If True, include games already tracked in game_postponements
                           table with status 'confirmed' or 'resolved'.
                           Default False filters these out to reduce noise.

        Returns:
            List of anomaly dictionaries with severity, type, details
        """
        logger.info(f"Running postponement detection for {check_date} (include_handled={include_handled})")

        self.anomalies = []

        # Load already-handled games for filtering (unless include_handled=True)
        if not include_handled:
            self._handled_game_ids = self._get_handled_game_ids(check_date)
        else:
            self._handled_game_ids = set()

        # Detection methods
        self._detect_final_without_scores(check_date)
        self._detect_rescheduled_games(check_date)
        self._detect_final_without_boxscores(check_date)
        self._detect_news_postponements(check_date)

        return self.anomalies

    def _detect_final_without_scores(self, check_date: date):
        """Detect games marked 'Final' but with NULL scores."""
        query = """
        SELECT
            game_id,
            game_date,
            game_status,
            game_status_text,
            home_team_tricode,
            away_team_tricode,
            home_team_score,
            away_team_score
        FROM `nba_raw.nbac_schedule`
        WHERE game_date = @check_date
          AND game_status = 3  -- Final
          AND (home_team_score IS NULL OR away_team_score IS NULL)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result())
        except Exception as e:
            logger.error(f"Failed to detect final without scores: {e}", exc_info=True)
            return

        for row in results:
            # Skip already-handled games
            if row.game_id in self._handled_game_ids:
                logger.debug(f"Skipping already-handled game: {row.game_id}")
                continue

            teams = f"{row.away_team_tricode}@{row.home_team_tricode}"
            predictions_affected = get_affected_predictions(
                row.game_date, teams, self.client
            )

            self.anomalies.append({
                'type': 'FINAL_WITHOUT_SCORES',
                'severity': 'CRITICAL',
                'game_id': row.game_id,
                'game_date': str(row.game_date),
                'teams': teams,
                'predictions_affected': predictions_affected,
                'detection_source': 'schedule_anomaly',
                'details': f"Game marked as '{row.game_status_text}' but scores are NULL",
                'recommended_action': 'Mark as postponed, check news for details'
            })
            logger.warning(
                f"ANOMALY: {teams} on {row.game_date} marked Final but no scores "
                f"({predictions_affected} predictions affected)"
            )

    def _detect_rescheduled_games(self, check_date: date):
        """Detect same game_id appearing on multiple dates."""
        query = """
        SELECT
            game_id,
            ARRAY_AGG(DISTINCT game_date ORDER BY game_date) as dates,
            ARRAY_AGG(DISTINCT game_status_text) as statuses,
            ANY_VALUE(home_team_tricode) as home_team,
            ANY_VALUE(away_team_tricode) as away_team
        FROM `nba_raw.nbac_schedule`
        WHERE game_date >= DATE_SUB(@check_date, INTERVAL 7 DAY)
          AND game_date <= DATE_ADD(@check_date, INTERVAL 7 DAY)
        GROUP BY game_id
        HAVING COUNT(DISTINCT game_date) > 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result())
        except Exception as e:
            logger.error(f"Failed to detect rescheduled games: {e}", exc_info=True)
            return

        for row in results:
            # Skip already-handled games
            if row.game_id in self._handled_game_ids:
                logger.debug(f"Skipping already-handled game: {row.game_id}")
                continue

            dates = [str(d) for d in row.dates]
            teams = f"{row.away_team}@{row.home_team}"
            original_date = datetime.strptime(dates[0], '%Y-%m-%d').date()
            predictions_affected = get_affected_predictions(
                original_date, teams, self.client
            )

            self.anomalies.append({
                'type': 'GAME_RESCHEDULED',
                'severity': 'HIGH',
                'game_id': row.game_id,
                'original_date': dates[0],
                'new_date': dates[-1] if len(dates) > 1 else None,
                'all_dates': dates,
                'teams': teams,
                'predictions_affected': predictions_affected,
                'statuses': list(row.statuses),
                'detection_source': 'schedule_duplicate',
                'details': f"Game appears on multiple dates: {', '.join(dates)}",
                'recommended_action': 'Invalidate predictions for original date'
            })
            logger.warning(
                f"ANOMALY: {teams} (game_id={row.game_id}) "
                f"appears on multiple dates: {dates} ({predictions_affected} predictions affected)"
            )

    def _detect_final_without_boxscores(self, check_date: date):
        """Detect Final games that have no boxscore data anywhere."""
        query = """
        WITH schedule AS (
            SELECT DISTINCT
                game_id,
                home_team_tricode,
                away_team_tricode
            FROM `nba_raw.nbac_schedule`
            WHERE game_date = @check_date
              AND game_status = 3
        ),
        gamebook_games AS (
            SELECT DISTINCT game_id
            FROM `nba_raw.nbac_gamebook_player_stats`
            WHERE game_date = @check_date
        )
        SELECT
            s.game_id,
            s.home_team_tricode,
            s.away_team_tricode,
            g.game_id IS NOT NULL as has_gamebook
        FROM schedule s
        LEFT JOIN gamebook_games g ON CONCAT(
            FORMAT_DATE('%Y%m%d', @check_date), '_',
            s.away_team_tricode, '_', s.home_team_tricode
        ) = g.game_id
        WHERE g.game_id IS NULL
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result())
        except Exception as e:
            logger.error(f"Failed to detect final without boxscores: {e}", exc_info=True)
            return

        for row in results:
            # Skip already-handled games
            if row.game_id in self._handled_game_ids:
                logger.debug(f"Skipping already-handled game: {row.game_id}")
                continue

            # Check if we already have this as another anomaly type
            existing = [a for a in self.anomalies if a.get('game_id') == row.game_id]
            if existing:
                existing[0]['has_boxscores'] = False
                continue

            self.anomalies.append({
                'type': 'FINAL_NO_BOXSCORES',
                'severity': 'HIGH',
                'game_id': row.game_id,
                'game_date': str(check_date),
                'teams': f"{row.away_team_tricode}@{row.home_team_tricode}",
                'has_gamebook': row.has_gamebook,
                'detection_source': 'cross_validation',
                'details': "Game marked Final but no boxscore data in Gamebook",
                'recommended_action': 'Check if game was postponed or data scraping failed'
            })
            logger.warning(
                f"ANOMALY: {row.away_team_tricode}@{row.home_team_tricode} "
                f"marked Final but no boxscore data found"
            )

    def _detect_news_postponements(self, check_date: date):
        """Scan news articles for postponement mentions."""
        pattern = '|'.join(self.POSTPONEMENT_KEYWORDS)

        query = f"""
        SELECT
            article_id,
            title,
            summary,
            published_at,
            source
        FROM `nba_raw.news_articles_raw`
        WHERE DATE(published_at) = @check_date
          AND (
            REGEXP_CONTAINS(LOWER(title), r'{pattern}')
            OR REGEXP_CONTAINS(LOWER(summary), r'{pattern}')
          )
        ORDER BY published_at DESC
        LIMIT 20
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result())
        except Exception as e:
            logger.error(f"Failed to detect news postponements: {e}", exc_info=True)
            return

        if results:
            article_ids = [row.article_id for row in results]
            titles = [row.title for row in results]

            self.anomalies.append({
                'type': 'NEWS_POSTPONEMENT_MENTIONED',
                'severity': 'MEDIUM',
                'game_date': str(check_date),
                'article_count': len(results),
                'article_ids': article_ids[:5],
                'sample_titles': titles[:3],
                'detection_source': 'news_scan',
                'details': f"Found {len(results)} news articles mentioning postponement",
                'recommended_action': 'Review articles and cross-reference with schedule'
            })
            logger.info(
                f"Found {len(results)} news articles mentioning postponement on {check_date}"
            )

    def log_to_bigquery(self, anomaly: Dict[str, Any]) -> Optional[str]:
        """
        Log a detected anomaly to BigQuery.

        Logs ALL anomaly types for complete audit trail.
        Auto-confirms GAME_RESCHEDULED anomalies when new_date is in the future.

        Returns:
            game_id if logged successfully, None otherwise
        """
        game_id = anomaly.get('game_id')
        if not game_id:
            game_id = f"NEWS_{anomaly.get('game_date', 'unknown')}"

        original_date = anomaly.get('original_date') or anomaly.get('game_date')
        new_date = anomaly.get('new_date')
        predictions_count = anomaly.get('predictions_affected', 0)

        # Auto-confirm rescheduled games when new_date is in the future
        # This prevents them from sitting in 'detected' status requiring manual fix
        auto_confirm = False
        if anomaly.get('type') == 'GAME_RESCHEDULED' and new_date:
            try:
                if isinstance(new_date, str):
                    new_date_parsed = datetime.strptime(new_date, '%Y-%m-%d').date()
                else:
                    new_date_parsed = new_date
                if new_date_parsed >= date.today():
                    auto_confirm = True
                    logger.info(
                        f"Auto-confirming rescheduled game {game_id}: "
                        f"{original_date} → {new_date} (future date)"
                    )
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse new_date for auto-confirm: {e}")

        if auto_confirm:
            query = """
            INSERT INTO `nba_orchestration.game_postponements`
            (sport, game_id, original_date, new_date, reason, detection_source, detection_details,
             predictions_invalidated, status, confirmed_at)
            VALUES
            (@sport, @game_id, @original_date, @new_date, @reason, @detection_source, @detection_details,
             @predictions_count, 'confirmed', CURRENT_TIMESTAMP())
            """
        else:
            query = """
            INSERT INTO `nba_orchestration.game_postponements`
            (sport, game_id, original_date, new_date, reason, detection_source, detection_details,
             predictions_invalidated, status)
            VALUES
            (@sport, @game_id, @original_date, @new_date, @reason, @detection_source, @detection_details,
             @predictions_count, 'detected')
            """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("sport", "STRING", self.sport),
                bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
                bigquery.ScalarQueryParameter("original_date", "DATE", original_date),
                bigquery.ScalarQueryParameter("new_date", "DATE", new_date),
                bigquery.ScalarQueryParameter("reason", "STRING", anomaly.get('details', '')),
                bigquery.ScalarQueryParameter("detection_source", "STRING", anomaly['detection_source']),
                bigquery.ScalarQueryParameter("detection_details", "STRING", json.dumps(anomaly)),
                bigquery.ScalarQueryParameter("predictions_count", "INT64", predictions_count),
            ]
        )

        try:
            self.client.query(query, job_config=job_config).result()
            logger.info(f"Logged {anomaly['type']} anomaly for {game_id} to BigQuery")
            return game_id
        except Exception as e:
            logger.error(f"Failed to log anomaly: {e}", exc_info=True)
            return None

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of detected anomalies.

        Returns:
            Dictionary with counts by severity and type
        """
        summary = {
            'total': len(self.anomalies),
            'by_severity': {},
            'by_type': {},
            'has_critical': False,
            'has_high': False,
        }

        for anomaly in self.anomalies:
            severity = anomaly.get('severity', 'UNKNOWN')
            atype = anomaly.get('type', 'UNKNOWN')

            summary['by_severity'][severity] = summary['by_severity'].get(severity, 0) + 1
            summary['by_type'][atype] = summary['by_type'].get(atype, 0) + 1

            if severity == 'CRITICAL':
                summary['has_critical'] = True
            elif severity == 'HIGH':
                summary['has_high'] = True

        return summary


def get_affected_predictions(
    game_date: date,
    teams: Optional[str] = None,
    bq_client: Optional[bigquery.Client] = None
) -> int:
    """
    Count predictions that would be affected by a postponement.

    Args:
        game_date: Date to check
        teams: Optional team string like "GSW@MIN" to filter specific game
        bq_client: Optional BigQuery client

    Returns:
        Count of predictions affected
    """
    client = bq_client or bigquery.Client()
    date_str = game_date.strftime('%Y%m%d')

    if teams and '@' in teams:
        away, home = teams.split('@')
        pattern = f"{date_str}_{away}_{home}"
        query = """
        SELECT COUNT(*) as count
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND game_id = @game_id_pattern
          AND invalidation_reason IS NULL
        """
    else:
        pattern = f"{date_str}%"
        query = """
        SELECT COUNT(*) as count
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND game_id LIKE @game_id_pattern
          AND invalidation_reason IS NULL
        """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            bigquery.ScalarQueryParameter("game_id_pattern", "STRING", pattern),
        ]
    )

    try:
        result = list(client.query(query, job_config=job_config).result())
        return result[0].count if result else 0
    except Exception as e:
        logger.warning(f"Failed to count affected predictions: {e}")
        return 0


def _invalidate_predictions_for_postponement(
    client: bigquery.Client,
    nba_game_id: str,
    original_date: date
) -> int:
    """
    Invalidate predictions for a postponed game.

    Args:
        client: BigQuery client
        nba_game_id: NBA.com game ID (e.g., '0022500692')
        original_date: Original scheduled date

    Returns:
        Number of predictions invalidated
    """
    # Build the game_id pattern used in predictions (YYYYMMDD_AWAY_HOME format)
    # We need to find the teams from the schedule or postponement record
    try:
        # First, try to get teams from postponement record or schedule
        team_query = """
        SELECT DISTINCT
            away_team_tricode,
            home_team_tricode
        FROM `nba_raw.nbac_schedule`
        WHERE game_id = @nba_game_id
          AND game_date >= DATE_SUB(@original_date, INTERVAL 7 DAY)
          AND game_date <= DATE_ADD(@original_date, INTERVAL 7 DAY)
        LIMIT 1
        """
        team_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("nba_game_id", "STRING", nba_game_id),
                bigquery.ScalarQueryParameter("original_date", "DATE", original_date),
            ]
        )
        team_result = list(client.query(team_query, job_config=team_config).result())

        if not team_result:
            logger.warning(f"Could not find teams for game {nba_game_id}")
            return 0

        away_team = team_result[0].away_team_tricode
        home_team = team_result[0].home_team_tricode
        date_str = original_date.strftime('%Y%m%d')
        prediction_game_id = f"{date_str}_{away_team}_{home_team}"

        # Invalidate predictions
        invalidate_query = """
        UPDATE `nba_predictions.player_prop_predictions`
        SET
            invalidation_reason = @reason,
            invalidated_at = CURRENT_TIMESTAMP()
        WHERE game_date = @original_date
          AND game_id = @prediction_game_id
          AND invalidation_reason IS NULL
        """

        reason = f"game_postponed_{away_team}_{home_team}_{original_date}"
        invalidate_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("reason", "STRING", reason),
                bigquery.ScalarQueryParameter("original_date", "DATE", original_date),
                bigquery.ScalarQueryParameter("prediction_game_id", "STRING", prediction_game_id),
            ]
        )

        result = client.query(invalidate_query, job_config=invalidate_config).result()
        # Get the number of affected rows
        count = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0

        if count > 0:
            logger.info(
                f"Invalidated {count} predictions for postponed game "
                f"{away_team}@{home_team} on {original_date}"
            )

        return count

    except Exception as e:
        logger.error(f"Failed to invalidate predictions for {nba_game_id}: {e}")
        return 0


def auto_confirm_stale_postponements(
    bq_client: Optional[bigquery.Client] = None
) -> List[Dict[str, Any]]:
    """
    Auto-confirm postponements that are still in 'detected' status but have a future new_date.

    This prevents postponements from sitting in 'detected' status indefinitely when we can
    clearly see the game has been rescheduled to a future date.

    Args:
        bq_client: Optional BigQuery client

    Returns:
        List of confirmed postponements
    """
    client = bq_client or bigquery.Client()

    # Find postponements that should be auto-confirmed:
    # - status = 'detected'
    # - new_date >= today (game hasn't played yet)
    # - new_date is not NULL
    query = """
    SELECT
        game_id,
        original_date,
        new_date,
        reason,
        detection_source
    FROM `nba_orchestration.game_postponements`
    WHERE status = 'detected'
      AND new_date IS NOT NULL
      AND new_date >= CURRENT_DATE()
    """

    try:
        results = list(client.query(query).result())
    except Exception as e:
        logger.error(f"Failed to query stale postponements: {e}")
        return []

    confirmed = []
    for row in results:
        try:
            # Update status to confirmed
            update_query = """
            UPDATE `nba_orchestration.game_postponements`
            SET status = 'confirmed',
                confirmed_at = CURRENT_TIMESTAMP()
            WHERE game_id = @game_id
              AND original_date = @original_date
              AND status = 'detected'
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_id", "STRING", row.game_id),
                    bigquery.ScalarQueryParameter("original_date", "DATE", row.original_date),
                ]
            )

            client.query(update_query, job_config=job_config).result()

            # Also invalidate predictions for the original date
            invalidated_count = _invalidate_predictions_for_postponement(
                client, row.game_id, row.original_date
            )

            # Update the predictions_invalidated count
            if invalidated_count > 0:
                count_update = """
                UPDATE `nba_orchestration.game_postponements`
                SET predictions_invalidated = @count
                WHERE game_id = @game_id
                  AND original_date = @original_date
                """
                count_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("count", "INT64", invalidated_count),
                        bigquery.ScalarQueryParameter("game_id", "STRING", row.game_id),
                        bigquery.ScalarQueryParameter("original_date", "DATE", row.original_date),
                    ]
                )
                client.query(count_update, job_config=count_config).result()

            confirmed.append({
                'game_id': row.game_id,
                'original_date': str(row.original_date),
                'new_date': str(row.new_date),
                'reason': row.reason,
                'predictions_invalidated': invalidated_count,
            })

            logger.info(
                f"Auto-confirmed postponement: {row.game_id} "
                f"({row.original_date} → {row.new_date}), "
                f"invalidated {invalidated_count} predictions"
            )

        except Exception as e:
            logger.error(f"Failed to auto-confirm {row.game_id}: {e}")

    return confirmed
