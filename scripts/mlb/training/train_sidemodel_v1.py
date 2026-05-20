#!/usr/bin/env python3
"""
Train the MLB binary side-model (Path B, slice 2).

Fits two candidates -- logistic regression and a small LightGBM -- on the
reconstructed feature set from build_sidemodel_training_set.py and evaluates
them head-to-head against the production sigmoid-from-edge baseline. Five
governance gates decide deployability. A deployable artifact is saved ONLY
if the best candidate passes EVERY gate.

The artifact obeys the contract at the top of
predictions/mlb/sidemodel/binary_v1.py: a pickled dict with keys
{model, feature_names, version}. `model` is a single estimator exposing
predict_proba(). `feature_names` is a SUBSET of the raw columns
load_batch_features serves, plus the recommendation one-hots the loader
injects automatically.

Why `edge` / `predicted_strikeouts` are NOT features: the slice-1 worker
calls sidemodel.score(features, recommendation) where `features` is only
the load_batch_features dict -- it never passes the regressor outputs. A
model that needed `edge` would return None for every pick. `edge` is still
loaded into the CSV and used here purely to compute the sigmoid baseline.

Run (after the builder):
    PYTHONPATH=. .venv/bin/python3 scripts/mlb/training/train_sidemodel_v1.py
"""

import argparse
import math
import os
import pickle
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

# Reuse the stdlib metric helpers from the isotonic analysis script.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from isotonic_calibration_analysis import (  # noqa: E402
    brier_score, log_loss, reliability_bins,
)

SIGMOID_SCALE = 0.7  # production exporter edge -> p_over scale

# Side-model feature set -- raw load_batch_features column names, all drawn
# from the regressor's zero-tolerance CORE set so they are reliably non-null
# at score time. FanGraphs (fip/gb_pct) and Statcast are deliberately
# excluded: they are NaN-tolerant for the regressor but binary_v1.score()
# rejects ANY missing feature, which would zero out shadow coverage.
SIDEMODEL_FEATURES = [
    "k_avg_last_3", "k_avg_last_5", "k_avg_last_10", "k_std_last_10",
    "ip_avg_last_5", "season_k_per_9", "era_rolling_10", "whip_rolling_10",
    "opponent_team_k_rate", "ballpark_k_factor", "days_rest",
    "pitch_count_avg_last_5", "k_avg_vs_line", "strikeouts_line",
    "over_implied_prob",
]
RECO_ONEHOTS = ["recommendation_OVER", "recommendation_UNDER"]

MIN_COVERAGE = 0.97  # drop a feature below this train coverage (score-time safety)

GATES = {
    "class_balance_lo": 0.40,
    "class_balance_hi": 0.60,
    "min_brier_improvement": 0.01,
    "min_auc": 0.55,
    "direction_brier_tolerance": 0.005,
    "max_reliability_dev": 0.15,
    "reliability_min_bin_n": 10,
}


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def chronological_split(df: pd.DataFrame, train_frac: float = 0.75):
    """Split by date: train = first `train_frac` of distinct game_dates."""
    dates = sorted(df["game_date"].unique())
    cut = max(1, min(int(len(dates) * train_frac), len(dates) - 1))
    train_dates = set(dates[:cut])
    train = df[df["game_date"].isin(train_dates)].copy()
    test = df[~df["game_date"].isin(train_dates)].copy()
    return train, test


def make_X(df: pd.DataFrame, feature_names: list) -> np.ndarray:
    return df[feature_names].astype(float).values


def sigmoid_p_correct(edge: float) -> float:
    """P(recommended side wins) implied by the production edge -> sigmoid.

    The regressor's edge is signed (predicted_K - line). The pick is for the
    side edge points to, so the implied confidence in the *pick* is always
    1/(1+exp(-|edge|*scale)).
    """
    return 1.0 / (1.0 + math.exp(-abs(edge) * SIGMOID_SCALE))


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
def fit_logistic(X: np.ndarray, y: np.ndarray):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, C=1.0)),
    ])
    pipe.fit(X, y)
    return pipe


