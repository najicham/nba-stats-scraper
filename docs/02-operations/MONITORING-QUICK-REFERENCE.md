# Monitoring Quick Reference - Robustness Fixes

**Last Updated**: January 20, 2026
**Purpose**: Quick commands for monitoring the 3 deployed robustness fixes

---

## 🔍 QUICK HEALTH CHECKS

### **All Services Status** (30 seconds)

```bash
# Check all 3 deployed services
echo "=== FIX #1: BDL SCRAPER ===" && \
gcloud run services describe nba-scrapers --region=us-west1 --format="value(status.conditions.status)" && \
echo "" && \
echo "=== FIX #2: PHASE 3→4 GATE ===" && \
gcloud functions describe phase3-to-phase4 --gen2 --region=us-west1 --format="value(state)" && \
echo "" && \
echo "=== FIX #3: PHASE 4→5 CIRCUIT BREAKER ===" && \
gcloud functions describe phase4-to-phase5 --gen2 --region=us-west1 --format="value(state)"
```

**Expected Output**: All should show `True` or `ACTIVE`

---

## 📊 CHECK RECENT ACTIVITY

### **BDL Scraper Logs** (Check for retry behavior)

```bash
# Last 20 log entries
gcloud run services logs read nba-scrapers --region=us-west1 --limit=20

# Look for retry patterns
gcloud run services logs read nba-scrapers --region=us-west1 --limit=50 | grep -i "retry\|attempt"

# Check for errors
gcloud run services logs read nba-scrapers --region=us-west1 --limit=50 | grep -i "error\|fail"
```

**What to Look For**:
- ✅ Retry attempts on transient failures
- ✅ Success after retries
- ❌ Repeated failures (investigate)

---

### **Phase 3→4 Gate Logs** (Check for blocks)

```bash
# Last 20 invocations
gcloud functions logs read phase3-to-phase4 --gen2 --region=us-west1 --limit=20

# Look for gate blocks (CRITICAL)
gcloud functions logs read phase3-to-phase4 --gen2 --region=us-west1 --limit=100 | grep -i "block\|missing\|incomplete"

# Check for successful triggers
gcloud functions logs read phase3-to-phase4 --gen2 --region=us-west1 --limit=100 | grep -i "trigger.*phase.*4\|all.*complete"
```

**What to Look For**:
- ✅ Successful Phase 4 triggers when data complete
- ⚠️ Gate blocks when data incomplete (with Slack alert)
- ✅ Data freshness validations passing
- ❌ Repeated blocks (investigate upstream Phase 3)

---

### **Phase 4→5 Circuit Breaker Logs** (Check for blocks)

```bash
# Last 20 invocations
gcloud functions logs read phase4-to-phase5 --gen2 --region=us-west1 --limit=20

# Look for circuit breaker trips
gcloud functions logs read phase4-to-phase5 --gen2 --region=us-west1 --limit=100 | grep -i "circuit.*breaker\|insufficient\|block"

# Check quality thresholds
gcloud functions logs read phase4-to-phase5 --gen2 --region=us-west1 --limit=100 | grep -i "quality\|threshold\|processors.*complete"
```

**What to Look For**:
- ✅ Predictions triggered when quality threshold met
- ⚠️ Circuit breaker trips when <3/5 processors (with Slack alert)
- ✅ Critical processors (PDC, MLFS) present
- ❌ Repeated trips (investigate Phase 4 processors)

---

## 🎯 VALIDATION COMMANDS

### **Smoke Test Recent Dates** (10 seconds)

```bash
# Test last 10 days
python scripts/smoke_test.py $(date -d '10 days ago' +%Y-%m-%d) $(date +%Y-%m-%d)

# Test specific date
python scripts/smoke_test.py 2026-01-15 --verbose

# Test date range
python scripts/smoke_test.py 2026-01-01 2026-01-10
```

**Interpretation**:
- **≥70% pass rate**: Good health
- **50-69% pass rate**: Some issues (investigate specific failures)
- **<50% pass rate**: Systemic problem (check logs immediately)

