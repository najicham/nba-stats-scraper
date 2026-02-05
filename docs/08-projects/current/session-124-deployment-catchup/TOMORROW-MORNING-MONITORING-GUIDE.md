# Tomorrow Morning Monitoring Guide (Feb 5, 6-11 AM ET)

**Purpose:** Monitor first production test of Session 123 grading prevention system

**What's Being Tested:**
1. Phase 3 → Grading orchestrator (event-driven trigger)
2. Enhanced grading validation (blocks if coverage <50%)
3. Coverage monitor (auto-regrade if <70%)
4. New prediction validation layers (if deployments completed)

---

## Quick Reference Card

### Expected Timeline (Feb 5)

| Time (ET) | Event | What to Check |
|-----------|-------|---------------|
| ~6-10 AM | Phase 3 analytics completes | Firestore phase3_completion |
| ~6-10 AM | phase3-to-grading triggers | Cloud Function logs |
| ~6-15 AM | Grading runs | BigQuery prediction_accuracy |
| ~6-20 AM | Coverage monitor checks | Cloud Function logs |

### Success Looks Like

✅ **Phase 3 completion:** 5/5 processors in Firestore
✅ **Orchestrator trigger:** Logs show "Coverage check passed: X%"
✅ **Grading coverage:** ≥80% (850-960 predictions for 8 games)
✅ **Monitor:** No alerts, or INFO-level success message
✅ **Validation:** No false positives blocking good data

### Failure Looks Like

❌ **Auth error:** 401 Unauthorized in phase3-to-grading logs
❌ **Coverage too low:** Orchestrator logs "Coverage check failed: X%"
❌ **Grading blocked:** "BLOCKING grading due to insufficient coverage"
❌ **Monitor alert:** "Coverage <70%, triggering regrade"
❌ **Validation blocking:** Legitimate data marked as invalid

---

## Monitoring Commands

### 1. Check Phase 3 Completion (Baseline)

```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime

db = firestore.Client(project='nba-props-platform')
processing_date = datetime.now().strftime('%Y-%m-%d')

doc = db.collection('phase3_completion').document(processing_date).get()

if doc.exists:
    data = doc.to_dict()
    completed = [k for k in data.keys() if not k.startswith('_')]
    triggered = data.get('_triggered', False)
    trigger_reason = data.get('_trigger_reason', 'N/A')

    print(f"Phase 3 Status for {processing_date}:")
    print(f"  Processors complete: {len(completed)}/5")
    print(f"  Phase 4 triggered: {triggered}")
    print(f"  Trigger reason: {trigger_reason}")
    print(f"\nCompleted processors:")
    for proc in completed:
        print(f"    - {proc}")

    if len(completed) < 5:
        print(f"\n  ⚠️  WARNING: Only {len(completed)}/5 processors complete")
    elif not triggered:
        print(f"\n  ⚠️  WARNING: Phase 4 not triggered yet")
    else:
        print(f"\n  ✅ Phase 3 complete and Phase 4 triggered")
else:
    print(f"❌ No Phase 3 completion record for {processing_date}")
EOF
```

**Expected:** 5/5 processors, triggered = True

---

### 2. Check Phase3-to-Grading Orchestrator

```bash
# Check if orchestrator triggered
gcloud logging read 'resource.labels.service_name="phase3-to-grading"
  AND timestamp>="2026-02-05T13:00:00Z"' \
  --limit=20 \
  --format="table(timestamp,severity,textPayload)" \
  --project=nba-props-platform

# Look for these patterns:
# ✅ "Coverage check passed: X%" (X >= 80)
# ✅ "Triggering grading for 2026-02-04"
# ❌ "Coverage check failed: X%" (X < 80)
# ❌ "401 Unauthorized" (auth still broken)
```

**Expected:** "Coverage check passed" and "Triggering grading" messages

---

### 3. Check Grading Execution

```bash
# Check grading function logs
gcloud logging read 'resource.labels.service_name="grading"
  AND timestamp>="2026-02-05T13:00:00Z"' \
  --limit=30 \
  --format="table(timestamp,severity,textPayload)" \
  --project=nba-props-platform

# Look for these patterns:
# ✅ "Starting grading for date: 2026-02-04"
# ✅ "Grading complete: X predictions graded"
# ⚠️  "BLOCKING grading due to insufficient coverage"
# ❌ "ERROR" or "FAILED" messages
```

**Expected:** "Starting grading" followed by "Grading complete: ~850-960 predictions"

---

### 4. Check Grading Coverage

```bash
# Query actual grading results
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_graded,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT system_id) as systems,
  COUNTIF(prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate_pct
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-04'
"

# Expected results:
# total_graded: 850-960 (for 8 games)
# unique_players: 100-120
# systems: 8
# hit_rate_pct: 50-70% (varies by day, not a pass/fail metric)
```

**Alert Thresholds:**
- total_graded < 500: 🔴 CRITICAL - Major coverage issue
- total_graded 500-700: 🟡 WARNING - Partial coverage
- total_graded 700+: ✅ OK

