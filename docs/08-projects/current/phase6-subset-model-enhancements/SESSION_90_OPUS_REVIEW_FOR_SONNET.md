# Phase 6 Subset Exporters - Opus Code Review for Sonnet

**Date:** 2026-02-03 (Session 90)
**Reviewer:** Claude Opus 4.5
**Status:** Review complete - FIXES REQUIRED before deployment

---

## Executive Summary

I conducted a thorough code review of the Phase 6 subset exporter implementation. The architecture is sound and security measures are well-implemented. However, I found **one critical bug** that must be fixed before deployment.

### Verdict: ⚠️ SAFE TO DEPLOY WITH FIXES

---

## CRITICAL BUG: ROI Calculation is Incorrect

### Severity: CRITICAL - Data Integrity Issue

### Location
- `data_processors/publishing/all_subsets_picks_exporter.py` lines 307-318
- `data_processors/publishing/subset_performance_exporter.py` lines 196-209

### The Bug

The current ROI calculation:

```sql
CASE WHEN wins > 0
  THEN wins * 0.909
  ELSE -(graded_picks - wins)
END
```

This only counts profits on days with wins, but **FAILS to subtract losses within those same days**.

### Proof from Production Data

I ran a verification query comparing the buggy formula vs correct formula:

| Subset | Correct ROI | Buggy ROI | Error |
|--------|-------------|-----------|-------|
| v9_high_edge_any | **+1.1%** | +48.1% | **+47 points** |
| v9_high_edge_warning | **-4.5%** | +45.5% | **+50 points** |
| v9_premium_safe | **+27.3%** | +60.6% | **+33 points** |
| v9_high_edge_top3 | **+11.4%** | +53.0% | **+42 points** |

**The bug inflates reported ROI by 30-50 percentage points.** This is a severe data integrity issue that will mislead users.

### Root Cause Explanation

For a day with 4 wins and 2 losses (6 picks):
- **Expected profit:** `(4 × 0.909) - 2 = +1.636 units`
- **Buggy formula result:** `4 × 0.909 = +3.636 units` (misses the 2 losses!)

The `CASE WHEN wins > 0` condition means:
- When wins > 0: Only counts win profit, ignores losses
- When wins = 0: Correctly counts all as losses

### The Fix

**Replace both occurrences with:**

```sql
-- Correct formula (all in one expression)
SUM(wins * 0.909 - (graded_picks - wins)) as profit_units
```

Or equivalently (simplified):

```sql
SUM(wins * 1.909 - graded_picks) as profit_units
```

### Files to Update

#### File 1: `all_subsets_picks_exporter.py` (lines 307-318)

**BEFORE:**
```python
def _get_subset_performance(self, subset_id: str) -> Dict[str, float]:
    query = """
    SELECT
      ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
      ROUND(
        100.0 * SUM(
          CASE WHEN wins > 0
            THEN wins * 0.909
            ELSE -(graded_picks - wins)
          END
        ) / NULLIF(SUM(graded_picks), 0),
        1
      ) as roi
    FROM `nba_predictions.v_dynamic_subset_performance`
    WHERE subset_id = @subset_id
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    """
```

**AFTER:**
```python
def _get_subset_performance(self, subset_id: str) -> Dict[str, float]:
    query = """
    SELECT
      ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
      ROUND(
        100.0 * SUM(wins * 0.909 - (graded_picks - wins)) / NULLIF(SUM(graded_picks), 0),
        1
      ) as roi
    FROM `nba_predictions.v_dynamic_subset_performance`
    WHERE subset_id = @subset_id
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    """
```

#### File 2: `subset_performance_exporter.py` (lines 196-209)

**BEFORE:**
```python
def _query_window_performance(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    query = """
    SELECT
      subset_id,
      subset_name,
      SUM(graded_picks) as total_picks,
      SUM(wins) as total_wins,
      ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
      ROUND(SUM(
        CASE WHEN wins > 0
          THEN wins * 0.909  -- Win profit (assuming -110 odds)
          ELSE -(graded_picks - wins)  -- Loss
        END
      ), 1) as profit_units,
      ROUND(
        100.0 * SUM(
          CASE WHEN wins > 0
            THEN wins * 0.909
            ELSE -(graded_picks - wins)
          END
        ) / NULLIF(SUM(graded_picks), 0),
        1
      ) as roi_pct
    FROM `nba_predictions.v_dynamic_subset_performance`
    WHERE game_date >= @start_date
      AND game_date <= @end_date
    GROUP BY subset_id, subset_name
    ORDER BY subset_id
    """
```

