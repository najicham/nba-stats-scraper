#!/usr/bin/env python3
"""
MLB Pitcher Loader

Loads pitchers scheduled to pitch on a given date with betting lines and timing info.
Similar to NBA's player_loader.py but specialized for MLB pitcher props.

Features:
- Queries pitcher_game_summary for scheduled starters
- Gets betting lines from oddsa_pitcher_props with timing metadata
- Returns line_minutes_before_game for v3.6 timing analysis

Usage:
    from predictions.mlb.pitcher_loader import MLBPitcherLoader

    loader = MLBPitcherLoader()
    requests = loader.create_prediction_requests(game_date)

Created: 2026-01-15
"""

import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')


class MLBPitcherLoader:
    """
    Loads pitchers scheduled to pitch on a given date with betting lines.

    Provides line timing metadata (minutes_before_tipoff) for v3.6 analysis.
    """

    # Sportsbook priority order (prefer DraftKings, then FanDuel, etc.)
    SPORTSBOOK_PRIORITY = [
        'draftkings',
        'fanduel',
        'betmgm',
        'caesars',
        'pointsbet',
    ]

    def __init__(self, project_id: str = None):
        self.project_id = project_id or PROJECT_ID
        self.bq_client = bigquery.Client(project=self.project_id)
        self._stats = {
            'pitchers_loaded': 0,
            'pitchers_with_lines': 0,
            'pitchers_without_lines': 0,
        }

    def get_stats(self) -> Dict:
        """Return loader statistics"""
        return self._stats.copy()

    def create_prediction_requests(self, game_date: date) -> List[Dict]:
        """
        Create prediction requests for all starting pitchers on a given date.

        Args:
            game_date: The date to load pitchers for

        Returns:
            List of prediction request dictionaries with features and line timing
        """
        # Get scheduled pitchers
        pitchers = self._load_scheduled_pitchers(game_date)
        self._stats['pitchers_loaded'] = len(pitchers)

        if not pitchers:
            logger.warning(f"No starting pitchers found for {game_date}")
            return []

        # Get betting lines with timing
        lines = self._load_betting_lines(game_date)
        lines_by_pitcher = {line['player_lookup']: line for line in lines}

        # Build prediction requests
        requests = []
        for pitcher in pitchers:
            pitcher_lookup = pitcher['pitcher_lookup']

            # Get line info
            line_info = lines_by_pitcher.get(pitcher_lookup)

            if line_info:
                self._stats['pitchers_with_lines'] += 1
            else:
                self._stats['pitchers_without_lines'] += 1
                logger.debug(f"No betting line for {pitcher_lookup}")
                continue  # Skip pitchers without lines

            # Build request
            request = {
                # Identifiers
                'pitcher_lookup': pitcher_lookup,
                'game_date': game_date.isoformat(),
                'game_id': pitcher.get('game_id'),
                'team_abbr': pitcher.get('team_abbr'),
                'opponent_team_abbr': pitcher.get('opponent_team_abbr'),

                # Betting line info
                'strikeouts_line': line_info.get('strikeouts_line'),
                'over_odds': line_info.get('over_odds'),
                'under_odds': line_info.get('under_odds'),
                'line_source': line_info.get('bookmaker'),
                'line_captured_at': line_info.get('snapshot_time'),

                # v3.6: Line timing
                'line_minutes_before_game': line_info.get('minutes_before_tipoff'),

                # Features from game summary
                'features': self._extract_features(pitcher),
            }

            requests.append(request)

        logger.info(
            f"Created {len(requests)} prediction requests "
            f"({self._stats['pitchers_with_lines']} with lines, "
            f"{self._stats['pitchers_without_lines']} without lines)"
        )

        return requests

    def _load_scheduled_pitchers(self, game_date: date) -> List[Dict]:
        """Load starting pitchers from pitcher_game_summary"""
        query = """
        SELECT
            pgs.pitcher_lookup,
            pgs.game_id,
            pgs.team_abbr,
            pgs.opponent_team_abbr,
            pgs.is_home,
            -- Rolling stats
            pgs.k_avg_last_3,
            pgs.k_avg_last_5,
            pgs.k_avg_last_10,
            pgs.k_std_last_10,
            pgs.ip_avg_last_5,
            -- Season stats
            pgs.era_rolling_10,
            pgs.whip_rolling_10,
            pgs.games_started,
            pgs.strikeouts_total,
            -- Workload
            pgs.days_rest,
            pgs.games_last_30_days,
            pgs.pitch_count_avg,
            pgs.season_ip_total,
            -- Context
            pgs.opponent_team_k_rate,
            pgs.ballpark_k_factor,
            pgs.month_of_season,
            pgs.days_into_season,
            -- Bottom-up
            pgs.bottom_up_k_expected,
            pgs.lineup_k_vs_hand,
            pgs.avg_k_vs_opponent,
            pgs.games_vs_opponent,
            pgs.lineup_weak_spots
        FROM `{project}.mlb_analytics.pitcher_game_summary` pgs
        WHERE pgs.game_date = @game_date
          AND pgs.is_starting_pitcher = TRUE
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        return [dict(row) for row in result]

    def _load_betting_lines(self, game_date: date) -> List[Dict]:
        """
        Load betting lines with timing metadata.

        Returns the most recent line per pitcher, prioritizing sportsbooks.
        """
        # Build sportsbook priority CASE statement
        priority_cases = "\n".join(
            f"WHEN bookmaker = '{book}' THEN {i}"
            for i, book in enumerate(self.SPORTSBOOK_PRIORITY)
        )
        priority_cases += f"\nELSE {len(self.SPORTSBOOK_PRIORITY)}"

        query = """
        WITH ranked_lines AS (
            SELECT
                player_lookup,
                point as strikeouts_line,
                over_price as over_odds,
                under_price as under_odds,
                bookmaker,
                snapshot_time,
                game_start_time,
                minutes_before_tipoff,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY
                        CASE {priority_cases} END,
                        snapshot_time DESC
                ) as rn
            FROM `{project}.mlb_raw.oddsa_pitcher_props`
            WHERE game_date = @game_date
              AND market_key = 'pitcher_strikeouts'
              AND point IS NOT NULL
        )
        SELECT *
        FROM ranked_lines
        WHERE rn = 1
        """.format(project=self.project_id, priority_cases=priority_cases)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        return [dict(row) for row in result]

    def _extract_features(self, pitcher: Dict) -> Dict:
        """Extract features dictionary from pitcher data"""
        return {
            # Rolling stats (f00-f04)
            'f00_k_avg_last_3': pitcher.get('k_avg_last_3'),
            'f01_k_avg_last_5': pitcher.get('k_avg_last_5'),
            'f02_k_avg_last_10': pitcher.get('k_avg_last_10'),
            'f03_k_std_last_10': pitcher.get('k_std_last_10'),
            'f04_ip_avg_last_5': pitcher.get('ip_avg_last_5'),
            # Season stats (f06-f09) - f05 not in summary
            'f06_era_rolling_10': pitcher.get('era_rolling_10'),
            'f07_whip_rolling_10': pitcher.get('whip_rolling_10'),
            'f08_games_started': pitcher.get('games_started'),
            'f09_strikeouts_total': pitcher.get('strikeouts_total'),
            # Game context (f10)
            'f10_is_home': 1 if pitcher.get('is_home') else 0,
            # Opponent/Ballpark (f15-f16)
            'f15_opponent_team_k_rate': pitcher.get('opponent_team_k_rate'),
            'f16_ballpark_k_factor': pitcher.get('ballpark_k_factor'),
            # Temporal (f17-f18)
            'f17_month_of_season': pitcher.get('month_of_season'),
            'f18_days_into_season': pitcher.get('days_into_season'),
            # Workload (f20-f23)
            'f20_days_rest': pitcher.get('days_rest'),
            'f21_games_last_30_days': pitcher.get('games_last_30_days'),
            'f22_pitch_count_avg': pitcher.get('pitch_count_avg'),
            'f23_season_ip_total': pitcher.get('season_ip_total'),
            # Context (f24)
            'f24_is_postseason': 0,  # Default to regular season
            # Bottom-up (f25-f28, f33)
            'f25_bottom_up_k_expected': pitcher.get('bottom_up_k_expected'),
            'f26_lineup_k_vs_hand': pitcher.get('lineup_k_vs_hand'),
            'f27_avg_k_vs_opponent': pitcher.get('avg_k_vs_opponent'),
            'f28_games_vs_opponent': pitcher.get('games_vs_opponent'),
            'f33_lineup_weak_spots': pitcher.get('lineup_weak_spots'),
        }

    def get_line_timing_stats(self, game_date: date) -> Dict:
        """
        Get line timing statistics for a given date.

        Useful for analyzing line capture timing distribution.
        """
        query = """
        SELECT
            CASE
                WHEN minutes_before_tipoff > 240 THEN 'VERY_EARLY'
                WHEN minutes_before_tipoff > 60 THEN 'EARLY'
                WHEN minutes_before_tipoff > 0 THEN 'CLOSING'
                ELSE 'UNKNOWN'
            END as timing_bucket,
            COUNT(*) as count,
            AVG(minutes_before_tipoff) as avg_minutes,
            MIN(minutes_before_tipoff) as min_minutes,
            MAX(minutes_before_tipoff) as max_minutes
        FROM `{project}.mlb_raw.oddsa_pitcher_props`
        WHERE game_date = @game_date
          AND market_key = 'pitcher_strikeouts'
          AND minutes_before_tipoff IS NOT NULL
        GROUP BY timing_bucket
        ORDER BY avg_minutes DESC
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        return {row['timing_bucket']: dict(row) for row in result}


