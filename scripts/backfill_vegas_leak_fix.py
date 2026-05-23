#!/usr/bin/env python3
"""
One-time backfill: clean the historical odds-snapshot leak from ml_feature_store_v2.

Background (2026-05-22):
  Five queries in data_processors/precompute/ml_feature_store/feature_extractor.py
  sorted nba_raw.odds_api_player_points_props by `snapshot_timestamp DESC` with
  no `minutes_before_tipoff >= 0` bound, so when a post-tipoff (in-game) snapshot
  existed they grabbed a line set while the game was already being played —
  leaking the game state into a "pre-game" feature. Baseline measurement on
  Jan-Feb 2026 found 9.6% of player-games had picked an in-game snapshot. The
  code is now fixed (commit 5bf94ebe + 0ea9a9ee); this script rewrites the
  contaminated historical rows.

Scope:
  Features 25 (vegas_points_line), 27 (vegas_line_move), 50 (multi_book_line_std),
  54 (prop_line_delta) — all have dedicated `feature_N_value` columns in
  ml_feature_store_v2 and are consumed by training/serving.

  Features 60 (line_movement_direction) and 61 (vig_skew) are out of scope here:
  they only exist in the deprecated `features` ARRAY column and have a separate
  cleanup path (V18 training reads odds directly via the now-fixed
  ml/experiments/quick_retrain.py, so the next clean retrain handles them).

  Bettingpros-fallback rows (where odds_api had no data for a player/date) are
  left untouched — the bettingpros leak class is different (created_at, no
  minutes_before_tipoff column) and out of scope.

Usage:
  python scripts/backfill_vegas_leak_fix.py --validate 2026-02-15
      # Print per-feature old-vs-new for one date. No writes.

  python scripts/backfill_vegas_leak_fix.py --start 2024-01-01 --end 2026-05-22 --dry-run
      # Count rows that would change per feature. No writes.

  python scripts/backfill_vegas_leak_fix.py --start 2024-01-01 --end 2026-05-22 --apply
      # Execute the MERGEs. Requires --apply to write.

  --feature 25,27,50,54   Comma list of feature indices to backfill (default: all).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from typing import Dict, List, Tuple

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("vegas-leak-backfill")

PROJECT_ID = "nba-props-platform"
FEATURE_STORE = f"{PROJECT_ID}.nba_predictions.ml_feature_store_v2"
ODDS_TABLE = f"{PROJECT_ID}.nba_raw.odds_api_player_points_props"

SUPPORTED_FEATURES = (25, 27, 50, 54)

FEATURE_NAMES = {
    25: "vegas_points_line",
    27: "vegas_line_move",
    50: "multi_book_line_std",
    54: "prop_line_delta",
}


# ---------------------------------------------------------------------------
# Source queries — same logic as the (now-fixed) feature_extractor methods,
# but date-RANGED so one query covers the whole backfill window.
# ---------------------------------------------------------------------------

def q_vegas_lines(start: str, end: str) -> str:
    """Returns per (player_lookup, game_date): f25 (vegas_points_line), f27 (vegas_line_move).
    Mirrors data_processors/precompute/ml_feature_store/feature_extractor.py::_batch_extract_vegas_lines.
    """
    return f"""
    WITH odds_api_lines AS (
      SELECT DISTINCT player_lookup, game_date,
        FIRST_VALUE(points_line) OVER (
          PARTITION BY player_lookup, game_date
          ORDER BY CASE WHEN bookmaker = 'draftkings' THEN 0 ELSE 1 END,
                   snapshot_timestamp DESC
        ) AS vegas_points_line,
        FIRST_VALUE(points_line) OVER (
          PARTITION BY player_lookup, game_date
          ORDER BY CASE WHEN bookmaker = 'draftkings' THEN 0 ELSE 1 END,
                   snapshot_timestamp ASC
        ) AS vegas_opening_line
      FROM `{ODDS_TABLE}`
      WHERE game_date BETWEEN '{start}' AND '{end}'
        AND points_line IS NOT NULL
        AND points_line > 0
        AND minutes_before_tipoff >= 0
    )
    SELECT player_lookup, game_date,
      CAST(vegas_points_line AS FLOAT64) AS f25,
      CAST(vegas_points_line - vegas_opening_line AS FLOAT64) AS f27
    FROM odds_api_lines
    WHERE vegas_points_line IS NOT NULL
    """


def q_multi_book_std(start: str, end: str) -> str:
    """Returns per (player_lookup, game_date): f50 (multi_book_line_std).
    Mirrors feature_extractor.py::_batch_extract_multi_book_line_std (odds_api path only).
    """
    return f"""
    WITH latest_per_book AS (
      SELECT player_lookup, game_date, bookmaker, points_line,
        ROW_NUMBER() OVER (
          PARTITION BY player_lookup, game_date, bookmaker
          ORDER BY snapshot_timestamp DESC
        ) AS rn
      FROM `{ODDS_TABLE}`
      WHERE game_date BETWEEN '{start}' AND '{end}'
        AND points_line IS NOT NULL
        AND points_line > 0
        AND bookmaker != 'bovada'
        AND minutes_before_tipoff >= 0
    )
    SELECT player_lookup, game_date,
      CAST(STDDEV(points_line) AS FLOAT64) AS f50
    FROM latest_per_book
    WHERE rn = 1
    GROUP BY player_lookup, game_date
    HAVING COUNT(DISTINCT bookmaker) >= 2
    """


def q_prop_line_delta(start: str, end: str) -> str:
    """Returns per (player_lookup, game_date): f54 (prop_line_delta).
    Today's median line minus the player's previous game's median line.
    Extends the lookback by 14 days so rows at the start of @start can see a prior game.
    """
    return f"""
    WITH per_book_latest AS (
      SELECT DISTINCT player_lookup, game_date, bookmaker,
        FIRST_VALUE(points_line) OVER (
          PARTITION BY player_lookup, game_date, bookmaker
          ORDER BY snapshot_timestamp DESC
        ) AS latest_line
      FROM `{ODDS_TABLE}`
      WHERE game_date BETWEEN DATE_SUB('{start}', INTERVAL 14 DAY) AND '{end}'
        AND points_line IS NOT NULL
        AND points_line > 0
        AND minutes_before_tipoff >= 0
    ),
    daily_consensus AS (
      SELECT player_lookup, game_date,
        APPROX_QUANTILES(latest_line, 2)[OFFSET(1)] AS consensus_line
      FROM per_book_latest
      GROUP BY player_lookup, game_date
      HAVING COUNT(DISTINCT bookmaker) >= 1
    ),
    with_prev AS (
      SELECT player_lookup, game_date, consensus_line,
        LAG(consensus_line) OVER (
          PARTITION BY player_lookup ORDER BY game_date
        ) AS prev_consensus
      FROM daily_consensus
    )
    SELECT player_lookup, game_date,
      CAST(consensus_line - prev_consensus AS FLOAT64) AS f54
    FROM with_prev
    WHERE prev_consensus IS NOT NULL
      AND game_date BETWEEN '{start}' AND '{end}'
    """


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def fetch_clean_values(client: bigquery.Client, feat: int, start: str, end: str):
    """Run the source query for a single feature and return a DataFrame."""
    q = {
        25: q_vegas_lines,
        27: q_vegas_lines,  # same source as 25
        50: q_multi_book_std,
        54: q_prop_line_delta,
    }[feat](start, end)
    df = client.query(q).result().to_dataframe()
    if feat == 25 and "f25" in df.columns:
        df = df[["player_lookup", "game_date", "f25"]].rename(columns={"f25": "new_value"})
    elif feat == 27 and "f27" in df.columns:
        df = df[["player_lookup", "game_date", "f27"]].rename(columns={"f27": "new_value"})
    elif feat == 50:
        df = df.rename(columns={"f50": "new_value"})
    elif feat == 54:
        df = df.rename(columns={"f54": "new_value"})
    return df


def validate_one_date(client: bigquery.Client, target_date: str, features: List[int]) -> None:
    """Compare each feature's stored value vs the newly computed clean value for one date."""
    print(f"\n=== Validation: {target_date} ===")
    for feat in features:
        new_df = fetch_clean_values(client, feat, target_date, target_date)
        # fetch current stored values
        stored_q = f"""
        SELECT player_lookup, feature_{feat}_value AS stored_value
        FROM `{FEATURE_STORE}`
        WHERE game_date = '{target_date}'
          AND feature_{feat}_value IS NOT NULL
        """
        stored_df = client.query(stored_q).result().to_dataframe()

        merged = stored_df.merge(new_df, on="player_lookup", how="inner")
        merged["diff"] = (merged["stored_value"] - merged["new_value"]).abs()
        differing = merged[merged["diff"] > 0.001]

        print(
            f"  feat_{feat} ({FEATURE_NAMES[feat]}): "
            f"n_joined={len(merged)}, n_differing={len(differing)}, "
            f"avg_diff={merged['diff'].mean():.4f}, max_diff={merged['diff'].max():.3f}"
        )
        if len(differing) > 0 and len(differing) <= 8:
            print(f"    sample (stored, new, diff):")
            for _, row in differing.head(8).iterrows():
                print(
                    f"      {row['player_lookup']:30s} "
                    f"{row['stored_value']:>8.2f} -> {row['new_value']:>8.2f}  "
                    f"(d={row['diff']:.3f})"
                )


