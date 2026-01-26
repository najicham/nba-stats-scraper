# Cloud Function Consolidation - IN PROGRESS

**Date:** 2026-01-25
**Status:** 🚧 IN PROGRESS - Ready for execution
**Task:** #5 - Consolidate Cloud Function duplicate utilities
**Context:** Eliminate 125,667 lines of duplicate code across 8 Cloud Functions

---

## Current Status

### ✅ Analysis Complete
- Created consolidation script: `bin/maintenance/consolidate_cloud_function_utils.py`
- Dry-run completed successfully
- Identified **125,667 lines** of duplicate code to eliminate
- Found **62 duplicate files** across 8 Cloud Functions

### 🚧 Ready for Execution
- Script tested in dry-run mode
- Consolidation plan validated
- Import update strategy defined

---

## Key Findings from Dry-Run

### Massive Duplication Discovered

**Total lines to be saved:** **125,667 lines** (vs. 30K estimated!)

**Top Duplicate Files:**
1. `completeness_checker.py` - 1,761 lines × 7 = **10,566 lines saved**
2. `proxy_manager.py` - 947 lines × 7 = **5,682 lines saved**
3. `roster_manager.py` - 934 lines × 7 = **5,604 lines saved**
4. `player_name_resolver.py` - 935 lines × 7 = **5,610 lines saved**
5. `player_registry/reader.py` - 1,080 lines × 6 = **5,400 lines saved**
6. `nba_team_mapper.py` - 852 lines × 7 = **5,112 lines saved**
7. `email_alerting_ses.py` - 877 lines × 7 = **5,262 lines saved**
8. `notification_system.py` - 787 lines × 7 = **4,722 lines saved**

### Cloud Functions Affected (8 total)
1. `auto_backfill_orchestrator`
2. `daily_health_summary`
3. `phase2_to_phase3`
4. `phase3_to_phase4`
5. `phase4_to_phase5`
6. `phase5_to_phase6`
7. `self_heal`
8. `prediction_monitoring`

---

## Consolidation Strategy

### Phase 1: Copy Files to Central Location ✅ READY
**Action:** Copy 62 duplicate files to `orchestration/shared/utils/`

**Files to consolidate (52 new + 10 conflicts):**

**New files (52):**
- auth_utils.py (858 lines saved)
- bigquery_client.py (900 lines saved)
- bigquery_utils.py (3,642 lines saved)
- bigquery_utils_v2.py (2,844 lines saved)
- completeness_checker.py (10,566 lines saved)
- completion_tracker.py (3,828 lines saved)
- data_freshness_checker.py (1,830 lines saved)
- email_alerting_ses.py (5,262 lines saved)
- enhanced_error_notifications.py (2,634 lines saved)
- env_validation.py (762 lines saved)
- game_id_converter.py (2,286 lines saved)
- logging_utils.py (642 lines saved)
- metrics_utils.py (1,620 lines saved)
- mlb_game_id_converter.py (2,394 lines saved)
- mlb_team_mapper.py (3,786 lines saved)
- mlb_travel_info.py (2,232 lines saved)
- nba_team_mapper.py (5,112 lines saved)
- notification_system.py (4,722 lines saved)
- odds_player_props_preference.py (3,318 lines saved)
- odds_preference.py (2,292 lines saved)
- phase_execution_logger.py (1,974 lines saved)
- player_name_normalizer.py (1,476 lines saved)
- player_name_resolver.py (5,610 lines saved)
- processor_alerting.py (2,796 lines saved)
- prometheus_metrics.py (3,360 lines saved)
- proxy_health_logger.py (828 lines saved)
- proxy_manager.py (5,682 lines saved)
- pubsub_publishers.py (2,142 lines saved)
- rate_limiter.py (3,720 lines saved)
- roster_manager.py (5,604 lines saved)
- scraper_logging.py (1,026 lines saved)
- secrets.py (648 lines saved)
- sentry_config.py (864 lines saved)
- smart_alerting.py (1,782 lines saved)
- travel_team_info.py (366 lines saved)
- validation.py (1,614 lines saved)
- Plus 16 more files...

**Files with conflicts (10):**
These already exist centrally but have different hashes:
- `__init__.py`
- `alert_types.py`
- `bigquery_retry.py`
- `email_alerting.py`
- `pubsub_client.py`
- `retry_with_jitter.py`
- `slack_channels.py`
- `slack_retry.py`
- `storage_client.py`

**Action needed:** Manually review conflicts before consolidation

---

### Phase 2: Update Imports ⏳ NEXT
**Action:** Update all Cloud Function imports from `shared.utils` to `orchestration.shared.utils`

**Pattern:**
```python
# OLD
from shared.utils.completeness_checker import CompletenessChecker

# NEW
from orchestration.shared.utils.completeness_checker import CompletenessChecker
```

**Files to update:** All `*.py` files in 8 Cloud Function directories

**Automation:** Use find/replace script after manual review

---

### Phase 3: Test ⏳ TODO
**Action:** Validate Cloud Functions still work

**Test strategy:**
1. Run existing orchestrator tests
2. Deploy one Cloud Function to staging
3. Trigger test run
4. Validate logs and metrics
5. Roll out to remaining functions

---

### Phase 4: Delete Duplicates ⏳ TODO
**Action:** Remove duplicate `shared/utils/` directories from Cloud Functions

**Safety:** Only after Phase 3 testing passes

---

## Execution Plan