def fit_lightgbm(X_fit, y_fit, X_es, y_es):
    import lightgbm as lgb

    clf = lgb.LGBMClassifier(
        n_estimators=100, num_leaves=15, learning_rate=0.05,
        random_state=42, verbose=-1,
    )
    clf.fit(
        X_fit, y_fit,
        eval_set=[(X_es, y_es)],
        callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(0)],
    )
    return clf


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------
def eval_probs(probs, y) -> dict:
    from sklearn.metrics import roc_auc_score

    probs, y = list(probs), list(y)
    return {
        "n": len(y),
        "brier": brier_score(probs, y),
        "log_loss": log_loss(probs, y),
        "auc": float(roc_auc_score(y, probs)) if len(set(y)) > 1 else float("nan"),
    }


def direction_brier(probs, y, recos) -> dict:
    probs, y, recos = list(probs), list(y), list(recos)
    out = {}
    for d in ("OVER", "UNDER"):
        idx = [i for i, r in enumerate(recos) if r == d]
        out[d] = (brier_score([probs[i] for i in idx], [y[i] for i in idx])
                  if idx else float("nan"))
    return out


def print_reliability(label: str, probs, y, n_bins: int = 10):
    print(f"  Reliability ({label}):")
    print(f"    {'bin':<12}{'n':>5}{'pred':>9}{'actual':>9}{'dev':>8}")
    for lo, hi, n, pred, actual in reliability_bins(list(probs), list(y), n_bins):
        if n == 0:
            continue
        print(f"    [{lo:.1f},{hi:.1f}){n:>5}{pred:>9.3f}{actual:>9.3f}"
              f"{abs(pred - actual):>8.3f}")


def check_gates(cand_metrics, sig_metrics, train_win_rate,
                cand_dir, sig_dir, reliability) -> dict:
    """Apply the 5 governance gates. Returns a dict of bool results."""
    tol = GATES["direction_brier_tolerance"]
    brier_impr = sig_metrics["brier"] - cand_metrics["brier"]

    over_ok = (math.isnan(cand_dir["OVER"])
               or cand_dir["OVER"] <= sig_dir["OVER"] + tol)
    under_ok = (math.isnan(cand_dir["UNDER"])
                or cand_dir["UNDER"] <= sig_dir["UNDER"] + tol)

    bad_bins = [
        b for b in reliability
        if b[2] >= GATES["reliability_min_bin_n"]
        and abs(b[3] - b[4]) > GATES["max_reliability_dev"]
    ]

    res = {
        "class_balance": GATES["class_balance_lo"] <= train_win_rate <= GATES["class_balance_hi"],
        "brier_improvement": brier_impr >= GATES["min_brier_improvement"],
        "auc": (not math.isnan(cand_metrics["auc"])) and cand_metrics["auc"] >= GATES["min_auc"],
        "direction_stability": over_ok and under_ok,
        "calibration": len(bad_bins) == 0,
    }
    res["all_passed"] = all(res.values())
    res["_brier_improvement"] = brier_impr
    res["_bad_bins"] = bad_bins
    return res


