"""CLV validation — do our picks beat the closing line? (Phase 0/1 + Phase 2)

Phase 0 (feasibility, DONE) verdict: CONDITIONAL GO on 3 seasons.
  - Closing lines reconstructed from nba_raw.odds_api_player_points_props via player_lookup
    (direct join) + minutes_before_tipoff (closing = smallest positive value).
  - Coverage (graded pick -> pre-tip snapshot): 2023-24 77%, 2024-25 77%, 2025-26 88%.
    2021-22 absent; 2022-23 only 2.9% pre-tip -> EXCLUDED. 5-season CLV is NOT possible.
  - CAVEAT: pre-2025-26 has ~1 snapshot/game at ~T-2.2hr (a near-close proxy, misses the final
    ~2hr of movement); only 2025-26 has to-the-tip granularity. So pre-2025-26 CLV is conservative.

Phase 1 (first cut, DONE): edge3+ graded picks, median near-close line, by direction x season:
  UNDER mean CLV POSITIVE all 3 seasons (+0.26/+0.20/+0.63 incl. both non-anomaly seasons) ->
  UNDER edge is real (4th independent confirmation). OVER negative in normal seasons, positive
  only 2025-26 -> OVER fragility re-confirmed. BUT CLV not yet a usable per-pick gate
  (HR|+CLV ~= HR|-CLV pre-2025-26: T-2.2hr proxy + selection confound).

PHASE 2 (this file) — two questions:
  TASK 1  True-close gate (2025-26 ONLY, minutes_before_tipoff <= 15). With a real close (no
          T-2.2hr proxy), does HR|+CLV clearly beat HR|-CLV? i.e. is CLV a usable per-pick gate?
  TASK 2  CLV per signal. (2a) On ACTUAL fired tags from pick_signal_tags (UNDER) — note this
          table only exists from 2026-02-14, so it is 2025-26-partial. (2b) The candidate season-
          open UNDER slate, reconstructed from features cross-season (the real cross-season test):
          b2b_fatigue_under, slow_pace_under, downtrend_under, ft_anomaly_under,
          book_disagree_under, high_line_under. A signal with HR-edge AND +CLV is trustworthy.

CLV sign (points; positive = we beat the close):
  UNDER: line - close   (line dropped after we bet -> easier under -> +CLV)
  OVER : close - line   (line rose -> +CLV)

ARCHITECTURE — the closing-line reconstruction scans a 22M-row odds table; we do it ONCE.
  --build-cache  : run the heavy odds query, materialize per (game_date, player_lookup) median
                   close at BOTH granularities (near 0-180min, true 0-15min) to a local parquet.
                   RUN THIS IN BACKGROUND (it times out in the foreground).
  (default)      : load the parquet + cheap partition-filtered pulls (prediction_accuracy,
                   pick_signal_tags) + the local discovery feature cache; print all reports.
                   No odds scan -> fast.

Run:
  # 1. build the closing cache (background; ~minutes)
  PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/clv_validation.py --build-cache
  # 2. reports (fast, foreground)
  PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/clv_validation.py
"""

import argparse
import logging
import os

import numpy as np
import pandas as pd
from google.cloud import bigquery

logging.basicConfig(level=logging.WARNING, format='%(message)s')
logger = logging.getLogger(__name__)

PROJECT = 'nba-props-platform'

# Local closing-line cache (built by --build-cache; reused by the report path).
_SCRATCH = os.environ.get(
    'CLV_CACHE_DIR',
    '/tmp/claude-1001/-home-naji-code-nba-stats-scraper/'
    'c6a772ec-5311-4e02-b9ce-acb2210cf4db/scratchpad',
)
CACHE_PATH = os.path.join(_SCRATCH, 'clv_closing_lines.parquet')

REAL_BE = 53.5  # vig-realistic breakeven HR (%)


def _season(d: pd.Series) -> pd.Series:
    s = pd.Series(index=d.index, dtype=object)
    s[(d >= '2023-10-01') & (d <= '2024-08-01')] = '2023-24'
    s[(d >= '2024-10-01') & (d <= '2025-08-01')] = '2024-25'
    s[(d >= '2025-10-01') & (d <= '2026-08-01')] = '2025-26'
    return s


