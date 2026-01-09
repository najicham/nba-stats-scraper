# Handoff: Same-Day Pipeline Critical Fixes - January 9, 2026

## Session Summary

Thorough validation of daily orchestration discovered **4 critical issues** affecting V8 predictions. Partial recovery completed - full fix requires additional steps.

**Current State:**
- Timing issue: FIXED (for today)
- V8 model loading: NOT FIXED (env var missing)
- V8 confidence normalization: NOT FIXED (code bug)
- 241 player failures: NOT INVESTIGATED

---

## Quick Reference: What Needs to Be Done

### Immediate (Do Now - 5 minutes)

**1. Fix V8 model loading:**
```bash
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm"
```

**2. Re-run predictions after fix:**
```bash
gcloud scheduler jobs run same-day-predictions --location=us-west2
```

**3. Verify fix worked:**
```bash
# Wait 2 minutes, then check V8 confidence scores
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(confidence_score), 1) as avg_confidence,
  COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-09' AND system_id = 'catboost_v8' AND is_active = TRUE
GROUP BY system_id"

# Expected: avg_confidence > 70 (not 50), actionable > 0
```

---

## Issues Discovered

### Issue 1: UPGC Timing Race Condition (FIXED)

**What happened:** UPGC ran at 12:45 PM ET before BettingPros props were available (12:59 PM ET). All 108 predictions had `has_prop_line=false`.

**Status:** FIXED for today by re-running the pipeline after props were available.

**Recovery executed:**
```bash
# Re-ran UPGC → Phase 4 → Predictions
# Result: Prop coverage went from 0% → 44.4%
```

**Prevention needed:** See Project Plan for prevention mechanisms.

---

### Issue 2: V8 Model Not Loading (NOT FIXED)

**What happened:** CatBoost V8 model exists in GCS but the `CATBOOST_V8_MODEL_PATH` environment variable was never set on prediction-worker.

**Evidence:**
- All V8 predictions have `confidence_score = 50.0` (fallback default)
- All V8 recommendations are `PASS` (fallback always returns PASS)
- Worker logs show: `"Unknown system_id catboost_v8, assuming 0-1 scale"`

**Root cause:** Deployment oversight - model uploaded to GCS but env var not configured.

**Model location:** `gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm`

**Fix required:**
```bash
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm"
```

---

### Issue 3: V8 Confidence Normalization Bug (NOT FIXED)

**What happened:** `normalize_confidence()` in `data_loaders.py` doesn't recognize `catboost_v8` system_id.

**File:** `predictions/worker/data_loaders.py` lines 923-932

**Current code:**
```python
elif system_id in ['similarity_balanced_v1', 'xgboost_v1']:
    return confidence / 100.0  # catboost_v8 NOT included!
else:
    logger.warning(f"Unknown system_id {system_id}, assuming 0-1 scale")
    return confidence  # Bug: V8 returns 0-100, not normalized
```

**Fix required:** Add `'catboost_v8'` to the list:
```python
elif system_id in ['similarity_balanced_v1', 'xgboost_v1', 'catboost_v8']:
    return confidence / 100.0
```

---

### Issue 4: 241/349 Player Failures (NOT INVESTIGATED)

**What happened:** Only 108 of 349 rostered players processed. 241 failed completeness checks.

**Impact:** Only 4 of 10 games have predictions (ORL/PHI, WAS/NOP, DEN/ATL, PHX/NYK)

**Missing games:**
- BOS vs TOR
- BKN vs LAC
- MEM vs OKC
- GSW vs SAC
- POR vs HOU
- LAL vs MIL

**Investigation needed:**
1. Check completeness checker threshold (currently 70%)
2. Check BDL API data freshness for affected teams
3. Consider lowering threshold for same-day mode

---

## Project Documentation

**Comprehensive plan with code examples:**
```
docs/08-projects/current/pipeline-reliability-improvements/2026-01-09-SAME-DAY-PIPELINE-TIMING-FIX.md
```

This document contains:
- Full root cause analysis
- Prevention mechanisms (props pre-flight check, alerts, self-healing)
- Code snippets for all fixes
- Prioritized todo list
- Acceptance criteria

---

## Prevention Mechanisms (Implement This Week)

### 1. Props Pre-flight Check

Add to UPGC to fail fast if props not available:

```python
def _check_props_readiness(self, target_date: date) -> dict:
    """Pre-flight check: Are props available?"""
    query = """
    SELECT COUNT(DISTINCT player_lookup) as player_count
    FROM nba_raw.bettingpros_player_points_props
    WHERE game_date = @target_date AND is_active = TRUE
    """
    # Require at least 20 players with props
    return {'ready': result.player_count >= 20}
```

### 2. Zero Prop Coverage Alert

Alert when UPGC completes with 0% prop matching:

```python
if total > 50 and prop_pct == 0:
    send_critical_alert("UPGC: 0% Prop Coverage - Timing Issue Detected")
```

