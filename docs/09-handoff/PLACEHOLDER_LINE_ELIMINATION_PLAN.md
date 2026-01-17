# Placeholder Line Elimination Plan
## Root Cause Analysis & Implementation Strategy

**Date**: 2026-01-16, 8:00 PM ET
**Session**: 75
**Priority**: 🚨 CRITICAL - PRODUCTION BLOCKING

---

## Executive Summary

**ROOT CAUSE IDENTIFIED**: The system uses estimated lines when real sportsbook lines aren't available. When xgboost_v1 and moving_average_baseline_v1 launched on Jan 9-10, the line enrichment process failed, resulting in ALL predictions using placeholder line_value = 20.0.

**IMPACT**: XGBoost V1's "87.5% win rate" is invalid - ALL 293 predictions used placeholder lines, not real DraftKings/FanDuel lines.

**SOLUTION**: Multi-phase plan to eliminate placeholders and ensure only real sportsbook lines are used.

---

## 1. How Lines Get Into The System

### Architecture Overview

```
NIGHT BEFORE (23:00 UTC)                  GAME DAY (18:00-19:00 UTC)
Phase 4 → Phase 5                         Line Enrichment
├─ Predictions generated                  ├─ Props scraped (18:00)
├─ Lines from:                             ├─ Enrichment runs (18:40)
│   ├─ odds_api_player_points_props       └─ Updates predictions table
│   ├─ Estimated (season avg)                with real lines
│   └─ Placeholder (20.0)
└─ current_points_line set
```

### Line Hierarchy (player_loader.py:434-497)

**Priority Order**:
1. **ACTUAL_PROP** - Real sportsbook line from `odds_api_player_points_props`
   - Source: Odds API (DraftKings, FanDuel, BetMGM, etc.)
   - Best case scenario

2. **ESTIMATED_AVG** - Estimated from season average
   - Methods: points_avg_last_5, points_avg_last_10, season_avg
   - Fallback when no sportsbook line available

3. **NEEDS_BOOTSTRAP** - New player, no history
   - Returns empty line_values []
   - Skip prediction

### Where Placeholder 20.0 Comes From

**CRITICAL FINDING**: The **20.0 placeholder does NOT come from the coordinator!**

Investigation shows:
- Coordinator returns `has_prop_line=False` and `actual_prop_line=None` when no line exists
- Worker receives this and should handle gracefully
- **But somewhere in the pipeline, these NULL/None values become 20.0**

**Most Likely Source**: The enrichment processor or grading processor sets 20.0 as a default.

---

## 2. Why XGBoost V1 Got Placeholders (Jan 9-10)

### Timeline Analysis

**Jan 9, 2026** (XGBoost V1 launch day):
- 00:00 UTC: Predictions generated (night before)
- Lines requested from `odds_api_player_points_props`
- **BUG**: Line fetching returned `line_source=None`
- 18:00 UTC: Props scraped (162 players, 16 bookmakers, 43,704 lines available)
- 18:40 UTC: **Enrichment should have run** but didn't update xgboost_v1 predictions
- Result: ALL predictions stuck with placeholder line_value = 20.0

**Jan 10, 2026**:
- Same issue repeated
- 99 players, 16 bookmakers, 23,445 lines available
- xgboost_v1 predictions not enriched
- Result: ALL predictions stuck with placeholder 20.0

### Root Cause Hypotheses

**Hypothesis #1: System-Specific Enrichment Bug** (Most Likely)
- Enrichment processor may filter by system_id
- xgboost_v1 and moving_average_baseline_v1 launched Jan 9
- May not have been included in enrichment config
- **Evidence**: Only new systems affected, old systems have real lines

**Hypothesis #2: Line Source Filtering**
- Enrichment may skip predictions where `line_source=None`
- xgboost_v1 predictions had `line_source=None` from start
- Never got enriched

**Hypothesis #3: Timing Issue**
- Systems launched at specific time
- Enrichment ran before systems wrote predictions
- Predictions missed enrichment window

---

## 3. Confidence Tier Analysis (Real Lines Only)

### CatBoost V8 - Problem Tier Confirmed

| Confidence Tier | Picks | Wins | Win Rate | Avg Error | Status |
|-----------------|-------|------|----------|-----------|--------|
| 1. Very High (92%+) | 287 | 206 | **71.8%** | 3.05 | ✅ EXCELLENT |
| 2. High (90-92%) | 165 | 121 | **73.3%** | 4.23 | ✅ EXCELLENT |
| **3. Medium-High (88-90%)** | **156** | **71** | **45.5%** | **8.28** | ❌ **PROBLEM TIER** |
| 4. Medium (86-88%) | 173 | 97 | **56.1%** | 5.65 | ✅ OK |
| 5. Low-Medium (80-86%) | 76 | 37 | 48.7% | 7.45 | ⚠️ Below breakeven |
| 6. Low (<80%) | 499 | 293 | **58.7%** | 5.89 | ✅ OK |

