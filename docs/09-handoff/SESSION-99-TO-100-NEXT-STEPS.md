# Next Session TODO List - Session 100+

**Created:** 2026-01-18
**Status:** Ready for next session
**Context Remaining:** Medium (Session 99 complete)

---

## 🔴 CRITICAL - Do Immediately (Jan 19)

### 1. Monitor Jan 19 Grading Run (12:00 UTC / 7:00 AM ET)
**Priority:** 🔴 CRITICAL
**Time:** 20-30 minutes
**When:** Jan 19, 2026 at 12:00 UTC (or shortly after)

**This is the verification point for Sessions 98-99 fixes!**

**What to Check:**
- [ ] Zero 503 errors (Session 98 scheduling fix)
- [ ] Grading coverage > 70% for Jan 16-18
- [ ] Auto-heal retry logic working (Session 99 improvements)
- [ ] Structured logging events present
- [ ] Dashboard showing metrics correctly

**Commands:**
```bash
# Check for 503 errors (expect: ZERO)
gcloud functions logs read phase5b-grading --region=us-west2 --limit=100 | grep "503"

# Check coverage
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as graded
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= "2026-01-16"
GROUP BY game_date
ORDER BY game_date DESC'

# Check auto-heal retry patterns
gcloud functions logs read phase5b-grading --region=us-west2 --limit=200 | grep -E "Auto-heal|health check|retry"

# Check structured auto-heal events
gcloud functions logs read phase5b-grading --region=us-west2 --limit=200 --format=json | jq -r '.[] | select(.jsonPayload.event_type | startswith("phase3_trigger")) | "\(.timestamp) \(.jsonPayload.event_type) retries=\(.jsonPayload.details.retries // 0)"'

# View dashboard
open https://console.cloud.google.com/monitoring/dashboards/custom/1071d9e8-2f37-45b1-abb3-91abc2aa4174?project=nba-props-platform
```

**Success Criteria:**
- ✅ Zero 503 errors
- ✅ Coverage > 70% for all dates with boxscores
- ✅ Auto-heal shows successful retries in structured logs
- ✅ Dashboard displays metrics

**If Issues Found:**
- 503 errors still occurring → Investigate Phase 3 minScale setting
- Low coverage → Check auto-heal logs for failures
- Retry logic not working → Check deployment revision

**Reference:** `docs/02-operations/ML-MONITORING-REMINDERS.md`

