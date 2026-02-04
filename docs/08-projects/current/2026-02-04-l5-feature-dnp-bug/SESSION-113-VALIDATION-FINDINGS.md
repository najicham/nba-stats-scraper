# Session 113 - Daily Validation Findings (Feb 3, 2026)

**Date**: Feb 3, 2026 11 PM ET
**Validation Target**: Feb 2, 2026 games (4 games, all final)
**Status**: 🔴 CRITICAL ISSUES FOUND

## Executive Summary

Multiple critical issues detected:
1. **Phase 2→3 orchestrator not triggering** (7/7 processors complete, not triggered)
2. **Model bias causing 49.1% hit rate** (below breakeven)
3. **0/7 high-edge picks** (all were UNDERs on under-predicted stars)
4. **Stale running cleanup alerts** (7 stuck records at 6 PM)

## Validation Results

### Phase Completion Status

| Phase | Status | Details |
|-------|--------|---------|
| Phase 2 (Scrapers) | ✅ OK | 7/7 processors complete |
| Phase 2→3 Trigger | 🔴 **FAILED** | Phase 3 NOT triggered despite 7/7 complete |
| Phase 3 (Analytics) | 🟡 PARTIAL | 1/5 processors (only upcoming_player_game_context) |
| Phase 4 (Precompute) | ⚠️ UNKNOWN | Not checked yet |
| Phase 5 (Predictions) | ✅ OK | 111 predictions, 69 active, 69 actionable |
| Grading | ✅ OK | 62/62 predictions graded (100%) |

### Data Completeness

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Games | 4 | 4 | ✅ OK |
| Player records | ~200 | 140 | ⚠️ LOW |
| Team records | 8 | 8 | ✅ OK |
| Predictions | ~100 | 111 | ✅ OK |
| ML Features | ~150 | 151 | ✅ OK |

### Model Performance (Feb 2)

| Metric | Value | Status |
|--------|-------|--------|
| **Overall Hit Rate** | **49.1%** | 🔴 **CRITICAL** |
| High-edge picks (5+) | 0/7 (0.0%) | 🔴 **CRITICAL** |
| Medium-edge picks (3-5) | 2/4 (50.0%) | 🔴 POOR |
| Low-edge picks (<3) | 24/42 (57.1%) | 🟡 MARGINAL |
| Predictions graded | 62/62 (100%) | ✅ OK |

### Model Bias Analysis

**CRITICAL FINDING**: Severe regression-to-mean bias detected.

| Player Tier | Predictions | Avg Predicted | Avg Actual | Bias | Status |
|-------------|-------------|---------------|------------|------|--------|
| **Stars (25+)** | 10 | 18.3 | 30.0 | **-11.7** | 🔴 **CRITICAL** |
| Starters (15-24) | 19 | 13.3 | 18.0 | -4.7 | 🟡 WARNING |
| Role (5-14) | 23 | 11.4 | 9.0 | +2.5 | 🟡 WARNING |
| Bench (<5) | 10 | 7.0 | 2.7 | +4.3 | 🟡 WARNING |

**Impact**:
- Model under-predicted stars by 11.7 pts on average
- All 7 high-edge picks were UNDERs on stars (because model thinks stars will score 18, line is 13)
- Stars actually scored 30, so all UNDERs lost

### Recommendation Distribution

| Direction | Count | Hit Rate | Status |
|-----------|-------|----------|--------|
| UNDER | 51 | 49.0% | 🔴 CRITICAL |
| OVER | 2 | 50.0% | 🔴 POOR |
| PASS | 9 | N/A | - |

**Heavy UNDER skew** (51 UNDER vs 2 OVER) - this is the RED signal pattern.

## Root Causes Identified

### 1. Phase 2→3 Orchestrator Not Triggering

**Evidence**:
```
Phase 2 Completion for 2026-02-02:
  Processors: 7, Phase 3 triggered: False
  🔴 BUG: Phase 2 complete but Phase 3 NOT triggered!
```

