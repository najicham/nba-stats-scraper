#!/usr/bin/env python3
"""
Walk-Forward Season Simulator

Empirically determines optimal retrain cadence and training window strategy
by simulating "train → evaluate → retrain → repeat" across a full season.

V9's decay curve shows ~2.5 weeks of profitable edge 3+ performance (62.5%),
then breakeven by week 3, then losses. This tool answers: what cadence and
window type maximizes season-long ROI?

Usage:
    # Compare retrain cadences (expanding window)
    PYTHONPATH=. python ml/experiments/season_walkforward.py \
        --season-start 2025-11-02 --season-end 2026-02-12 \
        --cadences 14,21,28,42 --window-type expanding

    # Test with pre-season bootstrap
    PYTHONPATH=. python ml/experiments/season_walkforward.py \
        --season-start 2025-11-02 --season-end 2026-02-12 \
        --cadences 14,28 --pre-season-start 2024-10-22 --pre-season-end 2025-04-13

    # Compare expanding vs rolling
    PYTHONPATH=. python ml/experiments/season_walkforward.py \
        --season-start 2025-11-02 --season-end 2026-02-12 \
        --cadences 14,28 --window-type both --rolling-windows 56

    # Quick test
    PYTHONPATH=. python ml/experiments/season_walkforward.py \
        --season-start 2025-12-01 --season-end 2026-02-12 \
        --cadences 14 --window-type expanding --min-training-days 21

Session 271 - Walk-Forward Season Simulator
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
from typing import Optional
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb

from shared.ml.feature_contract import (
    V9_CONTRACT,
    FEATURE_STORE_NAMES,
    FEATURE_STORE_FEATURE_COUNT,
    FEATURE_DEFAULTS,
    get_contract,
)
from shared.ml.training_data_loader import get_quality_where_clause

PROJECT_ID = "nba-props-platform"

# Frozen CatBoost hyperparameters (same as quick_retrain.py defaults)
DEFAULT_CATBOOST_PARAMS = {
    'iterations': 1000,
    'learning_rate': 0.05,
    'depth': 6,
    'l2_leaf_reg': 3,
    'random_seed': 42,
    'verbose': 0,
    'early_stopping_rounds': 50,
}

# Betting economics
STAKE = 110  # Risk $110 to win $100 at -110 odds
WIN_PAYOUT = 100
BREAKEVEN_HR = 52.4


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class StrategyConfig:
    name: str
    cadence_days: int
    window_type: str  # "expanding" or "rolling"
    rolling_window_days: Optional[int] = None
    min_training_days: int = 28
    pre_season_start: Optional[str] = None
    pre_season_end: Optional[str] = None


@dataclass
class CycleResult:
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
    over_hr: Optional[float]
    under_hr: Optional[float]
    over_picks: int = 0
    under_picks: int = 0
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class SeasonResult:
    strategy: StrategyConfig
    cycles: list = field(default_factory=list)
    total_picks: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_pushes: int = 0
    total_hr: Optional[float] = None
    total_pnl: float = 0.0
    total_roi: Optional[float] = None
    avg_mae: Optional[float] = None


# =============================================================================
# Feature Preparation (reused from quick_retrain.py)
# =============================================================================

def prepare_features(df, contract=V9_CONTRACT, exclude_features=None):
    """Prepare feature matrix using NAME-BASED extraction.

    Session 238: Prefers individual feature_N_value columns (NULL-aware).
    NULL -> np.nan -> CatBoost handles natively.
    Falls back to array-based extraction for older data.
    """
    exclude_set = set(exclude_features or [])
    active_features = [f for f in contract.feature_names if f not in exclude_set]

    store_name_to_idx = {name: i for i, name in enumerate(FEATURE_STORE_NAMES)}

    rows = []
    for _, row in df.iterrows():
        row_data = {}

        # Read from individual feature_N_value columns (Session 287 migration).
        # NULL means no real data → np.nan (CatBoost handles natively).
        for name in active_features:
            idx = store_name_to_idx.get(name)
            if idx is not None:
                val = row.get(f'feature_{idx}_value')
                if val is not None and not pd.isna(val):
                    row_data[name] = float(val)
                else:
                    row_data[name] = np.nan
            else:
                row_data[name] = np.nan

        rows.append(row_data)

    X = pd.DataFrame(rows, columns=active_features)

    # CatBoost handles NaN natively — no imputation needed.
    nan_pct = X.isna().mean().mean() * 100
    if nan_pct > 0:
        print(f"  Feature matrix: {X.shape[0]} rows x {X.shape[1]} cols, {nan_pct:.1f}% NaN (CatBoost native)")

    y = df['actual_points'].astype(float)
    return X, y


# =============================================================================
# Hit Rate / P&L Computation (reused from quick_retrain.py)
# =============================================================================

def compute_hit_rate(preds, actuals, lines, min_edge=3.0):
    """Compute hit rate for given edge threshold. Returns (hr%, graded_count)."""
    edges = preds - lines
    mask = np.abs(edges) >= min_edge
    if mask.sum() == 0:
        return None, 0

    b_actual = actuals[mask]
    b_lines = lines[mask]
    b_over = edges[mask] > 0

    wins = ((b_actual > b_lines) & b_over) | ((b_actual < b_lines) & ~b_over)
    pushes = b_actual == b_lines
    graded = len(b_actual) - pushes.sum()

    if graded == 0:
        return None, 0
    return round(wins.sum() / graded * 100, 2), int(graded)


def compute_pnl(preds, actuals, lines, min_edge=3.0):
    """Compute P&L, wins, losses, pushes for edge-filtered picks."""
    edges = preds - lines
    mask = np.abs(edges) >= min_edge
    if mask.sum() == 0:
        return 0.0, 0, 0, 0, 0, 0, None, None

    b_actual = actuals[mask]
    b_lines = lines[mask]
    b_edges = edges[mask]
    b_over = b_edges > 0

    wins_mask = ((b_actual > b_lines) & b_over) | ((b_actual < b_lines) & ~b_over)
    pushes_mask = b_actual == b_lines
    losses_mask = ~wins_mask & ~pushes_mask

    wins = int(wins_mask.sum())
    losses = int(losses_mask.sum())
    pushes = int(pushes_mask.sum())
    picks = wins + losses + pushes

    pnl = wins * WIN_PAYOUT - losses * STAKE  # pushes = $0

    # Directional breakdown
    over_mask = mask & (edges > 0)
    under_mask = mask & (edges < 0)

    over_hr = None
    under_hr = None
    over_picks = 0
    under_picks = 0

    if over_mask.sum() > 0:
        o_actual = actuals[over_mask]
        o_lines = lines[over_mask]
        o_wins = (o_actual > o_lines).sum()
        o_pushes = (o_actual == o_lines).sum()
        o_graded = int(over_mask.sum()) - o_pushes
        over_picks = int(over_mask.sum())
        if o_graded > 0:
            over_hr = round(o_wins / o_graded * 100, 1)

    if under_mask.sum() > 0:
        u_actual = actuals[under_mask]
        u_lines = lines[under_mask]
        u_wins = (u_actual < u_lines).sum()
        u_pushes = (u_actual == u_lines).sum()
        u_graded = int(under_mask.sum()) - u_pushes
        under_picks = int(under_mask.sum())
        if u_graded > 0:
            under_hr = round(u_wins / u_graded * 100, 1)

    return pnl, wins, losses, pushes, over_picks, under_picks, over_hr, under_hr


# =============================================================================
# Season Simulator
# =============================================================================

class SeasonSimulator:
    def __init__(
        self,
        season_start: str,
        season_end: str,
        contract=V9_CONTRACT,
        pre_season_start: Optional[str] = None,
        pre_season_end: Optional[str] = None,
        min_edge: float = 3.0,
        catboost_params: Optional[dict] = None,
    ):
        self.season_start = season_start
        self.season_end = season_end
        self.contract = contract
        self.pre_season_start = pre_season_start
        self.pre_season_end = pre_season_end
        self.min_edge = min_edge
        self.catboost_params = catboost_params or DEFAULT_CATBOOST_PARAMS.copy()

        self.client = bigquery.Client(project=PROJECT_ID)
        self.train_df = None
        self.eval_df = None

    def bulk_load_data(self):
        """Load all training + eval data in 2 bulk BQ queries."""
        quality_clause = get_quality_where_clause("mf")

        # Determine full date range for training data
        train_earliest = self.pre_season_start or self.season_start

        feature_value_columns = ',\n      '.join(
            f'mf.feature_{i}_value' for i in range(FEATURE_STORE_FEATURE_COUNT)
        )

        # Query 1: Training data (all quality-ready, no line requirement)
        train_query = f"""
        SELECT
          mf.player_lookup,
          mf.game_date,
          mf.features,
          mf.feature_names,
          {feature_value_columns},
          mf.feature_quality_score,
          mf.required_default_count,
          mf.default_feature_count,
          pgs.points as actual_points,
          pgs.minutes_played
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
          ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
        WHERE mf.game_date BETWEEN '{train_earliest}' AND '{self.season_end}'
          AND {quality_clause}
          AND pgs.points IS NOT NULL
          AND pgs.minutes_played > 0
        """

        # Query 2: Eval data (quality-ready WITH DraftKings lines)
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
          mf.features,
          mf.feature_names,
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

        print(f"Loading training data ({train_earliest} to {self.season_end})...")
        self.train_df = self.client.query(train_query).to_dataframe()
        print(f"  -> {len(self.train_df):,} training records loaded")

        print(f"Loading eval data ({self.season_start} to {self.season_end})...")
        self.eval_df = self.client.query(eval_query).to_dataframe()
        print(f"  -> {len(self.eval_df):,} eval records loaded (with DK lines)")

        # Convert game_date to datetime for fast filtering
        self.train_df['game_date'] = pd.to_datetime(self.train_df['game_date'])
        self.eval_df['game_date'] = pd.to_datetime(self.eval_df['game_date'])

    def slice_train(self, start: str, end: str) -> pd.DataFrame:
        """Slice training data by date range (instant, in-memory)."""
        s = pd.Timestamp(start)
        e = pd.Timestamp(end)
        return self.train_df[(self.train_df['game_date'] >= s) & (self.train_df['game_date'] <= e)]

    def slice_eval(self, start: str, end: str) -> pd.DataFrame:
        """Slice eval data by date range (instant, in-memory)."""
        s = pd.Timestamp(start)
        e = pd.Timestamp(end)
        return self.eval_df[(self.eval_df['game_date'] >= s) & (self.eval_df['game_date'] <= e)]

    def generate_cycles(self, strategy: StrategyConfig) -> list:
        """Generate (train_start, train_end, eval_start, eval_end) tuples for a strategy."""
        season_start = date.fromisoformat(self.season_start)
        season_end = date.fromisoformat(self.season_end)
        cadence = timedelta(days=strategy.cadence_days)
        min_train = timedelta(days=strategy.min_training_days)

        # First eval starts after min_training_days
        first_eval_start = season_start + min_train

        if strategy.window_type == "expanding":
            train_origin = date.fromisoformat(strategy.pre_season_start) if strategy.pre_season_start else season_start
        else:
            train_origin = None  # rolling computes per-cycle

        cycles = []
        eval_start = first_eval_start
        cycle_num = 1

        while eval_start < season_end:
            eval_end = min(eval_start + cadence - timedelta(days=1), season_end)
            train_end = eval_start - timedelta(days=1)

            if strategy.window_type == "expanding":
                train_start = train_origin
            else:
                # Rolling: fixed window ending at train_end
                train_start = train_end - timedelta(days=strategy.rolling_window_days) + timedelta(days=1)
                # Don't go before available data
                earliest = date.fromisoformat(strategy.pre_season_start) if strategy.pre_season_start else season_start
                train_start = max(train_start, earliest)

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

    def run_single_cycle(
        self, cycle_num: int, train_start: str, train_end: str, eval_start: str, eval_end: str
    ) -> CycleResult:
        """Train a model and evaluate on one cycle."""
        # Slice data
        train_slice = self.slice_train(train_start, train_end)
        eval_slice = self.slice_eval(eval_start, eval_end)

        # Check minimum training data
        if len(train_slice) < 500:
            return CycleResult(
                cycle_num=cycle_num,
                train_start=train_start, train_end=train_end,
                eval_start=eval_start, eval_end=eval_end,
                train_n=len(train_slice), picks=0, wins=0, losses=0, pushes=0,
                hr=None, pnl=0.0, mae=None, over_hr=None, under_hr=None,
                skipped=True, skip_reason=f"< 500 training records ({len(train_slice)})",
            )

        # Check eval data
        if len(eval_slice) == 0:
            return CycleResult(
                cycle_num=cycle_num,
                train_start=train_start, train_end=train_end,
                eval_start=eval_start, eval_end=eval_end,
                train_n=len(train_slice), picks=0, wins=0, losses=0, pushes=0,
                hr=None, pnl=0.0, mae=None, over_hr=None, under_hr=None,
                skipped=True, skip_reason="0 eval records (All-Star break?)",
            )

        # Prepare features
        X_train, y_train = prepare_features(train_slice, self.contract)

        # 85/15 train/val split for early stopping
        X_tr, X_val, y_tr, y_val = _train_val_split(X_train, y_train, val_frac=0.15)

        # Train CatBoost
        model = cb.CatBoostRegressor(**self.catboost_params)
        model.fit(X_tr, y_tr, eval_set=(X_val, y_val), verbose=0)

        # Prepare eval features
        X_eval, y_eval = prepare_features(eval_slice, self.contract)
        lines = eval_slice['vegas_line'].astype(float).values

        # Predict
        preds = model.predict(X_eval)
        actuals = y_eval.values

        # MAE
        cycle_mae = round(mean_absolute_error(actuals, preds), 2)

        # P&L and hit rate
        pnl, wins, losses, pushes, over_picks, under_picks, over_hr, under_hr = compute_pnl(
            preds, actuals, lines, self.min_edge
        )
        picks = wins + losses + pushes
        hr, _ = compute_hit_rate(preds, actuals, lines, self.min_edge)

        return CycleResult(
            cycle_num=cycle_num,
            train_start=train_start, train_end=train_end,
            eval_start=eval_start, eval_end=eval_end,
            train_n=len(train_slice), picks=picks, wins=wins, losses=losses, pushes=pushes,
            hr=hr, pnl=pnl, mae=cycle_mae, over_hr=over_hr, under_hr=under_hr,
            over_picks=over_picks, under_picks=under_picks,
        )

    def run_strategy(self, strategy: StrategyConfig) -> SeasonResult:
        """Run all cycles for a strategy."""
        cycles = self.generate_cycles(strategy)
        result = SeasonResult(strategy=strategy)

        print(f"\n{'='*70}")
        print(f"Strategy: {strategy.name}")
        print(f"  Cadence: {strategy.cadence_days}d | Window: {strategy.window_type}"
              f"{f' ({strategy.rolling_window_days}d)' if strategy.rolling_window_days else ''}")
        print(f"  Cycles: {len(cycles)}")
        print(f"{'='*70}")

        maes = []
        for cycle_num, ts, te, es, ee in cycles:
            cr = self.run_single_cycle(cycle_num, ts, te, es, ee)
            result.cycles.append(cr)

            status = "SKIP" if cr.skipped else f"{cr.picks} picks"
            hr_str = f"{cr.hr:.1f}%" if cr.hr is not None else "N/A"
            pnl_str = f"${cr.pnl:+,.0f}" if not cr.skipped else "—"
            print(f"  Cycle {cr.cycle_num}: train {cr.train_start}→{cr.train_end} | "
                  f"eval {cr.eval_start}→{cr.eval_end} | "
                  f"N={cr.train_n:,} | {status} | HR={hr_str} | P&L={pnl_str}"
                  f"{f' [{cr.skip_reason}]' if cr.skipped else ''}")

            if not cr.skipped:
                result.total_picks += cr.picks
                result.total_wins += cr.wins
                result.total_losses += cr.losses
                result.total_pushes += cr.pushes
                result.total_pnl += cr.pnl
                if cr.mae is not None:
                    maes.append(cr.mae)

        # Compute totals
        graded = result.total_wins + result.total_losses
        if graded > 0:
            result.total_hr = round(result.total_wins / graded * 100, 2)
        if result.total_picks > 0:
            total_risked = (result.total_wins + result.total_losses) * STAKE
            result.total_roi = round(result.total_pnl / total_risked * 100, 1) if total_risked > 0 else None
        if maes:
            result.avg_mae = round(np.mean(maes), 2)

        return result

    def run_all(self, strategies: list) -> list:
        """Run all strategies."""
        results = []
        for strategy in strategies:
            results.append(self.run_strategy(strategy))
        return results


# =============================================================================
# Helpers
# =============================================================================

def _train_val_split(X, y, val_frac=0.15):
    """Temporal-aware train/val split (last val_frac% of data as validation)."""
    n = len(X)
    split_idx = int(n * (1 - val_frac))
    return X.iloc[:split_idx], X.iloc[split_idx:], y.iloc[:split_idx], y.iloc[split_idx:]


# =============================================================================
# Output Formatting
# =============================================================================

def print_cycle_table(result: SeasonResult):
    """Print detailed cycle-by-cycle table for a strategy."""
    print(f"\n{'='*100}")
    print(f"CYCLE DETAIL: {result.strategy.name}")
    print(f"{'='*100}")
    header = (f"{'#':>3} | {'Train Window':^23} | {'Eval Window':^23} | "
              f"{'Train N':>7} | {'Picks':>5} | {'W-L-P':>9} | {'HR%':>6} | "
              f"{'P&L':>8} | {'MAE':>5} | {'OvHR':>5} | {'UnHR':>5}")
    print(header)
    print("-" * len(header))

    cum_pnl = 0.0
    for c in result.cycles:
        if c.skipped:
            print(f"{c.cycle_num:>3} | {c.train_start}→{c.train_end} | "
                  f"{c.eval_start}→{c.eval_end} | {c.train_n:>7,} | "
                  f"{'SKIPPED':^42} {c.skip_reason}")
            continue

        cum_pnl += c.pnl
        wlp = f"{c.wins}-{c.losses}-{c.pushes}"
        hr = f"{c.hr:.1f}" if c.hr is not None else "N/A"
        mae = f"{c.mae:.2f}" if c.mae is not None else "N/A"
        o_hr = f"{c.over_hr:.0f}" if c.over_hr is not None else "—"
        u_hr = f"{c.under_hr:.0f}" if c.under_hr is not None else "—"
        print(f"{c.cycle_num:>3} | {c.train_start}→{c.train_end} | "
              f"{c.eval_start}→{c.eval_end} | {c.train_n:>7,} | {c.picks:>5} | "
              f"{wlp:>9} | {hr:>5}% | ${c.pnl:>+7,.0f} | {mae:>5} | {o_hr:>5} | {u_hr:>5}")

    print("-" * len(header))
    graded = result.total_wins + result.total_losses
    hr_str = f"{result.total_hr:.1f}%" if result.total_hr is not None else "N/A"
    roi_str = f"{result.total_roi:+.1f}%" if result.total_roi is not None else "N/A"
    print(f"{'TOT':>3} | {'':^23} | {'':^23} | {'':>7} | {result.total_picks:>5} | "
          f"{result.total_wins}-{result.total_losses}-{result.total_pushes!s:>9} | "
          f"{hr_str:>6} | ${result.total_pnl:>+7,.0f} | {result.avg_mae or 'N/A':>5} | "
          f"{'':>5} | {'':>5}")
    print(f"  ROI: {roi_str} | Graded: {graded}")


def print_comparison_matrix(results: list):
    """Print side-by-side strategy comparison."""
    print(f"\n{'='*90}")
    print("STRATEGY COMPARISON MATRIX")
    print(f"{'='*90}")

    header = (f"{'Strategy':<28} | {'Picks':>5} | {'W-L':>7} | {'HR%':>6} | "
              f"{'P&L':>9} | {'ROI':>7} | {'MAE':>5} | {'Cycles':>6}")
    print(header)
    print("-" * len(header))

    for r in sorted(results, key=lambda x: x.total_pnl, reverse=True):
        hr = f"{r.total_hr:.1f}" if r.total_hr is not None else "N/A"
        roi = f"{r.total_roi:+.1f}" if r.total_roi is not None else "N/A"
        mae = f"{r.avg_mae:.2f}" if r.avg_mae is not None else "N/A"
        active_cycles = sum(1 for c in r.cycles if not c.skipped)
        print(f"{r.strategy.name:<28} | {r.total_picks:>5} | "
              f"{r.total_wins}-{r.total_losses!s:>7} | {hr:>5}% | "
              f"${r.total_pnl:>+8,.0f} | {roi:>6}% | {mae:>5} | {active_cycles:>6}")

    print("-" * len(header))
    # Highlight best
    if results:
        best_pnl = max(results, key=lambda x: x.total_pnl)
        best_hr = max(results, key=lambda x: x.total_hr or 0)
        print(f"\n  Best P&L:  {best_pnl.strategy.name} (${best_pnl.total_pnl:+,.0f})")
        print(f"  Best HR:   {best_hr.strategy.name} ({best_hr.total_hr:.1f}%)")


def print_decay_analysis(results: list):
    """Print HR bucketed by model age across strategies."""
    print(f"\n{'='*90}")
    print("DECAY ANALYSIS: Hit Rate by Model Age")
    print(f"{'='*90}")

    age_buckets = [
        ("0-7d", 0, 7),
        ("8-14d", 8, 14),
        ("15-21d", 15, 21),
        ("22-28d", 22, 28),
        ("29+d", 29, 999),
    ]

    header = f"{'Strategy':<28} | " + " | ".join(f"{b[0]:>12}" for b in age_buckets)
    print(header)
    print("-" * len(header))

    for r in results:
        bucket_data = {b[0]: {"wins": 0, "graded": 0} for b in age_buckets}

        for c in r.cycles:
            if c.skipped or c.picks == 0:
                continue

            # Model age = days from train_end to midpoint of eval window
            train_end = date.fromisoformat(c.train_end)
            eval_start = date.fromisoformat(c.eval_start)
            eval_end = date.fromisoformat(c.eval_end)

            # Assign entire cycle to a bucket based on average model age
            avg_eval = eval_start + (eval_end - eval_start) / 2
            model_age = (avg_eval - train_end).days

            for bname, bmin, bmax in age_buckets:
                if bmin <= model_age <= bmax:
                    bucket_data[bname]["wins"] += c.wins
                    bucket_data[bname]["graded"] += c.wins + c.losses
                    break

        parts = []
        for bname, _, _ in age_buckets:
            bd = bucket_data[bname]
            if bd["graded"] > 0:
                hr = bd["wins"] / bd["graded"] * 100
                parts.append(f"{hr:>5.1f}% ({bd['graded']:>3})")
            else:
                parts.append(f"{'—':>12}")

        print(f"{r.strategy.name:<28} | " + " | ".join(parts))

    print(f"\nBreakeven: {BREAKEVEN_HR}% (at -110 odds)")


# =============================================================================
# Strategy Builder
# =============================================================================

def build_strategies(args) -> list:
    """Build strategy configs from CLI args."""
    strategies = []
    cadences = [int(c) for c in args.cadences.split(",")]
    rolling_windows = [int(w) for w in args.rolling_windows.split(",")] if args.rolling_windows else [56]

    window_types = []
    if args.window_type in ("expanding", "both"):
        window_types.append("expanding")
    if args.window_type in ("rolling", "both"):
        window_types.append("rolling")

    for wtype in window_types:
        for cadence in cadences:
            if wtype == "expanding":
                name = f"expand_{cadence}d"
                strategies.append(StrategyConfig(
                    name=name,
                    cadence_days=cadence,
                    window_type="expanding",
                    min_training_days=args.min_training_days,
                    pre_season_start=args.pre_season_start,
                    pre_season_end=args.pre_season_end,
                ))
            else:
                for rw in rolling_windows:
                    # Validate rolling window >= min_training_days
                    if rw < args.min_training_days:
                        print(f"WARNING: rolling window {rw}d < min_training_days "
                              f"{args.min_training_days}d, skipping")
                        continue
                    name = f"roll_{rw}d_cad_{cadence}d"
                    strategies.append(StrategyConfig(
                        name=name,
                        cadence_days=cadence,
                        window_type="rolling",
                        rolling_window_days=rw,
                        min_training_days=args.min_training_days,
                        pre_season_start=args.pre_season_start,
                        pre_season_end=args.pre_season_end,
                    ))

    return strategies


# =============================================================================
# CLI
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Walk-Forward Season Simulator: find optimal retrain cadence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare cadences with expanding window
  PYTHONPATH=. python ml/experiments/season_walkforward.py \\
      --season-start 2025-11-02 --season-end 2026-02-12 \\
      --cadences 14,21,28,42 --window-type expanding

  # Compare expanding vs rolling
  PYTHONPATH=. python ml/experiments/season_walkforward.py \\
      --season-start 2025-11-02 --season-end 2026-02-12 \\
      --cadences 14,28 --window-type both --rolling-windows 56

  # With pre-season bootstrap
  PYTHONPATH=. python ml/experiments/season_walkforward.py \\
      --season-start 2025-11-02 --season-end 2026-02-12 \\
      --cadences 14,28 --pre-season-start 2024-10-22 --pre-season-end 2025-04-13
        """,
    )

    parser.add_argument("--season-start", required=True, help="Season start date (YYYY-MM-DD)")
    parser.add_argument("--season-end", required=True, help="Season end date (YYYY-MM-DD)")
    parser.add_argument("--cadences", required=True,
                        help="Comma-separated retrain cadences in days (e.g., 14,21,28,42)")
    parser.add_argument("--window-type", default="expanding", choices=["expanding", "rolling", "both"],
                        help="Training window type (default: expanding)")
    parser.add_argument("--rolling-windows", default=None,
                        help="Comma-separated rolling window sizes in days (default: 56)")
    parser.add_argument("--min-training-days", type=int, default=28,
                        help="Minimum training days before first model (default: 28)")
    parser.add_argument("--min-edge", type=float, default=3.0,
                        help="Minimum edge threshold for picks (default: 3.0)")
    parser.add_argument("--pre-season-start", default=None,
                        help="Prior season start date for bootstrap training data")
    parser.add_argument("--pre-season-end", default=None,
                        help="Prior season end date for bootstrap training data")
    parser.add_argument("--model-version", default="v9",
                        help="Model version contract to use (default: v9)")
    parser.add_argument("--save-json", default=None,
                        help="Save results to JSON file")

    return parser.parse_args()


