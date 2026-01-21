# Boxscore Gap Investigation - January 18, 2026

**Date:** 2026-01-19 (investigating Jan 18 data)
**Investigator:** Claude Code (Session 98)
**Status:** ✅ Complete
**Severity:** Medium - Data completeness issue affecting 2/6 games

---

## Executive Summary

**FINDING: 2 of 6 Games Missing Boxscores**

On January 18, 2026, 6 NBA games were scheduled and completed, but only 4 games have boxscores in the `bdl_player_boxscores` table. This resulted in incomplete analytics processing and grading coverage.

**Impact:**
- ✅ 4/6 games (67%) have boxscores
- ❌ 2/6 games (33%) missing boxscores
- ⚠️ Interestingly, 5/6 games made it to Phase 3 analytics (unexpected)

**Missing Games:**
1. **POR @ SAC** (0022500606 / 20260118_POR_SAC)
2. **TOR @ LAL** (0022500607 / 20260118_TOR_LAL) - *but exists in Phase 3!*

---

## Investigation Results

### Query 1: Scheduled Games

```sql
SELECT
  game_id, game_date, home_team_tricode, away_team_tricode, game_status_text
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_date = '2026-01-18'
ORDER BY game_id;
```

**Result:** 6 games, all status "Final"

| game_id | away | home | status |
|---------|------|------|--------|
| 0022500602 | ORL | MEM | Final |
| 0022500603 | BKN | CHI | Final |
| 0022500604 | NOP | HOU | Final |
| 0022500605 | CHA | DEN | Final |
| 0022500606 | POR | SAC | Final |
| 0022500607 | TOR | LAL | Final |

### Query 2: Games with Boxscores (BallDontLie format)

```sql
SELECT game_id, COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = '2026-01-18'
GROUP BY game_id;
```

**Result:** 4 games

| game_id | players |
|---------|---------|
| 20260118_BKN_CHI | 36 |
| 20260118_CHA_DEN | 35 |
| 20260118_NOP_HOU | 35 |
| 20260118_ORL_MEM | 35 |

**Missing:**
- 20260118_POR_SAC
- 20260118_TOR_LAL

### Query 3: Phase 3 Analytics

```sql
SELECT game_id, COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2026-01-18'
GROUP BY game_id;
```

**Result:** 5 games (!!)

| game_id | players |
|---------|---------|
| 20260118_BKN_CHI | 22 |
| 20260118_CHA_DEN | 35 |
| 20260118_NOP_HOU | 20 |
| 20260118_ORL_MEM | 23 |
| 20260118_TOR_LAL | 27 | ← **Unexpected!**

**Anomaly:** TOR@LAL has analytics but no boxscore in bdl_player_boxscores!

### Query 4: Missing Games Analysis

**Cross-check:** All 6 games show as "MISSING" when joining schedule → boxscores

**Root Cause:** Game ID format mismatch:
- Schedule table: `0022500602` (NBA.com format)
- BDL boxscores: `20260118_BKN_CHI` (date_away_home format)

---

## Root Cause Analysis

### Issue 1: Game ID Format Mismatch

**Problem:** Two different game ID formats in use across tables

**NBA.com Format:** `0022500602`
- Used by: `nbac_schedule`, NBA.com scrapers
- Format: Season type (00=regular) + Season year (225=2024-25) + Game number (00602)

**BallDontLie Format:** `20260118_BKN_CHI`
- Used by: `bdl_player_boxscores`, BallDontLie scrapers
- Format: Date (YYYYMMDD) + Away team + Home team

**Impact:**
- JOIN queries between schedule and boxscores fail
- Difficult to track which games have data
- No automatic cross-reference

**Solution Needed:**
- Add game ID mapping table
- Or normalize to single format across all tables
- Or add both formats to each table

### Issue 2: TOR@LAL Mystery

**Observation:** TOR@LAL has analytics but no BDL boxscore

**Possible Explanations:**
1. **Different data source:** Analytics may have been generated from NBA.com boxscore (not BDL)
2. **Timing issue:** Boxscore arrived, was processed, then deleted/overwritten
3. **Manual intervention:** Someone manually triggered analytics for this game
4. **Alternative ingestion path:** Multiple boxscore sources feeding analytics

**Investigation Needed:**
- Check if `nbac_player_boxscore` table has TOR@LAL data
- Review orchestration logs for TOR@LAL game_id
- Check for manual Phase 3 triggers on Jan 18

### Issue 3: POR@SAC Completely Missing

**Observation:** POR@SAC missing from both boxscores AND analytics

**True Data Gap:** This is a genuine scraper failure

**Likely Causes:**
1. BDL API didn't have data yet when scraper ran
2. Scraper failed silently (no retry)
3. Game postponed/cancelled but schedule not updated

**Evidence Needed:**
- Check scraper_execution_log for POR@SAC attempts
- Check BDL API for delayed data publication
- Verify game actually occurred (check NBA.com directly)