**Firestore state**:
- `phase2_completion/2026-02-02`: 7 processors complete
- `_triggered = False` (should be True)

**Orchestrator logs**:
- Receiving `BdlLiveBoxscoresProcessor` completions for Feb 3 data
- WARNING: "Processor name 'BdlLiveBoxscoresProcessor' not in explicit mapping"
- No trigger for Feb 2 Phase 3

**Why analytics data exists anyway**:
- Phase 3 processors may have been manually triggered
- Or evening analytics workflow ran (6 PM, 10 PM, 1 AM)
- Only 1/5 Phase 3 processors completed (upcoming_player_game_context)

**Impact**:
- Phase 3 incomplete (1/5 processors)
- Phase 4 may not have run with complete data
- Pipeline stalled at Phase 2→3 transition

**Recommended Fix**:
1. Check orchestrator code for trigger logic bug
2. Manually trigger Phase 3 for Feb 2: `gcloud scheduler jobs run same-day-phase3`
3. Monitor Firestore for `_triggered` field updates
4. Add monitoring alert for `_triggered = False` when processors complete

### 2. Model Bias (Regression-to-Mean)

**Same as Session 102 discovery** - Model has systematic bias:
- Under-predicts stars by ~12 pts
- Over-predicts bench by ~4 pts
- Causes high-edge picks to all be losing UNDERs on stars

**Reference**: `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`

**Recommended Fix**:
- V10 model retraining with tier features
- OR post-prediction recalibration by tier
- OR switch to quantile regression

### 3. Stale Running Cleanup Alerts

**Evidence from Slack**:
```
[6:00 PM] Marked 7 stuck records as failed
Processors: TeamOffenseGameSummaryProcessor(4),
           AsyncUpcomingPlayerGameContextProcessor(2),
           UpcomingTeamGameContextProcessor(1)
```

**Impact**: Processors getting stuck, requiring cleanup

**Recommended Investigation**:
- Check heartbeat system logs
- Review processor timeout settings
- Check if processors are deadlocking

## Slack Alerts Analysis

### 1. NBA Scrapers - HTTP Errors Detected
- **Status**: CLEARED
- **Details**: "Request Count returned to normal with a value of 0.000"
- **Assessment**: Transient 400 errors, now resolved

### 2. NBA Pipeline Auth Errors Detected
- **Service**: nba-phase2-raw-processors
- **Status**: CLEARED
- **Details**: "returned to normal with a value of 7.000"
- **Assessment**: Auth errors cleared (likely missing email config vars)

### 3. NBA Scrapers - Application Warning Detected
- **Status**: CLEARED
- **Details**: Warnings returned to normal
- **Assessment**: Transient warnings, now resolved

### 4. Stale Running Cleanup (6:00 PM, 6:30 PM, 7:30 PM)
- **Impact**: 7 stuck records marked as failed at 6 PM
  - TeamOffenseGameSummaryProcessor (4)
  - AsyncUpcomingPlayerGameContextProcessor (2)
  - UpcomingTeamGameContextProcessor (1)
- **Impact**: 1 more at 6:30 PM (MLFeatureStoreProcessor)
- **Impact**: 2 more at 7:30 PM (PredictionCoordinator)
- **Assessment**: Processors timing out or deadlocking
- **Action**: Investigate heartbeat system and processor timeout settings

### 5. BDL API Missing Games (7:05 PM)
- **Details**: "10 game(s) expected but NOT returned by BDL API"
- **Games**: DEN@DET, NYK@WAS, ATL@MIA, LAL@BKN
- **Timing**: 7:05 PM post_game_window_1
- **Assessment**: Games hadn't completed yet (normal for 7 PM check)
- **Note**: Message correctly states "may not have completed yet"

## Deployment Drift Check

**Services checked**: 5 key services
**Status**: ✅ All services up to date