**Automated Reminder:** Will trigger at 9:00 AM via Slack (#reminders channel)

---

## 🟡 HIGH Priority - Do This Week

### 2. Merge Sessions 98-99 PR
**Priority:** 🟡 HIGH
**Time:** 5 minutes
**When:** After Jan 19 grading run verification

**Steps:**
1. [ ] Verify Jan 19 grading run successful (see #1 above)
2. [ ] Open PR: https://github.com/najicham/nba-stats-scraper/compare/main...session-98-docs-with-redactions?expand=1
3. [ ] Copy description from `PR-DESCRIPTION.md`
4. [ ] Create and merge PR
5. [ ] Delete `session-98-docs-with-redactions` branch after merge

**Why Wait?**
- All production changes already deployed
- Just merging documentation
- Good to verify fixes work before documenting as "complete"

---

### 3. Validate Cloud Monitoring Alerts
**Priority:** 🟡 HIGH
**Time:** 45-60 minutes
**When:** Jan 19-20

**What to Test:**
The 3 alerts created in Session 98:

1. **[CRITICAL] Grading Phase 3 Auto-Heal 503 Errors**
   - [ ] Trigger test condition (simulate 503 error)
   - [ ] Verify Slack notification arrives in correct channel
   - [ ] Verify notification content is actionable
   - [ ] Document response procedure

2. **[WARNING] Phase 3 Analytics Processing Failures**
   - [ ] Trigger test condition
   - [ ] Verify Slack notification
   - [ ] Document response procedure

3. **[WARNING] Low Grading Coverage**
   - [ ] Trigger test condition (or wait for natural occurrence)
   - [ ] Verify Slack notification
   - [ ] Document response procedure

**How to Test:**
```bash
# List current alert policies
gcloud alpha monitoring policies list --project=nba-props-platform

# View specific alert
gcloud alpha monitoring policies describe POLICY_NAME --project=nba-props-platform

# Check alert history
# (Navigate to Cloud Console > Monitoring > Alerting)
```

**Deliverable:**
- Document test results
- Create alert response runbook if not exists
- Update alerts if notification channels wrong

**Reference:** See Session 98 alert creation scripts in `bin/monitoring/`

---

### 4. Run Staging Table Cleanup (Optional but Recommended)
**Priority:** 🟡 MEDIUM
**Time:** 30 minutes
**When:** Anytime this week

**Background:**
- 1,816 orphaned staging tables identified in Session 99
- Total size: ~15-20 MB
- Safe to delete (already consolidated to main tables)

**Steps:**
```bash
# Navigate to project
cd /home/naji/code/nba-stats-scraper

# Dry run first (safe, shows what would be deleted)
DRY_RUN=true MIN_AGE_DAYS=30 ./bin/cleanup/cleanup_orphaned_staging_tables.sh

# Review output carefully
# Check that tables are >30 days old
# Verify they're staging tables (match pattern)

# If everything looks good, run for real
DRY_RUN=false MIN_AGE_DAYS=30 ./bin/cleanup/cleanup_orphaned_staging_tables.sh
```

**Benefits:**
- Frees up storage
- Keeps dataset clean
- Prevents future accumulation
- Good housekeeping

**Risk:** Low (only deletes staging tables >30 days old that have been consolidated)

**Reference:** `bin/cleanup/cleanup_orphaned_staging_tables.sh`

---

## 🟢 MEDIUM Priority - Do Next 2 Weeks

### 5. XGBoost V1 Performance Analysis (Jan 24)
**Priority:** 🟢 MEDIUM
**Time:** 1-2 hours
**When:** Jan 24, 2026 (7 days from deployment)

**Automated Reminder:** Will trigger via Slack on Jan 24 at 9:00 AM

**What to Do:**
- [ ] Run 7-day performance query
- [ ] Compare XGBoost V1 vs CatBoost V8
- [ ] Verify production MAE ≤ 4.5
- [ ] Check win rate ≥ 52.4%
- [ ] Verify no placeholders

**Query:**
```sql
SELECT
  COUNT(*) as total_picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as production_mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-17'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
```

**Success Criteria:**
- MAE ≤ 4.5
- Win rate ≥ 52.4%
- Sample size > 100 picks

**Reference:** `docs/02-operations/ML-MONITORING-REMINDERS.md`

---

### 6. Create Session 99 Handoff Document
**Priority:** 🟢 MEDIUM
**Time:** 30-45 minutes
**When:** After Jan 19 grading run + PR merge

**What to Create:**
- Session 99 → 100 handoff document
- Summary of what was accomplished
- What's pending for next session
- Key metrics and verification results

**Template:** Follow pattern from `docs/09-handoff/SESSION-98-TO-99-GIT-PUSH-HANDOFF.md`

**Include:**
- Git push resolution
- Auto-heal deployment results
- Dashboard deployment
- Jan 19 grading run results
- Next steps

---

## ⚪ LOW Priority - Nice to Have

### 7. Dashboard Enhancements
**Priority:** ⚪ LOW
**Time:** 2-3 hours
**When:** After all above complete

**Potential Enhancements:**
- [ ] Create log-based metrics for auto-heal retry counts
- [ ] Add metric for 503 errors specifically (vs all 5xx)
- [ ] Add lock acquisition success/failure metrics
- [ ] Create custom charts using new metrics

**How:**
1. Create log-based metrics in Cloud Logging
2. Add metrics to dashboard JSON
3. Redeploy dashboard

**Reference:** `monitoring/dashboards/grading-system-dashboard.json` (template)

---

### 8. Increase Phase 3 Capacity (Only If Needed)
**Priority:** ⚪ LOW
**Time:** 15 minutes
**When:** Only if 503s persist after Jan 21

**Current Settings:**
- minScale: 1
- maxScale: 10

**If 503s continue:**
- [ ] Check Cloud Run metrics (CPU, memory, requests)
- [ ] Increase maxScale from 10 → 20
- [ ] Monitor for 3 days
- [ ] Document cost impact

**Command:**
```bash
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west1 \
  --max-instances=20 \
  --project=nba-props-platform
```

**Expected:** Not needed (minScale=1 should prevent cold starts)

---

### 9. Documentation Improvements
**Priority:** ⚪ LOW
**Time:** 1-2 hours
**When:** Anytime

**Potential Tasks:**
- [ ] Create quick-start guide for new developers
- [ ] Update architecture diagrams with Session 98-99 changes
- [ ] Create troubleshooting decision tree
- [ ] Add more examples to monitoring guides

---

## 📅 Scheduled Future Work (Automated Reminders)

### Jan 31, 2026 - XGBoost V1 Head-to-Head Comparison
**Reminder:** Automated Slack notification
**Time:** 1-2 hours
**What:** Compare XGBoost V1 vs CatBoost V8 performance patterns

### Feb 16, 2026 - Champion Decision Point
**Reminder:** Automated Slack notification
**Time:** 2-3 hours
**What:** Decide if XGBoost V1 should become champion model

### Mar 17, 2026 - Ensemble Optimization
**Reminder:** Automated Slack notification
**Time:** 3-4 hours
**What:** Optimize ensemble weights with 60 days of data

---

## 🎯 Recommended Session 100 Plan

**Option A: Verification & Cleanup (Recommended)**
**Time:** 2-3 hours

1. Monitor Jan 19 grading run (30 min) ← CRITICAL
2. Merge Sessions 98-99 PR (5 min)
3. Validate Cloud Monitoring alerts (60 min)
4. Run staging table cleanup (30 min)
5. Create Session 99→100 handoff (30 min)

**Option B: Passive Monitoring**
**Time:** 30 min/day for 7 days

1. Monitor Jan 19 grading run (30 min) ← CRITICAL
2. Daily coverage checks (5 min/day)
3. Wait for Jan 24 XGBoost V1 analysis

**Option C: Skip to Jan 24**
Wait for automated XGBoost V1 reminder, monitor grading passively

---

## 📊 Success Metrics for Next Session

**Must Have:**
- ✅ Jan 19 grading run verified successful
- ✅ Zero 503 errors confirmed
- ✅ Auto-heal retry logic confirmed working

**Should Have:**
- ✅ PR merged to main
- ✅ Cloud Monitoring alerts tested
- ✅ Staging tables cleaned up

**Nice to Have:**
- ✅ Dashboard enhancements
- ✅ Additional documentation
- ✅ Alert response runbooks

---

## 🔗 Key References

**Session Documentation:**
- `docs/09-handoff/SESSION-98-TO-99-GIT-PUSH-HANDOFF.md`
- `docs/09-handoff/SESSION-99-TO-100-HANDOFF.md`
- `docs/09-handoff/SESSION-99-AUTO-HEAL-AND-DASHBOARD-IMPROVEMENTS.md`

**Monitoring:**
- `docs/02-operations/ML-MONITORING-REMINDERS.md`
- `docs/02-operations/GRADING-MONITORING-GUIDE.md`
- `docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md`

**Scripts:**
- `bin/cleanup/cleanup_orphaned_staging_tables.sh`
- `monitoring/dashboards/deploy-grading-dashboard.sh`

**Dashboard:**
- https://console.cloud.google.com/monitoring/dashboards/custom/1071d9e8-2f37-45b1-abb3-91abc2aa4174?project=nba-props-platform

---

**Last Updated:** 2026-01-18
**Session:** 99 → 100
**Status:** Ready for next session
