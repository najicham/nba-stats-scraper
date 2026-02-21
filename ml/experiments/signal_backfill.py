#!/usr/bin/env python3
"""Backfill signal annotations and best bets picks for historical dates.

Uses prediction_accuracy (graded) instead of player_prop_predictions (live)
since we're looking at past dates.

Usage:
    PYTHONPATH=. python ml/experiments/signal_backfill.py [--start DATE] [--end DATE] [--dry-run]
"""

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

from google.cloud import bigquery

from ml.signals.registry import build_default_registry
from ml.signals.aggregator import BestBetsAggregator
from ml.signals.combo_registry import load_combo_registry, match_combo
from ml.signals.model_health import BREAKEVEN_HR

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
SYSTEM_ID = 'catboost_v9'

QUERY = """
WITH preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.game_date,
    pa.system_id,
    pa.team_abbr,
    pa.opponent_team_abbr,
    CAST(pa.predicted_points AS FLOAT64) AS predicted_points,
    CAST(pa.line_value AS FLOAT64) AS line_value,
    pa.recommendation,
    CAST(pa.predicted_points - pa.line_value AS FLOAT64) AS edge,
    CAST(pa.confidence_score AS FLOAT64) AS confidence_score,
    pa.actual_points,
    pa.prediction_correct
  FROM `{project}.nba_predictions.prediction_accuracy` pa
  WHERE pa.game_date = @target_date
    AND pa.system_id = '{system_id}'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

-- Rolling stats
game_stats AS (
  SELECT
    player_lookup,
    game_date,
    minutes_played,
    AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS three_pct_last_3,
    AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_season,
    STDDEV(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_std,
    AVG(CAST(three_pt_attempts AS FLOAT64))
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pa_per_game,
    AVG(minutes_played)
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS minutes_avg_last_3,
    AVG(minutes_played)
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season
  FROM `{project}.nba_analytics.player_game_summary`
  WHERE game_date >= '2025-10-22'
    AND minutes_played > 0
),

latest_stats AS (
  SELECT gs.*
  FROM game_stats gs
  INNER JOIN preds p ON gs.player_lookup = p.player_lookup
  WHERE gs.game_date < @target_date
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY gs.player_lookup ORDER BY gs.game_date DESC
  ) = 1
),

-- Streak data for cold_snap
streak_data AS (
  SELECT
    player_lookup,
    game_date,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 1) OVER w AS prev_over_1,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 2) OVER w AS prev_over_2,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 3) OVER w AS prev_over_3,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 4) OVER w AS prev_over_4,
    LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 5) OVER w AS prev_over_5
  FROM (
    SELECT *
    FROM `{project}.nba_predictions.prediction_accuracy`
    WHERE game_date >= '2025-10-22'
      AND system_id = '{system_id}'
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE
      AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_id ORDER BY graded_at DESC
    ) = 1
  )
  WINDOW w AS (PARTITION BY player_lookup ORDER BY game_date)
),

latest_streak AS (
  SELECT sd.*
  FROM streak_data sd
  INNER JOIN preds p ON sd.player_lookup = p.player_lookup
  WHERE sd.game_date < @target_date
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY sd.player_lookup ORDER BY sd.game_date DESC
  ) = 1
),

-- Model health: 7-day rolling HR as of target_date
model_health AS (
  SELECT
    ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1) AS hit_rate_7d,
    COUNT(*) AS graded_count
  FROM `{project}.nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(@target_date, INTERVAL 7 DAY)
    AND game_date < @target_date
    AND system_id = '{system_id}'
    AND ABS(predicted_points - line_value) >= 3.0
    AND prediction_correct IS NOT NULL
    AND is_voided IS NOT TRUE
)

SELECT
  p.*,
  ls.three_pct_last_3, ls.three_pct_season, ls.three_pct_std, ls.three_pa_per_game,
  ls.minutes_avg_last_3, ls.minutes_avg_season,
  ls.minutes_played AS prev_minutes,
  DATE_DIFF(@target_date, ls.game_date, DAY) AS rest_days,
  lsk.prev_over_1, lsk.prev_over_2, lsk.prev_over_3,
  lsk.prev_over_4, lsk.prev_over_5,
  mh.hit_rate_7d AS model_health_hr_7d,
  mh.graded_count AS model_health_graded
FROM preds p
LEFT JOIN latest_stats ls ON ls.player_lookup = p.player_lookup
LEFT JOIN latest_streak lsk ON lsk.player_lookup = p.player_lookup
CROSS JOIN model_health mh
ORDER BY p.player_lookup
""".format(project=PROJECT_ID, system_id=SYSTEM_ID)


