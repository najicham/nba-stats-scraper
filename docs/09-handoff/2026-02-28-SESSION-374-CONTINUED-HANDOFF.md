# Session 374 Continued Handoff — Filter Experiments & Fleet Triage

**Date:** 2026-02-28
**Prior Session:** 374 (2 shadow models deployed, percentile features dead end)

---

## What Was Done

### Phase 1: BQ Validation Queries (5 experiments)

All 5 filter/signal hypotheses were tested against best-bets-level data. **None passed decision gates:**

| Experiment | Result | Decision |
|---|---|---|
| **E1: Low CV UNDER block** | N=3 at best bets, HR=66.7% | SKIP — filter stack handles it |
| **E2: Adaptive signal floor** | Feb SC=3 = 57.1% (above breakeven) | SKIP — no SC below breakeven in Feb |
| **E3: Slate size filter** | Light slate N=6 total | SKIP — too rare to implement |
| **E4: Time slot x direction** | Worst = primetime UNDER 55.2% raw | SKIP — nothing below 45% |
| **E5: Model agreement signal** | 2+ models = 92.3% HR (N=13) | SKIP — 12/13 from Jan, redundant |

### Key Insight

**The existing filter stack is highly effective.** All 5 hypothesized inefficiencies are already handled. This confirms Session 373's finding. The filter/signal improvements from Sessions 370-373 (signal floor 3, opponent blocks, new signals) are working well.

### Model Agreement Deep-Dive (E5)

Inspected all 13 multi-model agreement picks:
- All had n_models_eligible = 2 (none higher)
- All had edge >= 5.5 (already high-edge picks)
- 12/13 from January, only 1 Feb pick (Sengun UNDER)
- Signal would fire ~1x/week and mostly on picks already selected by high_edge
- Verdict: Redundant with existing signals, no incremental value

### Shadow Fleet Triage (14-day window, Feb 14-27)

22 enabled models in registry. Fleet dashboard results:

**Best performers:**
- `v9_low_vegas_train0106_0205`: 56.7% HR (N=60, UNDER 59.6%) — remains best shadow
- `v9_50f_noveg`: 61.5% (N=13) — promising but too small

**New models (just deployed, no predictions yet):**
- `catboost_v12_train0104_0208`: 67.35% backtest, deployed Mar 1
- `catboost_v12_train1221_0208`: 71.79% backtest, deployed Mar 1
- Both v12+vw015, loaded from BQ registry (not GCS manifest)

**At breakeven (50-53%):** 6 models including production v12 (53.5%, N=99)

**No model meets DISABLE criteria** (HR < 40%, N >= 20) or **PROMOTE criteria** (HR > 55%, N >= 30) beyond v9_low_vegas.

### Model Loading Architecture

Confirmed: prediction worker loads models from **BQ model_registry** (not GCS manifest). `get_enabled_models_from_registry()` queries `WHERE enabled = TRUE AND is_production = FALSE AND status IN ('active', 'shadow')`.

### Unregistered Models Explained

`catboost_v8`, `ensemble_v1`, `ensemble_v1_1`, `similarity_balanced_v1` predictions come from the **backfill job** (`backfill_jobs/prediction/player_prop_predictions_backfill.py`), NOT the production worker. These were decommissioned in Session 343. The backfill script was never updated to remove them. Low priority cleanup.

### CLAUDE.md Updated

Added 5 dead ends to dead ends list:
- Low CV UNDER filter, adaptive signal floor, slate size filter, time slot filter, model agreement signal

---

## What Was NOT Done

- No code changes (no filters passed decision gates)
- No deployment needed
- No model promotions/disables (insufficient data)

---

## Recommended Next Steps

### By Mar 3 (next session)
1. **Check Session 374 shadow models** — `catboost_v12_train0104_0208` and `catboost_v12_train1221_0208` should have 2-3 days of predictions by then
2. **Check Q5/Q55 models** — `v12_noveg_q5_train0115_0222` and `v12_noveg_q55_train0115_0222` should be accumulating data

### By Mar 5-7
3. **Full fleet triage** — Most models will have N >= 20 by then:
   ```bash
   PYTHONPATH=. python bin/model_family_dashboard.py --days 14 --min-picks 3
   PYTHONPATH=. python bin/post_filter_eval.py --model-id MODEL_ID --start 2026-02-28 --end 2026-03-05
   ```

4. **Promote v9_low_vegas?** — At 56.7% (N=60), it's the best shadow. Consider promoting if it holds through Mar 5.

### Future Experiments
5. **Retrain with Dec 21 - Feb 28 window** — The 49-day sweet spot found in Session 374 would be Dec 21 → Feb 8. A Mar retrain using Dec 28 → Feb 15 (49 days) would capture latest data.
6. **Filter stack is mature** — Diminishing returns on filter experiments. Model quality (fresher training data) is the remaining lever.

---

## Season Performance (as of Feb 27)
- **75-36 (67.6%), +32.25 units** (ATH +33.52 on Feb 22)
- Current regime: FLAT — profitable but grinding
- Signal count 4+ = 76.0% HR
