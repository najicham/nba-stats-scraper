# Session 122 - Action Items

**Created:** 2026-01-24
**Status:** Ready for next session

---

## P1 - Fix These Soon

### 1. Fix Cleanup Processor Test
**File:** `tests/unit/orchestration/test_cleanup_processor.py`
**Issue:** Test assertion failing - query contains `bdl_box_scores` but test expects it not to
**Fix Options:**
- Update the cleanup processor to use correct table name
- Or update test expectation if table name is correct

```bash
# Run test
pytest tests/unit/orchestration/test_cleanup_processor.py -v
```

### 2. Configure Slack Webhook
**Issue:** `SLACK_WEBHOOK_URL` not configured in Cloud Functions
**Impact:** No Slack notifications for health checks
**Files affected:** `daily-health-check` Cloud Function

### 3. Fix Prediction Test Imports
**Files:**
- `tests/unit/prediction_tests/test_execution_logger.py`
- `tests/unit/prediction_tests/test_system_circuit_breaker.py`

**Error:** `ModuleNotFoundError: No module named 'predictions.worker'`
**Likely fix:** Check PYTHONPATH or conftest.py setup

---

## P2 - Nice to Have

### 4. Fix Deprecation Warnings
**Files using deprecated `datetime.utcnow()`:**
```
tests/e2e/test_rate_limiting_flow.py
tests/unit/prediction_tests/coordinator/test_batch_staging_writer_race_conditions.py
tests/processors/precompute/team_defense_zone_analysis/test_validation.py
tests/unit/orchestration/test_cleanup_processor.py
```

**Fix:** Replace with `datetime.now(timezone.utc)`

### 5. Push Commits
```bash
git push origin main
```

### 6. Investigate Git Modified Files
Files showing modified but no diff:
- `bin/scraper_catchup_controller.py`
- `shared/utils/slack_retry.py`

Check with:
```bash
git diff --stat
git diff --ignore-space-change
```

---

## Deferred from Session 11 (P2/P3)

### P2 - Medium Priority
- Add `exc_info=True` to error logs (40+ files)
- Replace direct `requests` calls with http_pool (22 files)

### P3 - Low Priority
- Add Firestore state persistence to prediction worker
- Configure DLQs for critical Pub/Sub topics
- Add validation to remaining cloud functions (15+ functions)

---

## Quick Reference

```bash
# Run all unit tests (excluding broken prediction tests)
pytest tests/unit/ --ignore=tests/unit/prediction_tests/ -v

# Check cleanup processor specifically
pytest tests/unit/orchestration/test_cleanup_processor.py -v

# Find datetime.utcnow usage
grep -r "datetime.utcnow" tests/
```
