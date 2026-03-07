# System Improvement Execution Plan — Session 429

**Date:** 2026-03-07
**Estimated Total:** ~4-5 hours across Phases A-D

---

## Phase A: Immediate Fixes (30-45 min)

### A1. Deactivate BLOCKED v16 shadow model (5 min)
```bash
python bin/deactivate_model.py catboost_v16_noveg_train0105_0221
```
- BLOCKED at 50.0% HR, still enabled
- No dependencies, do first

### A2. Create `service_errors` BQ table (5 min)
- Schema exists: `schemas/bigquery/nba_orchestration/service_errors.sql`
- Table never created in BigQuery
- 5+ systems silently fail to log errors (decay CF, deactivate_model, transform_processor_base)
```bash
bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/service_errors.sql
```
- Verify: `bq show nba_orchestration.service_errors`

### A3. Fix decay-detection CF — 3 bugs (20-30 min)
**File:** `orchestration/cloud_functions/decay_detection/main.py`

**Bug 1: SQL syntax error (line 637-642)**
The `check_pick_volume_anomaly` function uses `CROSS JOIN recent_game_days rgd` with `ARRAY_AGG(STRUCT(rgd.game_date, rgd.pick_count))` but the GROUP BY doesn't include `rgd` columns.

**Fix:** Pre-aggregate `recent_game_days` into a single row before the CROSS JOIN:
```sql
-- Replace CROSS JOIN recent_game_days rgd with:
CROSS JOIN (
  SELECT ARRAY_AGG(STRUCT(game_date, pick_count) ORDER BY game_date DESC) as recent_days
  FROM recent_game_days
) rgd
-- And remove rgd columns from GROUP BY
-- Change line 637 from ARRAY_AGG(STRUCT(rgd.game_date, rgd.pick_count)...) to just rgd.recent_days
```

**Bug 2: Dataset mismatch (line 906)**
CF writes audit to `nba_predictions.service_errors` but table is in `nba_orchestration.service_errors`.
```python
# Line 906: Change
INSERT INTO `{PROJECT_ID}.nba_predictions.service_errors`
# To:
INSERT INTO `{PROJECT_ID}.nba_orchestration.service_errors`
```

**Bug 3: Column mismatch in INSERT (line 907)**
CF inserts `(service_name, error_type, error_message, context, created_at)` but schema requires `error_id, error_timestamp, error_category, severity` etc.
- Fix: Use `ServiceErrorLogger` pattern or match schema columns.

### A4. Enable AUTO_DISABLE_ENABLED (5 min)
**Prerequisite:** A2 + A3 must be done first.
```bash
gcloud functions deploy decay-detection \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars AUTO_DISABLE_ENABLED=true
```
- Safety floor: 3+ models remain (currently 9 enabled, well above floor)
- Runs daily at 11 AM ET

---

## Phase B: Monitoring Automation (30-45 min)

### B1. Schedule data_source_health_canary (15 min)
**Current state:** CLI-only (`bin/monitoring/data_source_health_canary.py`), no HTTP handler.
**Approach:** Wrap in lightweight Cloud Function (HTTP trigger) or add to existing `daily-health-check` CF.

**Option A — Add to daily_health_check CF:**
The daily-health-check CF already runs at 8 AM ET and checks 11 system health items. Add data source freshness as check #12. This avoids creating a new CF.

**Option B — Create new Cloud Scheduler → existing script:**
The script already has Slack integration. Add `main(request)` HTTP handler that calls the existing `main()` logic.

**Recommended:** Option B (cleaner separation). Schedule at 7 AM ET (after overnight scraping).

### B2. Schedule signal_decay_monitor (15 min)
**Current state:** CLI-only (`bin/monitoring/signal_decay_monitor.py`).
**Same approach as B1.** Add HTTP handler, schedule at 12 PM ET (after grading and model_performance_daily are populated).

### B3. Consolidate feature contract — kill duplication (15 min)
**File:** `predictions/worker/prediction_systems/catboost_v12.py`
**Current:** Hardcoded 50-element `V12_NOVEG_FEATURES` list (lines 44-108)
**Fix:** Import from `shared/ml/feature_contract.py` like `catboost_monthly.py` already does (lines 52-61).

```python
# Replace hardcoded list with:
from shared.ml.feature_contract import V12_NOVEG_FEATURE_NAMES
V12_NOVEG_FEATURES = V12_NOVEG_FEATURE_NAMES
```

**Note:** Agent research confirmed the lists are currently perfectly aligned, so this is a refactor to prevent future drift, not a bug fix.

---

## Phase C: Smart Automation (2-3 hours)

### C1. Move CHAMPION_MODEL_ID to registry query (30 min)
**File:** `shared/config/model_selection.py` (line 12)
**Current:** `CHAMPION_MODEL_ID = 'catboost_v12'` hardcoded
**Fix:** Query `model_registry WHERE is_production = TRUE` with cache (1-hour TTL).

```python
import functools
import time

_champion_cache = {'model_id': None, 'expires': 0}

def get_champion_model_id() -> str:
    if time.time() < _champion_cache['expires'] and _champion_cache['model_id']:
        return _champion_cache['model_id']
    # Query BQ model_registry for is_production = TRUE
    # Fallback to CHAMPION_MODEL_ID constant if query fails
    # Cache for 1 hour
```

