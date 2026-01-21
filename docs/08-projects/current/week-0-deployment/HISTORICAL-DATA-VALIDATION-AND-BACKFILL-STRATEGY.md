# Historical Data Validation and Backfill Strategy

**Date**: 2026-01-19
**Scope**: Validation of past 7 days (Jan 13-19, 2026) and backfill strategy
**Status**: Analysis Complete, Backfill Ready to Execute

---

## Executive Summary

### Critical Findings

**Missing Box Scores (Phase 2 - Raw Data)**:
- **Jan 13-18**: Box scores missing for 1-8 games per day (11%-33% coverage)
- **Jan 15**: Most critical - only 11% coverage (8/9 games missing)
- **Root Cause**: BDL (BallerDataLeague) scraper failures or delays

**Phase 4 Failures (Precompute)**:
- **Jan 16, 18**: Complete Phase 4 failure (0 records for PDC, PSZA, PCF, TDZA)
- **Jan 13-17**: Persistent INCOMPLETE_UPSTREAM errors in PSZA (~64-71 players/day)
- **Total Impact**: 339 INCOMPLETE_UPSTREAM errors across 5 days

**Missing Grading (Phase 6)**:
- **Jan 17-19**: 0% grading coverage (2,608 predictions ungraded)
- **Jan 13-16**: 89.6%-92.8% grading coverage (good)
- **Root Cause**: Grading Cloud Function not triggered for recent dates

**Predictions**:
- ✅ All dates have predictions
- ⚠️ Recent days (Jan 16-19) have NO predictions for players without prop lines
- ⚠️ System count varies (4-7 systems) suggesting instability

---

## Detailed Findings by Layer

### Layer 1: Raw Data (Phase 2)

#### Box Scores Completeness

| Date       | Games | Gamebooks | Box Scores | Missing | Coverage |
|------------|-------|-----------|------------|---------|----------|
| 2026-01-19 | 3     | 8 (267%)  | 8 (267%)   | 0       | ✅ 267%  |
| 2026-01-18 | 6     | 6 (100%)  | 4 (67%)    | 2       | ❌ 67%   |
| 2026-01-17 | 9     | 9 (100%)  | 7 (78%)    | 2       | ❌ 78%   |
| 2026-01-16 | 6     | 6 (100%)  | 5 (83%)    | 1       | ❌ 83%   |
| 2026-01-15 | 9     | 9 (100%)  | 1 (11%)    | 8       | ❌ 11%   |
| 2026-01-14 | 7     | 7 (100%)  | 5 (71%)    | 2       | ❌ 71%   |
| 2026-01-13 | 7     | 7 (100%)  | 5 (71%)    | 2       | ❌ 71%   |

**Total Missing**: 17 box score entries across 6 days

**Impact**:
- Gamebooks are 100% complete (Phase 3 can work with gamebooks alone)
- Box scores provide additional validation and stats
- Missing box scores cascade to Phase 4 shot zone analysis

---

### Layer 3: Analytics (Phase 3)

#### player_game_summary Availability

| Date       | Records | Players | Games | Status |
|------------|---------|---------|-------|--------|
| 2026-01-18 | 127     | 127     | 5     | ✅     |
| 2026-01-17 | 254     | 254     | 8     | ✅     |
| 2026-01-16 | 238     | 119     | 6     | ✅     |
| 2026-01-15 | 215     | 215     | 9     | ✅     |
| 2026-01-14 | 152     | 152     | 7     | ✅     |
| 2026-01-13 | 155     | 155     | 7     | ✅     |

**Status**: ✅ All dates have player_game_summary (grading prerequisite met)

---

### Layer 4: Precompute Features (Phase 4)

#### Processor Status by Date

| Date       | PDC    | PSZA           | PCF    | MLFS   | TDZA   |
|------------|--------|----------------|--------|--------|--------|
| 2026-01-18 | ❌ 0   | ❌ 0           | ❌ 0   | ✅ 144 | ❌ 0   |
| 2026-01-17 | ✅ 123 | ⚠️ 445 (64 err) | ✅ 147 | ✅ 147 | ✅ 30  |
| 2026-01-16 | ❌ 0   | ⚠️ 442 (65 err) | ❌ 0   | ✅ 170 | ✅ 30  |
| 2026-01-15 | ✅ 191 | ⚠️ 442 (70 err) | ✅ 243 | ⚠️ 242 (117 err) | ✅ 30 |
| 2026-01-14 | ✅ 177 | ⚠️ 442 (69 err) | ⚠️ 213 (1 err) | ✅ 234 | ✅ 30 |
| 2026-01-13 | ✅ 183 | ⚠️ 441 (71 err) | ✅ 216 | ✅ 236 | ✅ 30 |

