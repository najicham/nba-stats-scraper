#!/usr/bin/env python3
"""
Arsenal metric ↔ MLB prediction hit rate correlation.

For each graded MLB prediction, computes three as-of arsenal metrics
(putaway-pitch whiff rate on 2-strike counts, late-game velocity fade,
arsenal concentration) using ONLY per-pitch data prior to the pick date,
then stratifies prediction hit rate by each metric's tier.

Purpose: decide whether any of these metrics should become a production
signal (boost/rescue/filter). Re-run monthly as data accumulates.

Usage:
    python scripts/mlb/analysis/arsenal_signal_correlation.py
    python scripts/mlb/analysis/arsenal_signal_correlation.py --since 2026-05-01
"""

import argparse
import logging
from google.cloud import bigquery

logger = logging.getLogger(__name__)
PROJECT_ID = "nba-props-platform"


# sql-template — interpolated via .format(project=...) in _run()
_PUTAWAY_SQL = """
WITH predictions AS (
  SELECT pa.pitcher_lookup, pa.game_date, pa.recommendation, pa.prediction_correct
  FROM `{project}.mlb_predictions.prediction_accuracy` pa
  WHERE pa.game_date >= DATE(@since)
    AND pa.prediction_correct IS NOT NULL
    AND pa.has_prop_line
    AND pa.recommendation IN ('OVER', 'UNDER')
),
pitches_by_type AS (
  SELECT
    pred.pitcher_lookup, pred.game_date AS pick_date, pred.recommendation, pred.prediction_correct,
    p.pitch_type_code,
    COUNT(*) AS pitches, COUNTIF(p.is_whiff) AS whiffs, COUNTIF(p.is_swing) AS swings
  FROM predictions pred
  JOIN `{project}.mlb_raw.mlb_game_feed_pitches` p
    ON REPLACE(p.pitcher_lookup, '_', '') = REPLACE(pred.pitcher_lookup, '_', '')
  WHERE p.game_date >= DATE('2026-03-01')
    AND p.game_date < pred.game_date
    AND DATE_DIFF(pred.game_date, p.game_date, DAY) <= 21
    AND p.count_strikes = 2 AND p.pitch_type_code IS NOT NULL
  GROUP BY 1, 2, 3, 4, 5
),
putaway_ranked AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY pitcher_lookup, pick_date ORDER BY pitches DESC
  ) AS rn FROM pitches_by_type
),
putaway_top AS (
  SELECT pitcher_lookup, pick_date, recommendation, prediction_correct,
    pitch_type_code AS putaway_code,
    CASE WHEN swings >= 5 THEN ROUND(100.0 * whiffs / swings, 1) END AS putaway_whiff
  FROM putaway_ranked WHERE rn = 1
)
SELECT
  recommendation,
  CASE
    WHEN putaway_whiff IS NULL THEN '0_NULL'
    WHEN putaway_whiff >= 25 THEN '3_elite (>=25%)'
    WHEN putaway_whiff >= 15 THEN '2_good (15-25%)'
    ELSE '1_weak (<15%)'
  END AS putaway_tier,
  COUNT(*) AS n,
  COUNTIF(prediction_correct) AS hits,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hit_rate
FROM (
  SELECT pred.*, pt.putaway_whiff
  FROM predictions pred LEFT JOIN putaway_top pt
    ON pred.pitcher_lookup = pt.pitcher_lookup AND pred.game_date = pt.pick_date
)
GROUP BY 1, 2 ORDER BY 1, 2
"""


# sql-template — interpolated via .format(project=...) in _run()
_VELO_FADE_SQL = """
WITH predictions AS (
  SELECT pa.pitcher_lookup, pa.game_date, pa.recommendation, pa.prediction_correct
  FROM `{project}.mlb_predictions.prediction_accuracy` pa
  WHERE pa.game_date >= DATE(@since)
    AND pa.prediction_correct IS NOT NULL
    AND pa.has_prop_line
    AND pa.recommendation IN ('OVER', 'UNDER')
),
asof_velo AS (
  SELECT
    pred.pitcher_lookup, pred.game_date AS pick_date, pred.recommendation, pred.prediction_correct,
    AVG(IF(p.inning = 1, p.velocity, NULL)) AS velo_i1,
    AVG(IF(p.inning >= 5, p.velocity, NULL)) AS velo_i5plus,
    COUNTIF(p.inning = 1) AS n_i1,
    COUNTIF(p.inning >= 5) AS n_i5plus
  FROM predictions pred
  JOIN `{project}.mlb_raw.mlb_game_feed_pitches` p
    ON REPLACE(p.pitcher_lookup, '_', '') = REPLACE(pred.pitcher_lookup, '_', '')
  WHERE p.game_date >= DATE('2026-03-01')
    AND p.game_date < pred.game_date
    AND DATE_DIFF(pred.game_date, p.game_date, DAY) <= 30
    AND p.pitch_type_code IN ('FF', 'SI', 'FC') AND p.velocity IS NOT NULL
  GROUP BY 1, 2, 3, 4
),
fade AS (
  SELECT *,
    CASE WHEN n_i1 >= 5 AND n_i5plus >= 5
         THEN ROUND(velo_i1 - velo_i5plus, 1) END AS fade_mph
  FROM asof_velo
)
SELECT
  recommendation,
  CASE
    WHEN fade_mph IS NULL THEN '0_NULL'
    WHEN fade_mph >= 2 THEN '3_heavy (>=2 mph)'
    WHEN fade_mph >= 1 THEN '2_moderate (1-2)'
    WHEN fade_mph >= 0 THEN '1_light (0-1)'
    ELSE '0_builds'
  END AS fade_tier,
  COUNT(*) AS n,
  COUNTIF(prediction_correct) AS hits,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hit_rate
FROM (
  SELECT p.*, f.fade_mph
  FROM predictions p LEFT JOIN fade f
    ON p.pitcher_lookup = f.pitcher_lookup AND p.game_date = f.pick_date
)
GROUP BY 1, 2 ORDER BY 1, 2
"""


def _run(client: bigquery.Client, sql: str, since: str):
    job = client.query(
        sql.format(project=PROJECT_ID),
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("since", "STRING", since)]
        ),
    )
    rows = list(job.result())
    return rows


def _print_table(title: str, rows):
    print(f"\n== {title} ==")
    if not rows:
        print("  (no rows)")
        return
    headers = list(rows[0].keys())
    widths = [max(len(str(h)), max((len(str(r[h])) for r in rows), default=0)) for h in headers]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for r in rows:
        print(fmt.format(*[r[h] for h in headers]))


def main():
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="2026-04-01", help="Earliest prediction date (YYYY-MM-DD)")
    args = ap.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    putaway = _run(client, _PUTAWAY_SQL, args.since)
    _print_table(f"Putaway-pitch whiff rate vs HR (since {args.since})", putaway)

    fade = _run(client, _VELO_FADE_SQL, args.since)
    _print_table(f"Velo fade vs HR (since {args.since})", fade)

    total_n = sum(r["n"] for r in putaway) if putaway else 0
    if total_n < 300:
        print(f"\nNote: total N={total_n}. Stratified HR needs ≥ ~300 graded picks "
              f"(~50 per bucket × 6 buckets) for reliable signal detection. "
              f"Re-run when N grows.")


if __name__ == "__main__":
    main()