**Impact:** Champion changes become a BQ UPDATE instead of code change + deploy.

### C2. Auto-demote filters based on counterfactual HR (1-1.5 hours)
**Foundation:** `aggregator.py:_record_filtered()` already tracks every filtered pick with full detail. `bin/post_filter_eval.py` already grades counterfactual picks.

**Approach:**
1. Create a daily Cloud Function that runs after grading
2. For each active filter, query `prediction_accuracy` for picks that were filtered out yesterday
3. Compute counterfactual HR (what would have happened if the filter didn't block them)
4. If CF HR >= 55% at N >= 20 for 7 consecutive days → auto-demote to observation
5. Write results to `best_bets_filter_audit` table (new, or extend existing)
6. Slack alert with recommendation

**Key insight from Session 428:** 4 filters manually demoted had CF HR 55-65%. This automation would have caught them weeks earlier.

**Safeguards:**
- Never auto-demote without Slack notification
- 7-day consecutive threshold prevents single-day noise
- N >= 20 minimum sample size
- Log all demotion decisions to service_errors

### C3. Auto-recompute UNDER_SIGNAL_WEIGHTS (1 hour)
**Foundation:** `signal_health_daily` table has `hr_14d`, `picks_14d` per signal, partitioned by game_date.

**Approach:**
1. Daily job (after signal_health_daily is populated)
2. For each signal in UNDER_SIGNAL_WEIGHTS, query 14d HR and N
3. Compute weight: `weight = max(0.5, min(3.0, 1.0 + (hr_14d - 52.4) * 0.05))`
4. Write to BQ config table `nba_predictions.signal_weight_config`
5. Aggregator reads from config table at export time (with fallback to hardcoded defaults)

**Alternative (simpler):** Weekly Slack report showing current HR vs hardcoded weight for each UNDER signal. Human decides. This avoids the complexity of dynamic weights while still surfacing the data.

**Recommended:** Start with the weekly report (1 hour), defer full automation.

### C4. Automated signal promotion pipeline (30 min)
**Foundation:** `signal_health_daily` has HR and N for all shadow signals.

**Approach:** Weekly Slack report listing shadow signals meeting promotion criteria:
- Production: HR >= 60% + N >= 30
- Rescue: HR >= 65% + N >= 15

**Output:**
```
Signal Promotion Candidates (weekly):
  volatile_starter_under: HR 66.1% (14d), N=45 → READY for production
  downtrend_under: HR 62.4% (14d), N=38 → READY for production
  predicted_pace_over: HR 51.9% (14d), N=27 → NOT READY (HR < 60%)
```

**Note:** Full automation (auto-edit aggregator.py) is over-engineering. A formatted Slack report that a human approves is the right level.

---

## Phase D: Calendar Regime Deep Dive (1 hour, research-only)

### D1. Study historical toxic window patterns
- Query prediction_accuracy for Jan 15 - Mar 10 across 2025 and 2026 seasons
- Map HR by week to identify exact toxic window boundaries
- Compare: does the toxic window start/end on the same dates each year?

### D2. Evaluate regime-aware signal weights
- During toxic window (Jan 30-Feb 25 2026):
  - Which signals maintained HR >= 55%? (resilient signals)
  - Which signals dropped below 50%? (fragile signals)
- Compute: per-signal HR during toxic vs non-toxic periods
- Determine: would regime-aware multipliers have improved BB HR during toxic?

### D3. Decide build-vs-wait
- If regime-aware weights would have improved toxic window by 5+ pp → build in December
- If improvement < 5pp → the filter stack already compensates (65.9% BB HR during toxic)
- Document findings for future reference

---

## Dependency Graph

```
A1 (deactivate v16) ─── no deps ─── do immediately
A2 (create service_errors table) ─── no deps ─── do immediately
A3 (fix decay CF) ─── depends on A2 (audit trail needs table)
A4 (enable AUTO_DISABLE) ─── depends on A2 + A3

B1 (schedule data_source canary) ─── no deps
B2 (schedule signal_decay monitor) ─── no deps
B3 (feature contract consolidation) ─── no deps

C1 (champion to registry) ─── no deps
C2 (auto-demote filters) ─── depends on A2 (logging to service_errors)
C3 (UNDER weight report) ─── no deps
C4 (signal promotion report) ─── no deps

D1-D3 (calendar research) ─── no deps, do last
```

**Parallel opportunities:**
- A1 + A2 can run in parallel
- B1 + B2 + B3 can all run in parallel
- C1 + C3 + C4 can all run in parallel

---

## Commit Strategy

1. **Commit 1 (Phase A):** `fix: decay-detection CF — query syntax, dataset mismatch, auto-disable`
2. **Commit 2 (Phase B):** `feat: schedule monitoring canaries + consolidate feature contract`
3. **Commit 3 (Phase C):** `feat: champion model from registry + signal/filter reporting`
4. **Commit 4 (Phase D):** `docs: calendar regime analysis for 2026-27 planning`

Push after each commit (auto-deploys). Verify builds between phases.