def load_date_data(client: bigquery.Client, target_date: str) -> List[Dict]:
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
        ]
    )
    rows = client.query(QUERY, job_config=job_config).result(timeout=120)
    return [dict(row) for row in rows]


def evaluate_and_build(rows: List[Dict], registry, combo_reg=None) -> Tuple[
    List[Dict],   # tag rows for pick_signal_tags
    List[Dict],   # best bets picks
    str,          # health status
]:
    if not rows:
        return [], [], 'unknown'

    # Determine model health from first row (same for all rows on a date)
    hr_7d = float(rows[0].get('model_health_hr_7d') or 0) if rows[0].get('model_health_hr_7d') is not None else None

    health_status = 'unknown'
    if hr_7d is not None:
        if hr_7d < BREAKEVEN_HR:
            health_status = 'blocked'
        elif hr_7d < 58.0:
            health_status = 'watch'
        else:
            health_status = 'healthy'

    tag_rows = []
    signal_results_map = {}
    predictions = []
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        pred = {
            'player_lookup': row['player_lookup'],
            'game_id': row['game_id'],
            'game_date': row['game_date'],
            'system_id': row.get('system_id', SYSTEM_ID),
            'player_name': row.get('player_name', row.get('player_lookup', '')),
            'team_abbr': row.get('team_abbr', ''),
            'opponent_team_abbr': row.get('opponent_team_abbr', ''),
            'predicted_points': float(row['predicted_points'] or 0),
            'line_value': float(row['line_value'] or 0),
            'recommendation': row['recommendation'],
            'edge': float(row['edge'] or 0),
            'confidence_score': float(row['confidence_score'] or 0),
            'actual_points': row.get('actual_points'),
            'prediction_correct': row.get('prediction_correct'),
        }
        predictions.append(pred)

        # Build supplemental
        supplemental = {'model_health': {'hit_rate_7d_edge3': hr_7d}}

        if row.get('three_pct_last_3') is not None:
            supplemental['three_pt_stats'] = {
                'three_pct_last_3': float(row['three_pct_last_3']),
                'three_pct_season': float(row.get('three_pct_season') or 0),
                'three_pct_std': float(row.get('three_pct_std') or 0),
                'three_pa_per_game': float(row.get('three_pa_per_game') or 0),
            }

        if row.get('minutes_avg_last_3') is not None:
            supplemental['minutes_stats'] = {
                'minutes_avg_last_3': float(row['minutes_avg_last_3']),
                'minutes_avg_season': float(row.get('minutes_avg_season') or 0),
            }

        if row.get('prev_over_1') is not None:
            supplemental['streak_stats'] = {
                'prev_correct': [],
                'prev_over': [
                    row.get('prev_over_1'), row.get('prev_over_2'),
                    row.get('prev_over_3'), row.get('prev_over_4'),
                    row.get('prev_over_5'),
                ],
            }

        if row.get('prev_minutes') is not None and row.get('minutes_avg_season') is not None:
            supplemental['recovery_stats'] = {
                'prev_minutes': float(row['prev_minutes']),
                'minutes_avg_season': float(row['minutes_avg_season']),
            }

        if row.get('rest_days') is not None:
            supplemental['rest_stats'] = {'rest_days': int(row['rest_days'])}

        # Evaluate signals
        qualifying_tags = []
        all_results = []
        for signal in registry.all():
            result = signal.evaluate(pred, features=None, supplemental=supplemental)
            all_results.append(result)
            if result.qualifies and signal.tag != 'model_health':
                qualifying_tags.append(result.source_tag)

        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signal_results_map[key] = all_results

        # Match combo from registry
        matched = match_combo(qualifying_tags, combo_reg) if (qualifying_tags and combo_reg) else None

        tag_rows.append({
            'game_date': str(pred['game_date']),
            'player_lookup': pred['player_lookup'],
            'system_id': SYSTEM_ID,
            'game_id': pred.get('game_id'),
            'signal_tags': qualifying_tags,
            'signal_count': len(qualifying_tags),
            'matched_combo_id': matched.combo_id if matched else None,
            'combo_classification': matched.classification if matched else None,
            'combo_hit_rate': matched.hit_rate if matched else None,
            'model_health_status': health_status,
            'model_health_hr_7d': hr_7d,
            'evaluated_at': now,
            'version_id': f'backfill_{str(pred["game_date"])}',
        })

    # Build best bets (health gate removed, Session 270)
    best_bets_rows = []
    aggregator = BestBetsAggregator(combo_registry=combo_reg)
    top_picks, _ = aggregator.aggregate(predictions, signal_results_map)

    for pick in top_picks:
        best_bets_rows.append({
            'player_lookup': pick['player_lookup'],
            'game_id': pick.get('game_id', ''),
            'game_date': str(pick['game_date']),
            'system_id': SYSTEM_ID,
            'player_name': pick.get('player_name', ''),
            'team_abbr': pick.get('team_abbr', ''),
            'opponent_team_abbr': pick.get('opponent_team_abbr', ''),
            'predicted_points': pick.get('predicted_points'),
            'line_value': pick.get('line_value'),
            'recommendation': pick.get('recommendation', ''),
            'edge': pick.get('edge'),
            'confidence_score': pick.get('confidence_score'),
            'signal_tags': pick.get('signal_tags', []),
            'signal_count': pick.get('signal_count', 0),
            'composite_score': pick.get('composite_score'),
            'matched_combo_id': pick.get('matched_combo_id'),
            'combo_classification': pick.get('combo_classification'),
            'combo_hit_rate': pick.get('combo_hit_rate'),
            'warning_tags': pick.get('warning_tags', []),
            'rank': pick.get('rank'),
            'actual_points': pick.get('actual_points'),
            'prediction_correct': pick.get('prediction_correct'),
            'created_at': now,
        })

    return tag_rows, best_bets_rows, health_status


