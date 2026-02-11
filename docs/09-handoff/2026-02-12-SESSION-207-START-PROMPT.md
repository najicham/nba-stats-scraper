# Session 207 Start Prompt - Post-Testing Infrastructure Implementation

**Date:** 2026-02-12 (for Session 207+)
**Previous Session:** 206 - Testing infrastructure + P0 Cloud Build fix
**Status:** Ready for validation and next improvements

---

## Quick Context: What Just Happened (Session 206)

Session 206 conducted comprehensive review of Session 205 IAM fixes and discovered/fixed a **CRITICAL P0 bug**:

🚨 **Problem Found:** Session 205 added IAM permissions to manual deployment scripts but NOT to Cloud Build auto-deploy (`cloudbuild-functions.yaml`). The next auto-deploy would wipe IAM permissions again.

✅ **Problem Fixed:** Added Step 3 to Cloud Build config with IAM binding + verification

✅ **Prevention Added:** 29 tests (10 unit + 19 integration) prevent recurrence

---

## What's Ready to Use

### 1. Cloud Build Auto-Deploy (FIXED - P0)
**File:** `cloudbuild-functions.yaml`
**What changed:** Added Step 3 that sets IAM permissions after deployment
**Impact:** Next orchestrator deploy via Cloud Build will preserve IAM permissions

### 2. Test Suite (29 Tests - All Passing)
**Unit tests:** `tests/unit/validation/test_orchestrator_iam_check.py` (10 tests)
**Integration tests:** `tests/integration/test_orchestrator_deployment.py` (19 tests)
**Test pass rate:** 100% (29/29)

**Run tests:**
```bash
# All tests
PYTHONPATH=. pytest tests/unit/validation/test_orchestrator_iam_check.py tests/integration/test_orchestrator_deployment.py -v

# Should see: 29 passed, 1 skipped
```

