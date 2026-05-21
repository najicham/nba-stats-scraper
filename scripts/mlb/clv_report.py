#!/usr/bin/env python3
"""CLV report — closing-line value for MLB pitcher-strikeout best-bets.

Derives the genuine closing line per (game, pitcher) from the raw odds feed
(`mlb_raw.oddsa_pitcher_props` — the last snapshot before first pitch, consensus
across books) and computes CLV for every pick in
`mlb_predictions.signal_best_bets_picks`.

CLV (in K-line points) = how much better the line you bet was than the close.
  OVER  pick: closing_line - line_value   (positive = line moved your way)
  UNDER pick: line_value  - closing_line
Beating the closing line is the only reliable evidence of betting edge — this
is the project's north-star metric.

Usage:
    PYTHONPATH=. python scripts/mlb/clv_report.py [--days N] [--start YYYY-MM-DD]
"""

import argparse

from google.cloud import bigquery

PROJECT = "nba-props-platform"

QUERY = """
WITH last_snap AS (
  SELECT
    game_date, player_lookup, point, minutes_before_tipoff,
    snapshot_time = MAX(snapshot_time) OVER (
      PARTITION BY game_date, player_lookup) AS is_last
  FROM `mlb_raw.oddsa_pitcher_props`
  WHERE market_key = 'pitcher_strikeouts' AND game_date >= @start
),
closing AS (
  SELECT
    game_date,
    LOWER(REGEXP_REPLACE(player_lookup, r'[^a-z]', '')) AS plk,
    APPROX_QUANTILES(point, 2)[OFFSET(1)] AS closing_line,   -- consensus median
    ANY_VALUE(minutes_before_tipoff) AS close_mins_before,
    COUNT(*) AS n_books
  FROM last_snap
  WHERE is_last
  GROUP BY 1, 2
)
SELECT
  p.game_date, p.pitcher_lookup, p.recommendation,
  CAST(p.line_value AS FLOAT64)  AS line_value,
  CAST(p.edge AS FLOAT64)        AS edge,
  p.prediction_correct,
  c.closing_line, c.close_mins_before, c.n_books,
  CASE
    WHEN c.closing_line IS NULL THEN NULL
    WHEN p.recommendation = 'OVER'  THEN c.closing_line - CAST(p.line_value AS FLOAT64)
    WHEN p.recommendation = 'UNDER' THEN CAST(p.line_value AS FLOAT64) - c.closing_line
  END AS clv
FROM `mlb_predictions.signal_best_bets_picks` p
LEFT JOIN closing c
  ON c.game_date = p.game_date
  AND c.plk = LOWER(REGEXP_REPLACE(p.pitcher_lookup, r'[^a-z]', ''))
WHERE p.game_date >= @start
ORDER BY p.game_date
"""


def _pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


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
    df = client.query(
        QUERY.replace("@start", start_expr)).to_dataframe()

    n = len(df)
    matched = df[df["clv"].notna()]
    m = len(matched)
    print("=" * 60)
    print("  MLB PITCHER-STRIKEOUT CLV REPORT")
    print("=" * 60)
    if n == 0:
        print("  No picks in range.")
        return
    print(f"  Picks in range:        {n}")
    print(f"  Closing line matched:  {m}  ({_pct(m, n)})")
    if m == 0:
        print("  No closing lines matched — check lookup-format alignment.")
        return
    print(f"  Closing snapshot age:  median {matched['close_mins_before'].median():.0f} "
          f"min before first pitch")

    pos = int((matched["clv"] > 0).sum())
    flat = int((matched["clv"] == 0).sum())
    neg = int((matched["clv"] < 0).sum())
    print(f"\n  --- CLV (K-line points) ---")
    print(f"  Beat the close (CLV>0): {pos}  ({_pct(pos, m)})")
    print(f"  Flat (CLV=0):           {flat}  ({_pct(flat, m)})")
    print(f"  Lost to close (CLV<0):  {neg}  ({_pct(neg, m)})")
    print(f"  Mean CLV:   {matched['clv'].mean():+.3f}")
    print(f"  Median CLV: {matched['clv'].median():+.3f}")

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
    print("=" * 60)
    print("  Positive mean CLV is the signal that the system has genuine edge.")
    print("  Negative/zero mean CLV = no edge, regardless of backtest ROI.")


if __name__ == "__main__":
    main()
