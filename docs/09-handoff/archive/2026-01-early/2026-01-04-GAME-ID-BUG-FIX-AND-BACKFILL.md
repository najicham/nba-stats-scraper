# 🐛 game_id Mismatch Bug Fix & Full Backfill
**Date**: January 4, 2026
**Session**: Session 5 ML Training - Bug Fix Phase
**Status**: 🔄 IN PROGRESS

---

## 🚨 CRITICAL BUG DISCOVERED

### The Problem: game_id Format Mismatch

During ML training data quality validation, discovered that **usage_rate was 52.61% NULL** despite team offense data existing in the database.

**Root Cause**: Different game_id formats between tables prevent JOINs from working.

### Example:
```
Game: Denver @ Houston on 2022-01-01

player_game_summary table:
  game_id: "20220101_DEN_HOU"  (AWAY_HOME format)

team_offense_game_summary table:
  game_id: "20220101_HOU_DEN"  (source format from NBA.com)

JOIN result: NULL ❌ (no match!)
```

**Impact**:
- usage_rate calculation requires: `player FGA / team FGA` (needs team stats)
- JOIN fails → no team stats → usage_rate = NULL
- Affects 52.61% of records (43,977 out of 83,597)
- Blocks ML model from learning accurate usage patterns

---

## 🔍 ROOT CAUSE ANALYSIS

### Data Flow Investigation

1. **Player Analytics** (`nba_analytics.player_game_summary`):
   - Source: `nba_raw.nbac_gamebook_player_stats`
   - game_id format: `20220101_DEN_HOU` (AWAY_HOME)
   - Consistently uses AWAY_HOME format

2. **Team Analytics** (`nba_analytics.team_offense_game_summary`):
   - Source: `nba_raw.nbac_team_boxscore`
   - game_id format: Variable (sometimes HOME_AWAY, inconsistent)
   - Passed through directly from NBA.com source

### Why This Bug Existed

The team_offense processor was using game_id directly from `nbac_team_boxscore` without standardization:

```sql
-- OLD CODE (buggy)
SELECT
    tb.game_id,  -- Direct from source, inconsistent format
    tb.team_abbr,
    ...
FROM nba_raw.nbac_team_boxscore tb
```

Meanwhile, player_game_summary JOIN logic expected AWAY_HOME format:

```sql
-- Player processor JOIN (expected AWAY_HOME)
LEFT JOIN nba_analytics.team_offense_game_summary togs
  ON pgs.game_id = togs.game_id  -- FAILS when formats don't match!
  AND pgs.team_abbr = togs.team_abbr
```

---

## ✅ THE FIX

### Code Change: Standardize game_id Construction

**File**: `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`

**Change**: Lines 336-357 (team_boxscores CTE)

```sql
-- NEW CODE (fixed)
team_boxscores AS (
    SELECT
        -- FIX: Standardize game_id to AWAY_HOME format for consistent JOINs
        -- Player analytics uses AWAY_HOME format, so team analytics must match
        CASE
            WHEN tb.is_home THEN CONCAT(
                FORMAT_DATE('%Y%m%d', tb.game_date),
                '_',
                t2.team_abbr,  -- away team (opponent when we're home)
                '_',
                tb.team_abbr   -- home team (us)
            )
            ELSE CONCAT(
                FORMAT_DATE('%Y%m%d', tb.game_date),
                '_',
                tb.team_abbr,  -- away team (us)
                '_',
                t2.team_abbr   -- home team (opponent when we're away)
            )
        END as game_id,
        tb.nba_game_id,  -- Original NBA game ID preserved
        ...
```

**Logic**:
- Use `is_home` flag to determine home/away status
- Construct game_id in AWAY_HOME format: `{date}_{away}_{home}`
- Always consistent regardless of source data format

---

## 🔄 BACKFILL STRATEGY

