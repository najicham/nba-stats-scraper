# Master Improvement Plan - Additions & Corrections

**Date:** 2026-01-25
**Purpose:** Additional findings to incorporate into MASTER-IMPROVEMENT-PLAN.md
**Priority:** Review before starting implementation

---

## 1. NEW Critical Bug: Grading Not Running for 3 Games

**Priority:** This should be the FIRST action - fastest win with biggest impact

### The Problem

3 games from Jan 24 have complete boxscores but ZERO grading entries. This is separate from the GSW@MIN missing boxscore issue.

### Evidence

```
| Game             | Boxscore Players | Grading Rows | Status        |
|------------------|------------------|--------------|---------------|
| 20260124_BOS_CHI | 35               | 0            | NOT GRADED    |
| 20260124_CLE_ORL | 34               | 0            | NOT GRADED    |
| 20260124_MIA_UTA | 35               | 0            | NOT GRADED    |
| 20260124_LAL_DAL | 36               | 35           | Graded        |
| 20260124_NYK_PHI | 34               | 47           | Graded        |
| 20260124_WAS_CHA | 35               | 42           | Graded        |
| 20260124_GSW_MIN | 0 (missing)      | 0            | Can't grade   |
```

### Impact

- 362 predictions cannot be graded despite boxscore data existing
- Only 124/486 predictions graded (25.5%)
- This is NOT caused by missing boxscores - the data exists

### Fix (5 minutes)

```bash
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-01-24 --end-date 2026-01-24
```

### Verification Query

```sql
-- Run BEFORE and AFTER to verify fix
SELECT
  game_id,
  COUNT(*) as grading_rows
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = '2026-01-24'
GROUP BY 1
ORDER BY 1;

-- Should show 6 games after fix (not 3)
```

---

## 2. Correction: Auto-Retry Topic Mappings

### Current Plan Says

All 4 topics don't exist.

### Actual Status

| Configured Topic | Actual Status | Correction |
|-----------------|---------------|------------|
| `nba-phase1-scraper-trigger` | DOESN'T EXIST | Use fallback |
| `nba-phase3-analytics-trigger` | DOESN'T EXIST | Use fallback |
| `nba-phase4-precompute-trigger` | DOESN'T EXIST | Use fallback |
| `nba-predictions-trigger` | **EXISTS - WORKS** | Keep as-is |

### Note

`nba-phase3-trigger` and `nba-phase4-trigger` also exist, but they're the main triggers not fallback triggers. Using them for retries could cause issues with normal flow.

### Corrected Fix

```python
# In auto_retry_processor/main.py lines 44-49
PHASE_TOPIC_MAP = {
    'phase_2': 'nba-phase2-fallback-trigger',     # Changed
    'phase_3': 'nba-phase3-fallback-trigger',     # Changed
    'phase_4': 'nba-phase4-fallback-trigger',     # Changed
    'phase_5': 'nba-predictions-trigger',          # KEEP - this one works!
}
```

---

## 3. Update System Health Score

### Current Plan

```
System Health: 7/10 → Target: 9.5/10
```

### Recommended Update

```
System Health: 6/10 → Target: 9.5/10
```

### Rationale

The grading issue (50% of games with data not graded) is a significant degradation that wasn't factored into the original score.

---

## 4. Revised Immediate Action Order

### Recommended Order (by impact/effort ratio)

| # | Action | Time | Impact |
|---|--------|------|--------|
| 1 | Run grading backfill for Jan 24 | 5 min | Recovers 362 predictions |
| 2 | Fix auto-retry topic mappings | 30 min | Enables future resilience |
| 3 | Create fallback subscriptions | 15 min | Enables auto-retry to work |
| 4 | Manual GSW@MIN boxscore backfill | 5 min | Recovers last missing game |
| 5 | Investigate phase execution logging | 30 min | Observability |
| 6 | Deploy game ID mapping view | 5 min | Easier validation |

