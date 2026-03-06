#!/usr/bin/env python3
"""
Player Deep Dive Analysis

Comprehensive scoring pattern analysis for any NBA player.
Pulls data from BigQuery (game summary, feature store, prediction accuracy)
and generates a detailed markdown report.

Usage:
    python bin/analysis/player_deep_dive.py stephencurry
    python bin/analysis/player_deep_dive.py stephencurry --seasons 3
    python bin/analysis/player_deep_dive.py stephencurry --output results/curry_deep_dive.md
"""

import argparse
import sys
import os
from datetime import date, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"


def parse_args():
    parser = argparse.ArgumentParser(description="Player deep dive analysis")
    parser.add_argument("player_lookup", help="Player lookup key (e.g., stephencurry)")
    parser.add_argument("--seasons", type=int, default=3, help="Number of seasons back to analyze (default: 3)")
    parser.add_argument("--output", help="Output file path (default: results/player_deep_dive_{player}.md)")
    parser.add_argument("--min-date", help="Override start date (YYYY-MM-DD)")
    return parser.parse_args()


def fetch_data(client, player_lookup: str, start_date: str) -> dict:
    """Fetch all data from BigQuery in 3 queries."""

    # 1. Game summary — core stats + prop lines
    game_summary_sql = f"""
    SELECT
        game_date,
        game_id,
        points,
        minutes_played,
        assists,
        offensive_rebounds + defensive_rebounds as rebounds,
        steals,
        blocks,
        turnovers,
        fg_makes,
        fg_attempts,
        three_pt_makes,
        three_pt_attempts,
        ft_makes,
        ft_attempts,
        paint_makes,
        paint_attempts,
        mid_range_makes,
        mid_range_attempts,
        usage_rate,
        ts_pct,
        efg_pct,
        starter_flag,
        win_flag,
        plus_minus,
        points_line,
        over_under_result,
        margin,
        opening_line,
        line_movement,
        team_abbr,
        opponent_team_abbr,
        is_dnp,
        dnp_reason_category,
        season_year
    FROM nba_analytics.player_game_summary
    WHERE player_lookup = '{player_lookup}'
      AND game_date >= '{start_date}'
      AND (is_dnp IS NULL OR is_dnp = FALSE)
      AND points IS NOT NULL
      AND points > 0
    ORDER BY game_date
    """

    # 2. Feature store — contextual features
    features_sql = f"""
    SELECT
        game_date,
        days_rest,
        feature_5_value as fatigue_score,
        feature_7_value as pace_score,
        feature_13_value as opp_def_rating,
        feature_14_value as opp_pace,
        feature_15_value as home_away,
        feature_16_value as back_to_back,
        feature_22_value as team_pace,
        feature_37_value as star_teammates_out,
        feature_38_value as game_total_line,
        feature_41_value as spread_magnitude,
        feature_42_value as implied_team_total,
        feature_44_value as scoring_trend_slope,
        feature_55_value as over_rate_last_10,
        feature_56_value as margin_vs_line_avg_last_5
    FROM nba_predictions.ml_feature_store_v2
    WHERE player_lookup = '{player_lookup}'
      AND game_date >= '{start_date}'
    ORDER BY game_date
    """

    # 3. Prediction accuracy — model performance on this player
    predictions_sql = f"""
    SELECT
        game_date,
        actual_points,
        line_value,
        predicted_points,
        recommendation,
        prediction_correct,
        ABS(CAST(predicted_points AS FLOAT64) - CAST(line_value AS FLOAT64)) as edge,
        system_id,
        confidence_score,
        minutes_played
    FROM nba_predictions.prediction_accuracy
    WHERE player_lookup = '{player_lookup}'
      AND game_date >= '{start_date}'
      AND has_prop_line = TRUE
      AND recommendation IN ('OVER', 'UNDER')
      AND prediction_correct IS NOT NULL
    ORDER BY game_date
    """

    print("Fetching game summary data...")
    games_df = client.query(game_summary_sql).to_dataframe()
    print(f"  -> {len(games_df)} games")

    print("Fetching feature store data...")
    features_df = client.query(features_sql).to_dataframe()
    print(f"  -> {len(features_df)} feature records")

    print("Fetching prediction accuracy data...")
    preds_df = client.query(predictions_sql).to_dataframe()
    print(f"  -> {len(preds_df)} graded predictions")

    return {
        "games": games_df,
        "features": features_df,
        "predictions": preds_df,
    }


def merge_data(data: dict) -> pd.DataFrame:
    """Merge games with features on game_date."""
    games = data["games"].copy()
    features = data["features"].copy()

    games["game_date"] = pd.to_datetime(games["game_date"])
    features["game_date"] = pd.to_datetime(features["game_date"])

    merged = games.merge(features, on="game_date", how="left")

    # win_flag is broken (always FALSE) — use plus_minus as proxy
    if "plus_minus" in merged.columns:
        merged["win_flag"] = merged["plus_minus"].apply(
            lambda x: True if pd.notna(x) and float(x) > 0 else (False if pd.notna(x) else None)
        )

    return merged


def compute_season_label(game_date) -> str:
    """Convert game_date to NBA season label like '2024-25'."""
    if isinstance(game_date, str):
        game_date = pd.to_datetime(game_date)
    year = game_date.year
    month = game_date.month
    if month >= 10:
        return f"{year}-{str(year + 1)[2:]}"
    else:
        return f"{year - 1}-{str(year)[2:]}"


# ============================================================
# Analysis Modules
# ============================================================

