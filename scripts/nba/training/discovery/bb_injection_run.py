#!/usr/bin/env python3
"""INC-4 step 2: run the REAL best-bets pipeline on counterfactual walk-forward
predictions (in the scratch table) and measure BB-pipeline HR vs raw edge HR.

Monkeypatches bin.simulate_best_bets.query_predictions_with_supplements to read the
prediction SOURCE from the scratch table (predictions_table=...); everything else
(signals, negative filters, ranking, caps, supplement tables) is the REAL pipeline.
Grades BB picks against the cache's per-pick 'correct'. Read-only.

NOTE (handoff risk): the pipeline pulls live per-date signal context (model_performance_daily,
signal_health_daily, regime, blacklist) that is sparse/absent for historical dates -> historical
BB HR ~= raw + negative-filters. Scope to recent seasons (2025-26) for the first proof.

Usage:
  PYTHONPATH=. python -u scripts/nba/training/discovery/bb_injection_run.py \
      --start 2025-12-01 --end 2026-01-31 --max-dates 20
"""
import argparse
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
logging.getLogger().setLevel(logging.ERROR)
import numpy as np
import pandas as pd
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"
SCRATCH = f"{PROJECT_ID}.nba_predictions.walkforward_sim_predictions"
SYSTEM_ID = "wf_sim_v12noveg"
FILES = ['results/nba_walkforward_2021/predictions_w56_r7.csv',
         'results/nba_walkforward_2022/predictions_w56_r7.csv',
         'results/nba_walkforward_clean/predictions_w56_r7.csv',
         'results/bb_simulator/predictions_2025_26_all_models.csv']

# --- monkeypatch the prediction source onto the scratch table ---
import bin.simulate_best_bets as sbb
_orig_q = sbb.query_predictions_with_supplements
def _patched(bq_client, target_date, **kw):
    kw.setdefault('predictions_table', SCRATCH)
    return _orig_q(bq_client, target_date, **kw)
sbb.query_predictions_with_supplements = _patched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--max-dates', type=int, default=0, help='0 = all')
    args = ap.parse_args()

    c = bigquery.Client(project=PROJECT_ID)
    # cache truth for grading
    cache = pd.concat([pd.read_csv(f) for f in FILES if Path(f).exists()], ignore_index=True)
    cache = cache.drop_duplicates(['game_date', 'player_lookup', 'line'])
    cache['game_date'] = cache['game_date'].astype(str)
    truth = cache.set_index(['game_date', 'player_lookup'])['correct'].to_dict()

    dates = [str(r['game_date']) for r in c.query(
        f"SELECT DISTINCT game_date FROM `{SCRATCH}` WHERE system_id='{SYSTEM_ID}' "
        f"AND game_date BETWEEN '{args.start}' AND '{args.end}' ORDER BY game_date").result()]
    if args.max_dates:
        # evenly sample to span the window
        idx = np.linspace(0, len(dates) - 1, min(args.max_dates, len(dates))).astype(int)
        dates = [dates[i] for i in sorted(set(idx))]
    print(f"running BB pipeline on {len(dates)} dates [{args.start}..{args.end}]", flush=True)

    registry = sbb.build_default_registry()
    combo_registry = sbb.load_combo_registry(bq_client=c)

    rows = []
    for i, d in enumerate(dates, 1):
        try:
            res = sbb.simulate_date(c, d, model_id=SYSTEM_ID, multi_model=False,
                                    registry=registry, combo_registry=combo_registry,
                                    historical=True)
        except Exception as e:
            print(f"  {d}: ERROR {type(e).__name__}: {e}", flush=True)
            continue
        for p in res.get('picks', []):
            pl = p.get('player_lookup', '')
            rec = p.get('recommendation', '')
            edge = p.get('edge', p.get('abs_edge', np.nan))
            corr = truth.get((d, pl))
            rows.append({'game_date': d, 'player_lookup': pl, 'rec': rec,
                         'abs_edge': abs(edge) if edge == edge else np.nan, 'correct': corr})
        if i % 5 == 0 or i == len(dates):
            print(f"  [{i}/{len(dates)}] {d}: cand={res.get('candidates')} picks={len(res.get('picks',[]))}", flush=True)

    bb = pd.DataFrame(rows, columns=['game_date', 'player_lookup', 'rec', 'abs_edge', 'correct'])
    if bb.empty:
        print("\n=== BB-pipeline picks: 0 ===")
        print("  Pipeline RAN but produced no picks. Expected for this config: a single V12_NOVEG model")
        print("  has edges too tight for the OVER edge_floor (6.0), and the synthetic system_id has no")
        print("  model_performance_daily/signal_health history so model-dependent signals can't fire")
        print("  (UNDER can't reach real_sc>=2). Next: seed sim-model health rows OR use fleet-scale edges")
        print("  OR lower the floor for the sim. (See INC-4 handoff 'main risk'.)")
        return
    print(f"\n=== BB-pipeline picks: {len(bb)} (graded: {bb['correct'].notna().sum()}) ===")
    g = bb[bb['correct'].notna()].copy()
    g['correct'] = g['correct'].astype(int)
    def hr(df):
        return (100*df.correct.mean(), len(df)) if len(df) else (float('nan'), 0)
    print(f"  ALL BB:        {hr(g)[0]:.1f}% (N={hr(g)[1]})")
    for lo, lab in [(3, 'edge3+'), (5, 'edge5+')]:
        s = g[g.abs_edge >= lo]
        a = hr(s); o = hr(s[s.rec == 'OVER']); u = hr(s[s.rec == 'UNDER'])
        print(f"  {lab}: {a[0]:.1f}% (N={a[1]}) | OVER {o[0]:.1f}% (N={o[1]}) | UNDER {u[0]:.1f}% (N={u[1]})")
    print("\n  (compare to RAW single-model edge HR from edge_belief_audit.py)")


if __name__ == '__main__':
    main()
