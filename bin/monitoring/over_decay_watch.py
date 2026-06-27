"""OVER decay-watch — season-resume governance harness for the fragile OVER layer.

Context (2026-06-23 research): the OVER signal layer and the high-edge OVER band
have NO cross-season edge — they were profitable ONLY in the 2025-26 scoring anomaly
and are presumed-fragile going into 2026-27 (see
docs/09-handoff/2026-06-23-signal-trustmap-RESULT.md and -edge-calibration-RESULT.md).
The agreed posture: re-grade each OVER signal on LIVE 2026-27 data by ~Dec 2026 and
DEMOTE any that does not clearly clear breakeven at N>=30 (handoff action list).

This tool automates that re-grade. It is READ-ONLY (prints a report, writes nothing).
Each watched OVER signal is PRESUMED FRAGILE and must EARN a keep verdict by clearing
the keep-threshold at N>=min_n on the current season's live graded picks. It mirrors
the exact production grading join used by ml/signals/signal_health.py:
  pick_signal_tags (deduped) ⋈ deduped prediction_accuracy, edge = ABS(pred - line).

Usage:
  # Re-grade current season (auto season-start). Run from ~Dec 2026 onward.
  PYTHONPATH=. python bin/monitoring/over_decay_watch.py

  # Explicit window / thresholds
  PYTHONPATH=. python bin/monitoring/over_decay_watch.py --season-start 2026-10-20 --min-n 30 --keep-threshold 58

  # Smoke test: re-grade 2025-26 (should REPRODUCE the OVER inflation — validates the query)
  PYTHONPATH=. python bin/monitoring/over_decay_watch.py --smoke-test
"""

import argparse
import logging
import math
from datetime import date

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'

NOMINAL_BE = 52.4   # -110 nominal breakeven (HR %)
REAL_BE = 53.5      # with vig realism

# Watched OVER signals + their prior-4-season (2021-25) pooled OVER HR — the
# "fragility baseline". A live HR near the baseline = still fragile (do NOT trust
# the 2025-26 inflation). Source: signal-trustmap + crossbook RESULT docs.
WATCHED_OVER_SIGNALS = {
    'cold_3pt_over':      {'prior4_hr': 45.0, 'note': 'sub-breakeven 4/5 prior seasons — STRONGEST demote candidate'},
    'fast_pace_over':     {'prior4_hr': 53.0, 'note': '58/47/49/59 prior; 78% in 2025-26 only'},
    'line_rising_over':   {'prior4_hr': 52.0, 'note': 'breakeven all 4 prior; 81.8% in 2025-26 only'},
    'book_disagree_over': {'prior4_hr': 50.0, 'note': 'no edge any era (prior p=0.726)'},
    'b2b_boost_over':     {'prior4_hr': 51.0, 'note': '44/53/47/62 prior (2/5 > BE) — likely 2025-26 artifact'},
}


