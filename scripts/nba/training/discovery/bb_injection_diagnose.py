#!/usr/bin/env python3
"""INC-4 diagnostic: run the REAL BB pipeline on the scratch table and report the
aggregated filter-rejection histogram + candidate-level edge/real_sc distributions,
so we know EXACTLY which gate produces picks=0 before choosing a fix.

Read-only. Single-model path on 2025-26 (where the game_stats CTE / behavioral
supplements are populated, hardcoded WHERE game_date >= '2025-10-22').

Usage:
  PYTHONPATH=. python -u scripts/nba/training/discovery/bb_injection_diagnose.py \
      --start 2025-12-01 --end 2026-01-31 --max-dates 15
"""
import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
logging.getLogger().setLevel(logging.ERROR)
import numpy as np
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"
SCRATCH = f"{PROJECT_ID}.nba_predictions.walkforward_sim_predictions"
SYSTEM_ID = "wf_sim_v12noveg"

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
    ap.add_argument('--max-dates', type=int, default=15)
    ap.add_argument('--multi-model', action='store_true')
    args = ap.parse_args()

    c = bigquery.Client(project=PROJECT_ID)
    dates = [str(r['game_date']) for r in c.query(
        f"SELECT DISTINCT game_date FROM `{SCRATCH}` WHERE system_id='{SYSTEM_ID}' "
        f"AND game_date BETWEEN '{args.start}' AND '{args.end}' ORDER BY game_date").result()]
    if args.max_dates and len(dates) > args.max_dates:
        idx = np.linspace(0, len(dates) - 1, args.max_dates).astype(int)
        dates = [dates[i] for i in sorted(set(idx))]
    print(f"diagnosing {len(dates)} dates [{args.start}..{args.end}] multi_model={args.multi_model}", flush=True)

    registry = sbb.build_default_registry()
    combo_registry = sbb.load_combo_registry(bq_client=c)

    rej = Counter()
    tot_cand = tot_picks = 0
    # candidate-level distributions (pulled from raw predictions, pre-pipeline)
    over_edges, under_edges = [], []
    for i, d in enumerate(dates, 1):
        try:
            res = sbb.simulate_date(c, d, model_id=None if args.multi_model else SYSTEM_ID,
                                    multi_model=args.multi_model, registry=registry,
                                    combo_registry=combo_registry, historical=True)
        except Exception as e:
            print(f"  {d}: ERROR {type(e).__name__}: {e}", flush=True)
            continue
        tot_cand += res.get('candidates', 0)
        tot_picks += len(res.get('picks', []))
        fs = res.get('filter_summary', {})
        rejected = fs.get('rejected', {})
        for f, n in rejected.items():
            rej[f] += n
        top = sorted(rejected.items(), key=lambda x: -x[1])
        print(f"  [{i}/{len(dates)}] {d}: cand={res.get('candidates')} picks={len(res.get('picks',[]))}", flush=True)
        print(f"      rejected: {top}", flush=True)

    print(f"\n=== TOTAL: candidates={tot_cand} picks={tot_picks} ===")
    print("rejection histogram (filter -> count):")
    for f, n in rej.most_common():
        print(f"  {f:38s} {n}")


if __name__ == '__main__':
    main()