def dry_run(client: bigquery.Client, start: str, end: str, features: List[int]) -> None:
    """Count rows that would be updated per feature, without writing."""
    print(f"\n=== Dry run: {start} -> {end} ===")
    for feat in features:
        new_df = fetch_clean_values(client, feat, start, end)
        stored_q = f"""
        SELECT player_lookup, game_date, feature_{feat}_value AS stored_value
        FROM `{FEATURE_STORE}`
        WHERE game_date BETWEEN '{start}' AND '{end}'
          AND feature_{feat}_value IS NOT NULL
        """
        stored_df = client.query(stored_q).result().to_dataframe()
        # Cast dates to comparable types
        new_df["game_date"] = new_df["game_date"].astype(str)
        stored_df["game_date"] = stored_df["game_date"].astype(str)
        merged = stored_df.merge(new_df, on=["player_lookup", "game_date"], how="inner")
        merged["diff"] = (merged["stored_value"] - merged["new_value"]).abs()
        differing = merged[merged["diff"] > 0.001]
        print(
            f"  feat_{feat} ({FEATURE_NAMES[feat]}): "
            f"joined={len(merged):>7d}, would_update={len(differing):>6d} "
            f"({100*len(differing)/max(len(merged),1):.2f}%), "
            f"avg_diff={merged['diff'].mean():.4f}"
        )


