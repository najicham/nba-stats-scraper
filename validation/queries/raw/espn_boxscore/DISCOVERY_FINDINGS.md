# ESPN Boxscore Data - Discovery Findings

**File:** `validation/queries/raw/espn_boxscore/DISCOVERY_FINDINGS.md`  
**Date:** October 13, 2025  
**Processor:** `espn_boxscore_processor.py`  
**Table:** `nba_raw.espn_boxscores`  
**Pattern:** Pattern 3 (Single Event) - Extremely Sparse Backup Source  

---

## Executive Summary

ESPN Boxscore is an **extremely sparse backup data source** with minimal historical collection. Unlike primary sources (BDL, NBA.com), ESPN data exists for only 1 game in our current dataset, serving as a final validation checkpoint in the Early Morning Final Check workflow.

**Key Characteristics:**
- ⚠️ **EXTREMELY SPARSE:** Only 1 game collected (2025-01-15)
- 🔴 **Game ID Mismatch:** Cannot join with schedule on game_id
- ✅ **High Quality When Present:** Accurate stats, complete player data
- 📊 **Backup Only:** Not a comprehensive data source

---

## Discovery Query Results

### Query 1: Actual Date Range and Volume

```
Earliest Date:        2025-01-15
Latest Date:          2025-01-15
Total Dates:          1
Unique Games:         1
Total Player Records: 25
Unique Players:       25
Unique Teams:         2
```

**Analysis:** 
- Only a single game collected in entire dataset
- 25 players = reasonable (12-13 per team with bench)
- This is a backup validation source, not comprehensive collection

---

### Query 2: Records Per Game Pattern

```
Date        Game ID              Players  Teams  Teams List    Home  Away
2025-01-15  20250115_HOU_PHI     25       2      HOU,PHI       PHI   HOU
```

**Analysis:**
- 25 players per game is within expected range (20-30 typical)
- Clean team abbreviations (HOU, PHI)
- Standard game_id format: YYYYMMDD_AWAY_HOME

---

### Query 3: Sample Player Data

Top scorers from the one game:
```
Joel Embiid        41 pts, 10 reb, 3 ast (PHI)
Tyrese Maxey       27 pts, 1 reb, 7 ast (PHI)
Jalen Green        20 pts, 5 reb, 3 ast (HOU)
Alperen Sengun     19 pts, 9 reb, 6 ast (HOU)
```

**Analysis:**
- Stats appear accurate and complete
- All key fields populated (points, rebounds, assists, minutes)
- Player names normalized correctly (player_lookup field)
- Starter flag working correctly

---

### Query 4: Schedule Coverage Analysis (Jan-Feb 2025)

```
Total Scheduled Dates:    56
Dates with ESPN Data:     0
Total Scheduled Games:    409
Games with ESPN Data:     0
Date Coverage %:          0.0%
Game Coverage %:          0.0%
```

**Analysis:**
- The one ESPN game (2025-01-15) doesn't match schedule join
- This is because game_id formats don't match (see Query 5)
- ESPN coverage is effectively 0% when using game_id joins
- **CRITICAL:** Must use date + team joins instead

---

### Query 5: Join Key Format Check

```
Source    Game ID              Date        Home   Away
ESPN      20250115_HOU_PHI     2025-01-15  PHI    HOU
Schedule  0022400604           2025-01-20  GSW    BOS
Schedule  0022400588           2025-01-18  IND    PHI
Schedule  0022400787           2025-02-13  MIN    OKC
Schedule  0022400833           2025-02-25  NOP    SAS
```

**CRITICAL FINDING:**
- ESPN uses our standard format: `YYYYMMDD_AWAY_HOME`
- Schedule uses NBA.com format: `0022400604`
- **Game IDs DO NOT MATCH between sources**
- **Solution:** Join on `game_date + home_team_abbr + away_team_abbr`

---

### Query 6: ESPN vs BDL Comparison (Jan 2025)

```
ESPN Only Games:    1
BDL Only Games:     227
Both Sources:       0
Total Games:        228
```

**Analysis:**
- Zero overlap between ESPN and BDL in January 2025
- BDL has comprehensive coverage (227 games)
- ESPN has minimal coverage (1 game)
- Confirms ESPN is backup-only, not parallel collection

---

## Data Structure Analysis

### BigQuery Schema Key Fields

**Identifiers:**
- `game_id` (STRING) - Our standard format, doesn't match schedule
- `espn_game_id` (STRING) - ESPN's internal ID
- `game_date` (DATE) - **Use this for joins**
- `season_year` (INTEGER)

**Teams:**
- `home_team_abbr` (STRING) - Standard abbreviations
- `away_team_abbr` (STRING) - Standard abbreviations
- `team_abbr` (STRING) - Player's team

**Player Stats:**
- All standard fields: points, rebounds, assists, etc.
- `player_lookup` (STRING) - Normalized for cross-source matching
- `starter` (BOOLEAN) - Starter vs bench

