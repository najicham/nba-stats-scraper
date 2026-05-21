#!/usr/bin/env python3
"""Calibration report — old sigmoid p_over vs new Poisson p_over (Stage 1.4).

Reads one or more season_replay.py `all_predictions.csv` files and compares the
calibration of the pre-Stage-1.1 hand-tuned win-probability `sigmoid(0.7*edge)`
against the Stage 1.1 honest Poisson tail. Reports Brier score, a reliability
table, ECE/MCE, the decile edge->hit-rate monotonicity (the original sigmoid
bug), and a pitcher-clustered paired bootstrap on the Brier delta. Prints a
PASS/FAIL verdict against the Stage 1.4 thresholds.

`p_new` is the `p_over` column the replay recorded (the Poisson tail). `p_old`
reproduces the pre-Stage-1.1 sigmoid `sigmoid(0.7*raw_edge)` from `raw_pred_k`
(the pre-blend model output). If `raw_pred_k` is absent the harness falls back
to the blended `edge` and warns — that flatters the sigmoid, so re-run the
replay to record `raw_pred_k`.

Usage:
    python scripts/mlb/training/calibration_report.py run_dir/all_predictions.csv [more.csv ...]
    python scripts/mlb/training/calibration_report.py --self-test
"""

import argparse
import sys

import numpy as np
import pandas as pd

# Pre-Stage-1.1 hand-tuned sigmoid scale (the curve being replaced).
SIGMOID_SCALE = 0.7
N_BINS = 10
DEFAULT_BOOTSTRAP = 10000

# Stage 1.4 pass/fail thresholds (15-agent review, Agent 12).
BRIER_MIN_DELTA = 0.002   # Brier(new) must beat Brier(old) by at least this
ECE_MAX = 0.05            # ECE(new) must be at or below this
SPEARMAN_MIN = 0.95       # decile-index -> hit-rate rank correlation for "monotonic"

