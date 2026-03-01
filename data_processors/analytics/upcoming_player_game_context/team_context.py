"""
Path: data_processors/analytics/upcoming_player_game_context/team_context.py

Team Context Module - Opponent Stats and Variance Metrics

Extracted from upcoming_player_game_context_processor.py for maintainability.
Contains functions for calculating team-level opponent metrics.
"""

import logging
from datetime import date
from typing import Optional

from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded

logger = logging.getLogger(__name__)


class TeamContextCalculator:
    """
    Calculator for team-level opponent metrics.

    Provides methods for calculating pace, defense/offense ratings,
    rebounding rates, and variance metrics for opponents.
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize the calculator.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id
        # Cache for opponent metrics to avoid redundant queries
        # Key: (opponent_abbr, game_date) -> dict of all metrics
        self._opponent_cache = {}
        self._team_cache = {}  # For team-specific metrics like pace_differential

    def precompute_opponent_metrics(self, opponent_abbrs: list, game_date: date) -> None:
        """
        Pre-compute all opponent metrics in a single batch query.

        This dramatically reduces BigQuery calls from O(players * metrics) to O(1).
        Call this before processing players for a given date.

        Args:
            opponent_abbrs: List of unique opponent team abbreviations
            game_date: Game date for the metrics
        """
        if not opponent_abbrs:
            return

        try:
            # Batch query for offense table metrics (pace, off_rating, reb_rate)
            query = f"""
            WITH ranked_games AS (
                SELECT
                    team_abbr,
                    pace,
                    offensive_rating,
                    rebounds / NULLIF(possessions, 0) as reb_rate,
                    ROW_NUMBER() OVER (PARTITION BY team_abbr ORDER BY game_date DESC) as rn
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr IN UNNEST(@opponent_abbrs)
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
            )
            SELECT
                team_abbr as opponent_abbr,
                ROUND(AVG(pace), 2) as avg_pace,
                ROUND(STDDEV(pace), 2) as pace_variance,
                ROUND(AVG(offensive_rating), 2) as avg_off_rating,
                ROUND(STDDEV(offensive_rating), 2) as off_rating_variance,
                ROUND(AVG(reb_rate), 4) as avg_reb_rate,
                ROUND(STDDEV(reb_rate), 4) as reb_rate_variance
            FROM ranked_games
            WHERE rn <= 10
            GROUP BY team_abbr
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("opponent_abbrs", "STRING", opponent_abbrs),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()

            for row in result:
                cache_key = (row.opponent_abbr, game_date)
                self._opponent_cache[cache_key] = {
                    'pace': row.avg_pace or 0.0,
                    'pace_variance': row.pace_variance or 0.0,
                    'off_rating': row.avg_off_rating or 0.0,
                    'off_rating_variance': row.off_rating_variance or 0.0,
                    'reb_rate': row.avg_reb_rate or 0.0,
                    'reb_rate_variance': row.reb_rate_variance or 0.0,
                }

            logger.info(f"Pre-computed opponent metrics for {len(opponent_abbrs)} teams (cached {len(self._opponent_cache)} entries)")

        except Exception as e:
            logger.warning(f"Failed to pre-compute opponent metrics: {e}. Will fall back to individual queries.")

    def _get_cached_opponent_metric(self, opponent_abbr: str, game_date: date, metric: str) -> Optional[float]:
        """Get a cached metric value, or None if not cached."""
        cache_key = (opponent_abbr, game_date)
        if cache_key in self._opponent_cache:
            return self._opponent_cache[cache_key].get(metric)
        return None

    def calculate_pace_differential(self, team_abbr: str, opponent_abbr: str, game_date: date) -> float:
        """
        Calculate difference between team's pace and opponent's pace (last 10 games).

        Args:
            team_abbr: Player's team abbreviation
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Pace differential (team_pace - opponent_pace), rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_team AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @team_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            ),
            recent_opponent AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT
                ROUND((SELECT AVG(pace) FROM recent_team) - (SELECT AVG(pace) FROM recent_opponent), 2) as pace_diff
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.pace_diff if row.pace_diff is not None else 0.0

            logger.warning(f"No pace data found for {team_abbr} vs {opponent_abbr}")
            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error calculating pace differential for {team_abbr} vs {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error calculating pace differential for {team_abbr} vs {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_pace_last_10(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's average pace over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average pace over last 10 games, rounded to 2 decimals
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'pace')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(pace), 2) as avg_pace
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.avg_pace if row.avg_pace is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent pace for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent pace for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_ft_rate_allowed(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's defensive FT rate allowed per 100 possessions (last 10 games).

        Calculates FTA allowed per 100 possessions, which normalizes for pace:
        FT Rate = (opp_ft_attempts / opponent_pace) * 100

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average FT attempts allowed per 100 possessions (last 10 games),
                   rounded to 3 decimals. Returns 0.0 if no data available.
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT
                    opp_ft_attempts,
                    opponent_pace,
                    CASE
                        WHEN opponent_pace > 0 THEN
                            ROUND((opp_ft_attempts / opponent_pace) * 100, 3)
                        ELSE NULL
                    END as ft_rate_per_100
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                  AND opp_ft_attempts IS NOT NULL
                  AND opponent_pace IS NOT NULL
                  AND opponent_pace > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT
                ROUND(AVG(ft_rate_per_100), 3) as avg_ft_rate_allowed,
                COUNT(*) as games_count
            FROM recent_games
            WHERE ft_rate_per_100 IS NOT NULL
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                if row.avg_ft_rate_allowed is not None and row.games_count >= 3:
                    return float(row.avg_ft_rate_allowed)
                elif row.avg_ft_rate_allowed is not None:
                    logger.debug(
                        f"FT rate for {opponent_abbr} based on only {row.games_count} games"
                    )
                    return float(row.avg_ft_rate_allowed)

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting FT rate allowed for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting FT rate allowed for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_def_rating_last_10(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's defensive rating over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average defensive rating over last 10 games, rounded to 2 decimals
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'def_rating')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT defensive_rating
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(defensive_rating), 2) as avg_def_rating
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.avg_def_rating if row.avg_def_rating is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent def rating for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent def rating for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_off_rating_last_10(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's offensive rating over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average offensive rating over last 10 games, rounded to 2 decimals
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'off_rating')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT offensive_rating
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(offensive_rating), 2) as avg_off_rating
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.avg_off_rating if row.avg_off_rating is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent off rating for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent off rating for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_rebounding_rate(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's rebounding rate (rebounds per possession) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Rebounding rate (rebounds/possession) over last 10 games, rounded to 2 decimals
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'reb_rate')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT rebounds, possessions
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                  AND possessions > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(rebounds) / NULLIF(AVG(possessions), 0), 2) as rebounding_rate
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.rebounding_rate if row.rebounding_rate is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent rebounding rate for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent rebounding rate for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_pace_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's pace variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of pace over last 10 games, rounded to 2 decimals
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'pace_variance')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(pace), 2) as pace_stddev
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.pace_stddev if row.pace_stddev is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent pace variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent pace variance for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_ft_rate_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's FT rate variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of FT rate per 100 possessions over last 10 games,
                   rounded to 3 decimals. Returns 0.0 if insufficient data.
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'ft_rate_variance')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT
                    opp_ft_attempts,
                    opponent_pace,
                    CASE
                        WHEN opponent_pace > 0 THEN
                            ROUND((opp_ft_attempts / opponent_pace) * 100, 3)
                        ELSE NULL
                    END as ft_rate_per_100
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                  AND opp_ft_attempts IS NOT NULL
                  AND opponent_pace IS NOT NULL
                  AND opponent_pace > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT
                ROUND(STDDEV(ft_rate_per_100), 3) as ft_rate_stddev,
                COUNT(*) as games_count
            FROM recent_games
            WHERE ft_rate_per_100 IS NOT NULL
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                if row.ft_rate_stddev is not None and row.games_count >= 2:
                    return float(row.ft_rate_stddev)

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent FT rate variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent FT rate variance for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_def_rating_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's defensive rating variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of defensive rating over last 10 games, rounded to 2 decimals
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'def_rating_variance')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT defensive_rating
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(defensive_rating), 2) as def_rating_stddev
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.def_rating_stddev if row.def_rating_stddev is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent def rating variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent def rating variance for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_off_rating_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's offensive rating variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of offensive rating over last 10 games, rounded to 2 decimals
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'off_rating_variance')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT offensive_rating
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(offensive_rating), 2) as off_rating_stddev
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.off_rating_stddev if row.off_rating_stddev is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent off rating variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent off rating variance for {opponent_abbr}: {e}")
            return 0.0

    def get_opponent_rebounding_rate_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's rebounding rate variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of rebounding rate over last 10 games, rounded to 3 decimals
        """
        # Check cache first
        cached = self._get_cached_opponent_metric(opponent_abbr, game_date, 'reb_rate_variance')
        if cached is not None:
            return cached

        try:
            query = f"""
            WITH recent_games AS (
                SELECT
                    rebounds / NULLIF(possessions, 0) as rebounding_rate
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                  AND possessions > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(rebounding_rate), 3) as rebounding_rate_stddev
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.rebounding_rate_stddev if row.rebounding_rate_stddev is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent rebounding rate variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent rebounding rate variance for {opponent_abbr}: {e}")
            return 0.0

    def get_star_teammates_out(self, team_abbr: str, game_date: date) -> int:
        """
        Count star teammates who are OUT or DOUBTFUL for the game.

        Star criteria (last 10 games, season avg fallback):
        - Average points >= 18 PPG OR
        - Average minutes >= 28 MPG OR
        - Usage rate >= 25%

        Session 374: Added season avg fallback for long-term injuries.
        INTERVAL 10 DAY missed players out 10+ days (Giannis 27 PPG, Tatum, Morant).

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Game date to check

        Returns:
            int: Number of star teammates out (0-5 typical range)
        """
        try:
            query = f"""
            WITH team_roster AS (
                SELECT player_lookup
                FROM `{self.project_id}.nba_raw.espn_team_rosters`
                WHERE team_abbr = @team_abbr
                  AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                  AND roster_date <= @game_date
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= @game_date
                        AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                        AND team_abbr = @team_abbr
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB(@game_date, INTERVAL 10 DAY)
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            -- Session 374: Season avg fallback for long-term injured stars.
            -- INTERVAL 10 DAY misses players out 10+ days (Giannis 27 PPG, Tatum, Morant).
            player_season_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= '2025-10-22'
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            star_players AS (
                SELECT s.player_lookup
                FROM player_season_stats s
                INNER JOIN team_roster r ON s.player_lookup = r.player_lookup
                LEFT JOIN player_recent_stats rs ON rs.player_lookup = s.player_lookup
                WHERE COALESCE(rs.avg_points, s.avg_points) >= 18
                   OR COALESCE(rs.avg_minutes, s.avg_minutes) >= 28
                   OR COALESCE(rs.avg_usage, s.avg_usage) >= 25
            ),
            injured_players AS (
                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_raw.nbac_injury_report`
                WHERE game_date = @game_date
                  AND team = @team_abbr
                  AND UPPER(injury_status) IN ('OUT', 'DOUBTFUL')
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_hour DESC
                ) = 1
            )
            SELECT COUNT(*) as star_teammates_out
            FROM star_players s
            INNER JOIN injured_players i ON s.player_lookup = i.player_lookup
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return int(row.star_teammates_out) if row.star_teammates_out is not None else 0

            return 0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting star teammates out for {team_abbr}: {e}")
            return 0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting star teammates out for {team_abbr}: {e}")
            return 0

    def get_questionable_star_teammates(self, team_abbr: str, game_date: date) -> int:
        """
        Count star teammates who are QUESTIONABLE for the game.

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Game date to check

        Returns:
            int: Number of star teammates questionable (0-5 typical range)
        """
        try:
            query = f"""
            WITH team_roster AS (
                SELECT player_lookup
                FROM `{self.project_id}.nba_raw.espn_team_rosters`
                WHERE team_abbr = @team_abbr
                  AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                  AND roster_date <= @game_date
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= @game_date
                        AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                        AND team_abbr = @team_abbr
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB(@game_date, INTERVAL 10 DAY)
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            -- Session 374: Season avg fallback (same fix as get_star_teammates_out)
            player_season_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= '2025-10-22'
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            star_players AS (
                SELECT s.player_lookup
                FROM player_season_stats s
                INNER JOIN team_roster r ON s.player_lookup = r.player_lookup
                LEFT JOIN player_recent_stats rs ON rs.player_lookup = s.player_lookup
                WHERE COALESCE(rs.avg_points, s.avg_points) >= 18
                   OR COALESCE(rs.avg_minutes, s.avg_minutes) >= 28
                   OR COALESCE(rs.avg_usage, s.avg_usage) >= 25
            ),
            questionable_players AS (
                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_raw.nbac_injury_report`
                WHERE game_date = @game_date
                  AND team = @team_abbr
                  AND UPPER(injury_status) = 'QUESTIONABLE'
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_hour DESC
                ) = 1
            )
            SELECT COUNT(*) as questionable_star_teammates
            FROM star_players s
            INNER JOIN questionable_players q ON s.player_lookup = q.player_lookup
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return int(row.questionable_star_teammates) if row.questionable_star_teammates is not None else 0

            return 0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting questionable star teammates for {team_abbr}: {e}")
            return 0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting questionable star teammates for {team_abbr}: {e}")
            return 0

    def get_star_tier_out(self, team_abbr: str, game_date: date) -> int:
        """
        Calculate weighted tier score for OUT/DOUBTFUL star teammates.

        Star tiers (based on PPG, season avg with recent fallback):
        - Tier 1 (Superstar): 25+ PPG = 3 points
        - Tier 2 (Star): 18-24.99 PPG = 2 points
        - Tier 3 (Quality starter): <18 PPG but 28+ MPG or 25%+ usage = 1 point

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Game date to check

        Returns:
            int: Weighted tier score (0-15 typical range)
        """
        try:
            query = f"""
            WITH team_roster AS (
                SELECT player_lookup
                FROM `{self.project_id}.nba_raw.espn_team_rosters`
                WHERE team_abbr = @team_abbr
                  AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                  AND roster_date <= @game_date
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= @game_date
                        AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                        AND team_abbr = @team_abbr
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB(@game_date, INTERVAL 10 DAY)
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            -- Session 374: Season avg fallback (same fix as get_star_teammates_out)
            player_season_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= '2025-10-22'
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            star_players_with_tier AS (
                SELECT
                    s.player_lookup,
                    CASE
                        WHEN COALESCE(rs.avg_points, s.avg_points) >= 25 THEN 3
                        WHEN COALESCE(rs.avg_points, s.avg_points) >= 18 THEN 2
                        ELSE 1
                    END as tier_weight
                FROM player_season_stats s
                INNER JOIN team_roster r ON s.player_lookup = r.player_lookup
                LEFT JOIN player_recent_stats rs ON rs.player_lookup = s.player_lookup
                WHERE COALESCE(rs.avg_points, s.avg_points) >= 18
                   OR COALESCE(rs.avg_minutes, s.avg_minutes) >= 28
                   OR COALESCE(rs.avg_usage, s.avg_usage) >= 25
            ),
            injured_players AS (
                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_raw.nbac_injury_report`
                WHERE game_date = @game_date
                  AND team = @team_abbr
                  AND UPPER(injury_status) IN ('OUT', 'DOUBTFUL')
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_hour DESC
                ) = 1
            )
            SELECT SUM(s.tier_weight) as star_tier_out
            FROM star_players_with_tier s
            INNER JOIN injured_players i ON s.player_lookup = i.player_lookup
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return int(row.star_tier_out) if row.star_tier_out is not None else 0

            return 0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting star tier out for {team_abbr}: {e}")
            return 0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting star tier out for {team_abbr}: {e}")
            return 0

    def get_probable_teammates(self, team_abbr: str, game_date: date) -> Optional[int]:
        """
        Count teammates with PROBABLE status for the game.

        Players with 'probable' injury status are expected to play but have
        some uncertainty. A high number of probable teammates may indicate
        a team dealing with minor injuries/rest issues.

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Game date to check

        Returns:
            int: Number of teammates with probable status (0-10 typical range)
                 Returns None if injury data is unavailable
        """
        try:
            query = f"""
            WITH latest_injury_status AS (
                SELECT
                    player_lookup,
                    injury_status,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_lookup
                        ORDER BY report_hour DESC
                    ) as rn
                FROM `{self.project_id}.nba_raw.nbac_injury_report`
                WHERE game_date = @game_date
                  AND team = @team_abbr
            )
            SELECT COUNT(*) as probable_count
            FROM latest_injury_status
            WHERE rn = 1
              AND UPPER(injury_status) = 'PROBABLE'
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return int(row.probable_count) if row.probable_count is not None else 0

            return 0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error getting probable teammates for {team_abbr}: {e}")
            return None
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error getting probable teammates for {team_abbr}: {e}")
            return None