def module_1_baseline(df: pd.DataFrame) -> str:
    """Module 1: Baseline Scoring Profile"""
    lines = ["## Module 1: Baseline Scoring Profile\n"]

    # Season-by-season summary
    df["season"] = df["game_date"].apply(compute_season_label)
    seasons = df.groupby("season").agg(
        games=("points", "count"),
        avg=("points", "mean"),
        median=("points", "median"),
        std=("points", "std"),
        floor=("points", "min"),
        ceiling=("points", "max"),
        avg_min=("minutes_played", "mean"),
    ).round(1)

    lines.append("### Season-by-Season Scoring\n")
    lines.append("| Season | Games | Avg | Median | Std Dev | Floor | Ceiling | Avg Min |")
    lines.append("|--------|-------|-----|--------|---------|-------|---------|---------|")
    for season, row in seasons.iterrows():
        lines.append(f"| {season} | {int(row['games'])} | {row['avg']} | {row['median']} | {row['std']} | {int(row['floor'])} | {int(row['ceiling'])} | {row['avg_min']:.1f} |")

    # Overall stats
    overall_avg = df["points"].mean()
    overall_std = df["points"].std()
    lines.append(f"\n**Overall Average:** {overall_avg:.1f} pts (std: {overall_std:.1f})")

    # Over/under season average by month
    df["month"] = df["game_date"].dt.month
    df["month_name"] = df["game_date"].dt.strftime("%b")
    df["over_avg"] = df["points"] > overall_avg

    monthly = df.groupby(["month", "month_name"]).agg(
        games=("points", "count"),
        avg_pts=("points", "mean"),
        over_avg_pct=("over_avg", "mean"),
    ).round(3)

    lines.append("\n### Monthly Scoring Patterns\n")
    lines.append("| Month | Games | Avg Pts | Over Season Avg % |")
    lines.append("|-------|-------|---------|-------------------|")
    for (month, month_name), row in monthly.iterrows():
        lines.append(f"| {month_name} | {int(row['games'])} | {row['avg_pts']:.1f} | {row['over_avg_pct']*100:.1f}% |")

    # Scoring distribution buckets
    bins = [0, 10, 15, 20, 25, 30, 35, 40, 100]
    labels = ["0-10", "11-15", "16-20", "21-25", "26-30", "31-35", "36-40", "41+"]
    df["pts_bucket"] = pd.cut(df["points"], bins=bins, labels=labels)
    dist = df["pts_bucket"].value_counts().sort_index()

    lines.append("\n### Scoring Distribution\n")
    lines.append("| Range | Games | % |")
    lines.append("|-------|-------|---|")
    for bucket, count in dist.items():
        lines.append(f"| {bucket} | {count} | {count/len(df)*100:.1f}% |")

    return "\n".join(lines)


def module_2_prop_line(df: pd.DataFrame) -> str:
    """Module 2: Prop Line Performance"""
    lines = ["## Module 2: Prop Line Performance\n"]

    prop_df = df[df["points_line"].notna() & (df["points_line"] > 0)].copy()
    if len(prop_df) == 0:
        lines.append("*No prop line data available.*")
        return "\n".join(lines)

    prop_df["over_line"] = prop_df["points"] > prop_df["points_line"]
    prop_df["under_line"] = prop_df["points"] < prop_df["points_line"]
    prop_df["push"] = prop_df["points"] == prop_df["points_line"]
    prop_df["margin"] = prop_df["points"] - prop_df["points_line"]

    over_rate = prop_df["over_line"].mean()
    under_rate = prop_df["under_line"].mean()
    push_rate = prop_df["push"].mean()
    avg_margin = prop_df["margin"].mean()

    lines.append(f"**Games with prop line:** {len(prop_df)}")
    lines.append(f"**Over rate:** {over_rate*100:.1f}% ({prop_df['over_line'].sum()}/{len(prop_df)})")
    lines.append(f"**Under rate:** {under_rate*100:.1f}% ({prop_df['under_line'].sum()}/{len(prop_df)})")
    lines.append(f"**Push rate:** {push_rate*100:.1f}%")
    lines.append(f"**Avg margin vs line:** {avg_margin:+.1f} pts\n")

    # By line range
    line_bins = [0, 20, 23, 26, 29, 100]
    line_labels = ["<20", "20-22.5", "23-25.5", "26-28.5", "29+"]
    prop_df["line_bucket"] = pd.cut(prop_df["points_line"], bins=line_bins, labels=line_labels)

    lines.append("### Over Rate by Line Range\n")
    lines.append("| Line Range | Games | Over % | Avg Margin | Avg Actual |")
    lines.append("|------------|-------|--------|------------|------------|")
    for bucket in line_labels:
        subset = prop_df[prop_df["line_bucket"] == bucket]
        if len(subset) > 0:
            lines.append(f"| {bucket} | {len(subset)} | {subset['over_line'].mean()*100:.1f}% | {subset['margin'].mean():+.1f} | {subset['points'].mean():.1f} |")

    # Streak analysis
    lines.append("\n### Streak Analysis\n")
    streaks = []
    current_streak = 0
    current_type = None
    for _, row in prop_df.sort_values("game_date").iterrows():
        if row["over_line"]:
            if current_type == "OVER":
                current_streak += 1
            else:
                if current_type:
                    streaks.append((current_type, current_streak))
                current_type = "OVER"
                current_streak = 1
        elif row["under_line"]:
            if current_type == "UNDER":
                current_streak += 1
            else:
                if current_type:
                    streaks.append((current_type, current_streak))
                current_type = "UNDER"
                current_streak = 1
        # pushes don't break streaks
    if current_type:
        streaks.append((current_type, current_streak))

    over_streaks = [s[1] for s in streaks if s[0] == "OVER"]
    under_streaks = [s[1] for s in streaks if s[0] == "UNDER"]

    if over_streaks:
        lines.append(f"- **Longest OVER streak:** {max(over_streaks)} games")
        lines.append(f"- **Avg OVER streak:** {np.mean(over_streaks):.1f} games")
    if under_streaks:
        lines.append(f"- **Longest UNDER streak:** {max(under_streaks)} games")
        lines.append(f"- **Avg UNDER streak:** {np.mean(under_streaks):.1f} games")

    # Line movement impact
    lm_df = prop_df[prop_df["line_movement"].notna()].copy()
    if len(lm_df) > 10:
        lm_df["line_dropped"] = lm_df["line_movement"] < 0
        lm_df["line_rose"] = lm_df["line_movement"] > 0
        lm_df["line_flat"] = lm_df["line_movement"] == 0

        lines.append("\n### Line Movement Impact\n")
        lines.append("| Movement | Games | Over % | Avg Margin |")
        lines.append("|----------|-------|--------|------------|")
        for label, mask in [("Line dropped", lm_df["line_dropped"]), ("Line rose", lm_df["line_rose"]), ("Line flat", lm_df["line_flat"])]:
            subset = lm_df[mask]
            if len(subset) >= 3:
                lines.append(f"| {label} | {len(subset)} | {subset['over_line'].mean()*100:.1f}% | {subset['margin'].mean():+.1f} |")

    # Margin distribution
    lines.append("\n### Margin Distribution (Actual - Line)\n")
    margin_bins = [(-100, -10), (-10, -5), (-5, -2), (-2, 0), (0, 2), (2, 5), (5, 10), (10, 100)]
    margin_labels = ["<-10", "-10 to -5", "-5 to -2", "-2 to 0", "0 to +2", "+2 to +5", "+5 to +10", ">+10"]
    lines.append("| Margin | Games | % |")
    lines.append("|--------|-------|---|")
    for (lo, hi), label in zip(margin_bins, margin_labels):
        count = ((prop_df["margin"] >= lo) & (prop_df["margin"] < hi)).sum()
        if hi == 100:
            count = (prop_df["margin"] >= lo).sum()
        if count > 0:
            lines.append(f"| {label} | {count} | {count/len(prop_df)*100:.1f}% |")

    return "\n".join(lines)


