# Daily Validation Issues - 2026-02-02

**Validation Type:** Yesterday's Results (2026-02-01 games)
**Thoroughness:** Comprehensive
**Date Run:** 2026-02-02 21:43 PST
**Games Validated:** 10 games (all Final)

---

## Executive Summary

**Overall Status:** 🟡 **WARNING** - Multiple issues detected requiring investigation

**Critical Issues:** 2
**Warnings:** 4
**Informational:** 3

---

## 🔴 CRITICAL ISSUES

### 1. Deployment Drift (P1 CRITICAL)

**Impact:** Data processed with old code, bug fixes not deployed

**Details:**
- **nba-phase3-analytics-processors**: STALE (deployed 2026-02-02 19:26, code changed 19:36)
- **nba-phase4-precompute-processors**: STALE (deployed 2026-02-02 19:28, code changed 19:36)
- **prediction-coordinator**: STALE (deployed 2026-02-02 18:51, code changed 19:36)

**Recent undeployed commit:**
```
2993e9fd feat: Add Phase 6 subset exporters with Opus review fixes
```

**Severity Justification:**
- All 3 services showing drift
- Code changes made 10-45 minutes after deployment
- Historical precedent: Sessions 82, 81, 64 had critical bugs persist due to deployment drift

**Recommendation:**
```bash
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh prediction-coordinator
```

**Question for Opus:** Does commit `2993e9fd` affect Phase 3/4 processing, or is it only Phase 6 exports? If only Phase 6, severity downgrade to P2.

---

### 2. Low-Edge Predictions Generated (P1 CRITICAL - Edge Filter Not Working)

**Impact:** Predictions with edge < 3 being created, which historically have 50% hit rate and lose money

**Details:**
- **Date:** 2026-02-02
- **Low-edge predictions:** 54 (edge < 3)
- **High-edge predictions:** 36 (edge >= 3)
- **Created:** 2026-02-02 21:38:27 - 21:44:41 UTC (recent)

**Expected Behavior (Session 81 fix):**
- Edge filter should exclude predictions with edge < 3
- Only predictions with edge >= 3 or NO_PROP_LINE should exist

**Actual Behavior:**
- 54 predictions with edge < 3 created tonight
- Filter appears to NOT be working

**Investigation Needed:**
1. Check if `MIN_EDGE_THRESHOLD` environment variable is set on prediction-coordinator
2. Check consolidation logs for "Edge filtering ENABLED" message
3. Verify Session 81 edge filter code is deployed
4. Sample low-edge predictions to see if they share a pattern

**Recommendation:**
```bash
# 1. Check env var
gcloud run services describe prediction-coordinator \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env[?(@.name=='MIN_EDGE_THRESHOLD')].value)"

# 2. Check logs
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-coordinator"
  AND textPayload=~"Session 81: Edge filtering"' \
  --limit=10 --format="table(timestamp,textPayload)"

# 3. Sample low-edge predictions
bq query --use_legacy_sql=false "
SELECT player_lookup, predicted_points, current_points_line,
  ABS(predicted_points - current_points_line) as edge, created_at
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-02'
  AND system_id = 'catboost_v9'
  AND line_source != 'NO_PROP_LINE'
  AND ABS(predicted_points - current_points_line) < 3
ORDER BY created_at DESC
LIMIT 10"
```

**Question for Opus:** Is edge filter supposed to be working by now? Session 81 was deployed, but are these predictions created before the filter was enabled?

---

## 🟡 WARNING ISSUES

### 3. Phase 3 Incomplete (P2 WARNING)

**Impact:** Downstream predictions may be missing team game context features

**Details:**
- **Completion:** 4/5 processors (80%)
- **Missing:** `upcoming_team_game_context`
- **Phase 4 triggered:** TRUE (despite incomplete Phase 3)

**Processors that completed:**
- ✅ player_game_summary: success
- ✅ team_offense_game_summary: success
- ✅ team_defense_game_summary: success
- ✅ upcoming_player_game_context: success
- ❌ upcoming_team_game_context: MISSING

**Expected:** 5/5 processors

**Investigation Needed:**
1. Check Cloud Run logs for `upcoming_team_game_context` processor
2. Determine if processor crashed, timed out, or never triggered
3. Check if predictions are missing team-level features due to this gap

**Recommendation:**
```bash
# Check logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50 | grep "upcoming_team_game_context"

# Check if manual retry needed
# (Command TBD based on log findings)
```

---

### 4. Grading Completeness - New Model Low (P2 WARNING)

**Impact:** Cannot properly evaluate `catboost_v9_2026_02` model performance

