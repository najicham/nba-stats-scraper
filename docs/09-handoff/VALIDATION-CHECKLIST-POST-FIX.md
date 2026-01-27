# Post-Fix Validation Checklist

**Purpose**: Run these checks after fixing the 3 critical issues
**Expected Time**: 15-20 minutes
**Run After**: 6:00 PM PST on Jan 27, 2026

---

## Pre-Validation: Confirm Fixes Deployed

- [ ] Circuit breaker batching code deployed
- [ ] PlayerGameSummaryProcessor fixed for Jan 25
- [ ] Cache processor re-run for Jan 26
- [ ] Usage rate calculation debugged/fixed

---

## Check #1: Circuit Breaker Quota (Target: <100 writes/day)

### A. Check Today's Write Count
```bash
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  COUNT(*) as write_count
FROM \`nba-props-platform.nba_orchestration.circuit_breaker_state\`
WHERE DATE(updated_at) = CURRENT_DATE()
GROUP BY processor_name
ORDER BY write_count DESC"
```

**Expected**:
- PlayerGameSummaryProcessor: <50 writes (down from 743)
- Total writes: <200 (down from 1,248)

**Pass Criteria**: Total writes < 500/day

### B. Check for Quota Errors
```bash
gcloud logging read 'resource.type=bigquery_resource AND protoPayload.status.message:quota' \
  --limit=5 \
  --format='table(timestamp,protoPayload.status.message)' \
  --project=nba-props-platform
```

**Expected**: No errors in last 4 hours

**Pass Criteria**: Zero quota errors since fix deployed

---

## Check #2: Cache for Jan 26 (Target: >100 players)

### A. Verify Cache Exists
```bash
bq query --use_legacy_sql=false "
SELECT
  cache_date,
  COUNT(DISTINCT player_lookup) as players_cached,
  MAX(created_at) as last_update
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date = '2026-01-26'"
```

**Expected**:
- players_cached: >100 (ideally ~150-200)
- last_update: Recent (within last 6 hours)

**Pass Criteria**: players_cached > 100

### B. Compare to Previous Day
```bash
bq query --use_legacy_sql=false "
SELECT
  cache_date,
  COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date IN ('2026-01-25', '2026-01-26')
GROUP BY cache_date
ORDER BY cache_date DESC"
```

**Expected**: Similar player counts (within 20% variance)

**Pass Criteria**: Jan 26 count within 20% of Jan 25

---

## Check #3: Usage Rate Coverage (Target: >90%)

### A. Check Overall Coverage
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  COUNTIF(usage_rate IS NOT NULL) as has_usage_rate,
  COUNTIF(minutes_played > 0) as active_players,
  ROUND(COUNTIF(usage_rate IS NOT NULL) * 100.0 / COUNTIF(minutes_played > 0), 1) as usage_rate_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-01-26'
  AND minutes_played > 0"
```

**Expected**:
- usage_rate_pct: >90% (up from 41.4%)

**Pass Criteria**: usage_rate_pct > 80% (acceptable) or >90% (excellent)

### B. Check Specific Player (jarenjacksonjr)
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  player_lookup,
  minutes_played,
  fg_attempts,
  usage_rate,
  team_abbr
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE player_lookup = 'jarenjacksonjr'
  AND game_date >= '2026-01-24'
ORDER BY game_date DESC"
```

**Expected**: usage_rate NOT NULL for all recent games

**Pass Criteria**: jarenjacksonjr has usage_rate for Jan 26

---

## Check #4: Tonight's Predictions (Jan 27)

### A. Check Predictions Generated
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT game_id) as unique_games,
  MAX(created_at) as last_created
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-27'
  AND is_active = TRUE"
```

**Expected**:
- total_predictions: >100
- unique_games: ~7 (tonight's games)
- last_created: Today

**Pass Criteria**: total_predictions > 50

### B. Check Prediction Quality Distribution
```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN confidence_score >= 0.7 THEN 'High'
    WHEN confidence_score >= 0.5 THEN 'Medium'
    ELSE 'Low'
  END as confidence_tier,
  COUNT(*) as prediction_count
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-27'
  AND is_active = TRUE
