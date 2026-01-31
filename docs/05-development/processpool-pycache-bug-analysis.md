# ProcessPoolExecutor .pyc Cache Bug Analysis

**Date:** 2026-01-30
**Investigated by:** Session 47
**Status:** Root cause identified, fix implemented

---

## Problem Statement

The `PlayerCompositeFactorsProcessor` was producing incorrect `fatigue_score = 0` values when using `ProcessPoolExecutor` for parallel processing, but correct `fatigue_score = 100` values when using serial processing.

**Key observation:** The JSON field `fatigue_context_json` contained the correct value (`final_score = 100`), but the extracted column `fatigue_score` had the wrong value (`0`).

---

## Root Cause

### The Bug
Stale `.pyc` bytecode cache files contained old code from **before** the fatigue_score bugfix (commits cec08a99, c475cb9e).

### How Python Bytecode Caching Works

1. When Python imports a module, it compiles `.py` to bytecode
2. Python caches this bytecode in `__pycache__/*.pyc` files
3. On subsequent imports, Python checks: **is `.pyc` newer than `.py`?**
4. If yes, Python uses the cached bytecode (faster startup)
5. If no, Python recompiles from source

### Why ProcessPoolExecutor Was Affected

```
Main Process                    Worker Process (spawned)
─────────────                   ─────────────────────────
1. Import worker.py             1. Fresh Python interpreter starts
2. (may use cached .pyc)        2. Import worker.py
3. Submit tasks                 3. Python checks: .pyc newer than .py?
4. Receive results              4. YES → Use cached (STALE) bytecode
                                5. Execute OLD buggy code
                                6. Return wrong values
```

The main process and worker processes can use **different** bytecode if:
- The `.pyc` was generated before a code fix
- The `.pyc` timestamp is newer than the `.py` timestamp (edge case)
- File system timestamp issues (NFS, Docker volumes, etc.)

### The Specific Bug

**Old code (in stale .pyc):**
```python
'fatigue_score': factor_scores['fatigue_score'],  # Returns adjustment: -5 to 0
```

**New code (in current .py):**
```python
'fatigue_score': factor_contexts['fatigue_context_json']['final_score'],  # Returns raw score: 0-100
```

For a well-rested player with raw score = 100:
- Adjustment = `(100 - 100) / 20 = 0`
- Old code stored: `0` ❌
- New code stores: `100` ✅

---

## Evidence

### Debug Logging Added

```python
# In worker subprocess
print(f"DEBUG WORKER [{player_lookup}]: factor.name={factor.name}, "
      f"adjustment={score}, context_final_score={context.get('final_score')}")
```

### Results After Clearing Cache

```
DEBUG WORKER [zionwilliamson]: factor.name=fatigue_score, adjustment=0.0, context_final_score=100
DEBUG WORKER [zionwilliamson]: FINAL record['fatigue_score']=100
WARNING: DEBUG MAIN [zionwilliamson]: received fatigue_score=100
```

All values correct after clearing `.pyc` files.

---

## Fixes Implemented

### 1. Immediate Fix: Clear Bytecode Cache

```bash
find /home/naji/code/nba-stats-scraper -name "*.pyc" -type f -delete
find /home/naji/code/nba-stats-scraper -type d -name "__pycache__" -exec rm -rf {} +
```

### 2. Automatic Cache Validation (worker.py)

Added function that runs on module import:

```python
def _validate_bytecode_cache():
    """Remove stale .pyc files if source is newer."""
    module_dir = Path(__file__).parent
    for pycache in [module_dir / "__pycache__", module_dir / "factors" / "__pycache__"]:
        if pycache.exists():
            for pyc_file in pycache.glob("*.pyc"):
                py_name = pyc_file.stem.split('.')[0] + ".py"
                py_file = pycache.parent / py_name
                if py_file.exists() and py_file.stat().st_mtime > pyc_file.stat().st_mtime:
                    logger.warning(f"Stale bytecode: {pyc_file.name}. Removing.")
                    pyc_file.unlink()

# Run on import
_validate_bytecode_cache()
```

### 3. Critical Validation Enforcement (worker.py)

Changed feature validation to FAIL records with critical violations:

```python
if critical_errors:  # e.g., fatigue_score outside 0-100
    return (False, {
        'entity_id': player_lookup,
        'reason': f"Critical feature validation failed: {critical_errors}",
        'category': 'VALIDATION_ERROR'
    })
```

---

## Prevention Strategies

### Option 1: Disable Bytecode Caching (Development)

**Pros:** Eliminates the problem entirely
**Cons:** Slower imports (~10-20% slower startup)

