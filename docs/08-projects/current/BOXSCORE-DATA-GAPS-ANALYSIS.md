# Boxscore Data Gaps Analysis

**Date:** 2025-12-28
**Session:** 182
**Status:** In Progress

---

## Problem Statement

5 teams (DET, GSW, POR, SAC, LAC) have 0 players in game context for Dec 28, causing prediction gaps. Investigation revealed missing boxscore data as the root cause.

---

## Missing Data Inventory

| Team | Missing Dates | Game IDs | Days Since Season Start |
|------|---------------|----------|------------------------|
| **DET** | Nov 28, Dec 22, Dec 23 | 0022500072, 0022500408, 0022500421 | 37, 61, 62 |
| **GSW** | Dec 22 | 0022500407 | 61 |
| **LAC** | Nov 28, Nov 29, Dec 23 | 0022500079, 0022500300, 0022500422 | 37, 38, 62 |
| **POR** | Dec 22, Dec 23 | 0022500408, 0022500420 | 61, 62 |
| **SAC** | Nov 28, Dec 21, Dec 23 | 0022500077, 0022500401, 0022500421 | 37, 60, 62 |

**Total:** 12 game-dates missing across 5 teams

---

## Root Cause Analysis

### Immediate Cause: BDL Scraper Gaps

The `bdl_player_box_scores` scraper failed to collect data for these dates. Possible reasons:

1. **API Rate Limiting**: BDL API has rate limits; if exceeded, data fetch fails silently
2. **Scraper Not Scheduled**: Scraper may not have run on those days
3. **Transient API Errors**: Network issues or API downtime during scheduled run
4. **No Retry Mechanism**: Failed scrapes are not automatically retried

### Contributing Factors

1. **No Completeness Monitoring**: No daily check to detect missing boxscore data
2. **No Alerting**: No alerts when boxscore data is incomplete
3. **Circuit Breaker Design**: When players fail completeness checks 3 times, they're locked out for 7 days - this is by design but causes cascading data gaps

### Pattern Observed

Two clusters of missing dates:
- **Cluster 1:** Nov 28-29 (Thanksgiving weekend)
- **Cluster 2:** Dec 21-23 (Pre-Christmas)

These are both holiday periods where:
- Fewer games are scheduled
- Support/monitoring may be reduced
- API issues less likely to be caught quickly

---

## Impact Analysis

### Cascade Effect

```
Missing boxscores (12 game-dates)
    ↓
Completeness < 70% for some lookback windows (L5, L7d, etc.)
    ↓
Players fail completeness checks in Phase 3
    ↓
Circuit breakers trip after 3 failures
    ↓
125 players locked out for 7 days
    ↓
5 teams have 0 players in game context
    ↓
Predictions missing for games involving those teams
```

### Affected Games (Dec 28)

| Game | Status |
|------|--------|
| GSW @ TOR | Missing GSW predictions |
| BOS @ POR | Missing POR predictions |
| DET @ LAC | Missing ALL predictions |
| SAC @ LAL | Missing SAC predictions |
| MEM @ WAS | OK |
| PHI @ OKC | OK |

---

## Prevention Recommendations

### Immediate (This Session)

1. [x] Backfill missing boxscore data
2. [ ] Clear circuit breakers
3. [ ] Re-run Phase 3

### Short-Term (Next Week)

1. **Add Boxscore Completeness Check**
   - Compare scheduled games vs collected boxscores daily
   - Alert if any game is missing boxscore data
   - Run at 6 AM ET (after overnight collection)

2. **Add Automatic Retry**
   - If boxscore scraper fails, retry 3 times with exponential backoff
   - Add to dead-letter queue if all retries fail
   - Alert on dead-letter items

3. **Reduce Circuit Breaker Lockout**
   - Current: 7 days is too long
   - Proposed: 24 hours or until data is available

### Long-Term (Next Month)

1. **Multi-Source Redundancy**
   - Use multiple data sources (BDL, NBA.com, ESPN)
   - Fall back to secondary source if primary fails
   - Reconcile data quality across sources

2. **Predictive Alerting**
   - Alert BEFORE completeness falls below threshold
   - "Warning: GSW has 2 missing games in L5 window"

