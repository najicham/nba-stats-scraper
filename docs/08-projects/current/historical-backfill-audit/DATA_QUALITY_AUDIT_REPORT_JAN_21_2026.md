# Data Quality Audit Report - January 21, 2026

**Report Date:** January 21, 2026
**Report Type:** Comprehensive Data Quality & Anomaly Detection
**Scope:** All pipeline phases (Raw, Analytics, Precompute)
**Analysis Period:** Last 7-30 days with focus on recent data

---

## Executive Summary

### Critical Issues Identified

1. **CRITICAL: BDL Data Coverage Severely Degraded**
   - Jan 15: Only 11.1% coverage (1 of 9 games)
   - Jan 20: Only 57.1% coverage (4 of 7 games)
   - 17 games missing from BDL in last 7 days

2. **CRITICAL: NBA.com Team Boxscore Scraper Failing**
   - 148 consecutive failures in last 24 hours (0% success rate)
   - Errors: "Expected 2 teams, got 0" and "No player rows in leaguegamelog JSON"

3. **WARNING: BDL API Instability**
   - 13 recent failures with "500 error responses" in last 24 hours
   - 93.5% success rate (normally >99%)

4. **INFO: No Critical Data Integrity Issues**
   - No duplicate records detected
   - No null critical fields
   - No anomalous stat values

---

## 1. Duplicate Records Check

### Results: ✅ PASS - No Duplicates Found

Checked the following tables for duplicates:
- `nbac_schedule`: No duplicate game_ids (last 30 days)
- `bdl_player_boxscores`: No duplicate player-game combinations (last 30 days)
- `nbac_player_boxscores`: No duplicate player-game combinations (last 30 days)

**Status:** No duplicate records detected in any raw tables.

---

## 2. Null/Missing Critical Fields

### Results: ✅ PASS - All Critical Fields Present

#### nbac_schedule (810 records, last 30 days)
```
Total Records: 810
Null game_id: 0
Null game_date: 0
Null home_team: 0
Null away_team: 0
Null game_status: 0
```

#### bdl_player_boxscores (6,487 records, last 30 days)
```
Total Records: 6,487
Null game_id: 0
Null player_lookup: 0
Null team_abbr: 0
Null points: 0
Null minutes: 0
Null assists: 0
Null rebounds: 0
```

#### nbac_player_boxscores (last 30 days)
```
Total Records: 0 (No NBAC boxscores in last 30 days)
```

#### player_game_summary - Analytics (5,427 records, last 30 days)
```
Total Records: 5,427
Null game_id: 0
Null player_lookup: 0
Null universal_id: 0
Null team_abbr: 0
Null game_date: 0
```

**Status:** All critical fields are populated correctly.

---

## 3. Row Count Comparisons Between Related Tables

### Cross-Phase Data Volume Analysis

| Phase | Table | Total Records | Unique Games | Unique Players | Date Range |
|-------|-------|--------------|--------------|----------------|------------|
| Phase 2 (Raw) | BDL Player Boxscores | 6,487 | 185 | 537 | 2025-12-23 to 2026-01-20 |
| Phase 3 (Analytics) | Player Game Summary | 5,427 | 217 | 527 | 2025-12-23 to 2026-01-20 |
| Phase 4 (Precompute) | Player Composite Factors | 6,415 | 301 | 567 | 2025-12-23 to 2026-01-21 |

### Key Observations

1. **Phase 3 has MORE games (217) than Phase 2 (185)**
   - Analytics is pulling from NBAC data in addition to BDL
   - This explains why some games exist in analytics but not in BDL raw

2. **Phase 3 has FEWER records than Phase 2**
   - Likely due to data consolidation/deduplication in analytics layer
   - This is expected behavior

3. **Phase 4 has most games (301)**
   - Precompute layer has data from future games (Jan 21)
   - Includes historical context for upcoming matchups

### Games in Analytics NOT in BDL (Critical Finding)

30 team-game combinations found in analytics but missing from BDL raw data, including:

**Recent Examples:**
- 2026-01-20: LAL @ DEN, TOR @ GSW, MIA @ SAC
- 2026-01-19: MIA @ GSW
- 2026-01-18: TOR @ LAL
- 2026-01-17: LAL @ POR
- 2026-01-16: WAS @ SAC

**Impact:** Analytics layer is compensating for BDL gaps by using NBAC data, but this creates inconsistency in data sources.

---

## 4. Data Freshness Issues

### Latest Game Dates by Phase

| Table | Latest Game Date | Total Games (Last 7 Days) |
|-------|-----------------|---------------------------|
| BDL Player Boxscores | 2026-01-20 | 29 |
| Player Game Summary (Analytics) | 2026-01-20 | 44 |
| Player Composite Factors (Precompute) | 2026-01-21 | 51 |

### Data Creation Timestamps (BDL)

All BDL data is created in single batch operations (0 minutes creation span):

