# Session 332 Handoff — V12 Interim Promotion + Full Model Retrain

**Date:** 2026-02-23
**Focus:** V9 champion decay response — interim V12 promotion, all-family retrain

## What Happened

V9 champion hit BLOCKED state (47.1% edge 3+ HR, 14d: 45.6%). Below 52.4% breakeven for 2+ weeks. V12 base is HEALTHY at 58-60% 7d HR.

### Actions Taken

1. **Promoted `catboost_v12` as interim champion** (commit `40a5ed87`)
   - Changed `CHAMPION_MODEL_ID` in `shared/config/model_selection.py` from `catboost_v9` → `catboost_v12`
   - Pushed to main → auto-deploy across all services
   - Affects: best bets model health, pre-game signal, monitoring dashboards
   - Does NOT affect prediction generation pipeline (shadow models still generate independently)

2. **Deployed `nba-grading-service`** — was 1 commit behind (completeness checker fix)

3. **Fixed 3 scheduler job timeouts:**
   - `predictions-12pm`: 180s → 540s
   - `predictions-final-retry`: 180s → 540s
   - `self-heal-predictions`: 600s → 900s

4. **Updated CLAUDE.md** — new champion model info

5. **Kicked off full model retrain** (`./bin/retrain.sh --all --enable --train-end 2026-02-15`)
   - Training window: Jan 4 → Feb 15 (42-day rolling)
   - Eval window: Feb 16 → Feb 22 (7 days of graded data)
   - 9 families: v12_mae, v12_noveg_mae, v12_noveg_q43, v12_q43, v12_vegas_q43, v9_low_vegas, v9_mae (plus duplicates — see known issue)

## V12 Promotion Analysis

| Model | Edge 3+ HR | N | Edge 6+ HR | N | 7d State |
|-------|-----------|---|-----------|---|----------|
| `v12_train1102_1225` | **68.1%** | 138 | **100%** | 19 | DEGRADING |
| `v12_train1102_0125` | **73.9%** | 46 | **100%** | 6 | INSUF. DATA |
| `catboost_v12` (promoted) | 57.1% | 98 | 50.0% | 8 | **HEALTHY** |
| `catboost_v9` (demoted) | 51.6% | 545 | — | — | **BLOCKED** |

V12 base chosen for interim because it's the only V12 variant that is both HEALTHY and has sufficient sample size.

## Retrain Status

**IMPORTANT: Retrain may still be running.** Check with:
```bash
# Check if retrain process is running
ps aux | grep retrain
# Or check the latest models in GCS
gsutil ls gs://nba-props-platform-models/catboost/v12/monthly/ | tail -10
```

**First attempt failed** (eval period Feb 23 → Mar 1 was in the future). Restarted with `--train-end 2026-02-15` so eval uses Feb 16-22 graded data.

**Governance gate results are expected to show FAIL** on the eval window — only ~18 edge 3+ picks in a 7-day eval period (need 50). This is normal for walkforward eval. The real validation happens after 2-3 days of production shadow picks accumulate 50+ edge 3+ graded predictions.

First model (v12_mae) trained: MAE 4.74 vs 5.14 baseline (improved!), saved to GCS, registered in ml_experiments. Continuing through all 9 families.

### After Retrain Completes

1. **Check which models passed governance gates:**
   ```bash
   bq query --use_legacy_sql=false --project_id=nba-props-platform "
   SELECT model_id, model_family, status, enabled,
     CAST(evaluation_metrics AS STRING) as metrics
   FROM nba_predictions.model_registry
   WHERE created_at >= '2026-02-23'
   ORDER BY model_family"
   ```

2. **Shadow the new models for 2+ days** before promoting any as permanent champion

3. **Promote the best fresh V12 variant** when it has 50+ edge 3+ graded picks and passes all governance gates (60% HR, ±1.5 vegas bias, no tier bias >5)

## Known Issues

### Duplicate Model Families in Registry
The `model_registry` has duplicate entries for `v12_mae` and `v9_mae` families, causing the retrain script to train each twice. Non-blocking but wasteful. Fix:
```sql
-- Investigate duplicates
SELECT model_family, model_id, status, enabled
FROM nba_predictions.model_registry
WHERE model_family IN ('v12_mae', 'v9_mae') AND enabled = TRUE
ORDER BY model_family, model_id;
-- Then disable the older/deprecated entries
```

### Scheduler Jobs Still Failing
- `auto-retry-processor-trigger` — DEADLINE_EXCEEDED (Pub/Sub-based, different timeout mechanism)
- `predictions-last-call` — code 2 UNKNOWN (coordinator still processing when scheduler times out; work likely completes despite error)

### `validation-runner` Still 1 Commit Behind
Non-critical service. Deploy when convenient:
```bash
./bin/deploy-service.sh validation-runner
```

### Firestore Completion Records Missing
No Phase 2/Phase 3 completion docs found for Feb 22 or Feb 23. Pipeline data IS flowing (analytics records exist), so this is a tracking gap, not a data gap. Investigate if Firestore writes are failing silently.

## Today's Game Day Context

- 3 games: SAS@DET, SAC@MEM, UTA@HOU
- **RED signal** — light slate (3 games), UNDER_HEAVY (2.7% over), 0 high-edge V9 picks
- V12 has 7 edge 3+ picks (vs V9's 0) — new champion already adding value
- Skip betting recommended on light slate regardless

## Files Changed

- `shared/config/model_selection.py` — Champion model ID: V9 → V12
- `CLAUDE.md` — Updated ML Model section

## Next Session Priorities

1. **Check retrain results** — which families passed governance gates?
2. **Monitor V12 as champion** — verify best bets export uses V12 health correctly
3. **Fix duplicate model families** in registry
4. **Investigate Firestore completion tracking** gap
5. **When fresh models have 50+ graded picks** (2-3 days), evaluate for permanent promotion