---

## 5. Additional Quick Reference Query

Add to the Quick Reference section:

```sql
-- Check grading status by game (identifies games with data but no grading)
SELECT
  b.game_id,
  COUNT(DISTINCT b.player_lookup) as boxscore_players,
  COALESCE(pa.graded_count, 0) as graded_players,
  CASE
    WHEN pa.graded_count IS NULL THEN 'NOT GRADED'
    WHEN pa.graded_count < COUNT(DISTINCT b.player_lookup) * 0.5 THEN 'PARTIAL'
    ELSE 'GRADED'
  END as status
FROM `nba-props-platform.nba_raw.bdl_player_boxscores` b
LEFT JOIN (
  SELECT game_id, COUNT(DISTINCT player_lookup) as graded_count
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date = '2026-01-24'
  GROUP BY 1
) pa ON b.game_id = pa.game_id
WHERE b.game_date = '2026-01-24'
GROUP BY 1, pa.graded_count
ORDER BY 1;
```

---

## 6. Future Enhancement: Sync Validation Script

Add to P1 or P2 improvements:

### Problem

`bin/maintenance/sync_shared_utils.py` doesn't detect:
- Missing files that are imported but don't exist in target
- Transitive dependencies (A imports B which imports C)
- New files added to source but not yet synced to targets

This caused the deployment failures fixed on Jan 25.

### Solution Sketch

```python
# Enhancement for sync_shared_utils.py
import ast
from pathlib import Path

def analyze_imports(file_path: Path) -> set[str]:
    """Extract all imports from a Python file using AST."""
    with open(file_path) as f:
        tree = ast.parse(f.read())

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split('.')[0])
    return imports

def find_missing_transitive_deps(source_dir: Path, target_dir: Path) -> list[str]:
    """Find imports in target that reference files not present."""
    missing = []
    for py_file in target_dir.rglob('*.py'):
        imports = analyze_imports(py_file)
        for imp in imports:
            if imp.startswith('shared.'):
                module_path = imp.replace('.', '/') + '.py'
                if not (target_dir / module_path).exists():
                    missing.append(f"{py_file}: imports {imp} (not found)")
    return missing
```

### Files to Modify

- `/bin/maintenance/sync_shared_utils.py`
- `/bin/orchestrators/sync_shared_utils.sh`

---

## 7. Data Status Summary (as of 2026-01-25 ~16:00 UTC)

For reference when validating fixes:

### Jan 24, 2026

| Metric | Value |
|--------|-------|
| Games scheduled (Final) | 7 |
| Games with BDL boxscores | 6 (missing GSW@MIN) |
| Games with NBAC boxscores | 6 (missing GSW@MIN) |
| Games with analytics | 6 |
| Total predictions made | 486 |
| Predictions graded | 124 (25.5%) |
| Games with grading | 3 of 6 with boxscores |
| Feature quality avg | 64.4 (all bronze tier) |

### Jan 23, 2026 (Reference - Fully Recovered)

| Metric | Value |
|--------|-------|
| Games scheduled | 8 |
| Games with boxscores | 8 |
| Games with analytics | 8 |

### Failed Processor Queue

```
| game_date  | processor_name       | status  | retry_count |
|------------|----------------------|---------|-------------|
| 2026-01-24 | nbac_player_boxscore | pending | 0           |
```

Note: retry_count is still 0 because auto-retry keeps failing to publish.

---

## Summary Checklist

Before starting implementation, ensure:

- [ ] Grading backfill added as Priority 1 action
- [ ] Auto-retry fix preserves working `nba-predictions-trigger`
- [ ] System health score updated to 6/10
- [ ] Action order reflects fastest wins first
- [ ] Grading status query added to quick reference

---

*Created: 2026-01-25*
*Reference: docs/09-handoff/2026-01-25-COMPREHENSIVE-SYSTEM-ANALYSIS.md*