---

### 5. Check Coverage Monitor

```bash
# Check if coverage monitor ran
gcloud logging read 'resource.labels.service_name="grading-coverage-monitor"
  AND timestamp>="2026-02-05T13:00:00Z"' \
  --limit=20 \
  --format="table(timestamp,severity,textPayload)" \
  --project=nba-props-platform

# Look for these patterns:
# ✅ "Grading coverage: X% (Y/Z gradable)" (X >= 70)
# ⚠️  "Coverage below threshold: X%, triggering regrade"
# 🔴 "Max regrade attempts exceeded"
```

**Expected:**
- Coverage ≥70%, no regrade triggered
- OR: Coverage <70%, regrade triggered (1st attempt)

---

### 6. Check Prediction Validation (If Deployed Tonight)

```bash
# Check if validation layers are working
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND (textPayload=~"validation" OR textPayload=~"BLOCKED" OR textPayload=~"DNP")' \
  --limit=30 \
  --freshness=12h \
  --format="table(timestamp,severity,textPayload)" \
  --project=nba-props-platform

# Look for these patterns:
# ✅ "Pre-write validation passed: X records"
# ℹ️  "BLOCKED: usage_rate > 50%" (validation working correctly)
# ℹ️  "DNP filter removed X records" (filter working)
# ❌ "Validation failed: <legitimate data>" (false positive)
```

**Expected:** Validation functioning, blocking only truly invalid data

---

## Triage Decision Tree

### Scenario 1: Auth Error Still Present

**Symptoms:**
- phase3-to-grading logs show "401 Unauthorized"
- Grading didn't run automatically

**Root Cause:** IAM binding didn't apply or was misconfigured

**Action:**
```bash
# Re-apply IAM binding
gcloud run services add-iam-policy-binding grading \
  --region=us-west2 \
  --member="serviceAccount:756957797294-compute@developer.gserviceaccount.com" \
  --role="roles/run.invoker"

# Manually trigger grading
curl -X POST "https://grading-f7p3g7f6ya-wl.a.run.app/grade" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"game_date": "2026-02-04"}'
```

**Escalation:** If manual trigger also fails, spawn Opus agent to investigate IAM setup

---

### Scenario 2: Coverage Too Low (<80%)

**Symptoms:**
- phase3-to-grading logs show "Coverage check failed: 45%"
- Orchestrator didn't trigger grading

**Root Cause:** Phase 3 incomplete or box scores missing

**Action:**
```bash
# Check which processors completed
# (Use Command #1 above)

# Check box score coverage
bq query "SELECT COUNT(DISTINCT player_lookup) as players, COUNT(*) as records
FROM nba_analytics.player_game_summary WHERE game_date = '2026-02-04'"

# If Phase 3 incomplete: Wait 30 min and check again
# If Phase 3 complete but low players: Check scraper logs

# Manual trigger if needed (bypasses coverage check)
curl -X POST "https://phase3-to-grading-f7p3g7f6ya-wl.a.run.app/manual_trigger?date=2026-02-04" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

**Escalation:** If Phase 3 is 5/5 complete but coverage still low, investigate box score scraper

---

### Scenario 3: Grading Blocked by Validation

**Symptoms:**
- Grading function logs show "BLOCKING grading due to insufficient coverage"
- This is the NEW validation from Session 123

**Root Cause:** Enhanced validation detected <50% coverage

**Action:**
```bash
# Check actual coverage vs threshold
bq query "
WITH predictions AS (
  SELECT COUNT(*) as pred_count FROM nba_predictions.player_prop_predictions
  WHERE game_date = '2026-02-04' AND is_active = TRUE
),
actuals AS (
  SELECT COUNT(*) as actual_count FROM nba_analytics.player_game_summary
  WHERE game_date = '2026-02-04'
)
SELECT pred_count, actual_count,
  ROUND(100.0 * actual_count / pred_count, 1) as coverage_pct
FROM predictions, actuals
"

# If coverage truly <50%: Validation working correctly, wait for more data
# If coverage >50%: Validation bug, needs investigation
```

**Escalation:** If validation blocking incorrectly (coverage >50%), spawn Opus agent to debug validation logic

---

### Scenario 4: Coverage Monitor Triggered Regrade

**Symptoms:**
- Coverage monitor logs show "Coverage <70%, triggering regrade"
- Firestore shows regrade attempt #1

**Root Cause:** Grading ran but with insufficient coverage

**Action:**
```bash
# Check regrade attempts
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
doc = db.collection('grading_regrade_attempts').document('2026-02-04').get()
if doc.exists:
    data = doc.to_dict()
    print(f"Regrade attempts: {data.get('attempts', 0)}")
    print(f"Last attempt: {data.get('last_attempt')}")
    print(f"Reasons: {data.get('reasons', [])}")
else:
    print("No regrade attempts yet")
EOF

