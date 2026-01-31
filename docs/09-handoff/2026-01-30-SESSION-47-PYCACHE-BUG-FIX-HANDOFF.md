# Session 47 Handoff - ProcessPoolExecutor .pyc Cache Bug Fix

**Date:** 2026-01-30
**Duration:** ~30 minutes
**Focus:** Investigate and fix ProcessPoolExecutor producing wrong fatigue_score values

---

## Executive Summary

This session successfully identified and fixed the root cause of the ProcessPoolExecutor bug where `fatigue_score = 0` was written to BigQuery despite the JSON showing `final_score = 100`.

**Root Cause:** Stale `.pyc` bytecode cache files contained old code from before the fatigue_score bugfix. When ProcessPoolExecutor spawned worker processes, Python loaded the cached (incorrect) bytecode instead of the current source.

---

## The Bug

### Symptom
- Parallel run: `fatigue_score = 0`, but `JSON_VALUE(fatigue_context_json, '$.final_score') = 100`
- Serial run: `fatigue_score = 100` (correct)

### Why It Happened

1. The original bug stored `factor_scores['fatigue_score']` (adjustment: -5 to 0) instead of `factor_contexts['fatigue_context_json']['final_score']` (raw score: 0-100)
2. A fix was committed (cec08a99, c475cb9e) that corrected the code
3. **However**, the `.pyc` bytecode cache files were not regenerated
4. Python's normal behavior checks if `.pyc` is newer than `.py` - if so, it uses the cached bytecode
5. ProcessPoolExecutor spawns new Python processes that reimport modules
6. These new processes loaded the stale `.pyc` with the old buggy code

### The Math
For a well-rested player with `fatigue_score = 100`:
- Old code: `factor_scores['fatigue_score'] = (100 - 100) / 20 = 0` ❌
- New code: `factor_contexts['fatigue_context_json']['final_score'] = 100` ✅

---

## Fixes Applied

### 1. Cleared Bytecode Cache

```bash
find /home/naji/code/nba-stats-scraper -name "*.pyc" -type f -delete
find /home/naji/code/nba-stats-scraper -type d -name "__pycache__" -exec rm -rf {} +
```

### 2. Added Bytecode Cache Validation (worker.py)

Added automatic cache validation on module import:

```python
def _validate_bytecode_cache():
    """
    Validate bytecode cache is fresh. If not, clear it.
    """
    # Checks if .py files are newer than .pyc files
    # If stale, removes the .pyc file to force recompilation
```

This runs every time the worker module is imported, including in ProcessPoolExecutor worker processes.

### 3. Added Critical Validation Enforcement (worker.py)

Changed feature validation to FAIL records with critical violations:

```python
if critical_errors:  # e.g., fatigue_score outside 0-100
    return (False, {
        'entity_id': player_lookup,
        'reason': f"Critical feature validation failed: {critical_errors}",
        'category': 'VALIDATION_ERROR'
    })
```

This ensures if the bug ever recurs, it will be immediately detected and records won't be written with bad data.

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/precompute/player_composite_factors/worker.py` | Added bytecode cache validation, strengthened feature validation |

---

## Verification

After fixing, ran parallel backfill:

```sql
SELECT AVG(fatigue_score), MIN(fatigue_score), MAX(fatigue_score),
       COUNTIF(fatigue_score > 0), COUNTIF(fatigue_score = 0)
FROM nba_precompute.player_composite_factors
WHERE game_date = '2026-01-30'
```

Result:
- Average: 91.16 (correct 0-100 scale)
- Min: 78, Max: 100 (all in expected range)
- Zero count: 0 (no buggy values)

---

## Prevention Mechanisms

1. **Bytecode Cache Validation** - Worker module now validates cache freshness on import
2. **Critical Validation Enforcement** - Records with invalid fatigue_score (outside 0-100) now fail instead of just logging
3. **Pre-write Validation** - `_validate_feature_ranges()` catches range violations before BigQuery write

---

## Next Steps

1. **Deploy Phase 4** - The fix is ready for production deployment:
   ```bash
   ./bin/deploy-service.sh nba-phase4-precompute-processors
   ```

2. **Consider PYTHONDONTWRITEBYTECODE** - For development, consider adding to shell profile:
   ```bash
   export PYTHONDONTWRITEBYTECODE=1
   ```
   This disables .pyc caching entirely, avoiding stale bytecode issues.

---

## Key Learnings

1. **ProcessPoolExecutor respawns Python** - Each worker is a fresh process that reimports all modules
2. **Python uses .pyc if newer** - Bytecode cache is used when its timestamp is newer than source
3. **Local dev vs production** - Docker builds always create fresh .pyc from correct source; this was a local dev issue
4. **Validation should FAIL, not just log** - Critical data quality issues should prevent writes, not just log warnings

---

*Session 47 Handoff - 2026-01-30*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
