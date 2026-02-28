#!/usr/bin/env python3
"""Edge Calibrator — map edge → P(win) using isotonic regression.

Instead of a fixed edge >= 3.0 floor, learn a calibration curve per
model_family + direction that converts edge to win probability.

Usage:
    # Train calibrators on historical data
    PYTHONPATH=. python ml/calibration/edge_calibrator.py --train-end 2026-02-14

    # Evaluate on holdout
    PYTHONPATH=. python ml/calibration/edge_calibrator.py --train-end 2026-02-14 --eval-end 2026-02-27
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, Tuple

import joblib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sklearn.isotonic import IsotonicRegression

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
MODELS_DIR = Path('models/edge_calibrators')


def _classify_family(system_id: str) -> str:
    """Classify system_id into model family for calibration grouping."""
    from shared.config.cross_model_subsets import classify_system_id
    return classify_system_id(system_id)


class EdgeCalibrator:
    """Per-model+direction isotonic calibration: edge → P(win)."""

    def __init__(self):
        self.calibrators: Dict[str, IsotonicRegression] = {}
        self.stats: Dict[str, Dict] = {}

    def fit(self, edges: np.ndarray, wins: np.ndarray,
            families: np.ndarray, directions: np.ndarray,
            min_samples: int = 20) -> 'EdgeCalibrator':
        """Fit separate calibrators per (family, direction) group.

        Args:
            edges: Array of abs(edge) values
            wins: Binary array (1=correct, 0=incorrect)
            families: Array of model family strings
            directions: Array of 'OVER'/'UNDER' strings
            min_samples: Minimum samples to fit a group calibrator
        """
        groups = defaultdict(lambda: {'edges': [], 'wins': []})

        for i in range(len(edges)):
            key = f"{families[i]}_{directions[i]}"
            groups[key]['edges'].append(edges[i])
            groups[key]['wins'].append(wins[i])

        for key, data in groups.items():
            n = len(data['edges'])
            if n < min_samples:
                logger.info(f"Skipping {key}: only {n} samples (need {min_samples})")
                continue

            X = np.array(data['edges'], dtype=np.float64)
            y = np.array(data['wins'], dtype=np.float64)

            iso = IsotonicRegression(
                y_min=0.0, y_max=1.0, out_of_bounds='clip', increasing=True
            )
            iso.fit(X, y)

            self.calibrators[key] = iso
            self.stats[key] = {
                'n_samples': n,
                'win_rate': float(y.mean()),
                'mean_edge': float(X.mean()),
                'edge_range': (float(X.min()), float(X.max())),
            }

            logger.info(
                f"Fitted {key}: N={n}, WR={y.mean():.1%}, "
                f"edge range={X.min():.1f}-{X.max():.1f}"
            )

        # Global fallback calibrator (all data)
        if len(edges) >= min_samples:
            iso_global = IsotonicRegression(
                y_min=0.0, y_max=1.0, out_of_bounds='clip', increasing=True
            )
            iso_global.fit(
                np.array(edges, dtype=np.float64),
                np.array(wins, dtype=np.float64),
            )
            self.calibrators['_global'] = iso_global
            self.stats['_global'] = {
                'n_samples': len(edges),
                'win_rate': float(np.mean(wins)),
                'mean_edge': float(np.mean(edges)),
            }

        return self

    def predict_win_prob(self, edge: float, family: str,
                         direction: str) -> float:
        """Predict P(win) for a given edge, family, direction.

        Falls back to global calibrator if group-specific not available.
        """
        key = f"{family}_{direction}"

        if key in self.calibrators:
            return float(self.calibrators[key].predict([edge])[0])
        elif '_global' in self.calibrators:
            return float(self.calibrators['_global'].predict([edge])[0])
        else:
            # No calibrator — use edge/10 as rough proxy (edge 5 → 50%)
            return min(edge / 10.0, 0.95)

    def save(self, path: Optional[Path] = None):
        """Save all calibrators to disk."""
        path = path or MODELS_DIR
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        for key, cal in self.calibrators.items():
            filepath = path / f"edge_cal_{key}.pkl"
            joblib.dump(cal, filepath)

        # Save stats
        joblib.dump(self.stats, path / 'calibration_stats.pkl')
        print(f"Saved {len(self.calibrators)} calibrators to {path}")

    def load(self, path: Optional[Path] = None) -> 'EdgeCalibrator':
        """Load calibrators from disk."""
        path = path or MODELS_DIR
        path = Path(path)

        self.stats = joblib.load(path / 'calibration_stats.pkl')

        for key in self.stats:
            filepath = path / f"edge_cal_{key}.pkl"
            if filepath.exists():
                self.calibrators[key] = joblib.load(filepath)

        print(f"Loaded {len(self.calibrators)} calibrators from {path}")
        return self

    def print_calibration_curve(self):
        """Print calibration curve at integer edge points."""
        print("\n--- Edge → P(win) Calibration Curves ---")
        print(f"{'Group':30s} {'N':>5s} {'WR':>6s} | ", end='')
        print(' '.join(f"E{e}" for e in range(2, 11)))

        for key in sorted(self.stats.keys()):
            if key == '_global':
                continue
            st = self.stats[key]
            cal = self.calibrators.get(key)
            if cal is None:
                continue

            print(f"{key:30s} {st['n_samples']:5d} {st['win_rate']:5.1%} | ", end='')
            probs = cal.predict(np.arange(2, 11, dtype=np.float64))
            print(' '.join(f"{p:.0%}" for p in probs))

        # Global
        if '_global' in self.calibrators:
            st = self.stats['_global']
            cal = self.calibrators['_global']
            print(f"{'_global':30s} {st['n_samples']:5d} {st['win_rate']:5.1%} | ", end='')
            probs = cal.predict(np.arange(2, 11, dtype=np.float64))
            print(' '.join(f"{p:.0%}" for p in probs))


def load_graded_data(bq_client, start_date: str, end_date: str):
    """Load graded best bets picks with edge, model, direction, outcome."""
    query = f"""
    SELECT
        bb.edge,
        bb.recommendation AS direction,
        bb.source_model_family AS family,
        bb.system_id,
        pa.prediction_correct AS win
    FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` bb
    JOIN `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        ON bb.player_lookup = pa.player_lookup
        AND bb.game_date = pa.game_date
        AND bb.system_id = pa.system_id
    WHERE bb.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND pa.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND pa.prediction_correct IS NOT NULL
        AND pa.is_voided IS NOT TRUE
        AND bb.edge >= 1.0
    ORDER BY bb.game_date
    """
    return bq_client.query(query).to_dataframe()


def load_all_predictions_data(bq_client, start_date: str, end_date: str):
    """Load ALL graded predictions (not just best bets) for broader calibration."""
    query = f"""
    SELECT
        ROUND(ABS(pa.predicted_points - pa.line_value), 1) AS edge,
        pa.recommendation AS direction,
        pa.system_id,
        pa.prediction_correct AS win
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
    WHERE pa.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND pa.prediction_correct IS NOT NULL
        AND pa.is_voided IS NOT TRUE
        AND pa.line_value IS NOT NULL
        AND ABS(pa.predicted_points - pa.line_value) >= 1.0
    ORDER BY pa.game_date
    """
    return bq_client.query(query).to_dataframe()


def main():
    parser = argparse.ArgumentParser(description='Train edge → P(win) calibrators')
    parser.add_argument('--train-start', default='2026-01-09',
                        help='Training start date')
    parser.add_argument('--train-end', required=True,
                        help='Training end date (inclusive)')
    parser.add_argument('--eval-start', default=None,
                        help='Eval start date (default: day after train-end)')
    parser.add_argument('--eval-end', default=None,
                        help='Eval end date (inclusive)')
    parser.add_argument('--use-all-predictions', action='store_true',
                        help='Train on all predictions, not just best bets')
    parser.add_argument('--threshold', type=float, default=0.55,
                        help='P(win) threshold to use as filter (default: 0.55)')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

    from google.cloud import bigquery
    bq_client = bigquery.Client(project=PROJECT_ID)

    # Load training data
    print(f"Loading training data: {args.train_start} → {args.train_end}")
    if args.use_all_predictions:
        df_train = load_all_predictions_data(bq_client, args.train_start, args.train_end)
        print(f"Loaded {len(df_train)} graded predictions (all models)")
    else:
        df_train = load_graded_data(bq_client, args.train_start, args.train_end)
        print(f"Loaded {len(df_train)} graded best bets picks")

    if len(df_train) == 0:
        print("ERROR: No training data found")
        return

    # Classify families
    if 'family' not in df_train.columns:
        df_train['family'] = df_train['system_id'].apply(_classify_family)

    # Fit calibrators
    calibrator = EdgeCalibrator()
    calibrator.fit(
        edges=df_train['edge'].values,
        wins=df_train['win'].astype(float).values,
        families=df_train['family'].values,
        directions=df_train['direction'].values,
        min_samples=15,
    )

    calibrator.print_calibration_curve()
    calibrator.save()

    # Evaluate on holdout if dates provided
    eval_start = args.eval_start
    eval_end = args.eval_end
    if eval_end and not eval_start:
        from datetime import datetime, timedelta
        train_end_dt = datetime.strptime(args.train_end, '%Y-%m-%d').date()
        eval_start = (train_end_dt + timedelta(days=1)).strftime('%Y-%m-%d')

    if eval_start and eval_end:
        print(f"\n{'='*70}")
        print(f"HOLDOUT EVALUATION: {eval_start} → {eval_end}")
        print(f"{'='*70}")

        if args.use_all_predictions:
            df_eval = load_all_predictions_data(bq_client, eval_start, eval_end)
        else:
            df_eval = load_graded_data(bq_client, eval_start, eval_end)

        if 'family' not in df_eval.columns:
            df_eval['family'] = df_eval['system_id'].apply(_classify_family)

        print(f"Holdout: {len(df_eval)} picks")

        if len(df_eval) == 0:
            print("No holdout data.")
            return

        # Compute P(win) for each holdout pick
        df_eval['p_win'] = [
            calibrator.predict_win_prob(row['edge'], row['family'], row['direction'])
            for _, row in df_eval.iterrows()
        ]

        # Compare: fixed edge >= 3.0 vs calibrated P(win) >= threshold
        for threshold in [0.50, 0.55, 0.60, 0.65]:
            cal_mask = df_eval['p_win'] >= threshold
            fix_mask = df_eval['edge'] >= 3.0

            cal_picks = df_eval[cal_mask]
            fix_picks = df_eval[fix_mask]

            cal_hr = cal_picks['win'].mean() * 100 if len(cal_picks) > 0 else 0
            fix_hr = fix_picks['win'].mean() * 100 if len(fix_picks) > 0 else 0

            print(f"\n  P(win) >= {threshold:.0%}:  N={len(cal_picks):3d}, "
                  f"HR={cal_hr:.1f}%, "
                  f"OVER={cal_picks[cal_picks['direction']=='OVER']['win'].mean()*100:.1f}% "
                  f"UNDER={cal_picks[cal_picks['direction']=='UNDER']['win'].mean()*100:.1f}%"
                  if len(cal_picks) > 0 else f"\n  P(win) >= {threshold:.0%}: N=0")

        # Fixed edge baseline
        fix_mask = df_eval['edge'] >= 3.0
        fix_picks = df_eval[fix_mask]
        fix_hr = fix_picks['win'].mean() * 100 if len(fix_picks) > 0 else 0
        print(f"\n  Edge >= 3.0 (baseline): N={len(fix_picks):3d}, "
              f"HR={fix_hr:.1f}%, "
              f"OVER={fix_picks[fix_picks['direction']=='OVER']['win'].mean()*100:.1f}% "
              f"UNDER={fix_picks[fix_picks['direction']=='UNDER']['win'].mean()*100:.1f}%"
              if len(fix_picks) > 0 else "\n  Edge >= 3.0: N=0")

        # Calibration monotonicity check
        print(f"\n--- Monotonicity Check (holdout) ---")
        for edge_floor in [2, 3, 4, 5, 6, 7]:
            mask = df_eval['edge'] >= edge_floor
            sub = df_eval[mask]
            if len(sub) >= 5:
                hr = sub['win'].mean() * 100
                avg_pwin = sub['p_win'].mean() * 100
                print(f"  Edge >= {edge_floor}: N={len(sub):3d}, "
                      f"actual HR={hr:.1f}%, avg P(win)={avg_pwin:.1f}%")


if __name__ == '__main__':
    main()
