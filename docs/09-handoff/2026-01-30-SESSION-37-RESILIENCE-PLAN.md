# Session 37 - System Resilience Plan

**Date:** 2026-01-30
**Focus:** Root cause analysis and resilience improvements

---

## Executive Summary

Today's validation revealed **3 critical issues** that highlight systemic weaknesses in deployment validation, error handling, and monitoring:

| Issue | Root Cause | Impact | Duration |
|-------|-----------|--------|----------|
| 0 predictions today | Missing `COPY predictions/worker/` in coordinator Dockerfile | All predictions blocked | ~19+ hours |
| Phase 3 incomplete (3/5) | PlayerGameSummaryProcessor throws exception when no game data exists | False failure signals | Recurring |
| Model drift | Hit rate dropped from 69% to 48% | Prediction quality degraded | 5 weeks |

---

## Root Causes Identified

### 1. Dockerfile Import Mismatch (P1 CRITICAL)

**What happened:**
- Commit `b02a2b04` (Jan 27) changed import path to `from predictions.worker.data_loaders import`
- Dockerfile was NOT updated to `COPY predictions/worker/`
- Coordinator crashed with `ModuleNotFoundError` on every prediction request

**Why it wasn't caught:**
- No pre-deployment validation of import paths
- No startup import verification
- Unit tests didn't catch deferred imports (import inside function, not at module level)

**Fix Applied:** Added `COPY predictions/worker/` to Dockerfile (commit `9ce805ba`)

### 2. Same-Day Processor False Failures (P2 HIGH)

**What happened:**
- `PlayerGameSummaryProcessor` triggered for same-day processing
- No game data exists yet (games haven't been played)
- Processor throws `ValueError("No data extracted")` instead of graceful skip
- Phase 3 completion shows 3/5 instead of expected state

**Why it's problematic:**
- Creates noise in monitoring (false failures)
- Pub/Sub retries the failed message repeatedly
- Circuit breaker eventually opens, blocking legitimate requests

**Root cause locations:**
- `analytics_base.py:1158-1173` - Throws exception on empty data
- `player_game_summary_processor.py:918` - Calls validation that throws

### 3. Model Performance Drift (P1 CRITICAL)

**What happened:**
- Hit rate dropped from 69.2% (Dec 28) to 48.3% (Jan 25)
- 3 consecutive weeks below 55% threshold
- No automated alerting triggered

**Why it wasn't caught:**
- Model drift monitoring exists but doesn't auto-alert
- `/validate-daily` shows the data but requires manual review

---

## Proposed Resilience Improvements

### Tier 1: Immediate Fixes (This Session)

| # | Improvement | Effort | Impact |
|---|------------|--------|--------|
| 1 | ✅ Fix coordinator Dockerfile | Done | Predictions unblocked |
| 2 | Add pre-deployment import validation | 2h | Prevent import errors |
| 3 | Add startup import verification to services | 1h | Catch errors at deploy time |

### Tier 2: Short-Term Improvements (Next 1-2 Sessions)

| # | Improvement | Effort | Impact |
|---|------------|--------|--------|
| 4 | Make processors gracefully skip when no data | 2h | Reduce false failures |
| 5 | Add Slack alerting for model drift | 1h | Catch drift earlier |
| 6 | Create deployment verification script | 2h | Verify services work after deploy |

### Tier 3: Medium-Term Improvements (Next 1-2 Weeks)

| # | Improvement | Effort | Impact |
|---|------------|--------|--------|
| 7 | Add pre-commit hook for Dockerfile import validation | 4h | Prevent drift at commit time |
| 8 | Create integration test for full prediction flow | 4h | Catch end-to-end breaks |
| 9 | Add automatic model retraining trigger | 8h | Auto-respond to drift |

---

## Detailed Implementation Plans

### 1. Pre-Deployment Import Validation

**Location:** `.pre-commit-hooks/validate_dockerfile_imports.py`

**Logic:**
1. Parse Dockerfile to find `COPY` statements
2. Parse Python files to find `import` statements
3. Verify all imports are satisfiable given the COPY statements
4. Fail if mismatch detected

**Example check:**
```python
# If coordinator.py has: from predictions.worker.data_loaders import ...
# Then Dockerfile must have: COPY predictions/worker/ ...
```

### 2. Startup Import Verification

**Location:** Each service's main entry point

**Logic:**
```python
def verify_imports():
    """Verify all critical imports are available at startup."""
    critical_imports = [
        'predictions.worker.data_loaders',
        'shared.config.gcp_config',
        # ... other critical imports
    ]
    for module in critical_imports:
        try:
            importlib.import_module(module)
        except ImportError as e:
            logger.error(f"CRITICAL: Missing import {module}: {e}")
            raise SystemExit(1)
```

### 3. Graceful Processor Skip

**Location:** `data_processors/analytics/analytics_base.py`

**Change:**
```python
def validate_extracted_data(self):
    if self.raw_data is None or self.raw_data.empty:
        if self._is_same_day_mode():
            logger.info("No data available for same-day processing - skipping gracefully")
            return False  # Signal to skip, not fail
        else:
            raise ValueError("No data extracted")  # Actual failure
    return True
```

### 4. Model Drift Alerting

**Location:** `bin/monitoring/model_drift_alert.py`

**Trigger:** Run daily after grading completes

**Logic:**
```python
# If 2+ consecutive weeks below 55% hit rate:
# - Send Slack alert to #app-error-alerts
# - Create GitHub issue
# - Update monitoring dashboard
```

### 5. Deployment Verification Script

**Location:** `bin/verify-deployment.sh`

**Logic:**
```bash
# After deployment:
# 1. Wait for service to be ready
# 2. Call /health endpoint
# 3. Call a test endpoint that exercises critical code paths
# 4. Check logs for import errors
# 5. Report pass/fail
```

---

## Validation Improvements

### Current Pain Points

1. **Too many manual queries** - Validation skill runs many BQ queries serially
2. **Schema mismatches** - Queries fail due to wrong column names
3. **No single source of truth** - Different tables have different schemas
4. **False positives** - Same-day processing flagged as failures

### Proposed Validation Enhancements

1. **Create validation dashboard view in BigQuery**
   - Single query that returns all key metrics
   - Pre-computed daily, available instantly

2. **Add schema validation to queries**
   - Check column existence before querying
   - Graceful degradation if column missing

3. **Mode-aware validation**
   - Pre-game vs post-game validation modes
   - Different expectations for each mode

4. **Automated validation report**
   - Run after each phase completes
   - Post summary to Slack
   - Only alert on actual issues (not expected states)

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `9ce805ba` | fix: Add missing predictions/worker to coordinator Dockerfile |

---

## Next Steps (Priority Order)

1. **Verify predictions are generating** after coordinator fix
2. **Add startup import verification** to coordinator
3. **Create pre-commit hook** for Dockerfile import validation
4. **Make PlayerGameSummaryProcessor** gracefully skip same-day with no data
5. **Add model drift Slack alerting**

---

## Key Learnings

1. **Deferred imports are dangerous** - Imports inside functions aren't caught by unit tests
2. **Dockerfile changes need validation** - Code changes that affect imports need Dockerfile review
3. **Graceful degradation > exceptions** - Services should handle expected empty states gracefully
4. **Monitoring needs teeth** - Model drift was visible but no alert fired

---

## Files Changed

| File | Change |
|------|--------|
| `predictions/coordinator/Dockerfile` | Added `COPY predictions/worker/` |
| `docs/09-handoff/2026-01-30-SESSION-37-RESILIENCE-PLAN.md` | This document |
