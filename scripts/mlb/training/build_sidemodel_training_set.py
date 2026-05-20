#!/usr/bin/env python3
"""
Build the MLB binary side-model training set (Path B, slice 2).

Reconstructs the point-in-time feature vector for every graded
catboost_v2_regressor pick and pairs it with the binary outcome
(was the pick correct?). Output: /tmp/mlb_sidemodel_training.csv.

The side-model's target is P(prediction_correct = True). Features are
reconstructed with the SAME loader the production worker uses
(pitcher_loader.load_batch_features), so the training feature contract
matches what binary_v1.BinaryV1SideModel.score() receives at predict time
-- the worker hands that loader's per-pitcher dict straight into score().

load_batch_features is called once per game_date (a single BQ query that
returns every pitcher for that date), exactly as the worker calls it in
run_multi_system_batch_predictions. No per-pitcher caching is needed.

Run:
    PYTHONPATH=. .venv/bin/python3 scripts/mlb/training/build_sidemodel_training_set.py
"""

import argparse
import logging
import os
import sys
from collections import defaultdict

import pandas as pd

# Repo root on path so `predictions.mlb.*` resolves (mirrors worker.py).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))

from google.cloud import bigquery  # noqa: E402
from predictions.mlb.pitcher_loader import load_batch_features  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_sidemodel_training_set")

PROJECT_ID = "nba-props-platform"

# Predictor CORE features (raw load_batch_features column names). The regressor
# applies zero-tolerance to these -- it BLOCKS a prediction if any is null.
# Mirroring that drop keeps the training set to rows the regressor could
# actually have predicted on. Source: CATBOOST_V2_FEATURES minus
# NAN_TOLERANT_FEATURES in catboost_v2_regressor_predictor.py, mapped back to
# the raw column names load_batch_features emits.
PREDICTOR_CORE_FEATURES = [
    "k_avg_last_3", "k_avg_last_5", "k_avg_last_10", "k_std_last_10",
    "ip_avg_last_5", "season_k_per_9", "era_rolling_10", "whip_rolling_10",
    "season_games_started", "season_strikeouts", "is_home",
    "opponent_team_k_rate", "ballpark_k_factor", "days_rest",
    "games_last_30_days", "pitch_count_avg_last_5", "season_innings",
    "k_avg_vs_line", "strikeouts_line", "projection_diff", "over_implied_prob",
]

# Features the trainer is expected to use -- surfaced here only so the
# coverage report at the end confirms they are dense enough to deploy
# (binary_v1.score() returns None on ANY missing feature).
SIDEMODEL_CANDIDATE_FEATURES = [
    "k_avg_last_3", "k_avg_last_5", "k_avg_last_10", "k_std_last_10",
    "ip_avg_last_5", "season_k_per_9", "era_rolling_10", "whip_rolling_10",
    "opponent_team_k_rate", "ballpark_k_factor", "days_rest",
    "pitch_count_avg_last_5", "k_avg_vs_line", "strikeouts_line",
    "over_implied_prob",
]


