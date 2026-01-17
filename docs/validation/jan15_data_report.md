# Data Availability Report - January 15, 2026

## Executive Summary

**Issue**: Analytics data shows only 215 players for Jan 15, 2026 when source data contains 316 players (68% capture rate).

**Root Cause**: Source data EXISTS but analytics processing appears incomplete or filtered.

## Detailed Findings

### 1. Games Scheduled
- **9 games** were scheduled for January 15, 2026
- All games show status: **Final**
- Games:
  1. 20260115/ATLPOR - Atlanta @ Portland
  2. 20260115/BOSMIA - Boston @ Miami
  3. 20260115/CHALAL - Charlotte @ LA Lakers
  4. 20260115/MEMORL - Memphis @ Orlando
  5. 20260115/MILSAS - Milwaukee @ San Antonio
  6. 20260115/NYKGSW - New York @ Golden State
  7. 20260115/OKCHOU - Oklahoma City @ Houston
  8. 20260115/PHXDET - Phoenix @ Detroit
  9. 20260115/UTADAL - Utah @ Dallas

### 2. Source Data Availability

#### NBA.com Gamebook (`nba_raw.nbac_gamebook_player_stats`)
- ✅ **All 9 games have data**
- **Total: 316 player records**
- Player counts per game:
  - 20260115/ATLPOR: 35 players
  - 20260115/BOSMIA: 34 players
  - 20260115/CHALAL: 36 players
  - 20260115/MEMORL: 35 players
  - 20260115/MILSAS: 35 players
  - 20260115/NYKGSW: 34 players
  - 20260115/OKCHOU: 35 players
  - 20260115/PHXDET: 35 players
  - 20260115/UTADAL: 37 players

#### BDL Boxscores (`nba_raw.bdl_player_boxscores`)
- ⚠️ **Only 1 game has data**
- 20260115_MEM_ORL: 35 players
- **Missing BDL data for 8 games**

### 3. Analytics Data (`nba_analytics.player_game_summary`)

- ✅ **All 9 games present** in analytics
- ⚠️ **Only 215 player records** (68% of source)
- Player counts per game:
  - 20260115_ATL_POR: 19 players (vs 35 in source)
  - 20260115_BOS_MIA: 20 players (vs 34 in source)
  - 20260115_CHA_LAL: 25 players (vs 36 in source)
  - 20260115_MEM_ORL: 34 players (vs 35 in source) ✅ Best
  - 20260115_MIL_SAS: 28 players (vs 35 in source)
  - 20260115_NYK_GSW: 25 players (vs 34 in source)
  - 20260115_OKC_HOU: 24 players (vs 35 in source)
  - 20260115_PHX_DET: 21 players (vs 21 in source)
  - 20260115_UTA_DAL: 19 players (vs 37 in source)

### 4. Missing Players Analysis

**101 players** from source data are missing in analytics.

Sample of players missing from analytics (20260115/ATLPOR game):
- Active players with minutes: Jalen Johnson (37:55), Onyeka Okongwu (36:50), Dyson Daniels (33:24), etc.
- DNP players (Did Not Play)
- Inactive players

**Pattern**: The analytics table appears to be filtering out:
1. Some inactive players
2. Some DNP (Did Not Play) players
3. Possibly some roster-only entries

## Data Quality Issues

### Critical
1. **68% capture rate** is too low for analytics
2. Missing 101 player records across all games
3. Only MEM_ORL game has near-complete data (34/35 = 97%)

### Moderate
1. BDL data missing for 8 of 9 games
2. Game ID format inconsistency:
   - Source uses: `20260115/ATLPOR`
   - Analytics uses: `20260115_ATL_POR`

## Conclusions

1. **Source data EXISTS**: All 9 games have complete NBA.com gamebook data
2. **Analytics processing incomplete**: Only capturing 68% of players
3. **Not a scraper issue**: This appears to be a data processor/transformation issue
4. **BDL dependency**: Low BDL coverage (1/9 games) may be contributing to analytics gaps

## Recommendations

1. Investigate analytics processor logic for Jan 15, 2026
2. Check if player filtering rules are too aggressive
3. Review why BDL data is missing for 8 games
4. Determine if roster-only players should be included in analytics
5. Consider running backfill for analytics table if processor has been fixed

## SQL Queries Used

```sql
-- Source data count
SELECT COUNT(*) as records
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2026-01-15';
-- Result: 316

-- Analytics data count
SELECT COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-15';
-- Result: 215

-- Per-game breakdown
SELECT game_code, COUNT(*) as player_count
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2026-01-15'
GROUP BY game_code
ORDER BY game_code;
```
