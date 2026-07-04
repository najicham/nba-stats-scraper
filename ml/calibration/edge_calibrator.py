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

# Bulk-batch leak guard thresholds (see validate_training_provenance).
BULK_BATCH_MAX_SHARE = 0.30      # one graded_at day may not hold >30% of rows...
BULK_BATCH_MAX_SPAN_DAYS = 14    # ...while spanning >14 days of game_dates
LATE_GRADE_DAYS = 10             # graded >10d after game = suspect unless verified


def _classify_family(system_id: str) -> str:
    """Classify system_id into model family for calibration grouping."""
    from shared.config.cross_model_subsets import classify_system_id
    return classify_system_id(system_id)


class LeakedTrainingDataError(ValueError):
    """Raised when training rows carry the bulk-backfill grading signature."""


def validate_training_provenance(df, verified: bool = False) -> None:
    """Reject training data carrying the backfill-leak signature (2026-07-03).

    The 2022-25 strata of `prediction_accuracy` are BACKFILL-LEAKED: ~123.8K rows
    spanning 4 seasons of game_dates were all graded in one batch on 2026-01-10
    (impossible WRs — the Session 458 leakage signature). Additional bulk batches
    exist on 2026-01-25 and 2026-02-22 that MIX leaked (prediction created after
    the game) and legitimate (live prediction, graded late) rows.

    Rules enforced on the frame (requires a `graded_at` column; `game_date` too):
      1. No single DATE(graded_at) may hold > BULK_BATCH_MAX_SHARE of rows while
         spanning > BULK_BATCH_MAX_SPAN_DAYS of game_dates — that is a bulk
         backfill batch, not live grading.
      2. If `verified=False` (rows were NOT provenance-checked against pre-game
         `player_prop_predictions.created_at`), any row graded > LATE_GRADE_DAYS
         after its game_date is rejected outright.

    Raises LeakedTrainingDataError. Pass `verified=True` only for frames loaded
    via load_live_verified_data(), where every row was already confirmed to come
    from a prediction created by the end of its game day.
    """
    import pandas as pd

    if 'graded_at' not in df.columns:
        raise LeakedTrainingDataError(
            "training frame has no graded_at column — cannot verify provenance; "
            "load it (or use load_live_verified_data)"
        )
    if len(df) == 0:
        return

    game_date = pd.to_datetime(df['game_date'])
    grade_day = pd.to_datetime(df['graded_at']).dt.tz_localize(None).dt.normalize()

    # Rule 1: bulk-batch signature. Fatal only for unverified frames — when
    # every row's prediction is confirmed pre-game (verified=True), a bulk
    # graded_at day just means "graded late in a batch", which is harmless
    # (the leak risk lives entirely in prediction creation time).
    by_day = df.groupby(grade_day)
    for day, idx in by_day.groups.items():
        share = len(idx) / len(df)
        span = (game_date.loc[idx].max() - game_date.loc[idx].min()).days
        if share > BULK_BATCH_MAX_SHARE and span > BULK_BATCH_MAX_SPAN_DAYS:
            msg = (
                f"bulk-batch grading signature: {share:.0%} of training rows "
                f"graded on {day.date()} spanning {span}d of game_dates."
            )
            if verified:
                logger.warning(
                    "%s Rows are provenance-verified (pre-game created_at), "
                    "so proceeding — late batch grading of live predictions "
                    "is harmless.", msg
                )
            else:
                raise LeakedTrainingDataError(
                    f"{msg} These rows are (or mix with) backfilled "
                    f"predictions — refuse to fit. Use "
                    f"load_live_verified_data() or filter the batch out."
                )

    # Rule 2: late grades without provenance verification
    if not verified:
        late = (grade_day - game_date).dt.days > LATE_GRADE_DAYS
        if late.any():
            raise LeakedTrainingDataError(
                f"{int(late.sum())}/{len(df)} rows graded > {LATE_GRADE_DAYS}d after "
                f"their game without provenance verification. Backfill batches mix "
                f"leaked and live rows — use load_live_verified_data(), which keeps "
                f"only rows whose prediction existed before the game."
            )


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

        # Per-direction pooled fallbacks (_pooled_OVER / _pooled_UNDER).
        # These are the primary fallback when a (family, direction) key is
        # absent — falling back to the direction-pooled _global first was the
        # 2026-07-03 "direction-blind" bug (OVER and UNDER have structurally
        # different edge→WR curves; pooling them serves a wrong curve to both).
        for direction in ('OVER', 'UNDER'):
            mask = np.asarray(directions) == direction
            n = int(mask.sum())
            if n < min_samples:
                logger.info(f"Skipping _pooled_{direction}: only {n} samples")
                continue
            iso_dir = IsotonicRegression(
                y_min=0.0, y_max=1.0, out_of_bounds='clip', increasing=True
            )
            X = np.asarray(edges, dtype=np.float64)[mask]
            y = np.asarray(wins, dtype=np.float64)[mask]
            iso_dir.fit(X, y)
            key = f"_pooled_{direction}"
            self.calibrators[key] = iso_dir
            self.stats[key] = {
                'n_samples': n,
                'win_rate': float(y.mean()),
                'mean_edge': float(X.mean()),
                'edge_range': (float(X.min()), float(X.max())),
            }
            logger.info(f"Fitted {key}: N={n}, WR={y.mean():.1%}")

        # Global fallback calibrator (all data) — last resort only.
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

        Fallback chain: (family, direction) → _pooled_{direction} → _global.
        The per-direction pooled curve comes before _global so an unknown
        family still gets a direction-correct curve (OVER and UNDER differ
        structurally; the direction-pooled _global is a last resort).
        """
        for key in (f"{family}_{direction}" if family else None,
                    f"_pooled_{direction}",
                    '_global'):
            if key and key in self.calibrators:
                return float(self.calibrators[key].predict([edge])[0])
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


def load_live_verified_data(bq_client, start_date: str, end_date: str):
    """Load graded predictions whose provenance is verified pre-game.

    This is the CLEAN loader (2026-07-03 leak remediation): a row qualifies
    only if a prediction for the same (player, game, system) exists in
    `player_prop_predictions` with `created_at` before the end of its game day
    (UTC) — i.e. the prediction demonstrably existed before/at tip-off, so a
    late `graded_at` means "graded late", not "backfilled". This keeps the
    ~8K legitimate live rows that the bulk grading batches mixed in and drops
    the backfilled (leaked) ones.
    """
    query = f"""
    WITH first_created AS (
        SELECT player_lookup, game_date, system_id,
               MIN(created_at) AS first_created_at
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY 1, 2, 3
    )
    SELECT
        ROUND(ABS(pa.predicted_points - pa.line_value), 1) AS edge,
        pa.recommendation AS direction,
        pa.system_id,
        pa.prediction_correct AS win,
        pa.game_date,
        pa.graded_at
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
    JOIN first_created fc
        ON fc.player_lookup = pa.player_lookup
        AND fc.game_date = pa.game_date
        AND fc.system_id = pa.system_id
    WHERE pa.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND pa.prediction_correct IS NOT NULL
        AND pa.has_prop_line = TRUE
        AND pa.recommendation IN ('OVER', 'UNDER')
        AND pa.is_voided IS NOT TRUE
        AND pa.line_value IS NOT NULL
        AND ABS(pa.predicted_points - pa.line_value) >= 1.0
        AND fc.first_created_at < TIMESTAMP_ADD(TIMESTAMP(pa.game_date), INTERVAL 1 DAY)
    ORDER BY pa.game_date
    """
    return bq_client.query(query).to_dataframe()


def load_graded_data(bq_client, start_date: str, end_date: str):
    """Load graded best bets picks with edge, model, direction, outcome."""
    query = f"""
    SELECT
        bb.edge,
        bb.recommendation AS direction,
        bb.source_model_family AS family,
        bb.system_id,
        pa.prediction_correct AS win,
        pa.game_date,
        pa.graded_at
    FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` bb
    JOIN `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        ON bb.player_lookup = pa.player_lookup
        AND bb.game_date = pa.game_date
        AND bb.system_id = pa.system_id
        AND pa.recommendation = bb.recommendation
        AND pa.line_value = bb.line_value
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
        pa.prediction_correct AS win,
        pa.game_date,
        pa.graded_at
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
    parser.add_argument('--live-verified', action='store_true',
                        help='Train on provenance-verified live predictions '
                             '(pre-game created_at; the clean loader)')
    parser.add_argument('--save-dir', default=None,
                        help='Directory to save pkls (default: models/edge_calibrators)')
    parser.add_argument('--min-samples', type=int, default=15,
                        help='Min rows to fit a (family, direction) key. Small-N '
                             'isotonic curves saturate at 0/100%% in the tails — '
                             'use ~300 for stable per-family curves; thinner '
                             'groups fall back to _pooled_{direction}.')
    parser.add_argument('--pooled-only', action='store_true',
                        help='Keep only _pooled_OVER/_pooled_UNDER/_global keys. '
                             'Per-family isotonic curves need cross-season volume '
                             '(a few hundred live rows per key still saturate at '
                             '0/100%% in the sparse tails) — ship pooled-only '
                             'until per-family graded volume accrues.')
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
    verified = False
    if args.live_verified:
        df_train = load_live_verified_data(bq_client, args.train_start, args.train_end)
        verified = True
        print(f"Loaded {len(df_train)} provenance-verified live predictions")
    elif args.use_all_predictions:
        df_train = load_all_predictions_data(bq_client, args.train_start, args.train_end)
        print(f"Loaded {len(df_train)} graded predictions (all models)")
    else:
        df_train = load_graded_data(bq_client, args.train_start, args.train_end)
        print(f"Loaded {len(df_train)} graded best bets picks")

    if len(df_train) == 0:
        print("ERROR: No training data found")
        return

    # LEAK GUARD (2026-07-03): refuse to fit on bulk-backfill-graded strata.
    validate_training_provenance(df_train, verified=verified)

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
        min_samples=args.min_samples,
    )

    if args.pooled_only:
        keep = {k for k in calibrator.calibrators if k.startswith('_')}
        dropped = sorted(set(calibrator.calibrators) - keep)
        calibrator.calibrators = {k: v for k, v in calibrator.calibrators.items()
                                  if k in keep}
        calibrator.stats = {k: v for k, v in calibrator.stats.items() if k in keep}
        if dropped:
            print(f"--pooled-only: dropped per-family keys: {', '.join(dropped)}")

    calibrator.print_calibration_curve()
    calibrator.save(Path(args.save_dir) if args.save_dir else None)

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

        if args.live_verified:
            df_eval = load_live_verified_data(bq_client, eval_start, eval_end)
        elif args.use_all_predictions:
            df_eval = load_all_predictions_data(bq_client, eval_start, eval_end)
        else:
            df_eval = load_graded_data(bq_client, eval_start, eval_end)
        if len(df_eval):
            validate_training_provenance(df_eval, verified=args.live_verified)

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