**AFTER:**
```python
def _query_window_performance(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    query = """
    SELECT
      subset_id,
      subset_name,
      SUM(graded_picks) as total_picks,
      SUM(wins) as total_wins,
      ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
      ROUND(SUM(wins * 0.909 - (graded_picks - wins)), 1) as profit_units,
      ROUND(
        100.0 * SUM(wins * 0.909 - (graded_picks - wins)) / NULLIF(SUM(graded_picks), 0),
        1
      ) as roi_pct
    FROM `nba_predictions.v_dynamic_subset_performance`
    WHERE game_date >= @start_date
      AND game_date <= @end_date
    GROUP BY subset_id, subset_name
    ORDER BY subset_id
    """
```

### Verification Query

After fixing, run this to verify:

```bash
bq query --use_legacy_sql=false "
SELECT
  subset_id,
  SUM(wins) as wins,
  SUM(graded_picks) as picks,
  ROUND(100.0 * SUM(wins * 0.909 - (graded_picks - wins)) / NULLIF(SUM(graded_picks), 0), 1) as correct_roi
FROM nba_predictions.v_dynamic_subset_performance
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY subset_id
ORDER BY correct_roi DESC
"
```

Expected results should show:
- `v9_high_edge_top1`: ~50% ROI (not 70%+)
- `v9_high_edge_warning`: Slightly negative (not 45%+)

---

## Major Issue #2: NULL Team/Opponent Values

### Severity: MAJOR - Bad User Experience

### Location
`all_subsets_picks_exporter.py` lines 186-190

### The Problem

The query uses LEFT JOIN with `player_game_summary`. If a player has a prediction but no matching row (player scratched, game postponed), the output includes NULL values:

```json
{"player": "John Doe", "team": null, "opponent": null, ...}
```

### Recommended Fix

Add a WHERE clause to filter incomplete picks:

```python
# Add after line 194
WHERE pgs.team_abbr IS NOT NULL  -- Only include picks with complete context
```

Or handle in Python when building clean_picks:

```python
# In the loop at line 96
if pick['team'] is None or pick['opponent'] is None:
    logger.warning(f"Skipping pick with missing team/opponent: {pick['player_name']}")
    continue
```

---

## Major Issue #3: N+1 Query Pattern (Performance)

### Severity: MAJOR - Performance Issue

### Location
`all_subsets_picks_exporter.py` line 92

### The Problem

`_get_subset_performance()` is called 9 times in a loop (once per subset), resulting in 9 separate BigQuery queries.

### Recommended Fix

Fetch all subset performance in one query:

```python
def _get_all_subset_performance(self) -> Dict[str, Dict[str, float]]:
    """Get 30-day performance stats for ALL subsets in one query."""
    query = """
    SELECT
      subset_id,
      ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
      ROUND(100.0 * SUM(wins * 0.909 - (graded_picks - wins)) / NULLIF(SUM(graded_picks), 0), 1) as roi
    FROM `nba_predictions.v_dynamic_subset_performance`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    GROUP BY subset_id
    """
    results = self.query_to_list(query)
    return {
        r['subset_id']: {
            'hit_rate': r['hit_rate'] or 0.0,
            'roi': r['roi'] or 0.0
        }
        for r in results
    }
```

Then in `generate_json()`:

```python
# Fetch all performance once at the start
all_performance = self._get_all_subset_performance()

# In the loop, lookup from cache instead of calling _get_subset_performance
stats = all_performance.get(subset['subset_id'], {'hit_rate': 0.0, 'roi': 0.0})
```

---

## Major Issue #4: Security Fallback Exposes Internal ID

### Severity: MAJOR - Security Issue

### Location
`shared/config/subset_public_names.py` lines 25-30

### The Problem

If a new subset is added to the database but not to `SUBSET_PUBLIC_NAMES`, the fallback exposes the internal ID:

```python
return SUBSET_PUBLIC_NAMES.get(subset_id, {
    'id': subset_id,      # SECURITY LEAK: "v9_high_edge_top5"
    'name': subset_id     # SECURITY LEAK
})
```

### Recommended Fix

```python
def get_public_name(subset_id: str) -> dict:
    """Get public name and ID for a subset_id."""
    if subset_id in SUBSET_PUBLIC_NAMES:
        return SUBSET_PUBLIC_NAMES[subset_id]

    # Log warning and return generic placeholder (don't expose internal ID)
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Unknown subset_id '{subset_id}' not in SUBSET_PUBLIC_NAMES - using generic placeholder")
    return {
        'id': 'unknown',
        'name': 'Other'
    }
```

---

## Minor Issue #5: Non-Sequential Public IDs (UX)

### Severity: MINOR - User Experience

### Location
`shared/config/subset_public_names.py` lines 9-19

### The Problem

The public ID assignments result in illogical sort order:

```python
'v9_high_edge_top1': {'id': '1', ...},  # Top Pick
'v9_high_edge_top3': {'id': '7', ...},  # Top 3 - Why 7?
'v9_high_edge_top5': {'id': '2', ...},  # Top 5 - Why 2?
```