def write_rows(client: bigquery.Client, table_id: str, rows: List[Dict]) -> int:
    if not rows:
        return 0
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )
    load_job = client.load_table_from_json(rows, table_id, job_config=job_config)
    load_job.result(timeout=120)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Signal Backfill")
    parser.add_argument('--start', default='2026-01-09', help='Start date (inclusive)')
    parser.add_argument('--end', default='2026-02-12', help='End date (inclusive)')
    parser.add_argument('--dry-run', action='store_true', help='Print results without writing')
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)
    registry = build_default_registry()
    combo_reg = load_combo_registry(bq_client=client)

    # Get list of game dates
    dates_q = f"""
    SELECT DISTINCT game_date
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date BETWEEN @start AND @end
      AND system_id = '{SYSTEM_ID}'
      AND prediction_correct IS NOT NULL
    ORDER BY game_date
    """
    dates_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("start", "DATE", args.start),
        bigquery.ScalarQueryParameter("end", "DATE", args.end),
    ])
    dates = [str(row.game_date) for row in client.query(dates_q, job_config=dates_config).result()]

    print(f"Backfilling {len(dates)} dates: {dates[0]} to {dates[-1]}")
    print(f"Signals: {', '.join(registry.tags())}")
    print(f"Dry run: {args.dry_run}\n")

    total_tags = 0
    total_bets = 0
    total_with_signals = 0

    for i, date_str in enumerate(dates):
        rows = load_date_data(client, date_str)

        tag_rows, bets_rows, health = evaluate_and_build(rows, registry, combo_reg=combo_reg)
        with_signals = sum(1 for r in tag_rows if r['signal_count'] > 0)

        status = f"[{i+1}/{len(dates)}] {date_str}: {len(rows)} preds, " \
                 f"{with_signals} with signals, {len(bets_rows)} best bets, health={health}"
        print(status)

        if not args.dry_run and tag_rows:
            write_rows(client, f'{PROJECT_ID}.nba_predictions.pick_signal_tags', tag_rows)
            if bets_rows:
                write_rows(client, f'{PROJECT_ID}.nba_predictions.signal_best_bets_picks', bets_rows)

        total_tags += len(tag_rows)
        total_bets += len(bets_rows)
        total_with_signals += with_signals

    print(f"\n{'=' * 60}")
    print(f"Backfill complete:")
    print(f"  Dates: {len(dates)}")
    print(f"  Tag rows written: {total_tags}")
    print(f"  Best bets written: {total_bets}")
    print(f"  Predictions with signals: {total_with_signals}")
    if args.dry_run:
        print("  (DRY RUN — nothing written)")


if __name__ == '__main__':
    main()