---

### **Check Phase Completion in Firestore**

```bash
# Check Phase 3 completion for a date
gcloud firestore documents get \
  --collection=phase3_completion \
  --document=2026-01-15

# Check Phase 4 completion for a date
gcloud firestore documents get \
  --collection=phase4_completion \
  --document=2026-01-15
```

**Look For**:
- `_triggered: true` = Phase completed and next phase triggered
- `_completed_count` = Number of processors complete
- Processor timestamps and statuses

---

## 🚨 ALERT INVESTIGATION

### **If You Get a "BLOCKED" Slack Alert**

**Phase 3→4 Gate Blocked**:
```bash
# 1. Check which tables are missing
gcloud functions logs read phase3-to-phase4 --gen2 --region=us-west1 --limit=50 | grep "Missing tables"

# 2. Check Phase 3 processor logs
# (Depends on which processor failed - see Slack alert details)

# 3. Validate data in BigQuery
bq query "SELECT table_name, COUNT(*) as cnt
FROM \`nba-props-platform.nba_analytics.INFORMATION_SCHEMA.TABLES\`
WHERE table_name IN ('player_game_summary', 'team_defense_game_summary',
                     'team_offense_game_summary', 'upcoming_player_game_context',
                     'upcoming_team_game_context')
GROUP BY table_name"

# 4. Check specific date data
DATE="2026-01-15"
bq query "SELECT COUNT(*) FROM \`nba-props-platform.nba_analytics.player_game_summary\` WHERE game_date = '$DATE'"
```

**Phase 4→5 Circuit Breaker Tripped**:
```bash
# 1. Check which processors completed
gcloud functions logs read phase4-to-phase5 --gen2 --region=us-west1 --limit=50 | grep "processors.*complete\|missing"

# 2. Validate critical processors
DATE="2026-01-15"
bq query "SELECT 'PDC' as processor, COUNT(*) as cnt FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date = '$DATE'
UNION ALL
SELECT 'MLFS', COUNT(*) FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` WHERE game_date = '$DATE'"

# 3. Check Phase 4 processor logs
# (Check individual processor Cloud Run services)
```

---

## 📈 METRICS TO TRACK

### **Weekly Metrics** (Track for 4 weeks)

| Metric | Baseline (Before) | Target (After) | How to Measure |
|--------|-------------------|----------------|----------------|
| New Issues/Week | 3-5 | 1-2 | Count Slack alerts, incident tickets |
| Gate Blocks/Week | N/A | 0-2 | Count "BLOCKED" Slack alerts |
| Firefighting Hours/Week | 10-15 | 3-5 | Time logs, calendar review |
| Backfill Time/10 dates | 1-2 hours | <1 minute | `time python scripts/smoke_test.py ...` |
| Average Health Score | 70-80% | 85-95% | Run smoke test, calculate avg |

### **Daily Quick Check** (2 minutes every morning)

```bash
# 1. Run smoke test on yesterday
YESTERDAY=$(date -d 'yesterday' +%Y-%m-%d)
python scripts/smoke_test.py $YESTERDAY --verbose

# 2. Check for any gate blocks in last 24 hours
gcloud functions logs read phase3-to-phase4 --gen2 --region=us-west1 --limit=100 | grep "BLOCK" | tail -5
gcloud functions logs read phase4-to-phase5 --gen2 --region=us-west1 --limit=100 | grep "circuit breaker" | tail -5

# 3. Check Slack for alerts
# (Manual check in #alerts channel)
```

---

## 🔧 TROUBLESHOOTING

### **BDL Scraper Not Retrying**

**Symptoms**: Box score gaps despite transient API failures

**Check**:
```bash
# Verify retry decorator is active
curl https://nba-scrapers-756957797294.us-west1.run.app/health

# Check for retry attempts in logs
gcloud run services logs read nba-scrapers --region=us-west1 --limit=100 | grep -A 5 -B 5 "retry\|attempt"

