"""Isotonic calibration analysis for the MLB catboost_v2_regressor.

The regressor predicts strikeouts (continuous). The exporter converts
edge = abs(predicted - line) to p_over via a sigmoid:

    p_over = 1 / (1 + exp(-edge * SIGMOID_SCALE))     # SIGMOID_SCALE = 0.7

Calibrated so edge=1.0 → p_over ~0.668, edge=2.0 → p_over ~0.802. The
walk-forward 4-season replay agreed at the edge=2+ ranges. The drift
showed up in production at edge 1.0-1.5 OVER, where the model claims
~67% but observed HR was 37.9-50%.

This script:
  1. Loads graded predictions (2026 season, regressor only) from
     /tmp/mlb_regressor_graded.csv (a BQ export).
  2. Computes sigmoid-derived p_over per pick (using current SIGMOID_SCALE).
  3. Splits 70/30 train/test by game_date.
  4. Fits sklearn IsotonicRegression on the train half.
  5. Reports Brier / log-loss / reliability-diagram bins before vs after.
  6. Saves the calibrator to /tmp/mlb_regressor_isotonic_v1.pkl.

NO production code is modified by this script. The next session will
load the calibrator into `predictions/mlb/prediction_systems/
catboost_v2_regressor_predictor.py` and apply it after the sigmoid step,
behind a feature flag.
"""
import argparse
import math
import os
import pickle
import sys
from typing import List, Tuple

# Stdlib-only stats helpers — keeps the script runnable without sklearn
# even though the actual fit needs sklearn.IsotonicRegression.
def brier_score(probs: List[float], outcomes: List[int]) -> float:
    assert len(probs) == len(outcomes)
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / len(probs)


