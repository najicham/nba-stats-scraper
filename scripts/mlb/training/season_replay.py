#!/usr/bin/env python3
"""
MLB Full Season Replay — End-to-End Production Simulation

Replays the 2025 season as if running the full production pipeline live:
  1. Walk-forward model training (CatBoost Regressor, 120d window, 14d retrains)
  2. Predictions on all pitchers each day
  3. Best bets pipeline: negative filters → signals → ranking → top-3
  4. Ultra tier tagging (home + projection agrees + half-line + edge >= 1.0)
  5. Day-by-day bankroll tracking (1u BB, 2u Ultra)
  6. Retrain log, model inventory, detailed pick-level output

Removes 5 dead features identified in Session 443:
  - f17_month_of_season, f18_days_into_season, f24_is_postseason (dead)
  - f67_season_starts (duplicate of f08_season_games)
  - f69_recent_workload_ratio (duplicate of f21/6.0)

Usage:
    PYTHONPATH=. python scripts/mlb/training/season_replay.py \
        --start-date 2025-04-01 \
        --end-date 2025-09-28 \
        --output-dir results/mlb_season_replay/
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"

# =============================================================================
# CONFIGURATION — matches production best_bets_exporter.py
# =============================================================================

TRAINING_WINDOW_DAYS = 120
RETRAIN_INTERVAL_DAYS = 14

# Edge/probability caps
DEFAULT_EDGE_FLOOR = 0.75
MAX_EDGE = 2.0
MAX_PROB_OVER = 0.85
MAX_PICKS_PER_DAY = 5
MIN_SIGNAL_COUNT = 2
UNDER_MIN_SIGNALS = 3
UNDER_ENABLED = False

# Sigmoid scale for edge -> p_over
SIGMOID_SCALE = 0.7

# Pitcher blacklist (Session 443 base + Session 444 + Session 447 replay additions)
PITCHER_BLACKLIST = frozenset([
    # Session 443 (18 pitchers — walk-forward <45% HR at N >= 10)
    'tanner_bibee', 'mitchell_parker', 'casey_mize', 'mitch_keller',
    'logan_webb', 'jose_berrios', 'logan_gilbert', 'logan_allen',
    'jake_irvin', 'george_kirby', 'mackenzie_gore', 'bailey_ober',
    'zach_eflin', 'ryne_nelson', 'jameson_taillon', 'ryan_feltner',
    'luis_severino', 'randy_vasquez',
    # Session 444 replay additions — 0% HR or <40% at N >= 3
    'adrian_houser',           # 0-4 (0% HR)
    'stephen_kolek',           # 0-3 (0% HR)
    'dean_kremer',             # 1-3 (25% HR)
    'michael_mcgreevy',        # 1-3 (25% HR)
    'tyler_mahle',             # 1-3 (25% HR)
    # Session 447 additions — season replay <45% HR at N >= 5
    'ranger_suárez',           # 33.3% HR, N=6
    'cade_horton',             # 37.5% HR, N=8
    'blake_snell',             # 40.0% HR, N=5
    'luis_castillo',           # 42.9% HR, N=7
    'paul_skenes',             # 44.4% HR, N=9
])

# Signal rescue tags — swstr_surge REMOVED S444 (54.9% HR), ballpark_k_boost REMOVED S447 (41.2% solo)
RESCUE_SIGNAL_TAGS = frozenset(['opponent_k_prone'])

# Base signals (inflate signal count with zero value)
BASE_SIGNAL_TAGS = frozenset(['high_edge'])

# Tracking-only signals — computed but excluded from real_signal_count (Session 454)
# k_trending_over: 55.6% cross-season — coin flip
# long_rest_over: 55.4% HR, -36u P&L across 4 seasons — actively losing money
# Session 460: All new shadow signals are tracking-only until cross-season validated
TRACKING_ONLY_SIGNALS = frozenset([
    'k_trending_over', 'long_rest_over',
    # Session 460 shadow signals — still accumulating data
    'cold_weather_k_over', 'short_starter_under', 'game_total_low_over',
    # Session 460 round 2 shadow signals
    'rematch_familiarity_under', 'cumulative_arm_stress_under',
    # Session 464 shadow signals
    'k_rate_reversion_under', 'k_rate_bounce_over',
    'umpire_k_friendly', 'umpire_csw_combo_over',  # S465: 64.2% HR but inflates RSC, hurts pick quality
    'rest_workload_stress_under', 'low_era_high_k_combo_over',
    # Session 465 combo shadow signals (2 remaining shadow)
    'day_game_elite_peripherals_combo_over',
    'high_csw_low_era_high_k_combo_over',
    # PROMOTED: high_csw_over, elite_peripherals_over, pitch_efficiency_depth_over (S460)
    # PROMOTED: day_game_shadow_over, pitcher_on_roll_over (S464)
    # PROMOTED: xfip_elite_over, day_game_high_csw_combo_over (S465)
])

# Ultra tier criteria — Session 452 cross-season redesign
# Removed: half_line (vacuous — all K lines are x.5), edge >= 1.1 (hurt 2022-2023)
# New: Home + Projection Agrees + edge >= 0.5 (minimal guard)
# Rescued picks CANNOT be Ultra (lowest-confidence picks shouldn't get 2u)
ULTRA_MIN_EDGE = 0.5
ULTRA_REQUIRES_HOME = True
ULTRA_REQUIRES_PROJECTION_AGREES = True

# Feature columns — CLEANED (5 dead features removed)
FEATURE_COLS = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    # f17, f18, f24 REMOVED (dead features)
    'f19_season_swstr_pct', 'f19b_season_csw_pct',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f25_is_day_game',
    'f30_k_avg_vs_line', 'f32_line_level',
    'f40_bp_projection', 'f41_projection_diff', 'f44_over_implied_prob',
    'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
    'f52_swstr_trend', 'f53_velocity_change',
    'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
    # f67 REMOVED (duplicate of f08)
    'f68_k_per_pitch',
    # f69 REMOVED (duplicate of f21/6.0)
    'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
]

# Columns to load (includes removed features for reference, but they won't be in training)
ALL_FEATURE_COLS_WITH_DEAD = FEATURE_COLS + [
    'f17_month_of_season', 'f18_days_into_season', 'f24_is_postseason',
    'f67_season_starts', 'f69_recent_workload_ratio',
]


def parse_args():
    parser = argparse.ArgumentParser(description="MLB Full Season Replay")
    parser.add_argument("--start-date", default="2025-04-01")
    parser.add_argument("--end-date", default="2025-09-28")
    parser.add_argument("--output-dir", default="results/mlb_season_replay/")
    parser.add_argument("--training-window", type=int, default=TRAINING_WINDOW_DAYS)
    parser.add_argument("--retrain-interval", type=int, default=RETRAIN_INTERVAL_DAYS)
    parser.add_argument("--edge-floor", type=float, default=DEFAULT_EDGE_FLOOR)
    parser.add_argument("--max-picks", type=int, default=MAX_PICKS_PER_DAY)
    parser.add_argument("--enable-under", action="store_true")
    parser.add_argument("--include-dead-features", action="store_true",
                       help="Include the 5 dead features for A/B comparison")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--use-blacklist", action="store_true",
                       help="Enable static pitcher blacklist (disabled by default)")
    parser.add_argument("--no-blacklist", action="store_true",
                       help="(deprecated, blacklist is now off by default)")
    parser.add_argument("--away-edge-floor", type=float, default=0.0,
                       help="Minimum edge for away OVER pitchers (0 = use default edge floor)")
    parser.add_argument("--block-away-rescue", action="store_true",
                       help="Block rescued picks for away pitchers")
    # Dynamic blacklist — walk-forward pitcher suppression
    parser.add_argument("--dynamic-blacklist", action="store_true",
                       help="Enable walk-forward pitcher suppression (replaces static blacklist)")
    parser.add_argument("--bl-min-n", type=int, default=10,
                       help="Min BB picks before suppression can trigger (default: 10)")
    parser.add_argument("--bl-max-hr", type=float, default=0.45,
                       help="Max HR threshold — suppress if HR < this (default: 0.45)")
    # P0 experiments — odds-aware ranking and juice filter
    parser.add_argument("--ev-ranking", action="store_true",
                       help="Rank OVER picks by EV (edge × payout_multiplier) instead of raw edge")
    parser.add_argument("--max-juice", type=int, default=0,
                       help="Block picks with odds worse than this (e.g. -160 blocks -170). 0=disabled")
    # P1 experiments — edge floor, RSC cap, rescue, max-edge, training
    parser.add_argument("--max-rsc", type=int, default=0,
                       help="Cap real signal count (e.g. 5 = block rsc>=6). 0=disabled")
    parser.add_argument("--no-rescue", action="store_true",
                       help="Disable all rescue signals (picks must meet edge floor)")
    parser.add_argument("--max-edge-cap", type=float, default=0.0,
                       help="Override MAX_EDGE cap (e.g. 1.5). 0=use default 2.0")
    # P2 experiments — CatBoost hyperparameters
    parser.add_argument("--depth", type=int, default=4,
                       help="CatBoost tree depth (default: 4, Session 459 winner)")
    parser.add_argument("--lr", type=float, default=0.015,
                       help="CatBoost learning rate (default: 0.015)")
    parser.add_argument("--iters", type=int, default=500,
                       help="CatBoost iterations (default: 500)")
    parser.add_argument("--l2-reg", type=float, default=10.0,
                       help="CatBoost l2_leaf_reg (default: 10.0, Session 459 winner)")
    return parser.parse_args()


# =============================================================================
# DATA LOADING
# =============================================================================

def load_data(client: bigquery.Client, earliest_date: str = "2024-01-01") -> pd.DataFrame:
    """Load all data for replay period.

    Args:
        earliest_date: Earliest date to load (training window start). Default 2024-01-01.
    """
    print(f"Loading data from BigQuery (from {earliest_date})...")

    query = f"""
    WITH statcast_rolling AS (
        SELECT DISTINCT
            player_lookup,
            game_date,
            swstr_pct_last_3,
            swstr_pct_last_5,
            swstr_pct_season_prior,
            fb_velocity_last_3,
            fb_velocity_season_prior
        FROM `mlb_analytics.pitcher_rolling_statcast`
        WHERE statcast_games_count >= 3
    )
    SELECT
        bp.game_date,
        bp.player_name,
        bp.player_lookup AS bp_player_lookup,
        bp.over_line,
        bp.projection_value,
        bp.actual_value,
        bp.over_odds,
        CASE WHEN bp.actual_value > bp.over_line THEN 1 ELSE 0 END as went_over,

        -- Metadata
        pgs.player_lookup,
        pgs.team_abbr,
        pgs.opponent_team_abbr,
        pgs.venue,
        pgs.innings_pitched,
        pgs.rolling_stats_games,

        -- Features
        pgs.k_avg_last_3 as f00_k_avg_last_3,
        pgs.k_avg_last_5 as f01_k_avg_last_5,
        pgs.k_avg_last_10 as f02_k_avg_last_10,
        pgs.k_std_last_10 as f03_k_std_last_10,
        pgs.ip_avg_last_5 as f04_ip_avg_last_5,
        pgs.season_k_per_9 as f05_season_k_per_9,
        pgs.era_rolling_10 as f06_season_era,
        pgs.whip_rolling_10 as f07_season_whip,
        pgs.season_games_started as f08_season_games,
        pgs.season_strikeouts as f09_season_k_total,
        IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
        pgs.opponent_team_k_rate as f15_opponent_team_k_rate,
        pgs.ballpark_k_factor as f16_ballpark_k_factor,
        pgs.month_of_season as f17_month_of_season,
        pgs.days_into_season as f18_days_into_season,
        pgs.season_swstr_pct as f19_season_swstr_pct,
        pgs.season_csw_pct as f19b_season_csw_pct,
        pgs.days_rest as f20_days_rest,
        pgs.games_last_30_days as f21_games_last_30_days,
        pgs.pitch_count_avg_last_5 as f22_pitch_count_avg,
        pgs.season_innings as f23_season_ip_total,
        IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,
        IF(pgs.is_day_game, 1.0, 0.0) as f25_is_day_game,

        -- Line-relative
        (pgs.k_avg_last_5 - bp.over_line) as f30_k_avg_vs_line,
        bp.over_line as f32_line_level,

        -- BettingPros
        bp.projection_value as f40_bp_projection,
        (bp.projection_value - bp.over_line) as f41_projection_diff,
        CASE
            WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
            ELSE 100.0 / (bp.over_odds + 100.0)
        END as f44_over_implied_prob,

        -- Rolling Statcast
        COALESCE(sc.swstr_pct_last_3, pgs.season_swstr_pct) as f50_swstr_pct_last_3,
        COALESCE(sc.fb_velocity_last_3, sc.fb_velocity_season_prior) as f51_fb_velocity_last_3,
        COALESCE(sc.swstr_pct_last_3 - sc.swstr_pct_season_prior, 0.0) as f52_swstr_trend,
        COALESCE(sc.fb_velocity_season_prior - sc.fb_velocity_last_3, 0.0) as f53_velocity_change,

        -- Pitcher matchup
        pgs.vs_opponent_k_per_9 as f65_vs_opp_k_per_9,
        pgs.vs_opponent_games as f66_vs_opp_games,

        -- Workload
        pgs.season_games_started as f67_season_starts,
        SAFE_DIVIDE(pgs.k_avg_last_5, NULLIF(pgs.pitch_count_avg_last_5, 0)) as f68_k_per_pitch,
        SAFE_DIVIDE(pgs.games_last_30_days, 6.0) as f69_recent_workload_ratio,

        -- FanGraphs
        fg.o_swing_pct as f70_o_swing_pct,
        fg.z_contact_pct as f71_z_contact_pct,
        fg.fip as f72_fip,
        fg.gb_pct as f73_gb_pct,
        fg.xfip as f74_xfip,

        -- Session 460: Additional columns for new signals
        pgs.game_total_line,
        pgs.team_implied_runs,
        -- Weather (joined via game home team)
        w.temperature_f,
        w.is_dome,
        -- Session 465: Umpire data
        ua.umpire_name,
        ump_stats.umpire_k_rate,
        ump_stats.umpire_games

    FROM `mlb_raw.bp_pitcher_props` bp
    JOIN `mlb_analytics.pitcher_game_summary` pgs
        ON pgs.game_date = bp.game_date
        AND LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', '')) = bp.player_lookup
    LEFT JOIN statcast_rolling sc
        ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
        AND pgs.game_date = sc.game_date
    LEFT JOIN (
        SELECT *
        FROM `mlb_raw.fangraphs_pitcher_season_stats`
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup, season_year ORDER BY snapshot_date DESC) = 1
    ) fg
        ON LOWER(REGEXP_REPLACE(NORMALIZE(fg.player_lookup, NFD), r'[\\W_]+', ''))
            = LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', ''))
        AND fg.season_year = EXTRACT(YEAR FROM pgs.game_date)
    -- Session 460: Weather data for cold_weather_k_over signal
    LEFT JOIN (
        SELECT team_abbr, scrape_date, temperature_f, is_dome,
               ROW_NUMBER() OVER (PARTITION BY team_abbr, scrape_date ORDER BY created_at DESC) as rn
        FROM `mlb_raw.mlb_weather`
    ) w ON w.team_abbr = CASE WHEN pgs.is_home THEN pgs.team_abbr ELSE pgs.opponent_team_abbr END
        AND w.scrape_date = pgs.game_date AND w.rn = 1
    -- Session 465: Umpire assignment → compute historical K-rate per umpire
    LEFT JOIN `mlb_raw.mlb_umpire_assignments` ua
        ON ua.game_date = pgs.game_date
        AND (ua.home_team_abbr = pgs.team_abbr OR ua.away_team_abbr = pgs.team_abbr)
    LEFT JOIN (
        -- Umpire K-rate from pitcher game data (K per IP * 9 / 4.3 ≈ K per PA)
        SELECT ua2.umpire_name,
               SAFE_DIVIDE(SUM(pgs2.strikeouts), NULLIF(SUM(pgs2.innings_pitched) * 4.3, 0)) as umpire_k_rate,
               COUNT(*) as umpire_games
        FROM `mlb_raw.mlb_umpire_assignments` ua2
        JOIN `mlb_analytics.pitcher_game_summary` pgs2
            ON pgs2.game_date = ua2.game_date
            AND (pgs2.team_abbr = ua2.home_team_abbr OR pgs2.team_abbr = ua2.away_team_abbr)
            AND pgs2.innings_pitched >= 3.0
        WHERE ua2.game_date >= '{earliest_date}'
          AND ua2.home_team_abbr IS NOT NULL AND ua2.home_team_abbr != ''
        GROUP BY ua2.umpire_name
        HAVING COUNT(*) >= 20
    ) ump_stats ON ump_stats.umpire_name = ua.umpire_name
    WHERE bp.market_id = 285
      AND bp.actual_value IS NOT NULL
      AND bp.projection_value IS NOT NULL
      AND bp.over_line IS NOT NULL
      AND pgs.innings_pitched >= 3.0
      AND pgs.rolling_stats_games >= 3
      AND pgs.game_date >= '{earliest_date}'
    ORDER BY bp.game_date
    """

    df = client.query(query).to_dataframe()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values('game_date').reset_index(drop=True)

    print(f"Loaded {len(df):,} samples")
    print(f"Date range: {df['game_date'].min().date()} to {df['game_date'].max().date()}")

    sc_coverage = df['f50_swstr_pct_last_3'].notna().mean() * 100
    print(f"Statcast coverage: {sc_coverage:.1f}%")

    return df


# =============================================================================
# MODEL TRAINING
# =============================================================================

def train_regressor(X_train: pd.DataFrame, y_train: pd.Series, seed: int = 42,
                    depth: int = 5, learning_rate: float = 0.015,
                    iterations: int = 500, l2_leaf_reg: float = 3):
    """Train CatBoost Regressor with production config."""
    from catboost import CatBoostRegressor

    model = CatBoostRegressor(
        depth=depth,
        learning_rate=learning_rate,
        iterations=iterations,
        l2_leaf_reg=l2_leaf_reg,
        subsample=0.8,
        random_seed=seed,
        loss_function='RMSE',
        verbose=0,
    )
    model.fit(X_train, y_train)
    return model


# =============================================================================
# SIGNAL EVALUATION
# =============================================================================

def evaluate_signals(row: pd.Series, predicted_k: float, edge: float,
                     recommendation: str) -> Dict:
    """Evaluate all signals for a single prediction. Returns signal results dict."""
    signals = {}
    signal_tags = []

    # --- high_edge (base signal) ---
    if recommendation == 'OVER' and edge >= 1.0:
        signals['high_edge'] = {'confidence': min(1.0, edge / 3.0)}
        signal_tags.append('high_edge')
    elif recommendation == 'UNDER' and edge <= -1.0:
        signals['high_edge'] = {'confidence': min(1.0, abs(edge) / 3.0)}
        signal_tags.append('high_edge')

    if recommendation == 'OVER':
        # --- swstr_surge ---
        swstr_last_3 = _safe_float(row, 'f50_swstr_pct_last_3')
        swstr_season = _safe_float(row, 'f19_season_swstr_pct')
        if swstr_last_3 is not None and swstr_season is not None:
            surge = swstr_last_3 - swstr_season
            if surge >= 0.02:
                signals['swstr_surge'] = {'confidence': min(1.0, surge / 0.05), 'surge_pct': surge}
                signal_tags.append('swstr_surge')

        # --- opponent_k_prone ---
        opp_k = _safe_float(row, 'f15_opponent_team_k_rate')
        if opp_k is not None and opp_k >= 0.24:
            signals['opponent_k_prone'] = {'confidence': min(1.0, (opp_k - 0.20) / 0.08),
                                           'opponent_k_rate': opp_k}
            signal_tags.append('opponent_k_prone')

        # --- ballpark_k_boost ---
        k_factor = _safe_float(row, 'f16_ballpark_k_factor')
        if k_factor is not None and k_factor > 1.05:
            signals['ballpark_k_boost'] = {'confidence': min(1.0, (k_factor - 1.0) / 0.15),
                                           'ballpark_k_factor': k_factor}
            signal_tags.append('ballpark_k_boost')

        # --- projection_agrees_over ---
        proj_diff = _safe_float(row, 'f41_projection_diff')
        if proj_diff is not None and proj_diff >= 0.5:
            signals['projection_agrees_over'] = {'confidence': min(1.0, proj_diff / 2.0),
                                                  'projection_diff': proj_diff}
            signal_tags.append('projection_agrees_over')

        # --- regressor_projection_agrees_over ---
        proj_val = _safe_float(row, 'projection_value')
        line = _safe_float(row, 'over_line')
        if proj_val is not None and line is not None and proj_val > line:
            diff = proj_val - line
            signals['regressor_projection_agrees_over'] = {'confidence': min(1.0, diff / 2.0),
                                                            'projection_diff': diff}
            signal_tags.append('regressor_projection_agrees_over')

        # --- k_trending_over ---
        k_last_3 = _safe_float(row, 'f00_k_avg_last_3')
        k_last_10 = _safe_float(row, 'f02_k_avg_last_10')
        if k_last_3 is not None and k_last_10 is not None:
            trend = k_last_3 - k_last_10
            if trend >= 1.0:
                signals['k_trending_over'] = {'confidence': min(1.0, trend / 3.0), 'trend': trend}
                signal_tags.append('k_trending_over')

        # --- recent_k_above_line ---
        k_vs_line = _safe_float(row, 'f30_k_avg_vs_line')
        if k_vs_line is not None and k_vs_line > 0:
            signals['recent_k_above_line'] = {'confidence': min(1.0, k_vs_line / 2.0),
                                               'k_avg_vs_line': k_vs_line}
            signal_tags.append('recent_k_above_line')

        # --- home_pitcher_over ---
        is_home = _safe_float(row, 'f10_is_home')
        if is_home is not None and is_home > 0.5:
            signals['home_pitcher_over'] = {'confidence': 0.6}
            signal_tags.append('home_pitcher_over')

        # --- long_rest_over ---
        days_rest = _safe_float(row, 'f20_days_rest')
        if days_rest is not None and days_rest >= 8:
            signals['long_rest_over'] = {'confidence': 0.7, 'days_rest': days_rest}
            signal_tags.append('long_rest_over')

        # --- Session 460: New shadow signals (OVER) ---

        # --- cold_weather_k_over ---
        temp = _safe_float(row, 'temperature_f')
        is_dome = row.get('is_dome')
        if temp is not None and temp < 60 and not is_dome:
            signals['cold_weather_k_over'] = {
                'confidence': min(1.0, (65 - temp) / 25.0),
                'temperature': temp,
            }
            signal_tags.append('cold_weather_k_over')

        # --- lineup_k_spike_over ---
        # NOTE: lineup_k_vs_hand not in pitcher_game_summary (computed by pitcher_loader at prediction time)
        # Signal fires in production only. Will backfill when bottom-up data is in analytics.

        # --- pitch_efficiency_depth_over ---
        ip_avg = _safe_float(row, 'f04_ip_avg_last_5')
        pitch_avg = _safe_float(row, 'f22_pitch_count_avg')
        if ip_avg is not None and ip_avg >= 6.0:
            is_efficient = (pitch_avg is not None and pitch_avg < 95)
            signals['pitch_efficiency_depth_over'] = {
                'confidence': 0.8 if is_efficient else 0.6,
                'ip_avg': ip_avg,
                'pitch_avg': pitch_avg,
            }
            signal_tags.append('pitch_efficiency_depth_over')

        # --- high_csw_over ---
        csw = _safe_float(row, 'f19b_season_csw_pct')
        if csw is not None and csw >= 0.30:
            signals['high_csw_over'] = {
                'confidence': min(1.0, (csw - 0.25) / 0.10),
                'csw_pct': csw,
            }
            signal_tags.append('high_csw_over')

        # --- elite_peripherals_over ---
        fip = _safe_float(row, 'f72_fip')
        k9 = _safe_float(row, 'f05_season_k_per_9')
        if fip is not None and k9 is not None and fip < 3.5 and k9 >= 9.0:
            fip_score = max(0, (3.5 - fip) / 1.5)
            k9_score = max(0, (k9 - 8.0) / 4.0)
            signals['elite_peripherals_over'] = {
                'confidence': min(1.0, (fip_score + k9_score) / 2.0),
                'fip': fip,
                'k_per_9': k9,
            }
            signal_tags.append('elite_peripherals_over')

        # --- game_total_low_over ---
        game_total = _safe_float(row, 'game_total_line')
        if game_total is not None and game_total <= 7.5:
            signals['game_total_low_over'] = {
                'confidence': min(1.0, (9.0 - game_total) / 3.0),
                'game_total_line': game_total,
            }
            signal_tags.append('game_total_low_over')

        # --- bottom_up_agrees_over ---
        # NOTE: bottom_up_k_expected not in pitcher_game_summary (computed by pitcher_loader)
        # Signal fires in production only. Will backfill when bottom-up data is in analytics.

        # --- day_game_shadow_over ---
        is_day = _safe_float(row, 'f25_is_day_game')
        if is_day is not None and is_day > 0.5:
            signals['day_game_shadow_over'] = {
                'confidence': 0.5,
            }
            signal_tags.append('day_game_shadow_over')

        # --- Session 464: New shadow signals (OVER) ---

        # --- k_rate_bounce_over ---
        k_avg_3_bounce = _safe_float(row, 'f00_k_avg_last_3')
        k9_bounce = _safe_float(row, 'f05_season_k_per_9')
        ip_avg_bounce = _safe_float(row, 'f04_ip_avg_last_5')
        if k_avg_3_bounce is not None and k9_bounce is not None and ip_avg_bounce is not None:
            expected_k = k9_bounce * ip_avg_bounce / 9.0
            deficit = expected_k - k_avg_3_bounce
            if deficit >= 2.0:
                signals['k_rate_bounce_over'] = {
                    'confidence': min(1.0, deficit / 4.0),
                    'k_avg_last_3': k_avg_3_bounce,
                    'expected_k': expected_k,
                    'k_deficit': deficit,
                }
                signal_tags.append('k_rate_bounce_over')

        # --- umpire_k_friendly (Session 465: now in replay SQL) ---
        ump_k = _safe_float(row, 'umpire_k_rate')
        if ump_k is not None and ump_k >= 0.22:
            signals['umpire_k_friendly'] = {
                'confidence': min(1.0, (ump_k - 0.18) / 0.08),
                'umpire_k_rate': ump_k,
                'umpire_name': str(row.get('umpire_name', '')),
            }
            signal_tags.append('umpire_k_friendly')

        # --- umpire_csw_combo_over ---
        csw_ump = _safe_float(row, 'f19b_season_csw_pct')
        if ump_k is not None and csw_ump is not None and ump_k >= 0.22 and csw_ump >= 0.30:
            signals['umpire_csw_combo_over'] = {
                'confidence': min(1.0, (ump_k - 0.18) / 0.08 * 0.5 + (csw_ump - 0.25) / 0.10 * 0.5),
                'umpire_k_rate': ump_k,
                'csw_pct': csw_ump,
            }
            signal_tags.append('umpire_csw_combo_over')

        # --- low_era_high_k_combo_over ---
        era_combo = _safe_float(row, 'f06_season_era')
        k9_combo = _safe_float(row, 'f05_season_k_per_9')
        if era_combo is not None and k9_combo is not None:
            if era_combo < 3.0 and k9_combo >= 8.5:
                era_s = max(0, (3.0 - era_combo) / 1.5)
                k9_s = max(0, (k9_combo - 7.5) / 4.0)
                signals['low_era_high_k_combo_over'] = {
                    'confidence': min(1.0, (era_s + k9_s) / 2.0),
                    'era': era_combo,
                    'k_per_9': k9_combo,
                }
                signal_tags.append('low_era_high_k_combo_over')

        # --- pitcher_on_roll_over ---
        k3_roll = _safe_float(row, 'f00_k_avg_last_3')
        k5_roll = _safe_float(row, 'f01_k_avg_last_5')
        line_roll = _safe_float(row, 'over_line')
        if k3_roll is not None and k5_roll is not None and line_roll is not None:
            if k3_roll > line_roll and k5_roll > line_roll:
                margin = ((k3_roll - line_roll) + (k5_roll - line_roll)) / 2.0
                signals['pitcher_on_roll_over'] = {
                    'confidence': min(1.0, margin / 2.0),
                    'k_avg_last_3': k3_roll,
                    'k_avg_last_5': k5_roll,
                    'line': line_roll,
                }
                signal_tags.append('pitcher_on_roll_over')

        # --- Session 465: combo signals (shadow) ---
        # day_game_high_csw_combo_over: day game + CSW >= 30%
        is_day = _safe_float(row, 'f25_is_day_game')
        csw_combo = _safe_float(row, 'f19b_season_csw_pct')
        if is_day is not None and is_day > 0.5 and csw_combo is not None and csw_combo >= 0.30:
            signals['day_game_high_csw_combo_over'] = {
                'confidence': min(1.0, 0.25 + (csw_combo - 0.25) / 0.10 * 0.5),
                'is_day_game': True,
                'csw_pct': csw_combo,
            }
            signal_tags.append('day_game_high_csw_combo_over')

        # day_game_elite_peripherals_combo_over: day game + FIP < 3.5 + K/9 >= 9.0
        fip_combo = _safe_float(row, 'f72_fip')
        k9_combo2 = _safe_float(row, 'f05_season_k_per_9')
        if (is_day is not None and is_day > 0.5 and fip_combo is not None
                and k9_combo2 is not None and fip_combo < 3.5 and k9_combo2 >= 9.0):
            fip_s = max(0, (3.5 - fip_combo) / 1.5)
            k9_s2 = max(0, (k9_combo2 - 8.0) / 4.0)
            signals['day_game_elite_peripherals_combo_over'] = {
                'confidence': min(1.0, 0.15 + (fip_s + k9_s2) / 2.0 * 0.7),
                'is_day_game': True, 'fip': fip_combo, 'k_per_9': k9_combo2,
            }
            signal_tags.append('day_game_elite_peripherals_combo_over')

        # high_csw_low_era_high_k_combo_over: CSW >= 30% + ERA < 3.0 + K/9 >= 8.5
        era_combo3 = _safe_float(row, 'f06_season_era')
        k9_combo3 = _safe_float(row, 'f05_season_k_per_9')
        csw_combo3 = _safe_float(row, 'f19b_season_csw_pct')
        if (csw_combo3 is not None and era_combo3 is not None and k9_combo3 is not None
                and csw_combo3 >= 0.30 and era_combo3 < 3.0 and k9_combo3 >= 8.5):
            csw_s = min(1.0, (csw_combo3 - 0.25) / 0.10)
            era_s3 = max(0, (3.0 - era_combo3) / 1.5)
            k9_s3 = max(0, (k9_combo3 - 7.5) / 4.0)
            signals['high_csw_low_era_high_k_combo_over'] = {
                'confidence': min(1.0, (csw_s + era_s3 + k9_s3) / 3.0),
                'csw_pct': csw_combo3, 'era': era_combo3, 'k_per_9': k9_combo3,
            }
            signal_tags.append('high_csw_low_era_high_k_combo_over')

    elif recommendation == 'UNDER':
        # --- velocity_drop_under ---
        vel_change = _safe_float(row, 'f53_velocity_change')
        if vel_change is not None and vel_change >= 1.5:
            signals['velocity_drop_under'] = {'confidence': min(1.0, vel_change / 3.0),
                                               'velocity_drop_mph': vel_change}
            signal_tags.append('velocity_drop_under')

        # --- short_rest_under ---
        days_rest = _safe_float(row, 'f20_days_rest')
        if days_rest is not None and days_rest < 4:
            conf = 0.8 if days_rest <= 3 else 0.6
            signals['short_rest_under'] = {'confidence': conf, 'days_rest': days_rest}
            signal_tags.append('short_rest_under')

        # --- high_variance_under ---
        k_std = _safe_float(row, 'f03_k_std_last_10')
        if k_std is not None and k_std > 3.5:
            signals['high_variance_under'] = {'confidence': min(1.0, (k_std - 3.0) / 3.0),
                                               'k_std': k_std}
            signal_tags.append('high_variance_under')

        # --- Session 460: New shadow signals (UNDER) ---

        # --- short_starter_under ---
        ip_avg_u = _safe_float(row, 'f04_ip_avg_last_5')
        if ip_avg_u is not None and ip_avg_u < 5.0:
            signals['short_starter_under'] = {
                'confidence': min(1.0, (5.0 - ip_avg_u) / 2.0),
                'ip_avg': ip_avg_u,
            }
            signal_tags.append('short_starter_under')

        # --- rematch_familiarity_under ---
        vs_games = _safe_float(row, 'f66_vs_opp_games')
        if vs_games is not None and vs_games >= 3:
            signals['rematch_familiarity_under'] = {
                'confidence': min(1.0, vs_games / 6.0),
                'vs_games': vs_games,
            }
            signal_tags.append('rematch_familiarity_under')

        # --- cumulative_arm_stress_under ---
        pitch_avg_u = _safe_float(row, 'f22_pitch_count_avg')
        games_30d_u = _safe_float(row, 'f21_games_last_30_days')
        if (pitch_avg_u is not None and games_30d_u is not None
                and pitch_avg_u >= 100 and games_30d_u >= 6):
            stress = (pitch_avg_u / 100.0) * (games_30d_u / 6.0)
            signals['cumulative_arm_stress_under'] = {
                'confidence': min(1.0, (stress - 1.0) / 1.0),
                'pitch_avg': pitch_avg_u,
                'games_30d': games_30d_u,
            }
            signal_tags.append('cumulative_arm_stress_under')

        # --- Session 464: New shadow signals (UNDER) ---

        # --- k_rate_reversion_under ---
        k_avg_3_rev = _safe_float(row, 'f00_k_avg_last_3')
        k9_rev = _safe_float(row, 'f05_season_k_per_9')
        ip_avg_rev = _safe_float(row, 'f04_ip_avg_last_5')
        if k_avg_3_rev is not None and k9_rev is not None and ip_avg_rev is not None:
            expected_k_rev = k9_rev * ip_avg_rev / 9.0
            excess = k_avg_3_rev - expected_k_rev
            if excess >= 2.0:
                signals['k_rate_reversion_under'] = {
                    'confidence': min(1.0, excess / 4.0),
                    'k_avg_last_3': k_avg_3_rev,
                    'expected_k': expected_k_rev,
                    'k_excess': excess,
                }
                signal_tags.append('k_rate_reversion_under')

        # --- rest_workload_stress_under ---
        rest_stress = _safe_float(row, 'f20_days_rest')
        games_stress = _safe_float(row, 'f21_games_last_30_days')
        if rest_stress is not None and games_stress is not None:
            if rest_stress <= 5 and games_stress >= 6:
                rest_s = max(0, (5 - rest_stress) / 2.0)
                wl_s = max(0, (games_stress - 5) / 3.0)
                signals['rest_workload_stress_under'] = {
                    'confidence': min(1.0, (rest_s + wl_s) / 2.0),
                    'days_rest': rest_stress,
                    'games_30d': games_stress,
                }
                signal_tags.append('rest_workload_stress_under')

    # --- Session 465: xfip_elite_over (direction-agnostic, fires on OVER only) ---
    # xFIP < 3.5 = elite underlying stuff. Wider than elite_peripherals
    # (FIP + K/9). Must be outside if/elif OVER/UNDER block to fire correctly.
    xfip = _safe_float(row, 'f74_xfip')
    if xfip is not None and xfip < 3.5:
        conf = min(1.0, (3.5 - xfip) / 1.5)
        signals['xfip_elite_over'] = {
            'confidence': conf,
            'xfip': xfip,
        }
        signal_tags.append('xfip_elite_over')

    real_signal_count = sum(1 for t in signal_tags
                            if t not in BASE_SIGNAL_TAGS and t not in TRACKING_ONLY_SIGNALS)
    return {
        'signal_tags': signal_tags,
        'signal_count': len(signal_tags),
        'real_signal_count': real_signal_count,
        'signals': signals,
    }


def _safe_float(row: pd.Series, col: str) -> Optional[float]:
    """Get float value from row, returning None for NaN."""
    val = row.get(col)
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def payout_multiplier(odds: float) -> float:
    """Convert American odds to payout multiplier (profit per $1 risked)."""
    if odds < 0:
        return 100.0 / abs(odds)
    else:
        return odds / 100.0


def compute_pnl(stake: float, correct: bool, odds: float = -110) -> float:
    """Compute P&L using American odds.

    Negative odds (e.g. -110): win pays stake * 100/|odds|
    Positive odds (e.g. +120): win pays stake * odds/100
    Loss always pays -stake.
    """
    if not correct:
        return -stake
    if odds < 0:
        return stake * (100.0 / abs(odds))
    else:
        return stake * (odds / 100.0)


# =============================================================================
# DYNAMIC BLACKLIST — Walk-Forward Pitcher Suppression
# =============================================================================

class DynamicBlacklist:
    """Walk-forward pitcher suppression based on trailing BB pick performance.

    Replaces static blacklist with self-correcting logic:
    - Track each pitcher's BB pick results (wins/losses)
    - If pitcher has >= min_n picks AND HR < max_hr, suppress them
    - Re-evaluates every day (or after cooldown period)
    - Only uses data available at prediction time (walk-forward safe)
    """

    def __init__(self, min_n: int = 10, max_hr: float = 0.45):
        self.min_n = min_n
        self.max_hr = max_hr
        # {pitcher_lookup: [(game_date_str, correct_bool)]}
        self._history: Dict[str, List[Tuple[str, bool]]] = defaultdict(list)
        # {pitcher_lookup: suppress_start_date_str}
        self._suppress_log: Dict[str, List[Dict]] = defaultdict(list)
        self._blocks_today: Dict[str, Dict] = {}  # Today's blocks for reporting

    def record_pick(self, pitcher_lookup: str, game_date: str, correct: bool):
        """Record a graded BB pick for a pitcher."""
        self._history[pitcher_lookup].append((game_date, correct))

    def is_suppressed(self, pitcher_lookup: str, game_date: str) -> Optional[Dict]:
        """Check if pitcher is dynamically suppressed.

        Returns None if not suppressed, or dict with suppression details if suppressed.
        """
        history = self._history.get(pitcher_lookup, [])
        if len(history) < self.min_n:
            return None

        wins = sum(1 for _, c in history if c)
        total = len(history)
        hr = wins / total

        if hr < self.max_hr:
            details = {
                'pitcher_lookup': pitcher_lookup,
                'game_date': game_date,
                'wins': wins,
                'losses': total - wins,
                'hr': round(hr * 100, 1),
                'n': total,
            }
            self._blocks_today[pitcher_lookup] = details
            # Log suppression events
            if not self._suppress_log[pitcher_lookup] or \
               self._suppress_log[pitcher_lookup][-1].get('end_date') is not None:
                self._suppress_log[pitcher_lookup].append({
                    'start_date': game_date,
                    'end_date': None,
                    'hr_at_start': round(hr * 100, 1),
                    'n_at_start': total,
                })
            return details

        # Pitcher is above threshold — close any open suppression
        if self._suppress_log[pitcher_lookup] and \
           self._suppress_log[pitcher_lookup][-1].get('end_date') is None:
            self._suppress_log[pitcher_lookup][-1]['end_date'] = game_date
            self._suppress_log[pitcher_lookup][-1]['hr_at_end'] = round(hr * 100, 1)
            self._suppress_log[pitcher_lookup][-1]['n_at_end'] = total

        return None

    def reset_daily(self):
        """Reset daily tracking."""
        self._blocks_today = {}

    def summary(self) -> Dict:
        """Return summary of dynamic blacklist activity."""
        pitchers_ever_suppressed = {
            p: logs for p, logs in self._suppress_log.items() if logs
        }
        total_blocks = sum(
            len([d for d, c in self._history[p]])
            for p in pitchers_ever_suppressed
        )
        return {
            'pitchers_suppressed': len(pitchers_ever_suppressed),
            'suppression_events': sum(len(v) for v in pitchers_ever_suppressed.values()),
            'pitcher_details': {
                p: {
                    'total_picks': len(self._history[p]),
                    'wins': sum(1 for _, c in self._history[p] if c),
                    'hr': round(sum(1 for _, c in self._history[p] if c)
                                / max(len(self._history[p]), 1) * 100, 1),
                    'suppression_periods': logs,
                }
                for p, logs in pitchers_ever_suppressed.items()
            },
        }


# =============================================================================
# NEGATIVE FILTERS
# =============================================================================

def apply_negative_filters(row: pd.Series, recommendation: str,
                           pitcher_lookup: str, use_blacklist: bool = True) -> Optional[str]:
    """Apply negative filters. Returns filter name if blocked, None if passed."""

    # 1. bullpen_game_skip
    ip_avg = _safe_float(row, 'f04_ip_avg_last_5')
    if ip_avg is not None and ip_avg < 4.0:
        return 'bullpen_game_skip'

    # 2. insufficient_data_skip
    season_games = _safe_float(row, 'f08_season_games') or 0
    if season_games < 3:
        return 'insufficient_data_skip'

    # 3. pitcher_blacklist (OVER only)
    if use_blacklist and recommendation == 'OVER' and pitcher_lookup in PITCHER_BLACKLIST:
        return 'pitcher_blacklist'

    # 4. whole_line_over (OVER only)
    if recommendation == 'OVER':
        line = _safe_float(row, 'over_line')
        if line is not None and line == int(line):
            return 'whole_line_over'

    return None


# =============================================================================
# ULTRA TIER
# =============================================================================

def check_ultra(row: pd.Series, edge: float, recommendation: str,
                signal_tags: List[str], pitcher_lookup: str,
                was_rescued: bool = False, use_blacklist: bool = False) -> Tuple[bool, List[str]]:
    """Check if pick qualifies for Ultra tier. Returns (is_ultra, criteria_list).

    Session 452 cross-season redesign:
    - Removed half_line (vacuous — all K lines are x.5)
    - Lowered edge floor from 1.1 to 0.5 (edge floor hurt 2022-2023)
    - Rescued picks cannot be Ultra (lowest confidence shouldn't get 2u)
    - Blacklist check respects --use-blacklist flag
    """
    if recommendation != 'OVER':
        return False, []

    # Rescued picks cannot be Ultra — they barely passed the edge floor
    if was_rescued:
        return False, []

    criteria = []

    # Edge >= 0.5 (minimal guard against near-coin-flip predictions)
    if edge >= ULTRA_MIN_EDGE:
        criteria.append(f'edge_{edge:.1f}')
    else:
        return False, []

    # Home pitcher
    is_home = _safe_float(row, 'f10_is_home')
    if is_home is not None and is_home > 0.5:
        criteria.append('is_home')
    elif ULTRA_REQUIRES_HOME:
        return False, []

    # Projection agrees
    proj_agrees = ('projection_agrees_over' in signal_tags or
                   'regressor_projection_agrees_over' in signal_tags)
    if proj_agrees:
        criteria.append('projection_agrees')
    elif ULTRA_REQUIRES_PROJECTION_AGREES:
        return False, []

    # Not blacklisted (only when blacklist is active)
    if use_blacklist and pitcher_lookup in PITCHER_BLACKLIST:
        return False, []

    return True, criteria


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def run_replay(df: pd.DataFrame, feature_cols: List[str],
               sim_start: pd.Timestamp, sim_end: pd.Timestamp,
               args) -> Dict:
    """Run the full season replay."""
    use_blacklist = getattr(args, 'use_blacklist', False)
    use_dynamic_bl = getattr(args, 'dynamic_blacklist', False)

    # Initialize dynamic blacklist if enabled
    dyn_bl = None
    if use_dynamic_bl:
        dyn_bl = DynamicBlacklist(
            min_n=args.bl_min_n,
            max_hr=args.bl_max_hr,
        )

    retrain_log = []
    daily_summary = []
    all_picks = []
    all_predictions = []
    filter_audit = defaultdict(int)
    model_inventory = []

    current_model = None
    last_train_date = None
    model_version = 0

    game_dates = sorted(df[
        (df['game_date'] >= sim_start) & (df['game_date'] <= sim_end)
    ]['game_date'].unique())

    print(f"\nSimulating {len(game_dates)} game days: {sim_start.date()} to {sim_end.date()}")
    print(f"Feature count: {len(feature_cols)} (dead features removed: "
          f"{'NO' if args.include_dead_features else 'YES'})")
    print(f"Config: {args.training_window}d window, {args.retrain_interval}d retrain, "
          f"edge >= {args.edge_floor}, top-{args.max_picks}/day")
    print()

    bankroll = 0.0
    bb_wins = 0
    bb_losses = 0
    ultra_wins = 0
    ultra_losses = 0

    for i, game_date in enumerate(game_dates):
        # =====================================================
        # STEP 1: Check retrain
        # =====================================================
        needs_retrain = (
            current_model is None or
            last_train_date is None or
            (game_date - last_train_date).days >= args.retrain_interval
        )

        if needs_retrain:
            train_start = game_date - pd.Timedelta(days=args.training_window)
            train_mask = (df['game_date'] >= train_start) & (df['game_date'] < game_date)
            train_df = df[train_mask]

            X_train = train_df[feature_cols].copy()
            for col in X_train.columns:
                X_train[col] = pd.to_numeric(X_train[col], errors='coerce')
            y_train = train_df['actual_value']  # Regression target: raw K count

            if len(X_train) < 50:
                if current_model is None:
                    continue  # Skip this day, no model yet
                # Keep using previous model
            else:
                current_model = train_regressor(
                    X_train, y_train, seed=args.seed,
                    depth=args.depth, learning_rate=args.lr,
                    iterations=args.iters, l2_leaf_reg=args.l2_reg,
                )
                last_train_date = game_date
                model_version += 1

                # Validation: holdout last 14 days of training window
                val_start = game_date - pd.Timedelta(days=14)
                val_mask = (train_df['game_date'] >= val_start)
                if val_mask.sum() >= 10:
                    X_val = train_df[val_mask][feature_cols].copy()
                    for col in X_val.columns:
                        X_val[col] = pd.to_numeric(X_val[col], errors='coerce')
                    y_val = train_df[val_mask]['actual_value']
                    val_preds = current_model.predict(X_val)
                    val_mae = np.mean(np.abs(val_preds - y_val))
                    val_bias = np.mean(val_preds - y_val)
                else:
                    val_mae = None
                    val_bias = None

                retrain_entry = {
                    'game_date': str(game_date.date()),
                    'model_version': model_version,
                    'train_samples': len(X_train),
                    'train_start': str(train_start.date()),
                    'train_end': str((game_date - pd.Timedelta(days=1)).date()),
                    'val_mae': round(val_mae, 4) if val_mae else None,
                    'val_bias': round(val_bias, 4) if val_bias else None,
                }
                retrain_log.append(retrain_entry)
                model_inventory.append({
                    'model_id': f'catboost_v2_regressor_m{model_version:03d}',
                    'trained_on': str(game_date.date()),
                    'window': f'{train_start.date()} to {(game_date - pd.Timedelta(days=1)).date()}',
                    'samples': len(X_train),
                    'val_mae': round(val_mae, 4) if val_mae else None,
                })

                if (i % 28 == 0) or (model_version <= 3):
                    mae_str = f', MAE={val_mae:.3f}' if val_mae else ''
                    print(f"  [Model v{model_version}] Trained on {game_date.date()} "
                          f"({len(X_train)} samples{mae_str})")

        if current_model is None:
            continue

        # =====================================================
        # STEP 2: Generate predictions for all pitchers today
        # =====================================================
        test_mask = df['game_date'] == game_date
        test_df = df[test_mask].copy()

        X_test = test_df[feature_cols].copy()
        for col in X_test.columns:
            X_test[col] = pd.to_numeric(X_test[col], errors='coerce')

        if len(X_test) == 0:
            continue

        predicted_k = current_model.predict(X_test)
        predicted_k = np.clip(predicted_k, 0, 20)

        # =====================================================
        # STEP 3: Best bets pipeline
        # =====================================================
        candidates = []

        for idx in range(len(test_df)):
            row = test_df.iloc[idx]
            pred_k = float(predicted_k[idx])
            line = float(row['over_line'])
            actual = float(row['actual_value'])
            edge = pred_k - line
            recommendation = 'OVER' if edge > 0 else 'UNDER'
            p_over = 1.0 / (1.0 + math.exp(-edge * SIGMOID_SCALE))
            pitcher_lookup = str(row.get('player_lookup', ''))

            # Track all predictions
            pred_record = {
                'game_date': str(game_date.date()),
                'pitcher_lookup': pitcher_lookup,
                'pitcher_name': str(row.get('player_name', '')),
                'team_abbr': str(row.get('team_abbr', '')),
                'opponent_team_abbr': str(row.get('opponent_team_abbr', '')),
                'venue': str(row.get('venue', '')),
                'predicted_k': round(pred_k, 2),
                'actual_k': actual,
                'line': line,
                'edge': round(edge, 2),
                'recommendation': recommendation,
                'p_over': round(p_over, 4),
                'correct': int((recommendation == 'OVER' and actual > line) or
                              (recommendation == 'UNDER' and actual <= line)),
                'model_version': model_version,
            }
            all_predictions.append(pred_record)

            # --- Direction filter ---
            if recommendation == 'UNDER' and not args.enable_under:
                filter_audit['direction_filter'] += 1
                continue

            # --- Overconfidence cap ---
            max_edge_effective = args.max_edge_cap if args.max_edge_cap > 0 else MAX_EDGE
            if recommendation == 'OVER' and abs(edge) > max_edge_effective:
                filter_audit['overconfidence_cap'] += 1
                continue

            # --- Probability cap ---
            if recommendation == 'OVER' and p_over > MAX_PROB_OVER:
                filter_audit['probability_cap'] += 1
                continue

            # --- Negative filters ---
            blocked_by = apply_negative_filters(row, recommendation, pitcher_lookup, use_blacklist=use_blacklist)
            if blocked_by:
                filter_audit[blocked_by] += 1
                continue

            # --- Dynamic blacklist (walk-forward pitcher suppression) ---
            if dyn_bl and recommendation == 'OVER':
                suppression = dyn_bl.is_suppressed(pitcher_lookup, str(game_date.date()))
                if suppression:
                    filter_audit['dynamic_blacklist'] += 1
                    # Record the actual outcome so suppressed pitchers can recover
                    # (without this, history freezes and pitcher can never un-suppress)
                    actual = float(row['actual_value'])
                    would_correct = (actual > line)
                    dyn_bl.record_pick(pitcher_lookup, str(game_date.date()), would_correct)
                    continue

            # --- Edge floor + rescue ---
            is_home_pitcher = _safe_float(row, 'f10_is_home')
            is_away = is_home_pitcher is not None and is_home_pitcher < 0.5

            # Away pitchers: higher edge floor, optionally block rescue
            effective_edge_floor = args.edge_floor
            if recommendation == 'OVER' and is_away and args.away_edge_floor > 0:
                effective_edge_floor = args.away_edge_floor

            if abs(edge) < effective_edge_floor:
                # Away rescue blocked?
                if is_away and args.block_away_rescue:
                    filter_audit['away_rescue_blocked'] += 1
                    continue
                # No rescue mode?
                if args.no_rescue:
                    filter_audit['edge_floor'] += 1
                    continue
                # Check rescue signals
                sig_result = evaluate_signals(row, pred_k, edge, recommendation)
                rescued = any(t in RESCUE_SIGNAL_TAGS for t in sig_result['signal_tags'])
                if not rescued:
                    if is_away and args.away_edge_floor > 0 and abs(edge) >= args.edge_floor:
                        filter_audit['away_low_edge'] += 1
                    else:
                        filter_audit['edge_floor'] += 1
                    continue
                # Rescued — proceed with rescue flag
                was_rescued = True
            else:
                was_rescued = False

            # --- Signal evaluation ---
            sig_result = evaluate_signals(row, pred_k, edge, recommendation)
            signal_tags = sig_result['signal_tags']
            real_sc = sig_result['real_signal_count']

            # --- Signal count gate ---
            required_signals = UNDER_MIN_SIGNALS if recommendation == 'UNDER' else MIN_SIGNAL_COUNT
            if real_sc < required_signals:
                filter_audit['signal_count_gate'] += 1
                continue

            # --- RSC cap (e.g. --max-rsc 5 blocks rsc >= 6) ---
            if args.max_rsc > 0 and real_sc > args.max_rsc:
                filter_audit['rsc_cap'] = filter_audit.get('rsc_cap', 0) + 1
                continue

            # Passed all filters!
            raw_odds = row.get('over_odds')
            if raw_odds is None or (isinstance(raw_odds, float) and math.isnan(raw_odds)):
                over_odds = -110  # standard juice default
            else:
                over_odds = float(raw_odds)

            # --- Max juice filter (e.g. --max-juice -160 blocks -170, -180) ---
            if args.max_juice < 0 and over_odds < args.max_juice:
                filter_audit['max_juice'] = filter_audit.get('max_juice', 0) + 1
                continue

            candidates.append({
                'game_date': str(game_date.date()),
                'pitcher_lookup': pitcher_lookup,
                'pitcher_name': str(row.get('player_name', '')),
                'team_abbr': str(row.get('team_abbr', '')),
                'opponent_team_abbr': str(row.get('opponent_team_abbr', '')),
                'venue': str(row.get('venue', '')),
                'predicted_k': round(pred_k, 2),
                'actual_k': actual,
                'line': line,
                'edge': round(edge, 2),
                'over_odds': over_odds,
                'recommendation': recommendation,
                'p_over': round(p_over, 4),
                'signal_tags': signal_tags,
                'signal_count': sig_result['signal_count'],
                'real_signal_count': real_sc,
                'was_rescued': was_rescued,
                'is_home': int(row.get('f10_is_home', 0) > 0.5),
                'model_version': model_version,
                '_row': row,  # Temp: for ultra check
            })

        # --- Rank and select top-N ---
        over_cands = [c for c in candidates if c['recommendation'] == 'OVER']
        under_cands = [c for c in candidates if c['recommendation'] == 'UNDER']

        # OVER: pure edge ranking (or EV ranking if --ev-ranking)
        if args.ev_ranking:
            for c in over_cands:
                c['ev'] = round(abs(c['edge']) * payout_multiplier(c['over_odds']), 4)
            over_cands.sort(key=lambda c: c['ev'], reverse=True)
        else:
            # Tiebreaker: small bonus for umpire_k_friendly signal (doesn't inflate RSC)
            over_cands.sort(
                key=lambda c: abs(c['edge']) + (0.01 if 'umpire_k_friendly' in c.get('signal_tags', []) else 0.0),
                reverse=True,
            )

        # UNDER: weighted signal quality
        for c in under_cands:
            quality = 0.0
            for tag in c['signal_tags']:
                w = {'velocity_drop_under': 2.0, 'short_rest_under': 1.5,
                     'high_variance_under': 1.5}.get(tag, 1.0)
                quality += c.get('signals', {}).get(tag, {}).get('confidence', 0.5) * w
            c['under_signal_quality'] = quality
        under_cands.sort(key=lambda c: c.get('under_signal_quality', 0), reverse=True)

        ranked = over_cands + under_cands
        selected = ranked[:args.max_picks]

        # --- Ultra tier tagging + grading ---
        day_picks = []
        for rank_idx, pick in enumerate(selected, 1):
            row_data = pick.pop('_row')

            # Check ultra
            is_ultra, ultra_criteria = check_ultra(
                row_data, pick['edge'], pick['recommendation'],
                pick['signal_tags'], pick['pitcher_lookup'],
                was_rescued=pick.get('was_rescued', False),
                use_blacklist=use_blacklist,
            )

            actual_k = pick['actual_k']
            line = pick['line']
            correct = int(
                (pick['recommendation'] == 'OVER' and actual_k > line) or
                (pick['recommendation'] == 'UNDER' and actual_k <= line)
            )

            # Staking — use actual American odds for P&L
            stake = 2.0 if is_ultra else 1.0
            odds = pick.get('over_odds', -110)
            pnl = compute_pnl(stake, bool(correct), odds)

            pick.update({
                'rank': rank_idx,
                'correct': correct,
                'is_ultra': is_ultra,
                'ultra_criteria': ultra_criteria if is_ultra else [],
                'stake': stake,
                'pnl': round(pnl, 4),
            })
            day_picks.append(pick)

            bankroll += pnl
            if correct:
                bb_wins += 1
                if is_ultra:
                    ultra_wins += 1
            else:
                bb_losses += 1
                if is_ultra:
                    ultra_losses += 1

        # Also check ultra for picks NOT in top-3 (ultra overlay)
        ultra_extras = []
        for pick in ranked[args.max_picks:]:
            row_data = pick.pop('_row')
            is_ultra, ultra_criteria = check_ultra(
                row_data, pick['edge'], pick['recommendation'],
                pick['signal_tags'], pick['pitcher_lookup'],
                was_rescued=pick.get('was_rescued', False),
                use_blacklist=use_blacklist,
            )
            if is_ultra:
                actual_k = pick['actual_k']
                line = pick['line']
                correct = int(
                    (pick['recommendation'] == 'OVER' and actual_k > line) or
                    (pick['recommendation'] == 'UNDER' and actual_k <= line)
                )
                stake = 2.0
                odds = pick.get('over_odds', -110)
                pnl = compute_pnl(stake, bool(correct), odds)
                pick.update({
                    'rank': len(day_picks) + len(ultra_extras) + 1,
                    'correct': correct,
                    'is_ultra': True,
                    'ultra_criteria': ultra_criteria,
                    'stake': stake,
                    'pnl': round(pnl, 4),
                    'ultra_extra': True,  # Not in top-3 but added as ultra overlay
                })
                ultra_extras.append(pick)
                bankroll += pnl
                if correct:
                    ultra_wins += 1
                    bb_wins += 1
                else:
                    ultra_losses += 1
                    bb_losses += 1

        day_picks.extend(ultra_extras)

        # Remove temp _row from remaining unpicked candidates
        for pick in ranked[args.max_picks:]:
            pick.pop('_row', None)

        all_picks.extend(day_picks)

        # Update dynamic blacklist with today's graded picks
        if dyn_bl:
            dyn_bl.reset_daily()
            for pick in day_picks:
                dyn_bl.record_pick(
                    pick['pitcher_lookup'],
                    str(game_date.date()),
                    bool(pick['correct']),
                )

        # Daily summary
        day_correct = sum(p['correct'] for p in day_picks)
        day_total = len(day_picks)
        day_pnl = sum(p['pnl'] for p in day_picks)
        day_ultra = sum(1 for p in day_picks if p.get('is_ultra'))

        daily_summary.append({
            'game_date': str(game_date.date()),
            'picks': day_total,
            'correct': day_correct,
            'hr': round(day_correct / day_total * 100, 1) if day_total > 0 else 0,
            'pnl': round(day_pnl, 1),
            'bankroll': round(bankroll, 1),
            'ultra_picks': day_ultra,
            'model_version': model_version,
            'candidates_total': len(candidates),
            'predictions_total': sum(1 for p in all_predictions
                                      if p['game_date'] == str(game_date.date())),
        })

        # Progress
        if (i + 1) % 30 == 0 or i == len(game_dates) - 1:
            hr = bb_wins / (bb_wins + bb_losses) * 100 if (bb_wins + bb_losses) > 0 else 0
            print(f"  Day {i+1}/{len(game_dates)}: {game_date.date()} | "
                  f"BB: {bb_wins}-{bb_losses} ({hr:.1f}%) | "
                  f"Bankroll: {bankroll:+.1f}u | Model: v{model_version}")

    results = {
        'picks': all_picks,
        'predictions': all_predictions,
        'daily_summary': daily_summary,
        'retrain_log': retrain_log,
        'model_inventory': model_inventory,
        'filter_audit': dict(filter_audit),
        'bankroll': bankroll,
        'bb_record': (bb_wins, bb_losses),
        'ultra_record': (ultra_wins, ultra_losses),
    }

    if dyn_bl:
        results['dynamic_blacklist'] = dyn_bl.summary()

    return results


# =============================================================================
# ANALYSIS & REPORTING
# =============================================================================

def print_report(results: Dict, args):
    """Print comprehensive analysis report."""
    picks = results['picks']
    daily = results['daily_summary']
    bb_w, bb_l = results['bb_record']
    ultra_w, ultra_l = results['ultra_record']
    total = bb_w + bb_l
    hr = bb_w / total * 100 if total > 0 else 0

    print("\n" + "=" * 80)
    print("  MLB SEASON REPLAY — FULL RESULTS")
    print("=" * 80)

    # Overall
    total_staked = sum(p.get('stake', 1.0) for p in picks)
    print(f"\n{'─' * 40}")
    print(f"  OVERALL RECORD")
    print(f"{'─' * 40}")
    print(f"  Best Bets:  {bb_w}-{bb_l} ({hr:.1f}% HR)")
    print(f"  Bankroll:   {results['bankroll']:+.1f}u")
    print(f"  Total staked: {total_staked:.0f}u")
    print(f"  ROI:        {results['bankroll'] / total_staked * 100:.1f}%" if total_staked > 0 else "  ROI: N/A")
    print(f"  Avg picks/day: {total / len(daily):.1f}" if daily else "")

    # Ultra tier
    ultra_total = ultra_w + ultra_l
    if ultra_total > 0:
        ultra_hr = ultra_w / ultra_total * 100
        ultra_pnl = sum(p['pnl'] for p in picks if p.get('is_ultra'))
        print(f"\n{'─' * 40}")
        print(f"  ULTRA TIER")
        print(f"{'─' * 40}")
        print(f"  Record:    {ultra_w}-{ultra_l} ({ultra_hr:.1f}% HR)")
        print(f"  P&L:       {ultra_pnl:+.1f}u (at 2u/pick)")
        print(f"  Volume:    {ultra_total} picks ({ultra_total / total * 100:.0f}% of total)")

        # Non-ultra
        non_ultra_w = bb_w - ultra_w
        non_ultra_l = bb_l - ultra_l
        non_ultra_total = non_ultra_w + non_ultra_l
        if non_ultra_total > 0:
            non_ultra_hr = non_ultra_w / non_ultra_total * 100
            non_ultra_pnl = sum(p['pnl'] for p in picks if not p.get('is_ultra'))
            print(f"\n  Non-Ultra:  {non_ultra_w}-{non_ultra_l} ({non_ultra_hr:.1f}% HR)")
            print(f"  Non-Ultra P&L: {non_ultra_pnl:+.1f}u (at 1u/pick)")

    # Direction breakdown
    over_picks = [p for p in picks if p['recommendation'] == 'OVER']
    under_picks = [p for p in picks if p['recommendation'] == 'UNDER']
    print(f"\n{'─' * 40}")
    print(f"  DIRECTION BREAKDOWN")
    print(f"{'─' * 40}")
    if over_picks:
        ow = sum(p['correct'] for p in over_picks)
        print(f"  OVER:   {ow}-{len(over_picks)-ow} ({ow/len(over_picks)*100:.1f}% HR, N={len(over_picks)})")
    if under_picks:
        uw = sum(p['correct'] for p in under_picks)
        print(f"  UNDER:  {uw}-{len(under_picks)-uw} ({uw/len(under_picks)*100:.1f}% HR, N={len(under_picks)})")

    # Home vs Away breakdown
    home_picks = [p for p in picks if p.get('is_home')]
    away_picks = [p for p in picks if not p.get('is_home')]
    if home_picks and away_picks:
        print(f"\n{'─' * 40}")
        print(f"  HOME vs AWAY")
        print(f"{'─' * 40}")
        hw = sum(p['correct'] for p in home_picks)
        hp = sum(p['pnl'] for p in home_picks)
        print(f"  Home:   {hw}-{len(home_picks)-hw} ({hw/len(home_picks)*100:.1f}% HR, N={len(home_picks)}, P&L={hp:+.1f}u)")
        aw = sum(p['correct'] for p in away_picks)
        ap = sum(p['pnl'] for p in away_picks)
        print(f"  Away:   {aw}-{len(away_picks)-aw} ({aw/len(away_picks)*100:.1f}% HR, N={len(away_picks)}, P&L={ap:+.1f}u)")

        # Rescued breakdown
        rescued_picks = [p for p in picks if p.get('was_rescued')]
        if rescued_picks:
            rw = sum(p['correct'] for p in rescued_picks)
            rp = sum(p['pnl'] for p in rescued_picks)
            print(f"  Rescued: {rw}-{len(rescued_picks)-rw} ({rw/len(rescued_picks)*100:.1f}% HR, N={len(rescued_picks)}, P&L={rp:+.1f}u)")

    # Monthly breakdown
    picks_df = pd.DataFrame(picks)
    if len(picks_df) > 0:
        picks_df['month'] = pd.to_datetime(picks_df['game_date']).dt.to_period('M')
        print(f"\n{'─' * 40}")
        print(f"  MONTHLY BREAKDOWN")
        print(f"{'─' * 40}")
        print(f"  {'Month':>10} {'W-L':>8} {'HR%':>8} {'P&L':>8} {'Picks/Day':>10}")
        for month, grp in picks_df.groupby('month'):
            w = grp['correct'].sum()
            l = len(grp) - w
            h = w / len(grp) * 100
            pnl = grp['pnl'].sum()
            days = grp['game_date'].nunique()
            ppd = len(grp) / days if days > 0 else 0
            marker = " ***" if h < 55 else (" **" if h < 58 else "")
            print(f"  {str(month):>10} {w:>3}-{l:<3} {h:>7.1f}% {pnl:>+7.1f}u {ppd:>9.1f}{marker}")

    # Filter audit
    print(f"\n{'─' * 40}")
    print(f"  FILTER AUDIT (total blocked)")
    print(f"{'─' * 40}")
    for filt, count in sorted(results['filter_audit'].items(), key=lambda x: -x[1]):
        print(f"  {filt:<25} {count:>6}")

    # Dynamic blacklist report
    if 'dynamic_blacklist' in results:
        bl = results['dynamic_blacklist']
        print(f"\n{'─' * 40}")
        print(f"  DYNAMIC BLACKLIST")
        print(f"{'─' * 40}")
        print(f"  Pitchers suppressed:   {bl['pitchers_suppressed']}")
        print(f"  Suppression events:    {bl['suppression_events']}")
        if bl.get('pitcher_details'):
            print(f"\n  {'Pitcher':<25} {'Picks':>6} {'W-L':>8} {'HR%':>6} {'Periods':>8}")
            for pitcher, details in sorted(
                bl['pitcher_details'].items(),
                key=lambda x: x[1]['hr'],
            ):
                w = details['wins']
                l = details['total_picks'] - w
                n_periods = len(details.get('suppression_periods', []))
                print(f"  {pitcher:<25} {details['total_picks']:>6} "
                      f"{w:>3}-{l:<3} {details['hr']:>5.1f}% {n_periods:>8}")

    # Model inventory
    print(f"\n{'─' * 40}")
    print(f"  MODEL INVENTORY ({len(results['retrain_log'])} retrains)")
    print(f"{'─' * 40}")
    print(f"  {'Version':>8} {'Trained':>12} {'Samples':>8} {'Val MAE':>8}")
    for entry in results['retrain_log']:
        mae_str = f"{entry['val_mae']:.3f}" if entry.get('val_mae') else 'N/A'
        print(f"  v{entry['model_version']:>6} {entry['game_date']:>12} "
              f"{entry['train_samples']:>8} {mae_str:>8}")

    # Edge distribution
    if len(picks_df) > 0:
        print(f"\n{'─' * 40}")
        print(f"  EDGE CALIBRATION")
        print(f"{'─' * 40}")
        for lo, hi, label in [(0.5, 1.0, '0.5-1.0'), (1.0, 1.5, '1.0-1.5'),
                               (1.5, 2.0, '1.5-2.0')]:
            subset = picks_df[(picks_df['edge'].abs() >= lo) & (picks_df['edge'].abs() < hi)]
            if len(subset) > 0:
                w = subset['correct'].sum()
                print(f"  Edge {label}: {w}-{len(subset)-w} "
                      f"({w/len(subset)*100:.1f}% HR, N={len(subset)})")

    # Signal effectiveness
    if len(picks_df) > 0:
        print(f"\n{'─' * 40}")
        print(f"  SIGNAL EFFECTIVENESS (in selected picks)")
        print(f"{'─' * 40}")
        signal_stats = defaultdict(lambda: {'wins': 0, 'total': 0})
        for _, pick in picks_df.iterrows():
            for tag in pick.get('signal_tags', []):
                signal_stats[tag]['total'] += 1
                signal_stats[tag]['wins'] += pick['correct']

        print(f"  {'Signal':>30} {'W-L':>8} {'HR%':>8} {'N':>6}")
        for tag, stats in sorted(signal_stats.items(), key=lambda x: -x[1]['total']):
            w = stats['wins']
            n = stats['total']
            l = n - w
            h = w / n * 100 if n > 0 else 0
            print(f"  {tag:>30} {w:>3}-{l:<3} {h:>7.1f}% {n:>6}")

    # Pitcher performance (top and bottom)
    if len(picks_df) > 0:
        pitcher_stats = picks_df.groupby('pitcher_lookup').agg(
            wins=('correct', 'sum'),
            total=('correct', 'count'),
            avg_edge=('edge', lambda x: x.abs().mean()),
        )
        pitcher_stats['hr'] = pitcher_stats['wins'] / pitcher_stats['total'] * 100
        pitcher_stats = pitcher_stats[pitcher_stats['total'] >= 3]

        if len(pitcher_stats) > 0:
            print(f"\n{'─' * 40}")
            print(f"  TOP PITCHERS (N >= 3)")
            print(f"{'─' * 40}")
            top = pitcher_stats.nlargest(10, 'hr')
            for name, row in top.iterrows():
                print(f"  {name:<25} {int(row['wins'])}-{int(row['total']-row['wins'])} "
                      f"({row['hr']:.0f}% HR, edge={row['avg_edge']:.2f})")

            print(f"\n  WORST PITCHERS (N >= 3)")
            bottom = pitcher_stats.nsmallest(10, 'hr')
            for name, row in bottom.iterrows():
                print(f"  {name:<25} {int(row['wins'])}-{int(row['total']-row['wins'])} "
                      f"({row['hr']:.0f}% HR, edge={row['avg_edge']:.2f})")

    # Winning/losing day analysis
    if daily:
        daily_df = pd.DataFrame(daily)
        daily_df = daily_df[daily_df['picks'] > 0]
        winning = daily_df[daily_df['pnl'] > 0]
        losing = daily_df[daily_df['pnl'] < 0]
        push = daily_df[daily_df['pnl'] == 0]
        print(f"\n{'─' * 40}")
        print(f"  DAY ANALYSIS")
        print(f"{'─' * 40}")
        print(f"  Winning days:  {len(winning)} ({len(winning)/len(daily_df)*100:.0f}%)")
        print(f"  Losing days:   {len(losing)} ({len(losing)/len(daily_df)*100:.0f}%)")
        print(f"  Push days:     {len(push)} ({len(push)/len(daily_df)*100:.0f}%)")
        if len(winning) > 0:
            print(f"  Avg winning day P&L: {winning['pnl'].mean():+.1f}u")
        if len(losing) > 0:
            print(f"  Avg losing day P&L: {losing['pnl'].mean():+.1f}u")

        # Streak analysis
        streaks = []
        current_streak = 0
        for _, row in daily_df.iterrows():
            if row['pnl'] < 0:
                current_streak += 1
            else:
                if current_streak > 0:
                    streaks.append(current_streak)
                current_streak = 0
        if current_streak > 0:
            streaks.append(current_streak)
        if streaks:
            print(f"  Max losing streak: {max(streaks)} days")


def save_results(results: Dict, output_dir: Path):
    """Save all results to CSV/JSON files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Picks
    picks_df = pd.DataFrame(results['picks'])
    # Convert list columns for CSV
    if 'signal_tags' in picks_df.columns:
        picks_df['signal_tags'] = picks_df['signal_tags'].apply(
            lambda x: '|'.join(x) if isinstance(x, list) else str(x))
    if 'ultra_criteria' in picks_df.columns:
        picks_df['ultra_criteria'] = picks_df['ultra_criteria'].apply(
            lambda x: '|'.join(x) if isinstance(x, list) else str(x))
    picks_df.to_csv(output_dir / "best_bets_picks.csv", index=False)

    # All predictions
    preds_df = pd.DataFrame(results['predictions'])
    preds_df.to_csv(output_dir / "all_predictions.csv", index=False)

    # Daily summary
    daily_df = pd.DataFrame(results['daily_summary'])
    daily_df.to_csv(output_dir / "daily_summary.csv", index=False)

    # Retrain log
    retrain_df = pd.DataFrame(results['retrain_log'])
    retrain_df.to_csv(output_dir / "retrain_log.csv", index=False)

    # Model inventory
    inv_df = pd.DataFrame(results['model_inventory'])
    inv_df.to_csv(output_dir / "model_inventory.csv", index=False)

    # Summary JSON
    total_staked = sum(p.get('stake', 1.0) for p in results['picks'])
    summary = {
        'simulation_period': f"{results['daily_summary'][0]['game_date']} to "
                             f"{results['daily_summary'][-1]['game_date']}" if results['daily_summary'] else 'N/A',
        'total_picks': len(results['picks']),
        'total_predictions': len(results['predictions']),
        'total_staked': round(total_staked, 2),
        'retrains': len(results['retrain_log']),
        'bb_record': {'wins': results['bb_record'][0], 'losses': results['bb_record'][1],
                       'hr': round(results['bb_record'][0] / max(sum(results['bb_record']), 1) * 100, 2)},
        'ultra_record': {'wins': results['ultra_record'][0], 'losses': results['ultra_record'][1],
                          'hr': round(results['ultra_record'][0] / max(sum(results['ultra_record']), 1) * 100, 2)},
        'bankroll': round(results['bankroll'], 2),
        'roi_pct': round(results['bankroll'] / max(total_staked, 1) * 100, 2),
        'pnl_uses_actual_odds': True,
        'filter_audit': results['filter_audit'],
    }
    if 'dynamic_blacklist' in results:
        summary['dynamic_blacklist'] = results['dynamic_blacklist']
    with open(output_dir / "simulation_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\nResults saved to: {output_dir}")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    args = parse_args()

    print("=" * 80)
    print("  MLB FULL SEASON REPLAY")
    print("=" * 80)
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Config: {args.training_window}d window, {args.retrain_interval}d retrains")
    print(f"Edge floor: {args.edge_floor} K, Max picks/day: {args.max_picks}")
    print(f"UNDER enabled: {args.enable_under}")
    use_blacklist = getattr(args, 'use_blacklist', False)
    print(f"Blacklist: {'ENABLED (' + str(len(PITCHER_BLACKLIST)) + ' pitchers)' if use_blacklist else 'DISABLED'}")
    print(f"Dead features removed: {'NO' if args.include_dead_features else 'YES'}")
    if args.away_edge_floor > 0:
        print(f"Away edge floor: {args.away_edge_floor} K")
    if args.block_away_rescue:
        print(f"Away rescue: BLOCKED")
    if args.dynamic_blacklist:
        print(f"Dynamic blacklist: ON (HR < {args.bl_max_hr*100:.0f}% at N >= {args.bl_min_n})")
    print()

    # Compute earliest date needed (start_date minus training window buffer)
    sim_start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
    earliest_date = (sim_start_dt - timedelta(days=args.training_window + 30)).strftime("%Y-%m-%d")

    # Load data
    client = bigquery.Client(project=PROJECT_ID)
    df = load_data(client, earliest_date=earliest_date)

    # Select features
    if args.include_dead_features:
        feature_cols = [f for f in ALL_FEATURE_COLS_WITH_DEAD if f in df.columns]
    else:
        feature_cols = [f for f in FEATURE_COLS if f in df.columns]

    print(f"Using {len(feature_cols)} features")
    print()

    # Run replay
    sim_start = pd.Timestamp(args.start_date)
    sim_end = pd.Timestamp(args.end_date)

    results = run_replay(df, feature_cols, sim_start, sim_end, args)

    # Print report
    print_report(results, args)

    # Save results
    output_dir = Path(args.output_dir)
    save_results(results, output_dir)


if __name__ == "__main__":
    main()