def module_3_rest_fatigue(df: pd.DataFrame) -> str:
    """Module 3: Rest & Fatigue"""
    lines = ["## Module 3: Rest & Fatigue\n"]

    rest_df = df[df["days_rest"].notna()].copy()
    if len(rest_df) == 0:
        lines.append("*No rest data available.*")
        return "\n".join(lines)

    rest_df["days_rest_int"] = rest_df["days_rest"].astype(int)
    rest_df["rest_bucket"] = rest_df["days_rest_int"].apply(
        lambda x: "0 (B2B)" if x == 0 else ("1" if x == 1 else ("2" if x == 2 else "3+"))
    )

    # Performance by days rest
    lines.append("### Scoring by Days Rest\n")
    lines.append("| Days Rest | Games | Avg Pts | Median | Std | Avg Min |")
    lines.append("|-----------|-------|---------|--------|-----|---------|")
    for bucket in ["0 (B2B)", "1", "2", "3+"]:
        subset = rest_df[rest_df["rest_bucket"] == bucket]
        if len(subset) > 0:
            lines.append(f"| {bucket} | {len(subset)} | {subset['points'].mean():.1f} | {subset['points'].median():.1f} | {subset['points'].std():.1f} | {subset['minutes_played'].mean():.1f} |")

    # Prop line performance by rest
    prop_rest = rest_df[rest_df["points_line"].notna() & (rest_df["points_line"] > 0)].copy()
    if len(prop_rest) > 0:
        prop_rest["over_line"] = prop_rest["points"] > prop_rest["points_line"]
        prop_rest["margin"] = prop_rest["points"] - prop_rest["points_line"]

        lines.append("\n### Prop Line Performance by Days Rest\n")
        lines.append("| Days Rest | Games | Over % | Avg Margin |")
        lines.append("|-----------|-------|--------|------------|")
        for bucket in ["0 (B2B)", "1", "2", "3+"]:
            subset = prop_rest[prop_rest["rest_bucket"] == bucket]
            if len(subset) >= 3:
                lines.append(f"| {bucket} | {len(subset)} | {subset['over_line'].mean()*100:.1f}% | {subset['margin'].mean():+.1f} |")

    # Back-to-back analysis
    b2b_df = rest_df[rest_df["back_to_back"].notna()].copy()
    if len(b2b_df) > 0:
        b2b_games = b2b_df[b2b_df["back_to_back"] == 1.0]
        non_b2b = b2b_df[b2b_df["back_to_back"] == 0.0]
        lines.append(f"\n### Back-to-Back Impact")
        lines.append(f"- **B2B games:** {len(b2b_games)} — Avg {b2b_games['points'].mean():.1f} pts, {b2b_games['minutes_played'].mean():.1f} min")
        lines.append(f"- **Non-B2B:** {len(non_b2b)} — Avg {non_b2b['points'].mean():.1f} pts, {non_b2b['minutes_played'].mean():.1f} min")
        if len(b2b_games) > 0:
            delta = b2b_games["points"].mean() - non_b2b["points"].mean()
            lines.append(f"- **B2B scoring delta:** {delta:+.1f} pts")

    # Fatigue score correlation
    fatigue_df = rest_df[rest_df["fatigue_score"].notna()].copy()
    if len(fatigue_df) > 10:
        corr = fatigue_df["fatigue_score"].corr(fatigue_df["points"])
        lines.append(f"\n### Fatigue Score Correlation")
        lines.append(f"- **Fatigue score ↔ points correlation:** {corr:.3f}")

        # Bucket fatigue
        fatigue_df["fatigue_bucket"] = pd.cut(
            fatigue_df["fatigue_score"],
            bins=[0, 50, 75, 90, 100],
            labels=["Low (<50)", "Medium (50-75)", "High (75-90)", "Full (90-100)"]
        )
        lines.append("\n| Fatigue Level | Games | Avg Pts | Avg Min |")
        lines.append("|---------------|-------|---------|---------|")
        for bucket in ["Low (<50)", "Medium (50-75)", "High (75-90)", "Full (90-100)"]:
            subset = fatigue_df[fatigue_df["fatigue_bucket"] == bucket]
            if len(subset) > 0:
                lines.append(f"| {bucket} | {len(subset)} | {subset['points'].mean():.1f} | {subset['minutes_played'].mean():.1f} |")

    return "\n".join(lines)


