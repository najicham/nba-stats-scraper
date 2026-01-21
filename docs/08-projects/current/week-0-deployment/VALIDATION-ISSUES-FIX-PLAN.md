# Validation Script Issues - Comprehensive Fix Plan

**Created**: 2026-01-20 15:40 UTC
**Status**: Ready for Review
**Context**: Historical validation running, schema investigation complete

---

## Executive Summary

The historical validation script has **3 critical issues** preventing accurate data quality assessment:

1. **Issue #2: Wrong Column Names** - Script uses `analysis_date` for tables that use different columns (HIGH severity)
2. **Issue #3: Wrong Table Names** - Script queries non-existent tables (MEDIUM severity)
3. **Issue #4: Health Score Corruption** - Error marker (-1) corrupts health calculations (HIGH severity)

**Impact**: Current validation results are **UNRELIABLE**. All 378 dates show validation errors that prevent accurate health scoring.

**Recommendation**: Fix Issues #2 and #3 immediately (20 min), then restart validation to get accurate results.

---

## Issue Details & Investigation Results

### Issue #2: Column Name Mismatches ⚠️ HIGH

**What's Wrong:**
The script queries tables with incorrect column names, causing validation errors on EVERY date.

**Schema Investigation Results:**

| Table | Script Queries | Actual Column | Status |
|-------|---------------|---------------|--------|
| `upcoming_player_game_context` | `analysis_date` | `game_date` | ✗ WRONG |
| `player_daily_cache` | `analysis_date` | `cache_date` | ✗ WRONG |
| `player_shot_zone_analysis` | `analysis_date` | `analysis_date` | ✓ Correct |
| `player_composite_factors` | `analysis_date` | `game_date` + `analysis_date` | ? Ambiguous |
| `team_defense_zone_analysis` | `analysis_date` | `analysis_date` | ✓ Correct |

**Error Messages:**
```
Unrecognized name: analysis_date at [1:92]
Unrecognized name: analysis_date at [1:83]
```

