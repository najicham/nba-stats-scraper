#!/usr/bin/env python3
"""
Tier-Based Model Selection Backtest

Tests the hypothesis that using different models for different player tiers
improves overall prediction accuracy.

Hypothesis from Session 53:
- V8 Production: Best for stars (55.8%) and bench (57.5%)
- JAN_DEC_ONLY: Best for rotation (63%) and starters (59.9%)

Tier-based strategy:
- Stars (25+ ppg): Use V8 production model
- Starters (15-25 ppg): Use JAN_DEC_ONLY model
- Rotation (5-15 ppg): Use JAN_DEC_ONLY model
- Bench (<5 ppg): Use V8 production model

Usage:
    PYTHONPATH=. python ml/experiments/tier_based_backtest.py \
        --eval-start 2026-01-01 \
        --eval-end 2026-01-30

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
import numpy as np
import pandas as pd
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb

PROJECT_ID = "nba-props-platform"
RESULTS_DIR = Path(__file__).parent / "results"
MODELS_DIR = Path(__file__).parent.parent.parent / "models"

# Feature names - supports variable length feature vectors
ALL_FEATURES = [
    # Recent Performance (0-4)
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days",
    # Composite Factors (5-8)
    "fatigue_score", "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    # Derived Factors (9-12)
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    # Matchup Context (13-17)
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back", "playoff_game",
    # Shot Zones (18-21)
    "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
    # Team Context (22-24)
    "team_pace", "team_off_rating", "team_win_pct",
    # Vegas Lines (25-28)
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    # Opponent History (29-30)
    "avg_points_vs_opponent", "games_vs_opponent",
    # Minutes/Efficiency (31-32)
    "minutes_avg_last_10", "ppm_avg_last_10",
    # DNP Risk (33)
    "dnp_rate",
    # Player Trajectory (34-36)
    "pts_slope_10g", "pts_vs_season_zscore", "breakout_flag",
]

# Betting constants
WIN_PAYOUT = 100 / 110
LOSS_PAYOUT = -1.0
BREAKEVEN_HIT_RATE = 1 / (1 + WIN_PAYOUT)

# Tier thresholds (based on points_avg_last_10)
TIER_THRESHOLDS = {
    'star': 22.0,        # 22+ ppg = star
    'starter': 14.0,     # 14-22 ppg = starter
    'rotation': 6.0,     # 6-14 ppg = rotation
    # below 6 = bench
}


def estimate_tier(points_avg: float) -> str:
    """Estimate player tier from points average."""
    if points_avg >= TIER_THRESHOLDS['star']:
        return 'star'
    elif points_avg >= TIER_THRESHOLDS['starter']:
        return 'starter'
    elif points_avg >= TIER_THRESHOLDS['rotation']:
        return 'rotation'
    else:
        return 'bench'


def get_model_for_tier(tier: str) -> str:
    """Get which model to use for a given tier."""
    if tier in ['star', 'bench']:
        return 'v8_production'
    else:  # starter, rotation
        return 'jan_dec_only'


class TierBasedPredictor:
    """
    Tier-based model selector that routes predictions to the best model
    for each player's scoring tier.
    """

    def __init__(
        self,
        v8_model_path: str = None,
        jan_dec_model_path: str = None,
    ):
        """Initialize with both models."""
        # Load V8 production model (33 features)
        if v8_model_path:
            self.v8_model = cb.CatBoostRegressor()
            self.v8_model.load_model(v8_model_path)
        else:
            # Find most recent V8 model
            v8_files = sorted(MODELS_DIR.glob("catboost_v8_33features_*.cbm"))
            if v8_files:
                self.v8_model = cb.CatBoostRegressor()
                self.v8_model.load_model(str(v8_files[-1]))
                print(f"Loaded V8 model: {v8_files[-1].name}")
            else:
                raise FileNotFoundError("No V8 model found in models/")

        self.v8_feature_count = 33

        # Load JAN_DEC_ONLY model (37 features)
        if jan_dec_model_path:
            self.jan_dec_model = cb.CatBoostRegressor()
            self.jan_dec_model.load_model(jan_dec_model_path)
        else:
            # Find JAN_DEC_ONLY experiment model
            jan_dec_files = sorted(
                (Path(__file__).parent / "results").glob(
                    "catboost_v9_exp_JAN_DEC_ONLY_*.cbm"
                )
            )
            if jan_dec_files:
                self.jan_dec_model = cb.CatBoostRegressor()
                self.jan_dec_model.load_model(str(jan_dec_files[-1]))
                print(f"Loaded JAN_DEC_ONLY model: {jan_dec_files[-1].name}")
            else:
                raise FileNotFoundError("No JAN_DEC_ONLY model found")

        self.jan_dec_feature_count = 37

    def predict(
        self,
        features: np.ndarray,
        points_avg_last_10: float,
    ) -> tuple[float, str, str]:
        """
        Generate prediction using the appropriate model for the player's tier.

        Args:
            features: Feature array (length 33 or 37)
            points_avg_last_10: Player's avg points last 10 games (for tier estimation)

        Returns:
            (prediction, tier, model_used)
        """
        tier = estimate_tier(points_avg_last_10)
        model_choice = get_model_for_tier(tier)

        if model_choice == 'v8_production':
            # V8 uses 33 features - truncate if needed
            features_for_model = features[:self.v8_feature_count]
            pred = float(self.v8_model.predict([features_for_model])[0])
        else:  # jan_dec_only
            # JAN_DEC_ONLY uses 37 features
            if len(features) >= self.jan_dec_feature_count:
                features_for_model = features[:self.jan_dec_feature_count]
            else:
                # Pad with zeros if needed (unlikely in practice)
                features_for_model = np.pad(
                    features,
                    (0, self.jan_dec_feature_count - len(features)),
                    mode='constant'
                )
            pred = float(self.jan_dec_model.predict([features_for_model])[0])

        return pred, tier, model_choice


def load_evaluation_data(
    client: bigquery.Client,
    eval_start: str,
    eval_end: str,
) -> pd.DataFrame:
    """Load evaluation data from BigQuery."""
    query = f"""
    SELECT
      mf.player_lookup,
      mf.game_date,
      mf.features,
      mf.feature_count,
      mf.features[OFFSET(1)] as points_avg_last_10,
      mf.features[OFFSET(25)] as vegas_points_line,
      mf.features[OFFSET(28)] as has_vegas_line,
      pgs.points as actual_points
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
    INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup
      AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{eval_start}' AND '{eval_end}'
      AND mf.feature_count >= 33
      AND ARRAY_LENGTH(mf.features) >= 33
      AND pgs.points IS NOT NULL
    ORDER BY mf.game_date
    """
    return client.query(query).to_dataframe()


def calculate_tier_metrics(
    df: pd.DataFrame,
    predictions: np.ndarray,
    min_edge: float = 1.0,
) -> dict:
    """Calculate hit rates by tier."""
    results = {}

    for tier in ['star', 'starter', 'rotation', 'bench']:
        mask = df['tier'] == tier
        if not mask.any():
            results[tier] = {'count': 0, 'hit_rate': None}
            continue

        tier_df = df[mask].copy()
        tier_preds = predictions[mask]
        tier_lines = tier_df['vegas_points_line'].values.copy()
        tier_actuals = tier_df['actual_points'].values

        # IMPORTANT: Only use real Vegas lines (has_vegas_line = 1.0)
        has_real_line = tier_df['has_vegas_line'].values == 1.0
        tier_lines[~has_real_line] = np.nan

        # Filter to valid lines (non-NaN)
        valid_mask = ~np.isnan(tier_lines)
        if not valid_mask.any():
            results[tier] = {
                'count': int(mask.sum()),
                'bets': 0,
                'hit_rate': None,
                'no_vegas_lines': True,
            }
            continue

        tier_preds = tier_preds[valid_mask]
        tier_lines = tier_lines[valid_mask]
        tier_actuals = tier_actuals[valid_mask]

        # Calculate hits
        edges = tier_preds - tier_lines
        over_bets = edges >= min_edge
        under_bets = edges <= -min_edge
        bet_mask = over_bets | under_bets

        if not bet_mask.any():
            results[tier] = {
                'count': int(mask.sum()),
                'with_lines': int(valid_mask.sum()),
                'bets': 0,
                'hit_rate': None,
            }
            continue

        bet_acts = tier_actuals[bet_mask]
        bet_lines = tier_lines[bet_mask]
        bet_overs = over_bets[bet_mask]

        over_wins = (bet_acts > bet_lines) & bet_overs
        under_wins = (bet_acts < bet_lines) & ~bet_overs
        hits = over_wins | under_wins
        pushes = bet_acts == bet_lines

        n_graded = len(bet_acts) - pushes.sum()
        hit_rate = hits.sum() / n_graded if n_graded > 0 else None

        results[tier] = {
            'count': int(mask.sum()),
            'bets': int(bet_mask.sum()),
            'graded': int(n_graded),
            'hits': int(hits.sum()),
            'hit_rate': round(hit_rate * 100, 2) if hit_rate else None,
            'model_used': get_model_for_tier(tier),
        }

    return results


def calculate_overall_metrics(
    df: pd.DataFrame,
    predictions: np.ndarray,
    min_edge: float = 1.0,
) -> dict:
    """Calculate overall betting metrics."""
    lines = df['vegas_points_line'].values.copy()
    has_real_line = df['has_vegas_line'].values == 1.0
    lines[~has_real_line] = np.nan

    valid_mask = ~np.isnan(lines)
    if not valid_mask.any():
        return {'hit_rate': None, 'bets_placed': 0}

    preds = predictions[valid_mask]
    acts = df['actual_points'].values[valid_mask]
    lns = lines[valid_mask]

    edges = preds - lns
    over_bets = edges >= min_edge
    under_bets = edges <= -min_edge
    bet_mask = over_bets | under_bets

    if not bet_mask.any():
        return {'hit_rate': None, 'bets_placed': 0}

    bet_acts = acts[bet_mask]
    bet_lines = lns[bet_mask]
    bet_overs = over_bets[bet_mask]

    over_wins = (bet_acts > bet_lines) & bet_overs
    under_wins = (bet_acts < bet_lines) & ~bet_overs
    hits = over_wins | under_wins
    pushes = bet_acts == bet_lines

    n_graded = len(bet_acts) - pushes.sum()
    hit_rate = hits.sum() / n_graded if n_graded > 0 else None

    profit = hits.sum() * WIN_PAYOUT + (~hits & ~pushes).sum() * LOSS_PAYOUT
    roi = profit / len(bet_acts) if len(bet_acts) > 0 else None

    return {
        'hit_rate': round(hit_rate * 100, 2) if hit_rate else None,
        'hits': int(hits.sum()),
        'misses': int((~hits & ~pushes).sum()),
        'pushes': int(pushes.sum()),
        'bets_placed': int(bet_mask.sum()),
        'bets_graded': int(n_graded),
        'roi': round(roi * 100, 2) if roi else None,
        'profit': round(profit, 2),
    }


def run_baseline_comparison(
    df: pd.DataFrame,
    v8_predictions: np.ndarray,
    jan_dec_predictions: np.ndarray,
    tier_predictions: np.ndarray,
    min_edge: float = 1.0,
) -> dict:
    """Compare tier-based to baseline models."""
    results = {}

    for name, preds in [
        ('V8_only', v8_predictions),
        ('JAN_DEC_only', jan_dec_predictions),
        ('tier_based', tier_predictions),
    ]:
        metrics = calculate_overall_metrics(df, preds, min_edge)
        tier_metrics = calculate_tier_metrics(df.copy(), preds, min_edge)
        results[name] = {
            'overall': metrics,
            'by_tier': tier_metrics,
        }

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Tier-based model selection backtest"
    )
    parser.add_argument(
        "--eval-start",
        default="2026-01-01",
        help="Evaluation start date"
    )
    parser.add_argument(
        "--eval-end",
        default="2026-01-30",
        help="Evaluation end date"
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=2.0,
        help="Minimum edge to place bet (default: 2.0 for clearer signal)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path"
    )
    args = parser.parse_args()

    print("=" * 80)
    print(" TIER-BASED MODEL SELECTION BACKTEST")
    print("=" * 80)
    print(f"\nEvaluation period: {args.eval_start} to {args.eval_end}")
    print(f"Minimum edge threshold: {args.min_edge}")

    # Load models
    print("\nLoading models...")
    predictor = TierBasedPredictor()

    # Load V8-only for comparison
    v8_files = sorted(MODELS_DIR.glob("catboost_v8_33features_*.cbm"))
    v8_only_model = cb.CatBoostRegressor()
    v8_only_model.load_model(str(v8_files[-1]))

    # Load data
    print("\nLoading evaluation data...")
    client = bigquery.Client(project=PROJECT_ID)
    df = load_evaluation_data(client, args.eval_start, args.eval_end)
    print(f"Loaded {len(df):,} samples")

    if len(df) == 0:
        print("ERROR: No evaluation data found")
        sys.exit(1)

    # Add tier column
    df['tier'] = df['points_avg_last_10'].apply(estimate_tier)

    # Show tier distribution
    print("\nTier distribution:")
    tier_counts = df['tier'].value_counts()
    for tier in ['star', 'starter', 'rotation', 'bench']:
        count = tier_counts.get(tier, 0)
        pct = 100 * count / len(df)
        model = get_model_for_tier(tier)
        print(f"  {tier:10s}: {count:4d} ({pct:5.1f}%) -> {model}")

    # Generate predictions for all three strategies
    print("\nGenerating predictions...")

    # Prepare feature arrays
    all_features = np.array([np.array(f) for f in df['features'].tolist()])

    # 1. V8-only predictions (33 features)
    v8_features = all_features[:, :33]
    v8_predictions = v8_only_model.predict(v8_features)

    # 2. JAN_DEC_only predictions (37 features)
    jan_dec_features = all_features[:, :37]
    jan_dec_predictions = predictor.jan_dec_model.predict(jan_dec_features)

    # 3. Tier-based predictions
    tier_predictions = np.zeros(len(df))
    tier_models_used = []
    for i, (_, row) in enumerate(df.iterrows()):
        features = np.array(row['features'])
        pred, tier, model_used = predictor.predict(
            features, row['points_avg_last_10']
        )
        tier_predictions[i] = pred
        tier_models_used.append(model_used)

    # Calculate MAE
    actuals = df['actual_points'].values
    print("\n--- MAE Comparison ---")
    print(f"  V8-only:     {mean_absolute_error(actuals, v8_predictions):.4f}")
    print(f"  JAN_DEC-only: {mean_absolute_error(actuals, jan_dec_predictions):.4f}")
    print(f"  Tier-based:  {mean_absolute_error(actuals, tier_predictions):.4f}")

    # Run comparison
    print("\n" + "=" * 80)
    print(" BETTING METRICS COMPARISON (Edge >= {:.1f})".format(args.min_edge))
    print("=" * 80)

    comparison = run_baseline_comparison(
        df.copy(),
        v8_predictions,
        jan_dec_predictions,
        tier_predictions,
        args.min_edge,
    )

    for strategy, data in comparison.items():
        overall = data['overall']
        print(f"\n{strategy}:")
        if overall.get('hit_rate'):
            print(f"  Overall: {overall['hit_rate']:.1f}% ({overall['hits']}/{overall['bets_graded']})")
            print(f"  ROI: {overall['roi']:.1f}%, Profit: ${overall['profit']:.2f}")
        else:
            print("  Overall: No bets placed")

        print("  By tier:")
        for tier in ['star', 'starter', 'rotation', 'bench']:
            tier_data = data['by_tier'].get(tier, {})
            if tier_data.get('hit_rate'):
                print(f"    {tier:10s}: {tier_data['hit_rate']:5.1f}% ({tier_data['hits']}/{tier_data['graded']})")
            else:
                print(f"    {tier:10s}: No bets")

    # High confidence breakdown
    print("\n" + "=" * 80)
    print(" HIGH EDGE ANALYSIS (Edge >= 3.0)")
    print("=" * 80)

    high_edge_comparison = run_baseline_comparison(
        df.copy(),
        v8_predictions,
        jan_dec_predictions,
        tier_predictions,
        min_edge=3.0,
    )

    for strategy, data in high_edge_comparison.items():
        overall = data['overall']
        if overall.get('hit_rate'):
            print(f"  {strategy:15s}: {overall['hit_rate']:.1f}% ({overall['hits']}/{overall['bets_graded']}) ROI={overall['roi']:.1f}%")
        else:
            print(f"  {strategy:15s}: No bets")

    # Summary
    print("\n" + "=" * 80)
    print(" SUMMARY")
    print("=" * 80)

    v8_hr = comparison['V8_only']['overall'].get('hit_rate', 0) or 0
    jd_hr = comparison['JAN_DEC_only']['overall'].get('hit_rate', 0) or 0
    tb_hr = comparison['tier_based']['overall'].get('hit_rate', 0) or 0

    print(f"\nAt edge >= {args.min_edge}:")
    print(f"  V8-only:      {v8_hr:.1f}%")
    print(f"  JAN_DEC-only: {jd_hr:.1f}%")
    print(f"  Tier-based:   {tb_hr:.1f}%")

    improvement = tb_hr - v8_hr
    if improvement > 0:
        print(f"\n  Tier-based improves over V8 by: +{improvement:.1f}%")
    elif improvement < 0:
        print(f"\n  Tier-based underperforms V8 by: {improvement:.1f}%")
    else:
        print(f"\n  No difference between tier-based and V8")

    # Save results
    results = {
        'eval_period': {
            'start': args.eval_start,
            'end': args.eval_end,
        },
        'min_edge': args.min_edge,
        'samples': len(df),
        'tier_distribution': {
            tier: int(tier_counts.get(tier, 0))
            for tier in ['star', 'starter', 'rotation', 'bench']
        },
        'mae': {
            'V8_only': round(mean_absolute_error(actuals, v8_predictions), 4),
            'JAN_DEC_only': round(mean_absolute_error(actuals, jan_dec_predictions), 4),
            'tier_based': round(mean_absolute_error(actuals, tier_predictions), 4),
        },
        'comparison_edge_2': comparison,
        'comparison_edge_3': high_edge_comparison,
        'tier_strategy': {
            'star': 'v8_production',
            'starter': 'jan_dec_only',
            'rotation': 'jan_dec_only',
            'bench': 'v8_production',
        },
        'timestamp': datetime.now().isoformat(),
    }

    output_path = args.output or str(
        RESULTS_DIR / f"tier_based_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