# ---------------------------------------------------------------------------
# Closing-line cache (the ONE heavy odds scan)
# ---------------------------------------------------------------------------
CLOSING_QUERY = f"""
SELECT
  game_date,
  player_lookup,
  -- median cross-book line within each window. APPROX_QUANTILES ignores NULLs,
  -- so IF(window, line, NULL) gives a conditional median in a single scan.
  APPROX_QUANTILES(IF(minutes_before_tipoff BETWEEN 0 AND 180, points_line, NULL), 2)[OFFSET(1)] AS close_near,
  APPROX_QUANTILES(IF(minutes_before_tipoff BETWEEN 0 AND  15, points_line, NULL), 2)[OFFSET(1)] AS close_true,
  COUNTIF(minutes_before_tipoff BETWEEN 0 AND 180) AS n_near,
  COUNTIF(minutes_before_tipoff BETWEEN 0 AND  15) AS n_true
FROM `{PROJECT}.nba_raw.odds_api_player_points_props`
WHERE game_date >= '2023-10-01'
  AND minutes_before_tipoff BETWEEN 0 AND 180
GROUP BY game_date, player_lookup
"""


def build_cache():
    """Run the heavy odds query and materialize the closing-line parquet."""
    logging.getLogger().setLevel(logging.INFO)
    logger.info("Building closing-line cache (scanning odds_api_player_points_props)...")
    c = bigquery.Client(project=PROJECT)
    df = c.query(CLOSING_QUERY).result().to_dataframe()
    df['game_date'] = df['game_date'].astype(str)
    df['player_lookup'] = df['player_lookup'].astype(str)
    os.makedirs(_SCRATCH, exist_ok=True)
    df.to_parquet(CACHE_PATH, index=False)
    logger.info(f"Wrote {len(df):,} (game_date, player_lookup) rows -> {CACHE_PATH}")
    logger.info(f"  rows with a true-close (n_true>0): {(df['n_true'] > 0).sum():,}")
    return df


def load_cache() -> pd.DataFrame:
    if not os.path.exists(CACHE_PATH):
        raise SystemExit(
            f"Closing cache not found at {CACHE_PATH}.\n"
            f"Build it first (IN BACKGROUND): "
            f"PYTHONPATH=. .venv/bin/python3 {__file__} --build-cache")
    df = pd.read_parquet(CACHE_PATH)
    df['game_date'] = df['game_date'].astype(str)
    df['player_lookup'] = df['player_lookup'].astype(str)
    return df


# ---------------------------------------------------------------------------
# Cheap BQ pulls (partition-filtered; NO odds scan)
# ---------------------------------------------------------------------------
def pull_picks(c: bigquery.Client) -> pd.DataFrame:
    """One graded prediction per (game_date, player_lookup): the highest-edge model.

    Mirrors the DiscoveryDataset dedup so the BQ-side (tasks 1) and feature-side (task 2b)
    populations agree. edge3+, has_prop_line, graded, 2023-26.
    """
    sql = f"""
    WITH d AS (
      SELECT game_date, player_lookup, recommendation, line_value,
             CAST(prediction_correct AS INT64) AS correct,
             ABS(predicted_points - line_value) AS edge,
             ROW_NUMBER() OVER (
               PARTITION BY game_date, player_lookup
               ORDER BY ABS(predicted_points - line_value) DESC) AS rn
      FROM `{PROJECT}.nba_predictions.prediction_accuracy`
      WHERE game_date >= '2023-10-01'
        AND has_prop_line = TRUE
        AND recommendation IN ('OVER','UNDER')
        AND prediction_correct IS NOT NULL
    )
    SELECT game_date, player_lookup, recommendation, line_value, correct, edge
    FROM d WHERE rn = 1 AND edge >= 3.0
    """
    df = c.query(sql).result().to_dataframe()
    df['game_date'] = df['game_date'].astype(str)
    df['player_lookup'] = df['player_lookup'].astype(str)
    return df


