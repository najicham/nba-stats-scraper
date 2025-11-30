# Bootstrap Period Implementation - Files to Modify

**Quick Reference for Implementation**
**Total Files:** 13-14 files

---

## 📄 Documentation (4 files to update + 1 created)

✅ **CREATED:**
- `docs/08-projects/current/bootstrap-period/IMPLEMENTATION-PLAN.md`
- `docs/08-projects/current/bootstrap-period/FILES-TO-MODIFY.md` (this file)

**TO UPDATE:**
- [ ] `docs/09-handoff/2025-11-27-bootstrap-period-handoff.md`
  - Add reference to IMPLEMENTATION-PLAN.md in Q&A section
  - Link to partial window decision

- [ ] `docs/08-projects/current/bootstrap-period/EXECUTIVE-SUMMARY.md`
  - Add note about partial windows (not NULL after day 7)
  - Reference games_used metadata approach

- [ ] `docs/08-projects/current/bootstrap-period/README.md`
  - Add link to IMPLEMENTATION-PLAN.md
  - Update implementation status

---

## 🔧 Configuration (1 file)

- [ ] `shared/config/nba_season_dates.py`

**Changes:**
```python
# Line 10-15: Update SEASON_START_DATES
SEASON_START_DATES = {
    2024: date(2024, 10, 23),  # Verify/update
    2023: date(2023, 10, 25),  # UPDATE: Currently shows 10-24
    2022: date(2022, 10, 18),
    2021: date(2021, 10, 19),  # ADD: Epoch date
}

# Line 39: Update default threshold
def is_early_season(..., days_threshold: int = 7):  # Change from 14 → 7
```

**Effort:** 15 minutes

---

## 📊 SQL Schemas (2 files)

### File 1: player_daily_cache.sql

- [ ] `schemas/bigquery/precompute/player_daily_cache.sql`

**Changes:**
```sql
-- Add after line 41 (after games_played_season field)

-- ============================================================================
-- ROLLING WINDOW METADATA - Track actual games used (3 fields)
-- Added for bootstrap period partial window support
-- ============================================================================
points_avg_last_5_games_used INT64,     -- How many games used for L5 (out of 5)
points_avg_last_10_games_used INT64,    -- How many games used for L10 (out of 10)
points_avg_season_games_used INT64,     -- Same as games_played_season
```

**Migration SQL:**
```sql
ALTER TABLE `nba-props-platform.nba_precompute.player_daily_cache`
ADD COLUMN IF NOT EXISTS points_avg_last_5_games_used INT64,
ADD COLUMN IF NOT EXISTS points_avg_last_10_games_used INT64,
ADD COLUMN IF NOT EXISTS points_avg_season_games_used INT64;
```

**Effort:** 30 minutes

### File 2: ml_feature_store_v2.sql

- [ ] `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`

**Changes:**
```sql
-- Line 77: Update comment
insufficient_data_reason STRING,  -- Why data was insufficient OR partial
                                   -- 'early_season', 'partial_window_L30_7_of_30'

-- Line 30: Add comment
feature_quality_score NUMERIC(5,2),  -- 0-100 quality score
-- NOTE: Feature-level quality via player_daily_cache.{feature}_games_used
```

**Effort:** 15 minutes

---

## 💻 Python Code (4-5 processor files)

### File 1: ML Feature Store Processor

- [ ] `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Location:** Lines 340-377 (`_is_early_season` method)

**Key changes:**
1. Import from `shared.config.nba_season_dates`
2. Replace `_is_early_season()` with `_should_skip_early_season()`
3. Use date-based check instead of threshold-based
4. Add skip logic to `process()` method

**Code snippet:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def _should_skip_early_season(self, analysis_date: date) -> bool:
    season_year = get_season_year_from_date(analysis_date)
    if is_early_season(analysis_date, season_year, days_threshold=7):
        logger.info(f"Skipping {analysis_date}: early season (day 0-6)")
        return True
    return False

def process(self, analysis_date: date, season_year: int = None):
    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    if self._should_skip_early_season(analysis_date):
        return  # Exit early

    # Existing process logic...
```

**Effort:** 2 hours

---

### File 2: Player Daily Cache Processor

- [ ] `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

**Key changes:**
1. Import from `shared.config.nba_season_dates`
2. Add skip logic to `process()` method
3. Calculate and populate games_used fields for L5, L10, season
4. Update quality score calculation
5. Update insufficient_data_reason format

**Code snippet:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def process(self, analysis_date: date, season_year: int = None):
    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    # Skip early season
    if is_early_season(analysis_date, season_year, days_threshold=7):
        logger.info(f"Skipping {analysis_date}: early season")
        return

    # Calculate with games_used tracking
    for player in players:
        l5_games = player_games.head(5)
        l10_games = player_games.head(10)

        record = {
            'points_avg_last_5': l5_games['points'].mean() if len(l5_games) > 0 else None,
            'points_avg_last_5_games_used': len(l5_games),  # NEW
            'points_avg_last_10': l10_games['points'].mean() if len(l10_games) > 0 else None,
            'points_avg_last_10_games_used': len(l10_games),  # NEW
            'points_avg_season': player_games['points'].mean(),
            'points_avg_season_games_used': len(player_games),  # NEW
            'early_season_flag': False,  # Past day 7
            'insufficient_data_reason': f'partial_window_L10_{len(l10_games)}_of_10' if len(l10_games) < 10 else None,
            # ... existing fields ...
        }
```

