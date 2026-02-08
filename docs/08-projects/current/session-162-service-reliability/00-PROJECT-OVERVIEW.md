# Session 162: Service Reliability Improvements

**Date:** 2026-02-08
**Focus:** Fix recurring deployment/service reliability issues, improve error visibility, prevent regression

---

## Problem Statement

Multiple sessions (101, 102, 128, 159, 160, 161) have discovered the same categories of bugs:
1. **Silent failures** — processors fail but return no error message
2. **Unprotected runtime calls** — `next()`, tuple unpacking crash without context
3. **Validation unit mismatches** — rules don't match processor output units
4. **Missing dependency detection** — Cloud Functions deploy with missing imports
5. **Env var wipe on deploy** — `--set-env-vars` instead of `--update-env-vars`
6. **Model bias measurement artifact** — tiering by `actual_points` creates survivorship bias

---

## Root Cause Analysis

### Why These Keep Happening

| Pattern | Root Cause | Sessions Affected |
|---------|------------|-------------------|
| Silent processor failures | `run()` returns False, caller doesn't extract error | 162 (every Phase 3 debug session) |
| Unprotected `next()` | No default value for empty query results | 162 (UpcomingTeamGameContext) |
| Validation unit mismatch | Rule author assumed fractions, didn't check processor output | 162 (defense zone backfill) |
| Missing dependencies | Transitive imports not tracked in requirements.txt | 161 (PyYAML) |
| Env var wipe | Wrong gcloud flag in build template | 162 (cloudbuild-functions.yaml) |
| Bias measurement artifact | `actual_points` tiering is survivorship bias | 101, 102, 124, 161 |

### Common Theme: No Cross-Checking Between Layers

Every bug above is a **synchronization failure** between two components that should agree:
- Processor output ↔ Validation rules (unit mismatch)
- Method return type ↔ Caller unpacking (tuple bug)
- requirements.txt ↔ actual imports (missing dependency)
- Schema docs ↔ validation thresholds (already said ±15, rule said ±0.30)

---

## Fixes Applied (4 commits)

### Commit 1: `c9a02f4e` — UpcomingTeamGameContext unpack + bias methodology
- **Fix:** `_validate_before_write()` returns `List[Dict]` but caller unpacked as tuple
- **Fix:** `/validate-daily` skill updated to use `season_avg` tiers (4 query sections)

### Commit 2: `ee68ce7a` — Service reliability improvements (3 fixes)
1. **Error visibility:** Processor responses now include error message when `run()` returns False
2. **Protected `next()`:** 3 unprotected `next()` calls in `_validate_after_write` now use `next(iter, None)`
3. **Deploy-time import validation:** `cloudbuild-functions.yaml` validates main.py imports before deploying
4. **Env var fix:** Changed `--set-env-vars` to `--update-env-vars` in Cloud Functions build

### Commit 3: `344b0378` — Defense zone validation unit mismatch
- **Fix:** Changed `vs_league_avg` thresholds from ±0.30 (fractions) to ±15.0 (percentage points)

---

## Prevention Mechanisms Added

### 1. Deploy-Time Import Validation (Cloud Functions)
**File:** `cloudbuild-functions.yaml` Step 1
```yaml
# Installs requirements and tries to import main.py
python -c "import main"  # Fails fast if dependencies missing
```
**Prevents:** PyYAML-type incidents (Session 161)

### 2. Error Messages in Processor Responses
**Files:** `async_orchestration.py`, `main_analytics_service.py`
```python
# Before: {"status": "error"}  (no context)
# After:  {"status": "error", "error": "actual error message"}
```
**Prevents:** Blind debugging through Cloud Logging for every processor failure

### 3. Safe `next()` Pattern
**File:** `bigquery_save_ops.py`
```python
# Before: actual_count = next(count_result).actual_count  # StopIteration crash
# After:  count_row = next(count_result, None)
```
**Prevents:** Silent crashes in post-write validation

---

## Remaining Risks / Future Work

1. **Other `next()` calls** — Search codebase for unprotected `next()` outside analytics
2. **Other validation unit mismatches** — Audit all validation rules against processor output
3. **Pre-commit validation rules test** — Add a test that validates rules against sample processor output
4. **Cloud Function env var audit** — Check if existing functions lost env vars from `--set-env-vars`

---

## Key Lesson

**Always cross-check between layers.** When writing validation rules, test them against actual processor output. When writing callers, check the callee's return type. When writing requirements.txt, trace all transitive imports. The cost of cross-checking is 5 minutes; the cost of not cross-checking is a P1 incident.