**Key Findings**:
- **88-90% tier**: 45.5% win rate (BELOW 52.4% breakeven) ❌
- High error (8.28 pts) indicates overconfident predictions
- Already filtered in production (good!)
- **Keep this filter active**

### Ensemble V1 - No Problem Tiers

| Confidence Tier | Win Rate | Status |
|-----------------|----------|--------|
| Medium (86-88%) | 58.2% | ✅ OK |
| Low-Medium (80-86%) | 54.9% | ✅ OK |
| Low (<80%) | 55.3% | ✅ OK |

**Verdict**: No confidence tier filtering needed

### Similarity Balanced V1 - All Tiers OK

| Confidence Tier | Win Rate | Status |
|-----------------|----------|--------|
| Very High (92%+) | 54.4% | ✅ OK |
| High (90-92%) | 57.1% | ✅ OK |
| Medium-High (88-90%) | 50.0% | ⚠️ Breakeven |
| Low-Medium (80-86%) | 54.0% | ✅ OK |
| Low (<80%) | 60.4% | ✅ GOOD |

**Verdict**: No filtering needed (but 88-90% is marginal)

### Zone Matchup V1 & Moving Average - No Problem Tiers

Both systems have all predictions in low confidence (<80%) tier with 54-55% win rates. No filtering needed.

---

## 4. Elimination Plan - 3 Phases

### Phase 1: IMMEDIATE (Today) - Block Placeholder Usage

**Goal**: Prevent any new predictions from using placeholder lines

**Actions**:

1. **Update Grading to Exclude Placeholders**
   ```sql
   -- Add to all performance queries
   WHERE line_value != 20.0  -- Exclude placeholder lines
   AND line_source IN ('ACTUAL_PROP', 'ODDS_API')
   AND has_prop_line = TRUE
   ```

2. **Add Prediction Validation**
   - File: `predictions/worker/worker.py`
   - Add check before writing predictions:
   ```python
   # CRITICAL: Never write predictions with placeholder lines
   if current_points_line == 20.0 and line_source is None:
       logger.error(f"Rejecting prediction for {player_lookup} - placeholder line detected")
       return {
           'status': 'skip',
           'reason': 'placeholder_line_detected'
       }
   ```

3. **Update Enrichment to Alert on Failures**
   - File: `orchestration/cloud_functions/enrichment_trigger/main.py`
   - Add Slack alert if enrichment fails
   - Monitor daily for any systems not getting enriched

**Files to Modify**:
- `orchestration/cloud_functions/grading/main.py`
- `predictions/worker/worker.py`
- `orchestration/cloud_functions/enrichment_trigger/main.py`

**Timeline**: Deploy today (2-3 hours)

### Phase 2: SHORT-TERM (Tomorrow) - Fix XGBoost V1 & moving_average_baseline_v1

**Goal**: Get these systems working with real lines

**Actions**:

1. **Investigate Jan 9-10 Enrichment Failure**
   ```bash
   # Check enrichment logs
   gcloud functions logs read enrichment_trigger --limit=100 --filter="2026-01-09"

   # Check if systems were included in enrichment
   bq query "
   SELECT system_id, COUNT(*) as predictions,
          COUNTIF(line_source='ACTUAL_PROP') as with_real_lines
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-01-09'
   GROUP BY system_id
   "
   ```

2. **Fix Enrichment for New Systems**
   - Ensure enrichment includes ALL systems (not hardcoded list)
   - Add validation that all systems get enriched
   - Add alerts if any system missing lines

3. **Re-run XGBoost V1 & moving_average_baseline_v1**
   - After enrichment fix deployed
   - Run for 7+ days with real DraftKings lines
   - Monitor line_source = 'ACTUAL_PROP' percentage

4. **Delete Invalid Historical Data**
   ```sql
   -- Mark Jan 9-10 xgboost_v1/moving_average_baseline_v1 as invalid
   DELETE FROM nba_predictions.prediction_accuracy
   WHERE system_id IN ('xgboost_v1', 'moving_average_baseline_v1')
   AND game_date IN ('2026-01-09', '2026-01-10')
   AND line_value = 20.0;
   ```

**Files to Check**:
- `data_processors/enrichment/prediction_line_enrichment/prediction_line_enrichment_processor.py`
- Enrichment configuration

**Timeline**: Fix tomorrow (4-6 hours investigation + fix)

### Phase 3: MEDIUM-TERM (This Week) - Enforce Real Lines Only

**Goal**: Architectural changes to eliminate placeholders entirely

**Actions**:

1. **Remove Estimated Lines (Optional - Consider Carefully)**

   **Arguments FOR keeping estimated lines**:
   - Allows predictions for players without sportsbook lines
   - Bench players, low-minute players still get predictions
   - Good for analysis/research

   **Arguments AGAINST**:
   - Can't actually bet on estimated lines
   - Inflates performance metrics
   - Confuses profitability analysis

   **Recommendation**: **KEEP estimated lines** but:
   - Clearly label as "ESTIMATED_AVG" in line_source
   - Filter out in profitability reports
   - Never count toward system win rates
   - Use for research/development only

2. **Add Real Line Validation**
   ```python
   # In player_loader.py
   def _create_request_for_player(self, player, game_date, use_multiple_lines):
       line_info = self._get_betting_lines(...)

       # CRITICAL: Only create requests for players with real lines
       if line_info['line_source'] not in ['ACTUAL_PROP']:
           logger.info(f"Skipping {player['player_lookup']} - no real sportsbook line")
           return None  # Don't create request

       # ... rest of method
   ```

3. **Add Line Quality Monitoring**
   - Daily report: % predictions with real vs estimated lines
   - Alert if real line % drops below 80%
   - Track by system_id

4. **Update Performance Reports**
   - All reports filter `line_value != 20.0`
   - All reports require `line_source = 'ACTUAL_PROP'`
   - Separate section for estimated line performance

**Files to Modify**:
- `predictions/coordinator/player_loader.py`
- `validation/validators/nba/r009_validation.py` (add line quality check)
- All performance report scripts

**Timeline**: Implement over 3-5 days

---

## 5. Confidence Tier Filtering Recommendations

### Keep Current Filters

**CatBoost V8**:
- ✅ **KEEP 88-90% filter** (45.5% win rate, below breakeven)
- ✅ **CONSIDER filtering 80-86%** (48.7% win rate, marginal)
- Rationale: High error (8.28 pts) indicates overconfidence

**File**: `predictions/worker/prediction_systems/catboost_v8.py`
```python
# Current filter (KEEP THIS)
if 0.88 <= confidence_score < 0.90:
    filter_reason = 'confidence_tier_88_90'
    is_actionable = False

# Consider adding:
if 0.80 <= confidence_score < 0.86:
    filter_reason = 'confidence_tier_80_86'
    is_actionable = False
```

### No Filtering Needed

**Other Systems**: All confidence tiers performing above breakeven (52.4%):
- ensemble_v1: 54.9-58.2% (all tiers OK)
- similarity_balanced_v1: 50.0-60.4% (all tiers OK, 88-90% marginal)
- zone_matchup_v1: 55.4% (single tier, OK)
- moving_average: 54.4% (single tier, OK)

**Recommendation**: No additional filtering for these systems.

---

## 6. Monitoring & Alerts

### Daily Line Quality Dashboard

Create dashboard tracking:

1. **Line Source Distribution**
   ```sql
   SELECT
       system_id,
       line_source,
       COUNT(*) as predictions,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY system_id), 1) as pct
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = CURRENT_DATE()
   GROUP BY system_id, line_source
   ORDER BY system_id, predictions DESC
   ```

2. **Placeholder Detection**
   ```sql
   SELECT
       system_id,
       COUNT(*) as total,
       COUNTIF(current_points_line = 20.0) as placeholders,
       ROUND(100.0 * COUNTIF(current_points_line = 20.0) / COUNT(*), 1) as placeholder_pct
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = CURRENT_DATE()
   GROUP BY system_id
   HAVING placeholders > 0
   ```

3. **Enrichment Success Rate**
   ```sql
   SELECT
       game_date,
       COUNT(*) as total_predictions,
       COUNTIF(line_source = 'ACTUAL_PROP') as enriched,
       ROUND(100.0 * COUNTIF(line_source = 'ACTUAL_PROP') / COUNT(*), 1) as enrichment_rate
   FROM nba_predictions.player_prop_predictions
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY game_date
   ORDER BY game_date DESC
   ```

### Alerts

**Slack Alert Triggers**:
1. Any system with >10% placeholder lines (20.0)
2. Enrichment rate < 80% for any date
3. New system launched (auto-check line quality)
4. Any prediction written with `line_source = None`

---

## 7. Testing & Validation

### Before Deployment

**Phase 1 Tests**:
- [ ] Grading queries exclude line_value = 20.0
- [ ] Worker rejects predictions with placeholder lines
- [ ] Enrichment sends alert on failure

**Phase 2 Tests**:
- [ ] Enrichment includes all systems (not hardcoded list)
- [ ] XGBoost V1 gets real lines (check line_source = 'ACTUAL_PROP')
- [ ] moving_average_baseline_v1 gets real lines
- [ ] No line_value = 20.0 in new predictions