def pull_under_tags(c: bigquery.Client) -> pd.DataFrame:
    """Actual fired signal tags on UNDER picks (pick_signal_tags ⋈ prediction_accuracy).

    NOTE: pick_signal_tags only exists from 2026-02-14 (Session 254) -> 2025-26-partial only.
    Mirrors the production grading join used by ml/signals/signal_health.py & over_decay_watch.
    """
    sql = f"""
    WITH deduped_pa AS (
      SELECT game_date, player_lookup, system_id, recommendation, line_value,
             CAST(prediction_correct AS INT64) AS correct,
             ABS(predicted_points - line_value) AS edge,
             ROW_NUMBER() OVER (
               PARTITION BY game_date, player_lookup, system_id
               ORDER BY CASE WHEN recommendation IN ('OVER','UNDER') THEN 0 ELSE 1 END,
                        CASE WHEN prediction_correct IS NOT NULL THEN 0 ELSE 1 END) AS rn
      FROM `{PROJECT}.nba_predictions.prediction_accuracy`
      WHERE game_date >= '2026-01-01' AND has_prop_line = TRUE
    ),
    pst AS (
      SELECT game_date, player_lookup, system_id, signal_tags,
             ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup, system_id
                                ORDER BY game_date) AS rn
      FROM `{PROJECT}.nba_predictions.pick_signal_tags`
      WHERE game_date >= '2026-01-01'
    )
    SELECT DISTINCT pst.game_date, pst.player_lookup, signal_tag,
           pa.line_value, pa.correct, pa.edge
    FROM pst
    CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
    INNER JOIN deduped_pa pa
      ON pa.game_date = pst.game_date AND pa.player_lookup = pst.player_lookup
     AND pa.system_id = pst.system_id AND pa.rn = 1
    WHERE pst.rn = 1 AND pa.correct IS NOT NULL
      AND pa.recommendation = 'UNDER' AND pa.edge >= 3.0
    """
    df = c.query(sql).result().to_dataframe()
    df['game_date'] = df['game_date'].astype(str)
    df['player_lookup'] = df['player_lookup'].astype(str)
    return df


# ---------------------------------------------------------------------------
# CLV computation
# ---------------------------------------------------------------------------
def add_clv(df: pd.DataFrame, close_col: str) -> pd.DataFrame:
    """Attach CLV (points, sign = we beat the close) using the given close column.

    Requires columns: recommendation/direction, line_value/line, <close_col>.
    """
    out = df.copy()
    dir_col = 'recommendation' if 'recommendation' in out.columns else 'direction'
    line_col = 'line_value' if 'line_value' in out.columns else 'line'
    # BQ NUMERIC -> Decimal; coerce to float so arithmetic with the float close works.
    out[line_col] = pd.to_numeric(out[line_col], errors='coerce')
    out[close_col] = pd.to_numeric(out[close_col], errors='coerce')
    out = out[out[close_col].notna() & out[line_col].notna()].copy()
    is_under = out[dir_col].str.upper() == 'UNDER'
    out['clv'] = np.where(
        is_under,
        out[line_col] - out[close_col],      # UNDER: +CLV if line dropped
        out[close_col] - out[line_col],      # OVER : +CLV if line rose
    )
    return out


def _line(label, sub, hr_col='correct'):
    """One summary row: N, mean CLV, %+CLV, %0CLV, HR, HR|+CLV, HR|-CLV."""
    n = len(sub)
    if n == 0:
        return f"  {label:<26} N=0"
    mean_clv = sub['clv'].mean()
    pct_pos = 100 * (sub['clv'] > 0).mean()
    pct_zero = 100 * (sub['clv'] == 0).mean()
    hr = 100 * sub[hr_col].mean()
    pos = sub[sub['clv'] > 0]
    neg = sub[sub['clv'] < 0]
    hr_pos = f"{100*pos[hr_col].mean():5.1f}" if len(pos) else "  n/a"
    hr_neg = f"{100*neg[hr_col].mean():5.1f}" if len(neg) else "  n/a"
    return (f"  {label:<26} N={n:>5}  CLV={mean_clv:>+6.3f}  +CLV={pct_pos:>5.1f}%  "
            f"0CLV={pct_zero:>5.1f}%  HR={hr:>5.1f}%  "
            f"HR|+={hr_pos}% (N={len(pos):>4})  HR|-={hr_neg}% (N={len(neg):>4})")


# ---------------------------------------------------------------------------
# Phase 1 recap (re-derived from the cache, no extra odds scan)
# ---------------------------------------------------------------------------
def report_phase1(picks: pd.DataFrame):
    print("=" * 104)
    print("PHASE 1 RECAP — edge3+ picks vs NEAR-close (0-180min median). Pre-2025-26 = ~T-2.2hr proxy.")
    print("  (uses 1 deduped highest-edge pick/player-game, so CLV magnitudes run slightly below the")
    print("   Phase-1 first-cut's all-predictions numbers — the directional conclusion is identical.)")
    print("=" * 104)
    d = add_clv(picks, 'close_near')
    for direction in ('UNDER', 'OVER'):
        print(f"\n  {direction}:")
        for season in ('2023-24', '2024-25', '2025-26'):
            sub = d[(d['recommendation'] == direction) & (d['season'] == season)]
            print(_line(season, sub))