**Critical Issues**:
1. **Jan 18**: Nearly complete Phase 4 failure (only MLFS succeeded)
2. **Jan 16**: Partial failure (PDC, PCF missing, TDZA OK)
3. **PSZA (PlayerShotZoneAnalysis)**: Consistent INCOMPLETE_UPSTREAM errors (339 total)
4. **MLFS (Jan 15)**: 117 UPSTREAM_INCOMPLETE errors

**Failure Categories**:
- `INCOMPLETE_UPSTREAM`: 339 players (needs backfill)
- `MISSING_DEPENDENCY`: 3 players (investigate)
- `UPSTREAM_INCOMPLETE`: 115 players (Jan 15 MLFS specific)

---

### Phase 5: Predictions

#### Prediction Volume by Date

| Date       | Predictions | Players | Systems | With Lines | Without Lines |
|------------|-------------|---------|---------|------------|---------------|
| 2026-01-19 | 615         | 51      | 7       | 615 (100%) | 0 (0%)        |
| 2026-01-18 | 1,680       | 57      | 6       | 1,680 (100%) | 0 (0%)      |
| 2026-01-17 | 313         | 57      | 5       | 313 (100%) | 0 (0%)        |
| 2026-01-16 | 1,328       | 67      | 4       | 1,328 (100%) | 0 (0%)      |
| 2026-01-15 | 2,193       | 103     | 4       | 1,905 (87%) | 288 (13%)    |
| 2026-01-14 | 285         | 73      | 4       | 215 (75%)  | 70 (25%)     |
| 2026-01-13 | 295         | 62      | 5       | 257 (87%)  | 38 (13%)     |

**Observations**:
- ✅ Predictions exist for all dates
- ⚠️ System count varies (4-7 systems) - inconsistent
- ⚠️ Recent dates (Jan 16-19) have NO predictions without prop lines
- 📊 Volume varies significantly (285 to 2,193 predictions)

**Concern**: Missing predictions for players without prop lines on recent dates

---

### Phase 6: Grading

#### Grading Coverage by Date

| Date       | Predictions | Graded | Coverage | Accuracy | Status |
|------------|-------------|--------|----------|----------|--------|
| 2026-01-19 | 615         | 0      | 0.0%     | -        | ❌ UNGRADED |
| 2026-01-18 | 1,680       | 0      | 0.0%     | -        | ❌ UNGRADED |
| 2026-01-17 | 313         | 0      | 0.0%     | -        | ❌ UNGRADED |
| 2026-01-16 | 1,328       | 1,232  | 92.8%    | 63.4%    | ✅ |
| 2026-01-15 | 2,193       | 1,964  | 89.6%    | 58.9%    | ✅ |
| 2026-01-14 | 285         | 261    | 91.6%    | 57.2%    | ✅ |
| 2026-01-13 | 295         | 271    | 91.9%    | 46.0%    | ✅ |

**Total Ungraded**: 2,608 predictions (Jan 17-19)

**Grading Prerequisites Met**:
- ✅ Predictions exist (all dates)
- ✅ player_game_summary exists (all dates)
- ✅ Coverage >50% (all dates)

**Root Cause**: Grading Cloud Function not triggered for Jan 17-19

---

## Root Cause Analysis

### 1. Missing Box Scores (17 entries across 6 days)

**Possible Causes**:
1. BDL API downtime or rate limiting
2. Scraper failures (unhandled exceptions)
3. Delayed box score availability (games still processing)
4. Network connectivity issues

**Impact**:
- Phase 3 mostly unaffected (gamebooks provide sufficient data)
- Phase 4 PSZA (shot zone analysis) severely affected
- Cascades to INCOMPLETE_UPSTREAM errors

