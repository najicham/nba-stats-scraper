#!/usr/bin/env python3
"""MLB prop-market efficiency scan — is any market "soft" enough to bet?

Project C2 ("softer markets") asks whether a less-modeled MLB prop market is
exploitable where starter strikeouts are not. This tool answers it decisively:
for every market it joins the consensus pre-game line + vig odds to the actual
outcome and measures whether a *naive directional bet* beats its breakeven.

Markets scanned:
  - 5 pitcher markets from `mlb_raw.oddsa_pitcher_props` (strikeouts, outs,
    hits_allowed, earned_runs, walks) vs `mlb_analytics.pitcher_game_summary`.
  - 8 batter markets from `mlb_raw.bp_batter_props` (self-contained — has
    `actual_value`, `is_push`, consensus lines, odds).

Pre-registered bar for "worth a real leak-free backtest":
  a naive OVER- or UNDER-always bet clears its vig-implied breakeven by
  >= 2.0 pp in BOTH 2024 AND 2025, with N >= 300 graded each season.
  A one-season-only edge is treated as noise.

VERDICT (run 2026-05-21, ~519K rows): every one of the 13 markets is
efficient under this test — no market shows a stable NAIVE directional bias
that clears the vig. Batter breakevens use best-line (optimistic) odds, so the
true batter edges are even worse than reported.

SCOPE NOTE: this rules out the crudest form of "soft" — a market-wide
always-OVER / always-UNDER bias. It does NOT rule out a CONDITIONAL edge on a
subset (specific pitchers, parks, day/night, books). Read the verdict as
"no free always-one-side money exists," not "no exploitable structure exists
anywhere." A conditional-subset C2 remains untested by design.

This is a market-EFFICIENCY scan (is the line biased), not a CLV test — a
several-hours-pre-game line is a valid "market number" for measuring bias.
Universe = the player actually appeared (the non-voided prop universe).

Usage:  PYTHONPATH=. python scripts/mlb/market_efficiency_scan.py [--pitcher|--batter]
"""
import argparse

import numpy as np
import pandas as pd
from google.cloud import bigquery

PROJECT = "nba-props-platform"
MIN_N_PER_SEASON = 300
EDGE_BAR_PP = 2.0

PITCHER_Q = """
WITH last_snap AS (
  SELECT game_date, player_lookup, market_key, bookmaker,
         point, over_price, under_price,
         ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup, market_key, bookmaker
                            ORDER BY snapshot_time DESC) AS rn
  FROM `mlb_raw.oddsa_pitcher_props`
  WHERE game_date >= '2024-01-01' AND point IS NOT NULL
),
consensus AS (
  SELECT game_date,
         LOWER(REGEXP_REPLACE(player_lookup, r'[^a-zA-Z]', '')) AS plk,
         market_key,
         APPROX_QUANTILES(point, 2)[OFFSET(1)]       AS line,
         APPROX_QUANTILES(over_price, 2)[OFFSET(1)]  AS over_odds,
         APPROX_QUANTILES(under_price, 2)[OFFSET(1)] AS under_odds
  FROM last_snap WHERE rn = 1
  GROUP BY 1, 2, 3
),
actuals AS (
  SELECT game_date,
         LOWER(REGEXP_REPLACE(player_lookup, r'[^a-zA-Z]', '')) AS plk,
         strikeouts, walks_allowed, hits_allowed, earned_runs,
         -- innings_pitched is dual-encoded: frac .1/.2 = baseball notation,
         -- frac .3/.7 = decimal thirds. Disambiguate -> true outs recorded.
         CAST(FLOOR(innings_pitched) AS INT64) * 3 +
           CASE ROUND(MOD(CAST(innings_pitched*10 AS INT64), 10))
             WHEN 1 THEN 1 WHEN 2 THEN 2 WHEN 3 THEN 1 WHEN 7 THEN 2
             ELSE 0 END AS outs_recorded
  FROM `mlb_analytics.pitcher_game_summary`
  WHERE game_date >= '2024-01-01' AND innings_pitched > 0
)
SELECT c.market_key AS market,
       EXTRACT(YEAR FROM c.game_date) AS season,
       c.line, c.over_odds, c.under_odds,
       CASE c.market_key
         WHEN 'pitcher_strikeouts'   THEN a.strikeouts
         WHEN 'pitcher_walks'        THEN a.walks_allowed
         WHEN 'pitcher_hits_allowed' THEN a.hits_allowed
         WHEN 'pitcher_earned_runs'  THEN a.earned_runs
         WHEN 'pitcher_outs'         THEN a.outs_recorded
       END AS actual
FROM consensus c
JOIN actuals a USING (game_date, plk)
"""
# Pitcher markets post integer lines (e.g. K line = 6.0) -> real pushes when
# actual == line. is_push is computed in Python after load (see main()).