# ---------------------------------------------------------------------------
# TASK 1 — true-close gate on 2025-26
# ---------------------------------------------------------------------------
def report_task1(picks: pd.DataFrame):
    print("\n" + "=" * 104)
    print("TASK 1 — TRUE-CLOSE GATE (2025-26 only, close = median of snaps <=15min to tip)")
    print("  Question: with a REAL close (no proxy), does HR|+CLV clearly beat HR|-CLV? Is CLV a gate?")
    print("=" * 104)
    s = picks[(picks['season'] == '2025-26') & (picks['n_true'] > 0)].copy()
    d = add_clv(s, 'close_true')
    print(f"\n  coverage: {len(d):,} of {len(picks[picks['season']=='2025-26']):,} "
          f"2025-26 edge3+ picks have a true-close snapshot")
    for direction in ('UNDER', 'OVER'):
        sub = d[d['recommendation'] == direction]
        print("\n  " + direction)
        print(_line('  all edge3+', sub))
        print(_line('  edge5+', sub[sub['edge'] >= 5]))

    # CLV-as-gate calibration: HR by CLV bucket (the decisive view)
    print("\n  CLV calibration (UNDER, edge3+, true-close) — does a better number predict winning?")
    u = d[d['recommendation'] == 'UNDER'].copy()
    if len(u):
        u['clv_bucket'] = pd.cut(u['clv'], bins=[-99, -0.5, -0.001, 0.001, 0.5, 99],
                                 labels=['<=-0.5', '(-0.5,0)', '=0', '(0,0.5]', '>0.5'])
        g = u.groupby('clv_bucket', observed=True).agg(
            N=('correct', 'size'), HR=('correct', lambda x: round(100 * x.mean(), 1)),
            mean_clv=('clv', lambda x: round(x.mean(), 3)))
        print(g.to_string().replace('\n', '\n    '))
    print("\n  READ: if HR rises monotonically with the CLV bucket (and HR|+CLV >> HR|-CLV), CLV is a")
    print("        usable per-pick gate on a real close. If flat, the Phase-1 proxy caveat was the")
    print("        whole story and CLV stays a population-level thesis check, not a per-pick filter.")


# ---------------------------------------------------------------------------
# TASK 2a — CLV on actual fired UNDER tags (2025-26-partial)
# ---------------------------------------------------------------------------
def report_task2a(tags: pd.DataFrame, cache: pd.DataFrame):
    print("\n" + "=" * 104)
    print("TASK 2a — CLV on ACTUALLY-FIRED UNDER tags (pick_signal_tags ⋈ pa). "
          "Table exists 2026-02+ only.")
    print("=" * 104)
    if tags.empty:
        print("  no fired UNDER tags found in window.")
        return
    m = tags.merge(cache, on=['game_date', 'player_lookup'], how='left')
    m['recommendation'] = 'UNDER'
    # prefer true-close where present, else near-close
    m['close'] = m['close_true'].where(m['n_true'] > 0, m['close_near'])
    d = add_clv(m, 'close')
    rows = []
    for tag, sub in d.groupby('signal_tag'):
        if len(sub) < 10:
            continue
        rows.append((tag, len(sub), round(sub['clv'].mean(), 3),
                     round(100 * (sub['clv'] > 0).mean(), 1),
                     round(100 * sub['correct'].mean(), 1)))
    rows.sort(key=lambda r: -r[2])
    print(f"\n  {'signal_tag':<34} {'N':>5} {'meanCLV':>8} {'%+CLV':>7} {'HR':>6}")
    print("  " + "-" * 64)
    for tag, n, clv, pos, hr in rows:
        print(f"  {tag:<34} {n:>5} {clv:>+8.3f} {pos:>6.1f}% {hr:>5.1f}%")
    print("\n  (tags with N<10 hidden. 2025-26-partial — directional only, do NOT demote on this N.)")


# ---------------------------------------------------------------------------
# TASK 2b — candidate season-open UNDER slate, reconstructed cross-season
# ---------------------------------------------------------------------------
def candidate_predicates(df: pd.DataFrame) -> dict:
    """Reconstruct each season-open UNDER candidate from real-scale features.

    Predicates mirror scripts/.../shadow_backlog_gate.py (the formal gate that validated them).
    """
    U = df['direction'].str.upper() == 'UNDER'
    p = {}
    if 'back_to_back' in df:
        # NOTE: back_to_back is populated only in 2025-26 in this cache (0x in 2021-25) -> b2b
        # CLV is computable for 2025-26 only here. Flagged in the report.
        p['b2b_fatigue_under'] = U & (df['back_to_back'] >= 0.5)
    if 'opponent_pace' in df:
        p['slow_pace_under'] = U & (df['opponent_pace'] <= 99) & (df['opponent_pace'] > 0)
    if 'scoring_trend_slope' in df:
        p['downtrend_under'] = U & df['scoring_trend_slope'].between(-1.5, -0.5)
    if 'fta_cv_last_10' in df and 'fta_avg_last_10' in df:
        p['ft_anomaly_under'] = U & (df['fta_cv_last_10'] >= 0.5) & (df['fta_avg_last_10'] >= 5)
    if 'multi_book_line_std' in df:
        # prod predicate (handoff: "verify on multi_book_line_std, then promote"); 2023-26 only
        p['book_disagree_under'] = U & (df['multi_book_line_std'] >= 1.0)
    p['high_line_under'] = U & (df['line'] >= 25)
    return p


