# Next Session TODO List

**Generated:** 2026-01-26
**Context:** Post-consolidation deployment complete, operational issues discovered

---

## 🔴 CRITICAL (Fix Immediately)

### 1. Fix Firestore Import Error in completion_tracker.py
**Priority:** P0 - Blocking phase completion tracking
**Impact:** Phase completions cannot be recorded

**Issue:**
```python
# In orchestration/shared/utils/completion_tracker.py line 243
"completed_at": firestore.SERVER_TIMESTAMP  # NameError: name 'firestore' is not defined
```

**Fix:**
```python
# Add to imports at top of file
from google.cloud import firestore

# Or use the client instance:
"completed_at": firestore.SERVER_TIMESTAMP
```

**Test:**
```bash
# After fix, redeploy affected functions
./bin/orchestrators/deploy_phase2_to_phase3.sh
# Check logs for the error
gcloud functions logs read phase2-to-phase3-orchestrator --region us-west2 --limit 50 | grep "firestore"
```

---

### 2. Create Missing BigQuery Table: nba_orchestration.phase_completions
**Priority:** P0 - Blocking completion tracking
**Impact:** Cannot track which processors have completed

**Error:**
```
404 Not found: Table nba-props-platform:nba_orchestration.phase_completions
```

**Action Items:**
- [ ] Check if table exists in different dataset
- [ ] Create table with correct schema if missing
- [ ] Verify table permissions for service account
- [ ] Update orchestrator config if needed

**Commands:**
```bash
# Check if table exists
bq ls nba_orchestration

# Create dataset if missing
bq mk --dataset nba-props-platform:nba_orchestration

# Create table (need schema from existing implementation)
# TODO: Get schema from completion_tracker.py or backup
```

---

## 🟡 HIGH PRIORITY (Fix This Week)

### 3. Investigate and Fix Remaining Import Errors

**Found in logs:**
- `shared.utils` import errors (old pattern)
- `shared.clients` import errors in phase4/phase5/phase6

**Action Items:**
- [ ] Search codebase for remaining `from shared.utils` imports
- [ ] Update to use `from orchestration.shared.utils`
- [ ] Verify shared/clients is included in deployments
- [ ] Consider consolidating shared/clients too

**Commands:**
```bash
# Find old patterns
grep -r "from shared\.utils" orchestration/cloud_functions --include="*.py"
grep -r "from shared\.clients" orchestration/cloud_functions --include="*.py" | grep -v "shared/clients/"

# Update deployment script if needed to include shared/clients
```

---

### 4. Expand Test Coverage for Cloud Functions

**Current:** 24 orchestrator tests
**Needed:** Individual function handlers, end-to-end scenarios

**See:** `docs/08-testing/TEST_COVERAGE_ROADMAP.md`

**Action Items:**
- [ ] Add tests for phase2_to_phase3 handler
- [ ] Add tests for phase3_to_phase4 handler
- [ ] Add tests for phase4_to_phase5 handler
- [ ] Add tests for phase5_to_phase6 handler
- [ ] Add end-to-end pipeline test (Phase 1→6)
- [ ] Add self-healing scenario tests
- [ ] Add error condition tests

---

### 5. Update Remaining Deployment Scripts

**Status:** 4 phase scripts updated, others need updating

**Action Items:**
- [ ] Find all Cloud Functions using `orchestration.shared.utils`
- [ ] Update their deployment scripts to use include_consolidated_utils.sh
- [ ] Test each deployment
- [ ] Document which functions updated

**Commands:**
```bash
# Find all functions using consolidated utils
find orchestration/cloud_functions -name "main.py" -exec grep -l "orchestration\.shared\.utils" {} \;

# Find their deployment scripts
find bin/orchestrators -name "deploy_*.sh" -type f

# Update each script to source the helper
```

---

## 🟢 MEDIUM PRIORITY (Nice to Have)

### 6. Monitor Production for 24 Hours

**Goal:** Verify consolidation works in real environment

**Metrics to Watch:**
- [ ] Phase completion rates (should remain stable)
- [ ] Import errors in logs (should be zero after fixes)
- [ ] Pipeline end-to-end success rate
- [ ] Prediction volume (should not drop)