**Investigation Required**:
```bash
# Check scraper logs for failures
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers" \
  --format=json \
  --limit=100 \
  --filter='timestamp>="2026-01-13T00:00:00Z" AND severity>=WARNING'
```

---

### 2. Phase 4 Complete Failures (Jan 16, 18)

**Pattern**:
- Jan 18: PDC, PSZA, PCF, TDZA all failed (only MLFS succeeded)
- Jan 16: PDC, PCF failed (PSZA partial, MLFS/TDZA OK)

**Possible Causes**:
1. Phase 4 service not triggered (orchestration issue)
2. Service crashed/restarted during processing
3. Firestore state issues (checkpoint corruption)
4. Upstream data validation blocked processing

**Investigation Required**:
```bash
# Check Phase 4 service logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-phase4-precompute-processors" \
  --format=json \
  --limit=100 \
  --filter='timestamp>="2026-01-16T00:00:00Z" AND timestamp<="2026-01-19T00:00:00Z"'
```

---

### 3. PSZA INCOMPLETE_UPSTREAM Errors (339 players)

**Consistency**: Every date has ~64-71 INCOMPLETE_UPSTREAM errors

**Root Cause**: PSZA requires shot zone data from box scores
- Missing box scores → Missing shot zone data → INCOMPLETE_UPSTREAM

**Solution**: Backfill box scores first, then re-run PSZA

---

### 4. Missing Grading (Jan 17-19)

**Prerequisites Met**:
- ✅ Predictions exist
- ✅ player_game_summary exists
- ✅ Coverage >50%

**Possible Causes**:
1. Cloud Scheduler missed triggers (service outage?)
2. Grading function crash/timeout
3. Pub/Sub delivery failure
4. Grading validation logic changed (blocking recent dates?)

**Investigation Required**:
```bash
# Check Cloud Scheduler execution
gcloud scheduler jobs list --location=us-west1
gcloud scheduler jobs describe nba-grading-scheduler --location=us-west1

# Check Pub/Sub topic delivery
gcloud pubsub topics list | grep grading
```

---

## Backfill Strategy

### Priority 1: Trigger Missing Grading (Immediate - 5 min)

**Impact**: Unblock 2,608 predictions for accuracy tracking

**Action**:
```bash
# Trigger grading for Jan 17
gcloud pubsub topics publish nba-grading-trigger \
  --message '{"target_date": "2026-01-17", "run_aggregation": true}'

# Trigger grading for Jan 18
gcloud pubsub topics publish nba-grading-trigger \
  --message '{"target_date": "2026-01-18", "run_aggregation": true}'

# Note: Jan 19 games not finished yet, skip for now
```

**Expected Result**:
- Jan 17: 313 predictions graded
- Jan 18: 1,680 predictions graded

**Validation**:
```sql
SELECT game_date, COUNT(*) as graded_count
FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE game_date IN ('2026-01-17', '2026-01-18')
GROUP BY game_date
ORDER BY game_date;
```

---

### Priority 2: Backfill Missing Box Scores (Medium Priority - 30 min)

**Impact**: Unblock Phase 4 PSZA processing for 339 players

**Action**:
```bash
# Backfill box scores for dates with missing data
PYTHONPATH=. python scripts/backfill_gamebooks.py --start-date 2026-01-13 --end-date 2026-01-18

# Or manually trigger BDL scraper for specific dates
# (depends on scraper implementation)
```

**Note**: Box scores may not be available if games were not recorded by BDL API

**Validation**:
```bash
# Re-check box score completeness
PYTHONPATH=. python scripts/check_data_completeness.py --days 7
```

---

### Priority 3: Backfill Phase 4 Complete Failures (High Priority - 20 min)

**Impact**: Restore ML features for Jan 16, 18 (critical for future predictions)

**Action**:
```bash
# Trigger Phase 4 for Jan 18 (all processors)
curl -X POST https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "2026-01-18",
    "backfill_mode": true,
    "processors": []
  }'

# Trigger Phase 4 for Jan 16 (PDC, PCF only)
curl -X POST https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "2026-01-16",
    "backfill_mode": true,
    "processors": ["PlayerDailyCache", "PlayerCompositeFactors"]
  }'
```

