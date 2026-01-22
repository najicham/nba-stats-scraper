# Database Data Completeness and Quality Verification Report
**Project:** nba-props-platform
**Report Date:** January 21, 2026
**Analysis Period:** January 19-21, 2026

---

## Executive Summary

This report provides a comprehensive analysis of database data completeness and quality across all NBA tables for the dates January 19, 20, and 21, 2026. The analysis reveals several critical discrepancies and data quality issues that require attention.

### Key Findings

1. **Jan 19 Discrepancy**: 281 raw player records vs 227 analytics records (54 record difference)
   - Caused by: Missing game in raw data + DNP (did not play) filtering
   - Game `20260119_MIA_GSW` exists in analytics (26 players) but NOT in raw data
   - 113 players with zero minutes ('00') in raw data, 80 filtered from analytics

2. **Jan 20 Critical Issue**: 885 predictions exist but ZERO analytics/precompute data
   - 6 games have predictions, but only 4 games have raw data
   - Complete absence of Phase 3 (analytics) and Phase 4 (precompute) data
   - Predictions were generated without required upstream data

3. **Jan 21**: No data in any table (expected - future date or no games scheduled)

---

## Section 1: Exact Record Counts By Date

### 1.1 Raw Player Boxscores (nba_raw.bdl_player_boxscores)

```
+------------+--------------+--------------+----------------+----------------+
| game_date  | record_count | unique_games | unique_players | unique_bdl_ids |
+------------+--------------+--------------+----------------+----------------+
| 2026-01-19 |          281 |            8 |            281 |            281 |
| 2026-01-20 |          140 |            4 |            140 |            140 |
+------------+--------------+--------------+----------------+----------------+
```

**Query Used:**
```sql
SELECT
    game_date,
    COUNT(*) as record_count,
    COUNT(DISTINCT game_id) as unique_games,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT bdl_player_id) as unique_bdl_ids
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date
ORDER BY game_date
```

### 1.2 Analytics Player Game Summary (nba_analytics.player_game_summary)

```
+------------+--------------+--------------+----------------+----------------------+
| game_date  | record_count | unique_games | unique_players | unique_universal_ids |
+------------+--------------+--------------+----------------+----------------------+
| 2026-01-19 |          227 |            9 |            227 |                  227 |
+------------+--------------+--------------+----------------+----------------------+
```

**Key Observation:** Analytics has 9 games while raw only has 8 games.

### 1.3 Precompute Player Daily Cache (nba_precompute.player_daily_cache)

```
+------------+--------------+----------------+----------------------+
| cache_date | record_count | unique_players | unique_universal_ids |
+------------+--------------+----------------+----------------------+
| 2026-01-19 |          129 |            129 |                  129 |
+------------+--------------+----------------+----------------------+
```

**Note:** Jan 20 and Jan 21 have ZERO precompute records.

### 1.4 Player Prop Predictions (nba_predictions.player_prop_predictions)

```
+------------+--------------+--------------+----------------+--------------------+
| game_date  | record_count | unique_games | unique_players | unique_predictions |
+------------+--------------+--------------+----------------+--------------------+
| 2026-01-19 |          615 |            8 |             51 |                615 |
| 2026-01-20 |          885 |            6 |             26 |                885 |
+------------+--------------+--------------+----------------+--------------------+
```

**Critical Issue:** Jan 20 has 885 predictions with NO upstream analytics or precompute data!

### 1.5 ESPN Scoreboard (Game Schedule)

```
No data for Jan 19, 20, or 21 in ESPN scoreboard table
```

---

## Section 2: Data Quality Issues

### 2.1 Players with Zero Minutes (DNP - Did Not Play)

```
+------------+---------------+----------------------+----------------+
| game_date  | total_records | zero_or_null_minutes | played_minutes |
+------------+---------------+----------------------+----------------+
| 2026-01-19 |           281 |                  113 |            168 |
| 2026-01-20 |           140 |                   58 |             82 |
+------------+---------------+----------------------+----------------+
```

**Important Discovery:** The raw data uses minutes format '00' for DNP, not '0:00' as initially assumed.

**Breakdown for Jan 19:**
- Total raw records: 281
- Players who played (minutes != '00'): 168
- Did not play (minutes = '00'): 113
- Analytics records: 227