### 3. Testing Environment Guide
**File:** `docs/05-development/testing-environment-options.md`
**Content:** 3 approaches for testing orchestrator changes safely
- **Option A:** Local emulators ($0/month, can't test IAM)
- **Option B:** Dataset-prefix staging ($50-100/month, full IAM testing) ⭐ **Recommended**
- **Option C:** Separate GCP project ($2000-5000/month, production replica)

**Quick start for Option B (recommended):**
```bash
# Scripts to create (not yet implemented):
./bin/testing/setup_staging_datasets.sh     # Create test datasets
./bin/testing/seed_staging_data.sh          # Copy sample data
./bin/testing/deploy_staging.sh             # Deploy with DATASET_PREFIX
```

### 4. Opus Code Review Findings
**8 findings documented** in Session 206 handoff
- 1 P0 (FIXED - Cloud Build IAM step)
- 2 P1 (error handling, hardcoded service account)
- 3 P2 (env var drift, weak parsing, validation list)
- 2 P3 (cleanup, consistency)

---

## What to Validate (First Priority)

### Morning Validation (Feb 13)
**Check if orchestrator triggered autonomously after Phase 3 completion:**

```python
from google.cloud import firestore
from datetime import datetime

db = firestore.Client(project='nba-props-platform')

# Check yesterday's orchestrator trigger
doc = db.collection('phase3_completion').document('2026-02-12').get()
if doc.exists:
    data = doc.to_dict()
    triggered = data.get('_triggered', False)

    if triggered:
        print("✅ SUCCESS: Orchestrator triggered autonomously!")
        print("   IAM fix is working correctly")
    else:
        print("❌ FAILED: Orchestrator did NOT trigger")
        print("   Need to investigate IAM permissions")
else:
    print("⏳ No Phase 3 completion yet for 2026-02-12")
```

**Expected:** `_triggered=True` (means IAM fix worked!)

### Test Validation
Run the test suite to confirm everything passes:
```bash
PYTHONPATH=. pytest tests/unit/validation/test_orchestrator_iam_check.py -v
PYTHONPATH=. pytest tests/integration/test_orchestrator_deployment.py -v

# Expected: 29 passed, 1 skipped
```

### IAM Permission Check
Verify all orchestrators have correct permissions:
```bash
for orch in phase3-to-phase4-orchestrator phase4-to-phase5-orchestrator phase5-to-phase6-orchestrator; do
  echo "=== $orch ==="
  gcloud run services get-iam-policy $orch --region us-west2 | grep -A 1 "roles/run.invoker"
done

# Expected: All 3 orchestrators show roles/run.invoker for compute service account
```

---

## What to Do Next

### Immediate (This Session)

**1. Validate Orchestrator Triggering (5 min)**
Run the Firestore check above to confirm IAM fix worked autonomously.

**2. Run Daily Validation (5 min)**
```bash
/validate-daily
```

Check Phase 0.6 (Orchestrator Health) - all checks should pass, including:
- Check 5: Orchestrator IAM Permissions (new from Session 205)

**3. Check for Any Issues (5 min)**
```bash
# Check if any games today
bq query "SELECT COUNT(*) FROM nba_reference.nba_schedule WHERE game_date = CURRENT_DATE()"

# Check predictions generated
bq query "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'"
```

### Priority 1 - Address P1 Findings (1-2 hours)

**From Opus Review:**

**P1a - Add Error Handling to Manual Scripts:**
Add explicit error handling to manual deployment scripts:
- `bin/orchestrators/deploy_phase3_to_phase4.sh`
- `bin/orchestrators/deploy_phase4_to_phase5.sh`
- `bin/orchestrators/deploy_phase5_to_phase6.sh`

**Pattern to add (after IAM binding step):**
```bash
# Verify the binding was applied
echo "Verifying IAM binding..."
IAM_POLICY=$(gcloud run services get-iam-policy $FUNCTION_NAME \
    --region=$REGION --project=$PROJECT_ID --format=json 2>/dev/null)

if echo "$IAM_POLICY" | grep -q "roles/run.invoker"; then
    echo -e "${GREEN}✓ IAM binding verified successfully${NC}"
else
    echo -e "${RED}CRITICAL: IAM binding verification FAILED${NC}"
    exit 1
fi
```

**P1b - Fix Env Var Drift Risk:**
Change `--set-env-vars` to `--update-env-vars` in manual scripts.

**Files to update:**
- `bin/orchestrators/deploy_phase3_to_phase4.sh` (line 144)
- `bin/orchestrators/deploy_phase5_to_phase6.sh` (line 158)

### Priority 2 - Implement Staging Environment (2-3 hours)

**Follow the guide:** `docs/05-development/testing-environment-options.md`

**Implement Option B (Dataset-Prefix Staging):**

1. **Create helper scripts:**
```bash
# Create bin/testing/ directory
mkdir -p bin/testing

# Create setup script
cat > bin/testing/setup_staging_datasets.sh << 'EOF'
#!/bin/bash
# See docs/05-development/testing-environment-options.md for full implementation
EOF
chmod +x bin/testing/setup_staging_datasets.sh

# Create seed script
cat > bin/testing/seed_staging_data.sh << 'EOF'
#!/bin/bash
# See docs/05-development/testing-environment-options.md for full implementation
EOF
chmod +x bin/testing/seed_staging_data.sh

# Create deploy script
cat > bin/testing/deploy_staging.sh << 'EOF'
#!/bin/bash
# See docs/05-development/testing-environment-options.md for full implementation
EOF
chmod +x bin/testing/deploy_staging.sh
```

2. **Add DATASET_PREFIX support to processors:**
Update these files to support `DATASET_PREFIX` env var:
- `data_processors/raw/processor_base.py`
- `data_processors/analytics/analytics_base.py`
- `data_processors/precompute/precompute_base.py`

**Pattern:**
```python
import os

DATASET_PREFIX = os.environ.get('DATASET_PREFIX', '')
RAW_DATASET = f"{DATASET_PREFIX}nba_raw"
ANALYTICS_DATASET = f"{DATASET_PREFIX}nba_analytics"
```

3. **Test the staging environment:**
```bash
# Setup test datasets
./bin/testing/setup_staging_datasets.sh

# Seed with sample data
./bin/testing/seed_staging_data.sh 2026-02-10

# Deploy orchestrator to test
DATASET_PREFIX=test_ ./bin/testing/deploy_staging.sh phase3-to-phase4-orchestrator
```

### Priority 3 - Address P2/P3 Findings (Optional)

**P2 - Improve IAM Validation Parsing:**
Update `/validate-daily` Check 5 to parse JSON properly instead of string matching.

**P2 - Remove phase2-to-phase3 from Validation:**
It's monitoring-only and may be deleted. Either remove from validation list or mark as optional.

**P3 - Cleanup `.bak` Files:**
```bash
rm bin/orchestrators/*.bak
echo "*.bak" >> .gitignore
git add .gitignore
git commit -m "chore: Add .bak to gitignore"
```

**P3 - Standardize Import Validation:**
Make all deployment scripts consistent (either run validation or skip it, not mixed).

---

## Key Files & Documentation

### Session 206 Output
- **Handoff:** `docs/09-handoff/2026-02-12-SESSION-206-HANDOFF.md` (comprehensive)
- **Integration tests doc:** `docs/09-handoff/2026-02-12-SESSION-206-INTEGRATION-TESTS.md`
- **Testing guide:** `docs/05-development/testing-environment-options.md`

### Test Files
- **Unit tests:** `tests/unit/validation/test_orchestrator_iam_check.py`
- **Unit test README:** `tests/unit/validation/README_IAM_CHECK.md`
- **Integration tests:** `tests/integration/test_orchestrator_deployment.py`
- **Integration README:** `tests/integration/README_ORCHESTRATOR_DEPLOYMENT.md`

### Code Changes
- **Cloud Build config:** `cloudbuild-functions.yaml` (Step 3 added)
- **validate-daily skill:** `.claude/skills/validate-daily/SKILL.md` (Check 5 added)

### Previous Sessions
- **Session 205:** `docs/09-handoff/2026-02-12-SESSION-205-HANDOFF.md` (original IAM fix)
- **Session 204:** `docs/09-handoff/2026-02-12-SESSION-204-FINAL-RECOMMENDATIONS.md` (phase2-to-phase3 removal)

---

## Common Commands

### Validation
```bash
# Daily validation
/validate-daily

# Check orchestrator IAM permissions
for orch in phase3-to-phase4-orchestrator phase4-to-phase5-orchestrator phase5-to-phase6-orchestrator; do
  gcloud run services get-iam-policy $orch --region us-west2 | grep -q "roles/run.invoker" && echo "$orch: ✅ OK" || echo "$orch: ❌ MISSING"
done

# Run all tests
PYTHONPATH=. pytest tests/unit/validation/test_orchestrator_iam_check.py tests/integration/test_orchestrator_deployment.py -v
```

### Deployment
```bash
# Check deployment drift
./bin/check-deployment-drift.sh

# Manual deploy (if needed)
./bin/orchestrators/deploy_phase3_to_phase4.sh

# Check Cloud Build logs
gcloud builds list --region=us-west2 --limit=5
```

### Predictions
```bash
# Check today's predictions
bq query "SELECT COUNT(*), system_id FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE() GROUP BY system_id"

# Check signal
bq query "SELECT * FROM nba_predictions.daily_prediction_signals WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'"
```

---

## Quick Decision Tree

**Start here:**
```
1. Did orchestrator trigger autonomously yesterday?
   → YES: ✅ IAM fix validated, proceed to P1 improvements
   → NO: ❌ Investigate IAM permissions, check Cloud Build logs
   → UNKNOWN: Run Firestore check above

2. Do all tests pass?
   → YES: ✅ Test suite healthy, safe to continue
   → NO: ❌ Fix failing tests before proceeding

3. Are there any production issues today?
   → YES: ❌ Address production issues first
   → NO: ✅ Proceed with P1/P2 improvements

4. What's the priority?
   → HIGH: Fix P1 findings (error handling, env var drift)
   → MEDIUM: Implement staging environment (Option B)
   → LOW: Address P2/P3 findings (parsing, cleanup)
   → RESEARCH: Explore other improvements from Opus review
```

---

## Expected State

### System Should Be
- ✅ All orchestrators have `roles/run.invoker` permission
- ✅ Cloud Build auto-deploy preserves IAM permissions (Step 3 added)
- ✅ 29 tests passing (10 unit + 19 integration)
- ✅ `/validate-daily` includes IAM permission check (Phase 0.6 Check 5)
- ✅ Documentation complete (handoff + guides + READMEs)

### System Should NOT Be
- ❌ Missing IAM permissions on any orchestrator
- ❌ Failing tests
- ❌ Missing predictions for today
- ❌ Stale deployments (check with `./bin/check-deployment-drift.sh`)

---

## Session 207 Suggested Agenda

**Morning (30 min):**
1. Run Firestore validation (check if orchestrator triggered yesterday)
2. Run `/validate-daily`
3. Run test suite
4. Review any overnight issues

**Mid-day (2-3 hours):**
1. Address P1 findings (error handling + env var fix)
2. Test manual deployment scripts with changes
3. Commit and push improvements

**Afternoon (2-3 hours - Optional):**
1. Implement staging environment (Option B)
2. Create helper scripts (setup, seed, deploy)
3. Add DATASET_PREFIX support to processors
4. Test staging deployment

**Wrap-up (30 min):**
1. Run full test suite
2. Commit staging infrastructure
3. Create Session 207 handoff

---

## Critical Reminders

⚠️ **Cloud Build auto-deploy now safe** - The P0 bug is fixed. Next orchestrator deploy will preserve IAM permissions.

⚠️ **Tests prevent recurrence** - 29 tests ensure Session 205 bug can't happen again.

⚠️ **Staging guide ready** - Use Option B (dataset-prefix) for safe testing before production.

⚠️ **Manual scripts need P1 fixes** - Add error handling and switch to `--update-env-vars`.

⚠️ **Validation is key** - Always check if orchestrator triggered autonomously to confirm IAM fix working.

---

## Copy-Paste Start

**To start Session 207, use this:**

```
Session 207 start - following up on Session 206 testing infrastructure.

First, let's validate the IAM fix worked:

1. Check if orchestrator triggered autonomously yesterday (Firestore validation)
2. Run /validate-daily to check system health
3. Run test suite to confirm all tests passing

Then proceed with P1 improvements:
- Add error handling to manual deployment scripts
- Fix env var drift risk (--set-env-vars → --update-env-vars)

Reference: docs/09-handoff/2026-02-12-SESSION-207-START-PROMPT.md
```

---

**Ready to go! 🚀**

All context, commands, and next steps are documented. Session 207 can start with validation and proceed to improvements.
