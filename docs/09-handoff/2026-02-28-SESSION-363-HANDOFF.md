# Session 363 Handoff — Infrastructure Fixes + Front-Load Detection

**Date:** 2026-02-28
**Previous:** Session 361 (shadow fleet review), Session 362 (daily validation)

## What Session 363 Did

Tackled all action items from Sessions 361 and 362 in a single pass: 3 bug fixes, 1 new feature, full deployment cleanup.

### 1. Firestore Race Condition Fix (P1)

**Root cause:** `completion_tracker` wrote to the same Firestore doc (`phase3_completion/{game_date}`) BEFORE the orchestrator's atomic transaction. When the transaction ran, every processor was already in the document and hit the "duplicate" code path (line 1554 `if processor_name in current`). Result: `_mode` never set, `_triggered` never set, Phase 4 never triggered via orchestrator.

**Fix:** Moved `completion_tracker.record_completion()` to AFTER `update_completion_atomic()`. The transaction now correctly detects new processors, evaluates trigger logic, and sets `_mode`/`_triggered`.

**Impact:** Phase 4 should now trigger via orchestrator Pub/Sub instead of relying solely on backup Cloud Scheduler. Data flow was never broken (backup scheduler compensated), but Firestore tracking will now be accurate.

**File:** `orchestration/cloud_functions/phase3_to_phase4/main.py`

### 2. Phase 0.35 game_id Format Mismatch Fix (P2)

**Root cause:** `nba_reference.nba_schedule` uses NBA numeric game_ids (`0022500852`), while `nba_analytics.player_game_summary` uses date_away_home format (`20260226_MIA_PHI`). JOINs on `game_id` between these tables silently produce 0 matches.

**Fix:** Construct analytics-format game_id from schedule data: `CONCAT(REPLACE(date, '-', ''), '_', away_tricode, '_', home_tricode)`. Fixed in two places:
- `.claude/skills/validate-daily/SKILL.md` (Phase 0.35 query template)
- `bin/validation/comprehensive_health_check.py` (`_check_cross_phase_consistency` — also removed stale BDL boxscore comparison)

### 3. Self-Heal Timeout Fix (P3)

**Problem:** `self-heal-predictions` Cloud Function had 540s timeout, scheduler had 900s deadline. Function was dying at 540s → scheduler reported DEADLINE_EXCEEDED (code 4).

**Fix:** Increased Cloud Run service timeout from 540s → 900s via `gcloud run services update`. Already live.

### 4. Front-Load Detection (New Feature)

**What it does:** Detects models where 7-day rolling HR is consistently 5+ pp below 14-day rolling HR for 3+ consecutive days. This pattern indicates a model that performed well initially but is now degrading — "front-loading."

**Implementation:** Added `detect_front_loading()` to `orchestration/cloud_functions/decay_detection/main.py`. Follows the same pattern as `detect_cross_model_crash()`. Sends dedicated Slack alert (dark orange, `#FF8C00`) to `#nba-alerts`.

**Validated locally:** Correctly flags:
- `catboost_v12_train1225_0205`: 7d 32.1% vs 14d 38.2% (6.1pp gap, 6 consecutive days)
- `catboost_v9`: 7d 35.0% vs 14d 43.5% (8.5pp gap, 4 consecutive days)

**Thresholds:** `FRONT_LOAD_HR_GAP = 5.0`, `FRONT_LOAD_MIN_DAYS = 3`, `FRONT_LOAD_MIN_N = 20`

### 5. Deployment Drift Cleanup

Resolved all drift. Went from 9 stale services → 0:
- 20 Cloud Build triggers fired automatically on push (all SUCCESS)
- `nba-grading-service` deployed manually (no auto-trigger for it)
- Final check: "All services up to date!"

---

## What Changed

| Commit | Description |
|--------|-------------|
| `cf73f6e6` | fix: Firestore race condition, game_id format mismatch, self-heal timeout |
| `279cea4d` | feat: add front-load detection to decay-detection CF |

---

## Verification Status

### Confirmed Working
- Firestore race condition fix — deployed via Cloud Build (SUCCESS)
- Phase 0.35 coverage query — fixed in skill + health check
- Self-heal timeout — live at 900s
- Front-load detection — validated locally with real data
- Deployment drift — 0 services stale

### Waiting on Data (Next Game Day)
- **LightGBM loading fix** (commit `7ee998bd` from Session 361): Code is correct (triple detection: registry `model_type`, `model_id` prefix `lgbm*`, GCS extension `.txt`). Registry has `model_type='lightgbm'` for both lgbm models. No worker runs since fix deployed at 22:02 UTC Feb 27. Will be tested on next prediction run.
- **Shadow fleet live data**: 15 models enabled, 7 newly registered. No graded predictions yet.