GROUP BY confidence_tier
ORDER BY confidence_tier DESC"
```

**Expected**: Reasonable distribution across confidence tiers

**Pass Criteria**: At least some "High" confidence predictions

---

## Check #5: Phase 3 Completion

### A. Check Firestore Status
```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime
db = firestore.Client()
processing_date = "2026-01-27"
doc = db.collection('phase3_completion').document(processing_date).get()
if doc.exists:
    data = doc.to_dict()
    print(f"Phase 3 Status for {processing_date}:")
    completed = sum(1 for v in data.values() if isinstance(v, dict) and v.get('status') == 'success')
    total = len(data)
    print(f"  Completed: {completed}/{total}")
    for processor, status in sorted(data.items()):
        if isinstance(status, dict):
            print(f"    {processor}: {status.get('status', 'unknown')}")
        else:
            print(f"    {processor}: {status}")
else:
    print(f"No Phase 3 completion record for {processing_date}")
EOF
```

**Expected**: All 5 Phase 3 processors marked complete

**Pass Criteria**: At least 4/5 processors complete

---

## Check #6: No New Errors

### A. Check Recent Processor Failures
```bash
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  status,
  data_date,
  started_at
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE DATE(started_at) = CURRENT_DATE()
  AND status = 'failed'
ORDER BY started_at DESC
LIMIT 10"
```

**Expected**: No new failures (or only expected ones)

**Pass Criteria**: <5 failures today

### B. Check Cloud Run Logs for Errors
```bash
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=20 | grep -i "error\|exception\|failed"
```

**Expected**: No critical errors in last hour

**Pass Criteria**: No quota errors, no dependency errors

---

## Final Validation: Run Full Check

```bash
# Run main validation script
python scripts/validate_tonight_data.py

# Should show:
# - ✅ 0 ISSUES (down from 5)
# - ⚠️ Minimal warnings
```

**Pass Criteria**: 0 ISSUES reported

---

## Spot Check Validation

```bash
# Run spot checks for data accuracy
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate

# Expected: ≥95% accuracy
```

**Pass Criteria**: ≥90% accuracy (ideally 95%+)

---

## Summary Checklist

After running all checks above, verify:

- [ ] Circuit breaker writes <500/day (target: <200)
- [ ] No BigQuery quota errors in last 4 hours
- [ ] Cache exists for Jan 26 with >100 players
- [ ] Usage rate coverage >80% for Jan 26
- [ ] jarenjacksonjr has usage_rate for Jan 26
- [ ] Predictions generated for tonight (Jan 27)
- [ ] Phase 3 completion shows 4/5+ processors
- [ ] <5 processor failures today
- [ ] Main validation script shows 0 ISSUES
- [ ] Spot checks ≥90% accuracy

---

## If Checks Fail

### Circuit Breaker Still High
- Check if batching code actually deployed
- Verify batch size is appropriate (10 updates/batch or 5 min)
- Consider emergency Firestore migration

### Cache Still Missing
- Check PlayerGameSummaryProcessor status for Jan 25
- Verify cache processor actually re-ran
- Check dependency logic - should it check same day?

### Usage Rate Still Low
- Check if fix was actually deployed
- Add more logging to debug join
- Verify team_offense_game_summary has correct game_ids

### Predictions Not Generated
- Check if ML feature processor ran
- Verify cache data is available
- Check prediction system logs

---

## Success Criteria Met?

**Minimum (Acceptable)**:
- [x] Circuit breaker <500 writes/day
- [x] Cache for Jan 26 exists
- [x] Usage rate >70%
- [x] Predictions generated

**Target (Excellent)**:
- [x] Circuit breaker <200 writes/day
- [x] Cache for Jan 26 >150 players
- [x] Usage rate >90%
- [x] No validation errors

---

## Report Results

Create summary:
```markdown
# Post-Fix Validation Results - [TIME]

## ✅ Fixes Validated
1. Circuit Breaker: [PASS/FAIL] - [write count]
2. Cache: [PASS/FAIL] - [player count]
3. Usage Rate: [PASS/FAIL] - [coverage %]

## 📊 Metrics
- Total writes: [count] (target: <200)
- Cache players: [count] (target: >100)
- Usage rate: [%] (target: >90%)
- Predictions: [count] (target: >50)

## 🎯 Overall Status: [✅ RESOLVED / ⚠️ PARTIAL / ❌ NEEDS WORK]

[Notes and remaining issues]
```

---

**Validation By**: [Your Name]
**Date**: 2026-01-27 6:00 PM PST
**Result**: [PASS/FAIL]
**Next Steps**: [If failed, what needs fixing]
