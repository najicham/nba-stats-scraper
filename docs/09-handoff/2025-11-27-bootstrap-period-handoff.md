# Bootstrap Period Design - Implementation Handoff Document

**Date:** 2025-11-27
**Status:** Investigation Complete ✅ - Ready for Implementation
**Decision:** Option A (Current-Season-Only)
**Next Owner:** [Developer/Team Name]

---

## Quick Start (5 Minutes)

**If you only have 5 minutes, read this:**

1. **Problem:** System can't calculate rolling averages (L5, L10) in first 3 weeks of NBA season due to insufficient data
2. **Investigation:** Ran 13 queries across 2 seasons to compare cross-season vs current-season approaches
3. **Finding:** Cross-season advantage lasts only 5-7 days, and HURTS 24% of predictions (team changes)
4. **Decision:** Skip predictions for first 7 days of season (Option A)
5. **Implementation:** 10 hours - update 4 processors to skip early season
6. **Read:** [EXECUTIVE-SUMMARY.md](./EXECUTIVE-SUMMARY.md) for full details

---

## Project Context

### What Problem Are We Solving?

**The Bootstrap Period Problem:**
- NBA season starts ~Oct 22-25 each year
- Rolling statistics need 5-10 games of historical data
- In first 3 weeks, players have 0-5 games available
- Phase 4 processors can't calculate trends/averages
- Phase 5 predictions fail (missing features)
- Result: NULL predictions during early season

**Example:**
- Oct 25, 2023 (opening night): Player has 0 games
- Need "last 10 games average" → Can't calculate (no data)
- Phase 5 XGBoost model needs features → NULL
- User sees no prediction

### Two Possible Approaches

**Option A: Current-Season-Only** (CHOSEN)
- Use only current season games for rolling averages
- Skip predictions when <3-5 games available
- Result: No predictions for ~7 days each October
- Effort: 10 hours

**Option B/C: Cross-Season** (REJECTED)
- Use prior season games to fill gaps
- Predictions available from day 1
- Result: 24% of predictions are WORSE (team changes)
- Effort: 40-60 hours

---

## Investigation Summary

### What We Tested

**4 Test Suites Executed:**
1. **Multi-date trend analysis** (8 dates: Oct 25, 27, 30, Nov 1, 6, 8, 10, 15)
2. **Role change impact** (stable vs team changed vs points changed)
3. **2024 season validation** (pattern consistency)
4. **Confidence calibration** (games available vs accuracy)

**Total Queries:** 13
**Seasons Tested:** 2 (2023-24, 2024-25)
**Duration:** ~4 hours

### Key Findings

**Finding 1: Short-Lived Advantage**
- Cross-season advantage exists only days 2-7 (Oct 27 - Nov 1)
- Maximum benefit: 1.48 MAE on day 2
- By Nov 1: Approaches are tied (4.59 vs 4.60 MAE)
- Advantage lasts <1 week, not 3 weeks

**Finding 2: Team Changes Invalidate Cross-Season** 🚨
- 24% of players changed teams between seasons
- For team changes: Cross-season MAE 5.35 vs Current-season 4.43
- **Cross-season is 0.91 MAE WORSE for team changes**
- This affects 1 in 4 predictions

**Finding 3: Coverage is Excellent**
- Day 2: 81% coverage
- Day 5: 94% coverage
- Day 7: 97% coverage
- Missing predictions for 7 days is acceptable

**Finding 4: Pattern is Consistent**
- Tested 2023-24 and 2024-25 seasons
- Same crossover point (Nov 1-6)
- Same coverage trajectory
- Findings are reliable

### Decision Rationale

**Why Option A?**
1. **Cost-benefit:** 10 hours vs 40-60 hours for equivalent outcome
2. **Team changes:** Cross-season hurts 24% of predictions
3. **Coverage:** 94-97% by day 7 is sufficient
4. **Convergence:** Tied by Nov 1 anyway
5. **Simplicity:** Can always add Option C later if needed

**The Math:**
- Don't spend 40-60 hours to gain 0.5 MAE for 5 days/year when 24% of predictions are worse

---

## Documents to Read

### Essential Reading (Must Read - 30 minutes)

