#!/usr/bin/env python3
"""Focused Signal Backtest — Cross-Model + Vegas Line Move signals only.

Session 259: Tests 4 specific signals per reviewer recommendation:
  - Signal 9:  vegas_line_move_with (sharp money agrees with model)
  - Signal 21: v9_v12_both_high_edge (both models edge >= 5, same direction)
  - Signal 22: v9_v12_disagree_strong (V9 edge >= 5, V12 opposite — skip signal)
  - Signal 23: v9_confident_v12_edge (V9 confidence >= 80% + V12 edge >= 3)

Usage:
    PYTHONPATH=. python ml/experiments/signal_backtest_focused.py
"""

from collections import defaultdict
from typing import Dict, List

from google.cloud import bigquery

# ── Eval windows ──────────────────────────────────────────────────────────────
EVAL_WINDOWS = [
    ("W1", "2026-01-02", "2026-01-15"),
    ("W2", "2026-01-16", "2026-01-31"),
    ("W3", "2026-02-01", "2026-02-08"),
    ("W4", "2026-02-09", "2026-02-14"),
]

QUERY = """
WITH v9_preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.game_date,
    pa.predicted_points,
    pa.line_value,
    pa.recommendation,
    CAST(pa.predicted_points - pa.line_value AS FLOAT64) AS edge,
    pa.actual_points,
    pa.prediction_correct,
    pa.confidence_score,
    pa.team_abbr,
    pa.opponent_team_abbr
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  WHERE pa.game_date BETWEEN @start_date AND @end_date
    AND pa.system_id = 'catboost_v9'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
    AND pa.prediction_correct IS NOT NULL
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

v12_preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.recommendation AS v12_recommendation,
    CAST(pa.predicted_points - pa.line_value AS FLOAT64) AS v12_edge,
    pa.prediction_correct AS v12_correct,
    pa.confidence_score AS v12_confidence
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  WHERE pa.game_date BETWEEN @start_date AND @end_date
    AND pa.system_id = 'catboost_v12'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

feature_data AS (
  SELECT
    fs.player_lookup,
    fs.game_date,
    fs.feature_27_value AS vegas_line_move,
    fs.feature_28_value AS has_vegas_line
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
  WHERE fs.game_date BETWEEN @start_date AND @end_date
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY fs.player_lookup, fs.game_date ORDER BY fs.updated_at DESC
  ) = 1
)

SELECT
  v9.*,
  v12.v12_recommendation,
  v12.v12_edge,
  v12.v12_correct,
  v12.v12_confidence,
  fd.vegas_line_move
FROM v9_preds v9
LEFT JOIN v12_preds v12
  ON v12.player_lookup = v9.player_lookup AND v12.game_id = v9.game_id
LEFT JOIN feature_data fd
  ON fd.player_lookup = v9.player_lookup AND fd.game_date = v9.game_date
ORDER BY v9.game_date, v9.player_lookup
"""


# ── Signal definitions ────────────────────────────────────────────────────────

def eval_vegas_line_move_with(row: Dict) -> bool:
    """Signal 9: Vegas line moved toward our prediction + edge >= 3.

    vegas_line_move > 0 means line moved UP (toward OVER).
    If model says OVER and line moved up, sharp money agrees.
    If model says UNDER and line moved down (negative), sharp money agrees.
    """
    edge = abs(row.get('edge') or 0)
    if edge < 3.0:
        return False

    vlm = row.get('vegas_line_move')
    if vlm is None:
        return False

    rec = row.get('recommendation')
    if rec == 'OVER' and vlm > 0:
        return True
    if rec == 'UNDER' and vlm < 0:
        return True
    return False


def eval_v9_v12_both_high_edge(row: Dict) -> bool:
    """Signal 21: Both V9 and V12 edge >= 5, same direction."""
    v9_edge = abs(row.get('edge') or 0)
    v12_edge = abs(row.get('v12_edge') or 0)
    v9_rec = row.get('recommendation')
    v12_rec = row.get('v12_recommendation')

    if v9_edge < 5.0 or v12_edge < 5.0:
        return False
    if v9_rec is None or v12_rec is None:
        return False
    return v9_rec == v12_rec


def eval_v9_v12_disagree_strong(row: Dict) -> bool:
    """Signal 22: V9 edge >= 5 but V12 says opposite direction (skip signal)."""
    v9_edge = abs(row.get('edge') or 0)
    v9_rec = row.get('recommendation')
    v12_rec = row.get('v12_recommendation')

    if v9_edge < 5.0:
        return False
    if v9_rec is None or v12_rec is None:
        return False
    return v9_rec != v12_rec


def eval_v9_confident_v12_edge(row: Dict) -> bool:
    """Signal 23: V9 confidence >= 80% + V12 edge >= 3, same direction."""
    v9_conf = float(row.get('confidence_score') or 0)
    v12_edge = abs(row.get('v12_edge') or 0)
    v9_rec = row.get('recommendation')
    v12_rec = row.get('v12_recommendation')

    if v9_conf < 0.80:
        return False
    if v12_edge < 3.0:
        return False
    if v9_rec is None or v12_rec is None:
        return False
    return v9_rec == v12_rec