def load_batch_features(
    game_date: date,
    pitcher_lookups: Optional[List[str]] = None,
    project_id: str = None
) -> Dict[str, Dict]:
    """
    Load features for multiple pitchers in a single BigQuery query.

    This is the SHARED feature loader used by all prediction systems to avoid
    redundant BigQuery queries during batch processing.

    Optimization: Instead of each system (v1_baseline, v1_6_rolling, ensemble_v1)
    calling batch_predict() and executing the same query 3 times, we load features
    ONCE and pass them to each system's predict() method.

    Expected improvement: 66% reduction in BigQuery queries, 30-40% faster batch times.

    Args:
        game_date: Game date to predict for
        pitcher_lookups: Optional list of pitcher lookups to filter (None = all starting pitchers)
        project_id: GCP project ID (default: env var GCP_PROJECT_ID)

    Returns:
        Dict[pitcher_lookup, features]: Mapping of pitcher_lookup to feature dict

    Example:
        >>> features_by_pitcher = load_batch_features(date(2026, 6, 15))
        >>> features = features_by_pitcher['gerrit-cole']
        >>> prediction = predictor.predict('gerrit-cole', features=features, strikeouts_line=6.5)
    """
    proj_id = project_id or PROJECT_ID
    client = bigquery.Client(project=proj_id)

    # Build pitcher filter clause
    if pitcher_lookups:
        pitcher_filter = "AND pgs.player_lookup IN UNNEST(@pitcher_lookups)"
    else:
        pitcher_filter = ""

    # Query: Same as PitcherStrikeoutsPredictor.batch_predict() but returns features
    # Joins 3 tables:
    # 1. mlb_analytics.pitcher_game_summary - Core features
    # 2. mlb_analytics.pitcher_rolling_statcast - Statcast features (V1.6)
    # 3. mlb_raw.bp_pitcher_props - BettingPros projections (V1.6)
    query = f"""
    WITH latest_features AS (
        SELECT
            pgs.player_lookup,
            pgs.game_date as feature_date,
            pgs.team_abbr,
            pgs.opponent_team_abbr,
            pgs.is_home,
            pgs.is_postseason,
            pgs.days_rest,
            pgs.k_avg_last_3,
            pgs.k_avg_last_5,
            pgs.k_avg_last_10,
            pgs.k_std_last_10,
            pgs.ip_avg_last_5,
            pgs.season_k_per_9,
            pgs.era_rolling_10,
            pgs.whip_rolling_10,
            pgs.season_games_started,
            pgs.season_strikeouts,
            pgs.season_innings,
            -- V1.4 features
            pgs.opponent_team_k_rate,
            pgs.ballpark_k_factor,
            pgs.month_of_season,
            pgs.days_into_season,
            pgs.vs_opponent_k_per_9 as avg_k_vs_opponent,
            pgs.vs_opponent_games as games_vs_opponent,
            -- Workload
            pgs.games_last_30_days,
            pgs.pitch_count_avg_last_5,
            pgs.data_completeness_score,
            pgs.rolling_stats_games,
            ROW_NUMBER() OVER (PARTITION BY pgs.player_lookup ORDER BY pgs.game_date DESC) as rn
        FROM `{proj_id}.mlb_analytics.pitcher_game_summary` pgs
        WHERE pgs.game_date < @game_date
          AND pgs.game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
          AND pgs.rolling_stats_games >= 3
          {pitcher_filter}
    ),
    -- V1.6: Rolling Statcast features (most recent before game_date)
    statcast_latest AS (
        SELECT
            player_lookup,
            swstr_pct_last_3,
            fb_velocity_last_3,
            swstr_pct_last_5,
            swstr_pct_season_prior,
            ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
        FROM `{proj_id}.mlb_analytics.pitcher_rolling_statcast`
        WHERE game_date < @game_date
    ),
    -- V1.6: BettingPros projections for game date
    bp_features AS (
        SELECT
            player_lookup,
            projection_value as bp_projection,
            over_line as bp_over_line,
            -- Calculate performance percentages
            SAFE_DIVIDE(perf_last_5_over, perf_last_5_over + perf_last_5_under) as perf_last_5_pct,
            SAFE_DIVIDE(perf_last_10_over, perf_last_10_over + perf_last_10_under) as perf_last_10_pct
        FROM `{proj_id}.mlb_raw.bp_pitcher_props`
        WHERE game_date = @game_date
          AND market_name = 'pitcher-strikeouts'
    )
    SELECT
        lf.*,
        -- Rolling Statcast (f50-f53)
        s.swstr_pct_last_3,
        s.fb_velocity_last_3,
        COALESCE(s.swstr_pct_last_3 - s.swstr_pct_season_prior, 0) as swstr_trend,
        COALESCE(s.fb_velocity_last_3, 0) as velocity_last_3,
        -- BettingPros (f40-f44)
        bp.bp_projection,
        COALESCE(bp.bp_projection - bp.bp_over_line, 0) as projection_diff,
        bp.perf_last_5_pct,
        bp.perf_last_10_pct,
        bp.bp_over_line as strikeouts_line
    FROM latest_features lf
    LEFT JOIN statcast_latest s ON lf.player_lookup = s.player_lookup AND s.rn = 1
    LEFT JOIN bp_features bp ON lf.player_lookup = bp.player_lookup
    WHERE lf.rn = 1
    """

    try:
        # Build query parameters
        params = [
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat()),
        ]
        if pitcher_lookups:
            params.append(
                bigquery.ArrayQueryParameter("pitcher_lookups", "STRING", pitcher_lookups)
            )

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        result = client.query(query, job_config=job_config).result()

        # Build dictionary mapping pitcher_lookup -> features
        features_by_pitcher = {}
        for row in result:
            features = dict(row)
            pitcher_lookup = features['player_lookup']
            features_by_pitcher[pitcher_lookup] = features

        logger.info(f"Loaded features for {len(features_by_pitcher)} pitchers on {game_date}")
        return features_by_pitcher

    except Exception as e:
        logger.error(f"Failed to load batch features: {e}")
        return {}


# CLI for testing
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Load MLB pitchers with betting lines")
    parser.add_argument("--date", type=str, help="Date (YYYY-MM-DD), default: today")
    parser.add_argument("--timing-stats", action="store_true", help="Show line timing stats")
    args = parser.parse_args()

    game_date = date.fromisoformat(args.date) if args.date else date.today()

    loader = MLBPitcherLoader()

    if args.timing_stats:
        stats = loader.get_line_timing_stats(game_date)
        print(f"\nLine Timing Stats for {game_date}:")
        for bucket, data in stats.items():
            print(f"  {bucket}: {data['count']} lines, avg {data['avg_minutes']:.0f} min before")
    else:
        requests = loader.create_prediction_requests(game_date)
        print(f"\nLoaded {len(requests)} pitchers for {game_date}")
        for req in requests[:5]:  # Show first 5
            print(f"  {req['pitcher_lookup']}: line={req['strikeouts_line']}, "
                  f"timing={req['line_minutes_before_game']} min before")

        print(f"\nLoader stats: {loader.get_stats()}")