1. **[EXECUTIVE-SUMMARY.md](./EXECUTIVE-SUMMARY.md)** ⭐ **START HERE**
   - Complete overview of findings
   - All test results summarized
   - Final recommendation with justification
   - Implementation plan
   - ~15 minutes to read

2. **[comprehensive-testing-plan.md](./comprehensive-testing-plan.md)** 📊
   - All 4 test suites with detailed results
   - SQL queries used for testing
   - Trend charts and data tables
   - Decision matrix
   - ~15 minutes to skim, 1 hour to read thoroughly

### Supporting Documentation (Reference - as needed)

3. **[README.md](./README.md)** 📋
   - Project overview
   - Quick links to all documents
   - Implementation checklist
   - ~5 minutes

4. **[bootstrap-design-decision.md](./bootstrap-design-decision.md)** 📖
   - Detailed design options (A, B, C)
   - Metadata schema proposals
   - Edge cases and gray areas
   - ~30 minutes (only if you need design details)

5. **[preliminary-findings.md](./preliminary-findings.md)** 🎯
   - Initial Fast Track results (2 dates tested)
   - Historical document (superseded by comprehensive testing)
   - ~10 minutes

6. **[investigation-findings.md](./investigation-findings.md)** 🔍
   - Codebase analysis
   - What bootstrap patterns already exist
   - Phase 4/5 architecture
   - ~20 minutes

7. **[validation-questions-answered.md](./validation-questions-answered.md)** ❓
   - Q&A about Phase 5 NULL handling
   - Role change analysis
   - Retroactive validation approach
   - ~15 minutes

### Read Priority

**For Implementation:**
1. EXECUTIVE-SUMMARY.md (must read)
2. comprehensive-testing-plan.md (sections: Final Recommendation, Implementation Plan)
3. investigation-findings.md (sections: Q1, Q2 - understand current code)

**For Understanding the Decision:**
1. EXECUTIVE-SUMMARY.md (complete)
2. comprehensive-testing-plan.md (all test suite summaries)
3. bootstrap-design-decision.md (Option A vs B vs C comparison)

---

## Implementation Guide

### What Needs to Be Built (Option A)

**High-Level Overview:**
1. Create season start date utility
2. Add early season detection logic to 4 processors
3. Update early_season_flag calculation
4. Add user-facing message for NULL predictions
5. Test with historical data (2021-10-19 epoch)

### Files to Modify

**New File:**
- `shared/utils/season_dates.py` - Season start date lookup utility

**Existing Files to Modify:**
1. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
2. `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
3. `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
4. `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`

**Optional (if UI updates needed):**
- `predictions/worker/worker.py` - Add user message for NULL predictions

### Implementation Steps

**Phase 1: Core Logic (Week 1 - 10 hours)**

1. **Create Season Dates Utility** (2 hours)
   ```python
   # shared/utils/season_dates.py
   from datetime import date

   SEASON_START_DATES = {
       2021: date(2021, 10, 19),
       2022: date(2022, 10, 18),
       2023: date(2023, 10, 25),
       2024: date(2024, 10, 23),
       2025: date(2025, 10, 22),  # Estimated
   }

   def get_season_start_date(season_year: int) -> date:
       """Get season start date for a given season year."""
       return SEASON_START_DATES.get(season_year)

   def is_early_season(analysis_date: date, season_year: int, skip_days: int = 7) -> bool:
       """
       Check if analysis_date is within early season period.

       Args:
           analysis_date: Date being analyzed
           season_year: Season year (e.g., 2024 for 2024-25 season)
           skip_days: Number of days to skip (default: 7)

       Returns:
           True if within first skip_days of season start
       """
       season_start = get_season_start_date(season_year)
       if not season_start:
           return False

       days_into_season = (analysis_date - season_start).days
       return 0 <= days_into_season < skip_days
   ```

2. **Update ML Feature Store Processor** (2 hours)

   Location: `ml_feature_store_processor.py:340-453` (existing early season logic)

   **Change from:**
   ```python
   # Current: Uses >50% threshold
   if _is_early_season(analysis_date):  # >50% players lack data
       # Create early season placeholders
   ```

   **Change to:**
   ```python
   from shared.utils.season_dates import is_early_season

   # New: Uses deterministic date check
   if is_early_season(analysis_date, season_year, skip_days=7):
       # Skip processing entirely OR create early season placeholders
       self.logger.info(f"Skipping {analysis_date}: within 7 days of season start")
       return  # Skip processing
   ```