def wilson(wins, n, z=1.96):
    """Wilson score interval for a binomial proportion (returns pct lo, hi)."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (100.0 * (centre - half) / d, 100.0 * (centre + half) / d)


def resolve_season_start(explicit):
    if explicit:
        return explicit
    try:
        from ml.signals.supplemental_data import _season_start_for
        return _season_start_for(date.today())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"_season_start_for failed ({e}); falling back to Oct-1 heuristic")
        y = date.today().year if date.today().month >= 7 else date.today().year - 1
        return f"{y}-10-01"


def verdict(hr, n, lo, hi, min_n, keep):
    """Presumed-fragile decision: a signal must EARN a keep."""
    if n < min_n:
        return ('INSUFFICIENT', f'N<{min_n} — keep in SHADOW, accumulating')
    if hr < NOMINAL_BE or hi < keep:
        return ('DEMOTE', f'fragility confirmed (HR {hr:.1f}%, CI hi {hi:.1f}% < keep {keep:.0f}%) — move to SHADOW')
    if lo > REAL_BE and hr >= keep:
        return ('KEEP', f'recovered (HR {hr:.1f}%, CI lo {lo:.1f}% > {REAL_BE}) — eligible to KEEP (needs sign-off)')
    return ('WATCH', f'marginal (HR {hr:.1f}%, CI [{lo:.1f},{hi:.1f}]) — hold in SHADOW, gather more')


def query_signals(client, season_start, end_date, watched):
    sql = f"""
    WITH deduped_pa AS (
      SELECT game_date, player_lookup, system_id, recommendation, prediction_correct,
             ABS(predicted_points - line_value) AS edge,
             ROW_NUMBER() OVER (
               PARTITION BY game_date, player_lookup, system_id
               ORDER BY CASE WHEN recommendation IN ('OVER','UNDER') THEN 0 ELSE 1 END,
                        CASE WHEN prediction_correct IS NOT NULL THEN 0 ELSE 1 END
             ) AS rn
      FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
      WHERE game_date >= @season_start AND game_date <= @end_date  -- <= correct: as-of inclusive
        AND has_prop_line = TRUE
    ),
    pst AS (
      SELECT game_date, player_lookup, system_id, signal_tags,
             ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup, system_id ORDER BY game_date) AS rn
      FROM `{PROJECT_ID}.nba_predictions.pick_signal_tags`
      WHERE game_date >= @season_start AND game_date <= @end_date  -- <= correct: as-of inclusive
    ),
    tagged AS (
      SELECT DISTINCT pst.game_date, pst.player_lookup, pst.system_id, signal_tag,
             pa.prediction_correct, pa.edge
      FROM pst
      CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
      INNER JOIN deduped_pa pa
        ON pa.game_date = pst.game_date AND pa.player_lookup = pst.player_lookup
       AND pa.system_id = pst.system_id AND pa.rn = 1
      WHERE pst.rn = 1 AND pa.prediction_correct IS NOT NULL
        AND pa.recommendation = 'OVER'
        AND signal_tag IN UNNEST(@watched)
    )
    SELECT signal_tag,
      COUNT(*) AS n,                                   COUNTIF(prediction_correct) AS wins,
      COUNTIF(edge >= 5) AS n_e5,                      COUNTIF(edge >= 5 AND prediction_correct) AS wins_e5,
      COUNTIF(edge >= 6) AS n_e6,                      COUNTIF(edge >= 6 AND prediction_correct) AS wins_e6
    FROM tagged GROUP BY signal_tag
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter('season_start', 'DATE', season_start),
        bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
        bigquery.ArrayQueryParameter('watched', 'STRING', list(watched)),
    ])
    return {r.signal_tag: r for r in client.query(sql, job_config=cfg).result()}