**Files Affected:**
- `scripts/validate_historical_season.py:103` - upcoming_context query
- `scripts/validate_historical_season.py:121` - PDC query
- `scripts/validate_historical_season.py:124` - MLFS query (table doesn't exist anyway)

**Impact:**
- Phase 3 validation: 1/3 tables fail (33% error rate)
- Phase 4 validation: 2/5 processors fail (40% error rate)
- Health scores artificially deflated for ALL dates
- Cannot distinguish real data gaps from validation bugs

**Root Cause:**
Script assumes all precompute tables use `analysis_date`, but actual schemas vary:
- Raw data (Phase 2): Uses `game_date` (when game played)
- Analytics (Phase 3): Uses `game_date` (tied to specific games)
- Precompute (Phase 4): Mixed - some use `analysis_date`, some use `cache_date`

**The Fix:**
Update queries to use correct column per table:

```python
# Phase 3 - Line 103
'upcoming_context': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.upcoming_player_game_context` WHERE game_date = '{game_date}'"

# Phase 4 - Line 121
'PDC': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_daily_cache` WHERE cache_date = '{game_date}'",

# Phase 4 - Line 123 (player_composite_factors has BOTH columns)
'PCF': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_composite_factors` WHERE game_date = '{game_date}'"
```

**Fix Complexity:** TRIVIAL (3 line changes)
**Fix Time:** 5 minutes
**Testing:** Re-run on 1-2 dates to confirm queries succeed

---

### Issue #3: Wrong Table Names ⚡ MEDIUM

**What's Wrong:**
Script queries tables that don't exist, causing errors on ALL dates.

**Investigation Results:**

| Table Script Queries | Actual Table Name | Status |
|---------------------|-------------------|--------|
| `bettingpros_player_props` | `bettingpros_player_points_props` | ✗ WRONG NAME |
| `ml_feature_store_v2` | (doesn't exist) | ✗ MISSING |

**Error Messages:**
```
Not found: Table nba-props-platform:nba_raw.bettingpros_player_props
Not found: Table nba-props-platform:nba_precompute.ml_feature_store_v2
```

**Impact:**
- Phase 2 validation: 1/3 scrapers fail (33% error rate)
- Phase 4 validation: 1/5 processors fail (20% error rate)
- False negatives: Data may exist but validation reports -1

**Root Cause:**
1. **BettingPros**: Table was renamed from generic `bettingpros_player_props` to specific `bettingpros_player_points_props`
2. **ML Feature Store**: Table was never created or uses different name (likely feature removed)

**The Fix:**

```python
# Phase 2 - Line 77 - Fix table name
'bettingpros_props': f"SELECT COUNT(DISTINCT player_name) FROM `{self.project_id}.nba_raw.bettingpros_player_points_props` WHERE game_date = '{game_date}'"

# Phase 4 - Line 124 - Remove or make optional
# Option 1: Remove from validation
processors = {
    'PDC': ...,
    'PSZA': ...,
    'PCF': ...,
    # 'MLFS': ...,  # Commented out - table doesn't exist
    'TDZA': ...
}

# Option 2: Check if exists first (more robust)
def table_exists(self, table_ref: str) -> bool:
    try:
        self.bq_client.get_table(table_ref)
        return True
    except Exception:
        return False
```

**Fix Complexity:** TRIVIAL (2 changes)
**Fix Time:** 5 minutes
**Testing:** Verify table name with `bq show` command

---

### Issue #4: Health Score Corruption (NEW) ⚠️ HIGH

**What's Wrong:**
When queries fail, the script sets count to `-1`, which corrupts health score calculations.

**The Problem:**

```python
# Current behavior (Line 93)
except Exception as e:
    logger.warning(f"Error checking {scraper_name} for {game_date}: {e}")
    results[scraper_name] = -1  # Error marker

# Health score calculation (Line 221)
bdl_coverage = validation['phase2'].get('bdl_box_scores', 0) / scheduled
# If bdl_box_scores = -1 and scheduled = 10:
# coverage = -1/10 = -0.1 = -10%
# This artificially lowers health scores!
```

**Impact:**
- Health scores are **unreliable** for any date with query errors
- Cannot trust current validation results for backfill prioritization
- Dates with validation bugs ranked as "worse" than dates with real data gaps
- Makes Issues #2 and #3 even more damaging

**Example:**
- Date with perfect data but 2 validation bugs: 50% health (WRONG)
- Date with missing data but no validation bugs: 70% health
- Backfill plan would incorrectly prioritize the first date

**Root Cause:**
Health score calculation doesn't distinguish between:
- `-1` = validation error (should ignore)
- `0` = no data (should penalize)

**The Fix:**

```python
def calculate_health_score(self, validation: Dict) -> float:
    """Calculate overall health score (0-100)."""
    scores = []

    # Phase 2: Box score coverage
    scheduled = validation['phase2'].get('scheduled_games', 0)
    if scheduled > 0:
        bdl = validation['phase2'].get('bdl_box_scores', 0)
        gamebook = validation['phase2'].get('nbac_gamebook', 0)

        # Skip if validation error (-1)
        if bdl >= 0 or gamebook >= 0:
            bdl_coverage = max(0, bdl) / scheduled
            gamebook_coverage = max(0, gamebook) / scheduled
            scores.append(max(bdl_coverage, gamebook_coverage) * 100)

    # Phase 3: Analytics completion (skip -1 values)
    phase3_valid = [v for v in validation['phase3'].values() if v >= 0]
    if phase3_valid:
        phase3_count = sum(1 for v in phase3_valid if v > 0)
        scores.append((phase3_count / len(phase3_valid)) * 100)

    # Similar fixes for Phase 4, 5, 6...

    return sum(scores) / len(scores) if scores else 0
```

**Fix Complexity:** MEDIUM (update health calculation logic)
**Fix Time:** 10 minutes
**Testing:** Verify health scores make sense for dates with known issues

---

## Fix Priority Matrix

| Issue | Severity | Impact | Fix Time | Priority | Fix Now? |
|-------|----------|--------|----------|----------|----------|
| #2 - Column Names | HIGH | Blocks 40% of validation | 5 min | **P0** | ✅ YES |
| #3 - Table Names | MEDIUM | Blocks 25% of validation | 5 min | **P0** | ✅ YES |
| #4 - Health Score | HIGH | Corrupts all results | 10 min | **P0** | ✅ YES |
| **TOTAL** | - | - | **20 min** | - | **✅ YES** |

---

## Recommended Action Plan

### Option A: Fix Now & Restart Validation (RECOMMENDED)

**Why:**
- Current validation results are unreliable (40% error rate)
- Health scores are corrupted by -1 values
- Backfill plan will be wrong if based on bad data
- Fixes are trivial (20 minutes total)
- Validation has 1 hour remaining (~60/378 dates done, can restart)

**Steps:**
1. ✅ Stop current validation (kill Task bf26ba0)
2. ✅ Fix column names in script (5 min)
3. ✅ Fix table names in script (5 min)
4. ✅ Fix health score calculation (10 min)
5. ✅ Restart validation with fixed script
6. ✅ Get accurate results in ~1.5 hours
7. ✅ Create reliable backfill plan

**Cost:** 20 min fixes + 1.5 hour validation = **~2 hours total**

**Benefit:** Accurate data quality assessment, reliable backfill priorities

---

### Option B: Let Validation Finish, Analyze Patterns, Fix Later

**Why:**
- Current validation will complete in ~1 hour
- Can still identify some patterns despite errors
- Can manually adjust for known validation bugs
- Avoids interrupting running process

**Steps:**
1. ⏳ Let validation finish (~1 hour)
2. 📊 Analyze CSV results (knowing 40% of columns are wrong)
3. 🔍 Manually adjust health scores for validation errors
4. 📝 Document issues for next validation run
5. 🔧 Fix script for future use

**Cost:** 1 hour wait + manual analysis complexity

**Risk:**
- Health scores unreliable for backfill prioritization
- May miss real data quality issues hidden by validation bugs
- Backfill plan may prioritize wrong dates

---

### Option C: Partial Fix & Continue (HYBRID)

**Why:**
- Fix the trivial issues now
- Let current validation finish for pattern analysis
- Re-run full validation tomorrow with all fixes

**Steps:**
1. ⏸️ Let current validation continue in background
2. ✅ Fix script issues in parallel (20 min)
3. ⏳ When current validation finishes: analyze patterns only
4. 🔄 Run fresh validation with fixes tomorrow
5. 📊 Compare results to identify real vs validation issues

**Cost:** 20 min fixes + 1 hour current validation + 1.5 hour new validation = **~3 hours total**

**Benefit:** Get preliminary insights now, accurate data later

---

## Detailed Fix Code

### Fix #1: Column Names (5 min)

**File:** `scripts/validate_historical_season.py`

**Change 1 - Phase 3 upcoming_context (Line 103):**
```python
# BEFORE
'upcoming_context': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.upcoming_player_game_context` WHERE analysis_date = '{game_date}'"

# AFTER
'upcoming_context': f"SELECT COUNT(*) FROM `{self.project_id}.nba_analytics.upcoming_player_game_context` WHERE game_date = '{game_date}'"
```

**Change 2 - Phase 4 PDC (Line 121):**
```python
# BEFORE
'PDC': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_daily_cache` WHERE analysis_date = '{game_date}'",

# AFTER
'PDC': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_daily_cache` WHERE cache_date = '{game_date}'",
```

**Change 3 - Phase 4 PCF (Line 123):**
```python
# BEFORE
'PCF': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_composite_factors` WHERE analysis_date = '{game_date}'",

# AFTER (use game_date since table has both columns)
'PCF': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.player_composite_factors` WHERE game_date = '{game_date}'",
```

---

### Fix #2: Table Names (5 min)

**File:** `scripts/validate_historical_season.py`

**Change 1 - BettingPros table (Line 77):**
```python
# BEFORE
'bettingpros_props': f"SELECT COUNT(DISTINCT player_name) FROM `{self.project_id}.nba_raw.bettingpros_player_props` WHERE game_date = '{game_date}'"

# AFTER
'bettingpros_props': f"SELECT COUNT(DISTINCT player_name) FROM `{self.project_id}.nba_raw.bettingpros_player_points_props` WHERE game_date = '{game_date}'"
```

**Change 2 - Remove ML Feature Store (Line 124):**
```python
# BEFORE
processors = {
    'PDC': f"...",
    'PSZA': f"...",
    'PCF': f"...",
    'MLFS': f"SELECT COUNT(*) FROM `{self.project_id}.nba_precompute.ml_feature_store_v2` WHERE analysis_date = '{game_date}'",
    'TDZA': f"..."
}

# AFTER (remove MLFS)
processors = {
    'PDC': f"...",
    'PSZA': f"...",
    'PCF': f"...",
    # 'MLFS': removed - table doesn't exist
    'TDZA': f"..."
}

# Also update total count (Line 141)
# BEFORE: results['total_count'] = len(processors)  # was 5
# AFTER: results['total_count'] = 4  # or len(processors)
```

---

### Fix #3: Health Score Calculation (10 min)

**File:** `scripts/validate_historical_season.py`

**Replace `calculate_health_score` method (Lines 214-248):**

```python
def calculate_health_score(self, validation: Dict) -> float:
    """Calculate overall health score (0-100), ignoring validation errors (-1)."""
    scores = []

    # Phase 2: Box score coverage (use best available scraper)
    scheduled = validation['phase2'].get('scheduled_games', 0)
    if scheduled > 0:
        bdl = validation['phase2'].get('bdl_box_scores', 0)
        gamebook = validation['phase2'].get('nbac_gamebook', 0)

        # Only calculate if we have valid data (not -1)
        valid_scrapers = [s for s in [bdl, gamebook] if s >= 0]
        if valid_scrapers:
            best_coverage = max(valid_scrapers) / scheduled
            scores.append(best_coverage * 100)

    # Phase 3: Analytics completion (ignore -1 values)
    phase3_valid = [v for v in validation['phase3'].values() if v >= 0]
    if phase3_valid:
        completed = sum(1 for v in phase3_valid if v > 0)
        scores.append((completed / len(phase3_valid)) * 100)

    # Phase 4: Processor completion (ignore -1 values)
    phase4_valid = {k: v for k, v in validation['phase4'].items()
                    if k not in ['completed_count', 'total_count'] and v >= 0}
    if phase4_valid:
        completed = sum(1 for v in phase4_valid.values() if v > 0)
        scores.append((completed / len(phase4_valid)) * 100)

    # Phase 5: Predictions exist
    if validation['phase5']['total_predictions'] > 0:
        scores.append(100)
    elif validation['phase5']['total_predictions'] == 0:
        scores.append(0)
    # If -1, skip (validation error)

    # Phase 6: Grading coverage
    predictions = validation['phase5']['total_predictions']
    graded = validation['phase6']['total_graded']
    if predictions > 0 and graded >= 0:  # Valid data
        grading_coverage = (graded / predictions) * 100
        scores.append(grading_coverage)
    elif predictions == 0:
        scores.append(0)  # No predictions to grade
    # If graded == -1, skip (validation error)

    return sum(scores) / len(scores) if scores else 0
```

---

## Testing Plan

### After Fixes Applied:

**Test 1: Column Name Fixes**
```bash
# Test on recent date (should have all tables)
python scripts/validate_historical_season.py --start 2025-01-15 --end 2025-01-15

# Expected: No "Unrecognized name: analysis_date" errors
# Expected: All Phase 3/4 queries succeed
```

**Test 2: Table Name Fixes**
```bash
# Check logs for table not found errors
# Expected: No "Not found: Table" errors for bettingpros or mlfs
```

**Test 3: Health Score Accuracy**
```bash
# Manually verify health score for known date
# Example: Date with perfect data should score ~95-100%
# Example: Date with known gaps should score proportionally
```

---

## Decision Time

**Question for User:**

Which option do you prefer?

**Option A (RECOMMENDED)**:
- ✅ Stop validation now
- ✅ Fix all 3 issues (20 min)
- ✅ Restart validation
- ✅ Get accurate results in ~2 hours total
- ✅ Reliable backfill plan today

**Option B**:
- ⏳ Let validation finish (~1 hour)
- ⚠️ Analyze results with known 40% error rate
- ⚠️ Manually adjust for validation bugs
- 📝 Document for future use
- ⏰ Fix & re-run later

**Option C (HYBRID)**:
- ⏸️ Let current validation finish in background
- ✅ Fix script in parallel
- 📊 Analyze patterns from flawed data
- 🔄 Re-run tomorrow with fixes
- ⏰ ~3 hours total

---

**My Recommendation**: **Option A** - Fix now and restart

**Reasoning:**
1. Fixes are trivial (20 min total)
2. Only 16% of validation complete (60/378 dates)
3. Current results are unreliable for backfill decisions
4. Better to get accurate data once than analyze flawed data twice
5. Total time investment is similar (2 hours vs 3 hours for Option C)

What would you like to do?

---

**Status**: Waiting for decision
**Next Steps**: Based on chosen option