**Partitioning:** By `game_date` (REQUIRED for all queries)

---

## Join Strategy

### ❌ WRONG: Cannot Join on game_id

```sql
-- This will NOT work - game_id formats don't match
LEFT JOIN nba_raw.nbac_schedule s 
  ON espn.game_id = s.game_id
```

### ✅ CORRECT: Join on Date + Teams

```sql
-- This is the only way to join ESPN with schedule
LEFT JOIN nba_raw.nbac_schedule s
  ON espn.game_date = s.game_date
  AND espn.home_team_abbr = s.home_team_tricode
  AND espn.away_team_abbr = s.away_team_tricode
```

**Why this works:**
- `game_date` matches exactly between sources
- Team abbreviations are standardized (HOU, PHI, etc.)
- Unique combination identifies specific games

---

## Validation Strategy

Given ESPN's extremely sparse coverage, validation queries should focus on:

### ✅ What to Validate

1. **Existence Checks** - Do we have ANY ESPN data at all?
2. **Data Quality** - When ESPN data exists, is it accurate?
3. **Cross-Validation** - Compare ESPN vs BDL for same games
4. **Player Stats Accuracy** - Verify points, rebounds, assists match BDL

### ❌ What NOT to Validate

1. **Completeness** - Can't expect all games to have ESPN data
2. **Coverage Gaps** - Gaps are expected, not failures
3. **Missing Dates** - ESPN is backup-only, gaps are normal
4. **Schedule Alignment** - ESPN won't match most scheduled games

---

## Expected Data Patterns

### Normal (Healthy)
- ✅ ESPN has 0-10 games per month (sparse is expected)
- ✅ When ESPN data exists, it matches BDL stats
- ✅ Player counts 20-30 per game
- ✅ All active players have stats populated

### Concerning (Needs Investigation)
- ⚠️ ESPN game exists but BDL doesn't (rare but possible)
- ⚠️ Stats differ by >5 points between ESPN and BDL
- ⚠️ Player counts <15 or >35 (unusual)
- ⚠️ Key stats (points, rebounds, assists) are NULL

### Critical (Alert Immediately)
- 🔴 ESPN and BDL have same game but wildly different scores
- 🔴 Player names don't match between sources
- 🔴 Team abbreviations wrong or NULL

---

## Business Context

### ESPN's Role in Data Pipeline

**Workflow Position:** Early Morning Final Check (5 AM PT)  
**Purpose:** Final backup validation before prop settlement  
**Collection Frequency:** Ad-hoc during backup workflows only

**Why ESPN is Sparse:**
- Not a primary data source (BDL and NBA.com are primary)
- Only collected during backup validation scenarios
- Serves as "last line of defense" data quality check
- Historical backfill not prioritized (1 game is sufficient for testing)

### Revenue Impact

**Priority:** MEDIUM-LOW  
**Risk:** LOW - ESPN is backup only, not critical path

**Impact if ESPN fails:**
- No immediate impact (BDL and NBA.com are primary)
- Loss of backup validation capability
- Reduced data quality confidence in edge cases

---

## Recommendations

### For Validation Queries

1. **Focus on Quality, Not Quantity**
   - Validate data accuracy when ESPN exists
   - Don't expect comprehensive coverage
   - Compare with BDL when both sources have same game

2. **Use Date + Team Joins**
   - Never join on game_id with schedule
   - Always use: game_date + home_team_abbr + away_team_abbr
   - Document this requirement clearly

3. **Set Realistic Expectations**
   - 0-10 games per month is normal
   - Gaps are expected, not failures
   - ESPN is backup validation, not primary data

### For Future Backfills

If ESPN coverage needs to expand:
- Target 1-2 games per day during season
- Focus on high-profile games (national TV)
- Maintain backup-only approach (don't replace BDL)

---

## Date Ranges for Validation Queries

Based on discovery findings:

```
Full Range (Current):   2025-01-15 to 2025-01-15 (1 day)
Current Season:         2024-10-22 to 2025-04-30
Historical:             None (only 1 game exists)

Recommended for Testing:
- Single Date:   2025-01-15 (the only game)
- Date Range:    2025-01-01 to 2025-01-31 (for future collection)
```

---

## Summary

ESPN Boxscore is an **extremely sparse backup data source** with unique validation requirements:

**Key Points:**
1. Only 1 game in current dataset (expected for backup source)
2. Game ID format mismatch requires date + team joins
3. Zero overlap with schedule when using game_id
4. High data quality when ESPN data exists
5. Validation should focus on accuracy, not completeness

**Validation Philosophy:**
> "When ESPN has data, is it correct?"  
> NOT: "Does ESPN have all the data?"

This is fundamentally different from BDL or NBA.com validation where comprehensive coverage is expected.

---

**Document Status:** ✅ Discovery Complete  
**Next Step:** Create validation queries adapted for sparse backup source  
**Pattern:** Pattern 3 with date + team join strategy  
**Priority:** Medium-Low (backup source)
