#!/usr/bin/env python3
"""Quick segmented analysis: do hot_streak / rest_advantage work for specific player tiers?

Segments by line_value:
  - Stars: line >= 25 pts
  - Mid-tier: 15 <= line < 25
  - Role players: line < 15
"""

from collections import defaultdict
from google.cloud import bigquery

QUERY = """
WITH v9_preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.game_date,
    pa.predicted_points,
    pa.line_value,
    pa.recommendation,
    CAST(pa.predicted_points - pa.line_value AS FLOAT64) AS edge,
    pa.actual_points,
    pa.prediction_correct,
    pa.team_abbr
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  WHERE pa.game_date BETWEEN '2026-01-05' AND '2026-02-13'
    AND pa.system_id = 'catboost_v9'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

streak_data AS (
  SELECT
    player_lookup,
    game_date,
    LAG(CAST(prediction_correct AS INT64), 1) OVER w AS prev_correct_1,
    LAG(CAST(prediction_correct AS INT64), 2) OVER w AS prev_correct_2,
    LAG(CAST(prediction_correct AS INT64), 3) OVER w AS prev_correct_3
  FROM (
    SELECT *
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date >= '2025-10-22'
      AND system_id = 'catboost_v9'
      AND recommendation IN ('OVER', 'UNDER')
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE
      AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_id ORDER BY graded_at DESC
    ) = 1
  )
  WINDOW w AS (PARTITION BY player_lookup ORDER BY game_date)
),

game_stats AS (
  SELECT
    player_lookup,
    game_date,
    DATE_DIFF(game_date,
      LAG(game_date, 1) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY) AS rest_days,
    AVG(minutes_played)
      OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2025-10-22'
    AND minutes_played > 0
)

SELECT
  v9.*,
  sd.prev_correct_1, sd.prev_correct_2, sd.prev_correct_3,
  gs.rest_days,
  gs.minutes_avg_season
FROM v9_preds v9
LEFT JOIN streak_data sd
  ON sd.player_lookup = v9.player_lookup AND sd.game_date = v9.game_date
LEFT JOIN game_stats gs
  ON gs.player_lookup = v9.player_lookup AND gs.game_date = v9.game_date
ORDER BY v9.game_date, v9.player_lookup
"""


def get_tier(line_value):
    if line_value >= 25:
        return "Stars (25+)"
    elif line_value >= 15:
        return "Mid (15-25)"
    else:
        return "Role (<15)"


def get_minutes_tier(minutes_avg):
    if minutes_avg is None:
        return "Unknown"
    if minutes_avg >= 32:
        return "Heavy (32+)"
    elif minutes_avg >= 25:
        return "Starter (25-32)"
    else:
        return "Bench (<25)"


def is_hot_streak(row):
    return (row.get('prev_correct_1') == 1
            and row.get('prev_correct_2') == 1
            and row.get('prev_correct_3') == 1)


def is_rest_advantage(row):
    return (row.get('rest_days') is not None
            and row['rest_days'] >= 3
            and row['recommendation'] == 'OVER')


def compute_hr(picks):
    if not picks:
        return None, 0
    correct = sum(1 for p in picks if p['prediction_correct'])
    return round(100.0 * correct / len(picks), 1), len(picks)


def main():
    client = bigquery.Client(project='nba-props-platform')
    print("Loading data...")
    rows = [dict(r) for r in client.query(QUERY).result()]
    print(f"Loaded {len(rows)} predictions\n")

    # Segment by signal x tier
    for signal_name, signal_fn in [("hot_streak", is_hot_streak),
                                    ("rest_advantage", is_rest_advantage)]:
        print(f"{'=' * 65}")
        print(f"  {signal_name.upper()} — Segmented Analysis")
        print(f"{'=' * 65}")

        # By line value tier
        by_line_tier = defaultdict(list)
        by_min_tier = defaultdict(list)
        for row in rows:
            if signal_fn(row):
                tier = get_tier(float(row['line_value']))
                by_line_tier[tier].append(row)
                min_tier = get_minutes_tier(
                    float(row['minutes_avg_season']) if row.get('minutes_avg_season') else None)
                by_min_tier[min_tier].append(row)

        total_qualifying = sum(len(v) for v in by_line_tier.values())
        print(f"\nTotal qualifying: {total_qualifying}")

        print(f"\n  By Line Value:")
        print(f"  {'Tier':<18} {'N':>5} {'HR':>8} {'Profitable?':>12}")
        print(f"  {'-' * 45}")
        for tier in ["Stars (25+)", "Mid (15-25)", "Role (<15)"]:
            picks = by_line_tier.get(tier, [])
            hr, n = compute_hr(picks)
            profitable = "YES" if hr and hr > 52.4 else "no" if hr else "--"
            hr_str = f"{hr:.1f}%" if hr else "--"
            print(f"  {tier:<18} {n:>5} {hr_str:>8} {profitable:>12}")

        print(f"\n  By Minutes Tier:")
        print(f"  {'Tier':<18} {'N':>5} {'HR':>8} {'Profitable?':>12}")
        print(f"  {'-' * 45}")
        for tier in ["Heavy (32+)", "Starter (25-32)", "Bench (<25)", "Unknown"]:
            picks = by_min_tier.get(tier, [])
            if not picks:
                continue
            hr, n = compute_hr(picks)
            profitable = "YES" if hr and hr > 52.4 else "no" if hr else "--"
            hr_str = f"{hr:.1f}%" if hr else "--"
            print(f"  {tier:<18} {n:>5} {hr_str:>8} {profitable:>12}")

        # Per-window breakdown for the best tier
        print(f"\n  Per-Window Breakdown:")
        windows = [("W2", "2026-01-05", "2026-01-18"),
                   ("W3", "2026-01-19", "2026-01-31"),
                   ("W4", "2026-02-01", "2026-02-13")]
        print(f"  {'Tier':<18}", end="")
        for wn, _, _ in windows:
            print(f" {wn:>14}", end="")
        print()
        print(f"  {'-' * 60}")
        for tier in ["Stars (25+)", "Mid (15-25)", "Role (<15)"]:
            print(f"  {tier:<18}", end="")
            for _, ws, we in windows:
                picks = [p for p in by_line_tier.get(tier, [])
                         if ws <= str(p['game_date']) <= we]
                hr, n = compute_hr(picks)
                if hr is not None:
                    print(f" {hr:5.1f}% (N={n:<3})", end="")
                else:
                    print(f"     -- (N=0  )", end="")
            print()

        print()


if __name__ == '__main__':
    main()
