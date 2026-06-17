#!/usr/bin/env python3
"""MLB BATTER-prop conditional-subset market-efficiency backtest (GO/NO-GO gate).

The naive always-OVER / always-UNDER batter scan (market_efficiency_scan.py)
already showed batter markets are efficient at the market-wide level. This
script asks the harder, stricter question that gates ANY batter-prop model
build: does ANY *conditional subset* of total_bases or hits batter props beat
the vig robustly across BOTH 2024 and 2025?

It REUSES the LOGIC of scripts/mlb/market_efficiency_scan.py (consensus line +
best-line odds vs actual, breakeven from American odds) but stratifies by
dimensions that exist in mlb_analytics.batter_game_summary and is adversarial
about multiple-testing false positives.

DATA
  Lines:   mlb_raw.oddsa_batter_props      (per-book; markets batter_total_bases,
           batter_hits). Consensus line = median point across books/snapshots;
           odds = median over/under price. Only 2 books -> "consensus" is
           effectively best-of-2, i.e. OPTIMISTIC. Edges are UPPER BOUNDS.
  Actuals: mlb_analytics.batter_game_summary. total_bases derived as
           hits + doubles + 2*triples + 3*home_runs. hits is a column.
           Stratification dims used (verified present): batting_order, is_home,
           venue. Plus line bucket + odds bucket (derived from the lines table).
           NOT used (don't exist as columns): opposing-pitcher handedness,
           day/night. Skipped in v1 by design.

PRE-REGISTERED PASS BAR (locked BEFORE looking at results):
  A subset (market x direction x dimension-value) PASSES only if it clears ALL:
    1. >= +2.0 pp edge over the -110 breakeven (52.38%) in 2024 separately
    2. >= +2.0 pp edge over the -110 breakeven in 2025 separately
    3. N >= 300 graded in EACH season
    4. Pooled (2024+2025) bootstrap 95% CI lower bound on win-rate > breakeven
    5. Survives Benjamini-Hochberg FDR at q=0.10 across ALL tested subsets
       (one-sided binomial p-value vs the subset's mean breakeven, pooled)
  Breakeven for the edge test (#1,#2) is the actual mean vig-implied breakeven
  for that subset/direction (best-line odds), NOT a flat 52.38 -- this is
  STRICTER than the -110 reference because best-line odds imply lower breakevens
  are required... we report both. The +2pp bar is measured vs the subset's own
  mean breakeven.

DEFAULT EXPECTATION: NO EDGE (efficient market). Treat any hit as a likely
false positive from multiple testing + optimistic odds until it clears the
full bar.

Usage:  PYTHONPATH=. python scripts/mlb/batter_subset_scan.py
"""
import numpy as np
import pandas as pd
from google.cloud import bigquery
from scipy import stats as sps

PROJECT = "nba-props-platform"
BREAKEVEN_110 = 0.5238095  # -110 reference breakeven
EDGE_BAR_PP = 2.0
MIN_N_PER_SEASON = 300
FDR_Q = 0.10
N_BOOT = 2000
RNG = np.random.default_rng(42)

# Consensus line + median odds per (player, game_date, market), and the
# game-context cols (is_home/venue) carried from the lines table for the
# odds/line buckets. Actuals (incl. batting_order/is_home/venue ground truth)
# come from batter_game_summary -- we use the summary's context dims since they
# are the authoritative ones requested.
LINES_Q = """
WITH last_snap AS (
  SELECT game_date,
         LOWER(REGEXP_REPLACE(player_lookup, r'[^a-zA-Z]', '')) AS plk,
         market_key, bookmaker, point, over_price, under_price,
         ROW_NUMBER() OVER (
           PARTITION BY game_date, player_lookup, market_key, bookmaker
           ORDER BY snapshot_time DESC) AS rn
  FROM `mlb_raw.oddsa_batter_props`
  WHERE game_date >= '2024-01-01'
    AND market_key IN ('batter_total_bases', 'batter_hits')
    AND point IS NOT NULL
)
SELECT game_date, plk, market_key AS market,
       APPROX_QUANTILES(point, 2)[OFFSET(1)]       AS line,
       APPROX_QUANTILES(over_price, 2)[OFFSET(1)]  AS over_odds,
       APPROX_QUANTILES(under_price, 2)[OFFSET(1)] AS under_odds
FROM last_snap
WHERE rn = 1
GROUP BY 1, 2, 3
"""

ACTUALS_Q = """
SELECT game_date,
       LOWER(REGEXP_REPLACE(player_lookup, r'[^a-zA-Z]', '')) AS plk,
       hits,
       hits + doubles + 2*triples + 3*home_runs AS total_bases,
       batting_order,
       is_home,
       venue
FROM `mlb_analytics.batter_game_summary`
WHERE game_date >= '2024-01-01'
  AND hits IS NOT NULL
"""