**Analysis:** Analytics includes 59 more players than just those who played, suggesting some DNP players are included in analytics.

### 2.2 NULL Values in Critical Fields

```
+------------+---------------+--------------------+--------------------+--------------+----------------+-------------+
| game_date  | total_records | null_player_lookup | null_bdl_player_id | null_game_id | null_team_abbr | null_points |
+------------+---------------+--------------------+--------------------+--------------+----------------+-------------+
| 2026-01-19 |           281 |                  0 |                  0 |            0 |              0 |           0 |
| 2026-01-20 |           140 |                  0 |                  0 |            0 |              0 |           0 |
+------------+---------------+--------------------+--------------------+--------------+----------------+-------------+
```

**Result:** NO NULL values in critical fields. Data quality is excellent in this regard.

### 2.3 Duplicate Records Check

**Query:**
```sql
SELECT
    game_date,
    game_id,
    player_lookup,
    COUNT(*) as duplicate_count
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date, game_id, player_lookup
HAVING COUNT(*) > 1
```

**Result:** NO duplicate records found.

---

## Section 3: Discrepancy Analysis

### 3.1 Jan 19: Raw vs Analytics (281 vs 227 records)

**Detailed Breakdown:**
```
+-------------------------------+-------+
|           category            | count |
+-------------------------------+-------+
| Raw Played - In Analytics     |   164 |
| Raw Played - NOT In Analytics |     4 |
| Raw DNP - In Analytics        |    33 |
| Raw DNP - NOT In Analytics    |    80 |
| In Analytics - NOT in Raw     |    30 |
+-------------------------------+-------+
```

**Explanation:**
1. Of 168 players who played, 164 are in analytics (4 missing)
2. Of 113 DNP players, 33 are included in analytics (80 filtered out)
3. 30 players are in analytics but NOT in raw data

### 3.2 The Missing Game: 20260119_MIA_GSW

**Critical Finding:**
```
+------------------------+------------------+--------------+
|         status         |     game_id      | player_count |
+------------------------+------------------+--------------+
| Analytics - Not in Raw | 20260119_MIA_GSW |           26 |
+------------------------+------------------+--------------+
```

**Game Comparison:**
```
+-----------+------------------+
|  source   |     game_id      |
+-----------+------------------+
| Analytics | 20260119_MIA_GSW |  <-- ONLY in Analytics
| Raw Data  | 20260119_BOS_DET |
| Raw Data  | 20260119_DAL_NYK |
| Raw Data  | 20260119_IND_PHI |
| Raw Data  | 20260119_LAC_WAS |
| Raw Data  | 20260119_MIL_ATL |
| Raw Data  | 20260119_OKC_CLE |
| Raw Data  | 20260119_PHX_BKN |
| Raw Data  | 20260119_UTA_SAS |
+-----------+------------------+
```

**Sample Players from Missing Game:**
- Stephen Curry (GSW) - 19 points, 28 minutes
- Bam Adebayo (MIA) - 4 points, 26 minutes
- Jimmy Butler III (GSW) - 17 points, 21 minutes
- Norman Powell (MIA) - 21 points, 30 minutes

**Root Cause:** The game `20260119_MIA_GSW` data was not ingested into the raw `bdl_player_boxscores` table, but somehow made it into the analytics layer, possibly from an alternate data source (ESPN boxscores?).

### 3.3 Sample Players in Raw but NOT in Analytics (Jan 19)

These are primarily players with '00' minutes (DNP):
```
+------------------+-------------------+--------------------+-----------+---------+--------+
|     game_id      |   player_lookup   |  player_full_name  | team_abbr | minutes | points |
+------------------+-------------------+--------------------+-----------+---------+--------+
| 20260119_DAL_NYK | kyrieirving       | Kyrie Irving       | DAL       | 00      |      0 |
| 20260119_DAL_NYK | pjwashington      | P.J. Washington    | DAL       | 00      |      0 |
| 20260119_IND_PHI | tyresehaliburton  | Tyrese Haliburton  | IND       | 00      |      0 |
| 20260119_IND_PHI | paulgeorge        | Paul George        | PHI       | 00      |      0 |
+------------------+-------------------+--------------------+-----------+---------+--------+
```

