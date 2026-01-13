# Backfill Improvements Deployment Runbook
**Created:** 2026-01-13 (Overnight Session 30)
**Status:** Ready for deployment
**Estimated Duration:** 2-3 hours

---

## 📋 Pre-Deployment Checklist

### Code Review ✅
- [ ] All changes reviewed by team
- [ ] Security review completed (if required)
- [ ] PR approved and merged to main

### Testing ✅
- [x] All unit tests passing (21/21)
- [ ] Integration test completed on historical date
- [ ] Staging deployment successful

### Documentation ✅
- [x] Implementation summary complete
- [x] Quick reference guide created
- [x] Integration test guide created
- [x] Deployment runbook (this doc) created

### Permissions & Access ✅
- [ ] BigQuery dataEditor role confirmed
- [ ] Cloud Function deployment permissions confirmed
- [ ] Production database access confirmed

---

## 🚀 Deployment Steps

### Phase 1: Code Deployment (30 min)

#### Step 1.1: Final Code Review
```bash
# Verify all changes are committed
git status

# Review what's being deployed
git diff main HEAD

# Ensure all tests pass
pytest tests/test_p0_improvements.py -v
```

**Expected:** Clean working directory, all tests passing

#### Step 1.2: Merge to Main
```bash
# Create PR (if not already done)
gh pr create --title "feat(backfill): Add P0+P1 safeguards - prevent partial backfill incidents" \
  --body "$(cat docs/08-projects/current/historical-backfill-audit/PR-DESCRIPTION.md)"

# OR merge locally (if PR already approved)
git checkout main
git pull origin main
git merge your-branch-name
git push origin main
```

**Expected:** Clean merge, no conflicts

#### Step 1.3: Verify Deployment
```bash
# On production server/environment, pull latest code
git pull origin main

# Verify code is present
grep -A5 "_validate_coverage" backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py

# Verify syntax
python -m py_compile backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py
python -m py_compile data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
```

**Expected:** Code present, no syntax errors

---

### Phase 2: Data Cleanup (15-30 min)

#### Step 2.1: Backup Current State
```bash
# Create backup of UPCG table
bq mk --table \
  nba-props-platform:nba_analytics.upcoming_player_game_context_backup_$(date +%Y%m%d) \
  nba-props-platform:nba_analytics.upcoming_player_game_context
```

**Expected:** Backup table created successfully

#### Step 2.2: Preview Cleanup
```bash
# See what will be deleted
python scripts/cleanup_stale_upcoming_tables.py --dry-run
```

**Expected:** List of stale records (likely hundreds to thousands)

#### Step 2.3: Execute Cleanup
```bash
# Run cleanup (will prompt for confirmation)
python scripts/cleanup_stale_upcoming_tables.py
```

**When Prompted:**
- Review the count of records to be deleted
- Type 'yes' to confirm
- Wait for completion

**Expected:**
- Backup created
- Stale records deleted
- Verification passed
- Summary logged

#### Step 2.4: Verify Cleanup
```sql
-- Should return 0 rows (no stale data)
SELECT COUNT(*) as stale_records
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY;
```

**Expected:** 0 stale records

---

### Phase 3: Cloud Function Deployment (30-45 min) [OPTIONAL]

#### Step 3.1: Create Pub/Sub Topic
```bash
gcloud pubsub topics create upcoming-tables-cleanup-trigger \
  --project=nba-props-platform
```

**Expected:** Topic created or already exists message

#### Step 3.2: Deploy Cloud Function
```bash
cd orchestration/cloud_functions/upcoming_tables_cleanup

gcloud functions deploy upcoming-tables-cleanup \
  --gen2 \
  --runtime=python311 \
  --region=us-east1 \
  --source=. \
  --entry-point=cleanup_upcoming_tables \
  --trigger-topic=upcoming-tables-cleanup-trigger \
  --timeout=540s \
  --memory=512MB \
  --service-account=nba-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --set-env-vars=GCP_PROJECT_ID=nba-props-platform

cd ../../..
```

