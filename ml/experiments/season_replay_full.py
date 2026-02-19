#!/usr/bin/env python3
"""
Full Season Replay with Multi-Model Retraining + Subset Simulation

Trains 6 model families every N days across a full season, applies subset
definitions to each model's predictions, and tracks per-subset performance.
Answers: "If we had been running all 6 models with biweekly retraining from
day 1, which subsets would have been most profitable?"

Models:
  V9 MAE        (33 features, MSE loss)
  V12-noveg MAE (50 features, MSE loss)
  V9 Q43        (33 features, Quantile:alpha=0.43)
  V9 Q45        (33 features, Quantile:alpha=0.45)
  V12 Q43       (50 features, Quantile:alpha=0.43)
  V12 Q45       (50 features, Quantile:alpha=0.45)

Usage:
    # Current season, 14-day cadence, all 6 models
    PYTHONPATH=. python ml/experiments/season_replay_full.py \
        --season-start 2025-11-04 --season-end 2026-02-17 --cadence 14

    # Last season
    PYTHONPATH=. python ml/experiments/season_replay_full.py \
        --season-start 2024-11-06 --season-end 2025-04-13 --cadence 14

    # Adaptive mode (adjusts direction/filters based on 28-day rolling lookback)
    PYTHONPATH=. python ml/experiments/season_replay_full.py \
        --season-start 2025-11-04 --season-end 2026-02-17 --cadence 14 \
        --adaptive --lookback-days 28

    # Rolling training window (56 days instead of expanding)
    PYTHONPATH=. python ml/experiments/season_replay_full.py \
        --season-start 2025-11-04 --season-end 2026-02-17 --cadence 14 \
        --rolling-train-days 56

    # Adaptive + rolling (full treatment)
    PYTHONPATH=. python ml/experiments/season_replay_full.py \
        --season-start 2025-11-04 --season-end 2026-02-17 --cadence 14 \
        --adaptive --lookback-days 28 --rolling-train-days 56 \
        --save-json ./replay_adaptive_rolling.json

Session 280-281 - Full Season Replay + Adaptive Mode
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
import numpy as np
import pandas as pd
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Optional, List, Dict, Tuple
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb

from shared.ml.feature_contract import (
    V9_CONTRACT,
    V12_NOVEG_CONTRACT,
    FEATURE_STORE_FEATURE_COUNT,
)
from shared.ml.training_data_loader import get_quality_where_clause

# Reuse core functions from season_walkforward
from ml.experiments.season_walkforward import (
    prepare_features,
    compute_pnl,
    compute_hit_rate,
    _train_val_split,
    DEFAULT_CATBOOST_PARAMS,
    STAKE,
    WIN_PAYOUT,
    BREAKEVEN_HR,
)

PROJECT_ID = "nba-props-platform"


# =============================================================================
# Model Family Definitions
# =============================================================================

MODEL_FAMILIES = {
    'v9': {
        'name': 'V9 MAE',
        'contract': V9_CONTRACT,
        'quantile_alpha': None,
    },
    'v12_noveg': {
        'name': 'V12 noveg MAE',
        'contract': V12_NOVEG_CONTRACT,
        'quantile_alpha': None,
    },
    'v9_q43': {
        'name': 'V9 Q43',
        'contract': V9_CONTRACT,
        'quantile_alpha': 0.43,
    },
    'v9_q45': {
        'name': 'V9 Q45',
        'contract': V9_CONTRACT,
        'quantile_alpha': 0.45,
    },
    'v12_noveg_q43': {
        'name': 'V12 Q43',
        'contract': V12_NOVEG_CONTRACT,
        'quantile_alpha': 0.43,
    },
    'v12_noveg_q45': {
        'name': 'V12 Q45',
        'contract': V12_NOVEG_CONTRACT,
        'quantile_alpha': 0.45,
    },
}


# =============================================================================
# Subset Definitions
# =============================================================================

@dataclass
class SubsetFilter:
    """Defines how to filter predictions into a named subset."""
    name: str
    min_edge: float = 3.0
    direction: Optional[str] = None   # 'OVER', 'UNDER', or None (both)
    top_n: Optional[int] = None       # Take top N by |edge| descending


SUBSET_DEFS: Dict[str, List[SubsetFilter]] = {
    'v9': [
        SubsetFilter('top_pick', min_edge=3.0, top_n=1),
        SubsetFilter('top_3', min_edge=3.0, top_n=3),
        SubsetFilter('top_5', min_edge=3.0, top_n=5),
        SubsetFilter('high_edge_over', min_edge=3.0, direction='OVER'),
        SubsetFilter('high_edge_all', min_edge=3.0),
        SubsetFilter('ultra_high_edge', min_edge=5.0),
        SubsetFilter('all_picks', min_edge=0.0),
    ],
    'v12_noveg': [
        SubsetFilter('nova_top_pick', min_edge=3.0, top_n=1),
        SubsetFilter('nova_top_3', min_edge=3.0, top_n=3),
        SubsetFilter('nova_top_5', min_edge=3.0, top_n=5),
        SubsetFilter('nova_high_edge_over', min_edge=3.0, direction='OVER'),
        SubsetFilter('nova_high_edge_all', min_edge=3.0),
        SubsetFilter('nova_ultra_high_edge', min_edge=5.0),
        SubsetFilter('nova_all_picks', min_edge=0.0),
    ],
    'v9_q43': [
        SubsetFilter('q43_under_top3', min_edge=3.0, direction='UNDER', top_n=3),
        SubsetFilter('q43_under_all', min_edge=3.0, direction='UNDER'),
        SubsetFilter('q43_all_picks', min_edge=0.0),
    ],
    'v9_q45': [
        SubsetFilter('q45_under_top3', min_edge=3.0, direction='UNDER', top_n=3),
        SubsetFilter('q45_all_picks', min_edge=0.0),
    ],
    'v12_noveg_q43': [
        SubsetFilter('nova_q43_under_top3', min_edge=3.0, direction='UNDER', top_n=3),
        SubsetFilter('nova_q43_under_all', min_edge=3.0, direction='UNDER'),
        SubsetFilter('nova_q43_all_picks', min_edge=0.0),
    ],
    'v12_noveg_q45': [
        SubsetFilter('nova_q45_under_top3', min_edge=3.0, direction='UNDER', top_n=3),
        SubsetFilter('nova_q45_all_picks', min_edge=0.0),
    ],
}


# =============================================================================
# Dimensional Analysis
# =============================================================================

@dataclass
class DimensionResult:
    """Accumulated results for one (model, dimension, category) triple."""
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    pnl: float = 0.0

    @property
    def picks(self):
        return self.wins + self.losses + self.pushes

    @property
    def graded(self):
        return self.wins + self.losses

    @property
    def hr(self):
        return round(self.wins / self.graded * 100, 1) if self.graded > 0 else None

    @property
    def roi(self):
        risked = self.graded * STAKE
        return round(self.pnl / risked * 100, 1) if risked > 0 else None


def grade_mask(preds, actuals, lines, mask):
    """Grade predictions within a boolean mask. Returns (wins, losses, pushes, pnl)."""
    if mask.sum() == 0:
        return 0, 0, 0, 0.0

    b_preds = preds[mask]
    b_actual = actuals[mask]
    b_lines = lines[mask]
    b_edges = b_preds - b_lines
    b_over = b_edges > 0

    wins_mask = ((b_actual > b_lines) & b_over) | ((b_actual < b_lines) & ~b_over)
    pushes_mask = b_actual == b_lines

    wins = int(wins_mask.sum())
    losses = int((~wins_mask & ~pushes_mask).sum())
    pushes = int(pushes_mask.sum())
    pnl = wins * WIN_PAYOUT - losses * STAKE

    return wins, losses, pushes, pnl


def _safe_feature(eval_df, col, default=0.0):
    """Safely extract a feature column as numpy array."""
    if col in eval_df.columns:
        return eval_df[col].fillna(default).values
    return np.full(len(eval_df), default)


def compute_dimensions(preds, actuals, lines, eval_df):
    """Compute all dimensional breakdowns.

    Returns dict of dimension_name -> {category_name: boolean_mask}.
    All masks are over the full prediction array (same length as preds).
    """
    edges = preds - lines
    abs_edges = np.abs(edges)
    edge3 = abs_edges >= 3  # base high-edge filter

    dimensions = {}

    # --- 1. Player Tier (by prop line as proxy for player importance) ---
    dimensions['Player Tier'] = {
        'Star (25+)': edge3 & (lines >= 25),
        'Starter (15-24.5)': edge3 & (lines >= 15) & (lines < 25),
        'Bench (<15)': edge3 & (lines < 15),
    }

    # --- 2. Direction ---
    dimensions['Direction'] = {
        'OVER': edges >= 3,
        'UNDER': edges <= -3,
    }

    # --- 3. Edge Buckets ---
    dimensions['Edge Bucket'] = {
        '3-4': (abs_edges >= 3) & (abs_edges < 4),
        '4-5': (abs_edges >= 4) & (abs_edges < 5),
        '5-7': (abs_edges >= 5) & (abs_edges < 7),
        '7+': abs_edges >= 7,
    }

    # --- 4. Tier x Direction ---
    dimensions['Tier x Direction'] = {
        'Star OVER': (lines >= 25) & (edges >= 3),
        'Star UNDER': (lines >= 25) & (edges <= -3),
        'Starter OVER': (lines >= 15) & (lines < 25) & (edges >= 3),
        'Starter UNDER': (lines >= 15) & (lines < 25) & (edges <= -3),
        'Bench OVER': (lines < 15) & (edges >= 3),
        'Bench UNDER': (lines < 15) & (edges <= -3),
    }

    # --- 5. Line Range (granular) ---
    dimensions['Line Range'] = {
        '5-9.5': edge3 & (lines >= 5) & (lines < 10),
        '10-14.5': edge3 & (lines >= 10) & (lines < 15),
        '15-19.5': edge3 & (lines >= 15) & (lines < 20),
        '20-24.5': edge3 & (lines >= 20) & (lines < 25),
        '25-29.5': edge3 & (lines >= 25) & (lines < 30),
        '30+': edge3 & (lines >= 30),
    }

    # --- 6. Feature-based signal simulations ---
    b2b = _safe_feature(eval_df, 'feature_16_value', 0.0)
    home = _safe_feature(eval_df, 'feature_15_value', 0.5)
    rest_adv = _safe_feature(eval_df, 'feature_9_value', 0.0)
    pts_std = _safe_feature(eval_df, 'feature_3_value', 5.0)
    pts_avg_5 = _safe_feature(eval_df, 'feature_0_value', 10.0)
    pts_avg_10 = _safe_feature(eval_df, 'feature_1_value', 10.0)
    pts_avg_season = _safe_feature(eval_df, 'feature_2_value', 10.0)
    fatigue = _safe_feature(eval_df, 'feature_5_value', 50.0)
    opp_def = _safe_feature(eval_df, 'feature_13_value', 112.0)

    # Safe division for hot/cold detection
    season_nz = np.where(pts_avg_season > 0, pts_avg_season, 1.0)

    # 3-pt features for bounce signal
    fg3_pct = _safe_feature(eval_df, 'feature_36_value', 0.35)  # 3pt% recent
    position_guard = _safe_feature(eval_df, 'feature_21_value', 0.0)  # guard indicator

    dimensions['Signal Simulation'] = {
        'bench_under': (lines < 15) & (edges <= -3),
        'b2b_fatigue': (b2b >= 0.5) & (abs_edges >= 3),
        'b2b_under': (b2b >= 0.5) & (edges <= -3),
        'b2b_fatigue_under': (b2b >= 0.5) & (edges <= -3) & (lines >= 15),
        'rest_advantage': (rest_adv > 0.5) & (abs_edges >= 3),
        'home_over': (home >= 0.5) & (edges >= 3),
        'away_under': (home < 0.5) & (edges <= -3),
        'volatile_under': (pts_std >= 6) & (edges <= -3),
        'hot_streak_over': (pts_avg_5 > season_nz * 1.15) & (edges >= 3),
        'cold_snap_over': (pts_avg_5 < season_nz * 0.85) & (edges >= 3),
        'high_fatigue_under': (fatigue >= 65) & (edges <= -3),
        'star_high_edge': (lines >= 25) & (abs_edges >= 5),
        'weak_def_over': (opp_def >= 115) & (edges >= 3),
        'strong_def_under': (opp_def <= 108) & (edges <= -3),
        'consistent_over': (pts_std <= 4) & (edges >= 3),
        'trending_up_over': (pts_avg_5 > pts_avg_10 * 1.05) & (edges >= 3),
        'trending_down_under': (pts_avg_5 < pts_avg_10 * 0.95) & (edges <= -3),
        # New: 3pt bounce (guards + home)
        '3pt_bounce_over': (fg3_pct < 0.30) & (home >= 0.5) & (edges >= 3),
        # New: home + bench combo
        'home_bench_over': (home >= 0.5) & (lines < 15) & (edges >= 3),
    }

    # --- 8. Smart Filters (what production BLOCKS) ---
    quality_score = _safe_feature(eval_df, 'feature_quality_score', 90.0)
    if 'feature_quality_score' not in eval_df.columns:
        quality_score = np.full(len(eval_df), 90.0)  # assume OK if missing
    else:
        quality_score = eval_df['feature_quality_score'].fillna(90.0).values

    relative_edge = np.where(lines > 0, abs_edges / lines, 0)

    sf_quality_block = quality_score < 85
    sf_bench_under_block = (edges < 0) & (lines < 12)
    sf_relative_edge_block = relative_edge >= 0.30
    sf_dead_zone_block = (lines >= 20) & (lines < 25)
    sf_any_block = sf_quality_block | sf_bench_under_block | sf_relative_edge_block

    dimensions['Smart Filter Impact'] = {
        'blocked_quality<85': edge3 & sf_quality_block,
        'blocked_bench_under_low': edge3 & sf_bench_under_block,
        'blocked_rel_edge>=30%': edge3 & sf_relative_edge_block,
        'blocked_dead_zone_20-24.5': edge3 & sf_dead_zone_block,
        'blocked_any_filter': edge3 & sf_any_block,
        'passed_all_filters': edge3 & ~sf_any_block,
        'passed_all+no_dead_zone': edge3 & ~sf_any_block & ~sf_dead_zone_block,
    }

    # --- 7. Confidence Tiers (composite) ---
    dimensions['Confidence Tier'] = {
        'Elite (edge 7+)': abs_edges >= 7,
        'Strong (5-7)': (abs_edges >= 5) & (abs_edges < 7),
        'Standard (3-5)': (abs_edges >= 3) & (abs_edges < 5),
        'Low (1-3)': (abs_edges >= 1) & (abs_edges < 3),
    }

    # --- 9. Day of Week ---
    if 'game_date' in eval_df.columns:
        dow = pd.to_datetime(eval_df['game_date']).dt.dayofweek.values  # 0=Mon
        dimensions['Day of Week'] = {
            'Mon': edge3 & (dow == 0),
            'Tue': edge3 & (dow == 1),
            'Wed': edge3 & (dow == 2),
            'Thu': edge3 & (dow == 3),
            'Fri': edge3 & (dow == 4),
            'Sat': edge3 & (dow == 5),
            'Sun': edge3 & (dow == 6),
        }

    # --- 10. Volatility Buckets ---
    dimensions['Volatility Bucket'] = {
        'Low (std<=5)': edge3 & (pts_std <= 5),
        'Med (std 5-7)': edge3 & (pts_std > 5) & (pts_std <= 7),
        'High (std 7-10)': edge3 & (pts_std > 7) & (pts_std <= 10),
        'VHigh (std 10+)': edge3 & (pts_std > 10),
    }

    # --- 11. Direction x Tier (actionable combos) ---
    dimensions['Direction x Tier'] = {
        'Star UNDER': (lines >= 25) & (edges <= -3),
        'Star OVER': (lines >= 25) & (edges >= 3),
        'Starter UNDER': (lines >= 15) & (lines < 25) & (edges <= -3),
        'Starter OVER': (lines >= 15) & (lines < 25) & (edges >= 3),
        'Bench OVER': (lines < 15) & (edges >= 3),
        'Bench UNDER': (lines < 15) & (edges <= -3),
    }

    # --- 12. Monthly ---
    if 'game_date' in eval_df.columns:
        months = pd.to_datetime(eval_df['game_date']).dt.month.values
        dimensions['Month'] = {
            'Nov': edge3 & (months == 11),
            'Dec': edge3 & (months == 12),
            'Jan': edge3 & (months == 1),
            'Feb': edge3 & (months == 2),
            'Mar': edge3 & (months == 3),
            'Apr': edge3 & (months == 4),
        }

    # --- 13. Opponent Defense Buckets ---
    dimensions['Opponent Defense'] = {
        'Elite (<106)': edge3 & (opp_def < 106),
        'Good (106-110)': edge3 & (opp_def >= 106) & (opp_def < 110),
        'Avg (110-114)': edge3 & (opp_def >= 110) & (opp_def < 114),
        'Weak (114-118)': edge3 & (opp_def >= 114) & (opp_def < 118),
        'Poor (118+)': edge3 & (opp_def >= 118),
    }

    # --- 14. Opponent Defense x Direction ---
    dimensions['Opp Def x Direction'] = {
        'Weak Def OVER': (opp_def >= 114) & (edges >= 3),
        'Weak Def UNDER': (opp_def >= 114) & (edges <= -3),
        'Strong Def OVER': (opp_def < 110) & (edges >= 3),
        'Strong Def UNDER': (opp_def < 110) & (edges <= -3),
    }

    # --- 15. Matchup Familiarity ---
    games_vs_opp = _safe_feature(eval_df, 'feature_30_value', 0.0)
    dimensions['Matchup Familiarity'] = {
        'New (<3 games)': edge3 & (games_vs_opp < 3),
        'Some (3-5)': edge3 & (games_vs_opp >= 3) & (games_vs_opp < 6),
        'Familiar (6+)': edge3 & (games_vs_opp >= 6),
    }

    # --- 16. Fatigue Buckets ---
    dimensions['Fatigue Level'] = {
        'Low (<40)': edge3 & (fatigue < 40),
        'Medium (40-60)': edge3 & (fatigue >= 40) & (fatigue < 60),
        'High (60-75)': edge3 & (fatigue >= 60) & (fatigue < 75),
        'Extreme (75+)': edge3 & (fatigue >= 75),
    }

    # --- 17. Fatigue x Direction ---
    dimensions['Fatigue x Direction'] = {
        'High Fatigue UNDER': (fatigue >= 60) & (edges <= -3),
        'High Fatigue OVER': (fatigue >= 60) & (edges >= 3),
        'Low Fatigue UNDER': (fatigue < 40) & (edges <= -3),
        'Low Fatigue OVER': (fatigue < 40) & (edges >= 3),
    }

    # --- 18. Rest Advantage ---
    dimensions['Rest Advantage'] = {
        'Disadvantage (<0)': edge3 & (rest_adv < 0),
        'Neutral (0)': edge3 & (rest_adv >= 0) & (rest_adv <= 0.1),
        'Advantage (0.5+)': edge3 & (rest_adv >= 0.5),
        'Big Advantage (1+)': edge3 & (rest_adv >= 1.0),
    }

    # --- 19. Home/Away x Direction ---
    dimensions['Location x Direction'] = {
        'Home OVER': (home >= 0.5) & (edges >= 3),
        'Home UNDER': (home >= 0.5) & (edges <= -3),
        'Away OVER': (home < 0.5) & (edges >= 3),
        'Away UNDER': (home < 0.5) & (edges <= -3),
    }

    # --- 20. Minutes Change (role stability) ---
    min_change = _safe_feature(eval_df, 'feature_12_value', 0.0)
    dimensions['Minutes Change'] = {
        'Rising (+3)': edge3 & (min_change >= 3),
        'Stable (-3 to +3)': edge3 & (min_change > -3) & (min_change < 3),
        'Declining (-3)': edge3 & (min_change <= -3),
    }

    # --- 21. Recent Trend x Direction ---
    trend = _safe_feature(eval_df, 'feature_11_value', 0.0)
    dimensions['Trend x Direction'] = {
        'Trending Up + OVER': (trend > 0.5) & (edges >= 3),
        'Trending Up + UNDER': (trend > 0.5) & (edges <= -3),
        'Trending Down + OVER': (trend < -0.5) & (edges >= 3),
        'Trending Down + UNDER': (trend < -0.5) & (edges <= -3),
        'Flat + edge3': (trend >= -0.5) & (trend <= 0.5) & edge3,
    }

    # --- 22. Vegas Line Movement ---
    line_move = _safe_feature(eval_df, 'feature_27_value', 0.0)
    dimensions['Vegas Line Move'] = {
        'Line moved up (1+)': edge3 & (line_move >= 1.0),
        'Line stable': edge3 & (line_move > -1.0) & (line_move < 1.0),
        'Line moved down (-1+)': edge3 & (line_move <= -1.0),
    }

    # --- 23. Vegas Move x Direction ---
    dimensions['Line Move x Direction'] = {
        'Line Up + OVER': (line_move >= 1.0) & (edges >= 3),
        'Line Up + UNDER': (line_move >= 1.0) & (edges <= -3),
        'Line Down + OVER': (line_move <= -1.0) & (edges >= 3),
        'Line Down + UNDER': (line_move <= -1.0) & (edges <= -3),
    }

    # =========================================================================
    # SESSION 285 — Player Archetype & Group Pattern Dimensions
    # =========================================================================

    # Load additional features for archetype slicing
    pct_three = _safe_feature(eval_df, 'feature_20_value', 0.30)
    pct_paint = _safe_feature(eval_df, 'feature_18_value', 0.35)
    pct_mid = _safe_feature(eval_df, 'feature_19_value', 0.15)
    usage_rate = _safe_feature(eval_df, 'feature_49_value', 20.0)
    pts_slope = _safe_feature(eval_df, 'feature_34_value', 0.0)
    star_out = _safe_feature(eval_df, 'feature_37_value', 0.0)
    min_avg = _safe_feature(eval_df, 'feature_31_value', 25.0)
    team_pace = _safe_feature(eval_df, 'feature_22_value', 100.0)
    multi_book_std = _safe_feature(eval_df, 'feature_50_value', 0.5)
    consec_below = _safe_feature(eval_df, 'feature_47_value', 0.0)
    pts_avg_3 = _safe_feature(eval_df, 'feature_43_value', 15.0)
    line_vs_avg = _safe_feature(eval_df, 'feature_53_value', 0.0)
    usage_spike = _safe_feature(eval_df, 'feature_8_value', 0.0)
    ppm = _safe_feature(eval_df, 'feature_32_value', 0.5)
    game_total = _safe_feature(eval_df, 'feature_38_value', 220.0)
    spread_mag = _safe_feature(eval_df, 'feature_41_value', 5.0)
    days_rest_f = _safe_feature(eval_df, 'feature_39_value', 1.0)
    breakout = _safe_feature(eval_df, 'feature_36_value', 0.0)

    # --- 24. Shooting Profile ---
    dimensions['Shooting Profile'] = {
        '3PT Heavy (>40%)': edge3 & (pct_three > 0.40),
        '3PT Moderate (25-40%)': edge3 & (pct_three >= 0.25) & (pct_three <= 0.40),
        'Paint Dominant (>45%)': edge3 & (pct_paint > 0.45),
        'Mid-Range Heavy (>25%)': edge3 & (pct_mid > 0.25),
        'Balanced': edge3 & (pct_three >= 0.20) & (pct_three <= 0.35) & (pct_paint >= 0.25) & (pct_paint <= 0.45),
    }

    # --- 25. Shooting Profile x Direction ---
    dimensions['Shot Profile x Direction'] = {
        '3PT Heavy OVER': (pct_three > 0.40) & (edges >= 3),
        '3PT Heavy UNDER': (pct_three > 0.40) & (edges <= -3),
        'Paint Dom OVER': (pct_paint > 0.45) & (edges >= 3),
        'Paint Dom UNDER': (pct_paint > 0.45) & (edges <= -3),
        'Balanced OVER': (pct_three >= 0.20) & (pct_three <= 0.35) & (pct_paint >= 0.25) & (edges >= 3),
        'Balanced UNDER': (pct_three >= 0.20) & (pct_three <= 0.35) & (pct_paint >= 0.25) & (edges <= -3),
    }

    # --- 26. Usage Rate Tiers ---
    dimensions['Usage Tier'] = {
        'High Usage (28%+)': edge3 & (usage_rate >= 28),
        'Medium Usage (20-28%)': edge3 & (usage_rate >= 20) & (usage_rate < 28),
        'Low Usage (<20%)': edge3 & (usage_rate < 20),
    }

    # --- 27. Usage x Direction ---
    dimensions['Usage x Direction'] = {
        'High Usage OVER': (usage_rate >= 28) & (edges >= 3),
        'High Usage UNDER': (usage_rate >= 28) & (edges <= -3),
        'Med Usage OVER': (usage_rate >= 20) & (usage_rate < 28) & (edges >= 3),
        'Med Usage UNDER': (usage_rate >= 20) & (usage_rate < 28) & (edges <= -3),
        'Low Usage OVER': (usage_rate < 20) & (edges >= 3),
        'Low Usage UNDER': (usage_rate < 20) & (edges <= -3),
    }

    # --- 28. Consistency Archetype ---
    dimensions['Consistency Archetype'] = {
        'Ultra Consistent (std<3)': edge3 & (pts_std < 3),
        'Consistent (std 3-5)': edge3 & (pts_std >= 3) & (pts_std < 5),
        'Average (std 5-7)': edge3 & (pts_std >= 5) & (pts_std < 7),
        'Volatile (std 7-10)': edge3 & (pts_std >= 7) & (pts_std < 10),
        'Wild Card (std 10+)': edge3 & (pts_std >= 10),
    }

    # --- 29. Consistency x Direction ---
    dimensions['Consistency x Direction'] = {
        'Consistent UNDER (std<5)': (pts_std < 5) & (edges <= -3),
        'Consistent OVER (std<5)': (pts_std < 5) & (edges >= 3),
        'Volatile UNDER (std>7)': (pts_std > 7) & (edges <= -3),
        'Volatile OVER (std>7)': (pts_std > 7) & (edges >= 3),
    }

    # --- 30. Star 3PT Shooter (line 25+ and 3PT heavy) ---
    star_3pt = (lines >= 25) & (pct_three > 0.35)
    dimensions['Star 3PT Archetype'] = {
        'Star 3PT OVER': star_3pt & (edges >= 3),
        'Star 3PT UNDER': star_3pt & (edges <= -3),
        'Star Non-3PT OVER': (lines >= 25) & (pct_three <= 0.35) & (edges >= 3),
        'Star Non-3PT UNDER': (lines >= 25) & (pct_three <= 0.35) & (edges <= -3),
    }

    # --- 31. Role Change / Minutes Trajectory ---
    dimensions['Role Trajectory'] = {
        'Rising Role OVER': (min_change >= 3) & (edges >= 3),
        'Rising Role UNDER': (min_change >= 3) & (edges <= -3),
        'Declining Role OVER': (min_change <= -3) & (edges >= 3),
        'Declining Role UNDER': (min_change <= -3) & (edges <= -3),
        'Stable High Min (30+)': edge3 & (min_avg >= 30) & (min_change > -3) & (min_change < 3),
        'Stable Low Min (<22)': edge3 & (min_avg < 22) & (min_change > -3) & (min_change < 3),
    }

    # --- 32. Star Teammate Out (opportunity) ---
    dimensions['Star Teammate Out'] = {
        'No Stars Out': edge3 & (star_out < 0.5),
        '1 Star Out': edge3 & (star_out >= 0.5) & (star_out < 1.5),
        '2+ Stars Out': edge3 & (star_out >= 1.5),
    }

    # --- 33. Star Out x Direction ---
    dimensions['Star Out x Direction'] = {
        '1+ Star Out OVER': (star_out >= 0.5) & (edges >= 3),
        '1+ Star Out UNDER': (star_out >= 0.5) & (edges <= -3),
        'No Stars Out OVER': (star_out < 0.5) & (edges >= 3),
        'No Stars Out UNDER': (star_out < 0.5) & (edges <= -3),
    }

    # --- 34. Team Pace x Usage ---
    fast_pace = team_pace >= 101
    slow_pace = team_pace < 98
    dimensions['Pace x Usage'] = {
        'Fast Pace + High Usage': edge3 & fast_pace & (usage_rate >= 28),
        'Fast Pace + Low Usage': edge3 & fast_pace & (usage_rate < 20),
        'Slow Pace + High Usage': edge3 & slow_pace & (usage_rate >= 28),
        'Slow Pace + Low Usage': edge3 & slow_pace & (usage_rate < 20),
    }

    # --- 35. Book Disagreement (multi-book line std) ---
    dimensions['Book Disagreement'] = {
        'Sharp Consensus (std<0.5)': edge3 & (multi_book_std < 0.5),
        'Mild Disagreement (0.5-1)': edge3 & (multi_book_std >= 0.5) & (multi_book_std < 1.0),
        'High Disagreement (1+)': edge3 & (multi_book_std >= 1.0),
    }

    # --- 36. Book Disagreement x Direction ---
    dimensions['Book Disagree x Direction'] = {
        'High Disagree OVER': (multi_book_std >= 1.0) & (edges >= 3),
        'High Disagree UNDER': (multi_book_std >= 1.0) & (edges <= -3),
        'Consensus OVER': (multi_book_std < 0.5) & (edges >= 3),
        'Consensus UNDER': (multi_book_std < 0.5) & (edges <= -3),
    }

    # --- 37. Cold Streak Length ---
    dimensions['Cold Streak'] = {
        'No Streak (0)': edge3 & (consec_below < 1),
        'Short Cold (1-2 games)': edge3 & (consec_below >= 1) & (consec_below < 3),
        'Extended Cold (3+)': edge3 & (consec_below >= 3),
    }

    # --- 38. Cold Streak x Direction ---
    dimensions['Cold Streak x Direction'] = {
        'Cold 3+ OVER (bounce)': (consec_below >= 3) & (edges >= 3),
        'Cold 3+ UNDER (continue)': (consec_below >= 3) & (edges <= -3),
        'Hot (0 below) OVER': (consec_below < 1) & (edges >= 3),
        'Hot (0 below) UNDER': (consec_below < 1) & (edges <= -3),
    }

    # --- 39. Line vs Season Average (market pricing) ---
    dimensions['Line vs Season Avg'] = {
        'Overpriced (line 3+ above avg)': edge3 & (line_vs_avg >= 3),
        'Fair (within 3)': edge3 & (line_vs_avg > -3) & (line_vs_avg < 3),
        'Underpriced (line 3+ below avg)': edge3 & (line_vs_avg <= -3),
    }

    # --- 40. Line Pricing x Direction ---
    dimensions['Line Pricing x Direction'] = {
        'Overpriced UNDER': (line_vs_avg >= 3) & (edges <= -3),
        'Overpriced OVER': (line_vs_avg >= 3) & (edges >= 3),
        'Underpriced OVER': (line_vs_avg <= -3) & (edges >= 3),
        'Underpriced UNDER': (line_vs_avg <= -3) & (edges <= -3),
    }

    # --- 41. Game Environment ---
    dimensions['Game Environment'] = {
        'High Total (228+)': edge3 & (game_total >= 228),
        'Normal Total (216-228)': edge3 & (game_total >= 216) & (game_total < 228),
        'Low Total (<216)': edge3 & (game_total < 216),
        'Blowout Spread (10+)': edge3 & (spread_mag >= 10),
        'Close Game (<4)': edge3 & (spread_mag < 4),
    }

    # --- 42. Game Environment x Direction ---
    dimensions['Game Env x Direction'] = {
        'High Total OVER': (game_total >= 228) & (edges >= 3),
        'High Total UNDER': (game_total >= 228) & (edges <= -3),
        'Low Total OVER': (game_total < 216) & (edges >= 3),
        'Low Total UNDER': (game_total < 216) & (edges <= -3),
        'Blowout UNDER': (spread_mag >= 10) & (edges <= -3),
        'Blowout OVER': (spread_mag >= 10) & (edges >= 3),
    }

    # --- 43. Efficiency Archetype (PPM = points per minute) ---
    dimensions['Efficiency'] = {
        'Elite Efficiency (ppm>0.7)': edge3 & (ppm > 0.7),
        'Good Efficiency (0.5-0.7)': edge3 & (ppm >= 0.5) & (ppm <= 0.7),
        'Low Efficiency (<0.5)': edge3 & (ppm < 0.5),
    }

    # --- 44. Compound Archetypes (multi-feature player groups) ---
    # Star + consistent + UNDER = highest conviction
    consistent_star_under = (lines >= 25) & (pts_std < 5) & (edges <= -3)
    # Bench + volatile + rising role
    volatile_bench_rising = (lines < 15) & (pts_std > 7) & (min_change >= 3)
    # High usage on fast team
    pace_usage_combo = (usage_rate >= 28) & (team_pace >= 101) & edge3
    # 3PT shooter vs weak defense
    shooter_vs_weak = (pct_three > 0.35) & (opp_def >= 114) & (edges >= 3)
    # Trending up + underpriced
    trending_underpriced = (pts_slope > 0.3) & (line_vs_avg <= -2) & (edges >= 3)
    # B2B + high fatigue + UNDER
    tired_under = (b2b >= 0.5) & (fatigue >= 60) & (edges <= -3)
    # Opportunity spike (star out + breakout flag)
    opportunity = (star_out >= 0.5) & (breakout >= 0.5) & edge3

    dimensions['Compound Archetypes'] = {
        'Consistent Star UNDER': consistent_star_under,
        'Volatile Bench Rising': volatile_bench_rising & edge3,
        'Pace+Usage Combo': pace_usage_combo,
        '3PT vs Weak Def OVER': shooter_vs_weak,
        'Trending Up + Underpriced': trending_underpriced,
        'Tired UNDER (B2B+Fatigue)': tired_under,
        'Opportunity Spike': opportunity,
    }

    # --- 45. Signal Combo Simulations ---
    # Combos of existing signals that might be synergistic
    bench_under_mask = (lines < 15) & (edges <= -3)
    rest_adv_mask = (rest_adv > 0.5) & edge3
    weak_def_mask = (opp_def >= 114) & (edges >= 3)
    strong_def_mask = (opp_def <= 108) & (edges <= -3)
    consistent_mask = (pts_std <= 4)
    volatile_mask = (pts_std >= 7)
    trending_up_mask = (pts_avg_5 > pts_avg_10 * 1.05) & (edges >= 3)

    dimensions['Signal Combos'] = {
        'bench_under + rest_adv': bench_under_mask & (rest_adv > 0.5),
        'bench_under + consistent': bench_under_mask & consistent_mask,
        'high_edge + weak_def': (abs_edges >= 5) & (opp_def >= 114),
        'high_edge + consistent': (abs_edges >= 5) & consistent_mask,
        'volatile + UNDER': volatile_mask & (edges <= -3),
        'volatile + strong_def UNDER': volatile_mask & strong_def_mask,
        'trending_up + weak_def': trending_up_mask & (opp_def >= 114),
        'rest_adv + OVER': (rest_adv > 0.5) & (edges >= 3),
        'b2b + strong_def UNDER': (b2b >= 0.5) & strong_def_mask,
        'consistent + home OVER': consistent_mask & (home >= 0.5) & (edges >= 3),
        '3pt_heavy + cold_snap OVER': (pct_three > 0.35) & (pts_avg_5 < season_nz * 0.85) & (edges >= 3),
        'star + high_edge UNDER': (lines >= 25) & (abs_edges >= 5) & (edges <= -3),
    }

    # --- 46. Points Per Minute x Tier ---
    dimensions['PPM x Tier'] = {
        'Star Elite PPM (>0.7)': (lines >= 25) & (ppm > 0.7) & edge3,
        'Star Low PPM (<0.6)': (lines >= 25) & (ppm < 0.6) & edge3,
        'Bench High PPM (>0.6)': (lines < 15) & (ppm > 0.6) & edge3,
        'Bench Low PPM (<0.4)': (lines < 15) & (ppm < 0.4) & edge3,
    }

    return dimensions


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ModelCycleResult:
    model_key: str
    model_name: str
    cycle_num: int
    train_start: str
    train_end: str
    eval_start: str
    eval_end: str
    train_n: int
    picks: int
    wins: int
    losses: int
    pushes: int
    hr: Optional[float]
    pnl: float
    mae: Optional[float]
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class SubsetCycleResult:
    subset_name: str
    cycle_num: int
    picks: int
    wins: int
    losses: int
    pushes: int
    hr: Optional[float]
    pnl: float


@dataclass
class SubsetSeasonResult:
    subset_name: str
    total_picks: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_pushes: int = 0
    total_hr: Optional[float] = None
    total_pnl: float = 0.0
    total_roi: Optional[float] = None
    cycle_results: list = field(default_factory=list)


# =============================================================================
# Core Logic
# =============================================================================

def apply_subset_filters(
    preds: np.ndarray,
    actuals: np.ndarray,
    lines: np.ndarray,
    subset_filters: List[SubsetFilter],
) -> Dict[str, Tuple[int, int, int, int, Optional[float], float]]:
    """Apply subset filters to predictions, grade each subset.

    Returns dict of subset_name -> (picks, wins, losses, pushes, hr, pnl).
    """
    edges = preds - lines
    abs_edges = np.abs(edges)
    results = {}

    for sf in subset_filters:
        # Edge threshold
        mask = abs_edges >= sf.min_edge

        # Direction filter
        if sf.direction == 'OVER':
            mask = mask & (edges > 0)
        elif sf.direction == 'UNDER':
            mask = mask & (edges < 0)

        if mask.sum() == 0:
            results[sf.name] = (0, 0, 0, 0, None, 0.0)
            continue

        # Top-N filter (by |edge| descending)
        if sf.top_n is not None and mask.sum() > sf.top_n:
            eligible_idx = np.where(mask)[0]
            top_idx = eligible_idx[np.argsort(-abs_edges[eligible_idx])[:sf.top_n]]
            new_mask = np.zeros(len(preds), dtype=bool)
            new_mask[top_idx] = True
            mask = new_mask

        # Grade
        b_actual = actuals[mask]
        b_lines = lines[mask]
        b_edges = edges[mask]
        b_over = b_edges > 0

        wins_mask = ((b_actual > b_lines) & b_over) | ((b_actual < b_lines) & ~b_over)
        pushes_mask = b_actual == b_lines

        wins = int(wins_mask.sum())
        losses = int((~wins_mask & ~pushes_mask).sum())
        pushes = int(pushes_mask.sum())
        picks = wins + losses + pushes

        graded = wins + losses
        hr = round(wins / graded * 100, 1) if graded > 0 else None
        pnl = wins * WIN_PAYOUT - losses * STAKE

        results[sf.name] = (picks, wins, losses, pushes, hr, pnl)

    return results



# Model family classification for cross-model subsets
QUANTILE_MODELS = {'v9_q43', 'v9_q45', 'v12_noveg_q43', 'v12_noveg_q45'}
MAE_MODELS = {'v9', 'v12_noveg'}
V9_FAMILY = {'v9', 'v9_q43', 'v9_q45'}
V12_FAMILY = {'v12_noveg', 'v12_noveg_q43', 'v12_noveg_q45'}


def compute_cross_model_consensus(
    cycle_predictions: Dict[str, Tuple[pd.DataFrame, np.ndarray]],
    min_edge: float = 3.0,
) -> Dict[str, Tuple[int, int, int, int, Optional[float], float]]:
    """Compute cross-model consensus subsets from multi-model predictions.

    Args:
        cycle_predictions: model_key -> (eval_df_reset, predictions_array)
        min_edge: minimum edge for a model to count as agreeing

    Returns dict of subset_name -> (picks, wins, losses, pushes, hr, pnl).
    """
    # Build per-player-game prediction map
    player_predictions: Dict[tuple, list] = {}

    for model_key, (eval_df, preds) in cycle_predictions.items():
        for i in range(len(eval_df)):
            row = eval_df.iloc[i]
            key = (str(row['player_lookup']), str(row['game_date'])[:10])
            pred = float(preds[i])
            line = float(row['vegas_line'])
            actual = float(row['actual_points'])
            edge = pred - line

            if key not in player_predictions:
                player_predictions[key] = []
            player_predictions[key].append({
                'model': model_key,
                'pred': pred,
                'line': line,
                'actual': actual,
                'edge': edge,
            })

    # Tally consensus subsets
    consensus_data = {
        'xm_consensus_3plus': {'wins': 0, 'losses': 0, 'pushes': 0},
        'xm_consensus_4plus': {'wins': 0, 'losses': 0, 'pushes': 0},
        'xm_quantile_agreement_under': {'wins': 0, 'losses': 0, 'pushes': 0},
        'xm_mae_plus_quantile_over': {'wins': 0, 'losses': 0, 'pushes': 0},
        'xm_diverse_agreement': {'wins': 0, 'losses': 0, 'pushes': 0},
    }

    active_models = set(cycle_predictions.keys())
    active_quantile = QUANTILE_MODELS & active_models

    for key, model_preds in player_predictions.items():
        if len(model_preds) < 2:
            continue

        actual = model_preds[0]['actual']
        line = model_preds[0]['line']

        def _outcome(direction):
            if actual == line:
                return 'pushes'
            if (direction == 'OVER' and actual > line) or \
               (direction == 'UNDER' and actual < line):
                return 'wins'
            return 'losses'

        over_count = sum(1 for mp in model_preds if mp['edge'] >= min_edge)
        under_count = sum(1 for mp in model_preds if mp['edge'] <= -min_edge)

        # --- xm_consensus_3plus / 5plus ---
        best_direction = None
        best_count = 0
        if over_count >= under_count and over_count >= 3:
            best_direction = 'OVER'
            best_count = over_count
        elif under_count > over_count and under_count >= 3:
            best_direction = 'UNDER'
            best_count = under_count

        if best_direction is not None:
            outcome = _outcome(best_direction)
            if best_count >= 3:
                consensus_data['xm_consensus_3plus'][outcome] += 1
            if best_count >= 4:
                consensus_data['xm_consensus_4plus'][outcome] += 1

        # --- xm_quantile_agreement_under ---
        # All 4 quantile models must be active and agree UNDER with edge >= min_edge
        if len(active_quantile) >= 4:
            q_preds = [mp for mp in model_preds if mp['model'] in QUANTILE_MODELS]
            if len(q_preds) == len(active_quantile):
                all_under = all(mp['edge'] <= -min_edge for mp in q_preds)
                if all_under:
                    consensus_data['xm_quantile_agreement_under'][_outcome('UNDER')] += 1

        # --- xm_mae_plus_quantile_over ---
        # Any MAE model says OVER + any quantile model confirms OVER
        mae_over = any(mp['edge'] >= min_edge for mp in model_preds
                       if mp['model'] in MAE_MODELS)
        quantile_over = any(mp['edge'] >= min_edge for mp in model_preds
                           if mp['model'] in QUANTILE_MODELS)
        if mae_over and quantile_over:
            consensus_data['xm_mae_plus_quantile_over'][_outcome('OVER')] += 1

        # --- xm_diverse_agreement ---
        # At least one V9-family + one V12-family agree on direction with edge >= min_edge
        v9_over = any(mp['edge'] >= min_edge for mp in model_preds
                      if mp['model'] in V9_FAMILY)
        v12_over = any(mp['edge'] >= min_edge for mp in model_preds
                       if mp['model'] in V12_FAMILY)
        v9_under = any(mp['edge'] <= -min_edge for mp in model_preds
                       if mp['model'] in V9_FAMILY)
        v12_under = any(mp['edge'] <= -min_edge for mp in model_preds
                        if mp['model'] in V12_FAMILY)
        if v9_over and v12_over:
            consensus_data['xm_diverse_agreement'][_outcome('OVER')] += 1
        elif v9_under and v12_under:
            consensus_data['xm_diverse_agreement'][_outcome('UNDER')] += 1

    results = {}
    for name, data in consensus_data.items():
        wins, losses, pushes = data['wins'], data['losses'], data['pushes']
        picks = wins + losses + pushes
        graded = wins + losses
        hr = round(wins / graded * 100, 1) if graded > 0 else None
        pnl = wins * WIN_PAYOUT - losses * STAKE
        results[name] = (picks, wins, losses, pushes, hr, pnl)

    return results


# =============================================================================
# Season Replay Engine
# =============================================================================

@dataclass
class AdaptiveConfig:
    """Thresholds for adaptive mode decisions."""
    over_include_threshold: float = 60.0   # Include OVER subsets if rolling HR >= this
    over_suppress_threshold: float = 50.0  # Suppress OVER if rolling HR < this
    under_include_threshold: float = 60.0
    under_suppress_threshold: float = 50.0
    filter_enable_threshold: float = 50.0  # Keep filter ON if blocked segment HR < this
    filter_disable_threshold: float = 58.0 # Turn filter OFF if blocked segment HR >= this
    model_weight_floor: float = 50.0       # Halve model weight if HR < this


@dataclass
class AdaptiveDecision:
    """Decisions made by adaptive mode for one cycle."""
    cycle_num: int
    include_over: bool = True
    include_under: bool = True
    disable_rel_edge_filter: bool = False
    model_weights: Dict[str, float] = field(default_factory=dict)
    reasoning: Dict[str, str] = field(default_factory=dict)


class FullSeasonReplay:
    """Multi-model season replay simulator."""

    def __init__(self, season_start: str, season_end: str,
                 cadence_days: int = 14, min_training_days: int = 28,
                 min_edge: float = 3.0, models: Optional[List[str]] = None,
                 lookback_days: int = 28, adaptive: bool = False,
                 rolling_train_days: Optional[int] = None,
                 warmup_days: int = 0,
                 skip_days: Optional[List[int]] = None,
                 eval_months: Optional[List[int]] = None,
                 min_pts_std: Optional[float] = None,
                 max_pts_std: Optional[float] = None,
                 tier_direction_rules: bool = False,
                 player_blacklist_hr: Optional[float] = None,
                 tier_models: bool = False,
                 under_only: bool = False,
                 min_line: Optional[float] = None,
                 max_line: Optional[float] = None,
                 no_rel_edge_filter: bool = False,
                 avoid_familiar: bool = False):
        self.season_start = season_start
        self.season_end = season_end
        self.cadence_days = cadence_days
        self.min_training_days = min_training_days
        self.min_edge = min_edge
        self.lookback_days = lookback_days
        self.adaptive = adaptive
        self.rolling_train_days = rolling_train_days
        # Experiment filters
        self.warmup_days = warmup_days  # Skip first N days of eval (Exp F)
        self.skip_days = skip_days or []  # Day-of-week to skip, 0=Mon (Exp B)
        self.eval_months = eval_months  # Only eval in these months (Exp A)
        self.min_pts_std = min_pts_std  # Min player volatility (Exp C)
        self.max_pts_std = max_pts_std  # Max player volatility (Exp C)
        self.tier_direction_rules = tier_direction_rules  # Exp D
        self.player_blacklist_hr = player_blacklist_hr  # Exp E threshold
        self.tier_models = tier_models  # Exp G: train per-tier models
        # Session 283 experiment filters
        self.under_only = under_only  # Exp H: UNDER picks only
        self.min_line = min_line  # Exp I: min prop line
        self.max_line = max_line  # Exp I: max prop line
        self.no_rel_edge_filter = no_rel_edge_filter  # Exp J: disable rel_edge>=30% filter
        self.avoid_familiar = avoid_familiar  # Exp K: skip players with 6+ games vs opponent

        if models:
            self.model_keys = [m for m in models if m in MODEL_FAMILIES]
        else:
            self.model_keys = list(MODEL_FAMILIES.keys())

        self.client = bigquery.Client(project=PROJECT_ID)
        self.train_df: Optional[pd.DataFrame] = None
        self.eval_df: Optional[pd.DataFrame] = None

        # Accumulated results
        self.model_cycle_results: List[ModelCycleResult] = []
        self.subset_season_results: Dict[str, SubsetSeasonResult] = {}
        # dim_results[(model_key, dim_name, cat_name)] -> DimensionResult
        self.dim_results: Dict[tuple, DimensionResult] = {}
        # Per-day decay: (model_key, model_age_days) -> DimensionResult
        self.decay_daily: Dict[tuple, DimensionResult] = {}
        # Edge sweep: (model_key, min_edge_threshold) -> DimensionResult
        self.edge_sweep: Dict[tuple, DimensionResult] = {}

        # Rolling lookback tracking: accumulated picks for rolling HR
        # List of dicts: {cycle_num, eval_date, subset_or_dim, direction, won, pnl, model_key}
        self.all_picks: List[dict] = []
        # rolling_health[(cycle_num, name)] -> {hr, n, pnl, direction_hr_over, direction_hr_under}
        self.rolling_health: Dict[tuple, dict] = {}
        # Adaptive decision log
        self.adaptive_log: Dict[int, AdaptiveDecision] = {}
        self.adaptive_config = AdaptiveConfig()
        # Player blacklist tracking: player_lookup -> {wins, losses}
        self.player_rolling: Dict[str, dict] = {}
        self.player_blacklist: set = set()
        # Experiment filter stats
        self.filter_stats: Dict[str, int] = {
            'warmup_skipped': 0, 'dow_skipped': 0, 'month_skipped': 0,
            'volatility_skipped': 0, 'tier_dir_skipped': 0, 'blacklist_skipped': 0,
        }

    def bulk_load_data(self):
        """Load all training + eval data in 2 bulk BQ queries."""
        quality_clause = get_quality_where_clause("mf")

        feature_value_columns = ',\n      '.join(
            f'mf.feature_{i}_value' for i in range(FEATURE_STORE_FEATURE_COUNT)
        )

        train_query = f"""
        SELECT
          mf.player_lookup,
          mf.game_date,
          {feature_value_columns},
          mf.feature_quality_score,
          mf.required_default_count,
          mf.default_feature_count,
          pgs.points as actual_points,
          pgs.minutes_played
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
          ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
        WHERE mf.game_date BETWEEN '{self.season_start}' AND '{self.season_end}'
          AND {quality_clause}
          AND pgs.points IS NOT NULL
          AND pgs.minutes_played > 0
        """

        eval_query = f"""
        WITH lines AS (
          SELECT game_date, player_lookup, points_line as line
          FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
          WHERE bookmaker = 'draftkings'
            AND game_date BETWEEN '{self.season_start}' AND '{self.season_end}'
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY game_date, player_lookup
            ORDER BY processed_at DESC
          ) = 1
        )
        SELECT
          mf.player_lookup,
          mf.game_date,
          {feature_value_columns},
          pgs.points as actual_points,
          l.line as vegas_line
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
          ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
        JOIN lines l
          ON mf.player_lookup = l.player_lookup AND mf.game_date = l.game_date
        WHERE mf.game_date BETWEEN '{self.season_start}' AND '{self.season_end}'
          AND {quality_clause}
          AND pgs.points IS NOT NULL
          AND (l.line - FLOOR(l.line)) IN (0, 0.5)
        """

        print(f"Loading training data ({self.season_start} to {self.season_end})...")
        self.train_df = self.client.query(train_query).to_dataframe()
        print(f"  -> {len(self.train_df):,} training records loaded")

        print(f"Loading eval data ({self.season_start} to {self.season_end})...")
        self.eval_df = self.client.query(eval_query).to_dataframe()
        print(f"  -> {len(self.eval_df):,} eval records loaded (with DK lines)")

        # Check V12 feature availability
        if 'feature_39_value' in self.eval_df.columns:
            non_null_pct = self.eval_df['feature_39_value'].notna().mean() * 100
            print(f"  V12 features: {non_null_pct:.0f}% populated"
                  f" ({'OK' if non_null_pct > 50 else 'SPARSE'})")

        self.train_df['game_date'] = pd.to_datetime(self.train_df['game_date'])
        self.eval_df['game_date'] = pd.to_datetime(self.eval_df['game_date'])

    def generate_cycles(self) -> List[Tuple[int, str, str, str, str]]:
        """Generate (cycle_num, train_start, train_end, eval_start, eval_end)."""
        season_start = date.fromisoformat(self.season_start)
        season_end = date.fromisoformat(self.season_end)
        cadence = timedelta(days=self.cadence_days)
        min_train = timedelta(days=self.min_training_days)

        first_eval_start = season_start + min_train
        cycles = []
        eval_start = first_eval_start
        cycle_num = 1

        while eval_start < season_end:
            eval_end = min(eval_start + cadence - timedelta(days=1), season_end)
            train_end = eval_start - timedelta(days=1)

            # Rolling training window: only use last N days
            if self.rolling_train_days is not None:
                train_start = max(
                    season_start,
                    train_end - timedelta(days=self.rolling_train_days - 1),
                )
            else:
                train_start = season_start  # Expanding window

            cycles.append((
                cycle_num,
                train_start.isoformat(),
                train_end.isoformat(),
                eval_start.isoformat(),
                eval_end.isoformat(),
            ))

            eval_start = eval_end + timedelta(days=1)
            cycle_num += 1

        return cycles

    def _slice(self, df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        return df[(df['game_date'] >= s) & (df['game_date'] <= e)]

    def _train_one_model(self, train_slice: pd.DataFrame, model_key: str):
        """Train a single model. Returns (model, skip_reason)."""
        family = MODEL_FAMILIES[model_key]
        contract = family['contract']

        if len(train_slice) < 500:
            return None, f"< 500 training records ({len(train_slice)})"

        X_train, y_train = prepare_features(train_slice, contract)
        X_tr, X_val, y_tr, y_val = _train_val_split(X_train, y_train, val_frac=0.15)

        params = DEFAULT_CATBOOST_PARAMS.copy()
        if family['quantile_alpha'] is not None:
            params['loss_function'] = f"Quantile:alpha={family['quantile_alpha']}"

        model = cb.CatBoostRegressor(**params)
        model.fit(X_tr, y_tr, eval_set=(X_val, y_val), verbose=0)
        return model, None

    def _accumulate_subset(self, subset_name: str, cycle_num: int,
                           picks: int, wins: int, losses: int,
                           pushes: int, hr: Optional[float], pnl: float):
        """Add a cycle's subset result to the season accumulator."""
        if subset_name not in self.subset_season_results:
            self.subset_season_results[subset_name] = SubsetSeasonResult(subset_name)
        ssr = self.subset_season_results[subset_name]
        ssr.total_picks += picks
        ssr.total_wins += wins
        ssr.total_losses += losses
        ssr.total_pushes += pushes
        ssr.total_pnl += pnl
        ssr.cycle_results.append(SubsetCycleResult(
            subset_name=subset_name, cycle_num=cycle_num,
            picks=picks, wins=wins, losses=losses, pushes=pushes, hr=hr, pnl=pnl,
        ))

    def _compute_rolling_health(self, cycle_num: int, eval_end_date: str):
        """Compute rolling HR over lookback window from accumulated picks.

        Populates self.rolling_health[(cycle_num, name)] for each subset/dimension.
        """
        cutoff = pd.Timestamp(eval_end_date) - pd.Timedelta(days=self.lookback_days)
        recent = [p for p in self.all_picks
                  if pd.Timestamp(p['eval_date']) >= cutoff]

        if not recent:
            return

        # Group by subset/dimension name
        groups: Dict[str, list] = {}
        for p in recent:
            name = p['name']
            if name not in groups:
                groups[name] = []
            groups[name].append(p)

        for name, picks in groups.items():
            wins = sum(1 for p in picks if p['won'])
            graded = sum(1 for p in picks if p['outcome'] != 'push')
            total_pnl = sum(p['pnl'] for p in picks)

            over_picks = [p for p in picks if p['direction'] == 'OVER' and p['outcome'] != 'push']
            under_picks = [p for p in picks if p['direction'] == 'UNDER' and p['outcome'] != 'push']

            over_hr = (sum(1 for p in over_picks if p['won']) / len(over_picks) * 100
                       if over_picks else None)
            under_hr = (sum(1 for p in under_picks if p['won']) / len(under_picks) * 100
                        if under_picks else None)

            self.rolling_health[(cycle_num, name)] = {
                'hr': round(wins / graded * 100, 1) if graded > 0 else None,
                'n': graded,
                'pnl': total_pnl,
                'direction_hr_over': round(over_hr, 1) if over_hr is not None else None,
                'direction_hr_under': round(under_hr, 1) if under_hr is not None else None,
            }

    def _make_adaptive_decision(self, cycle_num: int) -> AdaptiveDecision:
        """Based on rolling_health from prior cycles, decide what to adjust."""
        decision = AdaptiveDecision(cycle_num=cycle_num)
        cfg = self.adaptive_config

        # Find the most recent cycle_num that has rolling health data
        prev_cycle = cycle_num - 1
        if prev_cycle < 1:
            decision.reasoning['status'] = 'first cycle, no lookback data'
            return decision

        # --- 1. Direction gating ---
        # Look for 'Direction' dimension rolling health
        over_health = self.rolling_health.get((prev_cycle, 'Direction|OVER'))
        under_health = self.rolling_health.get((prev_cycle, 'Direction|UNDER'))

        if over_health and over_health['hr'] is not None:
            if over_health['hr'] >= cfg.over_include_threshold:
                decision.include_over = True
                decision.reasoning['over'] = f"INCLUDE (rolling HR {over_health['hr']:.1f}% >= {cfg.over_include_threshold}%)"
            elif over_health['hr'] < cfg.over_suppress_threshold:
                decision.include_over = False
                decision.reasoning['over'] = f"SUPPRESS (rolling HR {over_health['hr']:.1f}% < {cfg.over_suppress_threshold}%)"
            else:
                decision.reasoning['over'] = f"NEUTRAL (rolling HR {over_health['hr']:.1f}%)"

        if under_health and under_health['hr'] is not None:
            if under_health['hr'] >= cfg.under_include_threshold:
                decision.include_under = True
                decision.reasoning['under'] = f"INCLUDE (rolling HR {under_health['hr']:.1f}% >= {cfg.under_include_threshold}%)"
            elif under_health['hr'] < cfg.under_suppress_threshold:
                decision.include_under = False
                decision.reasoning['under'] = f"SUPPRESS (rolling HR {under_health['hr']:.1f}% < {cfg.under_suppress_threshold}%)"
            else:
                decision.reasoning['under'] = f"NEUTRAL (rolling HR {under_health['hr']:.1f}%)"

        # --- 2. Smart filter toggle (rel_edge >= 30%) ---
        rel_edge_health = self.rolling_health.get(
            (prev_cycle, 'Smart Filter Impact|blocked_rel_edge>=30%'))
        if rel_edge_health and rel_edge_health['hr'] is not None and rel_edge_health['n'] >= 10:
            if rel_edge_health['hr'] >= cfg.filter_disable_threshold:
                decision.disable_rel_edge_filter = True
                decision.reasoning['rel_edge_filter'] = (
                    f"DISABLE (blocked segment HR {rel_edge_health['hr']:.1f}% >= "
                    f"{cfg.filter_disable_threshold}%, N={rel_edge_health['n']})")
            elif rel_edge_health['hr'] < cfg.filter_enable_threshold:
                decision.disable_rel_edge_filter = False
                decision.reasoning['rel_edge_filter'] = (
                    f"KEEP (blocked segment HR {rel_edge_health['hr']:.1f}% < "
                    f"{cfg.filter_enable_threshold}%)")

        # --- 3. Model weighting ---
        for model_key in self.model_keys:
            model_health = self.rolling_health.get((prev_cycle, f'model|{model_key}'))
            if model_health and model_health['hr'] is not None and model_health['n'] >= 10:
                if model_health['hr'] < cfg.model_weight_floor:
                    decision.model_weights[model_key] = 0.5
                    decision.reasoning[f'model_{model_key}'] = (
                        f"HALVED (rolling HR {model_health['hr']:.1f}% < "
                        f"{cfg.model_weight_floor}%, N={model_health['n']})")
                else:
                    decision.model_weights[model_key] = 1.0
            else:
                decision.model_weights[model_key] = 1.0

        return decision

    def _record_picks(self, cycle_num: int, preds: np.ndarray,
                      actuals: np.ndarray, lines: np.ndarray,
                      eval_df: pd.DataFrame, model_key: str):
        """Record individual picks for rolling lookback computation."""
        edges = preds - lines
        abs_edges = np.abs(edges)
        eval_dates = eval_df['game_date'].values

        for i in range(len(preds)):
            if abs_edges[i] < self.min_edge:
                continue
            direction = 'OVER' if edges[i] > 0 else 'UNDER'
            actual_v = float(actuals[i])
            line_v = float(lines[i])
            if actual_v == line_v:
                outcome = 'push'
                won = False
                pick_pnl = 0.0
            elif (direction == 'OVER' and actual_v > line_v) or \
                 (direction == 'UNDER' and actual_v < line_v):
                outcome = 'win'
                won = True
                pick_pnl = WIN_PAYOUT
            else:
                outcome = 'loss'
                won = False
                pick_pnl = -STAKE

            eval_date = str(eval_dates[i])[:10]

            # Record for model-level rolling health
            self.all_picks.append({
                'cycle_num': cycle_num,
                'eval_date': eval_date,
                'name': f'model|{model_key}',
                'direction': direction,
                'won': won,
                'outcome': outcome,
                'pnl': pick_pnl,
            })

            # Record for direction dimension rolling health
            self.all_picks.append({
                'cycle_num': cycle_num,
                'eval_date': eval_date,
                'name': f'Direction|{direction}',
                'direction': direction,
                'won': won,
                'outcome': outcome,
                'pnl': pick_pnl,
            })

            # Record for smart filter dimensions
            rel_edge = abs_edges[i] / lines[i] if lines[i] > 0 else 0
            if rel_edge >= 0.30:
                self.all_picks.append({
                    'cycle_num': cycle_num,
                    'eval_date': eval_date,
                    'name': 'Smart Filter Impact|blocked_rel_edge>=30%',
                    'direction': direction,
                    'won': won,
                    'outcome': outcome,
                    'pnl': pick_pnl,
                })

    def _apply_eval_filters(self, preds: np.ndarray, actuals: np.ndarray,
                            lines: np.ndarray, eval_df: pd.DataFrame,
                            eval_start: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
        """Apply experiment filters (B-F) to eval predictions. Returns filtered arrays."""
        keep = np.ones(len(preds), dtype=bool)
        edges = preds - lines

        # F: Warmup — skip early eval days
        if self.warmup_days > 0:
            season_start_d = pd.Timestamp(self.season_start)
            warmup_end = season_start_d + pd.Timedelta(days=self.warmup_days)
            dates = pd.to_datetime(eval_df['game_date'])
            warmup_mask = dates < warmup_end
            n_skip = warmup_mask.sum()
            self.filter_stats['warmup_skipped'] += int(n_skip)
            keep &= ~warmup_mask

        # A: Eval months filter
        if self.eval_months:
            months = pd.to_datetime(eval_df['game_date']).dt.month.values
            month_mask = np.isin(months, self.eval_months)
            self.filter_stats['month_skipped'] += int((~month_mask & keep).sum())
            keep &= month_mask

        # B: Day-of-week skip
        if self.skip_days:
            dow = pd.to_datetime(eval_df['game_date']).dt.dayofweek.values
            dow_mask = ~np.isin(dow, self.skip_days)
            self.filter_stats['dow_skipped'] += int((~dow_mask & keep).sum())
            keep &= dow_mask

        # C: Volatility filter
        pts_std = _safe_feature(eval_df, 'feature_3_value', 5.0)
        if self.min_pts_std is not None:
            vol_mask = pts_std >= self.min_pts_std
            self.filter_stats['volatility_skipped'] += int((~vol_mask & keep).sum())
            keep &= vol_mask
        if self.max_pts_std is not None:
            vol_mask = pts_std <= self.max_pts_std
            self.filter_stats['volatility_skipped'] += int((~vol_mask & keep).sum())
            keep &= vol_mask

        # D: Tier x Direction rules (Star=UNDER only, Bench=OVER only)
        if self.tier_direction_rules:
            abs_edges = np.abs(edges)
            has_edge = abs_edges >= self.min_edge
            star_over = has_edge & (lines >= 25) & (edges > 0)
            bench_under = has_edge & (lines < 15) & (edges < 0)
            tier_block = star_over | bench_under
            self.filter_stats['tier_dir_skipped'] += int((tier_block & keep).sum())
            keep &= ~tier_block

        # E: Player blacklist
        if self.player_blacklist_hr is not None and self.player_blacklist:
            if 'player_lookup' in eval_df.columns:
                players = eval_df['player_lookup'].values
                bl_mask = np.array([p not in self.player_blacklist for p in players])
                self.filter_stats['blacklist_skipped'] += int((~bl_mask & keep).sum())
                keep &= bl_mask

        # H: UNDER-only mode
        if self.under_only:
            under_mask = edges <= 0  # Only keep UNDER predictions
            self.filter_stats['over_skipped'] = self.filter_stats.get('over_skipped', 0) + int((~under_mask & keep).sum())
            keep &= under_mask

        # I: Line range filter
        if self.min_line is not None:
            line_mask = lines >= self.min_line
            self.filter_stats['line_range_skipped'] = self.filter_stats.get('line_range_skipped', 0) + int((~line_mask & keep).sum())
            keep &= line_mask
        if self.max_line is not None:
            line_mask = lines <= self.max_line
            self.filter_stats['line_range_skipped'] = self.filter_stats.get('line_range_skipped', 0) + int((~line_mask & keep).sum())
            keep &= line_mask

        # K: Avoid familiar matchups (6+ games vs opponent)
        if self.avoid_familiar:
            games_vs = _safe_feature(eval_df, 'feature_30_value', 0.0)
            fam_mask = games_vs < 6
            self.filter_stats['familiar_skipped'] = self.filter_stats.get('familiar_skipped', 0) + int((~fam_mask & keep).sum())
            keep &= fam_mask

        if keep.all():
            return preds, actuals, lines, eval_df

        return preds[keep], actuals[keep], lines[keep], eval_df[keep].reset_index(drop=True)

    def _update_player_blacklist(self, preds: np.ndarray, actuals: np.ndarray,
                                  lines: np.ndarray, eval_df: pd.DataFrame):
        """Update per-player rolling HR and blacklist for next cycle."""
        if self.player_blacklist_hr is None:
            return
        if 'player_lookup' not in eval_df.columns:
            return

        edges = preds - lines
        abs_edges = np.abs(edges)
        players = eval_df['player_lookup'].values

        for i in range(len(preds)):
            if abs_edges[i] < self.min_edge:
                continue
            p = str(players[i])
            if p not in self.player_rolling:
                self.player_rolling[p] = {'wins': 0, 'losses': 0}
            pr = self.player_rolling[p]
            is_over = edges[i] > 0
            actual_v = float(actuals[i])
            line_v = float(lines[i])
            if actual_v == line_v:
                continue
            if (is_over and actual_v > line_v) or (not is_over and actual_v < line_v):
                pr['wins'] += 1
            else:
                pr['losses'] += 1

        # Rebuild blacklist
        self.player_blacklist = set()
        for p, pr in self.player_rolling.items():
            graded = pr['wins'] + pr['losses']
            if graded >= 8:
                hr_val = pr['wins'] / graded * 100
                if hr_val < self.player_blacklist_hr:
                    self.player_blacklist.add(p)

    def _train_tier_models(self, train_slice: pd.DataFrame, model_key: str):
        """Train separate models for Star/Starter/Bench tiers. Returns dict of tier -> model."""
        family = MODEL_FAMILIES[model_key]
        contract = family['contract']
        models = {}

        # Use feature_2_value (season avg points) as tier proxy in training data
        pts_avg = _safe_feature(train_slice, 'feature_2_value', 15.0)
        tier_masks = {
            'Star': pts_avg >= 22,
            'Starter': (pts_avg >= 12) & (pts_avg < 22),
            'Bench': pts_avg < 12,
        }

        for tier_name, mask in tier_masks.items():
            tier_slice = train_slice[mask]
            if len(tier_slice) < 300:
                models[tier_name] = None
                continue

            X_train, y_train = prepare_features(tier_slice, contract)
            X_tr, X_val, y_tr, y_val = _train_val_split(X_train, y_train, val_frac=0.15)

            params = DEFAULT_CATBOOST_PARAMS.copy()
            if family['quantile_alpha'] is not None:
                params['loss_function'] = f"Quantile:alpha={family['quantile_alpha']}"

            model = cb.CatBoostRegressor(**params)
            model.fit(X_tr, y_tr, eval_set=(X_val, y_val), verbose=0)
            models[tier_name] = model

        return models

    def run(self):
        """Run the full season replay."""
        self.bulk_load_data()
        cycles = self.generate_cycles()

        model_names = [MODEL_FAMILIES[k]['name'] for k in self.model_keys]
        mode_tags = []
        if self.adaptive:
            mode_tags.append(f"adaptive({self.lookback_days}d)")
        if self.rolling_train_days:
            mode_tags.append(f"rolling-train({self.rolling_train_days}d)")
        if self.warmup_days:
            mode_tags.append(f"warmup({self.warmup_days}d)")
        if self.skip_days:
            day_names = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
            mode_tags.append(f"skip-{','.join(day_names[d] for d in self.skip_days)}")
        if self.eval_months:
            mode_tags.append(f"months({','.join(str(m) for m in self.eval_months)})")
        if self.min_pts_std or self.max_pts_std:
            mode_tags.append(f"vol({self.min_pts_std or '*'}-{self.max_pts_std or '*'})")
        if self.tier_direction_rules:
            mode_tags.append("tier-dir-rules")
        if self.player_blacklist_hr:
            mode_tags.append(f"blacklist(<{self.player_blacklist_hr}%)")
        if self.tier_models:
            mode_tags.append("tier-models")
        mode_str = f" [{', '.join(mode_tags)}]" if mode_tags else ""

        print(f"\n{'='*70}")
        print(f"SEASON REPLAY: {self.season_start} -> {self.season_end} "
              f"({self.cadence_days}-day cadence){mode_str}")
        print(f"Models: {', '.join(model_names)}")
        print(f"Lookback: {self.lookback_days}d | Adaptive: {self.adaptive}"
              f" | Rolling train: {self.rolling_train_days or 'expanding'}")
        print(f"{'='*70}")

        for cycle_num, ts, te, es, ee in cycles:
            # Adaptive decision for this cycle
            adaptive_decision = None
            if self.adaptive:
                adaptive_decision = self._make_adaptive_decision(cycle_num)
                self.adaptive_log[cycle_num] = adaptive_decision
                if adaptive_decision.reasoning:
                    print(f"\n  ADAPTIVE decisions for cycle {cycle_num}:")
                    for key, reason in adaptive_decision.reasoning.items():
                        print(f"    {key}: {reason}")

            train_window = f"train {ts}->{te}"
            if self.rolling_train_days:
                train_window += f" ({self.rolling_train_days}d rolling)"
            print(f"\nCYCLE {cycle_num}: {train_window} | eval {es}->{ee}")

            train_slice = self._slice(self.train_df, ts, te)
            eval_slice = self._slice(self.eval_df, es, ee)

            if len(eval_slice) == 0:
                print("  No eval data -- skipping (All-Star break?)")
                continue

            cycle_predictions = {}  # model_key -> (eval_df_reset, preds)
            cycle_subset_results = {}  # subset_name -> (picks, wins, losses, pushes, hr, pnl)

            for model_key in self.model_keys:
                family = MODEL_FAMILIES[model_key]
                contract = family['contract']

                # Train model (tier-specific or standard)
                if self.tier_models:
                    tier_trained = self._train_tier_models(train_slice, model_key)
                    # Predict using tier-appropriate model
                    X_eval, y_eval = prepare_features(eval_slice, contract)
                    lines_raw = eval_slice['vegas_line'].astype(float).values
                    pts_avg_eval = _safe_feature(eval_slice, 'feature_2_value', 15.0)

                    preds = np.zeros(len(X_eval))
                    any_model = False
                    for i in range(len(X_eval)):
                        if pts_avg_eval[i] >= 22:
                            tier = 'Star'
                        elif pts_avg_eval[i] >= 12:
                            tier = 'Starter'
                        else:
                            tier = 'Bench'
                        m = tier_trained.get(tier)
                        if m is None:
                            # Fallback to any available model
                            m = next((v for v in tier_trained.values() if v is not None), None)
                        if m is not None:
                            preds[i] = m.predict(X_eval[i:i+1])[0]
                            any_model = True
                    if not any_model:
                        print(f"  {family['name']:14s}: SKIP -- no tier models trained")
                        continue
                    actuals = y_eval.values
                    lines = lines_raw
                else:
                    model, skip_reason = self._train_one_model(train_slice, model_key)
                    if model is None:
                        print(f"  {family['name']:14s}: SKIP -- {skip_reason}")
                        continue

                    X_eval, y_eval = prepare_features(eval_slice, contract)
                    preds = model.predict(X_eval)
                    actuals = y_eval.values
                    lines = eval_slice['vegas_line'].astype(float).values

                # Apply experiment filters (B-F)
                f_preds, f_actuals, f_lines, f_eval = self._apply_eval_filters(
                    preds, actuals, lines, eval_slice, es)

                cycle_predictions[model_key] = (
                    f_eval.reset_index(drop=True), f_preds
                )

                mae = round(mean_absolute_error(f_actuals, f_preds), 2)

                pnl, wins, losses, pushes, _, _, _, _ = compute_pnl(
                    f_preds, f_actuals, f_lines, self.min_edge
                )
                picks = wins + losses + pushes
                hr, _ = compute_hit_rate(f_preds, f_actuals, f_lines, self.min_edge)

                hr_str = f"{hr:.1f}%" if hr is not None else "N/A"
                print(f"  {family['name']:14s}: {picks:3d} picks, {hr_str:>6s} HR, "
                      f"${pnl:+,.0f}, MAE {mae}")

                self.model_cycle_results.append(ModelCycleResult(
                    model_key=model_key, model_name=family['name'],
                    cycle_num=cycle_num, train_start=ts, train_end=te,
                    eval_start=es, eval_end=ee, train_n=len(train_slice),
                    picks=picks, wins=wins, losses=losses, pushes=pushes,
                    hr=hr, pnl=pnl, mae=mae,
                ))

                # Record picks for rolling lookback (use filtered)
                self._record_picks(
                    cycle_num, f_preds, f_actuals, f_lines, f_eval, model_key)

                # Update player blacklist (use unfiltered to track all players)
                self._update_player_blacklist(preds, actuals, lines, eval_slice)

                # Per-model subset filters (adaptive direction gating, use filtered)
                if model_key in SUBSET_DEFS:
                    active_filters = SUBSET_DEFS[model_key]
                    if adaptive_decision:
                        active_filters = [
                            sf for sf in active_filters
                            if not (sf.direction == 'OVER' and not adaptive_decision.include_over)
                            and not (sf.direction == 'UNDER' and not adaptive_decision.include_under)
                        ]
                    sub_results = apply_subset_filters(
                        f_preds, f_actuals, f_lines, active_filters
                    )
                    cycle_subset_results.update(sub_results)

                # Dimensional analysis (use filtered)
                dims = compute_dimensions(f_preds, f_actuals, f_lines, f_eval)
                for dim_name, categories in dims.items():
                    for cat_name, mask in categories.items():
                        w, l, p, d_pnl = grade_mask(f_preds, f_actuals, f_lines, mask)
                        key = (model_key, dim_name, cat_name)
                        if key not in self.dim_results:
                            self.dim_results[key] = DimensionResult()
                        dr = self.dim_results[key]
                        dr.wins += w
                        dr.losses += l
                        dr.pushes += p
                        dr.pnl += d_pnl

                # Per-day decay tracking (use filtered)
                train_end_d = date.fromisoformat(te)
                eval_dates = f_eval['game_date'].dt.date.values
                edges = f_preds - f_lines
                abs_edges = np.abs(edges)
                for i in range(len(f_preds)):
                    if abs_edges[i] < self.min_edge:
                        continue
                    game_d = pd.Timestamp(eval_dates[i]).date()
                    age = (game_d - train_end_d).days
                    dk = (model_key, age)
                    if dk not in self.decay_daily:
                        self.decay_daily[dk] = DimensionResult()
                    dd = self.decay_daily[dk]
                    actual_v = float(f_actuals[i])
                    line_v = float(f_lines[i])
                    is_over = edges[i] > 0
                    if actual_v == line_v:
                        dd.pushes += 1
                    elif (is_over and actual_v > line_v) or (not is_over and actual_v < line_v):
                        dd.wins += 1
                        dd.pnl += WIN_PAYOUT
                    else:
                        dd.losses += 1
                        dd.pnl -= STAKE

                # Edge sweep (test thresholds 3, 4, 5)
                for threshold in [3.0, 4.0, 5.0]:
                    t_mask = abs_edges >= threshold
                    if t_mask.sum() == 0:
                        continue
                    w_s, l_s, p_s, pnl_s = grade_mask(f_preds, f_actuals, f_lines, t_mask)
                    ek = (model_key, threshold)
                    if ek not in self.edge_sweep:
                        self.edge_sweep[ek] = DimensionResult()
                    edr = self.edge_sweep[ek]
                    edr.wins += w_s
                    edr.losses += l_s
                    edr.pushes += p_s
                    edr.pnl += pnl_s

            # Cross-model consensus (need >= 2 models for diverse/mae+quantile subsets)
            if len(cycle_predictions) >= 2:
                xm_results = compute_cross_model_consensus(
                    cycle_predictions, self.min_edge
                )
                cycle_subset_results.update(xm_results)

            # Print subset breakdown for this cycle
            non_empty = {k: v for k, v in cycle_subset_results.items() if v[0] > 0}
            if non_empty:
                print(f"\n  Subset breakdown:")
                for sname, (sp, sw, sl, spu, shr, spnl) in sorted(
                    non_empty.items(), key=lambda x: -x[1][5]
                ):
                    shr_str = f"{shr:.1f}%" if shr is not None else "N/A"
                    print(f"    {sname:<24s}: {sw}-{sl}"
                          f" ({sp} picks), {shr_str:>6s} HR, ${spnl:+,.0f}")

            # Accumulate into season results
            for sname, (sp, sw, sl, spu, shr, spnl) in cycle_subset_results.items():
                self._accumulate_subset(sname, cycle_num, sp, sw, sl, spu, shr, spnl)

            # Compute rolling health at end of each cycle
            self._compute_rolling_health(cycle_num, ee)

        # Finalize season-level HR/ROI
        for ssr in self.subset_season_results.values():
            graded = ssr.total_wins + ssr.total_losses
            if graded > 0:
                ssr.total_hr = round(ssr.total_wins / graded * 100, 1)
                risked = graded * STAKE
                ssr.total_roi = round(ssr.total_pnl / risked * 100, 1) if risked > 0 else None

        # Print filter stats
        active_filters = {k: v for k, v in self.filter_stats.items() if v > 0}
        if active_filters:
            print(f"\n  Filter stats: {active_filters}")
        if self.player_blacklist:
            print(f"  Blacklisted players ({len(self.player_blacklist)}): "
                  f"{', '.join(sorted(self.player_blacklist)[:10])}"
                  f"{'...' if len(self.player_blacklist) > 10 else ''}")

        # Print summary reports
        self._print_subset_summary()
        self._print_model_summary()
        self._print_decay_analysis()
        self._print_daily_decay()
        self._print_edge_sweep()
        self._print_all_dimensions()

    # =========================================================================
    # Output Formatters
    # =========================================================================

    def _print_subset_summary(self):
        print(f"\n{'='*85}")
        print("SUBSET SEASON SUMMARY (sorted by P&L)")
        print(f"{'='*85}")

        header = (f"{'Subset':<26} | {'Picks':>5} | {'W-L':>9} | {'HR%':>6} | "
                  f"{'P&L':>9} | {'ROI':>7}")
        print(header)
        print("-" * len(header))

        sorted_subsets = sorted(
            self.subset_season_results.values(),
            key=lambda x: x.total_pnl, reverse=True,
        )

        for ssr in sorted_subsets:
            if ssr.total_picks == 0:
                continue
            hr = f"{ssr.total_hr:.1f}" if ssr.total_hr is not None else "N/A"
            roi = f"{ssr.total_roi:+.1f}" if ssr.total_roi is not None else "N/A"
            wl = f"{ssr.total_wins}-{ssr.total_losses}"
            print(f"{ssr.subset_name:<26} | {ssr.total_picks:>5} | {wl:>9} | "
                  f"{hr:>5}% | ${ssr.total_pnl:>+8,.0f} | {roi:>6}%")

        print("-" * len(header))
        print(f"Breakeven: {BREAKEVEN_HR}% | Stake: ${STAKE} | Win: ${WIN_PAYOUT}")

    def _print_model_summary(self):
        print(f"\n{'='*85}")
        print("MODEL SEASON SUMMARY (edge >= 3 only)")
        print(f"{'='*85}")

        header = (f"{'Model':<16} | {'Picks':>5} | {'W-L-P':>11} | {'HR%':>6} | "
                  f"{'P&L':>9} | {'ROI':>7} | {'Avg MAE':>7}")
        print(header)
        print("-" * len(header))

        for model_key in self.model_keys:
            cycles = [c for c in self.model_cycle_results
                      if c.model_key == model_key and not c.skipped]
            if not cycles:
                continue

            t_picks = sum(c.picks for c in cycles)
            t_wins = sum(c.wins for c in cycles)
            t_losses = sum(c.losses for c in cycles)
            t_pushes = sum(c.pushes for c in cycles)
            t_pnl = sum(c.pnl for c in cycles)
            maes = [c.mae for c in cycles if c.mae is not None]
            avg_mae = round(np.mean(maes), 2) if maes else None

            graded = t_wins + t_losses
            hr = round(t_wins / graded * 100, 1) if graded > 0 else None
            risked = graded * STAKE
            roi = round(t_pnl / risked * 100, 1) if risked > 0 else None

            name = MODEL_FAMILIES[model_key]['name']
            hr_str = f"{hr:.1f}" if hr is not None else "N/A"
            roi_str = f"{roi:+.1f}" if roi is not None else "N/A"
            mae_str = f"{avg_mae:.2f}" if avg_mae is not None else "N/A"
            wlp = f"{t_wins}-{t_losses}-{t_pushes}"

            print(f"{name:<16} | {t_picks:>5} | {wlp:>11} | {hr_str:>5}% | "
                  f"${t_pnl:>+8,.0f} | {roi_str:>6}% | {mae_str:>7}")

    def _print_decay_analysis(self):
        print(f"\n{'='*85}")
        print("DECAY ANALYSIS: Hit Rate by Model Age (edge >= 3)")
        print(f"{'='*85}")

        age_buckets = [
            ("0-7d", 0, 7),
            ("8-14d", 8, 14),
            ("15-21d", 15, 21),
            ("22-28d", 22, 28),
            ("29+d", 29, 999),
        ]

        header = f"{'Model':<16} | " + " | ".join(f"{b[0]:>12}" for b in age_buckets)
        print(header)
        print("-" * len(header))

        for model_key in self.model_keys:
            cycles = [c for c in self.model_cycle_results
                      if c.model_key == model_key and not c.skipped]
            bucket_data = {b[0]: {"wins": 0, "graded": 0} for b in age_buckets}

            for c in cycles:
                if c.picks == 0:
                    continue
                train_end_d = date.fromisoformat(str(c.train_end)[:10])
                eval_start_d = date.fromisoformat(str(c.eval_start)[:10])
                eval_end_d = date.fromisoformat(str(c.eval_end)[:10])
                avg_eval = eval_start_d + (eval_end_d - eval_start_d) / 2
                model_age = (avg_eval - train_end_d).days

                for bname, bmin, bmax in age_buckets:
                    if bmin <= model_age <= bmax:
                        bucket_data[bname]["wins"] += c.wins
                        bucket_data[bname]["graded"] += c.wins + c.losses
                        break

            parts = []
            for bname, _, _ in age_buckets:
                bd = bucket_data[bname]
                if bd["graded"] > 0:
                    hr_val = bd["wins"] / bd["graded"] * 100
                    parts.append(f"{hr_val:>5.1f}% ({bd['graded']:>3})")
                else:
                    parts.append(f"{'--':>12}")

            name = MODEL_FAMILIES[model_key]['name']
            print(f"{name:<16} | " + " | ".join(parts))

        print(f"\nBreakeven: {BREAKEVEN_HR}% (at -110 odds)")

    def _print_daily_decay(self):
        """Print per-day decay from actual game-level data."""
        print(f"\n{'='*85}")
        print("DAILY DECAY: Hit Rate by Exact Model Age (edge >= 3, per-pick)")
        print(f"{'='*85}")

        # Aggregate into weekly buckets from per-day data
        age_buckets = [
            ("Day 1-3", 1, 3),
            ("Day 4-7", 4, 7),
            ("Day 8-10", 8, 10),
            ("Day 11-14", 11, 14),
            ("Day 15-21", 15, 21),
            ("Day 22+", 22, 999),
        ]

        header = f"{'Model':<16} | " + " | ".join(f"{b[0]:>14}" for b in age_buckets)
        print(header)
        print("-" * len(header))

        for model_key in self.model_keys:
            bucket_data = {b[0]: DimensionResult() for b in age_buckets}
            for (mk, age), dr in self.decay_daily.items():
                if mk != model_key:
                    continue
                for bname, bmin, bmax in age_buckets:
                    if bmin <= age <= bmax:
                        bd = bucket_data[bname]
                        bd.wins += dr.wins
                        bd.losses += dr.losses
                        bd.pushes += dr.pushes
                        bd.pnl += dr.pnl
                        break

            parts = []
            for bname, _, _ in age_buckets:
                bd = bucket_data[bname]
                if bd.graded > 0:
                    parts.append(f"{bd.hr:>5.1f}% ({bd.graded:>4})")
                else:
                    parts.append(f"{'--':>14}")

            name = MODEL_FAMILIES[model_key]['name']
            print(f"{name:<16} | " + " | ".join(parts))

        # All models aggregate
        all_buckets = {b[0]: DimensionResult() for b in age_buckets}
        for (mk, age), dr in self.decay_daily.items():
            for bname, bmin, bmax in age_buckets:
                if bmin <= age <= bmax:
                    bd = all_buckets[bname]
                    bd.wins += dr.wins
                    bd.losses += dr.losses
                    bd.pushes += dr.pushes
                    bd.pnl += dr.pnl
                    break

        parts = []
        for bname, _, _ in age_buckets:
            bd = all_buckets[bname]
            if bd.graded > 0:
                parts.append(f"{bd.hr:>5.1f}% ({bd.graded:>4})")
            else:
                parts.append(f"{'--':>14}")
        print(f"{'ALL MODELS':<16} | " + " | ".join(parts))

        print(f"\nBreakeven: {BREAKEVEN_HR}%")

    def _print_edge_sweep(self):
        """Print HR/P&L at different edge thresholds per model."""
        print(f"\n{'='*85}")
        print("EDGE SWEEP: Performance at Different Minimum Edge Thresholds")
        print(f"{'='*85}")

        thresholds = [3.0, 4.0, 5.0]
        header = (f"{'Model':<16} | " +
                  " | ".join(f"{'Edge >= ' + str(t):^20}" for t in thresholds))
        print(header)
        sub = (f"{'':16} | " +
               " | ".join(f"{'Picks':>5} {'HR%':>5} {'P&L':>8}" for _ in thresholds))
        print(sub)
        print("-" * len(header))

        for model_key in self.model_keys:
            parts = []
            for t in thresholds:
                dr = self.edge_sweep.get((model_key, t))
                if dr and dr.graded > 0:
                    parts.append(f"{dr.picks:>5} {dr.hr:>5.1f} {dr.pnl:>+8.0f}")
                else:
                    parts.append(f"{'--':>5} {'--':>5} {'--':>8}")
            name = MODEL_FAMILIES[model_key]['name']
            print(f"{name:<16} | " + " | ".join(parts))

        print()

    # =========================================================================
    # Dimensional Analysis Output
    # =========================================================================

    def _print_dimension_table(self, dim_name: str, categories: List[str]):
        """Print one dimension table with models as columns."""
        print(f"\n{'='*100}")
        print(f"DIMENSION: {dim_name}")
        print(f"{'='*100}")

        # Build header
        model_names = [MODEL_FAMILIES[k]['name'] for k in self.model_keys]
        col_width = 18
        header = f"{'Category':<22} |"
        for mn in model_names:
            header += f" {mn:^{col_width}} |"
        print(header)

        sub_header = f"{'':22} |"
        for _ in model_names:
            sub_header += f" {'Picks':>5} {'HR%':>5} {'P&L':>6} |"
        print(sub_header)
        print("-" * len(header))

        for cat in categories:
            row = f"{cat:<22} |"
            for model_key in self.model_keys:
                key = (model_key, dim_name, cat)
                dr = self.dim_results.get(key)
                if dr and dr.graded > 0:
                    row += f" {dr.picks:>5} {dr.hr:>5.1f} {dr.pnl:>+6.0f} |"
                elif dr and dr.picks > 0:
                    row += f" {dr.picks:>5}   N/A {dr.pnl:>+6.0f} |"
                else:
                    row += f" {'--':>5} {'--':>5} {'--':>6} |"
            print(row)

        print("-" * len(header))

    def _print_signal_table(self):
        """Print signal simulation results ranked by aggregate HR."""
        print(f"\n{'='*100}")
        print("SIGNAL SIMULATION RESULTS (ranked by aggregate HR)")
        print(f"{'='*100}")

        # Get all signal categories
        signal_cats = set()
        for (mk, dn, cn) in self.dim_results:
            if dn == 'Signal Simulation':
                signal_cats.add(cn)

        if not signal_cats:
            print("  No signal data.")
            return

        # Compute aggregate stats per signal (across all models)
        signal_agg = {}
        for cat in signal_cats:
            total_w, total_l = 0, 0
            total_pnl = 0.0
            for model_key in self.model_keys:
                dr = self.dim_results.get((model_key, 'Signal Simulation', cat))
                if dr:
                    total_w += dr.wins
                    total_l += dr.losses
                    total_pnl += dr.pnl
            total_graded = total_w + total_l
            agg_hr = round(total_w / total_graded * 100, 1) if total_graded > 0 else 0
            signal_agg[cat] = (total_w + total_l, agg_hr, total_pnl)

        # Sort by aggregate HR descending
        sorted_signals = sorted(signal_agg.keys(),
                                key=lambda s: signal_agg[s][1], reverse=True)

        model_names = [MODEL_FAMILIES[k]['name'] for k in self.model_keys]
        col_width = 18
        header = f"{'Signal':<24} | {'Agg HR':>6} |"
        for mn in model_names:
            header += f" {mn:^{col_width}} |"
        print(header)

        sub_header = f"{'':24} | {'':>6} |"
        for _ in model_names:
            sub_header += f" {'Picks':>5} {'HR%':>5} {'P&L':>6} |"
        print(sub_header)
        print("-" * len(header))

        for cat in sorted_signals:
            agg_n, agg_hr, agg_pnl = signal_agg[cat]
            if agg_n == 0:
                continue

            hr_marker = " *" if agg_hr >= 60 else " +" if agg_hr >= BREAKEVEN_HR else "  "
            row = f"{cat:<24} | {agg_hr:>5.1f}%|"
            for model_key in self.model_keys:
                dr = self.dim_results.get((model_key, 'Signal Simulation', cat))
                if dr and dr.graded > 0:
                    row += f" {dr.picks:>5} {dr.hr:>5.1f} {dr.pnl:>+6.0f} |"
                elif dr and dr.picks > 0:
                    row += f" {dr.picks:>5}   N/A {dr.pnl:>+6.0f} |"
                else:
                    row += f" {'--':>5} {'--':>5} {'--':>6} |"
            print(row)

        print("-" * len(header))
        print(f"  * = HR >= 60%  |  + = above breakeven ({BREAKEVEN_HR}%)")

    def _print_all_dimensions(self):
        """Print all dimensional analysis tables."""
        # Collect unique dimensions and their categories (preserving order)
        dim_cats = {}
        for (mk, dn, cn) in self.dim_results:
            if dn not in dim_cats:
                dim_cats[dn] = []
            if cn not in dim_cats[dn]:
                dim_cats[dn].append(cn)

        # Print standard dimensions (not Signal Simulation)
        for dim_name in ['Player Tier', 'Direction', 'Edge Bucket',
                         'Confidence Tier', 'Tier x Direction', 'Line Range',
                         'Smart Filter Impact', 'Day of Week', 'Volatility Bucket',
                         'Direction x Tier', 'Month']:
            if dim_name in dim_cats:
                self._print_dimension_table(dim_name, dim_cats[dim_name])

        # Print signal table with special formatting
        if 'Signal Simulation' in dim_cats:
            self._print_signal_table()

    # =========================================================================
    # JSON Export
    # =========================================================================

    def to_json(self) -> dict:
        return {
            'config': {
                'season_start': self.season_start,
                'season_end': self.season_end,
                'cadence_days': self.cadence_days,
                'min_training_days': self.min_training_days,
                'min_edge': self.min_edge,
                'models': self.model_keys,
                'lookback_days': self.lookback_days,
                'adaptive': self.adaptive,
                'rolling_train_days': self.rolling_train_days,
                'warmup_days': self.warmup_days,
                'skip_days': self.skip_days,
                'eval_months': self.eval_months,
                'min_pts_std': self.min_pts_std,
                'max_pts_std': self.max_pts_std,
                'tier_direction_rules': self.tier_direction_rules,
                'player_blacklist_hr': self.player_blacklist_hr,
                'tier_models': self.tier_models,
                'filter_stats': self.filter_stats,
            },
            'model_cycles': [asdict(c) for c in self.model_cycle_results],
            'subset_results': {
                name: {
                    'total_picks': ssr.total_picks,
                    'total_wins': ssr.total_wins,
                    'total_losses': ssr.total_losses,
                    'total_pushes': ssr.total_pushes,
                    'total_hr': ssr.total_hr,
                    'total_pnl': ssr.total_pnl,
                    'total_roi': ssr.total_roi,
                    'cycles': [asdict(cr) for cr in ssr.cycle_results],
                }
                for name, ssr in self.subset_season_results.items()
            },
            'dimensions': {
                f"{mk}|{dn}|{cn}": {
                    'model': mk, 'dimension': dn, 'category': cn,
                    'wins': dr.wins, 'losses': dr.losses, 'pushes': dr.pushes,
                    'picks': dr.picks, 'hr': dr.hr, 'pnl': dr.pnl, 'roi': dr.roi,
                }
                for (mk, dn, cn), dr in self.dim_results.items()
            },
            'decay_daily': {
                f"{mk}|{age}": {
                    'model': mk, 'age_days': age,
                    'wins': dr.wins, 'losses': dr.losses, 'pushes': dr.pushes,
                    'picks': dr.picks, 'hr': dr.hr, 'pnl': dr.pnl,
                }
                for (mk, age), dr in self.decay_daily.items()
            },
            'edge_sweep': {
                f"{mk}|{threshold}": {
                    'model': mk, 'min_edge': threshold,
                    'wins': dr.wins, 'losses': dr.losses, 'pushes': dr.pushes,
                    'picks': dr.picks, 'hr': dr.hr, 'pnl': dr.pnl,
                }
                for (mk, threshold), dr in self.edge_sweep.items()
            },
            'rolling_health': {
                f"{cn}|{name}": health
                for (cn, name), health in self.rolling_health.items()
            },
            'adaptive_log': {
                str(cn): {
                    'cycle_num': d.cycle_num,
                    'include_over': d.include_over,
                    'include_under': d.include_under,
                    'disable_rel_edge_filter': d.disable_rel_edge_filter,
                    'model_weights': d.model_weights,
                    'reasoning': d.reasoning,
                }
                for cn, d in self.adaptive_log.items()
            },
        }


# =============================================================================
# CLI
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Full Season Replay with Multi-Model Retraining + Subset Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Current season, 14-day cadence, all 4 models
  PYTHONPATH=. python ml/experiments/season_replay_full.py \\
      --season-start 2025-11-04 --season-end 2026-02-12 --cadence 14

  # Last season
  PYTHONPATH=. python ml/experiments/season_replay_full.py \\
      --season-start 2024-11-06 --season-end 2025-04-13 --cadence 14

  # Just V9, 21-day cadence
  PYTHONPATH=. python ml/experiments/season_replay_full.py \\
      --season-start 2025-11-04 --season-end 2026-02-12 --cadence 21 --models v9

  # Save JSON
  PYTHONPATH=. python ml/experiments/season_replay_full.py \\
      --season-start 2025-11-04 --season-end 2026-02-12 --cadence 14 \\
      --save-json replay.json
        """,
    )
    parser.add_argument("--season-start", required=True,
                        help="Season start date (YYYY-MM-DD)")
    parser.add_argument("--season-end", required=True,
                        help="Season end date (YYYY-MM-DD)")
    parser.add_argument("--cadence", type=int, default=14,
                        help="Retrain cadence in days (default: 14)")
    parser.add_argument("--min-training-days", type=int, default=28,
                        help="Min training days before first model (default: 28)")
    parser.add_argument("--min-edge", type=float, default=3.0,
                        help="Min edge for model-level stats (default: 3.0)")
    parser.add_argument("--models", default=None,
                        help="Comma-separated model keys (default: all). "
                             "Options: v9,v12_noveg,v9_q43,v9_q45,v12_noveg_q43,v12_noveg_q45")
    parser.add_argument("--save-json", default=None,
                        help="Save results to JSON file")
    parser.add_argument("--lookback-days", type=int, default=28,
                        help="Rolling lookback window for health tracking (default: 28)")
    parser.add_argument("--adaptive", action="store_true",
                        help="Enable adaptive filter mode (adjusts direction/filters per cycle)")
    parser.add_argument("--rolling-train-days", type=int, default=None,
                        help="Rolling training window in days (default: None = expanding)")
    # Experiment filters
    parser.add_argument("--warmup-days", type=int, default=0,
                        help="Skip first N days of season for eval (Exp F)")
    parser.add_argument("--skip-days", default=None,
                        help="Comma-separated day-of-week to skip, 0=Mon (Exp B). E.g. '1,4' = skip Tue,Fri")
    parser.add_argument("--eval-months", default=None,
                        help="Comma-separated months to include (1=Jan). E.g. '1,2' = Jan+Feb only (Exp A)")
    parser.add_argument("--min-pts-std", type=float, default=None,
                        help="Min player points std dev (Exp C)")
    parser.add_argument("--max-pts-std", type=float, default=None,
                        help="Max player points std dev (Exp C)")
    parser.add_argument("--tier-direction-rules", action="store_true",
                        help="Star=UNDER only, Bench=OVER only (Exp D)")
    parser.add_argument("--player-blacklist-hr", type=float, default=None,
                        help="Blacklist players below this HR%% after 8+ picks (Exp E)")
    parser.add_argument("--tier-models", action="store_true",
                        help="Train separate models per player tier (Exp G)")
    # Session 283 experiment filters
    parser.add_argument("--under-only", action="store_true",
                        help="UNDER predictions only (Exp H)")
    parser.add_argument("--min-line", type=float, default=None,
                        help="Min prop line value (Exp I)")
    parser.add_argument("--max-line", type=float, default=None,
                        help="Max prop line value (Exp I)")
    parser.add_argument("--no-rel-edge-filter", action="store_true",
                        help="Disable rel_edge>=30%% smart filter in dimension tracking (Exp J)")
    parser.add_argument("--avoid-familiar", action="store_true",
                        help="Skip players with 6+ games vs opponent (Exp K)")

    return parser.parse_args()


def main():
    args = parse_args()

    models = args.models.split(",") if args.models else None

    skip_days = [int(d) for d in args.skip_days.split(",")] if args.skip_days else None
    eval_months = [int(m) for m in args.eval_months.split(",")] if args.eval_months else None

    replay = FullSeasonReplay(
        season_start=args.season_start,
        season_end=args.season_end,
        cadence_days=args.cadence,
        min_training_days=args.min_training_days,
        min_edge=args.min_edge,
        models=models,
        lookback_days=args.lookback_days,
        adaptive=args.adaptive,
        rolling_train_days=args.rolling_train_days,
        warmup_days=args.warmup_days,
        skip_days=skip_days,
        eval_months=eval_months,
        min_pts_std=args.min_pts_std,
        max_pts_std=args.max_pts_std,
        tier_direction_rules=args.tier_direction_rules,
        player_blacklist_hr=args.player_blacklist_hr,
        tier_models=args.tier_models,
        under_only=args.under_only,
        min_line=args.min_line,
        max_line=args.max_line,
        no_rel_edge_filter=args.no_rel_edge_filter,
        avoid_familiar=args.avoid_familiar,
    )

    replay.run()

    if args.save_json:
        with open(args.save_json, 'w') as f:
            json.dump(replay.to_json(), f, indent=2, default=str)
        print(f"\nResults saved to {args.save_json}")

    print("\nDone.")


if __name__ == "__main__":
    main()
