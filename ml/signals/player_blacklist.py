"""Player Blacklist — blocks chronically losing players from best bets.

Season replay experiments (Sessions 282-283) proved that blocking players
with <40% HR after 8+ graded edge-3+ picks adds +$10,450 in P&L.

Single public function: compute_player_blacklist().
Non-blocking: catches all exceptions, returns empty set on failure.

Created: 2026-02-17 (Session 284)
"""

import logging
from datetime import date
from typing import Any, Dict, Optional, Set, Tuple

from google.cloud import bigquery

from shared.config.model_selection import get_best_bets_model_id
from shared.config.nba_season_dates import get_season_start_date, get_season_year_from_date

logger = logging.getLogger(__name__)

DEFAULT_MIN_PICKS = 8
DEFAULT_HR_THRESHOLD = 40.0


def compute_player_blacklist(
    bq_client: bigquery.Client,
    target_date: str,
    system_id: str = None,
    min_picks: int = DEFAULT_MIN_PICKS,
    hr_threshold: float = DEFAULT_HR_THRESHOLD,
    project_id: str = 'nba-props-platform',
) -> Tuple[Set[str], Dict[str, Any]]:
    """Compute set of players to blacklist from signal best bets.

    Queries prediction_accuracy for season-to-date per-player win/loss stats
    (edge >= 3, not voided) and returns players with hit rate below threshold
    after sufficient sample size.

    Args:
        bq_client: BigQuery client.
        target_date: Date string YYYY-MM-DD (predictions date, query up to day before).
        system_id: Model system_id to filter on (default: champion).
        min_picks: Minimum graded edge-3+ picks to be eligible for blacklist.
        hr_threshold: Hit rate percentage below which a player is blacklisted.
            Strict less-than: exactly hr_threshold is NOT blacklisted.
        project_id: GCP project ID.

    Returns:
        Tuple of (blacklisted_set, stats_dict):
            blacklisted_set: Set of player_lookup strings to block.
            stats_dict: Diagnostic info (evaluated, blacklisted, worst players).
    """
    empty_result = (set(), {'evaluated': 0, 'blacklisted': 0, 'players': []})

    if system_id is None:
        system_id = get_best_bets_model_id()

    try:
        target = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
        season_year = get_season_year_from_date(target)
        season_start = get_season_start_date(season_year, use_schedule_service=False)

        query = f"""
        SELECT
            player_lookup,
            COUNTIF(prediction_correct = TRUE) AS wins,
            COUNTIF(prediction_correct = FALSE) AS losses,
            COUNT(*) AS total_picks,
            ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) AS hit_rate
        FROM `{project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date >= @season_start
          AND game_date < @target_date
          AND system_id = @system_id
          AND ABS(predicted_points - line_value) >= 3
          AND is_voided = FALSE
        GROUP BY player_lookup
        HAVING COUNT(*) >= @min_picks
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('season_start', 'DATE', season_start.isoformat()),
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id),
                bigquery.ScalarQueryParameter('min_picks', 'INT64', min_picks),
            ]
        )

        result = bq_client.query(query, job_config=job_config).result(timeout=60)
        rows = [dict(row) for row in result]

        blacklisted = set()
        player_stats = []

        for row in rows:
            hr = row['hit_rate']
            if hr < hr_threshold:
                blacklisted.add(row['player_lookup'])
                player_stats.append({
                    'player_lookup': row['player_lookup'],
                    'hit_rate': hr,
                    'wins': row['wins'],
                    'losses': row['losses'],
                    'total_picks': row['total_picks'],
                })

        # Sort worst first for logging
        player_stats.sort(key=lambda x: x['hit_rate'])

        stats = {
            'evaluated': len(rows),
            'blacklisted': len(blacklisted),
            'players': player_stats,
        }

        if blacklisted:
            top5 = player_stats[:5]
            top5_str = ', '.join(
                f"{p['player_lookup']} ({p['hit_rate']}% on {p['total_picks']})"
                for p in top5
            )
            logger.info(
                f"Player blacklist: {len(blacklisted)} blocked out of "
                f"{len(rows)} evaluated (min_picks={min_picks}, "
                f"hr_threshold={hr_threshold}%). Worst: {top5_str}"
            )
        else:
            logger.info(
                f"Player blacklist: 0 blocked out of {len(rows)} evaluated "
                f"(min_picks={min_picks}, hr_threshold={hr_threshold}%)"
            )

        return blacklisted, stats

    except Exception as e:
        logger.warning(f"Player blacklist computation failed (non-fatal): {e}")
        return empty_result