def print_gate_table(name: str, gates: dict):
    print(f"  Governance gates -- {name}:")
    labels = {
        "class_balance": "Class balance 0.40-0.60 (train win rate)",
        "brier_improvement": f"Test Brier improvement >= {GATES['min_brier_improvement']} vs sigmoid",
        "auc": f"Test AUC >= {GATES['min_auc']}",
        "direction_stability": "OVER & UNDER Brier each improve / within 0.005",
        "calibration": f"No N>=10 reliability bin off-diagonal > {GATES['max_reliability_dev']}",
    }
    for key, label in labels.items():
        print(f"    [{'PASS' if gates[key] else 'FAIL'}] {label}")
    extra = f"(brier delta vs sigmoid: {gates['_brier_improvement']:+.4f})"
    print(f"    {'>>> ALL GATES PASSED' if gates['all_passed'] else '>>> GATES FAILED'} {extra}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Train MLB binary side-model v1")
    ap.add_argument("--csv", default="/tmp/mlb_sidemodel_training.csv")
    ap.add_argument("--out-dir", default="/tmp")
    ap.add_argument("--bins", type=int, default=10)
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"ERROR: {args.csv} not found -- run build_sidemodel_training_set.py first")
        return 1

    df = pd.read_csv(args.csv)
    df = df.sort_values("game_date").reset_index(drop=True)
    print("=" * 66)
    print("  MLB BINARY SIDE-MODEL v1 -- TRAINING")
    print("=" * 66)
    print(f"  Loaded {len(df)} rows  ({df['game_date'].min()} -> {df['game_date'].max()})")

    # Coverage filter -- a feature that is sparse in training would also be
    # sparse at score time, and binary_v1.score() drops a pick on ANY missing
    # feature. Anything below MIN_COVERAGE is excluded from the artifact.
    features = []
    print("  Feature coverage (train+test):")
    for f in SIDEMODEL_FEATURES:
        cov = df[f].notna().mean() if f in df.columns else 0.0
        keep = cov >= MIN_COVERAGE
        print(f"    {f:<26} {cov * 100:6.1f}%  {'keep' if keep else 'DROP'}")
        if keep:
            features.append(f)
    if len(features) < 5:
        print(f"ERROR: only {len(features)} features survived coverage filter -- aborting")
        return 1

    df["recommendation_OVER"] = (df["recommendation"] == "OVER").astype(float)
    df["recommendation_UNDER"] = (df["recommendation"] == "UNDER").astype(float)
    feature_names = features + RECO_ONEHOTS
    print(f"  Using {len(feature_names)} features ({len(features)} numeric + 2 one-hot)")

    # Chronological 75/25 split by date.
    train, test = chronological_split(df, train_frac=0.75)
    print(f"  Train: {len(train)} rows ({train['game_date'].min()} -> "
          f"{train['game_date'].max()})")
    print(f"  Test:  {len(test)} rows ({test['game_date'].min()} -> "
          f"{test['game_date'].max()})")

    train_win_rate = float(train["outcome"].mean())
    print(f"  Train win rate: {train_win_rate:.4f}   "
          f"Test win rate: {test['outcome'].mean():.4f}")

    X_train, y_train = make_X(train, feature_names), train["outcome"].values
    X_test, y_test = make_X(test, feature_names), test["outcome"].values
    test_recos = test["recommendation"].tolist()

    # LightGBM early-stopping carve: last 15% of TRAIN dates.
    train_dates = sorted(train["game_date"].unique())
    es_cut = max(1, min(int(len(train_dates) * 0.85), len(train_dates) - 1))
    fit_dates = set(train_dates[:es_cut])
    lgb_fit = train[train["game_date"].isin(fit_dates)]
    lgb_es = train[~train["game_date"].isin(fit_dates)]
    print(f"  LightGBM early-stop carve: fit {len(lgb_fit)} / es-val {len(lgb_es)}")

    # ---- Baseline: production sigmoid-from-edge ----
    sig_test = [sigmoid_p_correct(e) for e in test["edge"].values]
    sig_metrics = eval_probs(sig_test, y_test)
    sig_dir = direction_brier(sig_test, y_test, test_recos)

    # ---- Candidate 1: logistic regression ----
    log_model = fit_logistic(X_train, y_train)
    log_test = log_model.predict_proba(X_test)[:, 1]
    log_metrics = eval_probs(log_test, y_test)
    log_dir = direction_brier(log_test, y_test, test_recos)
    log_rel = reliability_bins(list(log_test), list(y_test), args.bins)

    # ---- Candidate 2: small LightGBM ----
    lgb_model = fit_lightgbm(
        make_X(lgb_fit, feature_names), lgb_fit["outcome"].values,
        make_X(lgb_es, feature_names), lgb_es["outcome"].values,
    )
    lgb_test = lgb_model.predict_proba(X_test)[:, 1]
    lgb_metrics = eval_probs(lgb_test, y_test)
    lgb_dir = direction_brier(lgb_test, y_test, test_recos)
    lgb_rel = reliability_bins(list(lgb_test), list(y_test), args.bins)

    # ---- Report ----
    print()
    print("-" * 66)
    print("  TEST-SET METRICS")
    print("-" * 66)
    hdr = f"  {'model':<22}{'brier':>9}{'logloss':>10}{'auc':>9}"
    print(hdr)
    for name, m in [("sigmoid baseline", sig_metrics),
                    ("logistic", log_metrics),
                    ("lightgbm", lgb_metrics)]:
        print(f"  {name:<22}{m['brier']:>9.4f}{m['log_loss']:>10.4f}{m['auc']:>9.4f}")
    print()
    print("  Per-direction Brier (test):")
    print(f"    {'model':<22}{'OVER':>10}{'UNDER':>10}")
    for name, d in [("sigmoid baseline", sig_dir),
                    ("logistic", log_dir),
                    ("lightgbm", lgb_dir)]:
        print(f"    {name:<22}{d['OVER']:>10.4f}{d['UNDER']:>10.4f}")
    print()
    print_reliability("logistic", log_test, y_test, args.bins)
    print()
    print_reliability("lightgbm", lgb_test, y_test, args.bins)
    print()

    # ---- Gates ----
    log_gates = check_gates(log_metrics, sig_metrics, train_win_rate,
                            log_dir, sig_dir, log_rel)
    lgb_gates = check_gates(lgb_metrics, sig_metrics, train_win_rate,
                            lgb_dir, sig_dir, lgb_rel)
    print_gate_table("logistic", log_gates)
    print()
    print_gate_table("lightgbm", lgb_gates)
    print()

    # ---- Verdict ----
    candidates = [
        ("logistic", log_metrics, log_gates, log_model, log_dir, log_rel),
        ("lightgbm", lgb_metrics, lgb_gates, lgb_model, lgb_dir, lgb_rel),
    ]
    deployable = [c for c in candidates if c[2]["all_passed"]]
    deployable.sort(key=lambda c: c[1]["brier"])  # lowest test Brier wins

    print("=" * 66)
    if not deployable:
        print("  VERDICT: DEAD_END")
        beat = [c[0] for c in candidates
                if c[2]["_brier_improvement"] >= GATES["min_brier_improvement"]]
        if not beat:
            print("  Neither candidate beats the sigmoid baseline on test Brier "
                  f"by >= {GATES['min_brier_improvement']}.")
        else:
            print(f"  Beat sigmoid on Brier: {beat} -- but failed other gates.")
        print("  No artifact saved. Document the dead end in the SCOPING doc.")
        print("=" * 66)
        return 0

    name, metrics, gates, model, dirb, rel = deployable[0]
    version = f"binary_v1_{date.today():%Y%m%d}"
    out_path = os.path.join(args.out_dir, f"{version}.pkl")
    artifact = {
        "model": model,
        "feature_names": feature_names,
        "version": version,
        "metadata": {
            "candidate": name,
            "trained_at": datetime.utcnow().isoformat(),
            "training_rows": len(train),
            "test_rows": len(test),
            "train_date_range": [str(train["game_date"].min()),
                                 str(train["game_date"].max())],
            "test_date_range": [str(test["game_date"].min()),
                                str(test["game_date"].max())],
            "features": feature_names,
            "train_win_rate": train_win_rate,
            "test_metrics": {k: metrics[k] for k in ("n", "brier", "log_loss", "auc")},
            "test_direction_brier": dirb,
            "sigmoid_baseline": {k: sig_metrics[k] for k in ("brier", "log_loss", "auc")},
            "brier_improvement_vs_sigmoid": gates["_brier_improvement"],
        },
    }
    with open(out_path, "wb") as fh:
        pickle.dump(artifact, fh)

    print(f"  VERDICT: DEPLOY  ({name})")
    print(f"  Artifact: {out_path}  version={version}")
    print(f"  Test Brier {metrics['brier']:.4f} vs sigmoid {sig_metrics['brier']:.4f} "
          f"({gates['_brier_improvement']:+.4f})   AUC {metrics['auc']:.4f}")
    print()
    print("  Next steps (require explicit user approval before the env-var step):")
    print(f"    1. gsutil cp {out_path} \\")
    print(f"         gs://nba-props-platform-ml-models/mlb/sidemodel/{version}.pkl")
    print("    2. STOP for user sign-off.")
    print("    3. gcloud run services update mlb-prediction-worker --region=us-west2 \\")
    print(f"         --update-env-vars=\"MLB_SIDEMODEL_PATH="
          f"gs://nba-props-platform-ml-models/mlb/sidemodel/{version}.pkl\"")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