def log_loss(probs: List[float], outcomes: List[int], eps: float = 1e-9) -> float:
    total = 0.0
    for p, y in zip(probs, outcomes):
        p = max(eps, min(1 - eps, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(probs)


def reliability_bins(probs, outcomes, n_bins=10):
    """Return (bin_lo, bin_hi, n, avg_pred, actual_rate) per bucket."""
    bins = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        rows = [(p, y) for p, y in zip(probs, outcomes) if lo <= p < hi]
        if i == n_bins - 1:
            rows = [(p, y) for p, y in zip(probs, outcomes) if lo <= p <= hi]
        if not rows:
            bins.append((lo, hi, 0, None, None))
            continue
        avg_pred = sum(p for p, _ in rows) / len(rows)
        actual = sum(y for _, y in rows) / len(rows)
        bins.append((lo, hi, len(rows), avg_pred, actual))
    return bins


SIGMOID_SCALE = 0.7


def edge_to_p_over(edge: float, recommendation: str) -> float:
    """Replicates the production exporter's edge→p_over conversion.

    The model produces p_over for the OVER side. UNDER picks are scored as
    p_under = p_over_of_opposite_side, but for calibration we always
    convert to "probability that the recommended direction wins".

    For an OVER pick: probability the actual strikeouts exceed line.
    For an UNDER pick: probability the actual strikeouts fall below line.
    Sigmoid in both cases is computed off edge magnitude.
    """
    p_over = 1.0 / (1.0 + math.exp(-edge * SIGMOID_SCALE))
    # For UNDER the recommended side wins when actual < line — same
    # confidence interpretation given symmetry of the regressor's edge.
    return p_over


def load_data(path: str):
    rows = []
    with open(path) as fh:
        header = fh.readline().strip().split(",")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if len(parts) < len(header):
                continue
            try:
                edge = float(parts[idx["edge"]])
                outcome_str = parts[idx["prediction_correct"]].strip().lower()
                if outcome_str not in ("true", "false"):
                    continue
                outcome = 1 if outcome_str == "true" else 0
            except (ValueError, KeyError):
                continue
            rows.append({
                "game_date": parts[idx["game_date"]],
                "edge": edge,
                "recommendation": parts[idx["recommendation"]],
                "outcome": outcome,
            })
    rows.sort(key=lambda r: r["game_date"])
    return rows


def split_train_test(rows, train_frac=0.7):
    cut = int(len(rows) * train_frac)
    return rows[:cut], rows[cut:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="/tmp/mlb_regressor_graded.csv")
    ap.add_argument("--out", default="/tmp/mlb_regressor_isotonic_v1.pkl")
    ap.add_argument("--bins", type=int, default=10)
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"ERROR: {args.csv} not found — run the bq export first")
        return 1

    rows = load_data(args.csv)
    if len(rows) < 100:
        print(f"ERROR: only {len(rows)} usable rows — too sparse for calibration")
        return 1

    print(f"Loaded {len(rows)} graded picks from {rows[0]['game_date']} to {rows[-1]['game_date']}")

    train, test = split_train_test(rows, train_frac=0.7)
    print(f"Train: {len(train)}  Test: {len(test)}")
    print(f"Train cutoff date: {train[-1]['game_date']}  Test start: {test[0]['game_date']}")

    train_probs = [edge_to_p_over(r["edge"], r["recommendation"]) for r in train]
    train_y = [r["outcome"] for r in train]
    test_probs = [edge_to_p_over(r["edge"], r["recommendation"]) for r in test]
    test_y = [r["outcome"] for r in test]

    print()
    print("BEFORE CALIBRATION (current sigmoid)")
    print(f"  Train Brier: {brier_score(train_probs, train_y):.4f}")
    print(f"  Train LogLoss: {log_loss(train_probs, train_y):.4f}")
    print(f"  Test  Brier: {brier_score(test_probs, test_y):.4f}")
    print(f"  Test  LogLoss: {log_loss(test_probs, test_y):.4f}")
    print()
    print("Test reliability (current sigmoid):")
    print(f"  {'bin':<12} {'n':<5} {'pred':<6} {'actual':<7}")
    for lo, hi, n, pred, actual in reliability_bins(test_probs, test_y, args.bins):
        if n == 0:
            continue
        print(f"  [{lo:.1f},{hi:.1f}) {n:<5} {pred:.3f}  {actual:.3f}")

    try:
        from sklearn.isotonic import IsotonicRegression
    except ImportError:
        print("\nERROR: sklearn not installed. Install with `pip install scikit-learn`")
        return 1

    def evaluate(label, train_p, test_p):
        print()
        print(f"AFTER CALIBRATION ({label})")
        print(f"  Train Brier: {brier_score(train_p, train_y):.4f}   LogLoss: {log_loss(train_p, train_y):.4f}")
        print(f"  Test  Brier: {brier_score(test_p, test_y):.4f}   LogLoss: {log_loss(test_p, test_y):.4f}")
        print("  Test reliability:")
        print(f"    {'bin':<12} {'n':<5} {'pred':<6} {'actual':<7}")
        for lo, hi, n, pred, actual in reliability_bins(test_p, test_y, args.bins):
            if n == 0:
                continue
            print(f"    [{lo:.1f},{hi:.1f}) {n:<5} {pred:.3f}  {actual:.3f}")
        print(f"  Test Brier delta vs sigmoid: "
              f"{brier_score(test_p, test_y) - brier_score(test_probs, test_y):+.4f}")

    # --- Isotonic (pooled OVER+UNDER) ---
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(train_probs, train_y)
    evaluate("isotonic, pooled", iso.predict(train_probs).tolist(), iso.predict(test_probs).tolist())

    # --- Platt (logistic, 2 params — robust to small N) ---
    try:
        from sklearn.linear_model import LogisticRegression
        platt = LogisticRegression(C=1e6)  # weak regularization
        import numpy as np
        platt.fit(np.array(train_probs).reshape(-1, 1), train_y)
        platt_train = platt.predict_proba(np.array(train_probs).reshape(-1, 1))[:, 1].tolist()
        platt_test = platt.predict_proba(np.array(test_probs).reshape(-1, 1))[:, 1].tolist()
        evaluate("Platt logistic, pooled", platt_train, platt_test)
    except ImportError:
        print("(skipping Platt — numpy/sklearn unavailable)")

    # --- Isotonic per direction ---
    over_train = [(r["edge"], r["outcome"]) for r in train if r["recommendation"] == "OVER"]
    under_train = [(r["edge"], r["outcome"]) for r in train if r["recommendation"] == "UNDER"]
    over_test = [(r["edge"], r["outcome"]) for r in test if r["recommendation"] == "OVER"]
    under_test = [(r["edge"], r["outcome"]) for r in test if r["recommendation"] == "UNDER"]
    print()
    print(f"Direction split: OVER train={len(over_train)} test={len(over_test)} | "
          f"UNDER train={len(under_train)} test={len(under_test)}")
    if len(over_train) >= 50 and len(under_train) >= 50:
        iso_over = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso_under = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso_over.fit([edge_to_p_over(e, "OVER") for e, _ in over_train], [y for _, y in over_train])
        iso_under.fit([edge_to_p_over(e, "UNDER") for e, _ in under_train], [y for _, y in under_train])

        cal_test_split = []
        for r in test:
            base = edge_to_p_over(r["edge"], r["recommendation"])
            cal = iso_over if r["recommendation"] == "OVER" else iso_under
            cal_test_split.append(float(cal.predict([base])[0]))
        cal_train_split = []
        for r in train:
            base = edge_to_p_over(r["edge"], r["recommendation"])
            cal = iso_over if r["recommendation"] == "OVER" else iso_under
            cal_train_split.append(float(cal.predict([base])[0]))
        evaluate("isotonic, per direction", cal_train_split, cal_test_split)
    else:
        print("(skipping direction-split — not enough samples)")

    # Save the pooled isotonic as the v1 artifact (lowest LogLoss not the goal;
    # documentation of the fit is). Production decision is in handoff.
    with open(args.out, "wb") as fh:
        pickle.dump({
            "calibrator": iso,
            "sigmoid_scale": SIGMOID_SCALE,
            "trained_on_n": len(train),
            "trained_through_date": train[-1]["game_date"],
            "test_brier_before": brier_score(test_probs, test_y),
            "test_brier_after": brier_score(iso.predict(test_probs).tolist(), test_y),
            "system_id": "catboost_v2_regressor",
            "note": "Pooled isotonic — small-N artifact. Do NOT deploy as-is.",
        }, fh)
    print(f"\nSaved pooled isotonic calibrator to {args.out}")
    print("\nRECOMMENDATION: do not deploy. See handoff for full analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
