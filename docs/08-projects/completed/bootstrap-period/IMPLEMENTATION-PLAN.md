# Bootstrap Period - Implementation Plan

**Date:** 2025-11-27
**Status:** Ready for Implementation
**Approach:** Option A (Current-Season-Only) with Partial Window Support
**Estimated Effort:** 12-15 hours

---

## Executive Summary

This document outlines the complete implementation plan for Option A bootstrap period handling, including answers to critical design questions about partial windows, historical data usage, and ML training.

**Key Decisions:**
1. **Skip first 7 days** of regular season (no predictions Oct 25 - Nov 1)
2. **Use partial windows** after day 7 (e.g., L30 with only 10 games available)
3. **Add metadata fields** to track games_used for each rolling window
4. **Current-season-only** for ALL inference features
5. **All historical seasons** for ML model training
6. **Historical data considerations** documented for future fatigue/rest pattern work

---

## Critical Design Questions Answered

### Q1: What to do with "last 30 game average" when only 7 games available?

**ANSWER: Use available games with metadata (NOT NULL)**

**Implementation:**
```python
# Calculate rolling average using min_periods=1
points_avg_last_30 = player_games['points'].rolling(30, min_periods=1).mean()

# Track how many games were actually used
games_used = min(len(player_games), 30)
quality_score = games_used / 30.0  # 7/30 = 0.23

# Store with metadata
{
    'points_avg_last_30': 18.5,           # Value from 7 games
    'points_avg_last_30_games_used': 7,   # NEW field - how many games
    'feature_quality_score': 0.23,         # Low quality score
    'early_season_flag': False,            # Not early season (past day 7)
    'insufficient_data_reason': 'partial_window_L30_7_of_30_games'
}
```

**Rationale:**
- ML model can use the signal (18.5 is better than NULL)
- Model sees quality_score=0.23 and learns to weight appropriately
- During training, model learned from many partial window examples
- Gradual degradation is better than binary NULL

**Schema Impact:**
- Add `{feature}_games_used` fields for each rolling window
- Keep existing `feature_quality_score` calculation
- Update `insufficient_data_reason` to be more granular

---

### Q2: Should we use historical seasons for fatigue/rest patterns?

**ANSWER: Current-season-only for now, defer historical patterns to Week 4+**

**Two Types of Fatigue Metrics:**

#### Type A: Recent Fatigue (Current Season Only) ✅ Implement Now
```python
# These are about THIS season's workload
'games_in_last_7_days': 4,     # Current season only
'is_back_to_back': True,        # Today's context
'days_rest': 1,                 # Since last game
'minutes_in_last_14_days': 520  # Current season only
```

**Rationale:** Recent schedule density is seasonal, not historical

#### Type B: Rest Patterns (Historical) ⚠️ Defer to Future
```python
# "How does LeBron perform on 3 days rest vs 1 day rest?"
# This is a PATTERN that might be stable across seasons
'points_avg_on_3_days_rest': ???  # Defer - team change problem applies!
```

**The Team Change Problem:**
- 24% of players change teams each season
- Historical rest patterns invalidated by role changes
- Example: 6th man averaging 15 pts on 3 days rest → Starter averaging 22 pts
- Cross-season rest patterns are misleading without team-change tracking

**Future Implementation (Week 4+):**
If adding historical rest patterns:
1. Track team changes (use query from comprehensive-testing-plan.md)
2. Add `cross_season_data_used: bool` flag
3. Add `same_team_as_prior_season: bool` flag
4. Weight down cross-season patterns (0.5x? 0.7x? test it)
5. A/B test if it improves accuracy

**For Now:** Skip it. Current-season rest patterns are 80% of the value.

---

### Q3: Should ML training use historical seasons?

**ANSWER: YES! Training uses ALL seasons, inference uses current-season features**

**This is DIFFERENT from inference!**

#### Training (Use ALL historical data 2021-2025) ✅
```python
# When training the XGBoost model
train_data = query("""
  SELECT features, actual_points
  FROM ml_feature_store_v2
  WHERE game_date BETWEEN '2021-10-19' AND '2024-04-15'  -- Multiple seasons!
    AND is_production_ready = TRUE
""")

model.fit(train_data.features, train_data.actual_points)
```

**Why use all seasons for training:**
- Need large dataset (100k+ predictions) to learn patterns
- Model learns from early season examples across multiple seasons
- Model learns "when games_used=7 for L30, this is how reliable it is"
- Model learns team change patterns, rest patterns, all patterns
- Model learns to handle NULL values, partial windows, quality scores