**Note:** High-profile players like Kyrie Irving, Paul George, and Tyrese Haliburton appear as DNP, which is unusual and may indicate roster data quality issues.

### 3.4 Jan 20: Predictions Without Upstream Data

**Predictions Breakdown by Game:**
```
+------------------+----------------+-------------------+
|     game_id      | unique_players | total_predictions |
+------------------+----------------+-------------------+
| 20260120_LAC_CHI |              8 |               280 |
| 20260120_LAL_DEN |              4 |               140 |
| 20260120_MIA_SAC |              2 |                60 |
| 20260120_MIN_UTA |              3 |                90 |
| 20260120_PHX_PHI |              6 |               210 |
| 20260120_SAS_HOU |              3 |               105 |
+------------------+----------------+-------------------+
```

**Raw Data Games (Jan 20):**
```
+------------------+----------------+-----------+--------------+
|     game_id      | unique_players | dnp_count | played_count |
+------------------+----------------+-----------+--------------+
| 20260120_LAC_CHI |             36 |        11 |           25 |
| 20260120_MIN_UTA |             35 |        16 |           19 |
| 20260120_PHX_PHI |             34 |        14 |           20 |
| 20260120_SAS_HOU |             35 |        17 |           18 |
+------------------+----------------+-----------+--------------+
```

**Missing Games in Raw Data:**
- `20260120_LAL_DEN` - Has predictions but NO raw data
- `20260120_MIA_SAC` - Has predictions but NO raw data

**Analytics/Precompute for Jan 20:**
```
Analytics records: 0
Precompute records: 0
```

**Critical Problem:** The prediction service generated 885 predictions for Jan 20 despite:
1. Missing 2 games in raw data
2. ZERO analytics records (Phase 3)
3. ZERO precompute records (Phase 4)

**Possible Explanations:**
1. Predictions may have been generated using cached data from previous days
2. Predictions may have been generated before games were postponed/cancelled
3. There may be a race condition where predictions run before upstream data is ready
4. The prediction service may not have proper dependency checks

---

## Section 4: Historical Data Range

### 4.1 Table Metadata

**nba_raw.bdl_player_boxscores:**
- Total Records: 191,586
- Partitions: 935
- Storage: 69.7 MB

### 4.2 Last 14 Days Data Availability

```
+------------+-------------+-------------------+--------------------+
| check_date | raw_records | analytics_records | prediction_records |
+------------+-------------+-------------------+--------------------+
| 2026-01-21 |           0 |                 0 |                  0 |
| 2026-01-20 |         140 |                 0 |                885 |  <-- CRITICAL
| 2026-01-19 |         281 |               227 |                615 |
| 2026-01-18 |         141 |               127 |               1680 |
| 2026-01-17 |         247 |               254 |                313 |
| 2026-01-16 |         175 |               238 |               1328 |
| 2026-01-15 |          35 |               215 |               2193 |  <-- Anomaly
| 2026-01-14 |         176 |               152 |                285 |
| 2026-01-13 |         174 |               155 |                295 |
| 2026-01-12 |         140 |               128 |                 82 |
| 2026-01-11 |         348 |               324 |                577 |
| 2026-01-10 |         211 |               136 |                924 |
| 2026-01-09 |         347 |               416 |               2505 |  <-- Anomaly
| 2026-01-08 |         106 |                60 |                195 |
| 2026-01-07 |         349 |               259 |                287 |
+------------+-------------+-------------------+--------------------+
```

**Observations:**
1. Jan 15: Only 35 raw records but 215 analytics records (6x multiplier)
2. Jan 17: Analytics records (254) > Raw records (247)
3. Pattern of analytics having more records than raw suggests alternative data sources

---

## Section 5: Game Schedule Verification

### 5.1 ESPN Scoreboard Status

**Query:**
```sql
SELECT COUNT(*) as total_games
FROM `nba-props-platform.nba_raw.espn_scoreboard`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
```

**Result:**
```
+-------------+
| total_games |
+-------------+
|           0 |
+-------------+
```

**Finding:** ESPN scoreboard has NO data for any of the three target dates. This suggests either:
1. The scraping process failed
2. The table is not being populated
3. A different table is being used for game schedules