3. **Self-Healing Pipeline**
   - Automatically detect gaps
   - Trigger backfill for missing data
   - Clear circuit breakers once data is available
   - Re-process affected entities

---

## Commands Reference

```bash
# Check boxscore completeness for a team
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players
FROM nba_raw.bdl_player_boxscores
WHERE team_abbr = 'GSW'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY game_date
ORDER BY game_date
"

# Find missing boxscore dates for a team
bq query --use_legacy_sql=false "
WITH scheduled AS (
  SELECT game_date FROM nba_raw.nbac_schedule
  WHERE (home_team_tricode = 'GSW' OR away_team_tricode = 'GSW')
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND game_date < CURRENT_DATE()
),
collected AS (
  SELECT DISTINCT game_date FROM nba_raw.bdl_player_boxscores
  WHERE team_abbr = 'GSW'
)
SELECT s.game_date as missing_date
FROM scheduled s
LEFT JOIN collected c ON s.game_date = c.game_date
WHERE c.game_date IS NULL
"

# Check circuit breakers for today
bq query --use_legacy_sql=false "
SELECT entity_id, circuit_breaker_until
FROM nba_orchestration.reprocess_attempts
WHERE analysis_date = CURRENT_DATE()
  AND circuit_breaker_tripped = TRUE
LIMIT 20
"

# Clear circuit breakers for a date
bq query --use_legacy_sql=false "
UPDATE nba_orchestration.reprocess_attempts
SET circuit_breaker_tripped = FALSE, circuit_breaker_until = NULL
WHERE analysis_date = '2025-12-28' AND circuit_breaker_tripped = TRUE
"
```

---

## Backfill Status - COMPLETE

| Date | Status | Rows Collected |
|------|--------|----------------|
| 2025-11-28 | ✅ Complete | 6,982 |
| 2025-11-29 | ✅ Complete | 6,594 |
| 2025-12-21 | ✅ Complete | 1,898 |
| 2025-12-22 | ✅ Complete | 1,690 |
| 2025-12-23 | ✅ Complete | 1,440 |

**Total: 18,604 rows backfilled**

---

## Resolution Summary

### Actions Taken (Session 182)

1. **Scraped missing boxscore data** - Used `BdlPlayerBoxScoresScraper` for 5 dates
2. **Loaded to BigQuery** - Direct insert (bypassed broken processor registry)
3. **Cleared circuit breakers** - Reset 125 circuit breakers for Dec 28
4. **Re-ran Phase 3** - 442 players processed successfully
5. **Re-exported tonight API** - All 6 games now have players (191 total)

### Results

| Metric | Before | After |
|--------|--------|-------|
| Teams with 0 players | 5 (DET, GSW, LAC, POR, SAC) | 0 |
| Players in game context | ~100 | 442 |
| Tonight API players | 0 | 191 |

### Issues Found During Fix

1. **Processor Registry Gap**: `ball-dont-lie/player-box-scores` path is NOT registered
   - The scraper exports to this path, but Phase 2 has no processor for it
   - Required manual BigQuery insert to bypass
   - **Fix needed**: Add entry to `data_processors/raw/main_processor_service.py`

2. **Data Format Mismatch**: `BdlBoxscoresProcessor` expects different JSON structure
   - Scraper outputs flat array of stats
   - Processor expects nested games → players structure
   - **Fix needed**: Either update processor or create new one

---

## Files Changed

| File | Change |
|------|--------|
| `docs/08-projects/current/BOXSCORE-DATA-GAPS-ANALYSIS.md` | This document |

---

## Remaining Work

### HIGH Priority
1. **Add processor registry entry** for `ball-dont-lie/player-box-scores`
2. **Add boxscore completeness monitoring** to daily health check

### MEDIUM Priority
3. **Fix prediction worker duplicates** - MERGE instead of WRITE_APPEND
4. **Reduce circuit breaker lockout** - 24 hours instead of 7 days

### LOW Priority
5. **Automate gap detection** - Daily check for missing boxscore dates
6. **Add multi-source redundancy** - NBA.com fallback for BDL failures
