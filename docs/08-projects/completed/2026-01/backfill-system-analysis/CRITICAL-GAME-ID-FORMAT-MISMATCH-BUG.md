# CRITICAL: game_id Format Mismatch Between Analytics Tables

**Date**: January 4, 2026, 3:10 PM PST
**Severity**: HIGH - Blocks ML training from achieving expected performance
**Status**: BLOCKING - Requires immediate fix
**Discovered By**: ML Training Session during data validation

---

## EXECUTIVE SUMMARY

**Problem**: `team_offense_game_summary` uses **reversed game_id format** compared to `player_game_summary`, causing JOIN failures and 47% usage_rate coverage instead of expected 95%.

**Impact**:
- usage_rate feature only available for 47% of training data
- Expected ML model performance degradation: 4.0-4.2 MAE → likely 4.27+ MAE
- Blocks ability to beat 4.27 MAE baseline

**Root Cause**: game_id format inconsistency between analytics tables
- `player_game_summary`: `YYYYMMDD_AWAY_HOME`
- `team_offense_game_summary`: `YYYYMMDD_HOME_AWAY` ← **REVERSED!**

**Data Completeness**: ✅ Data exists for 2021-2024 (3,929 games in both tables)
**Bug Type**: Format mismatch, NOT missing data

---

## DISCOVERY TIMELINE

### Context
ML training session validating 2021-2024 training data before training XGBoost v5.

### Step 1: Validation Revealed Low usage_rate Coverage
```bash
./scripts/validation/validate_player_summary.sh 2021-10-01 2024-05-01
```

**Results**:
- ✅ Record count: 83,644 (threshold: 35,000+)
- ✅ minutes_played: 99.8% (threshold: 99.0%+)
- ❌ usage_rate: 47.7% (threshold: 95.0%+) ← **UNEXPECTED!**
- ✅ shot_zones: 88.1% (threshold: 40.0%+)

**Expected**: 95%+ coverage based on commit 390caba message
**Actual**: 47.7% coverage

### Step 2: Investigated Team Coverage by Year
```sql
SELECT
  DATE_TRUNC(game_date, YEAR) as year,
  COUNT(DISTINCT game_id) as total_games_in_player_summary,
  COUNT(DISTINCT CASE WHEN usage_rate IS NOT NULL THEN game_id END) as games_with_usage_rate,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN usage_rate IS NOT NULL THEN game_id END) / COUNT(DISTINCT game_id), 1) as coverage_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
GROUP BY year
ORDER BY year
```

**Results**:
| Year | Total Games | Games with usage_rate | Coverage % |
|------|-------------|----------------------|------------|
| 2021 | 538 | 255 | 47.4% |
| 2022 | 1,350 | 690 | 51.1% |
| 2023 | 1,257 | 623 | 49.6% |
| 2024 | 794 | 390 | 49.1% |

**Finding**: Consistent ~50% coverage across ALL years (not just recent seasons)

### Step 3: Checked team_offense_game_summary Completeness
```sql
SELECT
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  COUNT(DISTINCT game_date) as distinct_dates,
  COUNT(DISTINCT game_id) as distinct_games,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
```

**Results**:
- Earliest: 2021-10-19
- Latest: 2024-05-01
- Games: **3,929** ← Nearly matches player_game_summary (3,939)!
- Records: 7,858 (2 per game: home + away)

**Finding**: ✅ Data IS complete in team_offense! Not a missing data issue.

### Step 4: Investigated JOIN Match Rate
```sql
SELECT
  COUNT(DISTINCT pg.game_id) as player_games,
  COUNT(DISTINCT tg.game_id) as team_games,
  COUNT(DISTINCT CASE WHEN tg.game_id IS NOT NULL THEN pg.game_id END) as matched_games,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN tg.game_id IS NOT NULL THEN pg.game_id END) / COUNT(DISTINCT pg.game_id), 1) as match_rate_pct
FROM `nba-props-platform.nba_analytics.player_game_summary` pg
LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` tg
  ON pg.game_id = tg.game_id AND tg.game_date BETWEEN '2021-10-01' AND '2024-05-01'