def module_4_home_away(df: pd.DataFrame) -> str:
    """Module 4: Home vs Away"""
    lines = ["## Module 4: Home vs Away\n"]

    ha_df = df[df["home_away"].notna()].copy()
    if len(ha_df) == 0:
        # Fall back to team_abbr-based detection if feature store data missing
        lines.append("*No home/away feature data available.*")
        return "\n".join(lines)

    ha_df["is_home"] = ha_df["home_away"] == 1.0

    home = ha_df[ha_df["is_home"]]
    away = ha_df[~ha_df["is_home"]]

    lines.append("### Scoring Splits\n")
    lines.append("| Location | Games | Avg Pts | Median | Std | Avg Min | FG% |")
    lines.append("|----------|-------|---------|--------|-----|---------|-----|")
    for label, subset in [("Home", home), ("Away", away)]:
        fg_pct = (subset["fg_makes"].sum() / subset["fg_attempts"].sum() * 100) if subset["fg_attempts"].sum() > 0 else 0
        lines.append(f"| {label} | {len(subset)} | {subset['points'].mean():.1f} | {subset['points'].median():.1f} | {subset['points'].std():.1f} | {subset['minutes_played'].mean():.1f} | {fg_pct:.1f}% |")

    # Prop line performance home vs away
    prop_ha = ha_df[ha_df["points_line"].notna() & (ha_df["points_line"] > 0)].copy()
    if len(prop_ha) > 0:
        prop_ha["over_line"] = prop_ha["points"] > prop_ha["points_line"]
        prop_ha["margin"] = prop_ha["points"] - prop_ha["points_line"]

        lines.append("\n### Prop Line Performance\n")
        lines.append("| Location | Games | Over % | Avg Margin |")
        lines.append("|----------|-------|--------|------------|")
        for label, is_home in [("Home", True), ("Away", False)]:
            subset = prop_ha[prop_ha["is_home"] == is_home]
            if len(subset) >= 3:
                lines.append(f"| {label} | {len(subset)} | {subset['over_line'].mean()*100:.1f}% | {subset['margin'].mean():+.1f} |")

    # Home/away combined with rest
    rest_ha = ha_df[ha_df["days_rest"].notna()].copy()
    if len(rest_ha) > 20:
        rest_ha["rest_3plus"] = rest_ha["days_rest"].astype(int) >= 3
        lines.append("\n### Home + Rest Combinations\n")
        lines.append("| Combo | Games | Avg Pts |")
        lines.append("|-------|-------|---------|")
        for loc_label, is_home in [("Home", True), ("Away", False)]:
            for rest_label, rest_val in [("1d rest", False), ("3+ rest", True)]:
                subset = rest_ha[(rest_ha["is_home"] == is_home) & (rest_ha["rest_3plus"] == rest_val)]
                if len(subset) >= 3:
                    lines.append(f"| {loc_label} + {rest_label} | {len(subset)} | {subset['points'].mean():.1f} |")

    return "\n".join(lines)


def module_5_matchup(df: pd.DataFrame) -> str:
    """Module 5: Matchup Analysis"""
    lines = ["## Module 5: Matchup Analysis\n"]

    # Performance vs each opponent
    opp = df.groupby("opponent_team_abbr").agg(
        games=("points", "count"),
        avg_pts=("points", "mean"),
        median_pts=("points", "median"),
        max_pts=("points", "max"),
        avg_min=("minutes_played", "mean"),
    ).round(1)
    opp = opp.sort_values("avg_pts", ascending=False)

    lines.append("### Performance by Opponent (sorted by avg pts)\n")
    lines.append("| Opponent | Games | Avg Pts | Median | Best | Avg Min |")
    lines.append("|----------|-------|---------|--------|------|---------|")
    for team, row in opp.iterrows():
        if row["games"] >= 2:
            lines.append(f"| {team} | {int(row['games'])} | {row['avg_pts']} | {row['median_pts']} | {int(row['max_pts'])} | {row['avg_min']:.1f} |")

    # Opponent defensive rating correlation
    def_df = df[df["opp_def_rating"].notna()].copy()
    if len(def_df) > 20:
        corr = def_df["opp_def_rating"].corr(def_df["points"])
        lines.append(f"\n### Defensive Rating Impact")
        lines.append(f"- **Opp def rating ↔ points correlation:** {corr:.3f}")

        def_df["def_bucket"] = pd.cut(
            def_df["opp_def_rating"],
            bins=[90, 105, 110, 115, 130],
            labels=["Elite (<105)", "Good (105-110)", "Average (110-115)", "Poor (>115)"]
        )
        lines.append("\n| Opp Defense | Games | Avg Pts | Avg Min |")
        lines.append("|-------------|-------|---------|---------|")
        for bucket in ["Elite (<105)", "Good (105-110)", "Average (110-115)", "Poor (>115)"]:
            subset = def_df[def_df["def_bucket"] == bucket]
            if len(subset) > 0:
                lines.append(f"| {bucket} | {len(subset)} | {subset['points'].mean():.1f} | {subset['minutes_played'].mean():.1f} |")

    # Opponent pace correlation
    pace_df = df[df["opp_pace"].notna()].copy()
    if len(pace_df) > 20:
        corr = pace_df["opp_pace"].corr(pace_df["points"])
        lines.append(f"\n### Pace Impact")
        lines.append(f"- **Opp pace ↔ points correlation:** {corr:.3f}")

        pace_df["pace_bucket"] = pd.cut(
            pace_df["opp_pace"],
            bins=[90, 97, 100, 103, 115],
            labels=["Slow (<97)", "Below Avg (97-100)", "Above Avg (100-103)", "Fast (>103)"]
        )
        lines.append("\n| Opp Pace | Games | Avg Pts | Avg Min |")
        lines.append("|----------|-------|---------|---------|")
        for bucket in ["Slow (<97)", "Below Avg (97-100)", "Above Avg (100-103)", "Fast (>103)"]:
            subset = pace_df[pace_df["pace_bucket"] == bucket]
            if len(subset) > 0:
                lines.append(f"| {bucket} | {len(subset)} | {subset['points'].mean():.1f} | {subset['minutes_played'].mean():.1f} |")

    return "\n".join(lines)


