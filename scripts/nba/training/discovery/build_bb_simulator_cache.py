#!/usr/bin/env python3
"""Rebuild the 6 enrichment extracts the signal-discovery stack reads from
`results/bb_simulator/` (the lost bb_enriched_simulator.py).

`scripts/nba/training/discovery/data_loader.py` left-joins these onto the
walk-forward predictions (built by build_walkforward_predictions.py) on
(game_date, player_lookup). Column contract mapped from feature_scanner.py:507-526.

Produces:
  feature_store_enrichment.csv        — 23 named features (feature_N_value aliased)
  feature_store_extra.csv             — 13 named features (feature_N_value aliased)
  player_game_summary_enrichment.csv  — 13 PGS rolling/season stats (LEAKAGE-SAFE windows)
  bettingpros_multibook.csv           — line_std/line_movement/book_count + real odds_american
  schedule_enrichment.csv             — keys + opponent/home (no cols referenced by discovery)
(predictions_2025_26_all_models.csv already produced by build_walkforward_predictions.py)

Leakage discipline: every rolling/season PGS window ENDS at `1 PRECEDING` (MEMORY rule).
NO writes to BQ/GCS. Reproducible cache (results/ gitignored).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from google.cloud import bigquery
from shared.ml.training_data_loader import get_quality_where_clause

PROJECT_ID = "nba-props-platform"
OUT = Path("results/bb_simulator"); OUT.mkdir(parents=True, exist_ok=True)
RANGE = ("2021-10-01", "2026-07-01")

# named enrichment col -> feature store index (from FEATURE_STORE_NAMES)
FS_ENRICH = {
    'days_rest': 39, 'opponent_pace': 14, 'scoring_trend_slope': 44, 'points_std_last_10': 3,
    'prop_under_streak': 52, 'prop_over_streak': 51, 'over_rate_last_10': 55, 'implied_team_total': 42,
    'spread_magnitude': 41, 'multi_book_line_std': 50, 'games_vs_opponent': 30, 'teammate_usage_available': 47,
    'star_teammates_out': 37, 'points_avg_season': 2, 'rest_advantage': 9, 'vegas_points_line': 25,
    'minutes_avg_last_10': 31, 'game_total_line': 38, 'points_avg_last_3': 43,
    'consecutive_games_below_avg': 46, 'usage_rate_last_5': 48, 'back_to_back': 16, 'home_away': 15,
}
FS_EXTRA = {
    'prop_line_delta': 54, 'points_avg_last_5': 0, 'points_avg_last_10': 1, 'recent_trend': 11,
    'team_pace': 22, 'team_win_pct': 24, 'avg_pts_vs_opponent': 29, 'dnp_rate': 33, 'pts_slope_10g': 34,
    'minutes_load_last_7d': 40, 'deviation_from_avg_last3': 45, 'line_vs_season_avg': 53,
    'margin_vs_line_avg_last5': 56,
}


def fs_query(mapping):
    quality = get_quality_where_clause("mf")
    cols = ',\n      '.join(f'mf.feature_{i}_value AS {name}' for name, i in mapping.items())
    return f"""
    SELECT mf.player_lookup, mf.game_date,
      {cols}
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    WHERE mf.game_date BETWEEN '{RANGE[0]}' AND '{RANGE[1]}'
      AND {quality}
    """


PGS_QUERY = f"""
WITH base AS (
  SELECT player_lookup, game_date, season_year, points, minutes_played, plus_minus,
         fg_makes, fg_attempts, three_pt_makes, three_pt_attempts, ft_attempts, usage_rate
  FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '{RANGE[0]}' AND '{RANGE[1]}'
    AND points IS NOT NULL AND minutes_played > 0
    AND (is_dnp IS NULL OR is_dnp = FALSE)
)
SELECT player_lookup, game_date,
  -- season-to-date (partition by season), leakage-safe (... AND 1 PRECEDING)
  SAFE_DIVIDE(SUM(fg_makes) OVER w_season, SUM(fg_attempts) OVER w_season) AS fg_pct_season,
  SAFE_DIVIDE(SUM(three_pt_makes) OVER w_season, SUM(three_pt_attempts) OVER w_season) AS three_pct_season,
  AVG(three_pt_attempts) OVER w_season AS three_pa_per_game,
  AVG(minutes_played) OVER w_season AS minutes_avg_season,
  AVG(usage_rate) OVER w_season AS usage_rate,
  -- rolling last-N games (career order), leakage-safe
  AVG(ft_attempts) OVER w10 AS fta_avg_last_10,
  SAFE_DIVIDE(STDDEV(ft_attempts) OVER w10, NULLIF(AVG(ft_attempts) OVER w10, 0)) AS fta_cv_last_10,
  SAFE_DIVIDE(SUM(fg_makes) OVER w3, SUM(fg_attempts) OVER w3) AS fg_pct_last_3,
  SAFE_DIVIDE(SUM(three_pt_makes) OVER w3, SUM(three_pt_attempts) OVER w3) AS three_pct_last_3,
  AVG(points) OVER w10 AS mean_points_10g,
  LAG(plus_minus, 1) OVER w_order AS prev_pm_1,
  LAG(plus_minus, 2) OVER w_order AS prev_pm_2,
  LAG(plus_minus, 3) OVER w_order AS prev_pm_3