#### Inference (Use current-season features) ✅
```python
# When making prediction for today's game
features = get_features(player='LeBron', game_date='2025-11-28')
# features contains current-season L30 (calculated from 10 games available)
# features contains quality_score, games_used, etc.

prediction = model.predict(features)  # Model knows how to handle partial data!
```

**Key Insight:**
- **Training**: Learn from everything (cross-season helps model understand patterns)
- **Inference**: Use current-season data (but model learned how to handle it)
- **Model learns context**: "quality_score=0.23 means less reliable" from training data

---

## Summary Table: What Uses Historical Data?

| Data Type | Use Historical? | Reasoning |
|-----------|----------------|-----------|
| **Recent form (L5, L10, L30)** | ❌ Current season only | Team changes invalidate (per investigation) |
| **Rolling averages** | ❌ Current season only | Use available games with quality metadata |
| **Season averages** | ❌ Current season only | By definition, season-to-date |
| **Rest/fatigue (recent)** | ❌ Current season only | Schedule density is seasonal |
| **Rest patterns (historical)** | ⚠️ Maybe later (Week 4+) | Could add with team-change tracking |
| **Matchup history** | ⚠️ Maybe later (Week 4+) | "LeBron vs Warriors" might be stable |
| **ML model training** | ✅ YES, all seasons! | Need volume to learn patterns |
| **ML model inference** | ❌ Current season features | But model learned from historical data |

---

## Implementation Checklist

### Phase 1: Documentation Updates (This file + updates) - 2 hours

- [x] Create IMPLEMENTATION-PLAN.md (this file)
- [ ] Update 2025-11-27-bootstrap-period-handoff.md with Q&A section
- [ ] Update EXECUTIVE-SUMMARY.md with partial window decision
- [ ] Update README.md with link to implementation plan

### Phase 2: Configuration Updates - 1 hour

**File:** `shared/config/nba_season_dates.py`

**Updates needed:**
1. Add missing season dates (especially 2021 epoch)
2. Verify accuracy of existing dates against handoff doc
3. Update default threshold from 14 days → 7 days

**Changes:**
```python
# Add 2021 epoch and verify dates
SEASON_START_DATES = {
    2024: date(2024, 10, 23),  # Verify: handoff says 10-23
    2023: date(2023, 10, 25),  # Verify: handoff says 10-25 (currently 10-24!)
    2022: date(2022, 10, 18),  # Matches handoff
    2021: date(2021, 10, 19),  # ADD: Epoch date from handoff
}

# Update default threshold
def is_early_season(analysis_date: date, season_year: int, days_threshold: int = 7):
    # Changed from 14 → 7 days based on investigation
```

### Phase 3: Schema Updates - 2 hours

#### 3.1 Player Daily Cache Schema

**File:** `schemas/bigquery/precompute/player_daily_cache.sql`

**Add after line 41 (after `games_played_season`):**
```sql
-- ============================================================================
-- ROLLING WINDOW METADATA - Track actual games used (3 fields)
-- Added for bootstrap period partial window support
-- ============================================================================
points_avg_last_5_games_used INT64,     -- How many games used for L5 (out of 5)
points_avg_last_10_games_used INT64,    -- How many games used for L10 (out of 10)
points_avg_season_games_used INT64,     -- Same as games_played_season (for consistency)
```

**Rationale:**
- Enables quality scoring: quality = games_used / window_size
- Allows model to learn reliability of partial windows
- Minimal schema change (3 INT64 fields)

#### 3.2 ML Feature Store V2 Schema

**File:** `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`

**Current state:** Already has fields we need!
- ✅ `early_season_flag BOOLEAN` (line 76)
- ✅ `insufficient_data_reason STRING` (line 77)
- ✅ `feature_quality_score NUMERIC(5,2)` (line 30)

**Updates needed:**
1. Update comment on line 77 to include partial window reasons:
```sql
insufficient_data_reason STRING,  -- Why data was insufficient OR partial
                                   -- Examples: 'early_season', 'partial_window_L30_7_of_30_games'
```

2. Add note about feature-level metadata (no schema change, just comment):
```sql
-- NOTE: Individual feature quality tracked via player_daily_cache.{feature}_games_used
-- Overall feature_quality_score aggregates across all features
```

**No schema changes needed!** Existing fields support our approach.

#### 3.3 Other Precompute Schemas

**Files:**
- `schemas/bigquery/precompute/player_shot_zone_analysis.sql`
- `schemas/bigquery/precompute/team_defense_zone_analysis.sql`
- `schemas/bigquery/precompute/player_composite_factors.sql`

**Changes:** None needed. These already have:
- `early_season_flag BOOLEAN`
- `insufficient_data_reason STRING`
- Completeness metadata fields

