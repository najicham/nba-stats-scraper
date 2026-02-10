# Session 181 Handoff — Segmented Hit Rate Breakdowns for Experiment Evaluation

**Date:** 2026-02-10
**Previous:** Session 180 (two parts: experiment sweep + operational grading/comparison)

---

## What Was Done

### Added Per-Tier/Direction/Edge/Line Segmented Hit Rates to `quick_retrain.py`

Session 180 ran 34 experiments and discovered C4_MATCHUP_ONLY has 70.6% UNDER HR and C1_CHAOS has 71.4% UNDER HR — but these were invisible in the eval output, which only showed overall edge 3+ HR. The eval computed per-tier **bias** but not per-tier **hit rate**.

**Changes to `ml/experiments/quick_retrain.py`:**

1. **New function `compute_segmented_hit_rates()`** (~80 lines, after `compute_directional_hit_rates`):
   - **By tier:** Stars (25+), Starters (15-24), Role (5-14), Bench (<5)
   - **By direction:** OVER, UNDER (at edge 3+)
   - **By tier x direction:** 4 tiers x 2 directions = 8 cells
   - **By edge bucket:** [3-5), [5-7), [7+)
   - **By line range:** Low (<12.5), Mid (12.5-20.5), High (>20.5)
   - Each cell: `{hr, n, wins}` (hr=None if n=0)

2. **Call in eval section** — `segmented = compute_segmented_hit_rates(preds, y_eval.values, lines, season_avgs=season_avgs, min_edge=3.0)`

3. **New display section** "SEGMENTED HIT RATES (edge 3+)" with:
   - Tier HR table
   - Direction x Tier matrix (only non-empty cells)
   - Edge bucket table
   - Line range table
   - Best segments flagged (HR >= 58% with N >= 5)

4. **Stored in `results_json`** as `segmented_hit_rates` key — queryable in BigQuery:
   ```sql
   SELECT experiment_name,
     JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.UNDER.hr') as under_hr,
     JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.UNDER.n') as under_n,
     JSON_VALUE(results_json, '$.segmented_hit_rates.by_direction.OVER.hr') as over_hr
   FROM nba_predictions.ml_experiments
   WHERE experiment_name LIKE '%EXT%'
   ```

No deployment needed (experiment infrastructure only, not a production service).

---

## Uncommitted Changes

**Must commit and push:**
- `ml/experiments/quick_retrain.py` — segmented hit rates function + display + results_json
- `docs/09-handoff/NEXT-SESSION-PROMPT.md` — updated next session prompt
- `docs/09-handoff/2026-02-09-SESSION-180-HANDOFF.md` — updated with files modified section (was "none")
- `docs/09-handoff/2026-02-10-SESSION-181-HANDOFF.md` — this file

---

## Current State Summary

### Model Landscape (as of Feb 10)

| Model | Status | HR (Feb 4-9, matched) | Notes |
|-------|--------|----------------------|-------|
| `catboost_v9` (champion) | PRODUCTION (decaying) | 49.5% | Below breakeven |
| `catboost_v9_train1102_0131` | Shadow | 54.2% | Leading defaults candidate |
| `catboost_v9_train1102_0131_tuned` | Shadow | **55.1%** | Best overall, +24pp disagreement signal |
| C4_MATCHUP_ONLY | Experiment only | 60.0% (n=25) | Needs extended eval with segmented HR |
| C1_CHAOS | Experiment only | 58.3% (n=12) | Needs extended eval with segmented HR |

### Experiment Sweep Summary (Session 180, 34 experiments)

- **No experiment passed all governance gates** with 1 week of eval
- Volume-accuracy trade-off confirmed: less Vegas = more picks but ~50% HR
- Systematic OVER weakness across all 34 experiments (OVER HR never exceeded 54.5%)
- Two promising leads (C4, C1) need extended eval with the new segmented breakdowns

### Shadow Promotion Timeline

- **Target:** ~Feb 17-20 (2+ weeks of shadow data)
- **Leading candidate:** `catboost_v9_train1102_0131_tuned` (55.1% HR, +24pp disagreement)
- **Decision criteria:** Sustained HR > 53% over 2+ weeks, champion stays < 50%

---

## What Still Needs Doing

### P0 (Immediate)

1. **Commit and push this session's changes.** The segmented HR code is ready.

2. **Re-trigger Feb 10 predictions** if prop lines are now available:
   ```sql
   SELECT COUNT(*) FROM nba_raw.odds_api_player_points_props WHERE game_date = '2026-02-10'
   ```
   If >0, trigger predictions and backfill challengers. See Session 180 (2026-02-10) handoff for exact commands.

3. **Grade Feb 10** once games complete, then run comparison:
   ```bash
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0131_tuned --days 7
   ```

### P1 (When 2+ weeks eval data available, ~Feb 15+)

4. **Re-run C1_CHAOS and C4_MATCHUP_ONLY with extended eval** — now with segmented breakdowns:
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C1_CHAOS_EXT" \
     --rsm 0.3 --random-strength 10 --subsample 0.5 --bootstrap Bernoulli \
     --train-start 2025-11-02 --train-end 2026-01-31 \
     --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force --skip-register

   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C4_MATCHUP_EXT" \
     --category-weight "matchup=3.0" \
     --train-start 2025-11-02 --train-end 2026-01-31 \
     --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force --skip-register
   ```
   **Look for:** "SEGMENTED HIT RATES" section → segments with HR >= 58% and N >= 20+. If UNDER-only or a specific tier is profitable, consider segment-restricted deployment.

### P2 (Investigation)

5. **Investigate systematic OVER weakness.** All 34 experiments had OVER HR below breakeven. The new segmented breakdowns will show this clearly. Query OVER vs UNDER split across full `prediction_accuracy` to determine if model-specific or systemic:
   ```sql
   SELECT recommendation, COUNT(*) as n,
     ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 1) as hr
   FROM nba_predictions.prediction_accuracy
   WHERE game_date >= '2026-01-01' AND system_id = 'catboost_v9'
     AND prediction_correct IS NOT NULL
   GROUP BY 1
   ```

### P3 (Promotion Decision — ~Feb 17-20)

6. **Track tuned vs defaults.** Tuned leads (55.1% vs 54.2%) with stronger disagreement signal. Need 1-2 more weeks.

7. **If tuned wins promotion:** Update `CATBOOST_V9_MODEL_PATH` env var, recalibrate subsets and signal thresholds for tighter prediction distribution.

### P4 (Future)

8. **Signal recalibration** — 9 of 15 recent days RED. Signal tuned for champion's wider distribution.
9. **Monthly retrain cadence** — train through end of February, eval first week of March.
10. **Ensemble approaches** — combine C4 (matchup focus) + C1 (chaotic) + production model.

---

## Key References

- **Session 180 experiment sweep:** `docs/09-handoff/2026-02-09-SESSION-180-HANDOFF.md` (34 experiments, all results)
- **Session 180 operational:** `docs/09-handoff/2026-02-10-SESSION-180-HANDOFF.md` (grading, 4-way comparison)
- **Experiment infrastructure:** `docs/09-handoff/2026-02-09-SESSION-179B-HANDOFF.md` (16 CLI flags)
- **Parallel models guide:** `docs/08-projects/current/retrain-infrastructure/03-PARALLEL-MODELS-GUIDE.md`