**Commands:**
```bash
# Phase completions
bq query --use_legacy_sql=false '
  SELECT game_date, phase, COUNT(DISTINCT processor_name) as processors
  FROM `nba-betting-insights.orchestration.phase_completions`
  WHERE game_date >= CURRENT_DATE() - 1
  GROUP BY game_date, phase
  ORDER BY game_date DESC, phase
'

# Check for import errors
for func in phase2-to-phase3-orchestrator phase3-to-phase4-orchestrator phase4-to-phase5-orchestrator phase5-to-phase6-orchestrator; do
  echo "=== $func ==="
  gcloud functions logs read $func --region us-west2 --limit 100 | grep -i "import\|module"
done
```

---

### 7. Add Deployment Validation Tests

**Goal:** Catch deployment issues before they reach production

**Action Items:**
- [ ] Create pre-deployment smoke tests
- [ ] Add import validation to CI/CD
- [ ] Create deployment rollback procedure
- [ ] Document deployment best practices

---

### 8. Consolidate Remaining Shared Directories

**Status:** Only `shared/utils/` consolidated so far

**Candidates for consolidation:**
- `shared/clients/` - Client pool managers (BigQuery, Firestore, Pub/Sub)
- `shared/config/` - Configuration files
- `shared/alerts/` - Alerting utilities
- `shared/publishers/` - Pub/Sub publishers

**Benefits:**
- Further reduce code duplication
- Centralize maintenance
- Easier to update cross-cutting concerns

**Estimate:** Similar to utils consolidation, could save 50K+ more lines

---

## 📋 BACKLOG (Future Improvements)

### 9. Improve Prediction Accuracy
**Goal:** Tune ML models for better prop predictions
**See:** Session 20 handoff recommendations

### 10. Add More Integration Tests
**Goal:** Increase test coverage beyond current 24 tests
**See:** `docs/08-testing/TEST_COVERAGE_ROADMAP.md`

### 11. Add CI/CD for Cloud Function Deployments
**Goal:** Automate deployment process
**Action:** Set up GitHub Actions workflow

### 12. Create Staging Environment
**Goal:** Test changes before production
**Action:** Duplicate GCP resources with staging prefix

### 13. Add Deployment Observability
**Goal:** Better visibility into deployment health
**Action:** Add deployment metrics, alerts, dashboards

---

## 📊 Session 21 Recap

### ✅ Completed
- All 24 orchestrator tests passing
- 4 Cloud Functions deployed successfully
- Deployment scripts updated for consolidation
- Session 21 handoff document created

### 🚨 Issues Discovered
1. **Firestore import error** in completion_tracker.py
2. **Missing BigQuery table** nba_orchestration.phase_completions
3. **Some old import patterns** still in codebase
4. **shared/clients imports** need verification

### 📈 Deployment Status
| Function | Status | Revision |
|----------|--------|----------|
| phase2-to-phase3-orchestrator | ✅ ACTIVE | 00029-zop |
| phase3-to-phase4-orchestrator | ✅ ACTIVE | 00019-naj |
| phase4-to-phase5-orchestrator | ✅ ACTIVE | 00026-qob |
| phase5-to-phase6-orchestrator | ✅ ACTIVE | 00015-tuj |

---

## 🎯 Recommended Next Steps

1. **START HERE:** Fix the Firestore import error (#1)
2. **THEN:** Create the missing BigQuery table (#2)
3. **VERIFY:** Check logs after fixes to ensure no errors
4. **MONITOR:** Watch production for 24 hours (#6)
5. **CONTINUE:** Update remaining deployment scripts (#5)
6. **EXPAND:** Add more test coverage (#4)

---

## 📚 Resources

**Documentation:**
- Session 20 Handoff: `docs/09-handoff/2026-01-25-SESSION-20-HANDOFF.md`
- Session 21 Handoff: `docs/09-handoff/2026-01-25-SESSION-21-POST-CONSOLIDATION-VALIDATION.md`
- Test Coverage Roadmap: `docs/08-testing/TEST_COVERAGE_ROADMAP.md`

**Deployment:**
- Deployment scripts: `bin/orchestrators/deploy_phase*.sh`
- Consolidation helper: `bin/orchestrators/include_consolidated_utils.sh`

**Monitoring:**
- GCP Console: https://console.cloud.google.com/functions?project=nba-props-platform
- Admin Dashboard: `services/admin_dashboard/`

---

**Last Updated:** 2026-01-26
**Status:** Ready for next session