def module_6_shooting(df: pd.DataFrame) -> str:
    """Module 6: Shooting Patterns"""
    lines = ["## Module 6: Shooting Patterns\n"]

    overall_avg = df["points"].mean()
    df["above_avg"] = df["points"] > overall_avg

    # Over vs under games shooting comparison
    over_games = df[df["above_avg"]]
    under_games = df[~df["above_avg"]]

    def shooting_stats(subset):
        fg_pct = subset["fg_makes"].sum() / subset["fg_attempts"].sum() * 100 if subset["fg_attempts"].sum() > 0 else 0
        three_pct = subset["three_pt_makes"].sum() / subset["three_pt_attempts"].sum() * 100 if subset["three_pt_attempts"].sum() > 0 else 0
        ft_pct = subset["ft_makes"].sum() / subset["ft_attempts"].sum() * 100 if subset["ft_attempts"].sum() > 0 else 0
        return {
            "fg_pct": fg_pct,
            "three_pct": three_pct,
            "ft_pct": ft_pct,
            "avg_fga": subset["fg_attempts"].mean(),
            "avg_3pa": subset["three_pt_attempts"].mean(),
            "avg_fta": subset["ft_attempts"].mean(),
            "avg_3pm": subset["three_pt_makes"].mean(),
        }

    over_stats = shooting_stats(over_games)
    under_stats = shooting_stats(under_games)

    lines.append("### Shooting in Above-Average vs Below-Average Games\n")
    lines.append("| Metric | Above Avg | Below Avg | Delta |")
    lines.append("|--------|-----------|-----------|-------|")
    for label, key in [("FG%", "fg_pct"), ("3PT%", "three_pct"), ("FT%", "ft_pct"),
                       ("FGA/game", "avg_fga"), ("3PA/game", "avg_3pa"), ("FTA/game", "avg_fta"), ("3PM/game", "avg_3pm")]:
        delta = over_stats[key] - under_stats[key]
        fmt = ".1f" if "pct" in key else ".1f"
        lines.append(f"| {label} | {over_stats[key]:{fmt}} | {under_stats[key]:{fmt}} | {delta:+{fmt}} |")

    # Shot zone distribution
    shot_df = df[(df["paint_attempts"].notna()) & (df["fg_attempts"] > 0)].copy()
    if len(shot_df) > 20:
        shot_df["pct_paint"] = shot_df["paint_attempts"] / shot_df["fg_attempts"]
        shot_df["pct_mid"] = shot_df["mid_range_attempts"] / shot_df["fg_attempts"]
        shot_df["pct_3pt"] = shot_df["three_pt_attempts"] / shot_df["fg_attempts"]

        lines.append("\n### Shot Zone Distribution (% of FGA)\n")

        over_shot = shot_df[shot_df["above_avg"]]
        under_shot = shot_df[~shot_df["above_avg"]]

        lines.append("| Zone | Above Avg | Below Avg |")
        lines.append("|------|-----------|-----------|")
        for label, col in [("Paint", "pct_paint"), ("Mid-Range", "pct_mid"), ("3-Point", "pct_3pt")]:
            lines.append(f"| {label} | {over_shot[col].mean()*100:.1f}% | {under_shot[col].mean()*100:.1f}% |")

    # Win/loss shooting
    win_df = df[df["win_flag"].notna()].copy()
    if len(win_df) > 20:
        wins = win_df[win_df["win_flag"] == True]
        losses = win_df[win_df["win_flag"] == False]
        win_stats = shooting_stats(wins)
        loss_stats = shooting_stats(losses)

        lines.append("\n### Shooting in Wins vs Losses\n")
        lines.append(f"- **Wins:** {len(wins)} games, avg {wins['points'].mean():.1f} pts, FG% {win_stats['fg_pct']:.1f}%, 3PT% {win_stats['three_pct']:.1f}%")
        lines.append(f"- **Losses:** {len(losses)} games, avg {losses['points'].mean():.1f} pts, FG% {loss_stats['fg_pct']:.1f}%, 3PT% {loss_stats['three_pct']:.1f}%")

    # Three-point volume analysis
    lines.append("\n### Three-Point Volume Impact\n")
    df["three_volume"] = pd.cut(
        df["three_pt_attempts"],
        bins=[0, 5, 8, 11, 100],
        labels=["1-5", "6-8", "9-11", "12+"]
    )
    lines.append("| 3PA Range | Games | Avg Pts | Avg 3PM | 3PT% |")
    lines.append("|-----------|-------|---------|---------|------|")
    for bucket in ["1-5", "6-8", "9-11", "12+"]:
        subset = df[df["three_volume"] == bucket]
        if len(subset) > 0:
            three_pct = subset["three_pt_makes"].sum() / subset["three_pt_attempts"].sum() * 100 if subset["three_pt_attempts"].sum() > 0 else 0
            lines.append(f"| {bucket} | {len(subset)} | {subset['points'].mean():.1f} | {subset['three_pt_makes'].mean():.1f} | {three_pct:.1f}% |")

    return "\n".join(lines)


