# Pipeline Replay Test Plan - 2025-12-31

## Objective

Execute comprehensive end-to-end testing of the pipeline replay system to validate:
1. Dataset isolation works (test_* datasets)
2. Replay produces correct outputs
3. No production data is affected
4. Performance is acceptable
5. System is production-ready

---

## Pre-Test Checklist

### ✅ Prerequisites Verified
- [x] Test datasets created (test_nba_*)
- [x] Replay scripts ready (replay_pipeline.py, validate_replay.py)
- [x] Dataset prefix code committed (5ee366a)
- [ ] Phase 3 deployed with dataset_prefix support
- [ ] Phase 4 deployed with dataset_prefix support
- [ ] Services secured (no public access)

### 🎯 Test Environment Status
- **Phase 3 Analytics:** Deploying (Task: be8e579)
- **Phase 4 Precompute:** Deploying (Task: be8c163)
- **Test Datasets:** Created, 7-day TTL
- **Security:** All 5 services secured

---

## Test Plan Overview

### Phase 1: Deployment Verification (10-15 min)
1. Confirm deployments completed successfully
2. Verify health endpoints respond
3. Test dataset_prefix parameter acceptance
4. Verify IAM policies remain secure

### Phase 2: Test Date Selection (5-10 min)
1. Query production for dates with complete data
2. Check record counts for candidate dates
3. Select date with good coverage (8+ games, 200+ players)
4. Document expected record counts

### Phase 3: Dry Run Test (5 min)
1. Run replay in dry-run mode
2. Verify script executes without errors
3. Check parameter handling
4. Review timing estimates

### Phase 4: Actual Replay Test (15-30 min)
1. Execute Phase 3→4 replay for selected date
2. Monitor progress and timing
3. Capture logs and errors
4. Record performance metrics

### Phase 5: Output Validation (15-20 min)
1. Query test datasets for created records
2. Compare test vs production record counts
3. Validate data quality (no nulls, correct schemas)
4. Check for duplicates
5. Verify no production data was modified

### Phase 6: Security Audit (15-30 min)
1. Pull access logs for last 30 days
2. Identify external IPs accessing services
3. Check for unusual patterns
4. Document findings

### Phase 7: Documentation (10-15 min)
1. Create comprehensive test report
2. Update session summary
3. Create handoff for next session
4. Commit test results

**Total Estimated Time:** 90-140 minutes

---

## Detailed Test Procedures

### Phase 1: Deployment Verification

#### Step 1.1: Check Deployment Status
```bash
# Get deployment task status
cat /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/be8e579.output  # Phase 3
cat /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/be8c163.output  # Phase 4

# Check service status
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format="value(status.url,status.latestReadyRevisionName)"
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 --format="value(status.url,status.latestReadyRevisionName)"
```

**Expected Results:**
- Both deployments show "Deployment succeeded"
- Services have active revisions
- URLs are accessible

#### Step 1.2: Test Health Endpoints
```bash
# Get auth token
TOKEN=$(gcloud auth print-identity-token)

# Test Phase 3
curl -s -H "Authorization: Bearer $TOKEN" \
  https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/health | jq '.'

# Test Phase 4
curl -s -H "Authorization: Bearer $TOKEN" \
  https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/health | jq '.'
```

**Expected Results:**
```json
{
  "service": "analytics",
  "status": "healthy",
  "version": "a51aae7",
  "timestamp": "2025-12-31T..."
}
```

#### Step 1.3: Test Dataset Prefix Parameter
```bash
# Test Phase 3 with dataset_prefix
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2024-12-15", "end_date": "2024-12-15", "processors": [], "dataset_prefix": "test_", "dry_run": true}' \
  https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range | jq '.'

# Test Phase 4 with dataset_prefix
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2024-12-15", "processors": [], "dataset_prefix": "test_", "dry_run": true}' \
  https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date | jq '.'
```

**Expected Results:**
- Services accept dataset_prefix parameter
- Dry run mode works
- No errors returned