**Effort:** 2 hours

---

### File 3: Player Shot Zone Analysis Processor

- [ ] `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

**Key changes:**
1. Import from `shared.config.nba_season_dates`
2. Add skip logic to `process()` method

**Code snippet:**
```python
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

def process(self, analysis_date: date, season_year: int = None):
    if season_year is None:
        season_year = get_season_year_from_date(analysis_date)

    if is_early_season(analysis_date, season_year, days_threshold=7):
        logger.info(f"Skipping {analysis_date}: early season")
        return

    # Existing process logic...
```

**Effort:** 1 hour

---

### File 4: Team Defense Zone Analysis Processor

- [ ] `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`

**Note:** This file ALREADY imports from `shared.config.nba_season_dates` (lines 37-41)!

**Key changes:**
1. Add skip logic to `process()` method (same as shot zone above)

**Code snippet:** Same as File 3

**Effort:** 1 hour

---

### File 5: Player Composite Factors Processor (if exists)

- [ ] `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Check if file exists first**

**Key changes:** Same skip pattern as Files 3-4

**Effort:** 1 hour

---

## 🧪 Testing (No files to create - use BigQuery)

**Verification Queries:**

### Query 1: Verify Skip Logic
```sql
-- Should return 0 records
SELECT COUNT(*)
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2023-10-25' AND '2023-10-31';
```

### Query 2: Verify Partial Windows
```sql
-- Should show games_used < window_size
SELECT
  cache_date,
  player_lookup,
  points_avg_last_10,
  points_avg_last_10_games_used,
  ROUND(points_avg_last_10_games_used / 10.0, 2) as quality
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = '2023-11-01'
ORDER BY points_avg_last_10_games_used ASC
LIMIT 10;
```

### Query 3: Verify Accuracy
```sql
-- MAE should be <5.0 for Nov 1-15
WITH predictions AS (
  SELECT
    ABS(actual_points - predicted_points) as error
  FROM prediction_results
  WHERE prediction_date BETWEEN '2023-11-01' AND '2023-11-15'
)
SELECT AVG(error) as mae FROM predictions;
-- Expected: 4.5-4.8
```

**Test Dates:**
- **Skip:** 2023-10-25, 2023-10-26, 2023-10-31 (days 0-6)
- **Process:** 2023-11-01, 2023-11-06, 2023-12-01 (days 7+)

**Effort:** 2-3 hours

---

## Summary Checklist

### Phase 1: Config & Docs (2 hours)
- [ ] Update `shared/config/nba_season_dates.py`
- [ ] Update 3 documentation files
- [x] Create IMPLEMENTATION-PLAN.md
- [x] Create FILES-TO-MODIFY.md

### Phase 2: Schemas (1 hour)
- [ ] Update `player_daily_cache.sql` (add 3 fields)
- [ ] Update `ml_feature_store_v2.sql` (comments only)
- [ ] Run migration SQL on BigQuery

### Phase 3: Processors (6-8 hours)
- [ ] Update `ml_feature_store_processor.py`
- [ ] Update `player_daily_cache_processor.py`
- [ ] Update `player_shot_zone_analysis_processor.py`
- [ ] Update `team_defense_zone_analysis_processor.py`
- [ ] Update `player_composite_factors_processor.py` (if exists)

### Phase 4: Testing (2-3 hours)
- [ ] Run verification queries
- [ ] Test skip behavior (days 0-6)
- [ ] Test partial windows (day 7+)
- [ ] Verify accuracy matches investigation

### Phase 5: Deployment (1-2 weeks)
- [ ] Deploy to staging
- [ ] Test with historical data
- [ ] Code review
- [ ] Deploy to production
- [ ] Monitor logs

---

## Effort Summary

| Phase | Files | Hours |
|-------|-------|-------|
| Config & Docs | 4 | 2 |
| SQL Schemas | 2 | 1 |
| Processors | 4-5 | 6-8 |
| Testing | 0 | 2-3 |
| **TOTAL** | **10-11** | **11-14 hours** |

**Deployment:** 1-2 weeks
**First live validation:** October 2025

---

## Quick Start

**If you're ready to start implementation:**

1. Read `IMPLEMENTATION-PLAN.md` (complete context)
2. Start with Phase 1 (config + docs)
3. Then Phase 2 (schemas + migration)
4. Then Phase 3 (processors in order):
   - ml_feature_store
   - player_daily_cache
   - shot_zone_analysis
   - team_defense_zone_analysis
5. Test thoroughly before deployment

**Questions?** See IMPLEMENTATION-PLAN.md Q&A sections

---

**All files identified and scoped!** ✅