FROM base
WINDOW
  w_season AS (PARTITION BY player_lookup, season_year ORDER BY game_date
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
  w10 AS (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
  w3  AS (PARTITION BY player_lookup ORDER BY game_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING),
  w_order AS (PARTITION BY player_lookup ORDER BY game_date)
"""

BP_QUERY = f"""
WITH one_per_book AS (
  SELECT game_date, player_lookup, book_id, points_line, opening_line, odds_american, is_best_line
  FROM `{PROJECT_ID}.nba_raw.bettingpros_player_points_props`
  WHERE market_type = 'points' AND bet_side = 'over'
    AND game_date BETWEEN '{RANGE[0]}' AND '{RANGE[1]}'
    AND points_line IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY game_date, player_lookup, book_id ORDER BY bookmaker_last_update DESC) = 1
)
SELECT game_date, player_lookup,
  COUNT(DISTINCT book_id) AS book_count,
  STDDEV(points_line) AS line_std,
  AVG(points_line) - AVG(opening_line) AS line_movement,
  APPROX_QUANTILES(odds_american, 2)[OFFSET(1)] AS over_odds_median,
  MIN(points_line) AS line_min, MAX(points_line) AS line_max
FROM one_per_book
GROUP BY game_date, player_lookup
"""

SCHED_QUERY = f"""
SELECT DISTINCT player_lookup, game_date, opponent_team_abbr, team_abbr
FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '{RANGE[0]}' AND '{RANGE[1]}'
  AND points IS NOT NULL AND minutes_played > 0
"""


def dump(client, name, query):
    print(f"  building {name} ...", flush=True)
    df = client.query(query).to_dataframe()
    if 'game_date' in df.columns:
        df['game_date'] = df['game_date'].astype(str)
    path = OUT / f"{name}.csv"
    df.to_csv(path, index=False)
    print(f"    -> {path} : {len(df):,} rows, {len(df.columns)} cols", flush=True)
    return df


def main():
    client = bigquery.Client(project=PROJECT_ID)
    dump(client, "feature_store_enrichment", fs_query(FS_ENRICH))
    dump(client, "feature_store_extra", fs_query(FS_EXTRA))
    dump(client, "player_game_summary_enrichment", PGS_QUERY)
    bp = dump(client, "bettingpros_multibook", BP_QUERY)
    dump(client, "schedule_enrichment", SCHED_QUERY)
    print(f"\n  bettingpros per-season coverage:")
    if len(bp):
        bp['yr'] = bp['game_date'].str[:4]
        print("   ", {k: int(v) for k, v in bp['yr'].value_counts().sort_index().items()})
    print("DONE")


if __name__ == '__main__':
    main()