#### Step 1.4: Verify Security Still Intact
```bash
# Test without auth - should return 403
curl -s -o /dev/null -w "Phase 3: %{http_code}\n" \
  https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/health

curl -s -o /dev/null -w "Phase 4: %{http_code}\n" \
  https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/health

# Check IAM policies
gcloud run services get-iam-policy nba-phase3-analytics-processors --region=us-west2
gcloud run services get-iam-policy nba-phase4-precompute-processors --region=us-west2
```

**Expected Results:**
- Both return 403 without auth
- IAM policies show only service accounts (no allUsers)

---

### Phase 2: Test Date Selection

#### Step 2.1: Query Production for Recent Game Days
```bash
bq query --use_legacy_sql=false --format=json "
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_id) as players,
  COUNT(*) as boxscore_records
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date >= '2024-12-01'
  AND game_date <= '2024-12-31'
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 30
" > /tmp/available_dates.json

cat /tmp/available_dates.json | jq -r '.[] | "\(.game_date) - \(.games) games, \(.players) players, \(.boxscore_records) records"'
```

**Selection Criteria:**
- 6-12 games (typical NBA day)
- 200+ players
- Recent enough to have complete pipeline data
- Prefer dates around Dec 15-20 (good mix of data)

#### Step 2.2: Verify Complete Pipeline Data
```bash
# For each candidate date, check all phases
TEST_DATE="2024-12-15"  # Replace with selected date

echo "=== Phase 2 (Raw) ==="
bq query --use_legacy_sql=false "
SELECT COUNT(*) as count FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date = '$TEST_DATE'"

echo "=== Phase 3 (Analytics) ==="
bq query --use_legacy_sql=false "
SELECT COUNT(*) as count FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '$TEST_DATE'"

echo "=== Phase 4 (Precompute) ==="
bq query --use_legacy_sql=false "
SELECT COUNT(*) as count FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE analysis_date = '$TEST_DATE'"

echo "=== Phase 5 (Predictions) ==="
bq query --use_legacy_sql=false "
SELECT COUNT(*) as count FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '$TEST_DATE'"
```

**Expected Results:**
- All phases have data for the date
- Record counts are reasonable
- No zero counts (indicates complete pipeline run)

#### Step 2.3: Document Expected Counts
```bash
# Save baseline for comparison
cat > /tmp/baseline_counts.txt <<EOF
Test Date: $TEST_DATE

Production Counts:
- Raw Boxscores: [FROM QUERY]
- Analytics Player Summary: [FROM QUERY]
- Precompute Composite Factors: [FROM QUERY]
- Predictions: [FROM QUERY]

These will be compared against test replay outputs.
EOF
```

---

### Phase 3: Dry Run Test

#### Step 3.1: Run Replay in Dry-Run Mode
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

PYTHONPATH=. python bin/testing/replay_pipeline.py $TEST_DATE \
  --start-phase=3 \
  --dry-run \
  --dataset-prefix=test_ \
  2>&1 | tee /tmp/replay_dry_run.log
```

**Expected Results:**
- Script executes without errors
- Shows what would be executed
- No actual API calls made
- Timing estimates provided

#### Step 3.2: Review Dry Run Output
```bash
cat /tmp/replay_dry_run.log

# Check for:
# - Correct date parsing
# - Correct phase selection
# - Correct dataset prefix
# - No errors or warnings
```

---

### Phase 4: Actual Replay Test

#### Step 4.1: Execute Real Replay
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Record start time
echo "Replay started: $(date '+%Y-%m-%d %H:%M:%S')" > /tmp/replay_run.log

# Run replay with full logging
PYTHONPATH=. python bin/testing/replay_pipeline.py $TEST_DATE \
  --start-phase=3 \
  --dataset-prefix=test_ \
  --output-json=/tmp/replay_report.json \
  2>&1 | tee -a /tmp/replay_run.log

# Record end time
echo "Replay ended: $(date '+%Y-%m-%d %H:%M:%S')" >> /tmp/replay_run.log
```

**Monitor For:**
- Phase 3 completion time (expect 5-15 min)
- Phase 4 completion time (expect 5-15 min)
- Total time (expect 10-30 min)
- Any errors or warnings