def fetch_graded_picks(client: bigquery.Client, start_date: str) -> list:
    """Graded catboost_v2_regressor OVER/UNDER picks with a real prop line."""
    query = """
    SELECT
        game_date,
        pitcher_lookup,
        system_id,
        recommendation,
        CAST(edge AS FLOAT64) AS edge,
        CAST(line_value AS FLOAT64) AS line_value,
        CAST(predicted_strikeouts AS FLOAT64) AS predicted_strikeouts,
        prediction_correct
    FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
    WHERE game_date >= @start_date
      AND system_id = 'catboost_v2_regressor'
      AND has_prop_line = TRUE
      AND prediction_correct IS NOT NULL
      AND recommendation IN ('OVER', 'UNDER')
    ORDER BY game_date, pitcher_lookup
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("start_date", "DATE", start_date)]
    )
    return list(client.query(query, job_config=job_config).result())


def main() -> int:
    ap = argparse.ArgumentParser(description="Build MLB side-model training set")
    ap.add_argument("--start-date", default="2026-03-01",
                    help="Earliest game_date to include (default 2026-03-01)")
    ap.add_argument("--output", default="/tmp/mlb_sidemodel_training.csv")
    args = ap.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    logger.info("Querying graded catboost_v2_regressor picks since %s ...", args.start_date)
    picks = fetch_graded_picks(client, args.start_date)
    logger.info("Fetched %d graded picks", len(picks))
    if not picks:
        logger.error("No graded picks found -- nothing to build.")
        return 1

    picks_by_date = defaultdict(list)
    for p in picks:
        picks_by_date[p["game_date"]].append(p)
    dates = sorted(picks_by_date)
    logger.info("Picks span %s -> %s across %d dates", dates[0], dates[-1], len(dates))

    rows = []
    n_no_features = 0
    n_core_null = 0
    for i, game_date in enumerate(dates, 1):
        date_picks = picks_by_date[game_date]
        lookups = sorted({p["pitcher_lookup"] for p in date_picks})

        # One BQ query per date -- the exact call shape the worker uses.
        features_by_pitcher = load_batch_features(
            game_date=game_date, pitcher_lookups=lookups, project_id=PROJECT_ID
        )
        # Underscore-stripped fallback index in case pitcher_lookup formats
        # diverge between prediction_accuracy and pitcher_game_summary.
        norm_index = {k.replace("_", ""): v for k, v in features_by_pitcher.items()}

        for p in date_picks:
            lookup = p["pitcher_lookup"]
            features = features_by_pitcher.get(lookup)
            if features is None:
                features = norm_index.get(lookup.replace("_", ""))
            if features is None:
                n_no_features += 1
                continue

            # Mirror the regressor's zero-tolerance on core inputs.
            if any(features.get(f) is None for f in PREDICTOR_CORE_FEATURES):
                n_core_null += 1
                continue

            row = {
                "game_date": game_date.isoformat(),
                "pitcher_lookup": lookup,
                "system_id": p["system_id"],
                "recommendation": p["recommendation"],
                "outcome": 1 if p["prediction_correct"] else 0,
                "edge": p["edge"],
                "predicted_strikeouts": p["predicted_strikeouts"],
                "line_value": p["line_value"],
            }
            feat = dict(features)
            feat.pop("player_lookup", None)  # duplicates pitcher_lookup
            feat.pop("rn", None)             # internal ROW_NUMBER artifact
            row.update(feat)
            rows.append(row)

        if i % 10 == 0 or i == len(dates):
            logger.info("  processed %d/%d dates, %d rows so far", i, len(dates), len(rows))

    if not rows:
        logger.error("No usable training rows after feature reconstruction.")
        return 1

    df = pd.DataFrame(rows)
    df.to_csv(args.output, index=False)

    # ---- Summary ----
    over = df[df["recommendation"] == "OVER"]
    under = df[df["recommendation"] == "UNDER"]
    print()
    print("=" * 66)
    print("  MLB SIDE-MODEL TRAINING SET BUILD")
    print("=" * 66)
    print(f"  Graded picks queried:        {len(picks)}")
    print(f"  Skipped (no features):       {n_no_features}")
    print(f"  Dropped (core feature null): {n_core_null}")
    print(f"  Final training rows:         {len(df)}")
    print(f"  Date range:                  {df['game_date'].min()} -> {df['game_date'].max()}")
    print(f"  Win rate (outcome=1):        {df['outcome'].mean():.4f}  "
          f"({int(df['outcome'].sum())}/{len(df)})")
    print(f"  OVER:  {len(over):>4} picks, win rate "
          f"{(over['outcome'].mean() if len(over) else float('nan')):.4f}")
    print(f"  UNDER: {len(under):>4} picks, win rate "
          f"{(under['outcome'].mean() if len(under) else float('nan')):.4f}")
    print()
    print("  Feature non-null coverage (side-model candidates):")
    for f in SIDEMODEL_CANDIDATE_FEATURES:
        cov = df[f].notna().mean() if f in df.columns else 0.0
        print(f"    {f:<26} {cov * 100:6.1f}%")
    print()
    print("  Feature non-null coverage (NaN-tolerant / excluded from side-model):")
    for f in ["fip", "gb_pct", "o_swing_pct", "z_contact_pct",
              "swstr_pct_last_3", "season_swstr_pct", "bp_projection"]:
        cov = df[f].notna().mean() if f in df.columns else 0.0
        print(f"    {f:<26} {cov * 100:6.1f}%")
    print()
    print(f"  Written: {args.output}  ({len(df.columns)} columns)")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