**Expected:** Function deployed successfully

#### Step 3.3: Create Cloud Scheduler Job
```bash
gcloud scheduler jobs create pubsub upcoming-tables-cleanup-schedule \
  --location=us-east1 \
  --schedule="0 4 * * *" \
  --time-zone="America/New_York" \
  --topic=upcoming-tables-cleanup-trigger \
  --message-body='{"trigger":"scheduled"}' \
  --description="Daily TTL cleanup for upcoming_* tables (4 AM ET)"
```

**Expected:** Scheduler job created

#### Step 3.4: Grant Permissions
```bash
# Get project number
PROJECT_NUMBER=$(gcloud projects describe nba-props-platform --format="value(projectNumber)")

# Allow Cloud Scheduler to publish
gcloud pubsub topics add-iam-policy-binding upcoming-tables-cleanup-trigger \
  --member=serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com \
  --role=roles/pubsub.publisher

# Allow Cloud Function to access BigQuery
gcloud projects add-iam-policy-binding nba-props-platform \
  --member=serviceAccount:nba-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/bigquery.dataEditor
```

**Expected:** Permissions granted

#### Step 3.5: Test Cloud Function
```bash
# Manual trigger
gcloud scheduler jobs run upcoming-tables-cleanup-schedule --location=us-east1

# Wait 1-2 minutes, then check logs
gcloud functions logs read upcoming-tables-cleanup --region=us-east1 --limit=50
```

**Expected:** Function runs successfully, logs show cleanup activity

---

### Phase 4: Integration Testing (30-45 min)

#### Step 4.1: Test Normal Operation
```bash
# Run backfill on a recent date
PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2023-02-25 --end-date 2023-02-25 --parallel
```

**Check Logs For:**
- ✅ Pre-flight coverage check runs
- ✅ Defensive logging shows UPCG vs PGS comparison
- ✅ Coverage validation passes at 100%
- ✅ Checkpoint marked successful

**Expected:** All improvements visible, 100% coverage

#### Step 4.2: Test With Historical Date
```bash
# Run on date that previously had issues
PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2023-02-23 --end-date 2023-02-23 --parallel
```

**Check Logs For:**
- ✅ Pre-flight check shows no stale UPCG (cleaned in Phase 2)
- ✅ Fallback triggers if needed
- ✅ Coverage validation passes
- ✅ All 187 players processed

**Expected:** 100% coverage achieved

#### Step 4.3: Verify Results
```sql
-- Check coverage for test dates
SELECT
  pgs.game_date,
  COUNT(DISTINCT pgs.player_lookup) as expected,
  COUNT(DISTINCT pcf.player_lookup) as actual,
  ROUND(COUNT(DISTINCT pcf.player_lookup) / COUNT(DISTINCT pgs.player_lookup) * 100, 1) as coverage_pct
FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
  ON pgs.game_date = pcf.analysis_date AND pgs.player_lookup = pcf.player_lookup
WHERE pgs.game_date IN ('2023-02-23', '2023-02-25')
GROUP BY pgs.game_date
ORDER BY pgs.game_date;
```

**Expected:** 100% coverage for both dates

---

### Phase 5: Monitoring Setup (15-30 min)

#### Step 5.1: Set Up Dashboard Queries
```sql
-- Save as "Backfill Coverage Monitor" in BigQuery
SELECT
  analysis_date,
  expected_players,
  actual_players,
  coverage_pct,
  status
FROM `nba-props-platform.nba_orchestration.backfill_processing_metadata`
WHERE analysis_date >= CURRENT_DATE() - INTERVAL 30 DAY
ORDER BY analysis_date DESC;
```