def module_7_game_context(df: pd.DataFrame) -> str:
    """Module 7: Game Context"""
    lines = ["## Module 7: Game Context\n"]

    # Win/loss impact
    wl_df = df[df["win_flag"].notna()].copy()
    if len(wl_df) > 0:
        wins = wl_df[wl_df["win_flag"] == True]
        losses = wl_df[wl_df["win_flag"] == False]
        lines.append("### Win/Loss Impact\n")
        lines.append(f"- **Wins:** {len(wins)} games, avg {wins['points'].mean():.1f} pts, avg {wins['minutes_played'].mean():.1f} min")
        lines.append(f"- **Losses:** {len(losses)} games, avg {losses['points'].mean():.1f} pts, avg {losses['minutes_played'].mean():.1f} min")

        # Prop line in wins vs losses
        prop_wl = wl_df[wl_df["points_line"].notna() & (wl_df["points_line"] > 0)].copy()
        if len(prop_wl) > 10:
            prop_wl["over_line"] = prop_wl["points"] > prop_wl["points_line"]
            win_over = prop_wl[prop_wl["win_flag"] == True]["over_line"].mean()
            loss_over = prop_wl[prop_wl["win_flag"] == False]["over_line"].mean()
            lines.append(f"- **Over line in wins:** {win_over*100:.1f}%")
            lines.append(f"- **Over line in losses:** {loss_over*100:.1f}%")

    # Minutes distribution
    lines.append("\n### Minutes Distribution\n")
    min_bins = [0, 20, 25, 30, 35, 40, 50]
    min_labels = ["<20", "20-24", "25-29", "30-34", "35-39", "40+"]
    df["min_bucket"] = pd.cut(df["minutes_played"], bins=min_bins, labels=min_labels)
    lines.append("| Minutes | Games | Avg Pts | % |")
    lines.append("|---------|-------|---------|---|")
    for bucket in min_labels:
        subset = df[df["min_bucket"] == bucket]
        if len(subset) > 0:
            lines.append(f"| {bucket} | {len(subset)} | {subset['points'].mean():.1f} | {len(subset)/len(df)*100:.1f}% |")

    # Usage rate impact
    usage_df = df[df["usage_rate"].notna() & (df["usage_rate"] > 0)].copy()
    if len(usage_df) > 20:
        corr = usage_df["usage_rate"].corr(usage_df["points"])
        lines.append(f"\n### Usage Rate")
        lines.append(f"- **Usage rate ↔ points correlation:** {corr:.3f}")
        lines.append(f"- **Avg usage rate:** {usage_df['usage_rate'].mean():.1f}%")

        usage_df["usage_bucket"] = pd.cut(
            usage_df["usage_rate"],
            bins=[0, 25, 30, 35, 100],
            labels=["Low (<25%)", "Medium (25-30%)", "High (30-35%)", "Very High (>35%)"]
        )
        lines.append("\n| Usage Rate | Games | Avg Pts |")
        lines.append("|------------|-------|---------|")
        for bucket in ["Low (<25%)", "Medium (25-30%)", "High (30-35%)", "Very High (>35%)"]:
            subset = usage_df[usage_df["usage_bucket"] == bucket]
            if len(subset) > 0:
                lines.append(f"| {bucket} | {len(subset)} | {subset['points'].mean():.1f} |")

    # Spread/blowout context
    spread_df = df[df["spread_magnitude"].notna()].copy()
    if len(spread_df) > 20:
        spread_df["spread_bucket"] = pd.cut(
            spread_df["spread_magnitude"],
            bins=[0, 3, 6, 10, 100],
            labels=["Close (<3)", "Moderate (3-6)", "Clear (6-10)", "Blowout (>10)"]
        )
        lines.append("\n### Game Spread Impact\n")
        lines.append("| Spread | Games | Avg Pts | Avg Min |")
        lines.append("|--------|-------|---------|---------|")
        for bucket in ["Close (<3)", "Moderate (3-6)", "Clear (6-10)", "Blowout (>10)"]:
            subset = spread_df[spread_df["spread_bucket"] == bucket]
            if len(subset) > 0:
                lines.append(f"| {bucket} | {len(subset)} | {subset['points'].mean():.1f} | {subset['minutes_played'].mean():.1f} |")

    # Game total line impact
    total_df = df[df["game_total_line"].notna()].copy()
    if len(total_df) > 20:
        corr = total_df["game_total_line"].corr(total_df["points"])
        lines.append(f"\n### Game Total Line Impact")
        lines.append(f"- **Game total ↔ points correlation:** {corr:.3f}")

    # Star teammates out
    star_df = df[df["star_teammates_out"].notna()].copy()
    if len(star_df) > 10:
        star_df["stars_out_int"] = star_df["star_teammates_out"].astype(int)
        lines.append("\n### Star Teammates Out\n")
        lines.append("| Stars Out | Games | Avg Pts | Avg Min |")
        lines.append("|-----------|-------|---------|---------|")
        for n in sorted(star_df["stars_out_int"].unique()):
            subset = star_df[star_df["stars_out_int"] == n]
            if len(subset) >= 2:
                lines.append(f"| {n} | {len(subset)} | {subset['points'].mean():.1f} | {subset['minutes_played'].mean():.1f} |")

    return "\n".join(lines)


def module_8_temporal(df: pd.DataFrame) -> str:
    """Module 8: Temporal Patterns"""
    lines = ["## Module 8: Temporal Patterns\n"]

    df["dow"] = df["game_date"].dt.dayofweek
    df["dow_name"] = df["game_date"].dt.strftime("%A")

    # Day of week
    lines.append("### Day of Week\n")
    lines.append("| Day | Games | Avg Pts | Median |")
    lines.append("|-----|-------|---------|--------|")
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day in dow_order:
        subset = df[df["dow_name"] == day]
        if len(subset) > 0:
            lines.append(f"| {day} | {len(subset)} | {subset['points'].mean():.1f} | {subset['points'].median():.1f} |")

    # Day of week prop line performance
    prop_dow = df[df["points_line"].notna() & (df["points_line"] > 0)].copy()
    if len(prop_dow) > 20:
        prop_dow["over_line"] = prop_dow["points"] > prop_dow["points_line"]
        lines.append("\n### Day of Week — Over Prop Line %\n")
        lines.append("| Day | Games | Over % |")
        lines.append("|-----|-------|--------|")
        for day in dow_order:
            subset = prop_dow[prop_dow["dow_name"] == day]
            if len(subset) >= 3:
                lines.append(f"| {day} | {len(subset)} | {subset['over_line'].mean()*100:.1f}% |")

    # Monthly trends
    df["year_month"] = df["game_date"].dt.to_period("M")
    monthly = df.groupby("year_month").agg(
        games=("points", "count"),
        avg_pts=("points", "mean"),
    ).round(1)

    lines.append("\n### Month-by-Month Trend\n")
    lines.append("| Month | Games | Avg Pts |")
    lines.append("|-------|-------|---------|")
    for period, row in monthly.iterrows():
        lines.append(f"| {period} | {int(row['games'])} | {row['avg_pts']} |")

    # Early vs late season
    df["month_num"] = df["game_date"].dt.month
    early = df[df["month_num"].isin([10, 11, 12])]
    mid = df[df["month_num"].isin([1, 2])]
    late = df[df["month_num"].isin([3, 4])]

    lines.append("\n### Season Phase\n")
    lines.append("| Phase | Games | Avg Pts | Avg Min |")
    lines.append("|-------|-------|---------|---------|")
    for label, subset in [("Early (Oct-Dec)", early), ("Mid (Jan-Feb)", mid), ("Late (Mar-Apr)", late)]:
        if len(subset) > 0:
            lines.append(f"| {label} | {len(subset)} | {subset['points'].mean():.1f} | {subset['minutes_played'].mean():.1f} |")

    # After rest combinations by season phase
    rest_time = df[df["days_rest"].notna()].copy()
    if len(rest_time) > 30:
        rest_time["rest_3plus"] = rest_time["days_rest"].astype(int) >= 3
        rest_time["phase"] = rest_time["month_num"].apply(
            lambda m: "Early" if m >= 10 else ("Mid" if m <= 2 else "Late")
        )
        lines.append("\n### Rest + Season Phase Combinations\n")
        lines.append("| Phase | Rest | Games | Avg Pts |")
        lines.append("|-------|------|-------|---------|")
        for phase in ["Early", "Mid", "Late"]:
            for rest_label, rest_val in [("1d", False), ("3+d", True)]:
                subset = rest_time[(rest_time["phase"] == phase) & (rest_time["rest_3plus"] == rest_val)]
                if len(subset) >= 3:
                    lines.append(f"| {phase} | {rest_label} | {len(subset)} | {subset['points'].mean():.1f} |")

    # Consecutive game scoring trend
    lines.append("\n### Performance After Big/Bad Games\n")
    df_sorted = df.sort_values("game_date").copy()
    df_sorted["prev_pts"] = df_sorted["points"].shift(1)
    overall_avg = df["points"].mean()

    big_follow = df_sorted[df_sorted["prev_pts"] > overall_avg + 10]
    bad_follow = df_sorted[df_sorted["prev_pts"] < overall_avg - 10]

    if len(big_follow) >= 3:
        lines.append(f"- **After big games (>{overall_avg+10:.0f} pts):** {len(big_follow)} games, avg {big_follow['points'].mean():.1f} pts (regression to mean: {big_follow['points'].mean() - overall_avg:+.1f})")
    if len(bad_follow) >= 3:
        lines.append(f"- **After bad games (<{overall_avg-10:.0f} pts):** {len(bad_follow)} games, avg {bad_follow['points'].mean():.1f} pts (bounce back: {bad_follow['points'].mean() - overall_avg:+.1f})")

    return "\n".join(lines)