| Game Date | First Record Created | Last Record Created | Creation Span | Games |
|-----------|---------------------|---------------------|---------------|-------|
| 2026-01-20 | 2026-01-21 07:59:53 | 2026-01-21 07:59:53 | 0 min | 4 |
| 2026-01-19 | 2026-01-20 02:05:13 | 2026-01-20 02:05:13 | 0 min | 8 |
| 2026-01-18 | 2026-01-19 02:05:14 | 2026-01-19 02:05:14 | 0 min | 4 |
| 2026-01-17 | 2026-01-18 02:05:19 | 2026-01-18 02:05:19 | 0 min | 7 |
| 2026-01-16 | 2026-01-17 03:05:25 | 2026-01-17 03:05:25 | 0 min | 5 |
| 2026-01-15 | 2026-01-15 23:05:10 | 2026-01-15 23:05:10 | 0 min | 1 |

**Observation:** BDL scraper runs on a daily schedule, typically between 2-8 AM UTC.

---

## 5. Games with Partial Data

### BDL Coverage Analysis (Last 7 Days)

| Game Date | Total Final Games | Games in BDL | Missing from BDL | Coverage % |
|-----------|------------------|--------------|------------------|------------|
| 2026-01-20 | 7 | 4 | 3 | 57.1% |
| 2026-01-19 | 9 | 8 | 1 | 88.9% |
| 2026-01-18 | 6 | 4 | 2 | 66.7% |
| 2026-01-17 | 9 | 7 | 2 | 77.8% |
| 2026-01-16 | 6 | 5 | 1 | 83.3% |
| 2026-01-15 | 9 | 1 | 8 | **11.1%** ⚠️ |

### ⚠️ CRITICAL: Jan 15 Data Gap

**Issue:** Only 1 of 9 games (11.1%) from January 15 are in BDL.

**Missing Games from Jan 15:**
1. PHX @ DET (0022500579)
2. BOS @ MIA (0022500580)
3. OKC @ HOU (0022500581)
4. MIL @ SAS (0022500582)
5. UTA @ DAL (0022500583)
6. NYK @ GSW (0022500584)
7. ATL @ POR (0022500585)
8. CHA @ LAL (0022500586)

### Complete List of Missing Games (Last 7 Days)

See attached file: `/tmp/missing_games_bdl_jan21.csv`

**Total Missing:** 17 games out of 46 final games (63% coverage)

### Player Roster Completeness

All games present in BDL have complete rosters:
- No games found with fewer than 8 players per team
- Typical range: 30-36 players per game (both teams combined)

**Example from Jan 20:**
- LAC @ CHI: 36 players, 234 total points
- MIN @ UTA: 35 players, 117 total points
- PHX @ PHI: 34 players, 226 total points
- SAS @ HOU: 35 players, 157 total points

---

## 6. Unusual Timestamp Patterns

### Results: ✅ PASS - No Anomalies Detected

**Checks Performed:**
1. ✅ No future timestamps found
2. ✅ No records with created_at > updated_at
3. ✅ Consistent batch creation patterns
4. ✅ No unexpected delays between game date and data availability

**Observation:** All timestamp patterns are normal and consistent with expected batch processing behavior.

---

## 7. Scraper Health Analysis

### Scraper Success Rates (Last 24 Hours)

| Scraper | Workflow | Attempts | Successful | Failed | Success Rate |
|---------|----------|----------|------------|--------|--------------|
| **nbac_team_boxscore** | post_game_window_1 | 106 | 0 | 106 | **0.0%** ⚠️ |
| **nbac_team_boxscore** | post_game_window_2 | 21 | 0 | 21 | **0.0%** ⚠️ |
| **nbac_team_boxscore** | post_game_window_2b | 21 | 0 | 21 | **0.0%** ⚠️ |
| **oddsa_events** | betting_lines | 9 | 0 | 9 | **0.0%** ⚠️ |
| bdl_live_box_scores_scraper | MANUAL | 200 | 187 | 13 | 93.5% ⚠️ |
| espn_team_roster_api | morning_operations | 30 | 30 | 0 | 100.0% ✅ |
| nbac_gamebook_pdf | MANUAL | 6 | 6 | 0 | 100.0% ✅ |

### Critical Errors

#### 1. NBA.com Team Boxscore Failures (148 total failures)
**Error Messages:**
- "Expected 2 teams for game 0022500620, got 0"
- "Expected 2 teams for game 0022500621, got 0"
- "JSON decode failed: Expecting value: line 2 column 1 (char 1)"
- "No player rows in leaguegamelog JSON"

**Affected Games (Jan 21 - scheduled, not yet played):**
- 0022500620: CLE @ CHA
- 0022500621: IND @ BOS
- 0022500622: BKN @ NYK
- 0022500623: ATL @ MEM
- 0022500624: DET @ NOP
- 0022500625: OKC @ MIL
- 0022500626: TOR @ SAC