---

## Action Items for Next Session

### 1. Verify LightGBM Loading (After Next Game Day)

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND textPayload=~"lgbm|lightgbm|LightGBM"' \
  --project=nba-props-platform --limit=10 --freshness=12h \
  --format="table(timestamp,textPayload)"
```

**Expected:** "Loading LightGBM monthly model from: gs://..." (NOT "Loading CatBoost").

### 2. Verify All 15 Shadow Models Loaded

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND textPayload=~"Loaded.*monthly model"' \
  --project=nba-props-platform --limit=5 --freshness=12h \
  --format=json | python3 -c "import sys,json; [print(e.get('textPayload','')) for e in json.load(sys.stdin)]"
```

**Expected:** "Loaded 15 monthly model(s) (15 from registry, 0 from dict)"

### 3. Verify Firestore Trigger Tracking

After Phase 3 runs for the next game day, check Firestore:

```python
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
# Check latest date
docs = list(db.collection('phase3_completion').order_by('__name__', direction='DESCENDING').limit(3).stream())
for doc in docs:
    d = doc.to_dict()
    print(f"{doc.id}: _triggered={d.get('_triggered')}, _mode={d.get('_mode')}, _completed_count={d.get('_completed_count')}")
```

**Expected:** `_triggered=True`, `_mode=overnight` (or `evening`), processors listed as keys.

### 4. Shadow Fleet Evaluation (After 3-5 Days)

```sql
SELECT system_id,
       COUNT(*) as total_picks,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_w,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct)
         / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-02-28'
  AND system_id IN ('catboost_v12_train1201_0215', 'catboost_v16_noveg_rec14_train1201_0215',
                    'catboost_v16_noveg_train1201_0215', 'lgbm_v12_noveg_train1102_0209',
                    'lgbm_v12_noveg_train1201_0209')
GROUP BY system_id ORDER BY edge3_hr DESC;
```

**Key model:** `catboost_v12_train1201_0215` (V12 vegas=0.25) — 75% backtest HR. If it sustains 60%+ live, it's the promotion candidate.

### 5. Front-Load Detection — Monitor Alerts

The next `decay-detection` run (11 AM ET) will fire front-load alerts for `v12_train1225_0205` and `v9`. These models are already BLOCKED — the alert is informational. Consider disabling models that are both BLOCKED and front-loading to reduce noise.

---

## Current Fleet Status

### Production
- `catboost_v12` (v12_50f_huber): BLOCKED, 44.7% HR 7d

### Shadow — Accumulating Data
- `v9_low_vegas_train0106_0205`: BLOCKED 50-51.9% (best current model)
- Session 343-344, 348, 357 models: BLOCKED, accumulating

### Shadow — Newly Registered (No Live Data Yet)
- `catboost_v12_train1201_0215`: V12 vegas=0.25 — **75% backtest**
- `catboost_v16_noveg_rec14_train1201_0215`: V16 noveg + recency — **69% backtest**
- `catboost_v16_noveg_train1201_0215`: V16 noveg — 70.8% backtest
- `lgbm_v12_noveg_train1102_0209`: LightGBM — 73.3% backtest (loading fix untested)
- `lgbm_v12_noveg_train1201_0209`: LightGBM — 67.7% backtest (loading fix untested)
- `catboost_v12_noveg_q55_train0115_0222`: Q55 fresh window
- `catboost_v12_noveg_q5_train0115_0222`: Q5 experiment

### Best Bets Performance
- 7d: 7-3 (70.0%)
- 14d: 10-6 (62.5%)
- 30d: 29-18 (61.7%)

---

## Key File References

- Firestore fix: `orchestration/cloud_functions/phase3_to_phase4/main.py:1351-1415`
- Phase 0.35 fix: `.claude/skills/validate-daily/SKILL.md:391-412`, `bin/validation/comprehensive_health_check.py:474-560`
- Front-load detection: `orchestration/cloud_functions/decay_detection/main.py:55-176`
- Worker model loading: `predictions/worker/prediction_systems/catboost_monthly.py:302-339` (registry detection), `:405-463` (model loading)

## What NOT to Do

- **Don't promote any model** — none have sufficient live data yet
- **Don't experiment** — wait for shadow fleet data (3-5 days)
- **Don't revert the LightGBM fix** — it hasn't been tested yet
- **Don't disable front-loaded models** without checking if they contribute best bets picks