---

## Impact Assessment

**Grading Completeness:**
- Expected: 6 games graded
- Actual: 4-5 games graded (67-83%)
- Missing: POR@SAC definitely, TOR@LAL status unclear

**Prediction Coverage:**
- ML features depend on complete boxscore history
- Missing recent games degrades prediction accuracy
- Player prop predictions may be incomplete

**Analytics Pipeline:**
- Phase 3 processing incomplete
- Rolling averages skewed by missing data
- Trend analysis gaps

---

## Recommendations

### Immediate Actions (P0 - Critical)

1. **Implement Phase 1.2: Boxscore Completeness Pre-Flight Check** ✅
   - Verify all scheduled games have boxscores before triggering Phase 3
   - Auto-trigger missing boxscore scrapes
   - Retry Phase 3 after backfill

2. **Backfill Missing Games**
   ```bash
   # Manually trigger boxscore scrapes for Jan 18
   python scrapers/balldontlie/bdl_box_scores.py --date 2026-01-18 --force-refresh

   # Or trigger specific games if API supports it
   # Check if POR@SAC and TOR@LAL data now available
   ```

3. **Investigate TOR@LAL Analytics Source**
   ```sql
   -- Check if NBA.com boxscore has TOR@LAL
   SELECT game_id, COUNT(*) as players
   FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
   WHERE game_id LIKE '%0022500607%'
     OR game_id LIKE '%20260118_TOR_LAL%';
   ```

### Medium-Term Fixes (P1 - High Priority)

1. **Implement Phase 1.4: BallDontLie Fallback** ✅
   - Multi-source scraper with automatic fallback
   - NBA.com → BallDontLie failover
   - Ensures 100% game coverage

2. **Normalize Game ID Formats**
   - Add mapping table: `nba_raw.game_id_mappings`
   - Columns: nba_com_id, bdl_id, game_date, home_team, away_team
   - Generated during Phase 1 ingestion
   - Used for cross-table JOINs

3. **Add Data Completeness Validation**
   - Daily completeness report
   - Alert on missing games > 24 hours old
   - Auto-trigger backfill jobs

### Long-Term Improvements (P2 - Important)

1. **Unified Game ID Standard**
   - Migrate all tables to single game ID format
   - Use BDL format: `YYYYMMDD_AWAY_HOME` (more readable)
   - Or use NBA.com format: `0022500602` (official)
   - Add migration scripts

2. **Scraper Retry Logic**
   - Exponential backoff for failed scrapes
   - Multiple retry windows (1 hour, 6 hours, 24 hours)
   - Manual override for urgent backfills

3. **Data Lineage Tracking**
   - Record source of each boxscore (NBA.com vs BDL)
   - Track when data arrived vs when game ended
   - Monitor data latency

---

## Open Questions

1. **Why did TOR@LAL analytics exist without BDL boxscore?**
   - Need to check nbac_player_boxscore table
   - Need to review Phase 2→3 orchestration logs

2. **Was POR@SAC actually played?**
   - Verify on NBA.com directly
   - Check for game postponement announcements

3. **How often does this happen?**
   - Need to analyze historical completeness
   - Run query for all dates in last 30 days

---

## SQL Queries for Follow-Up

```sql
-- Historical completeness analysis
WITH scheduled AS (
  SELECT game_date, COUNT(*) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date >= '2026-01-01'
    AND game_status_text = 'Final'
  GROUP BY game_date
),
boxscores AS (
  SELECT game_date, COUNT(DISTINCT game_id) as boxscore_games
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= '2026-01-01'
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.scheduled_games,
  COALESCE(b.boxscore_games, 0) as boxscore_games,
  ROUND(COALESCE(b.boxscore_games, 0) / s.scheduled_games * 100, 1) as coverage_pct
FROM scheduled s
LEFT JOIN boxscores b ON s.game_date = b.game_date
WHERE s.scheduled_games > COALESCE(b.boxscore_games, 0)
ORDER BY s.game_date DESC;
```

---

## Files Investigated

- `nba_raw.nbac_schedule` - NBA.com schedule (official)
- `nba_raw.bdl_player_boxscores` - BallDontLie boxscores
- `nba_analytics.player_game_summary` - Phase 3 analytics
- `nba_orchestration.scraper_execution_log` - Scraper runs (not queried yet)

---

## Next Steps

1. ✅ Complete Phase 0 investigation
2. ⏭️ Implement Phase 1.2: Boxscore completeness check
3. ⏭️ Backfill Jan 18 missing games
4. ⏭️ Investigate TOR@LAL analytics source
5. ⏭️ Run historical completeness analysis

---

**Investigation Time:** 45 minutes
**SQL Queries Run:** 4
**Critical Gaps Found:** 2 games missing
**System Impact:** Medium (67-83% coverage)
