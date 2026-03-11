#!/usr/bin/env python3
"""Review MLB pitcher blacklist — recommend additions/removals based on recent data.

Queries prediction_accuracy (or replay results) to find:
  1. Blacklisted pitchers who are now beating the line (HR >= 55%, N >= 10) → REMOVE
  2. Non-blacklisted pitchers who are losing (HR < 40%, N >= 15) → ADD
  3. Blacklisted pitchers with insufficient data to evaluate → KEEP (no change)

Usage:
    PYTHONPATH=. python bin/mlb/review_blacklist.py
    PYTHONPATH=. python bin/mlb/review_blacklist.py --min-games 10 --since 2026-04-01
    PYTHONPATH=. python bin/mlb/review_blacklist.py --dry-run  # just print, no suggestions
"""

import argparse
import sys
from datetime import datetime, timedelta

from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"

# Current blacklist — keep in sync with ml/signals/mlb/signals.py PitcherBlacklistFilter.BLACKLIST
CURRENT_BLACKLIST = frozenset([
    'tanner_bibee', 'mitchell_parker', 'casey_mize', 'mitch_keller',
    'logan_webb', 'jose_berrios', 'logan_gilbert', 'logan_allen',
    'jake_irvin', 'george_kirby', 'mackenzie_gore', 'bailey_ober',
    'zach_eflin', 'ryne_nelson', 'jameson_taillon', 'ryan_feltner',
    'luis_severino', 'randy_vasquez',
    'adrian_houser', 'stephen_kolek', 'dean_kremer', 'michael_mcgreevy',
    'tyler_mahle',
    'ranger_suárez', 'cade_horton', 'blake_snell', 'luis_castillo',
    'paul_skenes',
])

# Thresholds
REMOVE_HR_THRESHOLD = 55.0   # Remove from blacklist if HR >= this
REMOVE_MIN_N = 10            # Minimum picks to evaluate for removal
ADD_HR_THRESHOLD = 40.0      # Add to blacklist if HR < this
ADD_MIN_N = 15               # Minimum picks to evaluate for addition
EDGE_THRESHOLD = 0.75        # Only evaluate picks with edge >= this


def parse_args():
    parser = argparse.ArgumentParser(description="Review MLB pitcher blacklist")
    parser.add_argument(
        "--since", type=str, default=None,
        help="Only consider predictions since this date (YYYY-MM-DD). Default: all available data."
    )
    parser.add_argument(
        "--min-games-remove", type=int, default=REMOVE_MIN_N,
        help=f"Min picks to recommend removal (default: {REMOVE_MIN_N})"
    )
    parser.add_argument(
        "--min-games-add", type=int, default=ADD_MIN_N,
        help=f"Min picks to recommend addition (default: {ADD_MIN_N})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Just print stats, no recommendations"
    )
    return parser.parse_args()


def query_pitcher_performance(client, since_date=None):
    """Query OVER prediction accuracy by pitcher."""
    date_filter = ""
    if since_date:
        date_filter = f"AND game_date >= '{since_date}'"

    query = f"""
    SELECT
        player_lookup AS pitcher_lookup,
        COUNT(*) AS n_picks,
        COUNTIF(prediction_correct) AS n_correct,
        ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) AS hit_rate,
        ROUND(AVG(ABS(predicted_points - line_value)), 2) AS avg_edge
    FROM `{PROJECT_ID}.mlb_predictions.prediction_accuracy`
    WHERE has_prop_line = TRUE
      AND recommendation = 'OVER'
      AND prediction_correct IS NOT NULL
      AND ABS(predicted_points - line_value) >= {EDGE_THRESHOLD}
      {date_filter}
    GROUP BY player_lookup
    ORDER BY n_picks DESC
    """
    return client.query(query).to_dataframe()


def main():
    args = parse_args()
    client = bigquery.Client(project=PROJECT_ID)

    print("=" * 70)
    print("MLB PITCHER BLACKLIST REVIEW")
    print("=" * 70)
    print(f"Current blacklist: {len(CURRENT_BLACKLIST)} pitchers")
    if args.since:
        print(f"Evaluating predictions since: {args.since}")
    print(f"Edge threshold: >= {EDGE_THRESHOLD} K")
    print()

    try:
        df = query_pitcher_performance(client, args.since)
    except Exception as e:
        print(f"ERROR: Could not query prediction_accuracy: {e}")
        print("This table may not exist for MLB yet. Run this after predictions accumulate.")
        sys.exit(1)

    if df.empty:
        print("No prediction data found. Run this after the season starts and predictions accumulate.")
        sys.exit(0)

    # --- Blacklisted pitchers performance ---
    print("BLACKLISTED PITCHERS — Recent Performance")
    print("-" * 60)
    bl_df = df[df['pitcher_lookup'].isin(CURRENT_BLACKLIST)].sort_values('hit_rate', ascending=False)
    if bl_df.empty:
        print("  No blacklisted pitchers found in prediction data.")
    else:
        for _, row in bl_df.iterrows():
            marker = ""
            if row['n_picks'] >= args.min_games_remove and row['hit_rate'] >= REMOVE_HR_THRESHOLD:
                marker = " ← RECOMMEND REMOVE"
            elif row['n_picks'] < args.min_games_remove:
                marker = " (insufficient data)"
            print(f"  {row['pitcher_lookup']:30s} {row['n_correct']:3.0f}/{row['n_picks']:3.0f} "
                  f"({row['hit_rate']:5.1f}% HR) avg_edge={row['avg_edge']:.2f}{marker}")

    print()

    # --- Non-blacklisted pitchers who are struggling ---
    print("NON-BLACKLISTED PITCHERS — Potential Additions")
    print("-" * 60)
    non_bl_df = df[~df['pitcher_lookup'].isin(CURRENT_BLACKLIST)].copy()
    candidates = non_bl_df[
        (non_bl_df['n_picks'] >= args.min_games_add) &
        (non_bl_df['hit_rate'] < ADD_HR_THRESHOLD)
    ].sort_values('hit_rate')

    if candidates.empty:
        print("  No non-blacklisted pitchers below threshold.")
    else:
        for _, row in candidates.iterrows():
            print(f"  {row['pitcher_lookup']:30s} {row['n_correct']:3.0f}/{row['n_picks']:3.0f} "
                  f"({row['hit_rate']:5.1f}% HR) avg_edge={row['avg_edge']:.2f} ← RECOMMEND ADD")

    print()

    # --- Summary ---
    if not args.dry_run:
        removals = bl_df[
            (bl_df['n_picks'] >= args.min_games_remove) &
            (bl_df['hit_rate'] >= REMOVE_HR_THRESHOLD)
        ]['pitcher_lookup'].tolist()

        additions = candidates['pitcher_lookup'].tolist() if not candidates.empty else []

        print("RECOMMENDATIONS")
        print("-" * 60)
        if removals:
            print(f"  REMOVE from blacklist ({len(removals)}):")
            for p in removals:
                print(f"    - '{p}'")
        else:
            print("  No removals recommended.")

        if additions:
            print(f"  ADD to blacklist ({len(additions)}):")
            for p in additions:
                print(f"    - '{p}'")
        else:
            print("  No additions recommended.")

        if removals or additions:
            print()
            print("  To apply: Edit BLACKLIST in ml/signals/mlb/signals.py")
            print("            AND PITCHER_BLACKLIST in scripts/mlb/training/season_replay.py")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