def breakeven(american_odds):
    """Vig-implied breakeven from American odds. NULL/0 -> NaN (NOT -110).

    CRITICAL: ~51% of oddsa_batter_props rows have NULL under_price (the feed
    posts one side per row). A leg with missing odds for a direction CANNOT be
    graded for that direction -- defaulting to -110 fabricates a 52.4%
    breakeven on heavy-favorite lines (true breakeven 59-83%), producing
    spurious "edges". So missing odds -> NaN, and those legs are dropped from
    that direction's evaluation downstream.
    """
    o = pd.to_numeric(pd.Series(american_odds), errors="coerce").to_numpy(dtype=float)
    valid = ~(np.isnan(o) | (o == 0))
    be = np.full_like(o, np.nan, dtype=float)
    neg = valid & (o < 0)
    pos = valid & (o >= 0)
    be[neg] = -o[neg] / (-o[neg] + 100.0)
    be[pos] = 100.0 / (o[pos] + 100.0)
    return be


def boot_ci_winrate(wins, n, iters=N_BOOT):
    """Bootstrap 95% CI lower bound on win rate from a Bernoulli sample."""
    if n == 0:
        return np.nan
    p = wins / n
    draws = RNG.binomial(n, p, size=iters) / n
    return np.percentile(draws, 2.5)


def build():
    client = bigquery.Client(project=PROJECT)
    lines = client.query(LINES_Q).to_dataframe()
    act = client.query(ACTUALS_Q).to_dataframe()
    df = lines.merge(act, on=["game_date", "plk"], how="inner")

    # actual value per market
    df["actual"] = np.where(df["market"] == "batter_total_bases",
                            df["total_bases"], df["hits"])
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["line"] = pd.to_numeric(df["line"], errors="coerce")
    df = df.dropna(subset=["line", "actual"])
    df["season"] = pd.to_datetime(df["game_date"]).dt.year
    df = df[df["season"].isin([2024, 2025])]

    # push handling: actual == line is a push (no action). batter hits/TB lines
    # are typically x.5 so pushes are rare, but TB lines can be integer.
    df["is_push"] = df["actual"] == df["line"]
    df = df[~df["is_push"]].copy()

    df["over_win"] = (df["actual"] > df["line"]).astype(int)
    df["under_win"] = (df["actual"] < df["line"]).astype(int)
    df["over_be"] = breakeven(df["over_odds"])
    df["under_be"] = breakeven(df["under_odds"])

    # derived stratification dims
    df["line_bucket"] = pd.cut(
        df["line"], bins=[-1, 0.5, 1.5, 2.5, 100],
        labels=["<=0.5", "1.0-1.5", "2.0-2.5", ">=3.0"])
    df["odds_bucket_over"] = pd.cut(
        pd.to_numeric(df["over_odds"], errors="coerce"),
        bins=[-100000, -150, -110, 100, 100000],
        labels=["<=-150", "-149..-110", "-109..+100", ">=+101"])
    df["odds_bucket_under"] = pd.cut(
        pd.to_numeric(df["under_odds"], errors="coerce"),
        bins=[-100000, -150, -110, 100, 100000],
        labels=["<=-150", "-149..-110", "-109..+100", ">=+101"])
    # batting order grouped
    bo = pd.to_numeric(df["batting_order"], errors="coerce")
    df["bo_group"] = pd.cut(bo, bins=[0, 2, 4, 6, 9],
                            labels=["1-2", "3-4", "5-6", "7-9"])
    return df


def eval_subset(sub, direction):
    """Per-season + pooled stats for one direction on a subset slice.

    Only legs that HAVE a valid price for `direction` are counted (be not NaN).
    """
    win_col = "over_win" if direction == "OVER" else "under_win"
    be_col = "over_be" if direction == "OVER" else "under_be"
    sub = sub[sub[be_col].notna()]
    out = {"per_season": {}}
    for season in (2024, 2025):
        s = sub[sub["season"] == season]
        n = len(s)
        if n == 0:
            out["per_season"][season] = dict(n=0)
            continue
        wr = s[win_col].mean() * 100
        be = s[be_col].mean() * 100
        out["per_season"][season] = dict(n=n, wr=wr, be=be, edge=wr - be)
    # pooled
    pooled = sub
    n = len(pooled)
    wins = int(pooled[win_col].sum())
    be_mean = pooled[be_col].mean()
    wr = wins / n * 100 if n else np.nan
    ci_lo = boot_ci_winrate(wins, n) * 100 if n else np.nan
    # one-sided binomial p vs the subset's own mean breakeven
    pval = sps.binomtest(wins, n, be_mean, alternative="greater").pvalue if n else 1.0
    out.update(dict(n=n, wr=wr, be=be_mean * 100, ci_lo=ci_lo, pval=pval,
                    edge_vs_110=wr - BREAKEVEN_110 * 100))
    return out


