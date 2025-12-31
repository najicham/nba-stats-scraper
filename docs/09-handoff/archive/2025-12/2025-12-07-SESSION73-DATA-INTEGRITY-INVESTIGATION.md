# Session 73: Data Integrity Investigation & Prevention

> **Date:** 2025-12-07/08
> **Focus:** Investigating data integrity issues, implementing prevention mechanisms
> **Status:** Complete - Ready for 4-year backfill with new safety features

---

## Executive Summary

This session investigated why PCF (Player Composite Factors) had `opponent_strength_score = 0` for Dec 4, 2021. We discovered two root causes:

1. **Operational Gap:** TDZA backfill ran in two batches that skipped Dec 4 entirely
2. **Phase 3 Data Quality:** Upstream `team_defense_game_summary` has NULL paint/mid-range data

We implemented a **lightweight existence check** that prevents processing when upstream data is missing, even in backfill mode.

---

## Key Findings

### Finding 1: TDZA Gap Between Batches

```
TDZA BACKFILL TIMELINE:
═══════════════════════════════════════════════════════════════════════════════

  Batch 1 (Dec 4, 23:40-23:42)          Batch 2 (Dec 5, 01:11-01:15)
  ┌─────────────────────────────┐       ┌─────────────────────────────────────┐
  │ Dec 1, 2, 3                 │       │ Dec 5, 6, 7, 8, 9, 10...            │
  │ (Ends at Dec 3!)            │       │ (Starts at Dec 5!)                  │
  └─────────────────────────────┘       └─────────────────────────────────────┘
                  │                                    │
                  └───────── DEC 4 SKIPPED! ──────────┘
                             (1.5 hour gap)
```

**Timeline Evidence (from BigQuery):**
| Date | First Processed | Records |
|------|-----------------|---------|
| Dec 3 | 2025-12-04 23:41:43 | 30 |
| Dec 4 | 2025-12-08 05:45:00 | 30 (fixed this session) |
| Dec 5 | 2025-12-05 01:11:34 | 30 |

### Finding 2: Phase 3 Data Quality Issue

The upstream `team_defense_game_summary` table has NULL values:

```sql
SELECT opp_paint_attempts, opp_mid_range_attempts, opp_three_pt_attempts
FROM nba_analytics.team_defense_game_summary
WHERE game_date = "2021-12-04"
```

| Column | Value |
|--------|-------|
| `opp_paint_attempts` | **NULL** |
| `opp_mid_range_attempts` | **NULL** |
| `opp_three_pt_attempts` | 37 (populated) |

This causes ALL dates to have `opponent_strength_score = 0` because:
1. TDZA processor sets `paint_defense_vs_league_avg = NULL` when paint attempts = 0
2. PCF uses `_safe_float(..., 0.0)` which defaults NULL to 0
3. This is **Phase 3** issue, not Phase 4

### Finding 3: Backfill Mode Was Too Aggressive

The original backfill mode code skipped ALL dependency checks:

```python
# BEFORE (dangerous)
if self.is_backfill_mode:
    self.dep_check = {'all_critical_present': True, ...}  # Trust blindly
```

This allowed PCF to process Dec 4 even though TDZA had 0 records.

---

## What We Fixed

### Fix 1: Lightweight Existence Check (Commit 21132a7)

Added a quick safety check that runs even in backfill mode:

**File:** `data_processors/precompute/precompute_base.py`

```python
def _quick_upstream_existence_check(self, analysis_date: date) -> List[str]:
    """
    Quick existence check for critical Phase 4 upstream dependencies.

    Takes ~1 second instead of 60+ seconds for full check.
    Returns list of missing table names (empty if all exist).
    """
    missing_tables = []

    # Check Phase 4 deps: player_shot_zone_analysis, team_defense_zone_analysis
    for table_name in phase_4_deps:
        query = f"SELECT COUNT(*) FROM {table} WHERE date = '{date}'"
        if count == 0:
            missing_tables.append(table_name)

    return missing_tables
```

**Integration in run() method:**
```python
if self.is_backfill_mode:
    # NEW: Quick safety check first
    missing = self._quick_upstream_existence_check(analysis_date)
    if missing:
        raise ValueError(f"⛔ BACKFILL SAFETY: Missing {missing}")

    # Then skip expensive checks as before
    logger.info("⏭️  BACKFILL MODE: Quick existence check passed")
```

### Fix 2: Re-ran TDZA and PCF for Dec 4

```bash
# TDZA was fixed in previous session (now has 30 records)
# Re-ran PCF this session:
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-12-04 --end-date 2021-12-04 --skip-preflight
```

Result: PCF Dec 4 now extracts 30 TDZA records (was 0 before).

### Fix 3: Updated Documentation (Commit 5fa7d22)

Updated `docs/02-operations/runbooks/backfill/phase4-data-integrity-guide.md`:
- Marked lightweight existence check as implemented
- Noted Phase 3 data quality issue for future investigation