### 3. Self-Healing Scheduler

1 PM ET job to detect and auto-fix timing issues:

```bash
gcloud scheduler jobs create http same-day-selfheal \
  --schedule="0 13 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-west2-nba-props-platform.cloudfunctions.net/same-day-selfheal"
```

### 4. Scheduler Reordering

Force props scrape before Phase 3:

```bash
# Add 10 AM props scrape
gcloud scheduler jobs create http same-day-props-ensure \
  --schedule="0 10 * * *" \
  --message-body='{"workflow": "betting_lines", "force": true}'

# Delay Phase 3 to 11 AM (was 10:30 AM)
gcloud scheduler jobs update http same-day-phase3 --schedule="0 11 * * *"
```

---

## Verification Commands

```bash
# Check V8 model loading after fix
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload:"CatBoost"' \
  --limit=10 --freshness=10m

# Check V8 predictions quality
bq query --use_legacy_sql=false "
SELECT
  ROUND(AVG(confidence_score), 1) as avg_conf,
  COUNTIF(recommendation = 'OVER') as overs,
  COUNTIF(recommendation = 'UNDER') as unders,
  COUNTIF(recommendation = 'PASS') as pass,
  COUNTIF(recommendation = 'NO_LINE') as no_line
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-09' AND system_id = 'catboost_v8'"

# Check UPGC prop coverage
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(has_prop_line) as with_props,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(has_prop_line) / COUNT(*), 1) as pct
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-09'"
```

---

## Today's Recovery Summary

| Metric | Before Recovery | After Recovery |
|--------|-----------------|----------------|
| UPGC Prop Coverage | 0% | 44.4% |
| Total Predictions | 305 | 473 |
| Actionable Picks | 0 | 59 |
| V8 Confidence | 50.0 (fallback) | 50.0 (still fallback) |
| V8 OVER/UNDER | 0 | 0 (need env var fix) |

---

## Priority Checklist for Next Session

### P0 - Do First (5 min)
- [ ] Set V8 model env var on prediction-worker
- [ ] Re-run predictions
- [ ] Verify V8 generating proper recommendations

### P1 - High (This Session)
- [ ] Fix V8 confidence normalization in data_loaders.py
- [ ] Deploy data_loaders fix
- [ ] Add props pre-flight check to UPGC
- [ ] Add 0% prop coverage alert to UPGC
- [ ] Deploy UPGC changes

### P2 - Medium (This Week)
- [ ] Create self-healing Cloud Function
- [ ] Deploy self-healing scheduler
- [ ] Reorder schedulers (props before Phase 3)
- [ ] Add same-day health dashboard query

### P3 - Lower (Investigate)
- [ ] Why did 241 players fail completeness?
- [ ] Consider same-day completeness threshold adjustment

---

## Files to Modify

| File | Change |
|------|--------|
| `predictions/worker/data_loaders.py` | Add `catboost_v8` to normalize_confidence() |
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | Add props pre-flight check and 0% alert |

---

## Related Documentation

- **Project Plan:** `docs/08-projects/current/pipeline-reliability-improvements/2026-01-09-SAME-DAY-PIPELINE-TIMING-FIX.md`
- **V8 Deployment:** `docs/08-projects/current/ml-model-v8-deployment/PRODUCTION-DEPLOYMENT.md`
- **Monitoring Gaps:** `docs/07-monitoring/observability-gaps.md`
- **Daily Validation:** `docs/02-operations/daily-validation-checklist.md`

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| (none) | Recovery only - no code changes committed |

Documentation created:
- `docs/08-projects/current/pipeline-reliability-improvements/2026-01-09-SAME-DAY-PIPELINE-TIMING-FIX.md`
- `docs/09-handoff/2026-01-09-SAME-DAY-PIPELINE-FIX-HANDOFF.md` (this file)

---

## Technical Context

### Why V8 Uses Fallback

The CatBoostV8 class tries to load model from:
1. Explicit path (not set)
2. `CATBOOST_V8_MODEL_PATH` env var (NOT SET - this is the bug)
3. Local `models/` directory (doesn't exist in Cloud Run)

When all fail, it falls back to simple average:
```python
def _fallback_prediction(self, ...):
    return {
        'confidence_score': 50.0,  # This is why all scores are 50
        'recommendation': 'PASS',   # This is why no OVER/UNDER
        'model_type': 'fallback',
    }
```

### Why 0% Prop Coverage Happened

Timeline:
```
12:45 PM ET - UPGC ran (props NOT in BigQuery yet)
12:59 PM ET - BettingPros props first available
```

UPGC uses LEFT JOIN with props table:
```sql
LEFT JOIN props pr ON p.player_lookup = pr.player_lookup
...
CASE WHEN pr.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_prop_line
```

When props table was empty, all players got `has_prop_line = false`.

---

*Handoff created: January 9, 2026*