**Action:** Skip early season in processors (no schema changes)

### Phase 4: Code Updates - 6-8 hours

#### 4.1 Update ML Feature Store Processor - 2 hours

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Location:** Lines 340-377 (existing `_is_early_season` method)

**Change from:**
```python
def _is_early_season(self, analysis_date: date) -> bool:
    """
    Check if we're in early season (insufficient data).

    Early season = >50% of players have early_season_flag set.
    """
    # Query player_daily_cache for threshold-based check
    if total > 0 and (early / total) > 0.5:
        self.early_season_flag = True
        return True
    return False
```

**Change to:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def _should_skip_early_season(self, analysis_date: date) -> bool:
    """
    Check if we should skip processing due to early season.

    Uses deterministic date-based check (first 7 days of season).
    This is cleaner than threshold-based approach.
    """
    season_year = get_season_year_from_date(analysis_date)

    if is_early_season(analysis_date, season_year, days_threshold=7):
        self.early_season_flag = True
        self.insufficient_data_reason = f"Early season: within 7 days of season start"
        logger.info(f"Skipping {analysis_date}: early season period (day 0-6)")
        return True

    return False

# Update process() method to skip early season
def process(self, analysis_date: date, season_year: int = None):
    # Determine season year if not provided
    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    # Skip early season (days 0-6)
    if self._should_skip_early_season(analysis_date):
        logger.info(f"Skipped early season: {analysis_date}")
        return  # Exit early, no records created

    # Day 7+: Process normally (existing code)
    # Rolling averages will use min_periods=1 (already implemented)
```

**Notes:**
- Keep existing `_create_early_season_placeholders` method (unused but keep for reference)
- Update quality scorer to use games_used metadata from player_daily_cache
- Test with dates: 2023-10-25 (skip), 2023-11-01 (process)

#### 4.2 Update Player Daily Cache Processor - 2 hours

**File:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

**Location:** Line ~113-114 (existing min_games threshold)

**Current code:**
```python
self.min_games_required = 10        # Preferred minimum
self.absolute_min_games = 5         # Absolute minimum to write record
```

**Add early season check to process() method:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def process(self, analysis_date: date, season_year: int = None):
    # Determine season year
    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    # Skip early season (days 0-6)
    if is_early_season(analysis_date, season_year, days_threshold=7):
        logger.info(f"Skipping {analysis_date}: early season period")
        return

    # Day 7+: Process with partial windows
    # ... existing extraction logic ...

    # Calculate rolling averages with min_periods=1
    for player in players:
        # L5 average
        l5_values = player_games.head(5)['points']
        points_avg_last_5 = l5_values.mean() if len(l5_values) > 0 else None
        points_avg_last_5_games_used = len(l5_values)

        # L10 average
        l10_values = player_games.head(10)['points']
        points_avg_last_10 = l10_values.mean() if len(l10_values) > 0 else None
        points_avg_last_10_games_used = len(l10_values)

        # Season average
        season_values = player_games['points']
        points_avg_season = season_values.mean() if len(season_values) > 0 else None
        points_avg_season_games_used = len(season_values)

        # Calculate quality score
        quality_score = points_avg_last_10_games_used / 10.0  # Based on L10

        # Set flags
        early_season_flag = False  # We're past day 7
        insufficient_data_reason = None
        if points_avg_last_10_games_used < 10:
            insufficient_data_reason = f'partial_window_L10_{points_avg_last_10_games_used}_of_10_games'

        record = {
            'points_avg_last_5': points_avg_last_5,
            'points_avg_last_5_games_used': points_avg_last_5_games_used,  # NEW
            'points_avg_last_10': points_avg_last_10,
            'points_avg_last_10_games_used': points_avg_last_10_games_used,  # NEW
            'points_avg_season': points_avg_season,
            'points_avg_season_games_used': points_avg_season_games_used,  # NEW
            'early_season_flag': early_season_flag,
            'insufficient_data_reason': insufficient_data_reason,
            # ... existing fields ...
        }
```

**Remove or update:**
- Old threshold-based early season detection (if exists)
- Update to use deterministic date-based approach

#### 4.3 Update Shot Zone Analysis Processor - 1 hour

**File:** `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

**Add to process() method:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def process(self, analysis_date: date, season_year: int = None):
    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    # Skip early season
    if is_early_season(analysis_date, season_year, days_threshold=7):
        logger.info(f"Skipping {analysis_date}: early season period")
        return

    # Day 7+: Process normally (existing code)
```

**Notes:**
- Minimal change (just add early season skip)
- Existing code already handles variable game counts