def main():
    args = parse_args()

    # Build strategies
    strategies = build_strategies(args)
    if not strategies:
        print("ERROR: No valid strategies to run. Check --cadences and --rolling-windows.")
        sys.exit(1)

    print(f"\nWalk-Forward Season Simulator")
    print(f"  Season: {args.season_start} to {args.season_end}")
    print(f"  Strategies: {len(strategies)}")
    for s in strategies:
        extra = f" ({s.rolling_window_days}d window)" if s.rolling_window_days else ""
        print(f"    - {s.name}: {s.cadence_days}d cadence, {s.window_type}{extra}")
    if args.pre_season_start:
        print(f"  Pre-season: {args.pre_season_start} to {args.pre_season_end}")
    print(f"  Min edge: {args.min_edge}")
    print(f"  Model: {args.model_version}")

    # Get contract
    contract = get_contract(args.model_version)

    # Initialize simulator
    sim = SeasonSimulator(
        season_start=args.season_start,
        season_end=args.season_end,
        contract=contract,
        pre_season_start=args.pre_season_start,
        pre_season_end=args.pre_season_end,
        min_edge=args.min_edge,
    )

    # Bulk load (2 BQ queries)
    sim.bulk_load_data()

    # Run all strategies
    results = sim.run_all(strategies)

    # Print reports
    for r in results:
        print_cycle_table(r)

    if len(results) > 1:
        print_comparison_matrix(results)

    print_decay_analysis(results)

    # Optional JSON export
    if args.save_json:
        export = []
        for r in results:
            export.append({
                "strategy": asdict(r.strategy),
                "total_picks": r.total_picks,
                "total_wins": r.total_wins,
                "total_losses": r.total_losses,
                "total_pushes": r.total_pushes,
                "total_hr": r.total_hr,
                "total_pnl": r.total_pnl,
                "total_roi": r.total_roi,
                "avg_mae": r.avg_mae,
                "cycles": [asdict(c) for c in r.cycles],
            })
        with open(args.save_json, "w") as f:
            json.dump(export, f, indent=2, default=str)
        print(f"\nResults saved to {args.save_json}")

    print("\nDone.")


if __name__ == "__main__":
    main()
