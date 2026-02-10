# Session 188 Handoff — Verification, Model Assessment, Scrapers Deploy

**Date:** 2026-02-10
**Previous:** Session 187 (Phase 2→3 trigger root cause fix, data gap backfills)
**Focus:** Verify Session 187 fixes landed, model promotion assessment, deploy stale scrapers

## What Was Done

### 1. Phase 2→3 Trigger — Verified Fix Deployed, Explained Why It Hasn't Fired Yet

Session 187's fix (commit `b2e9e54b`) added the complete `CLASS_TO_CONFIG_MAP` to the Phase 2→3 Cloud Function. Session 188 investigated why `_triggered` is still `False` for Feb 8, 9, and 10.

**Root cause: Deployment timing.** The Cloud Function was redeployed at **19:03 UTC** on Feb 10, but all Feb 9 processor events completed **before** that (last one at 15:00 UTC). The old Cloud Function processed those events, storing raw class names (`NbacGamebookProcessor`) instead of config names (`p2_nbacom_gamebook_pdf`).

**Verified:** Downloaded the deployed Cloud Function source from GCS and confirmed it has the complete `CLASS_TO_CONFIG_MAP` with all 5 processor mappings (lines 149-173 in `main.py`).

**Feb 10 trigger will work tonight:** Firestore already has 2 keys from old code (`OddsApiGameLinesBatchProcessor`, `OddsApiPropsBatchProcessor`). When tonight's 3 remaining processors complete, the new code will normalize them (`p2_nbacom_gamebook_pdf`, `p2_nbacom_boxscores`, `p2_bigdataball_pbp`). Total = 5 keys >= threshold of 5. The trigger counts all non-metadata keys regardless of naming format.

**No data loss:** Phase 3 ran for Feb 9 via overnight scheduler (363 player records in `player_game_summary`).

### 2. QUANT_43/45 — Not Generating Yet (Timing Issue, Will Auto-Resolve)

Both quantile shadow models have **zero predictions**. Root cause: code was pushed at 17:49-18:33 UTC but today's prediction runs completed at 13:01-16:07 UTC.

**Timeline:**
- Predictions ran: 13:01-16:07 UTC (revisions 00190-00192, old code)
- QUANT_43 deployed: 17:49 UTC (commit `6eedd607`, revision 00193)
- QUANT_45 deployed: 18:34 UTC (commit `76b9b08b`, revision 00195)
- Current revision: 00199 (commit `e6bf733`, 19:16 UTC) — has both QUANT configs

**Verified:** GCS model files exist, config is correct (`enabled: True`), latest revision has the code. First QUANT predictions will generate on tomorrow's 2:30 AM ET run.

**Secondary concern:** Revision 00192 (commit `c76ecb7`) loaded **retired** `_0208` and `_0208_tuned` models instead of the expected `_0131` variants. This suggests a stale Docker image was built by Cloud Build — possible layer caching issue. Worth monitoring but not blocking.

### 3. Model Promotion Assessment — Wait for QUANT Data

**Champion decay curve (edge 3+ HR by week):**

| Week | HR Edge 3+ | N | Status |
|------|-----------|---|--------|
| Jan 11 | 71.2% | 146 | Peak |
| Jan 18 | 67.3% | 110 | Decaying |
| Jan 25 | 57.1% | 98 | Below target |
| Feb 1 | 50.0% | 64 | Breakeven |
| Feb 8 | **43.8%** | 16 | **Losing money** |

Champion loses ~7pp per week from staleness. Now 40 days old and below breakeven.

**Challenger standings (14-day window):**

| Model | HR All | HR Edge 3+ (N) | Avg Bias | Volume |
|-------|--------|----------------|----------|--------|
| catboost_v9 (CHAMPION) | 48.6% | 50.0% (146) | -0.51 | ~10/day |
| catboost_v9_train1102_0108 | 50.5% | **70.8% (24)** | -1.57 | ~1.7/day |
| catboost_v9_train1102_0131_tuned | 53.4% | 33.3% (6) | +0.53 | ~1/day |
| catboost_v9_q43_train1102_0131 | — | — | — | No data |
| catboost_v9_q45_train1102_0131 | — | — | — | No data |