#### 4.4 Update Team Defense Zone Analysis Processor - 1 hour

**File:** `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`

**Same pattern as shot zone:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def process(self, analysis_date: date, season_year: int = None):
    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    # Skip early season
    if is_early_season(analysis_date, season_year, days_threshold=7):
        logger.info(f"Skipping {analysis_date}: early season period")
        return

    # Day 7+: Process normally (existing code)
```

**Note:** I see this file already imports from `shared.config.nba_season_dates` (line 37-41)!
Just need to add the skip logic.

#### 4.5 Update Composite Factors Processor (Optional) - 1 hour

**File:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Check if exists, then add same skip pattern.**

### Phase 5: Testing - 2-3 hours

#### Test Cases

**Test Dates:**
```python
# Should SKIP (return early, no records)
test_skip_dates = [
    (date(2021, 10, 19), 2021),  # Epoch day 0
    (date(2023, 10, 25), 2023),  # Opening night day 0
    (date(2023, 10, 26), 2023),  # Day 1
    (date(2023, 10, 31), 2023),  # Day 6
]

# Should PROCESS (normal behavior with partial windows)
test_process_dates = [
    (date(2023, 11, 1), 2023),   # Day 7 (crossover point)
    (date(2023, 11, 6), 2023),   # Day 12
    (date(2023, 12, 1), 2023),   # Mid-season
]
```

**Verification Queries:**

1. **Verify skip logic:**
```sql
-- Should return 0 records
SELECT COUNT(*)
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2023-10-25' AND '2023-10-31';
-- Expected: 0 (skipped)
```

2. **Verify partial windows:**
```sql
-- Should return records with games_used < window_size
SELECT
  cache_date,
  player_lookup,
  points_avg_last_10,
  points_avg_last_10_games_used,
  ROUND(points_avg_last_10_games_used / 10.0, 2) as quality_score
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = '2023-11-01'
ORDER BY points_avg_last_10_games_used ASC
LIMIT 10;
-- Expected: games_used values of 5-10, not all 10
```

3. **Verify accuracy:**
```sql
-- Predictions from Nov 1+ should have MAE <5.0
WITH predictions AS (
  SELECT
    actual_points,
    predicted_points,
    ABS(actual_points - predicted_points) as error
  FROM prediction_results
  WHERE prediction_date >= '2023-11-01'
    AND prediction_date <= '2023-11-15'
)
SELECT
  AVG(error) as mae,
  STDDEV(error) as std_error
FROM predictions;
-- Expected MAE: 4.5-4.8 (matches comprehensive-testing-plan.md results)
```

### Phase 6: Documentation Updates - 1 hour

**Files to update:**
- [ ] Update processor SKILL.md files (if exist)
- [ ] Update testing guide
- [ ] Document season start dates maintenance process
- [ ] Add troubleshooting guide

---

## File Modification Summary

### 📄 Documentation Files (5 files)

**To Create:**
1. ✅ `docs/08-projects/current/bootstrap-period/IMPLEMENTATION-PLAN.md` (this file)

**To Update:**
2. `docs/09-handoff/2025-11-27-bootstrap-period-handoff.md` - Add Q&A section
3. `docs/08-projects/current/bootstrap-period/EXECUTIVE-SUMMARY.md` - Add partial window note
4. `docs/08-projects/current/bootstrap-period/README.md` - Link to implementation plan
5. `docs/08-projects/current/bootstrap-period/comprehensive-testing-plan.md` - Reference

### 🔧 Configuration Files (1 file)

6. `shared/config/nba_season_dates.py` - Add 2021, verify dates, change default threshold

### 📊 SQL Schema Files (2 files)

7. `schemas/bigquery/precompute/player_daily_cache.sql` - Add 3 games_used fields
8. `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` - Update comments only

### 💻 Python Code Files (4-5 files)

9. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` - Update early season check
10. `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` - Add skip logic + games_used
11. `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` - Add skip logic
12. `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py` - Add skip logic
13. `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` - Add skip logic (if exists)

### ✅ Testing Files (0 files - use BigQuery directly)

No new test files needed - use BigQuery verification queries

**Total Files:** 13-14 files to modify

---

## Migration & Deployment

### Database Migration

**Schema changes require:**
1. Add 3 new columns to `player_daily_cache` table
2. Update comments on `ml_feature_store_v2` table

**Migration SQL:**
```sql
-- Add games_used fields to player_daily_cache
ALTER TABLE `nba-props-platform.nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS points_avg_last_5_games_used INT64,
ADD COLUMN IF NOT EXISTS points_avg_last_10_games_used INT64,
ADD COLUMN IF NOT EXISTS points_avg_season_games_used INT64;