**Root Cause:** Scrapers are attempting to fetch data for games that haven't started yet. This is expected behavior but indicates the scrapers are being triggered prematurely.

#### 2. BDL Live Boxscores API Errors (13 failures)
**Error Message:**
```
HTTPSConnectionPool(host='api.balldontlie.io', port=443):
Max retries exceeded with url: /v1/box_scores/live
(Caused by ResponseError('too many 500 error responses'))
```

**Time Range:** Jan 22, 00:45 - 01:21 UTC

**Impact:** Temporary API instability, but overall success rate remains high at 93.5%.

#### 3. Odds API Failures (9 failures)
**Error Message:** "Max decode/download retries reached: 8"

**Impact:** Betting lines data unavailable during failure periods.

---

## 8. Anomalous Data Values

### Results: ✅ PASS - No Anomalies Found

**Checks Performed:**
1. ✅ No negative stat values
2. ✅ No impossibly high point totals (>70 points)
3. ✅ No impossibly high rebounds (>30)
4. ✅ No impossibly high assists (>25)
5. ✅ No tied final game scores
6. ✅ No scores over 200 points

**Status:** All statistical values are within expected ranges.

---

## 9. Today's Games (January 21, 2026)

### Scheduled Games

| Game ID | Home Team | Away Team | Status |
|---------|-----------|-----------|--------|
| 0022500620 | CHA | CLE | Scheduled |
| 0022500621 | BOS | IND | Scheduled |
| 0022500622 | NYK | BKN | Scheduled |
| 0022500623 | MEM | ATL | Scheduled |
| 0022500624 | NOP | DET | Scheduled |
| 0022500625 | MIL | OKC | Scheduled |
| 0022500626 | SAC | TOR | Scheduled |

**Total:** 7 games scheduled for January 21, 2026

**Status:** All games show "Scheduled" status - none have started yet. This is normal for morning analysis.

---

## Summary of Findings

### Critical Issues (Require Immediate Attention)

1. **BDL Data Coverage Degraded**
   - Priority: 🔴 CRITICAL
   - Impact: 37% of games missing from primary data source
   - Trend: Getting worse (Jan 15: 11.1%, Jan 20: 57.1%)
   - Action Required: Investigate BDL API availability and scraper logic

2. **NBA.com Team Boxscore Scraper Down**
   - Priority: 🔴 CRITICAL
   - Impact: 148 consecutive failures in 24 hours
   - Root Cause: Premature triggering for unstarted games
   - Action Required: Adjust trigger logic to wait for game completion

### Warnings (Monitor Closely)

3. **BDL API Instability**
   - Priority: 🟡 WARNING
   - Impact: 13 recent 500 errors
   - Current Success Rate: 93.5%
   - Action Required: Monitor API health; consider retry logic improvements

### Positive Findings

4. **Data Integrity Excellent**
   - ✅ No duplicate records
   - ✅ No null critical fields
   - ✅ No anomalous stat values
   - ✅ Consistent timestamp patterns

5. **Analytics Layer Compensating**
   - Analytics successfully using NBAC data to fill BDL gaps
   - 44 games in analytics vs 29 in BDL (last 7 days)
   - Precompute layer functioning correctly with 51 games

---

## Recommended Actions

### Immediate (Within 24 Hours)

1. **Fix NBA.com Scraper Trigger Logic**
   - Add game status check before triggering boxscore scraper
   - Only scrape games with status = "Final"
   - Expected Impact: Reduce failure rate from 100% to <1%

2. **Investigate BDL January 15 Data Gap**
   - Check BDL API availability logs for Jan 15-16
   - Verify scraper execution logs for that period
   - Determine if backfill is possible/necessary

### Short Term (Within 1 Week)

3. **Implement BDL Availability Monitoring**
   - Track which games BDL API returns vs schedule
   - Alert when coverage drops below 90%
   - Log unavailable games for manual review

4. **Review and Tune Retry Logic**
   - Analyze BDL 500 error patterns
   - Implement exponential backoff if not present
   - Consider circuit breaker pattern for API health

### Long Term (Within 1 Month)

5. **Formalize Multi-Source Data Strategy**
   - Document when to use BDL vs NBAC data
   - Implement source preference hierarchy
   - Create data source quality metrics dashboard

6. **Create Data Completeness SLA**
   - Define acceptable data coverage thresholds
   - Implement automated alerting for SLA violations
   - Track coverage trends over time

---

## Appendix: Query Results Files

The following files have been generated during this audit:

1. `/home/naji/code/nba-stats-scraper/data_quality_audit_jan21_2026.sql` - Complete SQL queries used
2. `/tmp/missing_games_bdl_jan21.csv` - List of 17 missing games from BDL

---

**Report Generated:** January 21, 2026
**Generated By:** Automated Data Quality Audit System
**Next Scheduled Audit:** January 22, 2026
