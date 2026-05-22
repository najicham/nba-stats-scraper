#!/usr/bin/env python3
"""CLV report — closing-line value for MLB pitcher-strikeout best-bets.

Computes CLV for every pick in `mlb_predictions.signal_best_bets_picks` against
the genuine closing line from `mlb_raw.pitcher_props_closing` (the materialized
closing table — one row per game/pitcher/bookmaker, carrying `is_synthetic` and
`minutes_before_first_pitch`). The consensus closing line is the median across
books, preferring genuine (`is_synthetic=FALSE`) rows.

CLV (in K-line points) = how much better the line you bet was than the close.
  OVER  pick: closing_line - line_value   (positive = line moved your way)
  UNDER pick: line_value  - closing_line
Beating the closing line is the only reliable evidence of betting edge.

PRE-REGISTERED BAR (set before reading any result):
  CLV is real evidence of edge only with N >= 120 graded picks AND a
  bootstrap 95% CI lower bound strictly above 0. Anything less is a
  plumbing smoke-test, not a verdict. A leak-trained model can manufacture
  spurious positive CLV (the leak biases which pitchers get picked) — until
  the leak-free retrain ships, treat any positive read as PROVISIONAL.

Usage:
    PYTHONPATH=. python scripts/mlb/clv_report.py [--days N] [--start YYYY-MM-DD]
"""

import argparse

import numpy as np
from google.cloud import bigquery

PROJECT = "nba-props-platform"
MIN_N_FOR_VERDICT = 120

QUERY = """
WITH closing AS (
  SELECT
    game_date,
    LOWER(REGEXP_REPLACE(player_lookup, r'[^a-zA-Z]', '')) AS plk,
    -- consensus closing line: median across books, preferring genuine
    -- (non-synthetic) closing snapshots; fall back to all books otherwise.
    APPROX_QUANTILES(IF(is_synthetic = FALSE, closing_line, NULL), 2)[SAFE_OFFSET(1)]
      AS real_line,
    APPROX_QUANTILES(closing_line, 2)[SAFE_OFFSET(1)] AS any_line,
    MIN(minutes_before_first_pitch) AS close_mins_before,
    COUNTIF(is_synthetic = FALSE)   AS n_real_books,
    COUNT(*)                        AS n_books
  FROM `mlb_raw.pitcher_props_closing`
  WHERE game_date >= @start AND market_key = 'pitcher_strikeouts'
  GROUP BY 1, 2
)
SELECT
  p.game_date, p.pitcher_lookup, p.recommendation,
  CAST(p.line_value AS FLOAT64) AS line_value,
  CAST(p.edge AS FLOAT64)       AS edge,
  p.prediction_correct,
  COALESCE(c.real_line, c.any_line) AS closing_line,
  c.close_mins_before, c.n_real_books, c.n_books,
  (c.n_real_books > 0) AS is_true_closing,
  CASE
    WHEN COALESCE(c.real_line, c.any_line) IS NULL THEN NULL
    WHEN p.recommendation = 'OVER'
      THEN COALESCE(c.real_line, c.any_line) - CAST(p.line_value AS FLOAT64)
    WHEN p.recommendation = 'UNDER'
      THEN CAST(p.line_value AS FLOAT64) - COALESCE(c.real_line, c.any_line)
  END AS clv
FROM `mlb_predictions.signal_best_bets_picks` p
LEFT JOIN closing c
  ON c.game_date = p.game_date
  AND c.plk = LOWER(REGEXP_REPLACE(p.pitcher_lookup, r'[^a-zA-Z]', ''))
WHERE p.game_date >= @start
ORDER BY p.game_date
"""