def module_9_model_performance(preds_df: pd.DataFrame) -> str:
    """Module 9: Our Model's Performance on This Player"""
    lines = ["## Module 9: Model Prediction Performance\n"]

    if len(preds_df) == 0:
        lines.append("*No graded prediction data available.*")
        return "\n".join(lines)

    preds_df = preds_df.copy()
    preds_df["game_date"] = pd.to_datetime(preds_df["game_date"])
    preds_df["edge"] = pd.to_numeric(preds_df["edge"], errors="coerce")

    # Overall accuracy by system
    system_perf = preds_df.groupby("system_id").agg(
        predictions=("prediction_correct", "count"),
        correct=("prediction_correct", "sum"),
        avg_edge=("edge", "mean"),
    )
    system_perf["hit_rate"] = (system_perf["correct"] / system_perf["predictions"] * 100).round(1)
    system_perf = system_perf.sort_values("predictions", ascending=False)

    lines.append("### Accuracy by Model\n")
    lines.append("| Model | Predictions | Hit Rate | Avg Edge |")
    lines.append("|-------|-------------|----------|----------|")
    for system, row in system_perf.head(10).iterrows():
        lines.append(f"| {system} | {int(row['predictions'])} | {row['hit_rate']}% | {row['avg_edge']:.1f} |")

    # Overall accuracy by direction
    lines.append("\n### Accuracy by Direction\n")
    lines.append("| Direction | Predictions | Hit Rate |")
    lines.append("|-----------|-------------|----------|")
    for direction in ["OVER", "UNDER"]:
        subset = preds_df[preds_df["recommendation"] == direction]
        if len(subset) > 0:
            hr = subset["prediction_correct"].mean() * 100
            lines.append(f"| {direction} | {len(subset)} | {hr:.1f}% |")

    # Accuracy by edge band
    preds_df["edge_band"] = pd.cut(
        preds_df["edge"],
        bins=[0, 2, 3, 5, 8, 100],
        labels=["0-2", "2-3", "3-5", "5-8", "8+"]
    )
    lines.append("\n### Accuracy by Edge Band\n")
    lines.append("| Edge | Predictions | Hit Rate |")
    lines.append("|------|-------------|----------|")
    for band in ["0-2", "2-3", "3-5", "5-8", "8+"]:
        subset = preds_df[preds_df["edge_band"] == band]
        if len(subset) > 0:
            hr = subset["prediction_correct"].mean() * 100
            lines.append(f"| {band} | {len(subset)} | {hr:.1f}% |")

    # Monthly accuracy trend
    preds_df["year_month"] = preds_df["game_date"].dt.to_period("M")
    monthly = preds_df.groupby("year_month").agg(
        preds=("prediction_correct", "count"),
        correct=("prediction_correct", "sum"),
    )
    monthly["hr"] = (monthly["correct"] / monthly["preds"] * 100).round(1)

    lines.append("\n### Monthly Accuracy Trend\n")
    lines.append("| Month | Predictions | Hit Rate |")
    lines.append("|-------|-------------|----------|")
    for period, row in monthly.iterrows():
        lines.append(f"| {period} | {int(row['preds'])} | {row['hr']}% |")

    return "\n".join(lines)


def generate_report(player_lookup: str, data: dict, df: pd.DataFrame) -> str:
    """Generate the full markdown report."""
    lines = []
    import re
    # Split camelCase or run-together names (e.g., "stephencurry" -> "Stephen Curry")
    parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)', player_lookup)
    player_display = " ".join(p.capitalize() for p in parts) if parts else player_lookup

    lines.append(f"# {player_display} -- Deep Dive Analysis")
    lines.append(f"\n*Generated: {date.today().isoformat()}*")
    lines.append(f"*Data range: {df['game_date'].min().strftime('%Y-%m-%d')} to {df['game_date'].max().strftime('%Y-%m-%d')}*")
    lines.append(f"*Total games: {len(df)}*\n")

    lines.append("---\n")
    lines.append(module_1_baseline(df.copy()))
    lines.append("\n---\n")
    lines.append(module_2_prop_line(df.copy()))
    lines.append("\n---\n")
    lines.append(module_3_rest_fatigue(df.copy()))
    lines.append("\n---\n")
    lines.append(module_4_home_away(df.copy()))
    lines.append("\n---\n")
    lines.append(module_5_matchup(df.copy()))
    lines.append("\n---\n")
    lines.append(module_6_shooting(df.copy()))
    lines.append("\n---\n")
    lines.append(module_7_game_context(df.copy()))
    lines.append("\n---\n")
    lines.append(module_8_temporal(df.copy()))
    lines.append("\n---\n")
    lines.append(module_9_model_performance(data["predictions"].copy()))

    # Key findings summary
    lines.append("\n---\n")
    lines.append("## Key Findings Summary\n")
    lines.append(_compute_key_findings(df.copy(), data))

    return "\n".join(lines)