**Details:**
- **Model:** `catboost_v9_2026_02`
- **Grading coverage:** 46.1% (CRITICAL threshold)
- **Predictions:** 96 total, 89 gradable, 41 graded, 7 ungradable
- **Line availability:** 92.7% (good)

**Comparison (other models for context):**
- `catboost_v9`: 84.6% grading coverage (OK)
- `ensemble_v1_1`: 110.7% grading coverage (OK)

**Severity Justification:**
- New model just deployed
- 92.7% line availability means lines exist
- Only 46.1% graded suggests grading pipeline issue, NOT line availability issue

**Investigation Needed:**
1. Check when `catboost_v9_2026_02` predictions were created
2. Check if grading service has processed these predictions
3. Verify grading service recognizes the new system_id

**Recommendation:**
```bash
# Check prediction creation times
bq query --use_legacy_sql=false "
SELECT MIN(created_at) as first, MAX(created_at) as latest, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9_2026_02'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)"

# Check grading service logs
gcloud logging read 'resource.labels.service_name="prediction-grader"
  AND jsonPayload.system_id="catboost_v9_2026_02"' \
  --limit=20 --freshness=24h
```

**Question for Opus:** Is `catboost_v9_2026_02` a new model that just started generating predictions? If so, grading lag is expected and severity should be P3.

---

### 5. BDL Raw Data Quality Low (P2 WARNING)

**Impact:** Raw data source has incomplete minutes data, but Phase 3 analytics compensates

**Details:**
- **BDL raw table:** 62.1% minutes coverage (348 records, 216 with minutes)
- **Phase 3 analytics:** 100% minutes coverage for players who played (319/319)
- **Gap:** Phase 3 is filling in missing data successfully

**Observation:**
- BDL data missing minutes for 132 records (37.9%)
- Analytics layer successfully backfilled all minutes
- Likely using NBAC or other source as fallback

**Investigation Needed:**
1. Verify which source Phase 3 is using for minutes (BDL vs NBAC)
2. Check if this is expected behavior (BDL as backup, NBAC as primary)
3. Monitor if BDL quality continues to degrade

**Recommendation:**
- ℹ️ INFO: Document this behavior in runbook
- Monitor BDL quality trend
- If BDL continues at <70%, consider removing as data source

---

### 6. Model Performance Concerns - V9 (P3 MEDIUM)

**Impact:** catboost_v9 showing inconsistent weekly performance

**Details (last 4 weeks):**

| Week Starting | Predictions | Hit Rate | Bias | Status |
|---------------|-------------|----------|------|--------|
| 2026-02-01 | 123 | **69.1%** | +1.55 | ✅ GOOD |
| 2026-01-25 | 450 | **51.6%** | -0.12 | 🔴 POOR |
| 2026-01-18 | 392 | 56.4% | -0.39 | 🟡 OK |
| 2026-01-11 | 453 | 55.6% | -0.32 | 🟡 OK |
| 2026-01-04 | 144 | 54.2% | +0.58 | 🟡 OK |

**Observations:**
- Week of Jan 25: **51.6% hit rate** (below breakeven)
- Week of Feb 1: **69.1% hit rate** (excellent recovery)
- High variance: 51.6% → 69.1% swing

**New Model Performance:**
- `catboost_v9_2026_02` (Feb 1): **83.3% hit rate** (36 predictions)
- Sample size small but promising

**Investigation Needed:**
1. What caused Jan 25 week degradation?
2. Is Feb 1 recovery sustainable or sample size noise?
3. Should we fully switch to `catboost_v9_2026_02`?

**Recommendation:**
- Monitor `catboost_v9_2026_02` for 1-2 more weeks
- If it maintains 65%+, consider making it primary model
- Investigate Jan 25 week for systematic issues (data quality, opponent difficulty, etc.)

---

## ✅ POSITIVE FINDINGS

### 7. BDB Coverage Excellent (INFO)

**Status:** ✅ 100% coverage for 2026-02-01

**Details:**
- **Games scheduled:** 10
- **BDB data available:** 10
- **Coverage:** 100%

**Context:** Session 53 discovered BDB outage Jan 17-24. Coverage has been 100% since Jan 25.

---

### 8. Heartbeat System Healthy (INFO)

**Status:** ✅ OK

**Details:**
- **Total documents:** 30 (expected: 30-50)
- **Bad format documents:** 0 (old pattern)
- **Status:** Healthy

**Context:** Firestore heartbeat proliferation was a concern in earlier sessions. System is now stable.

---

### 9. Minutes Coverage 100% for Active Players (INFO)

**Status:** ✅ OK (after correcting for DNPs)

**Details:**
- **Total players:** 539
- **Players who played:** 319
- **Players with minutes:** 319
- **Coverage:** 100% for active players
- **DNP players:** 220 (expected to have NULL minutes)