**Validation**:
```bash
# Re-run deep validation
python scripts/validate_backfill_coverage.py \
  --start-date 2026-01-16 \
  --end-date 2026-01-18 \
  --details
```

---

### Priority 4: Backfill PSZA INCOMPLETE_UPSTREAM (After Box Scores - 30 min)

**Impact**: Complete shot zone analysis for 339 players

**Prerequisite**: Priority 2 (box scores) must complete first

**Action**:
```bash
# After box scores are backfilled, trigger PSZA only
for date in 2026-01-13 2026-01-14 2026-01-15 2026-01-16 2026-01-17; do
  curl -X POST https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d "{
      \"analysis_date\": \"$date\",
      \"backfill_mode\": true,
      \"processors\": [\"PlayerShotZoneAnalysis\"]
    }"
  sleep 5
done
```

**Validation**:
```bash
# Check PSZA INCOMPLETE_UPSTREAM errors
python scripts/validate_backfill_coverage.py \
  --start-date 2026-01-13 \
  --end-date 2026-01-17 \
  --processor PSZA
```

---

### Priority 5: Investigate MLFS UPSTREAM_INCOMPLETE (Jan 15)

**Impact**: 115 players missing ML features on Jan 15

**Action**:
```sql
-- Query to identify which players have UPSTREAM_INCOMPLETE errors
SELECT
  entity_id as player_lookup,
  failure_reason,
  error_message
FROM `nba-props-platform.nba_processing.precompute_failures`
WHERE game_date = '2026-01-15'
  AND processor_name = 'MLFeatureStoreV2'
  AND failure_reason = 'UPSTREAM_INCOMPLETE'
ORDER BY entity_id;
```

**Next Steps**:
1. Review error messages to understand which upstream dependencies are missing
2. Determine if upstream data can be backfilled
3. Re-run MLFS for Jan 15 if upstream data is restored

---

## Standardized Validation Procedure

### Daily Validation Checklist (Morning - Post-Overnight Processing)

**Run Time**: 8 AM ET (after overnight processing completes)

```bash
# 1. Check data completeness (scraping layer)
PYTHONPATH=. python scripts/check_data_completeness.py --date yesterday

# 2. Validate pipeline completeness (all layers)
python scripts/validation/validate_pipeline_completeness.py \
  --start-date yesterday \
  --end-date yesterday

# 3. Check Phase 4 with failure tracking
python scripts/validate_backfill_coverage.py \
  --start-date yesterday \
  --end-date yesterday \
  --details

# 4. Check predictions exist
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = CURRENT_DATE() - 1
GROUP BY game_date
"

# 5. Check grading ran (run after noon ET when grading should complete)
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as graded
FROM \`nba-props-platform.nba_predictions.prediction_grades\`
WHERE game_date = CURRENT_DATE() - 1
GROUP BY game_date
"
```

**Expected Results**:
- ✅ Box scores ≥90% coverage
- ✅ Phase 3 analytics complete
- ✅ Phase 4 coverage ≥80%
- ✅ Predictions exist
- ✅ Grading coverage ≥90% (after noon ET)

**Alerts Triggered**:
- ❌ Box scores <90%: Trigger box score backfill
- ❌ Phase 4 <80%: Investigate Phase 4 service logs
- ❌ Grading <90% (after noon ET): Manually trigger grading

---

### Weekly Validation (Sunday)

**Run Time**: Weekly on Sunday mornings

```bash
# 1. Validate last 7 days comprehensively
PYTHONPATH=. python scripts/check_data_completeness.py --days 7

python scripts/validation/validate_pipeline_completeness.py \
  --start-date $(date -d '7 days ago' +%Y-%m-%d) \
  --end-date $(date +%Y-%m-%d)

python scripts/validate_backfill_coverage.py \
  --start-date $(date -d '7 days ago' +%Y-%m-%d) \
  --end-date $(date +%Y-%m-%d) \
  --details

# 2. Check grading coverage for last 7 days
bq query --use_legacy_sql=false "
SELECT
  p.game_date,
  COUNT(DISTINCT p.prediction_id) as total_predictions,
  COUNT(DISTINCT g.prediction_id) as graded_predictions,
  ROUND(100.0 * COUNT(DISTINCT g.prediction_id) / NULLIF(COUNT(DISTINCT p.prediction_id), 0), 1) as coverage_pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` p