---

## Section 6: Comprehensive Summary

### 6.1 Side-by-Side Comparison

```
+------------+-----------+------------+---------+-----------+-------------------+-----------------+--------------------+-------------+------------------+--------------------+
| game_date  | raw_total | raw_played | raw_dnp | raw_games | analytics_records | analytics_games | precompute_records | predictions | prediction_games | prediction_players |
+------------+-----------+------------+---------+-----------+-------------------+-----------------+--------------------+-------------+------------------+--------------------+
| 2026-01-19 |       281 |        168 |     113 |         8 |               227 |               9 |                129 |         615 |                8 |                 51 |
| 2026-01-20 |       140 |         82 |      58 |         4 |                 0 |               0 |                  0 |         885 |                6 |                 26 |
+------------+-----------+------------+---------+-----------+-------------------+-----------------+--------------------+-------------+------------------+--------------------+
```

---

## Critical Issues Summary

### Issue 1: Missing Game in Raw Data (Jan 19)
**Severity:** HIGH
**Impact:** 30 players missing from raw data
**Game:** 20260119_MIA_GSW
**Recommendation:** Investigate why this game was not ingested into `bdl_player_boxscores`

### Issue 2: Predictions Without Upstream Data (Jan 20)
**Severity:** CRITICAL
**Impact:** 885 predictions generated without analytics or precompute data
**Recommendation:**
1. Add dependency checks in prediction pipeline
2. Investigate why Phase 3 and Phase 4 failed for Jan 20
3. Consider invalidating Jan 20 predictions

### Issue 3: DNP Player Filtering Inconsistency
**Severity:** MEDIUM
**Impact:** Inconsistent handling of DNP players (33 included, 80 excluded from analytics)
**Recommendation:** Document and standardize the filtering logic for DNP players

### Issue 4: High-Profile Players Marked as DNP
**Severity:** MEDIUM
**Impact:** Players like Kyrie Irving, Paul George showing as DNP (0 minutes)
**Recommendation:** Investigate roster data quality issues

### Issue 5: Analytics Has More Records Than Raw (Multiple Dates)
**Severity:** MEDIUM
**Impact:** Suggests multiple data sources feeding analytics without proper reconciliation
**Recommendation:**
1. Document all data sources feeding analytics
2. Implement data lineage tracking
3. Add reconciliation checks between raw and analytics

### Issue 6: Missing ESPN Scoreboard Data
**Severity:** HIGH
**Impact:** Cannot verify game schedules or postponements
**Recommendation:**
1. Check if ESPN scraper is running
2. Verify table name/location
3. Consider alternative sources for game schedules

---

## Recommendations

### Immediate Actions

1. **Investigate Jan 20 Pipeline Failure**
   - Check Cloud Function logs for Phase 3 (analytics) and Phase 4 (precompute)
   - Determine why predictions ran without upstream data
   - Consider reprocessing Jan 20 with complete data

2. **Fix Missing Game Issue (Jan 19)**
   - Backfill `20260119_MIA_GSW` into `bdl_player_boxscores`
   - Investigate root cause of ingestion failure

3. **Add Pipeline Validation**
   - Implement pre-flight checks in prediction pipeline
   - Validate that required upstream data exists before generating predictions
   - Add row count validation between pipeline stages

### Long-Term Improvements

1. **Data Lineage Tracking**
   - Implement end-to-end data lineage from raw to predictions
   - Track which data sources contribute to each table
   - Add audit columns (source, ingestion_timestamp, etc.)

2. **Automated Quality Checks**
   - Daily reconciliation between raw and analytics
   - Automated alerts for missing games
   - Row count validation between pipeline stages

3. **Documentation**
   - Document DNP player filtering logic
   - Create data dictionary with all sources
   - Document expected record counts per game

4. **Monitoring**
   - Add metrics for data completeness
   - Track pipeline dependencies
   - Alert on missing upstream data

---

## SQL Queries Used

All queries used in this analysis are available in:
`/home/naji/code/nba-stats-scraper/scripts/database_verification_queries.sql`

---

**Report Generated:** 2026-01-21
**Analyst:** Claude Code (Automated Analysis)
**Data Source:** nba-props-platform BigQuery project