def query_raw_over_band(client, season_start, end_date):
    """The high-edge OVER band itself (no signal tags) — the 'edge5+ money zone' claim."""
    sql = f"""
    WITH d AS (
      SELECT recommendation, prediction_correct, ABS(predicted_points - line_value) AS edge,
             ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup, system_id
               ORDER BY CASE WHEN recommendation IN ('OVER','UNDER') THEN 0 ELSE 1 END,
                        CASE WHEN prediction_correct IS NOT NULL THEN 0 ELSE 1 END) AS rn
      FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
      WHERE game_date >= @season_start AND game_date <= @end_date  -- <= correct: as-of inclusive
        AND has_prop_line = TRUE
    )
    SELECT
      COUNTIF(edge >= 3) AS n_e3, COUNTIF(edge >= 3 AND prediction_correct) AS w_e3,
      COUNTIF(edge >= 5) AS n_e5, COUNTIF(edge >= 5 AND prediction_correct) AS w_e5,
      COUNTIF(edge >= 6) AS n_e6, COUNTIF(edge >= 6 AND prediction_correct) AS w_e6
    FROM d WHERE rn = 1 AND prediction_correct IS NOT NULL AND recommendation = 'OVER'
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter('season_start', 'DATE', season_start),
        bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
    ])
    return list(client.query(sql, job_config=cfg).result())[0]


def band(label, wins, n, min_n, keep):
    if n == 0:
        return f"    {label:<10} N=0"
    hr = 100.0 * wins / n
    lo, hi = wilson(wins, n)
    v, _ = verdict(hr, n, lo, hi, min_n, keep)
    return f"    {label:<10} N={n:>4}  HR={hr:>5.1f}%  CI[{lo:>4.1f},{hi:>4.1f}]  {v}"


def main():
    ap = argparse.ArgumentParser(description='OVER decay-watch — re-grade fragile OVER signals on live data')
    ap.add_argument('--season-start', help='Season start date YYYY-MM-DD (default: auto)')
    ap.add_argument('--end-date', help='End date YYYY-MM-DD (default: today)')
    ap.add_argument('--min-n', type=int, default=30, help='Min graded picks to render a verdict (default 30)')
    ap.add_argument('--keep-threshold', type=float, default=58.0, help='HR%% a signal must clear to KEEP (default 58)')
    ap.add_argument('--smoke-test', action='store_true',
                    help='Re-grade 2025-26 to validate the query reproduces the OVER inflation')
    args = ap.parse_args()

    if args.smoke_test:
        season_start = '2025-10-28'
        end_date = '2026-06-30'
        print("SMOKE TEST — re-grading 2025-26 (expect OVER inflation: fast_pace/line_rising high).\n")
    else:
        season_start = resolve_season_start(args.season_start)
        end_date = args.end_date or date.today().isoformat()

    client = bigquery.Client(project=PROJECT_ID)
    print("=" * 88)
    print(f"OVER DECAY-WATCH  |  window {season_start} → {end_date}  |  min_n={args.min_n}  keep>={args.keep_threshold:.0f}%")
    print(f"posture: OVER presumed FRAGILE — must EARN a keep. breakeven {NOMINAL_BE}% (real {REAL_BE}%).")
    print("note: per-signal N is BB-level (pick_signal_tags) so it accrues slowly — the RAW")
    print("      high-edge OVER band below is the high-N, faster-moving primary indicator.")
    print("=" * 88)

    try:
        rows = query_signals(client, season_start, end_date, WATCHED_OVER_SIGNALS.keys())
    except Exception as e:  # noqa: BLE001
        logger.error(f"signal query failed: {e}")
        rows = {}

    actions = []
    for sig, meta in WATCHED_OVER_SIGNALS.items():
        r = rows.get(sig)
        print(f"\n● {sig}   (prior-4-season baseline {meta['prior4_hr']:.0f}%)")
        print(f"   {meta['note']}")
        if r is None or r.n == 0:
            print(f"   no graded OVER picks in window → INSUFFICIENT (keep in shadow)")
            actions.append((sig, 'INSUFFICIENT'))
            continue
        hr = 100.0 * r.wins / r.n
        lo, hi = wilson(r.wins, r.n)
        v, why = verdict(hr, r.n, lo, hi, args.min_n, args.keep_threshold)
        delta = hr - meta['prior4_hr']
        print(f"   ALL OVER : N={r.n:>4}  HR={hr:>5.1f}%  CI[{lo:.1f},{hi:.1f}]  (vs prior-4 baseline {delta:+.1f}pp)")
        print(band('edge5+', r.wins_e5, r.n_e5, args.min_n, args.keep_threshold))
        print(band('edge6+', r.wins_e6, r.n_e6, args.min_n, args.keep_threshold))
        print(f"   ➜ {v}: {why}")
        actions.append((sig, v))

    # Raw high-edge OVER band
    print("\n" + "-" * 88)
    print("RAW high-edge OVER band (no signal tags) — the 'edge5+ money zone is OVER-false' check")
    print("-" * 88)
    try:
        b = query_raw_over_band(client, season_start, end_date)
        for lab, w, n in [('edge3+', b.w_e3, b.n_e3), ('edge5+', b.w_e5, b.n_e5), ('edge6+', b.w_e6, b.n_e6)]:
            print(band(lab, w, n, args.min_n, args.keep_threshold))
        print("   prior-4-season: edge>=6 OVER = 38.9% (sub-BE 4/4); 2025-26 = 92.6% (anomaly).")
    except Exception as e:  # noqa: BLE001
        logger.error(f"raw-band query failed: {e}")

    # Summary
    print("\n" + "=" * 88)
    print("SUMMARY")
    print("=" * 88)
    for sig, v in actions:
        print(f"  {v:<13} {sig}")
    demote = [s for s, v in actions if v == 'DEMOTE']
    keep = [s for s, v in actions if v == 'KEEP']
    if demote:
        print(f"\n  → DEMOTE to SHADOW (needs sign-off): {', '.join(demote)}")
    if keep:
        print(f"  → KEEP active (recovered, needs sign-off): {', '.join(keep)}")
    if not demote and not keep:
        print("\n  No actionable verdicts yet — accumulate more live data (run again later in season).")


if __name__ == '__main__':
    main()