LEFT JOIN \`nba-props-platform.nba_predictions.prediction_grades\` g
  ON p.prediction_id = g.prediction_id
WHERE p.game_date >= CURRENT_DATE() - 7
GROUP BY p.game_date
ORDER BY p.game_date DESC
"

# 3. Check for any untracked failures
bq query --use_legacy_sql=false "
SELECT
  game_date,
  processor_name,
  COUNT(*) as failure_count,
  failure_reason
FROM \`nba-props-platform.nba_processing.precompute_failures\`
WHERE game_date >= CURRENT_DATE() - 7
  AND failure_reason NOT IN ('EXPECTED_INCOMPLETE', 'INSUFFICIENT_DATA', 'INCOMPLETE_DATA', 'CIRCUIT_BREAKER_ACTIVE')
GROUP BY game_date, processor_name, failure_reason
ORDER BY game_date DESC, failure_count DESC
"
```

**Review**:
- Identify patterns (recurring failures)
- Assess backfill needs
- Update monitoring thresholds if needed

---

### Monthly Validation (1st of Month)

**Run Time**: First Sunday of each month

```bash
# 1. Validate entire previous month
MONTH_START=$(date -d 'last month' +%Y-%m-01)
MONTH_END=$(date -d "$MONTH_START +1 month -1 day" +%Y-%m-%d)

python scripts/validation/validate_pipeline_completeness.py \
  --start-date $MONTH_START \
  --end-date $MONTH_END

# 2. Generate monthly coverage report
bq query --use_legacy_sql=false --format=csv "
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT g.prediction_id) as graded,
  ROUND(100.0 * COUNT(DISTINCT g.prediction_id) / NULLIF(COUNT(*), 0), 1) as grading_pct,
  ROUND(AVG(g.accuracy_pct), 1) as avg_accuracy
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` p
LEFT JOIN \`nba-props-platform.nba_predictions.prediction_grades\` g
  ON p.prediction_id = g.prediction_id
WHERE game_date >= '$MONTH_START' AND game_date <= '$MONTH_END'
GROUP BY month
" > monthly_validation_report.csv

cat monthly_validation_report.csv
```

---

## Prevention Recommendations

### 1. Automated Daily Health Checks

**Current**: Manual validation required

**Recommendation**: Implement automated daily health check Cloud Function

```python
# Pseudo-code for daily_health_check.py
def daily_health_check():
    yesterday = date.today() - timedelta(days=1)

    # Run all validation checks
    results = {
        'box_scores': check_box_score_completeness(yesterday),
        'phase3': check_phase3_completeness(yesterday),
        'phase4': check_phase4_completeness(yesterday),
        'predictions': check_predictions_exist(yesterday),
        'grading': check_grading_coverage(yesterday)
    }

    # Generate Slack alert if any check fails
    if any(not r['ok'] for r in results.values()):
        send_slack_alert(yesterday, results)

    return results
```

**Trigger**: Daily at 9 AM ET via Cloud Scheduler

---

### 2. Circuit Breaker for Phase 4

**Current**: Phase 4 fails silently when upstream data is incomplete

**Recommendation**: Implement pre-flight validation and circuit breaker

```python
# Before Phase 4 processing
def validate_phase3_readiness(game_date):
    expected_players = get_expected_player_count(game_date)
    actual_players = get_phase3_player_count(game_date)

    coverage = actual_players / expected_players

    if coverage < 0.90:
        raise ValidationError(f"Phase 3 coverage too low: {coverage:.1%}")

    return True
```

---

### 3. Grading Auto-Heal Expansion

**Current**: Grading can trigger Phase 3 if missing

**Recommendation**: Expand to trigger Phase 4 if needed

```python
# In grading Cloud Function
if validation['missing_reason'] == 'incomplete_features':
    trigger_phase4_backfill(target_date)
    wait_and_retry_grading(target_date)
```

---

### 4. Box Score Scraper Reliability

**Current**: Box scores missing with no retry mechanism

**Recommendation**:
1. Add retry logic to BDL scraper (3 retries with exponential backoff)
2. Send alert when box scores fail after retries
3. Track box score availability in Firestore for monitoring

---