**Initial Concern:** 59.2% overall coverage looked CRITICAL
**Resolution:** DNPs are expected to have NULL minutes. When excluding DNPs, coverage is perfect.

---

## 📊 DATA SUMMARY

### Games Processed
- **Date:** 2026-02-01
- **Games:** 10 (all Final)
- **Player records:** 539 (319 active, 220 DNP)
- **Analytics tables:** Populated

### Pipeline Status
- **Phase 3:** 4/5 complete (WARNING)
- **Phase 4:** Triggered (despite Phase 3 incomplete)
- **Phase 5:** Predictions generated
- **BDB Coverage:** 100%

### Data Quality Spot Checks
- **Samples tested:** 10
- **Samples passed:** 9/10 (90%)
- **Check accuracy:** 50% (10 passed, 1 failed, 9 skipped)
- **Failure:** Mike Conley rolling average 18.18% mismatch

**Note:** High skip rate (45%) due to usage_rate checks requiring team stats. 90% sample pass rate is acceptable.

---

## VALIDATION GAPS

### Tables Not Found (Expected in New Deployments)

1. **nba_orchestration.phase_execution_log** - Not found
   - Used for: Phase transition tracking
   - Fallback: Firestore completion records (working)

2. **nba_orchestration.processor_run_history** - Not found
   - Used for: Processor execution tracking
   - Fallback: Direct table checks (working)

3. **nba_raw.nbac_gamebook** - Not found
   - Used for: Scraper verification
   - Fallback: BDL data check (working)

4. **nba_raw.nbac_gamebook_player_boxscores** - Not found
   - Used for: Box score verification
   - Fallback: BDL + analytics verification (working)

**Impact:** Validation still works via fallback checks. These tables are nice-to-have, not critical.

---

## RECOMMENDED ACTIONS (Prioritized)

### Immediate (P1 - Today)

1. **Investigate Edge Filter Failure**
   - Run investigation queries above
   - Determine why 54 low-edge predictions were created
   - Redeploy coordinator if filter not enabled

2. **Deploy Stale Services**
   - Deploy 3 services with drift (if commit affects them)
   - Verify commit `2993e9fd` scope first

### High Priority (P2 - Within 24 Hours)

3. **Investigate Phase 3 Missing Processor**
   - Check `upcoming_team_game_context` logs
   - Determine if manual retry needed
   - Impact: Predictions may be missing team features

4. **Monitor New Model Grading**
   - Wait 24 hours to see if grading catches up
   - If still <50%, investigate grading service

5. **Document BDL Data Quality**
   - Add to runbook that BDL has 62% raw quality
   - Phase 3 successfully compensates
   - Monitor trend

### Medium Priority (P3 - Within 1 Week)

6. **Analyze Model Performance Variance**
   - Deep dive on Jan 25 week (51.6% hit rate)
   - Monitor `catboost_v9_2026_02` for 2 more weeks
   - Decision: Keep V9 or switch to V9_2026_02

7. **Fix Mike Conley Rolling Average**
   - Investigate 18.18% mismatch
   - Regenerate cache if needed

---

## QUESTIONS FOR OPUS REVIEW

1. **Deployment Drift:** Does commit `2993e9fd` ("Add Phase 6 subset exporters") affect Phase 3/4 processing, or only Phase 6? If only Phase 6, can we downgrade severity to P2?

2. **Edge Filter:** Should edge filter be working by now? Were these 54 low-edge predictions created before Session 81 filter was enabled, or is filter broken?

3. **New Model:** Is `catboost_v9_2026_02` a newly deployed model? If so, 46.1% grading coverage is expected lag and severity should be P3.

4. **Phase 3 Incomplete:** Is it acceptable for Phase 4 to trigger with only 4/5 Phase 3 processors complete? Or is this a regression?

5. **Vegas Line Coverage:** Script reports 44.2% coverage as "HEALTHY" but this seems low. What's the actual threshold?

6. **Spot Check Accuracy:** 50% check accuracy with 45% skip rate - is this acceptable, or should we tune the checks?

---

## VALIDATION METADATA

**Script Execution:**
- `./bin/check-deployment-drift.sh --verbose`: Exit 1 (drift detected)
- Firestore heartbeat check: PASS
- Phase 3 completion check: WARNING (4/5)
- Spot check: 90% sample pass rate
- BDB coverage: 100%
- Model drift analysis: Completed

**Queries Run:** 15+
**Services Checked:** 9
**Tables Validated:** 10+

---

**Generated:** 2026-02-02 21:47 PST
**Session:** Session 94 (assumed)
**For Review By:** Opus 4.5