### Phase 1: Team Offense Backfill ✅ IN PROGRESS
**Status**: Running (started ~5:15 PM EST)
**Command**:
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  --no-resume
```

**Date Range**: 2021-10-01 to 2024-05-01 (944 days)
**Mode**: Sequential (day-by-day)
**Expected Duration**: ~60-90 minutes
**Purpose**: Reprocess all team offense data with corrected game_id format

### Phase 2: Player Game Summary Re-backfill ⏳ PENDING
**Purpose**: Recalculate usage_rate using corrected team data
**Command**:
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-05-01 \
  --parallel \
  --workers 15 \
  --no-resume
```

**Expected Duration**: ~30 minutes (parallel mode)
**Purpose**: JOIN with fixed team data to calculate usage_rate

---

## 📊 EXPECTED IMPROVEMENTS

### Before Fix:
| Feature | NULL Rate | Impact |
|---------|-----------|--------|
| minutes_played | 0.16% | ✅ Good |
| usage_rate | **52.61%** | ❌ BROKEN |
| paint_attempts | 11.88% | ✅ Good |

### After Fix (Expected):
| Feature | NULL Rate | Impact |
|---------|-----------|--------|
| minutes_played | 0.16% | ✅ Good |
| usage_rate | **< 5%** | ✅ FIXED! |
| paint_attempts | 11.88% | ✅ Good |

**ML Impact**:
- usage_rate is expected to be a top 10 feature (15-25% importance)
- Current model trains on 53% fake data (defaults to 25.0)
- Fixed model will train on 95%+ real data
- Expected improvement: 4.56 MAE → 4.0-4.2 MAE (beats 4.27 baseline)

---

## ⏱️ TIMELINE

**5:00 PM EST**: Bug discovered during data quality validation
**5:15 PM EST**: Root cause identified (game_id mismatch)
**5:20 PM EST**: Code fix implemented and tested
**5:25 PM EST**: Phase 1 backfill started (team_offense)
**~6:30 PM EST**: Phase 1 expected completion
**~6:35 PM EST**: Phase 2 backfill start (player_game_summary)
**~7:05 PM EST**: Phase 2 expected completion
**~7:10 PM EST**: Data quality verification
**~7:15 PM EST**: ML training start
**~7:35 PM EST**: ML training completion & results

**Total Estimated Time**: 2 hours 35 minutes from bug discovery to trained model

---

## 🎯 SUCCESS CRITERIA

### Phase 1 Success (Team Offense Backfill):
- [ ] 99%+ success rate (allowing for All-Star weekend)
- [ ] All game_ids in AWAY_HOME format
- [ ] JOINs with player data succeed

### Phase 2 Success (Player Re-backfill):
- [ ] usage_rate NULL rate < 5%
- [ ] All 21 ML features have acceptable NULL rates
- [ ] Ready for ML training

### Final Success (ML Training):
- [ ] Test MAE < 4.27 (beats baseline)
- [ ] usage_rate in top 10 features
- [ ] No overfitting (train/val/test consistent)

---

## 📝 LESSONS LEARNED

### What Went Wrong:
1. **Assumed source data consistency**: Trusted NBA.com game_id format
2. **No validation**: JOIN failures were silent (NULL results)
3. **Incremental development**: Team and player processors built separately

### Prevention for Future:
1. **Standardize identifiers**: Always construct game_id in canonical format
2. **Validate JOINs**: Add assertions that JOINs find expected matches
3. **Integration tests**: Test cross-table JOINs in CI/CD
4. **Documentation**: Document identifier formats in schema comments

### Infrastructure Improvements Needed:
- Add CHECK constraints on game_id format
- Create shared game_id construction function
- Add JOIN success rate monitoring
- Document canonical formats in style guide

---

## 🔗 RELATED WORK

**Previous Bugs Fixed**:
- `minutes_played` NULL coercion bug (Commit: 83d91e2)
- `usage_rate` never implemented (Commit: 390caba)
- Shot distribution regression (Commit: 390caba)

**This Bug**:
- Blocked usage_rate from working despite implementation
- Shows importance of end-to-end validation
- Demonstrates need for integration testing

---

**Status**: 🔄 Backfill Phase 1 in progress
**Next Update**: After Phase 1 completion (~6:30 PM EST)