3. **Update Player Daily Cache Processor** (2 hours)

   Location: `player_daily_cache_processor.py:357`

   Add early season check before processing:
   ```python
   from shared.utils.season_dates import is_early_season

   def process(self, analysis_date: date, season_year: int):
       # Add early season check
       if is_early_season(analysis_date, season_year):
           self.logger.info(f"Skipping {analysis_date}: early season period")
           return

       # Existing processing logic...
   ```

4. **Update Shot Zone and Team Defense Processors** (2 hours each = 4 hours)

   Same pattern as player_daily_cache - add early season check

5. **Testing** (2 hours)

   Test with epoch date and early season dates:
   ```python
   # Test cases
   test_dates = [
       (date(2021, 10, 19), 2021, True),   # Epoch - should skip
       (date(2021, 10, 25), 2021, True),   # Day 6 - should skip
       (date(2021, 10, 26), 2021, False),  # Day 7 - should process
       (date(2023, 10, 25), 2023, True),   # Opening night 2023
       (date(2023, 11, 01), 2023, False),  # Nov 1 - should process
   ]
   ```

**Phase 2: UI Updates (Week 2 - 4 hours)**

1. **Add User Message** (2 hours)

   Location: `predictions/worker/worker.py:73-81` (error handling)

   ```python
   # When features are NULL due to early season
   if not features or early_season_flag:
       return {
           'prediction': None,
           'confidence': 0.0,
           'reason': 'Early season: Predictions available after Nov 1',
           'available_date': estimate_available_date(player, season_year),
           'early_season': True
       }
   ```

2. **Documentation Updates** (2 hours)
   - Update processor SKILL.md files
   - Add testing guide for early season
   - Document season start dates

**Phase 3: Deployment (Week 3)**

1. Deploy to staging
2. Verify with test data
3. Deploy to production
4. Monitor for issues

**Phase 4: Validation (Oct 2025)**

1. First live season start
2. Monitor user feedback
3. Measure accuracy (should match testing: MAE <5.0 by Nov 1)
4. Adjust skip_days if needed (current: 7, could be 5-10)

---

## Technical Context

### Current System Architecture

**Phase 2 (Raw):**
- Scrapers write game-level data to `nba_raw` tables
- No bootstrap concerns here

**Phase 3 (Analytics):**
- `player_game_summary` - Per-game records (no rolling calculations)
- No bootstrap handling needed (single game records)

**Phase 4 (Precompute):**
- `ml_feature_store_v2` - Rolling averages, trends, aggregations ⚠️ **BOOTSTRAP CONCERNS**
- `player_daily_cache` - Cached rolling stats ⚠️ **BOOTSTRAP CONCERNS**
- `player_shot_zone_analysis` - Zone-based trends ⚠️ **BOOTSTRAP CONCERNS**
- `team_defense_zone_analysis` - Defensive trends ⚠️ **BOOTSTRAP CONCERNS**

**Phase 5 (Predictions):**
- XGBoost model consumes Phase 4 features
- Already handles NULL gracefully (verified in validation-questions-answered.md)
- Returns NULL prediction when features missing

### Existing Bootstrap Patterns