def apply_merges(client: bigquery.Client, start: str, end: str, features: List[int]) -> None:
    """Execute the MERGEs. One MERGE per feature for clarity."""
    print(f"\n=== Apply: {start} -> {end} ===")
    for feat in features:
        src_query = {
            25: q_vegas_lines(start, end),
            27: q_vegas_lines(start, end),
            50: q_multi_book_std(start, end),
            54: q_prop_line_delta(start, end),
        }[feat]
        src_col = f"f{feat}"
        merge_sql = f"""
        MERGE `{FEATURE_STORE}` AS t
        USING (
          SELECT player_lookup, game_date, {src_col} AS new_value
          FROM ({src_query})
        ) AS s
        ON t.player_lookup = s.player_lookup
           AND t.game_date = s.game_date
           AND t.game_date BETWEEN '{start}' AND '{end}'
        WHEN MATCHED AND
             t.feature_{feat}_value IS NOT NULL
             AND ABS(t.feature_{feat}_value - s.new_value) > 0.001
        THEN UPDATE SET feature_{feat}_value = s.new_value
        """
        print(f"  feat_{feat} ({FEATURE_NAMES[feat]}): running MERGE ...")
        job = client.query(merge_sql)
        job.result()
        affected = job.num_dml_affected_rows
        print(f"    -> {affected} rows updated")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_features(spec: str) -> List[int]:
    out = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        n = int(tok)
        if n not in SUPPORTED_FEATURES:
            raise SystemExit(
                f"feature {n} not supported (supported: {SUPPORTED_FEATURES})"
            )
        out.append(n)
    return out or list(SUPPORTED_FEATURES)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--validate", metavar="YYYY-MM-DD", help="Validation mode: compare stored vs clean for one date")
    p.add_argument("--start", help="Backfill start date (YYYY-MM-DD)")
    p.add_argument("--end", help="Backfill end date (YYYY-MM-DD)")
    p.add_argument("--dry-run", action="store_true", help="Count affected rows without writing")
    p.add_argument("--apply", action="store_true", help="Actually run the MERGEs (writes to BQ)")
    p.add_argument("--feature", default=",".join(str(f) for f in SUPPORTED_FEATURES),
                   help=f"Comma-separated feature indices (subset of {SUPPORTED_FEATURES})")
    args = p.parse_args()

    features = parse_features(args.feature)
    client = bigquery.Client(project=PROJECT_ID)

    if args.validate:
        validate_one_date(client, args.validate, features)
        return 0

    if not (args.start and args.end):
        p.error("--start and --end are required for dry-run / apply modes (or use --validate)")

    # sanity-check dates
    datetime.strptime(args.start, "%Y-%m-%d")
    datetime.strptime(args.end, "%Y-%m-%d")

    if args.apply and args.dry_run:
        p.error("--apply and --dry-run are mutually exclusive")

    if not (args.apply or args.dry_run):
        p.error("specify one of --dry-run or --apply")

    if args.dry_run:
        dry_run(client, args.start, args.end, features)
    else:
        confirm = input(f"About to MERGE into {FEATURE_STORE} for {args.start} -> {args.end}, features {features}. Type 'apply' to proceed: ")
        if confirm.strip() != "apply":
            print("aborted")
            return 1
        apply_merges(client, args.start, args.end, features)

    return 0


if __name__ == "__main__":
    sys.exit(main())