WHERE pg.game_date BETWEEN '2021-10-01' AND '2024-05-01'
```

**Results**:
| player_games | team_games | matched_games | match_rate_pct |
|--------------|------------|---------------|----------------|
| 3,939 | 1,958 | 1,958 | 49.7% |

**Finding**: Only 49.7% of games match in JOIN despite both tables having ~3,929 games!

### Step 5: Discovered game_id Format Mismatch

**Sampled game_ids from player_game_summary**:
```
20240104_DEN_GSW
20240104_MIL_SAS
```

**Sampled game_ids from team_offense_game_summary**:
```
20240104_GSW_DEN  ← DEN and GSW are REVERSED!
20240104_SAS_MIL  ← MIL and SAS are REVERSED!
```

**Format Analysis**:
- `player_game_summary`: `YYYYMMDD_AWAY_HOME` (standard NBA format)
- `team_offense_game_summary`: `YYYYMMDD_HOME_AWAY` (reversed!)

### Step 6: Confirmed Fix with Reversed game_id
```sql
WITH reversed_team_games AS (
  SELECT
    CONCAT(
      SUBSTR(game_id, 1, 9),  -- Date part
      SUBSTR(game_id, 14, 3), -- Home team (move to away position)
      '_',
      SUBSTR(game_id, 10, 3)  -- Away team (move to home position)
    ) as reversed_game_id,
    game_id as original_game_id
  FROM team_offense_game_summary
  WHERE game_date = '2024-01-04'
)
SELECT
  pg.game_id as player_format,
  tg.original_game_id as team_format,
  tg.reversed_game_id as team_reversed
FROM player_game_summary pg
LEFT JOIN reversed_team_games tg ON pg.game_id = tg.reversed_game_id
WHERE pg.game_date = '2024-01-04'
```

**Results**:
| player_format | team_format | team_reversed |
|---------------|-------------|---------------|
| 20240104_DEN_GSW | 20240104_GSW_DEN | 20240104_DEN_GSW ✅ |
| 20240104_MIL_SAS | 20240104_SAS_MIL | 20240104_MIL_SAS ✅ |

**Finding**: ✅ Reversing team_offense game_ids creates perfect match!

---

## ROOT CAUSE ANALYSIS

### The Bug
`team_offense_game_summary` processor generates game_id in **HOME_AWAY** format, while:
- `player_game_summary` uses **AWAY_HOME** format
- Standard NBA convention is **AWAY_HOME** format

### Why This Breaks usage_rate
From `player_game_summary_processor.py:546`:
```python
LEFT JOIN team_stats ts ON wp.game_id = ts.game_id AND wp.team_abbr = ts.team_abbr
```

When game_ids don't match:
1. LEFT JOIN returns NULL for team stats
2. usage_rate calculation fails (needs team_fg_attempts, team_possessions, etc.)
3. usage_rate set to NULL
4. Result: 50% of records have NULL usage_rate

### Why 50% Match Rate?
Some games accidentally match when home/away teams are alphabetically swapped:
- Game: BOS @ NYK
- player_game_summary: `20240104_BOS_NYK` ✅
- team_offense (if BOS home): `20240104_BOS_NYK` ✅ Matches!
- team_offense (if NYK home): `20240104_NYK_BOS` ❌ No match

This creates ~50% accidental match rate.

---

## IMPACT ASSESSMENT

### On ML Training
**Expected Performance** (with 95% usage_rate coverage):
- Test MAE: 4.0-4.2 (beats 4.27 baseline by 2-6%)

**Likely Performance** (with 47% usage_rate coverage):
- Test MAE: 4.27+ (does NOT beat baseline)
- Missing critical feature for 53% of training data
- Model cannot learn proper usage_rate relationships

### On Production Pipeline
- ✅ Recent data (Oct 2025 - Jan 2026): Likely affected same way
- ✅ All analytics depending on player+team JOINs: Affected
- ✅ Phase 4 precompute: May inherit same issue

---

## RECOMMENDED FIXES

### Option 1: Fix team_offense Processor (RECOMMENDED)
**Fix**: Update `team_offense_game_summary_processor.py` to use AWAY_HOME format

**Pros**:
- Aligns with NBA standard convention
- Fixes issue at the source
- All downstream processors benefit

**Cons**:
- Requires full team_offense backfill (2021-01-01 to present)
- ~4,000+ games to reprocess

**Implementation**:
1. Locate game_id generation in `team_offense_game_summary_processor.py`
2. Change from `{home}_{away}` to `{away}_{home}` format
3. Deploy processor
4. Backfill 2021-01-01 to 2026-01-04
5. Validate with usage_rate coverage check

### Option 2: Fix player_game_summary Processor (NOT RECOMMENDED)
**Fix**: Update JOIN logic to reverse team_offense game_ids on-the-fly

**Pros**:
- No team_offense backfill needed
- Quick fix

**Cons**:
- Workaround, not root cause fix
- Adds complexity to player_game_summary processor
- Other processors may have same issue
- Doesn't fix root inconsistency

**Implementation**:
```sql
LEFT JOIN team_stats ts ON
  CONCAT(
    SUBSTR(wp.game_id, 1, 9),
    SUBSTR(wp.game_id, 14, 3),
    '_',
    SUBSTR(wp.game_id, 10, 3)
  ) = ts.game_id
  AND wp.team_abbr = ts.team_abbr