def _compute_key_findings(df: pd.DataFrame, data: dict) -> str:
    """Compute actionable findings from the data."""
    findings = []
    overall_avg = df["points"].mean()

    # Rest findings
    rest_df = df[df["days_rest"].notna()].copy()
    if len(rest_df) > 10:
        rest_df["days_rest_int"] = rest_df["days_rest"].astype(int)
        for rest_val in [0, 1, 2, 3]:
            if rest_val == 3:
                subset = rest_df[rest_df["days_rest_int"] >= 3]
                label = "3+ days rest"
            else:
                subset = rest_df[rest_df["days_rest_int"] == rest_val]
                label = f"{rest_val} days rest"
            if len(subset) >= 5:
                delta = subset["points"].mean() - overall_avg
                if abs(delta) > 2:
                    findings.append(f"- **{label}:** {delta:+.1f} pts vs average ({subset['points'].mean():.1f} avg, N={len(subset)})")

    # Home/away findings
    ha_df = df[df["home_away"].notna()].copy()
    if len(ha_df) > 10:
        home_avg = ha_df[ha_df["home_away"] == 1.0]["points"].mean()
        away_avg = ha_df[ha_df["home_away"] == 0.0]["points"].mean()
        delta = home_avg - away_avg
        if abs(delta) > 1.5:
            findings.append(f"- **Home/Away split:** Home {home_avg:.1f} vs Away {away_avg:.1f} ({delta:+.1f} pts)")

    # Prop line findings
    prop_df = df[df["points_line"].notna() & (df["points_line"] > 0)].copy()
    if len(prop_df) > 10:
        prop_df["over_line"] = prop_df["points"] > prop_df["points_line"]
        overall_over = prop_df["over_line"].mean()
        findings.append(f"- **Overall over rate:** {overall_over*100:.1f}% ({prop_df['over_line'].sum()}/{len(prop_df)})")

        # Best/worst line ranges for over
        prop_df["line_bucket"] = pd.cut(prop_df["points_line"], bins=[0, 20, 23, 26, 29, 100], labels=["<20", "20-23", "23-26", "26-29", "29+"])
        for bucket in prop_df["line_bucket"].unique():
            subset = prop_df[prop_df["line_bucket"] == bucket]
            if len(subset) >= 5:
                over_rate = subset["over_line"].mean()
                if over_rate > 0.6:
                    findings.append(f"- **Strong OVER at line {bucket}:** {over_rate*100:.1f}% (N={len(subset)})")
                elif over_rate < 0.4:
                    findings.append(f"- **Strong UNDER at line {bucket}:** {(1-over_rate)*100:.1f}% (N={len(subset)})")

    # Win/loss findings
    wl_df = df[df["win_flag"].notna()].copy()
    if len(wl_df) > 10:
        win_avg = wl_df[wl_df["win_flag"] == True]["points"].mean()
        loss_avg = wl_df[wl_df["win_flag"] == False]["points"].mean()
        findings.append(f"- **Win/Loss scoring:** Wins {win_avg:.1f} vs Losses {loss_avg:.1f} ({win_avg - loss_avg:+.1f})")

    # Three-point volume
    high_3pa = df[df["three_pt_attempts"] >= 10]
    low_3pa = df[df["three_pt_attempts"] < 7]
    if len(high_3pa) >= 5 and len(low_3pa) >= 5:
        delta = high_3pa["points"].mean() - low_3pa["points"].mean()
        if abs(delta) > 3:
            findings.append(f"- **3PA volume:** 10+ 3PA → {high_3pa['points'].mean():.1f} avg vs <7 3PA → {low_3pa['points'].mean():.1f} avg ({delta:+.1f})")

    # Opponent defense
    def_df = df[df["opp_def_rating"].notna()].copy()
    if len(def_df) > 20:
        weak_def = def_df[def_df["opp_def_rating"] > 115]
        strong_def = def_df[def_df["opp_def_rating"] < 105]
        if len(weak_def) >= 5 and len(strong_def) >= 5:
            delta = weak_def["points"].mean() - strong_def["points"].mean()
            findings.append(f"- **Vs defense:** Weak (>115 DRtg) {weak_def['points'].mean():.1f} vs Strong (<105 DRtg) {strong_def['points'].mean():.1f} ({delta:+.1f})")

    # Combined factors — home + rest + weak defense
    combo_df = df[(df["home_away"].notna()) & (df["days_rest"].notna()) & (df["opp_def_rating"].notna())].copy()
    if len(combo_df) > 20:
        ideal = combo_df[
            (combo_df["home_away"] == 1.0) &
            (combo_df["days_rest"].astype(int) >= 2) &
            (combo_df["opp_def_rating"] > 112)
        ]
        tough = combo_df[
            (combo_df["home_away"] == 0.0) &
            (combo_df["days_rest"].astype(int) <= 1) &
            (combo_df["opp_def_rating"] < 108)
        ]
        if len(ideal) >= 3:
            findings.append(f"- **Ideal spot (home + 2+ rest + weak D):** {ideal['points'].mean():.1f} avg (N={len(ideal)})")
        if len(tough) >= 3:
            findings.append(f"- **Tough spot (away + <=1 rest + strong D):** {tough['points'].mean():.1f} avg (N={len(tough)})")

    if not findings:
        return "*No strong actionable patterns found with sufficient sample size.*"

    return "\n".join(findings)


def main():
    args = parse_args()
    player = args.player_lookup

    # Determine start date
    if args.min_date:
        start_date = args.min_date
    else:
        # Go back N seasons (each season starts ~Oct)
        current_year = date.today().year
        current_month = date.today().month
        if current_month >= 10:
            season_start_year = current_year - args.seasons + 1
        else:
            season_start_year = current_year - args.seasons
        start_date = f"{season_start_year}-10-01"

    print(f"Player Deep Dive: {player}")
    print(f"Data from: {start_date}")
    print(f"{'=' * 50}")

    client = bigquery.Client(project=PROJECT_ID)
    data = fetch_data(client, player, start_date)

    if len(data["games"]) == 0:
        print(f"ERROR: No games found for '{player}' since {start_date}")
        sys.exit(1)

    df = merge_data(data)

    report = generate_report(player, data, df)

    # Output
    output_path = args.output or f"results/player_deep_dive_{player}.md"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)

    print(f"\nReport written to: {output_path}")
    print(f"Total games analyzed: {len(df)}")
    print(f"Games with prop lines: {len(df[df['points_line'].notna() & (df['points_line'] > 0)])}")
    print(f"Graded predictions: {len(data['predictions'])}")


if __name__ == "__main__":
    main()