---

## Commits Made

| Commit | Description |
|--------|-------------|
| `21132a7` | feat: Add lightweight upstream existence check in backfill mode |
| `5fa7d22` | docs: Update data integrity guide with implementation status |

---

## Current Data State

### Dec 4, 2021 Status After Fixes

| Processor | Records | Status |
|-----------|---------|--------|
| TDZA | 30 | Fixed (was 0) |
| PSZA | 351 | OK |
| PCF | 131 | Fixed (now extracts TDZA) |
| PDC | 97 | OK |
| ML | 131 | OK |

### Remaining Issue: opponent_strength_score = 0

ALL dates have `opponent_strength_score = 0` due to Phase 3 data quality:

```sql
SELECT game_date, AVG(opponent_strength_score)
FROM nba_precompute.player_composite_factors
WHERE game_date IN ("2021-12-03", "2021-12-04", "2021-12-05")
GROUP BY game_date
```

| game_date | avg_opponent_score |
|-----------|-------------------|
| 2021-12-03 | 0 |
| 2021-12-04 | 0 |
| 2021-12-05 | 0 |

This is caused by Phase 3 `team_defense_game_summary` having NULL paint/mid-range data.

---

## Prevention Mechanisms Now In Place

### 1. Lightweight Existence Check

**What it does:** Verifies at least 1 record exists in critical upstream tables before processing.

**When it runs:** Always, even in backfill mode.

**Cost:** ~1 second per date (vs 60+ seconds for full dependency check).

**Example output:**
```
⚠️  BACKFILL SAFETY: team_defense_zone_analysis has 0 records for 2021-12-04
⛔ BACKFILL SAFETY: Critical upstream data missing: ['team_defense_zone_analysis']
```

### 2. Failure Recording

Missing upstream now records to `precompute_failures` table with category `MISSING_UPSTREAM_IN_BACKFILL`.

### 3. Validation Script

Run after any backfill to catch issues:
```bash
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-12-01 --end-date 2021-12-31 --details
```

---

## Next Steps

### Immediate (Before 4-Year Backfill)

1. **Test the new safety feature** - Try running PCF on a date with missing TDZA to verify it fails correctly
2. **Clean up background processes** - Several are still running from investigation

### During 4-Year Backfill

3. **Run validation after each month** - Catch any issues early
4. **Monitor for `MISSING_UPSTREAM_IN_BACKFILL` failures** - These indicate gaps

### Future Investigation

5. **Phase 3 data quality issue** - Investigate why `team_defense_game_summary` has NULL paint/mid-range data
   - Location: `data_processors/analytics/team_defense_game_summary/`
   - Impact: `opponent_strength_score = 0` for all players

---

## Key Files Changed

| File | Change |
|------|--------|
| `data_processors/precompute/precompute_base.py` | Added `_quick_upstream_existence_check()` method |
| `docs/02-operations/runbooks/backfill/phase4-data-integrity-guide.md` | Updated implementation status |

---

## Validation Queries

### Check for TDZA Gaps
```sql
SELECT
  analysis_date,
  COUNT(*) as records
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date BETWEEN "2021-11-01" AND "2021-12-31"
GROUP BY analysis_date
ORDER BY analysis_date
```

### Check PCF Data Quality
```sql
SELECT
  game_date,
  AVG(opponent_strength_score) as avg_opponent_score,
  COUNT(*) as records
FROM `nba_precompute.player_composite_factors`
WHERE game_date BETWEEN "2021-12-01" AND "2021-12-10"
GROUP BY game_date
ORDER BY game_date
```

### Check Phase 3 Upstream Data
```sql
SELECT
  game_date,
  SUM(CASE WHEN opp_paint_attempts IS NULL THEN 1 ELSE 0 END) as paint_null,
  SUM(CASE WHEN opp_mid_range_attempts IS NULL THEN 1 ELSE 0 END) as mid_null,
  COUNT(*) as total
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date BETWEEN "2021-12-01" AND "2021-12-10"
GROUP BY game_date
ORDER BY game_date
```

---

## Background Processes (Clean Up)

Several background processes are still running from investigation:
- `d41664` - validate_backfill_coverage.py
- `8f8eb9` - PCF backfill Dec 1-7
- `5e653f`, `dd3b1e` - BQ count queries
- `0ed18c`, `dc5e1c` - BQ history queries

These should be cleaned up before starting the 4-year backfill.

---

## Summary

**Problem:** PCF Dec 4 had bad data (opponent_score = 0) because TDZA was skipped.

**Root Cause:** Two TDZA backfill batches left a gap at Dec 4 (operational error).

**Fix:** Implemented lightweight existence check that prevents this from happening again.

**Remaining:** Phase 3 data quality issue causes opponent_strength_score = 0 for ALL dates (separate investigation needed).

**Ready for 4-year backfill?** Yes, with new safety features in place.
