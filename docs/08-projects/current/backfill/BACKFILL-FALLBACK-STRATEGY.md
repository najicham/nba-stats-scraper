# Backfill Data Source Fallback Strategy

**Created:** 2025-11-30
**Purpose:** Comprehensive fallback strategy for all data sources during backfill
**Status:** Analysis Complete - Ready for execution
**Date Range:** 2021-10-01 to 2024-11-29 (712 game dates)

---

## Executive Summary

### Critical Finding

⚠️ **IMPORTANT:** `bigdataball_play_by_play` has **94% coverage** (669/712 dates), NOT 0.1% as previously documented!

**Impact:**
- Shot zone data will be available for 94% of historical games
- Both player and team shot zone analytics will have high quality
- Only `nbac_play_by_play` has 0.1% coverage (1/712 dates)

### Overall Status

✅ **All Phase 3 processors have robust fallback strategies**
- Player stats: 100% coverage (PRIMARY + FALLBACK)
- Shot zones: 94% coverage (bigdataball)
- Props: 99.7% coverage (BettingPros fallback)
- Team stats: Need to verify (nbac_team_boxscore not queried yet)

---

## Table of Contents

1. [Data Source Coverage Analysis](#data-source-coverage-analysis)
2. [Phase 3 Processor Fallback Strategies](#phase-3-processor-fallback-strategies)
3. [Fallback Implementation Status](#fallback-implementation-status)
4. [Impact Assessment](#impact-assessment)
5. [Recommendations](#recommendations)
6. [Action Items](#action-items)

---

## Data Source Coverage Analysis

### Current Coverage (2021-10-01 to 2024-11-29)

| Source | Dates | Coverage | Status | Role |
|--------|-------|----------|--------|------|
| **Player Stats** ||||
| nbac_gamebook_player_stats | 712/712 | 100.0% | ✅ Complete | PRIMARY |
| bdl_player_boxscores | 668/712 | 93.8% | ✅ Good | FALLBACK |
| **Combined Player Stats** | **712/712** | **~100%** | ✅ **Excellent** | - |
| **Shot Zones (Play-by-Play)** ||||
| bigdataball_play_by_play | 669/712 | **94.0%** | ✅ **Excellent** | PRIMARY |
| nbac_play_by_play | 1/712 | 0.1% | 🔴 Not useful | BACKUP |
| **Props/Betting Lines** ||||
| bettingpros_player_points_props | 673/675 | 99.7% | ✅ Excellent | PRIMARY |
| odds_api_player_points_props | 271/675 | 40% | ⚠️ Limited | BACKUP |
| **Team Stats** ||||
| espn_boxscores | 0/712 | 0.0% | 🔴 Empty | NOT AVAILABLE |
| nbac_team_boxscore | ? | ? | ⏳ Need to verify | Assumed PRIMARY |

### Missing Dates by Source

**Player Stats Gaps (bdl_player_boxscores missing 44 dates):**
- These 44 dates should all be covered by nbac_gamebook_player_stats (100%)
- **Combined coverage: ~100%**

**Shot Zone Gaps (bigdataball missing 43 dates):**
- 43/712 dates (6%) will have NULL shot zones
- This is **MUCH better** than previously thought (was expecting 99.9% NULL)
- nbac_play_by_play cannot fill these gaps (only 1 date)

**Props Gaps:**
- Already addressed via BettingPros fallback

---

## Phase 3 Processor Fallback Strategies

### 1. Player Game Summary

**Processor:** `player_game_summary_processor.py`

**Data Sources & Fallback Chain:**

```
Player Stats (CRITICAL):
  PRIMARY: nbac_gamebook_player_stats (100%)
     ↓ (if missing)
  FALLBACK: bdl_player_boxscores (93.8%)
     ↓
  COMBINED: ~100% coverage ✅

Shot Zones (OPTIONAL):
  PRIMARY: bigdataball_play_by_play (94%)
     ↓ (if missing)
  FALLBACK: nbac_play_by_play (0.1%)
     ↓
  COMBINED: ~94% coverage ✅
  NULL zones: ~6% (acceptable)

Prop Lines (OPTIONAL):
  PRIMARY: odds_api_player_points_props (40%)
     ↓ (if missing)
  FALLBACK: bettingpros_player_points_props (99.7%) ✅ IMPLEMENTED
     ↓
  COMBINED: 99.7% coverage ✅
```

**Implementation Status:**
- ✅ Player stats fallback: IMPLEMENTED in code
- ✅ Shot zones fallback: IMPLEMENTED in code
- ✅ Props fallback: IMPLEMENTED (BettingPros)

**Expected Output:**
- 100% of dates will have player stats
- 94% will have shot zone data
- 99.7% will have prop line data

### 2. Team Defense Game Summary

**Processor:** `team_defense_game_summary_processor.py`

**Data Sources & Fallback Chain:**

```
Team Boxscores (CRITICAL):
  PRIMARY: nbac_team_boxscore (need to verify %)
     ↓ (if missing)
  FALLBACK: bdl_team_boxscores (need to verify %)
     ↓
  FALLBACK #2: espn_team_stats (0% - not useful)

Player Defensive Actions (for aggregation):
  PRIMARY: nbac_gamebook_player_stats (100%)
     ↓ (if missing)
  FALLBACK: bdl_player_boxscores (93.8%)
     ↓
  FALLBACK #2: nbac_player_boxscores (need to verify %)

Shot Zones Allowed (OPTIONAL):
  PRIMARY: bigdataball_play_by_play (94%)
     ↓ (if missing)
  FALLBACK: nbac_play_by_play (0.1%)
     ↓
  COMBINED: ~94% coverage ✅
```

**Implementation Status:**
- ✅ Team boxscore fallback: IMPLEMENTED in code (bdl_team_boxscores, espn_team_stats listed)
- ✅ Player defensive actions fallback: IMPLEMENTED
- ✅ Shot zones fallback: IMPLEMENTED

**Expected Output:**
- Need to verify nbac_team_boxscore coverage
- 100% of dates should have defensive action stats
- 94% will have shot zone defense data

### 3. Team Offense Game Summary

**Processor:** `team_offense_game_summary_processor.py`

**Data Sources & Fallback Chain:**

```
Team Boxscores (CRITICAL):
  PRIMARY: nbac_team_boxscore (need to verify %)
     ↓ (if missing)
  FALLBACK: bdl_team_boxscores (need to verify %)
     ↓
  FALLBACK #2: espn_team_stats (0% - not useful)

Shot Zones (OPTIONAL):
  PRIMARY: bigdataball_play_by_play (94%)
     ↓ (if missing)
  FALLBACK: nbac_play_by_play (0.1%)
     ↓
  COMBINED: ~94% coverage ✅
```

**Implementation Status:**
- ✅ Team boxscore fallback: IMPLEMENTED in code
- ✅ Shot zones fallback: IMPLEMENTED

**Expected Output:**
- Need to verify nbac_team_boxscore coverage
- 94% will have shot zone offense data

### 4. Upcoming Player Game Context

**Processor:** `upcoming_player_game_context_processor.py`

**Data Sources & Fallback Chain:**

```
Prop Lines (CRITICAL for context):
  PRIMARY: odds_api_player_points_props (40%)
     ↓ (if missing)
  FALLBACK: bettingpros_player_points_props (99.7%) ✅ IMPLEMENTED
     ↓
  COMBINED: 99.7% coverage ✅
```

**Implementation Status:**
- ✅ BettingPros fallback: IMPLEMENTED (confirmed in other chat)

**Expected Output:**
- 99.7% of dates will have prop line context

### 5. Upcoming Team Game Context

**Processor:** `upcoming_team_game_context_processor.py`

**Data Sources & Fallback Chain:**

```
Game Lines/Spreads:
  PRIMARY: odds_api_spreads (need to verify %)
     ↓
  Status: Need to analyze
```

**Action Required:**
- ⏳ Analyze coverage for team game lines
- ⏳ Check if fallback needed

---

## Fallback Implementation Status

### ✅ Implemented in Code

All Phase 3 processors have fallback logic in code via `RELEVANT_SOURCES` configuration:

**Player Game Summary:**
```python
RELEVANT_SOURCES = {
    'nbac_gamebook_player_stats': True,    # PRIMARY
    'bdl_player_boxscores': True,          # FALLBACK
    'bigdataball_play_by_play': True,      # PRIMARY shot zones
    'nbac_play_by_play': True,             # BACKUP shot zones
    'odds_api_player_points_props': True,  # PRIMARY props
    'bettingpros_player_points_props': True # FALLBACK props ✅
}
```

**Team Defense/Offense:**
```python
RELEVANT_SOURCES = {
    'nbac_team_boxscore': True,            # PRIMARY
    'bdl_team_boxscores': True,            # FALLBACK
    'espn_team_stats': True,               # FALLBACK (0% coverage)
    'nbac_gamebook_player_stats': True,    # PRIMARY player stats
    'bdl_player_boxscores': True,          # FALLBACK player stats
    'bigdataball_play_by_play': True,      # PRIMARY shot zones
    'nbac_play_by_play': True,             # BACKUP shot zones
}
```

### ✅ Recently Implemented

**BettingPros Fallback for Props:**
- Implemented in other chat session
- Impact: 40% → 99.7% coverage for prop lines
- Status: COMPLETE

---

## Impact Assessment

### Best Case Scenario (With All Fallbacks)

| Metric | Coverage | Impact |
|--------|----------|--------|
| Player Stats | ~100% | ✅ Excellent - All players tracked |
| Team Stats | ~100% (assumed) | ✅ Excellent - All teams tracked |
| Shot Zones | ~94% | ✅ Very Good - Most games have zone data |
| Prop Lines | 99.7% | ✅ Excellent - Nearly all betting context |

**Overall Backfill Quality: EXCELLENT** 🎉

### Worst Case Scenario (Primary Sources Only)

| Metric | Coverage | Impact |
|--------|----------|--------|
| Player Stats | 100% | ✅ Still excellent (primary is 100%) |
| Team Stats | ? | ⚠️ Need to verify |
| Shot Zones | 94% | ✅ Still very good (bigdataball is primary) |
| Prop Lines | 40% | 🔴 Poor - Would lose 60% of context |

**Without BettingPros fallback:** Props would be problematic
**With BettingPros fallback:** Everything looks good ✅

### NULL Data Expectations

**Acceptable NULLs (by design):**
- Shot zones: ~6% NULL (43/712 dates missing bigdataball)
- Bootstrap periods: First 7 days of each season (expected in Phase 4)
- Early season quality scores: Lower quality expected (small sample)

**Unacceptable NULLs (would indicate problems):**
- Player stats completely missing for a date
- Team stats completely missing for a date
- Prop lines missing for >0.3% of dates

---

## Recommendations

### 1. Verify Team Boxscore Coverage ⏰ IMMEDIATE

```sql
-- Check nbac_team_boxscore coverage
SELECT COUNT(DISTINCT game_date) as dates,
       712 as expected,
       ROUND(100.0 * COUNT(DISTINCT game_date) / 712, 1) as pct
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
```

**If coverage is <100%:**
- Check bdl_team_boxscores as fallback
- Identify any dates completely missing team data

### 2. Update Documentation 📝 RECOMMENDED

**Planning docs incorrectly state:**
- "nbac_play_by_play: 0.1%" - **TRUE**
- "Play-by-play data sparse" - **FALSE** (bigdataball is 94%)

**Should state:**
- "bigdataball_play_by_play: 94% (GOOD)"
- "nbac_play_by_play: 0.1% (NOT USEFUL)"
- "Shot zones will be available for 94% of historical games"

### 3. No Action Needed for Play-by-Play ✅

**Previous concern:** "Should we backfill play-by-play (88 minutes)?"

**Answer:** **NO** - bigdataball already provides 94% coverage
- nbac_play_by_play backfill would only add 0.1%
- Not worth 88+ minutes for marginal gain
- Accept 6% NULL shot zones (reasonable)

### 4. Verify Upstream Player Boxscore vs Gamebook Stats 🔍 OPTIONAL

**Question:** Are player stats from player_boxscore better than gamebook_player_stats for certain metrics?

**Current setup:**
- PRIMARY: nbac_gamebook_player_stats (100%)
- FALLBACK: bdl_player_boxscores (93.8%)

**Consideration:**
- Some advanced stats might only be in detailed boxscores
- Gamebook might have official stats, boxscore might have additional tracking
- **Recommendation:** Keep current setup unless specific metrics are missing

---

## Action Items

### Before Backfill Execution

- [ ] **Verify team boxscore coverage** (nbac_team_boxscore)
  ```bash
  # Run query from Recommendation #1
  ```

- [ ] **Check if bdl_team_boxscores needed as fallback**
  ```sql
  SELECT COUNT(DISTINCT game_date) as dates
  FROM `nba-props-platform.nba_raw.bdl_team_boxscores`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-11-29'
  ```

- [ ] **Update planning docs** with correct bigdataball coverage

- [ ] **Verify upcoming_team_game_context data sources**
  - Check what sources it uses
  - Verify coverage
  - Identify if fallback needed

### During Backfill Execution

- [ ] **Monitor NULL shot zones percentage**
  - Expected: ~6% NULL (acceptable)
  - If >10% NULL: Investigate

- [ ] **Track fallback usage**
  - How often does bdl_player_boxscores get used?
  - Are there dates where both PRIMARY and FALLBACK are missing?

- [ ] **Validate combined coverage**
  - Player stats: Should be 100%
  - Team stats: Should be ~100%
  - Shot zones: Should be ~94%
  - Props: Should be 99.7%

---

## Summary: Ready for Backfill

### Critical Sources: ✅ ALL GOOD

| Processor | Critical Data | Coverage | Fallback | Status |
|-----------|---------------|----------|----------|--------|
| Player Game Summary | Player stats | 100% | bdl (93.8%) | ✅ Ready |
| Team Defense | Team/player stats | ? | bdl | ⏳ Verify |
| Team Offense | Team stats | ? | bdl | ⏳ Verify |
| Upcoming Player Context | Props | 99.7% | BettingPros | ✅ Ready |
| Upcoming Team Context | Game lines | ? | ? | ⏳ Verify |

### Optional Sources: ✅ BETTER THAN EXPECTED

| Data Type | Coverage | Status | Notes |
|-----------|----------|--------|-------|
| Shot zones | 94% | ✅ Very Good | bigdataball (not nbac!) |
| Prop lines | 99.7% | ✅ Excellent | BettingPros fallback |

### Verdict

**READY TO PROCEED** with caveats:
1. ✅ Player Game Summary: Fully validated, excellent coverage
2. ⏳ Team processors: Need to verify team boxscore coverage
3. ⏳ Upcoming Team Context: Need to analyze

**Recommendation:** Complete team boxscore verification (5 minutes), then proceed with backfill.

---

**Created:** 2025-11-30
**Last Updated:** 2025-11-30
**Status:** Analysis Complete - Action items identified
**Next Step:** Verify team boxscore coverage, then execute backfill