```

### Option 3: Fix team_offense Data (TEMPORARY WORKAROUND)
**Fix**: Run SQL UPDATE to reverse game_ids in existing data

**Pros**:
- No processor changes needed
- No backfill needed
- Immediate fix

**Cons**:
- Data corruption risk
- Future data will still be wrong
- Must remember to fix processor too

---

## VALIDATION QUERIES

### After Fix: Verify usage_rate Coverage
```sql
SELECT
  COUNT(*) as total_records,
  COUNTIF(usage_rate IS NOT NULL) as with_usage_rate,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as coverage_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
```

**Expected After Fix**: coverage_pct ≥ 95%

### Verify game_id Formats Match
```sql
-- Check player_game_summary format
SELECT DISTINCT
  SUBSTR(game_id, 10, 7) as team_portion,
  game_id
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2024-01-04'
LIMIT 3;

-- Check team_offense_game_summary format
SELECT DISTINCT
  SUBSTR(game_id, 10, 7) as team_portion,
  game_id
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date = '2024-01-04'
LIMIT 3;
```

**Expected After Fix**: Both should show same team_portion order (AWAY_HOME)

### Verify JOIN Success Rate
```sql
SELECT
  COUNT(DISTINCT pg.game_id) as player_games,
  COUNT(DISTINCT CASE WHEN ts.game_id IS NOT NULL THEN pg.game_id END) as matched_games,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN ts.game_id IS NOT NULL THEN pg.game_id END) / COUNT(DISTINCT pg.game_id), 1) as match_rate_pct
FROM `nba-props-platform.nba_analytics.player_game_summary` pg
LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` ts
  ON pg.game_id = ts.game_id AND ts.game_date BETWEEN '2021-10-01' AND '2024-05-01'
WHERE pg.game_date BETWEEN '2021-10-01' AND '2024-05-01'
```

**Expected After Fix**: match_rate_pct ≥ 99%

---

## NEXT STEPS

### For Backfill Chat:
1. **Locate** game_id generation in `team_offense_game_summary_processor.py`
2. **Fix** format to AWAY_HOME (match player_game_summary convention)
3. **Deploy** updated processor
4. **Backfill** 2021-01-01 to 2026-01-04 (full historical data)
5. **Validate** using queries above
6. **Trigger** player_game_summary re-processing (to recalculate usage_rate)

### For ML Training Chat:
**Decision Point**: Train now or wait for fix?

**Option A: Train Now (47% coverage)**
- Pros: See if we can beat baseline anyway
- Cons: Likely won't beat 4.27 MAE
- Use case: Proof-of-concept, baseline comparison

**Option B: Wait for Fix (95% coverage)**
- Pros: Expected 4.0-4.2 MAE (beats baseline!)
- Cons: Depends on backfill completion time
- Use case: Production-ready model

**Recommendation**: Depends on user priority (speed vs quality)

---

## EVIDENCE & DATA

### Query Results Summary
```
Training Period: 2021-10-01 to 2024-05-01

player_game_summary:
- Records: 83,644
- Games: 3,939
- usage_rate coverage: 47.7%

team_offense_game_summary:
- Records: 7,858
- Games: 3,929
- Coverage: 99.7% of player games exist

JOIN Match Rate: 49.7% ← BUG!
Expected Match Rate: 99%+
```

### Sample game_id Comparison
```
Date: 2024-01-04
Game: Denver @ Golden State

player_game_summary:  20240104_DEN_GSW (AWAY_HOME) ✅ Correct
team_offense:         20240104_GSW_DEN (HOME_AWAY) ❌ Reversed
Result:               No JOIN match → usage_rate = NULL
```

---

## RELATED DOCUMENTS

- `/docs/09-handoff/2026-01-04-ML-TRAINING-SESSION-HANDOFF.md` - Context on ML training expectations
- `/docs/08-projects/current/backfill-system-analysis/` - Backfill system documentation
- Commit 390caba - usage_rate implementation (expected 95% coverage)

---

## CONTACT

**Discovered by**: ML Training Session
**Date**: January 4, 2026, 3:10 PM PST
**Session**: ML model v5 training preparation

**Status**: Blocked pending fix
**Priority**: HIGH - Blocks ML model from beating baseline