-- Backfill existing records (optional - can be NULL for historical data)
UPDATE `nba-props-platform.nba_precompute.player_daily_cache`
SET
  points_avg_last_5_games_used = LEAST(games_played_season, 5),
  points_avg_last_10_games_used = LEAST(games_played_season, 10),
  points_avg_season_games_used = games_played_season
WHERE points_avg_last_5_games_used IS NULL;
```

### Deployment Steps

1. **Deploy to staging** (Week 1)
   - Update configuration
   - Update schemas
   - Deploy processor code
   - Run verification queries

2. **Test with historical data** (Week 2)
   - Process Oct-Nov 2023 dates
   - Verify skip behavior
   - Verify partial window behavior
   - Verify accuracy matches testing

3. **Deploy to production** (Week 3)
   - Gradual rollout
   - Monitor logs for errors
   - Verify nightly processing

4. **Monitor Oct 2025** (First live test)
   - Coverage metrics (target: >95% by Nov 1)
   - Accuracy metrics (target: MAE <5.0)
   - User feedback (target: <5% complaints)

---

## Success Criteria

**Implementation is successful if:**
- ✅ All 4 processors skip days 0-6 of season
- ✅ Days 7+ process with partial windows (not NULL)
- ✅ games_used metadata tracked for all rolling windows
- ✅ Verification queries return expected results
- ✅ No errors in staging testing
- ✅ Code review passes
- ✅ Documentation complete

**Validation is successful if (Oct 2025):**
- ✅ Coverage >95% by Nov 1
- ✅ MAE <5.0 for Nov 1-15 predictions
- ✅ <5% user complaints about missing predictions
- ✅ No production errors
- ✅ Processor logs show correct skip behavior

---

## Rollback Plan

**If implementation fails:**
1. Revert processor code changes
2. Keep schema changes (backward compatible)
3. System returns to threshold-based early season detection
4. Investigate and retry

**If validation fails (Oct 2025):**
1. Strong negative user feedback → Consider Option C (cross-season with warnings)
2. Poor accuracy → Investigate data quality issues
3. Coverage issues → Adjust skip_days threshold (7 → 5 or 10)

---

## Future Work (Deferred)

**Not implementing now (can revisit based on Oct 2025 data):**

1. **Cross-season rest patterns** (Week 4+)
   - Track team changes
   - Add cross_season_data_used flag
   - Weight down historical patterns
   - A/B test accuracy improvement

2. **Matchup history** (Week 4+)
   - "LeBron vs Warriors" historical performance
   - Track team changes for both players
   - May be stable across seasons

3. **Confidence degradation formula** (Week 4+)
   - Complex calculation based on:
     - games_used / window_size
     - team_changed flag
     - role_changed detection
     - playoff mixing
   - Only needed if implementing Option C

4. **Similar player baselines** (Future)
   - Use rookie college stats
   - Find similar players for new players
   - Low priority

5. **Situational models** (Future)
   - Rest-specific models
   - Home/away specific models
   - Opponent-specific models

**Focus:** Get Option A working perfectly first. Iterate based on real-world data.

---

## Questions for Product/Business

**Before final implementation, clarify:**

1. **User messaging:** What should users see for Oct 25-31 predictions?
   - Option A: "Predictions available after Nov 1"
   - Option B: "Insufficient data for early season predictions"
   - Option C: No message, just NULL predictions

2. **Competitive concerns:** Do competitors have day-1 predictions?
   - If yes: Consider Option C (cross-season with warnings)
   - If no: Option A is fine

3. **A/B testing:** Should we A/B test Option A vs Option C in Oct 2025?
   - Requires running both in parallel
   - Adds complexity but provides data

4. **Error handling:** How to handle edge cases?
   - Player trades during early season
   - Injuries during early season
   - Rookies (always insufficient data)

---

## Contact & Escalation

**Implementation questions:**
- Check this IMPLEMENTATION-PLAN.md
- Reference files listed in "File Modification Summary"
- Test queries in Phase 5: Testing

**Design questions:**
- See Q&A sections above
- See EXECUTIVE-SUMMARY.md for decision rationale
- See comprehensive-testing-plan.md for data supporting decisions

**If you need to change decisions:**
1. Read Q&A sections to understand reasoning
2. Consider impact on team change problem (24% of players)
3. Consult with product/business team
4. Document new decision in this file

---

**Ready to implement!** All questions answered, all files identified, all changes scoped.

**Estimated total effort:** 12-15 hours (vs 40-60 hours for Option B/C)