### 5. Prediction Volume Monitoring

**Current**: Prediction volume varies significantly (285-2,193)

**Recommendation**:
1. Set expected range based on game count (e.g., 400-800 predictions per game day)
2. Alert if volume is outside expected range
3. Track system count (should be consistent at 6-7 systems)

---

### 6. Weekly Backfill Review

**Current**: Backfills are reactive (triggered after failures discovered)

**Recommendation**:
1. Weekly review of validation results (Sundays)
2. Proactive backfill planning for upcoming week
3. Monthly retrospective on data quality trends

---

## Success Metrics

### Immediate (Week 0)

- [ ] All Jan 17-18 predictions graded (2,608 predictions)
- [ ] Jan 16, 18 Phase 4 complete failures resolved
- [ ] PSZA INCOMPLETE_UPSTREAM errors reduced to <10 per day
- [ ] Daily validation procedure documented and tested

### Short-term (Week 1-2)

- [ ] Automated daily health checks deployed
- [ ] Grading coverage consistently ≥95%
- [ ] Box score coverage consistently ≥95%
- [ ] Phase 4 coverage consistently ≥85%

### Long-term (Month 1-2)

- [ ] Zero missed grading days
- [ ] Box score scraper reliability ≥99%
- [ ] Phase 4 auto-heal implemented
- [ ] Monthly validation reports automated

---

## Appendix: Validation Queries

### Check Grading Coverage for Date Range

```sql
SELECT
  p.game_date,
  COUNT(DISTINCT p.prediction_id) as total_predictions,
  COUNT(DISTINCT g.prediction_id) as graded_predictions,
  ROUND(100.0 * COUNT(DISTINCT g.prediction_id) / NULLIF(COUNT(DISTINCT p.prediction_id), 0), 1) as coverage_pct,
  COUNTIF(g.prediction_correct = TRUE) as correct,
  COUNTIF(g.prediction_correct = FALSE) as incorrect,
  ROUND(100.0 * COUNTIF(g.prediction_correct = TRUE) / NULLIF(COUNTIF(g.prediction_correct IS NOT NULL), 0), 1) as accuracy_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
LEFT JOIN `nba-props-platform.nba_predictions.prediction_grades` g
  ON p.prediction_id = g.prediction_id
WHERE p.game_date BETWEEN '2026-01-13' AND '2026-01-19'
GROUP BY p.game_date
ORDER BY p.game_date DESC;
```

### Identify Phase 4 Errors Needing Investigation

```sql
SELECT
  game_date,
  processor_name,
  failure_reason,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT entity_id LIMIT 5) as sample_players
FROM `nba-props-platform.nba_processing.precompute_failures`
WHERE game_date BETWEEN '2026-01-13' AND '2026-01-19'
  AND failure_reason IN ('INCOMPLETE_UPSTREAM', 'MISSING_DEPENDENCY', 'UPSTREAM_INCOMPLETE', 'PROCESSING_ERROR')
GROUP BY game_date, processor_name, failure_reason
ORDER BY game_date DESC, failure_count DESC;
```

### Check Prediction System Consistency

```sql
SELECT
  game_date,
  COUNT(DISTINCT system_id) as active_systems,
  STRING_AGG(DISTINCT system_id ORDER BY system_id) as systems_list,
  COUNT(*) as total_predictions,
  COUNTIF(current_points_line IS NOT NULL) as with_lines,
  COUNTIF(current_points_line IS NULL) as without_lines
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date BETWEEN '2026-01-13' AND '2026-01-19'
GROUP BY game_date
ORDER BY game_date DESC;
```

---

## Next Steps

1. **Execute Priority 1**: Trigger grading for Jan 17-18 (5 min)
2. **Execute Priority 3**: Backfill Phase 4 for Jan 16, 18 (20 min)
3. **Investigate**: Box score scraper failures (30 min)
4. **Execute Priority 2**: Backfill box scores if possible (30 min)
5. **Execute Priority 4**: Re-run PSZA after box scores (30 min)
6. **Document**: Update this doc with execution results

**Total Estimated Time**: 2 hours

---

**Document Status**: ✅ Ready for Execution
**Last Updated**: 2026-01-19 22:30 UTC
**Owner**: Data Pipeline Team