```bash
# Add to ~/.bashrc or ~/.zshrc
export PYTHONDONTWRITEBYTECODE=1

# Or use Python flag
python -B script.py
```

### Option 2: Use `importlib.invalidate_caches()`

**Pros:** Forces Python to recheck all caches
**Cons:** Must be called before imports

```python
import importlib
importlib.invalidate_caches()

from .worker import _process_single_player_worker
```

### Option 3: Force Fresh Imports in Worker

**Pros:** Guarantees worker uses current code
**Cons:** Slower worker startup

```python
def _process_single_player_worker(...):
    import importlib
    import sys

    # Remove cached modules
    for mod_name in list(sys.modules.keys()):
        if 'player_composite_factors' in mod_name:
            del sys.modules[mod_name]

    # Force fresh import
    from .factors import ACTIVE_FACTORS, DEFERRED_FACTORS
```

### Option 4: Use ThreadPoolExecutor Instead

**Pros:** Threads share memory space, no reimport needed
**Cons:** GIL limits true parallelism for CPU-bound work

```python
# Current (problematic with stale cache)
with ProcessPoolExecutor(max_workers=32) as executor:
    ...

# Alternative (no reimport, but GIL-limited)
with ThreadPoolExecutor(max_workers=32) as executor:
    ...
```

### Option 5: Version Check in Worker (Recommended)

**Pros:** Explicit validation, clear error message
**Cons:** Requires manual version bump on changes

```python
# In worker.py
_WORKER_CODE_VERSION = "v2_fatigue_fix"

def _process_single_player_worker(..., expected_version: str):
    if expected_version != _WORKER_CODE_VERSION:
        raise RuntimeError(
            f"Worker code version mismatch! Expected {expected_version}, "
            f"got {_WORKER_CODE_VERSION}. Clear __pycache__ and retry."
        )
```

### Option 6: Pre-commit Hook to Clear Cache

**Pros:** Automatic, no manual intervention
**Cons:** Clears cache even when not needed

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: clear-pycache
      name: Clear Python bytecode cache
      entry: bash -c 'find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true'
      language: system
      pass_filenames: false
      always_run: true
```

### Option 7: Docker Build Always Fresh (Production)

In production, Docker builds create fresh `.pyc` from the correct source:

```dockerfile
# Dockerfile
COPY . /app
RUN python -m compileall /app  # Creates fresh .pyc from current source
```

This is why the bug only manifested in local development, not production.

---

## Recommended Approach

### For Development

1. **Add to shell profile:**
   ```bash
   export PYTHONDONTWRITEBYTECODE=1
   ```

2. **Add cache validation to critical worker modules** (already done for `worker.py`)

3. **Use pre-commit hook** to clear cache on commits

### For Production

1. **Docker builds are safe** - always compile from fresh source

2. **Add version check** for critical multiprocessing workers

3. **Fail-fast validation** - reject records with invalid values (already done)

---

## Testing the Fix

### Verify Parallel Processing Works

```bash
# Run with parallelization enabled
PYTHONPATH=/home/naji/code/nba-stats-scraper \
ENABLE_PLAYER_PARALLELIZATION=true \
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
--dates="2026-01-30"
```

### Verify Results in BigQuery

```sql
SELECT
  AVG(fatigue_score) as avg_fatigue,
  MIN(fatigue_score) as min_fatigue,
  MAX(fatigue_score) as max_fatigue,
  COUNTIF(fatigue_score = 0) as zero_count
FROM nba_precompute.player_composite_factors
WHERE game_date = '2026-01-30'
```

Expected:
- `avg_fatigue` ~ 90 (0-100 scale)
- `min_fatigue` >= 50 (rare to have extremely fatigued players)
- `max_fatigue` = 100 (well-rested players)
- `zero_count` = 0 (no buggy values)

---

## Lessons Learned

1. **ProcessPoolExecutor spawns fresh Python processes** that reimport all modules independently

2. **Python bytecode caching is usually helpful** but can cause subtle bugs when code changes aren't reflected in cache

3. **Validation should FAIL, not just log** - critical data quality issues should prevent bad data from being written

4. **JSON storage provides debugging trail** - the `fatigue_context_json` field showed the correct value even when the column was wrong

5. **Local dev differs from production** - Docker builds create fresh bytecode, so this bug wouldn't appear in production

---

## Related Files

- `data_processors/precompute/player_composite_factors/worker.py` - Worker with cache validation
- `data_processors/precompute/player_composite_factors/factors/fatigue_factor.py` - Fatigue calculation
- `docs/09-handoff/2026-01-30-SESSION-47-PYCACHE-BUG-FIX-HANDOFF.md` - Session handoff

---

*Document created: 2026-01-30*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