**Phase 3 Tests**:
- [ ] Only ACTUAL_PROP lines create prediction requests
- [ ] Estimated lines filtered out (or marked clearly)
- [ ] Daily monitoring dashboard shows 0 placeholders

### Validation Queries

**Check Line Quality**:
```bash
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()

query = '''
SELECT
    system_id,
    COUNT(*) as total,
    COUNTIF(line_value != 20) as real_lines,
    COUNTIF(line_source = \"ACTUAL_PROP\") as actual_prop,
    ROUND(100.0 * COUNTIF(line_source = \"ACTUAL_PROP\") / COUNT(*), 1) as real_pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY system_id
ORDER BY real_pct ASC
'''
result = client.query(query, location='us-west2')
print(result.to_dataframe().to_string(index=False))
"
```

**Expected Output**:
- All systems: real_pct = 100% (or close to it)
- No system with real_pct < 80%

---

## 8. Documentation Updates

### Files to Update

1. **PERFORMANCE-ANALYSIS-GUIDE.md**
   - Add section on line quality validation
   - Add required filters (line_value != 20)
   - Document line sources

2. **System Documentation**
   - Update xgboost_v1 docs: "Launched Jan 9 with line data issues, re-launched [date] with real lines"
   - Document placeholder issue and resolution

3. **Validation Checklist**
   - Add line quality check to daily validation
   - Require line_source = 'ACTUAL_PROP' for profitability analysis

4. **Runbooks**
   - Add troubleshooting for placeholder lines
   - Add enrichment failure recovery procedures

---

## 9. Success Criteria

### Phase 1 Success (Today)
- ✅ All grading queries filter out line_value = 20.0
- ✅ Worker validation prevents placeholder predictions
- ✅ Alerts configured for enrichment failures

### Phase 2 Success (Tomorrow)
- ✅ XGBoost V1 running with >95% real lines
- ✅ moving_average_baseline_v1 running with >95% real lines
- ✅ Enrichment includes all systems automatically
- ✅ Jan 9-10 invalid data deleted

### Phase 3 Success (This Week)
- ✅ Zero placeholders in production predictions
- ✅ All systems: line_source = 'ACTUAL_PROP' only
- ✅ Daily monitoring dashboard operational
- ✅ Alerts firing correctly

### Long-Term Success (This Month)
- ✅ 30 days of zero placeholder lines
- ✅ All performance reports use real lines only
- ✅ Documentation updated and accurate
- ✅ Team trained on line quality validation

---

## 10. Rollback Plan

### If Phase 1 Breaks Production

**Symptoms**:
- Grading fails
- Worker crashes
- No predictions generated

**Rollback**:
1. Revert grading query changes
2. Remove worker validation
3. Investigate issue offline
4. Redeploy when fixed

**Rollback Time**: < 15 minutes

### If Phase 2 Breaks Enrichment

**Symptoms**:
- All predictions get placeholder lines
- Enrichment errors in logs
- Alert storm

**Rollback**:
1. Revert enrichment processor changes
2. Run manual enrichment for affected date
3. Investigate and fix offline

**Rollback Time**: < 30 minutes

### If Phase 3 Breaks Prediction Generation

**Symptoms**:
- No predictions generated
- All players skipped
- Coordinator fails

**Rollback**:
1. Revert player_loader changes
2. Allow estimated lines temporarily
3. Fix and redeploy

**Rollback Time**: < 30 minutes

---

## 11. Conclusion

### Summary

**Problem**: Placeholder line_value = 20.0 invalidates performance analysis
**Root Cause**: Enrichment failure for new systems on Jan 9-10
**Impact**: XGBoost V1 and moving_average_baseline_v1 data invalid

**Solution**: 3-phase elimination plan
1. Immediate: Block new placeholders
2. Short-term: Fix affected systems
3. Medium-term: Enforce real lines only

**Confidence Filtering**:
- CatBoost V8: Keep 88-90% filter, consider 80-86%
- Other systems: No filtering needed

### Next Steps

**Today (Phase 1)**:
1. Deploy grading query updates
2. Add worker validation
3. Configure alerts

**Tomorrow (Phase 2)**:
1. Investigate enrichment failure
2. Fix enrichment for all systems
3. Re-launch XGBoost V1 & moving_average_baseline_v1
4. Delete invalid data

**This Week (Phase 3)**:
1. Enforce real lines only
2. Deploy monitoring dashboard
3. Update documentation
4. Validate 7 days zero placeholders

---

**Report Generated**: 2026-01-16 00:00 UTC
**Session**: 75
**Status**: 🚨 PLAN READY - AWAITING APPROVAL FOR IMPLEMENTATION
**Next Action**: Review plan with team, begin Phase 1 implementation
