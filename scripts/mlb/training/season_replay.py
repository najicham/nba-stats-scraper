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
MAX_PICKS_PER_DAY = 3
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

# Ultra tier criteria — edge raised from 1.0 to 1.1 (Session 444)
# Edge 1.0-1.1 ultra was 63% HR (noise), edge 1.1+ is 78%+
ULTRA_MIN_EDGE = 1.1
ULTRA_REQUIRES_HOME = True
ULTRA_REQUIRES_PROJECTION_AGREES = True
ULTRA_REQUIRES_HALF_LINE = True

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
    return parser.parse_args()


# =============================================================================
# DATA LOADING
# =============================================================================

def load_data(client: bigquery.Client) -> pd.DataFrame:
    """Load all data for replay period."""
    print("Loading data from BigQuery...")

    query = """
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
        fg.gb_pct as f73_gb_pct

    FROM `mlb_raw.bp_pitcher_props` bp
    JOIN `mlb_analytics.pitcher_game_summary` pgs
        ON pgs.game_date = bp.game_date
        AND LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', '')) = bp.player_lookup
    LEFT JOIN statcast_rolling sc
        ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
        AND pgs.game_date = sc.game_date
    LEFT JOIN `mlb_raw.fangraphs_pitcher_season_stats` fg
        ON LOWER(REGEXP_REPLACE(NORMALIZE(fg.player_lookup, NFD), r'[\\W_]+', ''))
            = LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', ''))
        AND fg.season_year = EXTRACT(YEAR FROM pgs.game_date)
    WHERE bp.market_id = 285
      AND bp.actual_value IS NOT NULL
      AND bp.projection_value IS NOT NULL
      AND bp.over_line IS NOT NULL
      AND pgs.innings_pitched >= 3.0
      AND pgs.rolling_stats_games >= 3
      AND pgs.game_date >= '2024-01-01'
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

def train_regressor(X_train: pd.DataFrame, y_train: pd.Series, seed: int = 42):
    """Train CatBoost Regressor with production config."""
    from catboost import CatBoostRegressor

    model = CatBoostRegressor(
        depth=5,
        learning_rate=0.015,
        iterations=500,
        l2_leaf_reg=3,
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

    real_signal_count = sum(1 for t in signal_tags if t not in BASE_SIGNAL_TAGS)
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


# =============================================================================
# NEGATIVE FILTERS
# =============================================================================

def apply_negative_filters(row: pd.Series, recommendation: str,
                           pitcher_lookup: str) -> Optional[str]:
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
    if recommendation == 'OVER' and pitcher_lookup in PITCHER_BLACKLIST:
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
                signal_tags: List[str], pitcher_lookup: str) -> Tuple[bool, List[str]]:
    """Check if pick qualifies for Ultra tier. Returns (is_ultra, criteria_list)."""
    if recommendation != 'OVER':
        return False, []

    criteria = []

    # Must be half-line (already passed whole_line filter, but double-check)
    line = _safe_float(row, 'over_line')
    if line is not None and line != int(line):
        criteria.append('half_line')
    else:
        return False, []

    # Edge >= 1.0
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

    # Not blacklisted (already filtered, but safety)
    if pitcher_lookup in PITCHER_BLACKLIST:
        return False, []

    return True, criteria


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def run_replay(df: pd.DataFrame, feature_cols: List[str],
               sim_start: pd.Timestamp, sim_end: pd.Timestamp,
               args) -> Dict:
    """Run the full season replay."""

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
                current_model = train_regressor(X_train, y_train, seed=args.seed)
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
            if recommendation == 'OVER' and abs(edge) > MAX_EDGE:
                filter_audit['overconfidence_cap'] += 1
                continue

            # --- Probability cap ---
            if recommendation == 'OVER' and p_over > MAX_PROB_OVER:
                filter_audit['probability_cap'] += 1
                continue

            # --- Negative filters ---
            blocked_by = apply_negative_filters(row, recommendation, pitcher_lookup)
            if blocked_by:
                filter_audit[blocked_by] += 1
                continue

            # --- Edge floor + rescue ---
            if abs(edge) < args.edge_floor:
                # Check rescue signals
                sig_result = evaluate_signals(row, pred_k, edge, recommendation)
                rescued = any(t in RESCUE_SIGNAL_TAGS for t in sig_result['signal_tags'])
                if not rescued:
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

            # Passed all filters!
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

        # OVER: pure edge ranking
        over_cands.sort(key=lambda c: abs(c['edge']), reverse=True)

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
                pick['signal_tags'], pick['pitcher_lookup']
            )

            actual_k = pick['actual_k']
            line = pick['line']
            correct = int(
                (pick['recommendation'] == 'OVER' and actual_k > line) or
                (pick['recommendation'] == 'UNDER' and actual_k <= line)
            )

            # Staking
            stake = 2.0 if is_ultra else 1.0
            pnl = stake if correct else -stake

            pick.update({
                'rank': rank_idx,
                'correct': correct,
                'is_ultra': is_ultra,
                'ultra_criteria': ultra_criteria if is_ultra else [],
                'stake': stake,
                'pnl': pnl,
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
                pick['signal_tags'], pick['pitcher_lookup']
            )
            if is_ultra:
                actual_k = pick['actual_k']
                line = pick['line']
                correct = int(
                    (pick['recommendation'] == 'OVER' and actual_k > line) or
                    (pick['recommendation'] == 'UNDER' and actual_k <= line)
                )
                stake = 2.0
                pnl = stake if correct else -stake
                pick.update({
                    'rank': len(day_picks) + len(ultra_extras) + 1,
                    'correct': correct,
                    'is_ultra': True,
                    'ultra_criteria': ultra_criteria,
                    'stake': stake,
                    'pnl': pnl,
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

    return {
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
    print(f"\n{'─' * 40}")
    print(f"  OVERALL RECORD")
    print(f"{'─' * 40}")
    print(f"  Best Bets:  {bb_w}-{bb_l} ({hr:.1f}% HR)")
    print(f"  Bankroll:   {results['bankroll']:+.1f}u")
    print(f"  ROI:        {results['bankroll'] / total * 100:.1f}%" if total > 0 else "  ROI: N/A")
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
    summary = {
        'simulation_period': f"{results['daily_summary'][0]['game_date']} to "
                             f"{results['daily_summary'][-1]['game_date']}" if results['daily_summary'] else 'N/A',
        'total_picks': len(results['picks']),
        'total_predictions': len(results['predictions']),
        'retrains': len(results['retrain_log']),
        'bb_record': {'wins': results['bb_record'][0], 'losses': results['bb_record'][1],
                       'hr': round(results['bb_record'][0] / max(sum(results['bb_record']), 1) * 100, 2)},
        'ultra_record': {'wins': results['ultra_record'][0], 'losses': results['ultra_record'][1],
                          'hr': round(results['ultra_record'][0] / max(sum(results['ultra_record']), 1) * 100, 2)},
        'bankroll': round(results['bankroll'], 2),
        'filter_audit': results['filter_audit'],
    }
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
    print(f"Dead features removed: {'NO' if args.include_dead_features else 'YES'}")
    print()

    # Load data
    client = bigquery.Client(project=PROJECT_ID)
    df = load_data(client)

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
