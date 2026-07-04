#!/usr/bin/env python3
"""Reliability gate for edge→P(win) calibrators — ECE, Brier, monotonicity.

Evaluates one or more calibrator directories against a LIVE, provenance-verified
holdout (rows whose prediction demonstrably existed pre-game — the only strata
of `prediction_accuracy` safe to evaluate on; see
edge_calibrator.validate_training_provenance for the leak background).

Usage:
    # Gate a single calibrator against a live holdout
    PYTHONPATH=. python ml/calibration/evaluate_reliability.py \
        --calibrator-dir models/edge_calibrators/v2026-07-04-live \
        --eval-start 2026-04-01 --eval-end 2026-06-30

    # Compare several fits on the same holdout
    PYTHONPATH=. python ml/calibration/evaluate_reliability.py \
        --calibrator-dir models/edge_calibrators/v2026-07-04-live \
        --calibrator-dir models/edge_calibrators/v2026-07-03 \
        --eval-start 2026-04-01 --eval-end 2026-06-30

Exit code 0 iff every evaluated calibrator passes the gate on UNDER
(ECE <= --max-ece, monotone). UNDER is the gated direction because it is the
durable, bettable side; OVER results are reported but advisory.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.calibration.edge_calibrator import (  # noqa: E402
    EdgeCalibrator,
    _classify_family,
    load_live_verified_data,
    validate_training_provenance,
)

PROJECT_ID = 'nba-props-platform'
BIN_EDGES = np.arange(0.0, 1.05, 0.05)
MIN_BIN_N = 30           # bins below this are reported but not gated
MONOTONE_TOLERANCE = 0.02  # allowed obs-HR dip between consecutive gated bins


def ece(pred: np.ndarray, obs: np.ndarray) -> float:
    """Expected calibration error over 0.05-wide probability bins."""
    total = len(pred)
    if total == 0:
        return float('nan')
    err = 0.0
    for lo, hi in zip(BIN_EDGES[:-1], BIN_EDGES[1:]):
        mask = (pred >= lo) & (pred < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        err += (n / total) * abs(pred[mask].mean() - obs[mask].mean())
    return float(err)


def reliability_table(pred: np.ndarray, obs: np.ndarray):
    """Per-bin (n, mean predicted, observed HR) rows for populated bins."""
    rows = []
    for lo, hi in zip(BIN_EDGES[:-1], BIN_EDGES[1:]):
        mask = (pred >= lo) & (pred < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        rows.append({
            'lo': float(lo), 'hi': float(hi), 'n': n,
            'pred': float(pred[mask].mean()),
            'obs': float(obs[mask].mean()),
        })
    return rows


def is_monotone(rows) -> bool:
    """Observed HR must be non-decreasing across gated (N>=MIN_BIN_N) bins."""
    gated = [r for r in rows if r['n'] >= MIN_BIN_N]
    for prev, cur in zip(gated, gated[1:]):
        if cur['obs'] < prev['obs'] - MONOTONE_TOLERANCE:
            return False
    return True


def evaluate(cal: EdgeCalibrator, df, label: str, max_ece: float) -> dict:
    """Print the reliability report for one calibrator; return gate results."""
    df = df.copy()
    df['family'] = df['system_id'].apply(_classify_family)
    df['p_win'] = [
        cal.predict_win_prob(row['edge'], row['family'], row['direction'])
        for _, row in df.iterrows()
    ]
    print(f"\n{'=' * 74}\n{label}\n{'=' * 74}")

    results = {}
    for direction in ('ALL', 'UNDER', 'OVER'):
        sub = df if direction == 'ALL' else df[df['direction'] == direction]
        if len(sub) == 0:
            print(f"\n{direction}: no rows")
            continue
        pred = sub['p_win'].to_numpy(dtype=float)
        obs = sub['win'].to_numpy(dtype=float)
        brier = float(np.mean((pred - obs) ** 2))
        e = ece(pred, obs)
        rows = reliability_table(pred, obs)
        mono = is_monotone(rows)

        print(f"\n{direction}: N={len(sub)}  Brier={brier:.4f}  ECE={e:.4f}  "
              f"Monotone={'Yes' if mono else 'NO'}")
        for r in rows:
            flag = '' if r['n'] >= MIN_BIN_N else '  (small, ungated)'
            print(f"  [{r['lo']:.2f},{r['hi']:.2f}) N={r['n']:>5} "
                  f"pred={r['pred'] * 100:5.1f}% obs={r['obs'] * 100:5.1f}%{flag}")
        results[direction] = {'n': len(sub), 'brier': brier, 'ece': e,
                              'monotone': mono}

    under = results.get('UNDER')
    gate_pass = bool(under and under['ece'] <= max_ece and under['monotone'])
    print(f"\nGATE (UNDER: ECE <= {max_ece}, monotone): "
          f"{'PASS' if gate_pass else 'FAIL'}")
    results['gate_pass'] = gate_pass
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibrator-dir', action='append', required=True,
                        help='Calibrator directory (repeatable to compare)')
    parser.add_argument('--eval-start', required=True)
    parser.add_argument('--eval-end', required=True)
    parser.add_argument('--max-ece', type=float, default=0.05,
                        help='UNDER ECE gate threshold (default 0.05)')
    args = parser.parse_args()

    from google.cloud import bigquery
    bq_client = bigquery.Client(project=PROJECT_ID)

    print(f"Loading live-verified holdout: {args.eval_start} → {args.eval_end}")
    df = load_live_verified_data(bq_client, args.eval_start, args.eval_end)
    print(f"Holdout: {len(df)} provenance-verified rows")
    if len(df) == 0:
        print("ERROR: empty holdout")
        sys.exit(1)
    validate_training_provenance(df, verified=True)

    all_pass = True
    for cal_dir in args.calibrator_dir:
        cal = EdgeCalibrator().load(Path(cal_dir))
        res = evaluate(cal, df, label=cal_dir, max_ece=args.max_ece)
        all_pass &= res['gate_pass']

    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