#### Step 4.2: Review Replay Results
```bash
# Check exit code
echo "Exit code: $?" >> /tmp/replay_run.log

# Review JSON report
cat /tmp/replay_report.json | jq '.'

# Extract key metrics
cat /tmp/replay_report.json | jq '{
  date: .replay_date,
  success: .overall_success,
  duration: .total_duration_seconds,
  phases: [.phases[] | {phase: .phase, duration: .duration_seconds, records: .records_processed, success: .success}]
}'
```

**Success Criteria:**
- overall_success: true
- No phase errors
- Reasonable timing (< 30 min total)
- Records processed in each phase

---

### Phase 5: Output Validation

#### Step 5.1: Check Test Datasets Have Data
```bash
echo "=== Test Dataset Verification ==="

# Phase 3 Analytics
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT player_id) as unique_players
FROM \`nba-props-platform.test_nba_analytics.player_game_summary\`
WHERE game_date = '$TEST_DATE'"

# Phase 4 Precompute
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  COUNT(DISTINCT player_id) as unique_players
FROM \`nba-props-platform.test_nba_precompute.player_composite_factors\`
WHERE analysis_date = '$TEST_DATE'"

# Check for team analytics too
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records
FROM \`nba-props-platform.test_nba_analytics.team_defense_game_summary\`
WHERE game_date = '$TEST_DATE'"
```

**Expected Results:**
- Test datasets have non-zero records
- Record counts similar to production
- No obvious data quality issues

#### Step 5.2: Compare Test vs Production
```bash
# Side-by-side comparison
echo "=== Production vs Test Comparison ==="

for table in player_game_summary team_defense_game_summary team_offense_game_summary; do
  echo "--- $table ---"

  PROD_COUNT=$(bq query --use_legacy_sql=false --format=csv "
    SELECT COUNT(*) FROM \`nba-props-platform.nba_analytics.$table\`
    WHERE game_date = '$TEST_DATE'" | tail -1)

  TEST_COUNT=$(bq query --use_legacy_sql=false --format=csv "
    SELECT COUNT(*) FROM \`nba-props-platform.test_nba_analytics.$table\`
    WHERE game_date = '$TEST_DATE'" | tail -1)

  echo "Production: $PROD_COUNT"
  echo "Test: $TEST_COUNT"

  if [ "$PROD_COUNT" = "$TEST_COUNT" ]; then
    echo "✅ Match!"
  else
    DIFF=$((TEST_COUNT - PROD_COUNT))
    echo "⚠️  Difference: $DIFF records"
  fi
  echo ""
done
```

#### Step 5.3: Run Validation Script
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

PYTHONPATH=. python bin/testing/validate_replay.py $TEST_DATE --prefix=test_ \
  2>&1 | tee /tmp/validation_results.txt

# Review validation results
cat /tmp/validation_results.txt
```

**Expected Results:**
- All validation checks pass
- No duplicates found
- Record counts meet minimums
- Data quality checks pass

#### Step 5.4: Verify Production Untouched
```bash
# Check that production data wasn't modified
# Compare last modified timestamps

bq show --format=prettyjson nba-props-platform:nba_analytics.player_game_summary | \
  jq '.lastModifiedTime' > /tmp/prod_last_modified.txt

# This should be BEFORE the replay test started
cat /tmp/prod_last_modified.txt
cat /tmp/replay_run.log | grep "Replay started"

# Manual verification needed
echo "Verify production lastModifiedTime is before replay start time"
```

#### Step 5.5: Sample Data Quality Checks
```bash
# Check for nulls in critical fields
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  COUNTIF(player_id IS NULL) as null_player_ids,
  COUNTIF(game_id IS NULL) as null_game_ids,
  COUNTIF(points IS NULL) as null_points
FROM \`nba-props-platform.test_nba_analytics.player_game_summary\`
WHERE game_date = '$TEST_DATE'"

# Check for duplicates
bq query --use_legacy_sql=false "
SELECT
  game_id,
  player_id,
  COUNT(*) as occurrences
FROM \`nba-props-platform.test_nba_analytics.player_game_summary\`
WHERE game_date = '$TEST_DATE'
GROUP BY game_id, player_id
HAVING COUNT(*) > 1
LIMIT 10"

# Expected: No results (no duplicates)
```