SIGNALS = {
    'vegas_line_move_with': eval_vegas_line_move_with,
    'v9_v12_both_high_edge': eval_v9_v12_both_high_edge,
    'v9_v12_disagree_strong': eval_v9_v12_disagree_strong,
    'v9_confident_v12_edge': eval_v9_confident_v12_edge,
}


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(picks: List[Dict]) -> Dict:
    if not picks:
        return {'hr': None, 'n': 0, 'roi': None, 'wins': 0}
    correct = sum(1 for p in picks if p.get('prediction_correct'))
    total = len(picks)
    hr = round(100.0 * correct / total, 1)
    profit = correct * 100 - (total - correct) * 110
    roi = round(100.0 * profit / (total * 110), 1)
    return {'hr': hr, 'n': total, 'roi': roi, 'wins': correct}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    client = bigquery.Client(project='nba-props-platform')

    print("=" * 75)
    print("  FOCUSED SIGNAL BACKTEST — Cross-Model + Vegas Line Move")
    print("  Session 259")
    print("=" * 75)

    all_window_results = {sig: {} for sig in SIGNALS}
    all_window_picks = {sig: [] for sig in SIGNALS}
    all_rows_total = 0
    v12_coverage = {'has_v12': 0, 'total': 0}
    vlm_coverage = {'has_vlm': 0, 'total': 0}

    for window_name, start, end in EVAL_WINDOWS:
        print(f"\n--- {window_name}: {start} to {end} ---")

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start),
                bigquery.ScalarQueryParameter("end_date", "DATE", end),
            ]
        )
        rows = [dict(r) for r in client.query(QUERY, job_config=job_config).result()]
        print(f"  Loaded {len(rows)} graded V9 predictions")
        all_rows_total += len(rows)

        # Data coverage
        w_v12 = sum(1 for r in rows if r.get('v12_recommendation') is not None)
        w_vlm = sum(1 for r in rows if r.get('vegas_line_move') is not None)
        w_vlm_nonzero = sum(1 for r in rows
                            if r.get('vegas_line_move') is not None
                            and r['vegas_line_move'] != 0)
        v12_coverage['has_v12'] += w_v12
        v12_coverage['total'] += len(rows)
        vlm_coverage['has_vlm'] += w_vlm
        vlm_coverage['total'] += len(rows)
        if len(rows) > 0:
            print(f"  V12 coverage: {w_v12}/{len(rows)} ({100*w_v12/len(rows):.0f}%)")
            print(f"  Vegas line move: {w_vlm} populated, {w_vlm_nonzero} non-zero "
                  f"({100*w_vlm_nonzero/len(rows):.1f}% with actual movement)")
        else:
            print("  (no data in this window)")
            continue

        for sig_name, eval_fn in SIGNALS.items():
            qualifying = [r for r in rows if eval_fn(r)]
            m = compute_metrics(qualifying)
            all_window_results[sig_name][window_name] = m
            all_window_picks[sig_name].extend(qualifying)

            if m['n'] > 0:
                print(f"  {sig_name:<30}: N={m['n']:<4} HR={m['hr']:5.1f}% "
                      f"ROI={m['roi']:+6.1f}%")
            else:
                print(f"  {sig_name:<30}: N=0")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 75)
    print("  PER-WINDOW BREAKDOWN")
    print("=" * 75)

    windows = [w[0] for w in EVAL_WINDOWS]
    header = f"{'Signal':<30}"
    for w in windows:
        header += f" | {w:>14}"
    header += f" | {'TOTAL':>14}"
    print(f"\n{header}")
    print("-" * len(header))

    for sig_name in SIGNALS:
        line = f"{sig_name:<30}"
        for w in windows:
            m = all_window_results[sig_name].get(w, {})
            if m.get('n', 0) > 0:
                line += f" | {m['hr']:5.1f}% N={m['n']:<3}"
            else:
                line += f" |     -- N=0  "

        total_m = compute_metrics(all_window_picks[sig_name])
        if total_m['n'] > 0:
            line += f" | {total_m['hr']:5.1f}% N={total_m['n']:<3}"
        else:
            line += f" |     -- N=0  "
        print(line)

    # ── Detailed stats ────────────────────────────────────────────────────
    print("\n" + "=" * 75)
    print("  DETAILED RESULTS")
    print("=" * 75)

    for sig_name in SIGNALS:
        picks = all_window_picks[sig_name]
        m = compute_metrics(picks)
        print(f"\n{sig_name}:")
        print(f"  Total: {m['wins']}/{m['n']} = {m['hr']}% HR, {m['roi']:+.1f}% ROI")

        if not picks:
            print("  (no qualifying picks)")
            continue

        # OVER vs UNDER split
        over = [p for p in picks if p['recommendation'] == 'OVER']
        under = [p for p in picks if p['recommendation'] == 'UNDER']
        m_over = compute_metrics(over)
        m_under = compute_metrics(under)
        print(f"  OVER:  {m_over['wins']}/{m_over['n']} = "
              f"{m_over['hr'] or 0}% HR" if m_over['n'] > 0 else "  OVER: N=0")
        print(f"  UNDER: {m_under['wins']}/{m_under['n']} = "
              f"{m_under['hr'] or 0}% HR" if m_under['n'] > 0 else "  UNDER: N=0")

        # Edge distribution
        edges = [abs(p['edge']) for p in picks]
        if edges:
            print(f"  Edge: avg={sum(edges)/len(edges):.1f}, "
                  f"min={min(edges):.1f}, max={max(edges):.1f}")

        # Home/Away
        home = [p for p in picks
                if len((p.get('game_id') or '').split('_')) >= 3
                and p.get('team_abbr') == (p.get('game_id') or '').split('_')[2]]
        away = [p for p in picks if p not in home]
        m_home = compute_metrics(home)
        m_away = compute_metrics(away)
        if m_home['n'] > 0:
            print(f"  Home:  {m_home['wins']}/{m_home['n']} = {m_home['hr']}% HR")
        if m_away['n'] > 0:
            print(f"  Away:  {m_away['wins']}/{m_away['n']} = {m_away['hr']}% HR")

    # ── Combo analysis: cross-model + vegas ───────────────────────────────
    print("\n" + "=" * 75)
    print("  COMBO ANALYSIS")
    print("=" * 75)

    # Build lookup sets for combos
    def pick_keys(picks):
        return {f"{p['player_lookup']}::{p['game_id']}" for p in picks}

    sig_keys = {name: pick_keys(picks) for name, picks in all_window_picks.items()}
    all_picks_by_key = {}
    for picks in all_window_picks.values():
        for p in picks:
            key = f"{p['player_lookup']}::{p['game_id']}"
            all_picks_by_key[key] = p

    combos_to_test = [
        ('v9_v12_both_high_edge', 'vegas_line_move_with'),
        ('v9_confident_v12_edge', 'vegas_line_move_with'),
        ('v9_v12_both_high_edge', 'v9_confident_v12_edge'),
    ]

    # Also test each new signal combined with existing high_edge and minutes_surge
    # (We can check high_edge and minutes_surge conditions inline)
    for combo_a, combo_b in combos_to_test:
        overlap = sig_keys[combo_a] & sig_keys[combo_b]
        overlap_picks = [all_picks_by_key[k] for k in overlap if k in all_picks_by_key]
        m = compute_metrics(overlap_picks)
        if m['n'] > 0:
            print(f"  {combo_a} + {combo_b}: "
                  f"{m['wins']}/{m['n']} = {m['hr']}% HR, {m['roi']:+.1f}% ROI")
        else:
            print(f"  {combo_a} + {combo_b}: N=0")

    # ── Signal 22 special: disagree as SKIP signal ────────────────────────
    print("\n" + "=" * 75)
    print("  DISAGREE SIGNAL — INVERTED (picks to SKIP)")
    print("=" * 75)

    disagree_picks = all_window_picks['v9_v12_disagree_strong']
    if disagree_picks:
        m = compute_metrics(disagree_picks)
        print(f"\n  When V9 says one thing (edge>=5) and V12 says opposite:")
        print(f"  V9 is correct: {m['wins']}/{m['n']} = {m['hr']}% HR")
        print(f"  → If HR < 52.4%, these are picks we should SKIP")
        print(f"  → V12 'veto' adds value if this HR is significantly below baseline")

        # Compare to V9 high edge WITHOUT disagree
        agree_keys = sig_keys['v9_v12_both_high_edge']
        disagree_keys = sig_keys['v9_v12_disagree_strong']
        # V9 high edge picks that V12 agrees with vs disagrees with
        print(f"\n  V9 edge>=5 + V12 agrees (same dir, edge>=5): "
              f"N={len(agree_keys)}")
        print(f"  V9 edge>=5 + V12 disagrees (opposite dir):     "
              f"N={len(disagree_keys)}")

    # ── Data coverage summary ─────────────────────────────────────────────
    print("\n" + "=" * 75)
    print("  DATA COVERAGE")
    print("=" * 75)
    print(f"  Total V9 graded predictions: {all_rows_total}")
    v12_pct = 100 * v12_coverage['has_v12'] / v12_coverage['total'] if v12_coverage['total'] else 0
    vlm_pct = 100 * vlm_coverage['has_vlm'] / vlm_coverage['total'] if vlm_coverage['total'] else 0
    print(f"  V12 coverage: {v12_coverage['has_v12']}/{v12_coverage['total']} ({v12_pct:.0f}%)")
    print(f"  Vegas line move coverage: {vlm_coverage['has_vlm']}/{vlm_coverage['total']} ({vlm_pct:.0f}%)")


if __name__ == '__main__':
    main()
