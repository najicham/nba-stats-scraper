# Session 162: Service Reliability Improvements

**Date:** 2026-02-08
**Focus:** Fix recurring deployment/service reliability issues, improve error visibility, prevent regression

---

## Problem Statement

Multiple sessions (101, 102, 128, 159, 160, 161) have discovered the same categories of bugs. Session 162 identified the common pattern: **cross-layer synchronization failures** where two components that should agree on a contract don't.

---

## Bugs Found and Fixed

### 1. Tuple Unpack Mismatch (UpcomingTeamGameContext)

**Contract violation:** `_validate_before_write()` returns `List[Dict]` but caller unpacked as `(valid, invalid)`.

| Component | Expected | Actual |
|-----------|----------|--------|
| `bigquery_save_ops._validate_before_write()` | Returns `List[Dict]` | Returns `List[Dict]` |
| `upcoming_team_game_context_processor.save_analytics()` | Unpacks as 2-tuple | **Mismatch** |
| Other callers (line 208, 2559) | Single assignment | Correct |

**Root cause:** Custom `save_analytics()` override was written without checking the base class method signature.

**Prevention:** This is hard to catch statically without type checking. The real prevention was the error visibility fix (see #4) — making these failures immediately visible instead of requiring Cloud Logging archaeology.

### 2. Unprotected `next()` Calls (_validate_after_write)

**Contract violation:** `next(query_result)` assumes BigQuery always returns at least one row.

| Location | Query Type | Can Return 0 Rows? |
|----------|-----------|---------------------|
| Line 1019 | `SELECT COUNT(*)` | Unlikely but possible (table deleted mid-query) |
| Line 1091 | `SELECT ... NULL checks` | Yes (no matching records) |
| Line 1145 | `SELECT ... anomaly checks` | Yes (table empty or filtered out) |

**Root cause:** `next()` without a default value is an implicit assertion that the iterator is non-empty. Python's `StopIteration` exception is not a standard `Exception` subclass behavior — it silently propagates in unexpected ways.

**Prevention:** Always use `next(iterator, default_value)` in production code. The default protects against empty iterators.

### 3. Validation Unit Mismatch (Defense Zone)

**Contract violation:** Validation rules expected fractions (±0.30) but processor outputs percentage points (±15.0).

| Component | Unit | Range |
|-----------|------|-------|
| Processor: `(zone_pct - league_avg) * 100` | Percentage points | -15 to +15 |
| Schema docs | "percentage points" | -10 to +10 |
| Tests | Percentage points | -15 to +15 |
| **Validation rule** | **Fractions** | **-0.30 to +0.30** |

**Root cause:** Rule author didn't check processor output or schema docs. The comment on the same line said "typically -20 to +20" but the threshold was 0.30.

**Prevention:** Add integration tests that validate rules against sample processor output. Or add a comment convention: `# Unit: percentage_points, Range: -15 to +15, Source: team_defense_zone_analysis_processor.py:1161`

### 4. Silent Error Responses

**Contract violation:** Callers expect error details in HTTP response, but `run()` returning `False` produced `{"status": "error"}` with no message.

| Code Path | Had Error Details? |
|-----------|-------------------|
| `processor.run()` raises exception | Yes: `{"error": str(e)}` |
| `processor.run()` returns `False` | **No: `{"status": "error"}`** |

**Root cause:** Two error paths (exception vs return False) but only one was wired to include details.

**Prevention:** The base class now sets `self.last_error = e`, and both callers extract it.

### 5. Env Var Wipe on Deploy

**Contract violation:** `--set-env-vars` replaces ALL env vars. `--update-env-vars` adds/updates without wiping.

**Root cause:** Wrong gcloud flag. CLAUDE.md already warned about this.

### 6. Model Bias Survivorship Bias

**Contract violation:** Queries tier by `actual_points` (outcome) instead of `season_avg` (identity).

See the handoff doc's "Model Bias: Why It Was Circular Reasoning" section for the full explanation.

---

## Systemic Pattern: Cross-Layer Sync Failures

All 6 bugs follow the same meta-pattern:

```
Component A defines a contract (return type, units, behavior)
Component B assumes a DIFFERENT contract
No automated check verifies they agree
Bug is invisible until runtime
```

**Why this keeps happening:**
1. No compile-time type checking (Python is dynamic)
2. Validation rules written independently from processor code
3. Error paths tested less than success paths
4. GCloud flags have non-obvious destructive defaults

**What we added to break the pattern:**
1. Deploy-time import validation (catches dependency mismatches)
2. Error messages in responses (makes mismatches visible faster)
3. Safe `next()` pattern (eliminates one class of assumption)
4. Updated SKILL.md queries (prevents bias methodology confusion)

---

## Key Lesson

**Always cross-check between layers.** When writing:
- **Validation rules** → test against actual processor output
- **Method callers** → check the callee's return type signature
- **requirements.txt** → trace all transitive imports
- **Analysis queries** → verify the tier methodology isn't circular

The cost of cross-checking is 5 minutes. The cost of not cross-checking is a P1 incident that wastes an entire session to debug.

---

## References

- Handoff: `docs/09-handoff/2026-02-08-SESSION-162-HANDOFF.md`
- Bias methodology: `docs/08-projects/current/session-124-model-naming-refresh/TIER-BIAS-METHODOLOGY.md`
- Session 161 model eval: `docs/08-projects/current/session-161-model-eval-and-subsets/00-PROJECT-OVERVIEW.md`