BATTER_Q = """
SELECT market_name AS market,
       EXTRACT(YEAR FROM game_date) AS season,
       COALESCE(over_consensus_line, over_line)   AS line,
       over_odds, under_odds,
       actual_value AS actual,
       is_push
FROM `mlb_raw.bp_batter_props`
WHERE game_date >= '2024-01-01'
  AND is_scored = TRUE AND actual_value IS NOT NULL
  AND over_odds IS NOT NULL AND over_odds != 0
  AND under_odds IS NOT NULL AND under_odds != 0
  AND COALESCE(over_consensus_line, over_line) IS NOT NULL
"""


def breakeven(american_odds):
    """Vig-implied breakeven win prob from American odds."""
    o = pd.to_numeric(pd.Series(american_odds), errors="coerce").to_numpy(dtype=float)
    o = np.where((o == 0) | np.isnan(o), -110.0, o)
    return np.where(o < 0, -o / (-o + 100.0), 100.0 / (o + 100.0))


def scan(df, label):
    print(f"\n{'=' * 100}\n  {label}  ({len(df):,} rows)\n{'=' * 100}")
    print(f"{'market':<22}{'season':>7}{'N':>7}{'MAE':>7}{'bias':>8}"
          f"{'OVER%':>8}{'be':>7}{'O-edge':>8}{'UND%':>8}{'be':>7}{'U-edge':>8}")
    print("-" * 100)
    verdict = {}
    for mkt in sorted(df["market"].dropna().unique()):
        sub = df[df["market"] == mkt]
        per_season = {}
        for season in sorted(sub["season"].dropna().unique()):
            s = sub[(sub["season"] == season) & (~sub["is_push"].fillna(False))]
            s = s.dropna(subset=["line", "actual"])
            if len(s) < 30:
                continue
            n = len(s)
            over_hr = (s["actual"] > s["line"]).mean() * 100
            und_hr = (s["actual"] < s["line"]).mean() * 100
            o_be = breakeven(s["over_odds"]).mean() * 100
            u_be = breakeven(s["under_odds"]).mean() * 100
            mae = (s["actual"] - s["line"]).abs().mean()
            bias = (s["actual"] - s["line"]).mean()
            o_edge, u_edge = over_hr - o_be, und_hr - u_be
            per_season[int(season)] = dict(n=n, o_edge=o_edge, u_edge=u_edge)
            print(f"{str(mkt):<22}{int(season):>7}{n:>7}{mae:>7.2f}{bias:>+8.2f}"
                  f"{over_hr:>8.1f}{o_be:>7.1f}{o_edge:>+8.1f}"
                  f"{und_hr:>8.1f}{u_be:>7.1f}{u_edge:>+8.1f}")
        if 2024 in per_season and 2025 in per_season:
            a, b = per_season[2024], per_season[2025]
            ok_n = a["n"] >= MIN_N_PER_SEASON and b["n"] >= MIN_N_PER_SEASON
            over_ok = a["o_edge"] >= EDGE_BAR_PP and b["o_edge"] >= EDGE_BAR_PP and ok_n
            und_ok = a["u_edge"] >= EDGE_BAR_PP and b["u_edge"] >= EDGE_BAR_PP and ok_n
            verdict[mkt] = ("WORTH BACKTEST (OVER)" if over_ok else
                            "WORTH BACKTEST (UNDER)" if und_ok else
                            "efficient / no stable edge")
        else:
            verdict[mkt] = "insufficient cross-season data"
        print()
    print(f"  VERDICT (>= +{EDGE_BAR_PP}pp over breakeven, BOTH 2024 & 2025):")
    for mkt, v in verdict.items():
        print(f"    {str(mkt):<24} {v}")
    return verdict


def main():
    ap = argparse.ArgumentParser(description="MLB prop-market efficiency scan")
    ap.add_argument("--pitcher", action="store_true", help="pitcher markets only")
    ap.add_argument("--batter", action="store_true", help="batter markets only")
    args = ap.parse_args()
    do_pitcher = args.pitcher or not args.batter
    do_batter = args.batter or not args.pitcher

    client = bigquery.Client(project=PROJECT)
    if do_pitcher:
        pdf = client.query(PITCHER_Q).to_dataframe()
        # Real pushes: integer pitcher lines where actual == line.
        pdf["is_push"] = (pd.to_numeric(pdf["actual"], errors="coerce")
                          == pd.to_numeric(pdf["line"], errors="coerce"))
        scan(pdf,
             "PITCHER markets — oddsa_pitcher_props consensus vs pitcher_game_summary")
    if do_batter:
        scan(client.query(BATTER_Q).to_dataframe(),
             "BATTER markets — bp_batter_props (best-line odds: edges are upper bounds)")


if __name__ == "__main__":
    main()