REQUIRED_COLUMNS = {'edge', 'p_over', 'line', 'actual_k'}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def load_predictions(paths: list) -> pd.DataFrame:
    """Load and concatenate one or more all_predictions.csv files."""
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        df['_source'] = path
        frames.append(df)
        print(f"  Loaded {len(df):,} rows from {path}")
    df = pd.concat(frames, ignore_index=True)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        sys.exit(f"FATAL: input missing required columns: {sorted(missing)}")
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Compute outcome, push flag, and both p_over series; drop pushes.

    Push = integer line that the strikeout count landed on exactly — no
    win/loss, so it is excluded from every calibration metric.
    """
    df = df.copy()
    for col in ('edge', 'p_over', 'line', 'actual_k'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['edge', 'p_over', 'line', 'actual_k'])

    is_push = (df['line'] == np.floor(df['line'])) & (df['actual_k'] == df['line'])
    n_push = int(is_push.sum())
    df = df[~is_push].reset_index(drop=True)

    df['y'] = (df['actual_k'] > df['line']).astype(int)
    df['p_new'] = df['p_over'].clip(0.0, 1.0)
    # p_old uses the RAW pre-blend edge (the true pre-Stage-1.1 system); the
    # blended edge is shrunk toward 0, which would flatter the old sigmoid.
    if 'raw_pred_k' in df.columns:
        raw_edge = pd.to_numeric(df['raw_pred_k'], errors='coerce') - df['line']
        df['p_old'] = _sigmoid(SIGMOID_SCALE * raw_edge)
    else:
        print("  WARNING: no raw_pred_k column — scoring the old sigmoid on the "
              "BLENDED edge, which flatters it. Re-run season_replay.py to record "
              "raw_pred_k for a valid old-vs-new comparison.")
        df['p_old'] = _sigmoid(SIGMOID_SCALE * df['edge'])
    df.attrs['n_push'] = n_push
    return df


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def reliability(p: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> tuple:
    """Equal-width reliability bins. Returns (rows, ece, mce).

    rows: list of (lo, hi, count, mean_predicted, empirical_rate).
    """
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    ece = 0.0
    mce = 0.0
    n = len(p)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        if i == n_bins - 1:
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p >= lo) & (p < hi)
        cnt = int(mask.sum())
        if cnt == 0:
            rows.append((lo, hi, 0, None, None))
            continue
        conf = float(p[mask].mean())
        acc = float(y[mask].mean())
        rows.append((lo, hi, cnt, conf, acc))
        gap = abs(conf - acc)
        ece += (cnt / n) * gap
        mce = max(mce, gap)
    return rows, ece, mce


def decile_monotonicity(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> tuple:
    """Bin by p decile; return (hit_rate_per_decile, inversions, spearman_rho)."""
    d = pd.DataFrame({'p': p, 'y': y})
    d['decile'] = pd.qcut(d['p'].rank(method='first'), n_bins, labels=False)
    hr = d.groupby('decile')['y'].mean()
    inversions = int((hr.diff().dropna() < 0).sum())
    rho = float(pd.Series(hr.index, dtype=float).corr(
        pd.Series(hr.values), method='spearman'))
    return hr, inversions, rho


def paired_bootstrap_brier_delta(df: pd.DataFrame, n_boot: int,
                                 seed: int = 0) -> tuple:
    """Pitcher-clustered paired bootstrap of Brier(new) - Brier(old).

    Resamples whole pitchers (Agent 5: per-start resampling understates
    variance — repeated pitchers are correlated). Returns (lo, mean, hi).
    """
    rng = np.random.default_rng(seed)
    se_old = (df['p_old'].values - df['y'].values) ** 2
    se_new = (df['p_new'].values - df['y'].values) ** 2

    if 'pitcher_lookup' in df.columns:
        groups = [g.index.values for _, g in df.groupby('pitcher_lookup')]
    else:
        print("  WARNING: no pitcher_lookup column — falling back to per-start "
              "bootstrap (CI will be too narrow)")
        groups = [np.array([i]) for i in range(len(df))]

    n_groups = len(groups)
    deltas = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, n_groups, n_groups)
        idx = np.concatenate([groups[k] for k in pick])
        deltas[b] = se_new[idx].mean() - se_old[idx].mean()
    return (float(np.percentile(deltas, 2.5)),
            float(deltas.mean()),
            float(np.percentile(deltas, 97.5)))


def _print_reliability(label: str, rows: list, ece: float, mce: float) -> None:
    print(f"\n  Reliability — {label}")
    print(f"  {'bin':>11}  {'N':>7}  {'pred':>7}  {'actual':>7}  {'gap':>7}")
    for lo, hi, cnt, conf, acc in rows:
        if cnt == 0:
            print(f"  [{lo:.1f},{hi:.1f}{']' if hi == 1.0 else ')'}  {0:>7}"
                  f"  {'—':>7}  {'—':>7}  {'—':>7}")
            continue
        print(f"  [{lo:.1f},{hi:.1f}{']' if hi == 1.0 else ')'}  {cnt:>7,}"
              f"  {conf:>7.3f}  {acc:>7.3f}  {abs(conf - acc):>7.3f}")
    print(f"  ECE = {ece:.4f}   MCE = {mce:.4f}")


def analyze(df_raw: pd.DataFrame, n_boot: int) -> dict:
    """Run the full calibration comparison and print the report."""
    df = prepare(df_raw)
    n = len(df)
    n_push = df.attrs.get('n_push', 0)
    if n == 0:
        sys.exit("FATAL: no gradeable rows after dropping pushes/NaNs.")

    y = df['y'].values
    p_old = df['p_old'].values
    p_new = df['p_new'].values

    print("\n" + "=" * 68)
    print("  CALIBRATION REPORT — sigmoid p_over  vs  Poisson p_over")
    print("=" * 68)
    print(f"\n  Gradeable starts: {n:,}   (pushes excluded: {n_push:,})")
    print(f"  OVER base rate:   {y.mean():.4f}")

    brier_old = brier(p_old, y)
    brier_new = brier(p_new, y)
    print(f"\n  Brier score   old sigmoid: {brier_old:.4f}")
    print(f"                new Poisson: {brier_new:.4f}")
    print(f"                delta (new-old): {brier_new - brier_old:+.4f}")

    rows_old, ece_old, mce_old = reliability(p_old, y)
    rows_new, ece_new, mce_new = reliability(p_new, y)
    _print_reliability("old sigmoid", rows_old, ece_old, mce_old)
    _print_reliability("new Poisson", rows_new, ece_new, mce_new)

    hr_old, inv_old, rho_old = decile_monotonicity(p_old, y)
    hr_new, inv_new, rho_new = decile_monotonicity(p_new, y)
    print(f"\n  Decile monotonicity (p_over -> empirical hit rate)")
    print(f"    old sigmoid: {inv_old} inversions, Spearman rho = {rho_old:+.3f}")
    print(f"    new Poisson: {inv_new} inversions, Spearman rho = {rho_new:+.3f}")
    print(f"    new decile hit rates: "
          f"{', '.join(f'{v:.3f}' for v in hr_new.values)}")

    lo, mean_d, hi = paired_bootstrap_brier_delta(df, n_boot)
    print(f"\n  Paired bootstrap — Brier(new) - Brier(old), "
          f"pitcher-clustered, {n_boot:,} resamples")
    print(f"    mean delta {mean_d:+.4f}   95% CI [{lo:+.4f}, {hi:+.4f}]")

    gate1 = (brier_new <= brier_old - BRIER_MIN_DELTA) and (hi < 0.0)
    gate2 = (ece_new < ece_old) and (ece_new <= ECE_MAX)
    # Spearman is the robust monotonicity check — a single decile inversion of
    # a few thousandths is finite-sample noise, not the sigmoid bug. Inversion
    # count is reported above for context but does not gate.
    gate3 = rho_new >= SPEARMAN_MIN
    verdict = gate1 and gate2 and gate3

    print(f"\n  --- Stage 1.4 verdict ---")
    print(f"  [{'PASS' if gate1 else 'FAIL'}] Brier: new beats old by >= "
          f"{BRIER_MIN_DELTA} and bootstrap CI upper bound < 0")
    print(f"  [{'PASS' if gate2 else 'FAIL'}] ECE: new < old and new <= {ECE_MAX}")
    print(f"  [{'PASS' if gate3 else 'FAIL'}] Monotonic: new decile "
          f"Spearman >= {SPEARMAN_MIN}")
    print(f"\n  >>> {'POISSON p_over VALIDATED' if verdict else 'NOT VALIDATED'} "
          f"<<<")
    print("=" * 68)

    return {
        'n_gradeable': n, 'n_push': n_push,
        'brier_old': brier_old, 'brier_new': brier_new,
        'ece_old': ece_old, 'ece_new': ece_new,
        'inversions_new': inv_new, 'spearman_new': rho_new,
        'bootstrap_ci': [lo, hi], 'verdict': verdict,
        'gate1': gate1, 'gate2': gate2, 'gate3': gate3,
    }


def _build_self_test_frame(n: int = 6000, seed: int = 1) -> pd.DataFrame:
    """Synthetic predictions with a known answer: p_new is perfectly calibrated
    (the true P(over)), p_old is overconfident + noisy. The harness must rank
    the Poisson (new) side clearly better and return a VALIDATED verdict.
    """
    rng = np.random.default_rng(seed)
    q = rng.uniform(0.05, 0.95, n)              # true P(over); p_new = q exactly
    y = rng.binomial(1, q)
    # p_old: overconfident (slope 2.5) + noise -> clearly miscalibrated.
    p_old = np.clip(0.5 + 2.5 * (q - 0.5) + rng.normal(0, 0.15, n), 0.02, 0.98)
    edge = np.log(p_old / (1.0 - p_old)) / SIGMOID_SCALE  # harness re-derives p_old
    return pd.DataFrame({
        'edge': edge,
        'raw_pred_k': 5.5 + edge,               # raw_edge == edge (no blend here)
        'p_over': q,
        'line': 5.5,                            # half-point line -> no pushes
        'actual_k': np.where(y == 1, 6.0, 5.0),
        'pitcher_lookup': rng.integers(0, 300, n).astype(str),
    })


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibration report: sigmoid vs Poisson p_over")
    parser.add_argument('csv', nargs='*',
                        help="season_replay all_predictions.csv file(s)")
    parser.add_argument('--bootstrap', type=int, default=DEFAULT_BOOTSTRAP,
                        help=f"bootstrap resamples (default {DEFAULT_BOOTSTRAP})")
    parser.add_argument('--self-test', action='store_true',
                        help="run on synthetic data and assert Poisson wins")
    args = parser.parse_args()

    if args.self_test:
        print("SELF-TEST — synthetic data (Poisson calibrated by construction)")
        df = _build_self_test_frame()
        result = analyze(df, n_boot=2000)
        assert result['brier_new'] < result['brier_old'], "Poisson Brier not better"
        assert result['gate1'], "gate1 (Brier) should pass on synthetic data"
        assert result['gate3'], "gate3 (monotonicity) should pass"
        assert result['verdict'], "self-test verdict should be VALIDATED"
        print("\nSELF-TEST PASSED")
        return

    if not args.csv:
        parser.error("provide at least one all_predictions.csv (or --self-test)")
    print("Loading prediction files...")
    df = load_predictions(args.csv)
    analyze(df, n_boot=args.bootstrap)


if __name__ == '__main__':
    main()