def report_task2b(cache: bigquery.Client):
    print("\n" + "=" * 104)
    print("TASK 2b — candidate UNDER slate via CLV, reconstructed cross-season (the real test)")
    print("  predicates mirror shadow_backlog_gate.py. close = near-close (0-180) for cross-season")
    print("  coverage; pre-2025-26 is the ~T-2.2hr proxy (conservative). +CLV cross-season = trust.")
    print("=" * 104)
    try:
        from scripts.nba.training.discovery.data_loader import DiscoveryDataset
    except Exception as e:  # noqa: BLE001
        print(f"  could not load DiscoveryDataset: {e}")
        return
    df = DiscoveryDataset(min_edge=0.0).df.copy()
    df = df[df['abs_edge'] >= 3.0].copy()
    df['game_date'] = df['game_date'].astype(str)
    df['player_lookup'] = df['player_lookup'].astype(str)
    df = df.merge(cache, on=['game_date', 'player_lookup'], how='left')
    df = df[df['close_near'].notna()].copy()
    df['recommendation'] = df['direction']
    d = add_clv(df, 'close_near')

    preds = candidate_predicates(d)
    for sig, mask in preds.items():
        print(f"\n  ● {sig}")
        sub_all = d[mask]
        if sub_all.empty:
            print("     (no matching rows in cache)")
            continue
        for season in ('2023-24', '2024-25', '2025-26'):
            sub = sub_all[sub_all['season'] == season]
            if len(sub) == 0:
                print(f"     {season}: N=0")
                continue
            mean_clv = sub['clv'].mean()
            pos = 100 * (sub['clv'] > 0).mean()
            hr = 100 * sub['correct'].mean()
            flag = ""
            if sig == 'b2b_fatigue_under' and season != '2025-26':
                flag = "  (back_to_back unpopulated pre-2025-26 in cache)"
            print(f"     {season}: N={len(sub):>4}  meanCLV={mean_clv:>+6.3f}  "
                  f"+CLV={pos:>5.1f}%  HR={hr:>5.1f}%{flag}")
        # pooled
        mean_clv = sub_all['clv'].mean()
        pos = 100 * (sub_all['clv'] > 0).mean()
        hr = 100 * sub_all['correct'].mean()
        print(f"     POOLED: N={len(sub_all):>4}  meanCLV={mean_clv:>+6.3f}  "
              f"+CLV={pos:>5.1f}%  HR={hr:>5.1f}%")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description='CLV validation — Phase 2')
    ap.add_argument('--build-cache', action='store_true',
                    help='Run the heavy odds scan and write the closing-line parquet, then exit. '
                         'RUN IN BACKGROUND.')
    args = ap.parse_args()

    if args.build_cache:
        build_cache()
        return

    cache = load_cache()
    c = bigquery.Client(project=PROJECT)

    print("Pulling picks + tags (cheap, partition-filtered)...")
    picks = pull_picks(c)
    picks['season'] = _season(pd.to_datetime(picks['game_date']).dt.strftime('%Y-%m-%d'))
    picks = picks.merge(cache, on=['game_date', 'player_lookup'], how='left')

    report_phase1(picks)
    report_task1(picks)

    tags = pull_under_tags(c)
    report_task2a(tags, cache)

    report_task2b(cache)

    print("\n" + "=" * 104)
    print("VERDICT TEMPLATE (fill from the numbers above):")
    print("  - Task 1: CLV-as-gate on a real close = [usable / not usable]")
    print("  - Task 2b: candidate signals with +CLV in BOTH non-anomaly seasons = [list] -> TRUST")
    print("            HR-edge but flat/neg CLV = [list] -> HR-only, treat with caution")
    print("=" * 104)


if __name__ == '__main__':
    main()