**Pattern 1: Early Season Placeholders** (ML Feature Store)
- Location: `ml_feature_store_processor.py:340-453`
- Current approach: Creates NULL feature records with `early_season_flag = TRUE`
- Uses >50% threshold (if >50% of players lack data, it's early season)
- **Change needed:** Replace with deterministic date check

**Pattern 2: Min Games Threshold** (Player Daily Cache)
- Location: `player_daily_cache_processor.py:357`
- Current approach: Binary threshold (skip if <5 games)
- **Change needed:** Add early season check (skip first 7 days regardless of game count)

**Pattern 3: Bootstrap Mode Override** (Completeness Checker)
- Location: `shared/utils/completeness_checker.py`
- Utility for checking data completeness
- Already has bootstrap mode support
- **Change needed:** None (can reuse existing utility)

### Database Schema

**Relevant Tables:**

**`nba_analytics.player_game_summary`:**
- Main source of game data
- Fields: player_lookup, game_date, season_year, team_abbr, points, minutes_played, etc.
- Coverage: 2021-10-19 (epoch) to present
- Used by Phase 4 processors to calculate rolling averages

**`nba_precompute.ml_feature_store_v2`:**
- Output of ML Feature Store processor
- 25 features (rolling averages, trends, composite factors)
- Has `early_season_flag` BOOLEAN field
- **No schema changes needed for Option A**

**`nba_predictions.prediction_worker_runs`:**
- Prediction logs
- May not exist (confirmed during investigation)
- Not critical for implementation

### Important Data Quality Notes

**Issue 1: minutes_played is NULL for 2023 data**
- Impact: Can't filter by minutes_played for 2023 season
- Workaround: Use `points > 0` filter instead
- Severity: Minor (doesn't affect implementation)

**Issue 2: Season year format**
- 2023-24 season is stored as season_year = 2023
- 2024-25 season is stored as season_year = 2024
- Pattern: season_year = year when season STARTED

---

## Testing & Validation

### Test Data

**Historical Epoch Date:**
- 2021-10-19 - First NBA game with data
- Use this to test bootstrap handling for historical backfills

**Test Dates (2023-24 Season):**
- Oct 25, 2023 - Opening night (day 0)
- Oct 27, 2023 - Day 2 (only 1 game available)
- Oct 30, 2023 - Day 5 (2-4 games available)
- Nov 1, 2023 - Day 7 (crossover point - should process)
- Nov 6, 2023 - Day 12 (should process)

### Expected Behavior

**Before Implementation (Current):**
- Oct 25-Nov 1: ML Feature Store creates early season placeholders (NULL features)
- Nov 1+: Normal processing

**After Implementation (Option A):**
- Oct 25-31: All 4 processors skip (no records written)
- Nov 1+: Normal processing resumes
- Coverage: 94-97% by Nov 1

### Test Queries

**Verify skip logic works:**
```sql
-- Should return 0 records for Oct 25-31, 2023
SELECT COUNT(*)
FROM `nba-props-platform.nba_precompute.ml_feature_store_v2`
WHERE created_at BETWEEN '2023-10-25' AND '2023-10-31';
-- Expected: 0 (skipped)

-- Should return >200 records for Nov 1, 2023
SELECT COUNT(*)
FROM `nba-props-platform.nba_precompute.ml_feature_store_v2`
WHERE created_at = '2023-11-01';
-- Expected: ~250 (processing resumed)
```

**Verify accuracy after Nov 1:**
```sql
-- Predictions from Nov 1+ should have MAE <5.0
-- (Based on testing results)
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
-- Expected MAE: 4.5-4.8 (matches testing)
```

### Rollback Plan

**If issues arise:**
1. Revert processor changes
2. System returns to current behavior (early season placeholders)
3. Phase 5 still handles NULL gracefully
4. No data loss (just missing predictions for 7 days)

**Fallback to Option C:**
If user feedback is strongly negative:
1. Implement cross-season approach with warnings
2. Add 15 aggregate metadata fields
3. Effort: 20-30 hours
4. See `bootstrap-design-decision.md` for Option C details

---

## Known Edge Cases

### Edge Case 1: Player Trades During Early Season

**Scenario:** Player traded on Oct 26
**Current behavior:** Will be skipped (no predictions until Nov 1)
**Expected behavior:** Same (acceptable)
**Mitigation:** None needed (7-day skip applies to all players)

### Edge Case 2: Rookies

**Scenario:** Rookie in first NBA season (no prior season data)
**Current behavior:** Will be skipped until Nov 1
**Expected behavior:** Same (acceptable - need 5+ games for reliable prediction)
**Mitigation:** None needed

### Edge Case 3: Players Returning from Injury

**Scenario:** Player returns from injury on Oct 28 after missing all offseason
**Current behavior:** Will be skipped until Nov 1
**Expected behavior:** Same (acceptable - need current season games)
**Mitigation:** None needed

### Edge Case 4: Backfills to 2021-10-19

**Scenario:** Historical backfill needs to process 2021-10-19 onward
**Current behavior:** Will skip Oct 19-25, 2021
**Expected behavior:** Same (acceptable - first predictions on Oct 26, 2021)
**Testing:** Use 2021-10-19 as test case

### Edge Case 5: Season Start Date Changes

**Scenario:** NBA changes season start date (e.g., 2026 starts Oct 20)
**Mitigation:** Update `SEASON_START_DATES` in `season_dates.py`
**Recommendation:** Check NBA schedule each summer, update constant

---

## Configuration

### Configurable Parameters

**Skip Days (Default: 7)**
```python
# In season_dates.py or config
EARLY_SEASON_SKIP_DAYS = 7  # Configurable

# Can adjust based on Oct 2025 results:
# - If users complain: Reduce to 5 days
# - If accuracy is poor: Increase to 10 days
```

**Season Start Dates**
```python
# Add new seasons as they're scheduled
SEASON_START_DATES = {
    2021: date(2021, 10, 19),
    2022: date(2022, 10, 18),
    2023: date(2023, 10, 25),
    2024: date(2024, 10, 23),
    2025: date(2025, 10, 22),  # Update when confirmed
    2026: date(2026, 10, 20),  # Add as needed
}
```

### Feature Flags (Optional)

**If you want to toggle behavior:**
```python
# In config or environment
ENABLE_EARLY_SEASON_SKIP = True  # Can disable for testing

# In processor:
if ENABLE_EARLY_SEASON_SKIP and is_early_season(analysis_date, season_year):
    return  # Skip
```

---

## Monitoring & Success Criteria

### Metrics to Track (Oct 2025)

**Coverage:**
- Target: >95% by Nov 1
- Measure: % of players with predictions
- Alert if: <90%

**Accuracy:**
- Target: MAE <5.0 for Nov 1-15 predictions
- Measure: Mean absolute error vs actual results
- Alert if: MAE >5.5

**User Feedback:**
- Track: Complaints about missing predictions
- Target: <5% of users complain
- Alert if: >10% complain or high-value users upset

**Error Rate:**
- Track: Prediction worker failures
- Target: <1% error rate
- Alert if: >5% error rate

### Dashboard Queries

**Coverage by Date:**
```sql
SELECT
  DATE(created_at) as date,
  COUNT(DISTINCT player_lookup) as players_with_predictions,
  ROUND(100.0 * COUNT(DISTINCT player_lookup) /
    (SELECT COUNT(DISTINCT player_lookup)
     FROM player_game_summary
     WHERE game_date = DATE(mfs.created_at)), 1) as coverage_pct
FROM ml_feature_store_v2 mfs
WHERE created_at >= '2025-10-22'
  AND created_at <= '2025-11-15'
GROUP BY DATE(created_at)
ORDER BY date;
```

**Accuracy Trend:**
```sql
SELECT
  DATE(prediction_date) as date,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(actual_points - predicted_points)), 2) as mae,
  ROUND(STDDEV(ABS(actual_points - predicted_points)), 2) as std_error
FROM prediction_results
WHERE prediction_date >= '2025-11-01'
  AND prediction_date <= '2025-11-15'
GROUP BY DATE(prediction_date)
ORDER BY date;
```

### Success Criteria

**Option A is successful if (Oct 2025):**
- ✅ Coverage >95% by Nov 1
- ✅ MAE <5.0 for Nov 1-15 predictions
- ✅ <5% user complaints
- ✅ No rollback needed
- ✅ Error rate <1%

**Reconsider if:**
- ❌ Strong negative user feedback (>10% complaints)
- ❌ High-value users leave platform
- ❌ Competitors steal users with day-1 predictions
- ❌ Coverage <90% by Nov 1
- ❌ MAE >5.5 (significantly worse than testing)

---

## Questions & Answers

### Q: Why not use prior season data?

**A:** Testing showed cross-season HURTS 24% of predictions (team changes). For team changed players, cross-season MAE is 5.35 vs current-season 4.43 - a 0.91 MAE penalty. This invalidates the cross-season approach.

### Q: What about the 7 days without predictions?

**A:** Coverage testing showed:
- Day 2: 81% coverage with current-season
- Day 5: 94% coverage
- Day 7: 97% coverage

Missing predictions for 7 days is acceptable given the alternative (24% bad predictions).

### Q: Can we reduce the skip window to 5 days?

**A:** Yes! The `skip_days` parameter is configurable. Based on Oct 2025 results:
- If users complain: Reduce to 5 days
- If accuracy is poor: Increase to 10 days
- Current setting (7 days) is based on data showing convergence at Nov 1-6

### Q: What if a new chat/developer has questions?

**A:** Read documents in this order:
1. This HANDOFF.md (you are here)
2. EXECUTIVE-SUMMARY.md (complete overview)
3. comprehensive-testing-plan.md (test results)
4. investigation-findings.md (codebase context)

If still unclear, check:
- `ml_feature_store_processor.py:340-453` for existing early season logic
- Test queries in comprehensive-testing-plan.md
- Original design in bootstrap-design-decision.md

### Q: What about confidence scores / degradation?

**A:** NOT implementing for Option A. Current-season-only uses binary approach:
- <7 days into season: Skip (no prediction)
- ≥7 days into season: Process normally

Confidence degradation (games/10 formula) was tested and NOT supported by data. If implementing cross-season later (Option C), you'll need complex confidence calculation.

### Q: Where can I find the test queries?

**A:** All test queries are in `comprehensive-testing-plan.md` with results. Key queries:
- Test 1.1-1.8: Multi-date trend (8 dates)
- Test 2.1-2.2: Role change impact
- Test 3.1-3.3: 2024 validation
- Test 4.1: Confidence calibration

### Q: How do I test the implementation?

**A:** Use these test dates:
```python
# Should SKIP (return early)
test_skip_dates = [
    (date(2021, 10, 19), 2021),  # Epoch
    (date(2023, 10, 25), 2023),  # Opening night
    (date(2023, 10, 30), 2023),  # Day 5
]

# Should PROCESS (normal behavior)
test_process_dates = [
    (date(2023, 11, 1), 2023),   # Day 7
    (date(2023, 11, 6), 2023),   # Day 12
    (date(2023, 12, 1), 2023),   # Mid-season
]
```

Verify:
1. Skip dates produce 0 records
2. Process dates produce ~250 records
3. Accuracy matches testing (MAE <5.0)

---

## Gotchas & Important Notes

### Gotcha 1: Don't Break Existing Early Season Logic

**Issue:** ML Feature Store already has early season placeholder logic
**Location:** `ml_feature_store_processor.py:340-453`
**Action:** Replace threshold-based approach with date-based approach, but keep the placeholder structure if needed

### Gotcha 2: Season Year Format

**Issue:** Season year = year when season started (not academic year)
**Example:**
- 2023-24 season = season_year 2023
- Oct 2023 games = season_year 2023
- Apr 2024 games = season_year 2023 (same season!)

### Gotcha 3: minutes_played is NULL

**Issue:** Can't use `minutes_played >= 10` filter for 2023 data
**Workaround:** Use `points > 0` instead
**Impact:** Minor (includes some low-minute players, but directionally correct)

### Gotcha 4: Backfill Jobs

**Issue:** Historical backfills need to handle 2021-10-19 epoch correctly
**Action:** Ensure backfill jobs use same `is_early_season()` logic
**Test:** Run backfill for Oct 2021 and verify skip behavior

### Gotcha 5: Playoff Games

**Issue:** Should playoff games from prior season be included?
**Decision:** With Option A, this doesn't matter (only using current season)
**Note:** If pivoting to Option C later, need to address playoff mixing

---

## Contact & Escalation

### For Implementation Questions

**Code Review:**
- Reference files in investigation-findings.md (Q1, Q2)
- Check existing patterns in `ml_feature_store_processor.py:340-453`

**Testing Questions:**
- See comprehensive-testing-plan.md for test cases
- Use test queries provided in document

**Design Questions:**
- See EXECUTIVE-SUMMARY.md for decision rationale
- See bootstrap-design-decision.md for alternative options

### For Product/Business Questions

**User Impact:**
- 7 days without predictions each October
- Can show message: "Predictions available after Nov 1"
- Coverage: 94-97% by day 7

**Competitive Concerns:**
- If competitors have day-1 predictions, consider Option C
- Option C: 20-30 hours, predictions from day 1, with warnings

**Timeline Concerns:**
- Option A: 10 hours (3 weeks to production)
- Option B: 40-60 hours (4-8 weeks)
- Option C: 20-30 hours (2-4 weeks)

### For Escalation

**If you need to change the decision:**
1. Read EXECUTIVE-SUMMARY.md to understand why Option A was chosen
2. Review the team change penalty finding (-0.91 MAE for 24% of players)
3. Consider Option C (hybrid) as alternative (not Option B)
4. Consult bootstrap-design-decision.md for Option C implementation details

**If testing shows different results:**
1. Verify test dates and season_year format
2. Check for minutes_played NULL issue (use points > 0)
3. Compare to expected results in comprehensive-testing-plan.md
4. Document differences and investigate

---

## Appendix: Quick Reference

### File Locations

**Documentation:**
- This file: `docs/08-projects/current/bootstrap-period/HANDOFF.md`
- Executive summary: `docs/08-projects/current/bootstrap-period/EXECUTIVE-SUMMARY.md`
- Test results: `docs/08-projects/current/bootstrap-period/comprehensive-testing-plan.md`

**Code Files to Modify:**
- New utility: `shared/utils/season_dates.py`
- ML Feature Store: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- Player Daily Cache: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- Shot Zone Analysis: `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
- Team Defense: `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`

### Key Constants

```python
# Season start dates
SEASON_STARTS = {
    2021: '2021-10-19',  # Epoch
    2022: '2022-10-18',
    2023: '2023-10-25',
    2024: '2024-10-23',
    2025: '2025-10-22',  # Estimated
}

# Skip window
EARLY_SEASON_SKIP_DAYS = 7  # Configurable (5-10 days range)

# Crossover point (from testing)
CONVERGENCE_DATE = 'Nov 1-6'  # Days 7-12 into season
```

### Key Findings At-a-Glance

| Finding | Value | Implication |
|---------|-------|-------------|
| Cross-season advantage duration | 5-7 days | Short-lived |
| Maximum advantage | 1.48 MAE (day 2) | Marginal |
| Team change penalty | -0.91 MAE (24% of players) | Cross-season HURTS |
| Coverage by day 7 | 94-97% | Sufficient |
| Crossover point | Nov 1-6 (days 7-12) | Early convergence |
| Implementation effort | 10 hours (Option A) | Low |
| Confidence in findings | HIGH (2 seasons, 10 dates, 13 queries) | Reliable |

### Decision Summary Table

| Factor | Option A | Option B | Option C | Winner |
|--------|----------|----------|----------|---------|
| Effort | 10 hours | 40-60 hours | 20-30 hours | A |
| Accuracy (Week 1) | 5.26 MAE | 4.75 MAE | 4.75 MAE | B/C |
| Accuracy (Week 2+) | 4.60 MAE | 4.59 MAE | 4.59 MAE | TIE |
| Team change impact | None | -0.91 MAE penalty | -0.91 MAE penalty | A |
| Coverage | 94-97% | 100% | 100% | B/C |
| Schema changes | 0 | 30-35 fields | 15 fields | A |
| Maintenance | None | Ongoing | Moderate | A |
| **TOTAL SCORE** | **9.0/10** | 6.3/10 | 7.5/10 | **A** |

---

## Final Checklist for New Owner

**Before starting implementation:**
- [ ] Read EXECUTIVE-SUMMARY.md (15 min)
- [ ] Skim comprehensive-testing-plan.md (15 min)
- [ ] Read investigation-findings.md Q1-Q2 (10 min)
- [ ] Understand why team changes matter (critical finding)
- [ ] Review files to modify (4 processors + 1 new utility)
- [ ] Understand configurable parameters (skip_days, season_start_dates)
- [ ] Review test cases and expected behavior

**During implementation:**
- [ ] Create season_dates.py utility
- [ ] Update 4 processors with early season check
- [ ] Add user-facing message for NULL predictions
- [ ] Test with historical dates (2021-10-19, 2023-10-25, 2023-11-01)
- [ ] Verify coverage and accuracy match testing results
- [ ] Document any deviations or issues

**After deployment:**
- [ ] Monitor coverage metrics (target: >95% by Nov 1)
- [ ] Monitor accuracy metrics (target: MAE <5.0)
- [ ] Track user feedback (target: <5% complaints)
- [ ] Prepare for Oct 2025 validation (first live test)

---

**Good luck with the implementation! The data is solid and the path is clear.**

**Questions? Read the documents above or check the code references provided.**