# Test scraper endpoint
curl -X POST "https://nba-scrapers-756957797294.us-west1.run.app/scrapers/bdl_box_scores" \
  -H "Content-Type: application/json" \
  -d '{"date": "2026-01-15"}'
```

**Fix**: Redeploy if retry logic not working
```bash
cd /path/to/project
./bin/deploy_robustness_fixes.sh  # Now includes all fixes
```

---

### **Phase 3→4 Gate Not Blocking**

**Symptoms**: Phase 4 runs even when Phase 3 incomplete

**Check**:
```bash
# Verify function is active
gcloud functions describe phase3-to-phase4 --gen2 --region=us-west1

# Check recent invocations
gcloud functions logs read phase3-to-phase4 --gen2 --region=us-west1 --limit=20

# Test data freshness check manually (in Python)
python -c "
from orchestration.cloud_functions.phase3_to_phase4.main import verify_phase3_data_ready
is_ready, missing, counts = verify_phase3_data_ready('2026-01-15')
print(f'Ready: {is_ready}')
print(f'Missing: {missing}')
print(f'Counts: {counts}')
"
```

---

### **Phase 4→5 Circuit Breaker Not Tripping**

**Symptoms**: Predictions run with incomplete Phase 4 data

**Check**:
```bash
# Verify function is active
gcloud functions describe phase4-to-phase5 --gen2 --region=us-west1

# Check recent invocations
gcloud functions logs read phase4-to-phase5 --gen2 --region=us-west1 --limit=20

# Check circuit breaker logic
python -c "
from orchestration.cloud_functions.phase4_to_phase5.main import verify_phase4_data_ready
is_ready, missing, counts = verify_phase4_data_ready('2026-01-15')
print(f'Ready: {is_ready}')
print(f'Missing: {missing}')
print(f'Counts: {counts}')
"
```

---

## 📞 ESCALATION

### **When to Investigate Immediately**

🚨 **CRITICAL** (Investigate within 1 hour):
- Circuit breaker tripping repeatedly (>3 times/day)
- Gate blocking for 2+ consecutive days
- BDL scraper failing with no retries
- Health scores dropping below 50%

⚠️ **WARNING** (Investigate within 24 hours):
- Gate blocking occasionally (1-2 times/week)
- Circuit breaker tripping occasionally
- Health scores 50-70%
- Increased alert volume

✅ **NORMAL** (Monitor, no immediate action):
- Occasional gate blocks (data caught up quickly)
- Rare circuit breaker trips (transient issues)
- Health scores 70%+
- Few alerts per week

---

## 🎯 SUCCESS INDICATORS

**Week 1 After Deployment**:
- ✅ All 3 services ACTIVE
- ✅ No repeated gate blocks
- ✅ Health scores stable or improving
- ✅ Reduced issue count

**Month 1 After Deployment**:
- ✅ 70% reduction in new issues
- ✅ 7-11 hours/week time savings
- ✅ Average health scores 80%+
- ✅ Proactive blocking alerts only

---

## 📚 RELATED DOCS

- `docs/09-handoff/2026-01-20-DEPLOYMENT-SUCCESS-FINAL.md` - Deployment summary
- `docs/08-projects/.../ROBUSTNESS-FIXES-IMPLEMENTATION-JAN-20.md` - Implementation details
- `docs/02-operations/BACKFILL-SUCCESS-CRITERIA.md` - Success thresholds
- `docs/02-operations/HISTORICAL-VALIDATION-STRATEGY.md` - Validation approach

---

**Created**: 2026-01-20 18:15 UTC
**Maintained By**: Engineering Team
**Update Frequency**: As needed when thresholds change

---

**Quick Links**:
- [Cloud Console - Cloud Run](https://console.cloud.google.com/run?project=nba-props-platform)
- [Cloud Console - Cloud Functions](https://console.cloud.google.com/functions/list?project=nba-props-platform)
- [Cloud Console - Logs](https://console.cloud.google.com/logs?project=nba-props-platform)