# Wait 30-60 minutes for regrade to complete
# Then check grading coverage again (Command #4)
```

**Expected:** 1 regrade attempt, coverage improves to >70%

**Escalation:** If regrade attempts ≥2, monitor will alert. Investigate why coverage persistently low.

---

### Scenario 5: Validation False Positives

**Symptoms:**
- Prediction-worker logs show legitimate data being blocked
- Example: "BLOCKED: usage_rate 35%" when 35% is valid

**Root Cause:** Validation thresholds too strict

**Action:**
```bash
# Get sample of blocked records
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"BLOCKED"' --limit=10 --freshness=12h

# Review if blocking is justified
# If false positives: Document cases and update validation rules

# Quick fix: Temporarily adjust thresholds in next deployment
```

**Escalation:** Spawn Opus agent to review validation logic and suggest threshold adjustments

---

## Success Criteria Checklist

Use this checklist at ~11 AM ET:

### Phase 3 Completion
- [ ] All 5 processors completed
- [ ] Phase 4 triggered
- [ ] Completion time reasonable (not delayed >2 hours)

### Orchestration Flow
- [ ] phase3-to-grading triggered automatically (not manual)
- [ ] Coverage check passed (≥80%)
- [ ] Grading function invoked successfully
- [ ] No auth errors

### Grading Results
- [ ] 700+ predictions graded (for 8 games)
- [ ] 8 systems represented
- [ ] Coverage ≥80% (graded / gradable)

### Coverage Monitoring
- [ ] Coverage monitor executed
- [ ] Coverage ≥70% (no regrade needed)
- [ ] OR: Coverage <70%, regrade triggered successfully
- [ ] No critical alerts

### Validation (If Deployed)
- [ ] Pre-write validation executed
- [ ] No false positives blocking good data
- [ ] Blocked records have clear justification in logs

---

## If Everything Passes ✅

**Document success:**

1. Capture final metrics:
   ```bash
   # Grading coverage
   bq query "SELECT COUNT(*) as graded FROM nba_predictions.prediction_accuracy WHERE game_date = '2026-02-04'"

   # Orchestrator timing
   gcloud logging read 'resource.labels.service_name="phase3-to-grading"' --limit=5
   ```

2. Update Session 124 document with success metrics

3. Update Session 123 handoff with first production results

4. Move to Task #5: Comprehensive validation (afternoon)

---

## If Anything Fails ❌

**Escalation procedure:**

1. **Capture error state:**
   ```bash
   # Save all relevant logs
   mkdir -p /tmp/grading-test-failure-$(date +%Y%m%d)

   gcloud logging read 'resource.labels.service_name="phase3-to-grading"' \
     --limit=50 > /tmp/grading-test-failure-$(date +%Y%m%d)/orchestrator.log

   gcloud logging read 'resource.labels.service_name="grading"' \
     --limit=50 > /tmp/grading-test-failure-$(date +%Y%m%d)/grading.log

   gcloud logging read 'resource.labels.service_name="grading-coverage-monitor"' \
     --limit=50 > /tmp/grading-test-failure-$(date +%Y%m%d)/monitor.log
   ```

2. **Spawn Opus agent for investigation:**
   - Provide error logs
   - Ask for root cause analysis
   - Request rollback recommendation

3. **Execute rollback if needed** (see SESSION-124-DEPLOYMENT-PLAN.md)

4. **Document incident:**
   - Create `/docs/09-handoff/2026-02-05-GRADING-TEST-FAILURE.md`
   - Include error logs, root cause, rollback steps
   - Propose fixes for next attempt

---

## Key Phone Numbers / Contacts

**Slack Channels:**
- `#daily-orchestration` - Normal grading alerts
- `#app-error-alerts` - Critical errors
- `#nba-alerts` - Warning-level issues

**Alert Webhooks:**
- Primary: `SLACK_WEBHOOK_URL` (daily orchestration)
- Critical: `SLACK_WEBHOOK_URL_ERROR` (app errors)
- Warnings: `SLACK_WEBHOOK_URL_WARNING` (alerts)

---

## Quick Command Reference

```bash
# One-liner health check
echo "Phase 3: $(python3 -c 'from google.cloud import firestore; import datetime; db=firestore.Client(); doc=db.collection("phase3_completion").document(datetime.datetime.now().strftime("%Y-%m-%d")).get(); print(f"{len([k for k in doc.to_dict().keys() if not k.startswith(\"_\")])}/5" if doc.exists else "Not found")')"; \
echo "Grading: $(bq query --use_legacy_sql=false --format=csv 'SELECT COUNT(*) FROM nba_predictions.prediction_accuracy WHERE game_date = "2026-02-04"' 2>/dev/null | tail -1) predictions"

# Re-run grading manually (if needed)
curl -X POST "https://grading-f7p3g7f6ya-wl.a.run.app/grade" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"game_date": "2026-02-04"}'

# Check deployment status
./bin/whats-deployed.sh
```

---

**Remember:** This is the FIRST production test. Some hiccups are expected. Document everything for learning.

**Good luck!** 🍀