### Step 1: Execute Consolidation (DO THIS NEXT)
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Execute the consolidation (copies files)
python bin/maintenance/consolidate_cloud_function_utils.py --execute
```

**Expected:** 52 files copied to `orchestration/shared/utils/`

---

### Step 2: Handle Conflicts Manually
**Review these 10 files with hash conflicts:**
1. Compare central version vs. duplicate version
2. Determine which is canonical
3. Update central if needed
4. Document decision

---

### Step 3: Update Imports
Create update script:
```bash
# Find all imports to update
find orchestration/cloud_functions -name "*.py" -type f -exec grep -l "from shared.utils" {} \;

# Update imports (after review)
find orchestration/cloud_functions -name "*.py" -type f -exec sed -i 's/from shared\.utils\./from orchestration.shared.utils./g' {} \;
```

---

### Step 4: Test Changes
```bash
# Run orchestrator tests
pytest tests/integration/test_orchestrator_transitions.py -v
pytest tests/cloud_functions/ -v

# Deploy to staging
gcloud functions deploy phase2-to-phase3 --env-vars-file staging.yaml

# Monitor logs
gcloud functions logs read phase2-to-phase3 --limit 50
```

---

### Step 5: Delete Duplicates (LAST)
```bash
# Only after testing passes!
rm -rf orchestration/cloud_functions/*/shared/utils/
```

---

## Rollback Plan

**If issues discovered:**

1. **Immediate:** Revert git commits
```bash
git reset --hard <previous-commit>
```

2. **Redeploy:** Previous version to Cloud Functions
```bash
gcloud functions deploy <function-name> --source=. --entry-point=<entry>
```

3. **Investigate:** Review specific function failures
4. **Fix:** Address root cause
5. **Retry:** Consolidation with fixes

---

## Files Created This Session

### New Files
1. `bin/maintenance/consolidate_cloud_function_utils.py` - Consolidation script
2. `docs/09-handoff/2026-01-25-CLOUD-FUNCTION-CONSOLIDATION-IN-PROGRESS.md` - This file

---

## Next Session Actions

### Option A: Complete Consolidation (RECOMMENDED)
**Time:** 2-3 hours
**Steps:**
1. Execute consolidation script (`--execute`)
2. Resolve 10 file conflicts
3. Update imports (find/replace)
4. Run tests
5. Delete duplicates
6. Commit and document

**Result:** **125,667 lines eliminated!**

---

### Option B: Investigate Conflicts First
**Time:** 1 hour
**Steps:**
1. Review 10 conflicting files
2. Determine canonical versions
3. Document decisions
4. Then proceed with Option A

**Result:** Careful consolidation with full understanding

---

## Risk Assessment

### Low Risk ✅
- **Duplicate files are identical** (same MD5 hash)
- **Central shared/utils already exists** (pattern established)
- **81 tests provide safety net**
- **Rollback is straightforward** (git revert)

### Medium Risk ⚠️
- **10 files have conflicts** (different hashes)
- **Import updates needed** (find/replace could miss some)
- **Deployment testing required**

### Mitigation
- ✅ Handle conflicts manually first
- ✅ Use automated import updates with review
- ✅ Test each Cloud Function before production
- ✅ Deploy incrementally (one function at a time)

---

## Expected Benefits

### Immediate
- **125,667 lines eliminated** from codebase
- **Maintenance burden reduced** (update once, not 7× times)
- **Git history cleaner** (smaller diffs)
- **Deployment faster** (fewer files to package)

### Long-term
- **Easier updates** (centralized utilities)
- **Reduced bugs** (no version drift across functions)
- **Faster onboarding** (single source of truth)
- **Better code reuse** (clear shared utilities)

---

## Success Criteria

### ✅ Phase 1 Complete When:
- [ ] 52 new files copied to `orchestration/shared/utils/`
- [ ] 10 conflicts resolved
- [ ] All file hashes validated

### ✅ Phase 2 Complete When:
- [ ] All imports updated in 8 Cloud Functions
- [ ] No `from shared.utils` imports remain (except tests)
- [ ] Import syntax validated

### ✅ Phase 3 Complete When:
- [ ] All orchestrator tests pass
- [ ] 1 Cloud Function deployed and tested in staging
- [ ] Logs show no import errors

### ✅ Phase 4 Complete When:
- [ ] Duplicate directories deleted
- [ ] Git commit created
- [ ] Documentation updated
- [ ] **125,667 lines saved!**

---

## Quick Reference Commands

### Check current duplicates
```bash
find orchestration/cloud_functions -type d -path "*/shared/utils" | wc -l
```

### Run consolidation (dry-run)
```bash
python bin/maintenance/consolidate_cloud_function_utils.py --dry-run
```

### Execute consolidation
```bash
python bin/maintenance/consolidate_cloud_function_utils.py --execute
```

### Count lines saved
```bash
find orchestration/cloud_functions/*/shared/utils -name "*.py" -exec wc -l {} \; | awk '{sum+=$1} END {print sum}'
```

---

## Context for Next Session

**You are here:** ✅ Analysis complete, ready to execute

**What's done:**
- Consolidation script created and tested
- Dry-run completed (125,667 lines to save)
- 62 duplicate files identified
- 10 conflicts flagged for review

**What's next:**
- Execute consolidation (`--execute`)
- Resolve 10 file conflicts
- Update imports
- Test Cloud Functions
- Delete duplicates

**Estimated time to complete:** 2-3 hours

---

**Status:** 🚧 IN PROGRESS
**Created:** 2026-01-25
**Last Updated:** 2026-01-25
**Next Step:** Execute consolidation script with `--execute` flag