def _pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def _bootstrap_ci(values, iters=5000, seed=42):
    """Percentile bootstrap 95% CI for the mean."""
    rng = np.random.default_rng(seed)
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return (float("nan"), float("nan"))
    means = v[rng.integers(0, len(v), size=(iters, len(v)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main():
    ap = argparse.ArgumentParser(description="MLB pitcher-strikeout CLV report")
    ap.add_argument("--days", type=int, default=60, help="lookback window (default 60)")
    ap.add_argument("--start", type=str, default=None, help="start date YYYY-MM-DD")
    args = ap.parse_args()

    client = bigquery.Client(project=PROJECT)
    if args.start:
        start_expr = f"DATE('{args.start}')"
    else:
        start_expr = f"DATE_SUB(CURRENT_DATE(), INTERVAL {args.days} DAY)"
    df = client.query(QUERY.replace("@start", start_expr)).to_dataframe()

    n = len(df)
    matched = df[df["clv"].notna()].copy()
    m = len(matched)
    print("=" * 64)
    print("  MLB PITCHER-STRIKEOUT CLV REPORT")
    print("=" * 64)
    if n == 0:
        print("  No picks in range.")
        return
    print(f"  Picks in range:        {n}")
    print(f"  Closing line matched:  {m}  ({_pct(m, n)})")
    if m == 0:
        print("  No closing lines matched — check pitcher_props_closing coverage "
              "and lookup-format alignment.")
        return
    true_close = matched[matched["is_true_closing"]]
    print(f"  Genuine closing (is_synthetic=FALSE source): {len(true_close)}  "
          f"({_pct(len(true_close), m)})")
    print(f"  Closing snapshot age:  median "
          f"{matched['close_mins_before'].median():.0f} min before first pitch")

    clv = matched["clv"].astype(float)
    pos = int((clv > 0).sum())
    flat = int((clv == 0).sum())
    neg = int((clv < 0).sum())
    lo, hi = _bootstrap_ci(clv.values)
    print(f"\n  --- CLV (K-line points) ---")
    print(f"  Beat the close (CLV>0): {pos}  ({_pct(pos, m)})")
    print(f"  Flat (CLV=0):           {flat}  ({_pct(flat, m)})")
    print(f"  Lost to close (CLV<0):  {neg}  ({_pct(neg, m)})")
    print(f"  Mean CLV:   {clv.mean():+.3f}   (SE {clv.std(ddof=1) / m**0.5:.3f})")
    print(f"  Median CLV: {clv.median():+.3f}")
    print(f"  Bootstrap 95% CI for mean CLV: [{lo:+.3f}, {hi:+.3f}]")

    for rec in ("OVER", "UNDER"):
        s = matched[matched["recommendation"] == rec]
        if len(s):
            print(f"    {rec:<5} n={len(s):<4} mean CLV {s['clv'].mean():+.3f}  "
                  f"beat-close {_pct((s['clv'] > 0).sum(), len(s))}")

    graded = matched[matched["prediction_correct"].notna()]
    if len(graded):
        wr = graded["prediction_correct"].mean() * 100
        pos_g = graded[graded["clv"] > 0]
        neg_g = graded[graded["clv"] <= 0]
        print(f"\n  --- CLV vs outcomes (graded n={len(graded)}) ---")
        print(f"  Overall win rate: {wr:.1f}%")
        if len(pos_g):
            print(f"  Win rate | CLV>0:  {pos_g['prediction_correct'].mean() * 100:.1f}% "
                  f"(n={len(pos_g)})")
        if len(neg_g):
            print(f"  Win rate | CLV<=0: {neg_g['prediction_correct'].mean() * 100:.1f}% "
                  f"(n={len(neg_g)})")

    print("=" * 64)
    # Pre-registered verdict — see module docstring.
    if m < MIN_N_FOR_VERDICT:
        print(f"  VERDICT: SMOKE-TEST ONLY — N={m} < {MIN_N_FOR_VERDICT}. Not a "
              f"verdict. Keep accruing closing-line data.")
    elif lo > 0:
        print(f"  VERDICT: positive CLV, 95% CI lower bound {lo:+.3f} > 0. "
              f"Genuine edge signal (PROVISIONAL until the leak-free retrain).")
    else:
        print(f"  VERDICT: no edge — CI lower bound {lo:+.3f} not above 0. "
              f"Negative/zero mean CLV = no edge, regardless of backtest ROI.")


if __name__ == "__main__":
    main()