def main():
    df = build()
    print(f"\nLoaded {len(df):,} graded (non-push) batter prop legs "
          f"({df['season'].value_counts().to_dict()})")
    print(f"Markets: {sorted(df['market'].unique())}")
    print("ODDS NOTE: consensus = median across only 2 books -> OPTIMISTIC "
          "best-line odds. All edges are UPPER BOUNDS.\n")

    dims = ["__all__", "line_bucket", "odds_bucket_over", "odds_bucket_under",
            "bo_group", "is_home", "venue"]
    rows = []
    for market in sorted(df["market"].unique()):
        mdf = df[df["market"] == market]
        for dim in dims:
            if dim == "__all__":
                groups = [("ALL", mdf)]
            else:
                groups = [(str(v), mdf[mdf[dim] == v])
                          for v in mdf[dim].dropna().unique()]
            for val, g in groups:
                if len(g) < 50:
                    continue
                for direction in ("OVER", "UNDER"):
                    r = eval_subset(g, direction)
                    a = r["per_season"].get(2024, {})
                    b = r["per_season"].get(2025, {})
                    rows.append(dict(
                        market=market, dim=dim, val=val, dir=direction,
                        n24=a.get("n", 0), edge24=a.get("edge", np.nan),
                        n25=b.get("n", 0), edge25=b.get("edge", np.nan),
                        n=r["n"], wr=r["wr"], be=r["be"], ci_lo=r["ci_lo"],
                        pval=r["pval"]))
    res = pd.DataFrame(rows)

    # Benjamini-Hochberg FDR at q=0.10 across ALL tested subsets
    res = res.sort_values("pval").reset_index(drop=True)
    m = len(res)
    res["bh_thresh"] = (res.index + 1) / m * FDR_Q
    res["bh_pass"] = res["pval"] <= res["bh_thresh"]
    # BH is a step-up: the largest k with p<=thresh validates all smaller ranks
    passing_ranks = res.index[res["bh_pass"]]
    kmax = passing_ranks.max() if len(passing_ranks) else -1
    res["fdr_signif"] = res.index <= kmax if kmax >= 0 else False

    # Apply full pre-registered bar
    res["bar_edge_both"] = (res["edge24"] >= EDGE_BAR_PP) & (res["edge25"] >= EDGE_BAR_PP)
    res["bar_n_both"] = (res["n24"] >= MIN_N_PER_SEASON) & (res["n25"] >= MIN_N_PER_SEASON)
    res["bar_ci"] = res["ci_lo"] > res["be"]
    res["PASS"] = (res["bar_edge_both"] & res["bar_n_both"]
                   & res["bar_ci"] & res["fdr_signif"])

    print(f"Tested {m} subset x direction hypotheses.\n")
    print("=" * 110)
    print("  TOP 20 SUBSETS BY POOLED WIN-RATE EDGE vs OWN BREAKEVEN")
    print("=" * 110)
    res["pooled_edge"] = res["wr"] - res["be"]
    show = res.sort_values("pooled_edge", ascending=False).head(20)
    cols = ["market", "dim", "val", "dir", "n24", "edge24", "n25", "edge25",
            "n", "wr", "be", "ci_lo", "pval", "fdr_signif", "PASS"]
    with pd.option_context("display.max_columns", None, "display.width", 200,
                           "display.float_format", lambda x: f"{x:.2f}"):
        print(show[cols].to_string(index=False))

    winners = res[res["PASS"]]
    print("\n" + "=" * 110)
    if len(winners):
        print(f"  GO -- {len(winners)} subset(s) cleared the FULL pre-registered bar:")
        with pd.option_context("display.max_columns", None, "display.width", 200,
                               "display.float_format", lambda x: f"{x:.2f}"):
            print(winners[cols].to_string(index=False))
    else:
        print("  NO-GO -- ZERO subsets cleared the full pre-registered bar.")
        # Show how far the best candidates got
        near = res[res["bar_edge_both"] & res["bar_n_both"]]
        print(f"\n  {len(near)} subset(s) cleared edge+N in both seasons; "
              f"of those {int(near['bar_ci'].sum())} cleared the bootstrap CI "
              f"and {int(near['fdr_signif'].sum())} survived BH-FDR.")
        if len(near):
            with pd.option_context("display.max_columns", None, "display.width", 200,
                                   "display.float_format", lambda x: f"{x:.2f}"):
                print(near[cols].to_string(index=False))
    print("=" * 110)


if __name__ == "__main__":
    main()