---

### Phase 6: Security Audit

#### Step 6.1: Pull Access Logs (30 Days)
```bash
# Get logs for all vulnerable services from Dec 1 onwards
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND (
     resource.labels.service_name="nba-phase4-precompute-processors"
     OR resource.labels.service_name="prediction-coordinator"
     OR resource.labels.service_name="prediction-worker"
     OR resource.labels.service_name="nba-phase1-scrapers"
     OR resource.labels.service_name="nba-admin-dashboard"
   )
   AND httpRequest.remoteIp!~"^10\."
   AND httpRequest.remoteIp!~"^172\.16\."
   AND httpRequest.remoteIp!~"^192\.168\."
   AND timestamp >= "2024-12-01T00:00:00Z"' \
  --limit=5000 \
  --format=json \
  --project=nba-props-platform \
  > /tmp/security_access_logs.json

echo "Total log entries: $(cat /tmp/security_access_logs.json | jq '. | length')"
```

#### Step 6.2: Analyze Unique IPs
```bash
# Extract unique IPs and their access patterns
cat /tmp/security_access_logs.json | jq -r '
  .[] |
  select(.httpRequest != null) |
  "\(.httpRequest.remoteIp) | \(.httpRequest.requestMethod) \(.httpRequest.requestUrl) | \(.httpRequest.status) | \(.timestamp)"
' | sort | uniq -c | sort -rn > /tmp/access_patterns.txt

# Show top 20 IPs
head -20 /tmp/access_patterns.txt
```

**Look For:**
- Google Cloud IPs (expected - internal traffic)
- Unknown external IPs (suspicious)
- Repeated failed attempts (reconnaissance)
- POST requests from unknown sources (potential exploitation)

#### Step 6.3: Check for Suspicious Patterns
```bash
# Look for POST requests (most dangerous)
cat /tmp/security_access_logs.json | jq -r '
  .[] |
  select(.httpRequest.requestMethod == "POST") |
  "\(.timestamp) | \(.httpRequest.remoteIp) | \(.httpRequest.requestUrl) | \(.httpRequest.status)"
' > /tmp/post_requests.txt

echo "Total POST requests from external IPs: $(wc -l < /tmp/post_requests.txt)"
cat /tmp/post_requests.txt

# Look for successful POST requests (200/201/202)
cat /tmp/security_access_logs.json | jq -r '
  .[] |
  select(.httpRequest.requestMethod == "POST" and (.httpRequest.status >= 200 and .httpRequest.status < 300)) |
  "\(.timestamp) | \(.httpRequest.remoteIp) | \(.httpRequest.requestUrl) | \(.httpRequest.status)"
' > /tmp/successful_posts.txt

echo "Successful POST requests: $(wc -l < /tmp/successful_posts.txt)"
cat /tmp/successful_posts.txt
```

#### Step 6.4: Identify Google vs External IPs
```bash
# Separate Google Cloud IPs from truly external ones
cat /tmp/security_access_logs.json | jq -r '
  .[] |
  select(.httpRequest != null) |
  .httpRequest.remoteIp
' | sort -u > /tmp/all_ips.txt

# For each IP, check if it's Google Cloud
while read ip; do
  # Google Cloud IP ranges typically resolve to *.googleusercontent.com or *.googleapis.com
  host $ip 2>/dev/null | grep -q "google" && echo "$ip - GOOGLE" || echo "$ip - EXTERNAL"
done < /tmp/all_ips.txt > /tmp/ip_classification.txt

cat /tmp/ip_classification.txt
```

#### Step 6.5: Timeline Analysis
```bash
# Group access by date to see exposure timeline
cat /tmp/security_access_logs.json | jq -r '
  .[] |
  select(.httpRequest != null) |
  .timestamp | split("T")[0]
' | sort | uniq -c

# Expected: More recent dates have more traffic (services were public longer)
```

---

### Phase 7: Documentation

#### Step 7.1: Create Test Results Document
```bash
# This will be created as a comprehensive markdown file
# Including all test results, metrics, findings
# Template provided in next step
```