**Decision: Wait until Feb 14-15.** Jan 8 shadow leads at 70.8% but n=24 is too small. QUANT_43 showed 65.8% HR in backtests with fundamentally different edge mechanism (systematic bias via quantile loss, doesn't decay). Need 3-5 days of production data before promoting.

### 4. Deployed nba-phase1-scrapers

Was 2 days stale, missing commit `1f46133b` (expanded OddsAPI bookmakers to 6 sportsbooks).

- Deployed to revision `nba-phase1-scrapers-00028-dlk` at commit `e6bf7334`
- All 8 deployment steps passed: dependency validation, smoke tests, heartbeat verification, env var checks
- Broader sportsbook coverage now active

### 5. Daily Validation Summary

| Check | Status | Details |
|-------|--------|---------|
| Deployment drift | **All clear** | Scrapers deployed, all services current |
| Feature quality | OK | 100% matchup, 74.7% quality-ready (59/79) |
| Predictions | OK | 18 predictions, 4 actionable (light 4-game day) |
| Signal | YELLOW | 33.3% pct_over, 1 high-edge pick |
| Grading (7-day) | Volatile | Feb 7: 72.2% actionable HR, Feb 6: 27.3% |
| Heartbeats | Clean | No stale heartbeats |

### 6. Breakout Classifier — Investigated, Kept Disabled

The breakout classifier (shadow mode) was disabled in Session 187 because it generated 20+ `CatBoostError` per prediction run: "Feature points_avg_season is present in model but not in pool."

**Root cause:** The prediction code hardcoded 8 features but the production model (`breakout_shared_v1_20251102_20260205.cbm`) was trained with 14 V2 features. A V1 fix (10 features) was attempted but reverted in Session 189 — the model was trained with V2 (14 features), not V1 (10 features), so the fix would produce suboptimal predictions.

**Session 189 Decision:** Keep classifier disabled. The model (AUC 0.5708) is too weak for production anyway — no predictions above 0.6 confidence (need 0.769+). Session 189 ran regression reframe experiments (RMSE, Q43, Q50, Q57 on continuous points target) confirming the problem is features, not loss functions. Breakout V3 needs contextual features (star_teammate_out, opponent injuries) before re-enabling.

### 7. Uncommitted Session 186 Work — Already Committed

Verified git status is clean. All Session 186 work (`compare-model-performance.py --all/--segments`, `catboost_monthly.py` strengths metadata, SKILL.md updates) was committed across commits `02c0c69c` through `76b9b08b`.

## Quick Start for Next Session

```bash
# 1. CRITICAL: Verify Phase 2→3 trigger fired for Feb 10 games
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase2_completion').document('2026-02-10').get()
if doc.exists:
    data = doc.to_dict()
    print(f'Phase 2 for 2026-02-10:')
    print(f'  _triggered: {data.get(\"_triggered\", False)}')
    processors = [k for k in data.keys() if not k.startswith('_')]
    print(f'  Processors ({len(processors)}): {sorted(processors)}')
"

# 2. Verify QUANT models generated predictions
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as predictions,
       COUNTIF(is_actionable) as actionable
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE 'catboost_v9_q%'
  AND game_date >= '2026-02-10'
GROUP BY 1, 2 ORDER BY 1, 2 DESC"

# 3. Verify breakout classifier is running clean (no CatBoostError)
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND textPayload=~"breakout"' --project=nba-props-platform --limit=10 --format="table(timestamp,textPayload)"

# 4. If QUANT has predictions, check initial performance
PYTHONPATH=. python bin/compare-model-performance.py --all --days 7

# 5. Run daily validation
/validate-daily
```

## Pending Follow-Ups

### High Priority
1. **Verify Phase 2→3 trigger fires for Feb 10** — first real test of Session 187 fix. `_triggered` should be `True` with 5 processors (mix of raw and config names)
2. **Verify QUANT_43/45 predictions generate** — should appear in tomorrow's 2:30 AM ET run
3. ~~**Verify breakout classifier runs clean**~~ — **Kept disabled (Session 189).** Model too weak, needs V3 features.
4. **Model promotion decision (Feb 14-15)** — once QUANT_43 has 3-5 days of production data, compare against Jan 8 shadow and decide on promotion

### Medium Priority
4. **Investigate stale Docker image issue** — revision 00192 loaded retired `_0208` models despite commit `c76ecb7` having them disabled. Cloud Build layer caching issue?
5. ~~**Fix breakout classifier feature mismatch**~~ — **Kept disabled (Session 189).** Needs V3 contextual features + retrain, not a feature order fix.

### Lower Priority
6. **Delay overnight Phase 3/4 schedulers** — from 6 AM to 8 AM ET to reduce noisy failures
7. **Extended eval for C1_CHAOS and NO_VEG** — when 2+ weeks of eval data available

## Key Finding: Phase 2→3 Trigger Timing

The Phase 2→3 trigger has been broken since at least Feb 8, but Phase 3 has been running anyway via the overnight scheduler. The fix IS deployed now — tonight (Feb 10) will be the first real test. The trigger uses a count-based check (`completed_count >= 5`), not name matching, so even mixed raw/config names in Firestore will satisfy the condition.

**If the trigger still doesn't fire for Feb 10:** The issue would be in how the remaining 3 processors publish completion events — check whether the Pub/Sub messages are reaching the Cloud Function at all. Look at Cloud Function invocation logs for Feb 10 after games complete.
