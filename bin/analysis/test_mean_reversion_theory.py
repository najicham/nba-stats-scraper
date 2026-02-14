#!/usr/bin/env python3
"""
Test Mean Reversion Theory for NBA Player Props

Tests the hypothesis that:
1. Players with 2+ consecutive "under" games are more likely to go "over" on the next game
2. Players with 2+ consecutive low FG% games are more likely to have higher FG% on the next game
3. Focus on star players (high scorers) for better accuracy

Analysis Categories:
- Prop Line Streak Analysis (2+ unders → over?)
- FG% Mean Reversion (2+ low FG% → higher FG%?)
- Points Scoring Streaks (2+ low scoring → bounce back?)
- Star Player Performance (does it work better for high-usage players?)
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from google.cloud import bigquery
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

# No shared utilities needed - use bigquery client directly


def run_prop_streak_analysis(
    client: bigquery.Client,
    start_date: str,
    end_date: str,
    min_ppg: float = 15.0
) -> pd.DataFrame:
    """
    Test if players with 2+ consecutive UNDER games are more likely to go OVER.

    Returns hit rate for "bet over after 2+ unders" vs baseline.
    """
    query = f"""
    WITH player_games AS (
      -- Get all graded predictions with actual results
      SELECT
        pa.game_date,
        pa.player_name,
        pa.player_id,
        pa.predicted_points,
        pa.vegas_line,
        pa.actual_points,
        pa.hit,
        pa.over_under,
        -- Get player's season PPG for star filter
        pgs.points_avg_season
      FROM nba_predictions.prediction_accuracy pa
      LEFT JOIN nba_predictions.ml_feature_store_v2 pgs
        ON pa.player_id = pgs.player_id
        AND pa.game_date = pgs.game_date
      WHERE pa.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND pa.actual_points IS NOT NULL
        AND pa.vegas_line IS NOT NULL
        AND pa.over_under IS NOT NULL
    ),

    streak_analysis AS (
      SELECT
        game_date,
        player_name,
        player_id,
        predicted_points,
        vegas_line,
        actual_points,
        hit,
        over_under,
        points_avg_season,

        -- Calculate consecutive unders before this game
        SUM(CASE WHEN over_under = 'UNDER' THEN 1 ELSE 0 END)
          OVER (
            PARTITION BY player_id
            ORDER BY game_date
            ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
          ) as unders_in_last_2,

        -- Calculate consecutive overs before this game
        SUM(CASE WHEN over_under = 'OVER' THEN 1 ELSE 0 END)
          OVER (
            PARTITION BY player_id
            ORDER BY game_date
            ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
          ) as overs_in_last_2,

        -- Row number to ensure we have history
        ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date) as game_num

      FROM player_games
    )

    SELECT
      -- Overall stats
      COUNT(*) as total_games,
      ROUND(AVG(CASE WHEN over_under = 'OVER' THEN 1.0 ELSE 0.0 END) * 100, 1) as baseline_over_rate,

      -- After 2 unders
      COUNTIF(unders_in_last_2 = 2 AND game_num >= 3) as games_after_2_unders,
      ROUND(AVG(CASE WHEN unders_in_last_2 = 2 AND game_num >= 3 AND over_under = 'OVER'
                     THEN 1.0 ELSE 0.0 END) * 100, 1) as over_rate_after_2_unders,

      -- After 2 overs (control group)
      COUNTIF(overs_in_last_2 = 2 AND game_num >= 3) as games_after_2_overs,
      ROUND(AVG(CASE WHEN overs_in_last_2 = 2 AND game_num >= 3 AND over_under = 'UNDER'
                     THEN 1.0 ELSE 0.0 END) * 100, 1) as under_rate_after_2_overs,

      -- Star players only (>= {min_ppg} PPG)
      COUNTIF(unders_in_last_2 = 2 AND game_num >= 3 AND points_avg_season >= {min_ppg}) as star_games_after_2_unders,
      ROUND(AVG(CASE WHEN unders_in_last_2 = 2 AND game_num >= 3
                          AND points_avg_season >= {min_ppg}
                          AND over_under = 'OVER'
                     THEN 1.0 ELSE 0.0 END) * 100, 1) as star_over_rate_after_2_unders

    FROM streak_analysis
    """

    df = client.query(query).to_dataframe()
    return df


def run_fg_pct_reversion_analysis(
    client: bigquery.Client,
    start_date: str,
    end_date: str,
    low_fg_threshold: float = 0.40
) -> pd.DataFrame:
    """
    Test if players with 2+ consecutive low FG% games bounce back.

    Returns correlation between "2 low FG% games" and "next game performance".
    """
    query = f"""
    WITH player_games AS (
      -- Get game stats with FG% and points vs line
      SELECT
        g.game_date,
        g.player_name,
        g.player_id,
        g.points,
        g.field_goal_percentage,
        g.three_point_percentage,
        g.field_goals_attempted,
        -- Get prop line data
        pa.vegas_line,
        pa.over_under,
        -- Calculate player's season average FG%
        AVG(g.field_goal_percentage) OVER (
          PARTITION BY g.player_id
          ORDER BY g.game_date
          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) as fg_pct_avg_season

      FROM nba_raw.nbac_gamebook_player_stats g
      LEFT JOIN nba_predictions.prediction_accuracy pa
        ON g.player_id = pa.player_id
        AND g.game_date = pa.game_date
      WHERE g.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND g.field_goal_percentage IS NOT NULL
        AND g.field_goals_attempted >= 5  -- Min shot attempts filter
    ),

    fg_streak_analysis AS (
      SELECT
        game_date,
        player_name,
        player_id,
        points,
        field_goal_percentage,
        three_point_percentage,
        vegas_line,
        over_under,
        fg_pct_avg_season,

        -- Count low FG% games in last 2
        SUM(CASE WHEN field_goal_percentage < {low_fg_threshold} THEN 1 ELSE 0 END)
          OVER (
            PARTITION BY player_id
            ORDER BY game_date
            ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
          ) as low_fg_games_in_last_2,

        -- Average FG% in last 2 games
        AVG(field_goal_percentage)
          OVER (
            PARTITION BY player_id
            ORDER BY game_date
            ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
          ) as avg_fg_pct_last_2,

        ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date) as game_num

      FROM player_games
    )

    SELECT
      -- Overall FG% stats
      COUNT(*) as total_games,
      ROUND(AVG(field_goal_percentage) * 100, 1) as avg_fg_pct,

      -- After 2 low FG% games
      COUNTIF(low_fg_games_in_last_2 = 2 AND game_num >= 3) as games_after_2_low_fg,
      ROUND(AVG(CASE WHEN low_fg_games_in_last_2 = 2 AND game_num >= 3
                     THEN field_goal_percentage END) * 100, 1) as avg_fg_pct_after_2_low,

      -- Bounce back rate (FG% > season avg)
      ROUND(AVG(CASE WHEN low_fg_games_in_last_2 = 2 AND game_num >= 3
                          AND field_goal_percentage > fg_pct_avg_season
                     THEN 1.0 ELSE 0.0 END) * 100, 1) as bounce_back_rate,

      -- Over rate after low FG% games
      COUNTIF(low_fg_games_in_last_2 = 2 AND game_num >= 3 AND vegas_line IS NOT NULL) as gradable_after_low_fg,
      ROUND(AVG(CASE WHEN low_fg_games_in_last_2 = 2 AND game_num >= 3
                          AND vegas_line IS NOT NULL
                          AND over_under = 'OVER'
                     THEN 1.0 ELSE 0.0 END) * 100, 1) as over_rate_after_low_fg

    FROM fg_streak_analysis
    """

    df = client.query(query).to_dataframe()
    return df


def run_points_scoring_streak_analysis(
    client: bigquery.Client,
    start_date: str,
    end_date: str
) -> pd.DataFrame:
    """
    Test if players with 2+ games below their average bounce back.

    Your friend's theory: Points alone doesn't tell the story, but let's check anyway.
    """
    query = f"""
    WITH player_games AS (
      SELECT
        g.game_date,
        g.player_name,
        g.player_id,
        g.points,
        -- Season average points (20-game rolling)
        AVG(g.points) OVER (
          PARTITION BY g.player_id
          ORDER BY g.game_date
          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) as points_avg_season,
        -- Prop line data
        pa.vegas_line,
        pa.over_under,
        pa.hit

      FROM nba_raw.nbac_gamebook_player_stats g
      LEFT JOIN nba_predictions.prediction_accuracy pa
        ON g.player_id = pa.player_id
        AND g.game_date = pa.game_date
      WHERE g.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND g.points IS NOT NULL
    ),

    scoring_streaks AS (
      SELECT
        game_date,
        player_name,
        player_id,
        points,
        points_avg_season,
        vegas_line,
        over_under,
        hit,

        -- Count games below average in last 2
        SUM(CASE WHEN points < points_avg_season THEN 1 ELSE 0 END)
          OVER (
            PARTITION BY player_id
            ORDER BY game_date
            ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
          ) as below_avg_in_last_2,

        ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date) as game_num

      FROM player_games
      WHERE points_avg_season IS NOT NULL
    )

    SELECT
      COUNT(*) as total_games,

      -- After 2 below-average games
      COUNTIF(below_avg_in_last_2 = 2 AND game_num >= 3 AND vegas_line IS NOT NULL) as games_after_2_below_avg,
      ROUND(AVG(CASE WHEN below_avg_in_last_2 = 2 AND game_num >= 3
                          AND vegas_line IS NOT NULL
                          AND over_under = 'OVER'
                     THEN 1.0 ELSE 0.0 END) * 100, 1) as over_rate_after_2_below_avg,

      -- Actually scored above average
      ROUND(AVG(CASE WHEN below_avg_in_last_2 = 2 AND game_num >= 3
                          AND points > points_avg_season
                     THEN 1.0 ELSE 0.0 END) * 100, 1) as scored_above_avg_rate

    FROM scoring_streaks
    """

    df = client.query(query).to_dataframe()
    return df


def run_star_player_filter_test(
    client: bigquery.Client,
    start_date: str,
    end_date: str
) -> pd.DataFrame:
    """
    Test if the mean reversion strategy works better for star players.

    Segments by PPG tiers: 25+, 20-25, 15-20, <15
    """
    query = f"""
    WITH player_games AS (
      SELECT
        pa.game_date,
        pa.player_name,
        pa.player_id,
        pa.over_under,
        pgs.points_avg_season,
        -- Consecutive unders
        SUM(CASE WHEN pa.over_under = 'UNDER' THEN 1 ELSE 0 END)
          OVER (
            PARTITION BY pa.player_id
            ORDER BY pa.game_date
            ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
          ) as unders_in_last_2,
        ROW_NUMBER() OVER (PARTITION BY pa.player_id ORDER BY pa.game_date) as game_num

      FROM nba_predictions.prediction_accuracy pa
      LEFT JOIN nba_predictions.ml_feature_store_v2 pgs
        ON pa.player_id = pgs.player_id
        AND pa.game_date = pgs.game_date
      WHERE pa.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND pa.actual_points IS NOT NULL
        AND pa.vegas_line IS NOT NULL
    )

    SELECT
      CASE
        WHEN points_avg_season >= 25 THEN 'Elite (25+ PPG)'
        WHEN points_avg_season >= 20 THEN 'Star (20-25 PPG)'
        WHEN points_avg_season >= 15 THEN 'Starter (15-20 PPG)'
        ELSE 'Bench (<15 PPG)'
      END as player_tier,

      COUNTIF(unders_in_last_2 = 2 AND game_num >= 3) as games_after_2_unders,
      ROUND(AVG(CASE WHEN unders_in_last_2 = 2 AND game_num >= 3 AND over_under = 'OVER'
                     THEN 1.0 ELSE 0.0 END) * 100, 1) as over_rate_after_2_unders,

      -- Compare to baseline (all games)
      COUNT(*) as total_games,
      ROUND(AVG(CASE WHEN over_under = 'OVER' THEN 1.0 ELSE 0.0 END) * 100, 1) as baseline_over_rate

    FROM player_games
    WHERE points_avg_season IS NOT NULL
    GROUP BY 1
    ORDER BY MIN(points_avg_season) DESC
    """

    df = client.query(query).to_dataframe()
    return df


def main():
    """Run all mean reversion tests."""

    # Configuration
    start_date = "2025-11-01"  # Season start
    end_date = "2026-02-12"    # Today

    client = bigquery.Client(project="nba-props-platform")

    print("=" * 80)
    print("MEAN REVERSION THEORY TESTING")
    print("=" * 80)
    print(f"Date Range: {start_date} to {end_date}")
    print()

    # Test 1: Prop Line Streaks
    print("TEST 1: Prop Line Streak Analysis")
    print("-" * 80)
    print("Theory: Players with 2+ consecutive UNDER games → bet OVER on next game")
    print()

    prop_results = run_prop_streak_analysis(client, start_date, end_date)
    print(prop_results.to_string(index=False))
    print()

    # Interpret results
    if not prop_results.empty:
        baseline = prop_results['baseline_over_rate'].iloc[0]
        after_2_unders = prop_results['over_rate_after_2_unders'].iloc[0]
        star_after_2_unders = prop_results['star_over_rate_after_2_unders'].iloc[0]

        if after_2_unders and baseline:
            lift = after_2_unders - baseline
            print(f"📊 RESULT: {'+' if lift > 0 else ''}{lift:.1f}% lift vs baseline")
            print(f"   Star players: {'+' if star_after_2_unders - baseline > 0 else ''}{star_after_2_unders - baseline:.1f}% lift")

            if lift > 5:
                print("   ✅ STRONG SIGNAL - Theory has merit!")
            elif lift > 2:
                print("   ⚠️  WEAK SIGNAL - Small edge detected")
            else:
                print("   ❌ NO SIGNAL - Random/negative")
    print()

    # Test 2: FG% Reversion
    print("\nTEST 2: Field Goal % Mean Reversion")
    print("-" * 80)
    print("Theory: Players with 2+ low FG% games → bounce back with higher FG%")
    print()

    fg_results = run_fg_pct_reversion_analysis(client, start_date, end_date)
    print(fg_results.to_string(index=False))
    print()

    if not fg_results.empty:
        avg_fg = fg_results['avg_fg_pct'].iloc[0]
        after_low_fg = fg_results['avg_fg_pct_after_2_low'].iloc[0]
        bounce_rate = fg_results['bounce_back_rate'].iloc[0]

        if after_low_fg and avg_fg:
            fg_lift = after_low_fg - avg_fg
            print(f"📊 FG% RESULT: {'+' if fg_lift > 0 else ''}{fg_lift:.1f}% FG% after 2 low games")
            print(f"   Bounce back rate (FG% > season avg): {bounce_rate:.1f}%")

            if fg_lift > 3:
                print("   ✅ STRONG BOUNCE BACK")
            elif fg_lift > 0:
                print("   ⚠️  WEAK BOUNCE BACK")
            else:
                print("   ❌ NO BOUNCE BACK - Negative correlation")
    print()

    # Test 3: Points Scoring Streaks
    print("\nTEST 3: Points Scoring Streaks")
    print("-" * 80)
    print("Theory: Players with 2+ games below average → bounce back")
    print()

    scoring_results = run_points_scoring_streak_analysis(client, start_date, end_date)
    print(scoring_results.to_string(index=False))
    print()

    # Test 4: Star Player Filter
    print("\nTEST 4: Star Player Tier Analysis")
    print("-" * 80)
    print("Theory: Mean reversion works better for star/consistent players")
    print()

    tier_results = run_star_player_filter_test(client, start_date, end_date)
    print(tier_results.to_string(index=False))
    print()

    # Summary
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    print()
    print("1. Check if FG% should be added to feature store")
    print("   - We have raw data but it's not in ML features")
    print("   - Could improve model if shooting efficiency matters")
    print()
    print("2. Consider adding to V12/V13 features:")
    print("   - fg_pct_last_3 / fg_pct_last_5")
    print("   - fg_pct_vs_season_avg (deviation)")
    print("   - three_pct_last_3 / three_pct_last_5")
    print()
    print("3. Already have prop streak features in V12:")
    print("   - prop_over_streak")
    print("   - prop_under_streak")
    print("   - consecutive_games_below_avg")
    print("   But these aren't in V9 production model!")
    print()


if __name__ == "__main__":
    main()