#### Step 7.2: Update Session Summary
```bash
# Add test results to session summary
# Include final status of all todos
# Document any issues found
```

#### Step 7.3: Create Final Handoff
```bash
# Create handoff document for next session
# Include:
# - What was completed
# - What issues were found
# - What needs follow-up
# - Recommended next steps
```

---

## Success Criteria

### Minimum Requirements (Must Pass)
- [ ] Both services deployed successfully
- [ ] Health endpoints respond
- [ ] Replay completes without errors
- [ ] Test datasets have data
- [ ] No production data modified
- [ ] No obvious security incidents in logs

### Ideal Outcomes (Should Pass)
- [ ] Test record counts match production ±5%
- [ ] All validation checks pass
- [ ] Total replay time < 30 minutes
- [ ] No external IPs made successful POST requests
- [ ] Dataset prefix isolation confirmed

### Stretch Goals (Nice to Have)
- [ ] Test record counts match production exactly
- [ ] Replay time < 20 minutes
- [ ] Zero external access in logs
- [ ] Ready for Phase 5 integration
- [ ] Automated security checks implemented

---

## Troubleshooting Guide

### Deployment Issues
**Symptom:** Health endpoint returns 500 or doesn't respond
**Solution:**
```bash
# Check logs
gcloud run services logs read nba-phase3-analytics-processors --region=us-west2 --limit=50

# Check revision status
gcloud run revisions list --service=nba-phase3-analytics-processors --region=us-west2
```

### Replay Failures
**Symptom:** Replay script crashes or errors
**Solution:**
```bash
# Check specific error in logs
cat /tmp/replay_run.log | grep -A 5 "ERROR\|Exception"

# Test individual phases manually
# (See deployment verification section for manual curl commands)
```

### Missing Data
**Symptom:** Test datasets are empty after replay
**Solution:**
```bash
# Verify dataset_prefix was actually used
bq ls nba-props-platform:test_nba_analytics

# Check if data went to production instead
bq query --use_legacy_sql=false "
SELECT MAX(TIMESTAMP_MILLIS(CAST(last_modified_time AS INT64))) as last_mod
FROM \`nba-props-platform.nba_analytics.__TABLES__\`"

# This should be BEFORE replay test
```

### Performance Issues
**Symptom:** Replay takes > 45 minutes
**Solution:**
- Check BigQuery slot usage
- Verify no concurrent operations
- Consider running during off-peak hours
- Check service resource limits

---

## Rollback Plan

If critical issues are discovered:

1. **Deployment Issues:**
   ```bash
   # Rollback to previous revision
   PREV_REVISION=$(gcloud run revisions list --service=nba-phase4-precompute-processors --region=us-west2 --format="value(name)" --limit=2 | tail -1)
   gcloud run services update-traffic nba-phase4-precompute-processors --region=us-west2 --to-revisions=$PREV_REVISION=100
   ```

2. **Test Data Contamination:**
   ```bash
   # Delete test datasets and recreate
   for dataset in test_nba_source test_nba_analytics test_nba_predictions test_nba_precompute; do
     bq rm -r -f nba-props-platform:$dataset
   done

   ./bin/testing/setup_test_datasets.sh
   ```

3. **Security Issues Found:**
   - Document immediately
   - Notify via email/slack if available
   - Re-verify IAM policies
   - Consider additional lockdown measures

---

## Next Steps After Testing

### If All Tests Pass
1. Document success
2. Consider adding Phase 5 dataset_prefix
3. Run full end-to-end test (Phases 3→6)
4. Implement automated security checks
5. Set up monitoring for IAM policy changes

### If Tests Fail
1. Document failures in detail
2. Create focused bug fix plan
3. Re-test after fixes
4. Update documentation
5. Consider deferring Phase 5 work

### Follow-up Items
1. Implement pre-deployment security validation
2. Add IAM policy monitoring
3. Create Terraform configs for IAM
4. Set up alerts for public service access
5. Schedule quarterly security audits

---

*Plan Created: 2025-12-31*
*Execution Start: After deployments complete*
*Expected Duration: 90-140 minutes*
*Priority: HIGH - Execute autonomously*