| Service | Status | Last Deployed |
|---------|--------|---------------|
| nba-phase3-analytics-processors | ✅ Up to date | 2026-02-03 18:19 |
| nba-phase4-precompute-processors | ✅ Up to date | 2026-02-03 19:53 |
| prediction-coordinator | ✅ Up to date | 2026-02-03 19:47 |
| prediction-worker | ✅ Up to date | 2026-02-03 19:07 |
| nba-phase1-scrapers | ✅ Up to date | 2026-02-02 14:37 |

**Services not checked** (no source tracking):
- phase4-to-phase5-orchestrator
- phase3-to-phase4-orchestrator
- nba-phase2-raw-processors
- nba-admin-dashboard

## Immediate Actions Required

### Priority 1 - CRITICAL (Do Now)

1. **Investigate Phase 2→3 orchestrator trigger failure**
   - Check orchestrator code for bug in trigger logic
   - Review Firestore trigger conditions
   - Add monitoring for stuck `_triggered = False` state

2. **Complete Phase 3 for Feb 2**
   - Manually trigger: `gcloud scheduler jobs run same-day-phase3`
   - Verify 5/5 processors complete
   - Check Phase 4 ran with complete data

3. **Investigate model bias**
   - Review Session 102 findings
   - Consider V10 model retraining
   - OR implement post-prediction recalibration

### Priority 2 - HIGH (Today)

4. **Investigate stuck processor cleanup**
   - Check heartbeat system logs
   - Review processor timeout settings
   - Identify why processors are getting stuck

5. **Run full data quality validation**
   - Run spot checks for Feb 2
   - Check usage_rate coverage
   - Verify rolling averages

### Priority 3 - MEDIUM (This Week)

6. **Add monitoring for orchestrator triggers**
   - Alert when `_triggered = False` for >1 hour after completion
   - Dashboard showing phase transition status
   - Slack notification for stuck triggers

7. **Review processor heartbeat system**
   - Check for document proliferation
   - Verify cleanup scripts running
   - Add monitoring for stuck processors

## Reference Documents

- Session 102 Model Bias Investigation: `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md`
- Session 102 Handoff: `docs/09-handoff/2026-02-03-SESSION-102-HANDOFF.md`
- Phase Orchestrator Code: `orchestration/cloud_functions/phase2_to_phase3/main.py`
- Heartbeat System: `shared/monitoring/processor_heartbeat.py`

## Validation Command Reference

```bash
# Check Phase 2 completion
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase2_completion').document('2026-02-02').get()
if doc.exists:
    data = doc.to_dict()
    print(f"Processors: {len([k for k in data.keys() if not k.startswith('_')])}")
    print(f"Triggered: {data.get('_triggered', False)}")
EOF

# Check Phase 3 completion
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase3_completion').document('2026-02-03').get()
if doc.exists:
    data = doc.to_dict()
    completed = [k for k in data.keys() if not k.startswith('_')]
    print(f"Processors: {len(completed)}/5")
    print(f"Completed: {completed}")
    print(f"Triggered: {data.get('_triggered', False)}")
EOF

# Check model bias
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN actual_points >= 25 THEN '1_Stars (25+)'
    WHEN actual_points >= 15 THEN '2_Starters (15-24)'
    WHEN actual_points >= 5 THEN '3_Role (5-14)'
    ELSE '4_Bench (<5)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points - actual_points), 1) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date = DATE('2026-02-02')
  AND actual_points IS NOT NULL
GROUP BY tier
ORDER BY tier"

# Manually trigger Phase 3
gcloud scheduler jobs run same-day-phase3 --location=us-west2
```

## Next Session TODO

1. Fix Phase 2→3 orchestrator trigger bug
2. Complete Phase 3 for Feb 2
3. Investigate model bias (V10 retraining or recalibration)
4. Add monitoring for stuck orchestrator triggers
5. Review heartbeat system for stuck processor detection