When sorted by ID, order is: Top Pick, Top 5, Top 10, Best Value, All Picks, Premium, **Top 3**, Alternative, Best Value Top 5

**Top 3 appears after Premium!**

### Recommended Fix

Renumber for logical grouping:

```python
SUBSET_PUBLIC_NAMES = {
    'v9_high_edge_top1': {'id': '1', 'name': 'Top Pick'},
    'v9_high_edge_top3': {'id': '2', 'name': 'Top 3'},        # Changed from 7
    'v9_high_edge_top5': {'id': '3', 'name': 'Top 5'},        # Changed from 2
    'v9_high_edge_top10': {'id': '4', 'name': 'Top 10'},      # Changed from 3
    'v9_high_edge_balanced': {'id': '5', 'name': 'Best Value'},  # Changed from 4
    'v9_high_edge_any': {'id': '6', 'name': 'All Picks'},     # Changed from 5
    'v9_premium_safe': {'id': '7', 'name': 'Premium'},        # Changed from 6
    'v9_high_edge_warning': {'id': '8', 'name': 'Alternative'},
    'v9_high_edge_top5_balanced': {'id': '9', 'name': 'Best Value Top 5'},
}

# Also update reverse lookup
PUBLIC_ID_TO_SUBSET = {v['id']: k for k, v in SUBSET_PUBLIC_NAMES.items()}
```

---

## Minor Issue #6: Inconsistent Schema for "No Data"

### Severity: MINOR - API Consistency

### Location
`daily_signals_exporter.py` lines 58-70

### The Problem

When no signal data exists, the response includes a `note` field:

```json
{
  "signal": "neutral",
  "note": "No data available for this date"
}
```

But normal responses don't have this field, creating inconsistent schema.

### Recommended Fix

Option A: Always include `note` field (set to `null` normally):
```python
return {
    ...
    'note': None  # Add to normal response
}
```

Option B: Remove `note` and rely on `picks: 0`:
```python
# Just remove 'note' from error response
```

---

## Testing Checklist

### Before Deployment

1. **Fix ROI calculation** (CRITICAL)
2. Run verification query to confirm ROI values are reasonable
3. Run security audit:
   ```bash
   gsutil cat gs://nba-props-platform-api/v1/picks/*.json | \
     grep -iE "(catboost|system_id|subset_id|v9_|confidence|edge|composite)" && \
     echo "LEAK!" || echo "Clean"
   ```
4. Run unit tests: `python bin/test-phase6-exporters.py`
5. Export test date and inspect output manually

### After Deployment

1. Monitor first export cycle
2. Check file sizes (should be 5-50KB for picks)
3. Verify 9 groups present in output
4. Verify no NULL team/opponent values

---

## Summary of Required Changes

### Must Fix Before Deploy (BLOCKING)

| Issue | File | Priority |
|-------|------|----------|
| ROI calculation bug | `all_subsets_picks_exporter.py:307-318` | **CRITICAL** |
| ROI calculation bug | `subset_performance_exporter.py:196-209` | **CRITICAL** |

### Should Fix Before Deploy (RECOMMENDED)

| Issue | File | Priority |
|-------|------|----------|
| NULL team/opponent | `all_subsets_picks_exporter.py:186-194` | MAJOR |
| Security fallback | `subset_public_names.py:25-30` | MAJOR |
| N+1 query pattern | `all_subsets_picks_exporter.py:92` | MAJOR |
| Public ID ordering | `subset_public_names.py:9-19` | MINOR |

### Can Fix Post-Deploy (MINOR)

| Issue | File | Priority |
|-------|------|----------|
| Inconsistent note field | `daily_signals_exporter.py:58-70` | MINOR |
| Hardcoded system_id | All exporters | MINOR |

---

## Deployment Sequence

```
1. Apply ROI calculation fix (both files)
       ↓
2. Apply security fallback fix
       ↓
3. Apply NULL filtering fix
       ↓
4. (Optional) Apply N+1 optimization
       ↓
5. (Optional) Fix public ID ordering
       ↓
6. Run unit tests
       ↓
7. Run ROI verification query
       ↓
8. Export test date locally
       ↓
9. Run security audit
       ↓
10. Deploy to production
       ↓
11. Monitor first export
```

---

## Questions Answered

| Question | Answer |
|----------|--------|
| Safe to deploy? | **Yes, with ROI fix** |
| Single file vs 9 files? | Single file is correct |
| Is "926A" codename safe? | Yes, opaque identifier |
| Cache TTLs appropriate? | Yes (5min/5min/1hr/24hr) |
| Error handling correct? | Yes, continue-on-error |
| Backwards compatible? | Yes, all additive changes |

---

**Please apply the ROI fix first - this is the most critical issue. The current formula reports ROIs that are 30-50 percentage points too high, which is severely misleading.**

Good luck with the fixes! The overall architecture is solid.