#### Step 5.2: Set Up Alerts (Optional)
Create alert for coverage < 90%:
```sql
-- Daily check for incomplete runs
SELECT
  analysis_date,
  coverage_pct,
  actual_players,
  expected_players
FROM `nba-props-platform.nba_orchestration.backfill_processing_metadata`
WHERE analysis_date = CURRENT_DATE() - INTERVAL 1 DAY
  AND coverage_pct < 90;
```

If results found, send alert to Slack/email.

#### Step 5.3: Document Monitoring Procedures
Add to team runbook:
- Where to check coverage (BigQuery dashboard)
- How to interpret results
- When to escalate
- Troubleshooting steps

---

## ✅ Post-Deployment Validation

### Immediate (Within 1 Hour)
- [ ] Code deployed to production
- [ ] Data cleanup completed successfully
- [ ] Cloud Function deployed (if applicable)
- [ ] Integration tests passed
- [ ] No errors in logs

### First 24 Hours
- [ ] Next scheduled backfill completes successfully
- [ ] Coverage validation appears in logs
- [ ] Pre-flight check runs correctly
- [ ] No false positives (legitimate runs blocked)
- [ ] Cloud Function runs on schedule (if deployed)

### First Week
- [ ] 7 consecutive successful backfills
- [ ] All coverage >= 90%
- [ ] No incidents reported
- [ ] Team comfortable with new logging
- [ ] Monitoring dashboard reviewed

---

## 🚨 Rollback Procedures

### If Code Changes Cause Issues

#### Option 1: Revert Code
```bash
git revert <commit-hash>
git push origin main
```

#### Option 2: Use Force Flag
```bash
# Bypass improvements temporarily
python ...backfill.py ... --force
```

### If Cleanup Deleted Wrong Data
```bash
# Restore from backup
bq cp \
  nba-props-platform:nba_analytics.upcoming_player_game_context_backup_YYYYMMDD \
  nba-props-platform:nba_analytics.upcoming_player_game_context
```

### If Cloud Function Causes Issues
```bash
# Pause scheduler
gcloud scheduler jobs pause upcoming-tables-cleanup-schedule --location=us-east1

# OR delete function
gcloud functions delete upcoming-tables-cleanup --region=us-east1
```

---

## 📞 Support Contacts

**Deployment Issues:**
- Review deployment logs
- Check troubleshooting section in quick ref guide
- Escalate to platform team if needed

**Data Issues:**
- Verify backup exists before any fixes
- Check BigQuery for data integrity
- Review recent changes in git log

**Monitoring Issues:**
- Verify BigQuery permissions
- Check dashboard queries
- Review Cloud Function logs

---

## 📝 Deployment Log Template

```markdown
# Deployment Log - Backfill Improvements

**Date:** YYYY-MM-DD HH:MM
**Deployed By:** [Name]
**Environment:** Production

## Pre-Deployment
- [ ] Code review completed
- [ ] All tests passing
- [ ] Permissions verified

## Deployment
- [ ] Code deployed to main
- [ ] Data cleanup completed (X records deleted)
- [ ] Cloud Function deployed
- [ ] Integration tests passed

## Post-Deployment
- [ ] First backfill successful
- [ ] Coverage validation working
- [ ] Pre-flight check working
- [ ] Monitoring active

## Issues Encountered
[None / List any issues]

## Notes
[Any observations or recommendations]

## Sign-Off
Deployed: [Name]
Verified: [Name]
Date: YYYY-MM-DD
```

---

## 🎯 Success Criteria

Deployment is considered successful when:
1. ✅ All code changes deployed
2. ✅ Integration tests pass
3. ✅ First production backfill completes with 100% coverage
4. ✅ All 4 improvements visible in logs
5. ✅ No false positives or errors
6. ✅ Monitoring dashboards active
7. ✅ Team trained on new features

---

**Estimated Total Time:** 2-3 hours

**Risk Level:** Low (all changes are fail-safe and additive)

**Recommended Deployment Window:** Non-peak hours, with team available for monitoring

---

*Last Updated: 2026-01-13*
*Version: 1.0*
*Status: Ready for deployment*
