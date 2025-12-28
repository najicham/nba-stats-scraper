# Issue: Boxscore Data Gaps Causing Circuit Breaker Failures

**Date Discovered:** 2025-12-27
**Status:** Active (temporary workaround in place)
**Impact:** 8 of 18 teams missing from predictions

---

## Problem Summary

Phase 3 analytics processor (`UpcomingPlayerGameContextProcessor`) rejects players who don't meet the 90% completeness threshold across 5 data windows (L5, L10, L7d, L14d, L30d). After 3 failures, a circuit breaker trips and blocks the player for 7 days.

**Result:** 394 players blocked, including stars like Jokic, De'Aaron Fox, DeMar DeRozan, Zach LaVine.

---

## Root Cause

### Issue 1: Missing Boxscore Data
The `nba_raw.bdl_player_boxscores` table has gaps for several teams:

| Team | Coverage (Dec 1-26) | Games Missing |
|------|---------------------|---------------|
| SAC  | 44% | 5 of 9 games |
| POR  | 55% | 5 of 11 games |
| LAC  | 60% | 4 of 10 games |
| GSW  | 70% | 3 of 10 games |
| LAL  | 70% | 3 of 10 games |
| HOU  | 82% | 2 of 11 games |
| ORL  | 82% | 2 of 11 games |

### Issue 2: Aggressive Completeness Threshold
- `production_ready_threshold = 90.0` in `shared/utils/completeness_checker.py:91`
- ALL 5 windows must be >= 90% complete
- No graceful degradation for partial data

### Issue 3: Circuit Breaker Blocking
- `nba_orchestration.reprocess_attempts` table tracks failures
- After 3 attempts, circuit breaker trips for 7 days
- No manual override exposed via API

---

## Temporary Workaround Applied (2025-12-27)

1. Lowered `production_ready_threshold` from 90 to 40 in `completeness_checker.py`
2. Cleared circuit breaker records: `DELETE FROM nba_orchestration.reprocess_attempts WHERE analysis_date = '2025-12-27'`
3. Redeployed Phase 3

**TODO:** Restore threshold to 90 after backfilling boxscore data.

---

## Long-Term Fixes Needed

### Fix 1: Backfill Missing Boxscore Data (HIGH PRIORITY)
```bash
# Identify gaps
bq query --use_legacy_sql=false "
WITH schedule AS (
  SELECT game_date, home_team_tricode as team FROM nba_raw.nbac_schedule WHERE game_date >= '2025-12-01'
  UNION ALL
  SELECT game_date, away_team_tricode as team FROM nba_raw.nbac_schedule WHERE game_date >= '2025-12-01'
),
boxscores AS (
  SELECT DISTINCT game_date, team_abbr FROM nba_raw.bdl_player_boxscores WHERE game_date >= '2025-12-01'
)
SELECT s.game_date, s.team
FROM schedule s
LEFT JOIN boxscores b ON s.game_date = b.game_date AND s.team = b.team_abbr
WHERE b.team_abbr IS NULL
ORDER BY s.game_date, s.team"
```

Then backfill using BallDontLie scraper.

### Fix 2: Graceful Degradation for Partial Data (MEDIUM PRIORITY)
- Allow processing with < 90% completeness but flag records
- Add `data_quality_score` field to output
- Let downstream consumers decide how to handle

### Fix 3: Circuit Breaker Self-Healing (MEDIUM PRIORITY)
- Auto-clear circuit breakers when upstream data improves
- Expose manual override via admin API
- Reduce circuit breaker duration from 7 days to 1 day

### Fix 4: Fresh Roster Data (LOW PRIORITY)
- ESPN roster data is from Oct 18, 2025 (2+ months stale)
- Need daily roster scraping to capture trades/signings
- Currently doesn't affect predictions but could cause issues

---

## Commands Reference

### Check boxscore coverage
```bash
bq query --use_legacy_sql=false "
SELECT team_abbr, COUNT(DISTINCT game_date) as games
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY team_abbr
ORDER BY games"
```

### Check active circuit breakers
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT entity_id) as blocked_players
FROM nba_orchestration.reprocess_attempts
WHERE circuit_breaker_tripped = TRUE AND circuit_breaker_until > CURRENT_TIMESTAMP()"
```

### Clear circuit breakers for a date
```bash
bq query --use_legacy_sql=false "
DELETE FROM nba_orchestration.reprocess_attempts WHERE analysis_date = 'YYYY-MM-DD'"
```

---

## Detection / Alerting (IMPLEMENTED 2025-12-27)

### Daily Boxscore Completeness Monitor

**Scripts:**
- `bin/monitoring/check_boxscore_completeness.sh` - Shell script for manual checks
- `scripts/check_boxscore_completeness.py` - Python script with email alerts

**Cloud Scheduler:** `boxscore-completeness-daily`
- Runs daily at 6:00 AM ET (after all games complete)
- Calls `POST /monitoring/boxscore-completeness` on Phase 2 service
- Sends email alerts if coverage drops below thresholds

**Thresholds:**
- CRITICAL: < 70% coverage (sends error alert)
- WARNING: < 90% coverage (sends warning alert)

**Usage:**
```bash
# Check yesterday
./bin/monitoring/check_boxscore_completeness.sh

# Check specific date
./bin/monitoring/check_boxscore_completeness.sh --date 2025-12-23

# Check last 7 days
./bin/monitoring/check_boxscore_completeness.sh --days 7

# Python version with email alerts
PYTHONPATH=. .venv/bin/python scripts/check_boxscore_completeness.py --days 7
```

**To set up scheduler:**
```bash
./bin/monitoring/setup_boxscore_completeness_scheduler.sh
```

### Future Monitoring (TODO)
1. Circuit breaker count exceeding threshold (e.g., > 50 players blocked)
2. Analytics output missing > 2 teams scheduled to play

---

## Root Cause Analysis (2025-12-27)

### Why Did the Boxscore Gaps Occur?

**Primary Cause: BallDontLie API Data Gaps**

The BallDontLie API does not always have complete game data immediately. Testing revealed:

1. **API returns incomplete data for recent games** - Games from Dec 21-23 show only partial team coverage
2. **West coast late games are most affected** - LAC, SAC, POR games consistently missing
3. **Some games never appear in BDL API** - Dec 23 games POR@ORL, SAC@DET, LAC@HOU still missing after 4 days

**Secondary Cause: No Daily Completeness Monitoring**

The pipeline lacked:
- Automated detection of boxscore gaps
- Alerts when coverage drops below threshold
- Automatic backfill triggering

### Prevention Strategies

1. **Add Daily Boxscore Completeness Check** (HIGH)
   - Run after each day's games complete
   - Compare schedule vs boxscores in BigQuery
   - Alert if coverage < 95%

2. **Implement Fallback Data Source** (MEDIUM)
   - NBA.com gamebook data as backup
   - Already scraped but not used for player boxscores

3. **Reduce Circuit Breaker Aggressiveness** (LOW)
   - Lower threshold from 90% to 70%
   - Reduce block duration from 7 days to 1 day
   - Auto-clear when upstream data improves

### Backfill Completed (2025-12-27)

```
Dates backfilled: 12/1, 12/2, 12/10, 12/11, 12/12, 12/15, 12/18, 12/20, 12/21, 12/22, 12/23, 12/26
Method: PYTHONPATH=. .venv/bin/python scrapers/balldontlie/bdl_box_scores.py --date DATE --group gcs
```

**Coverage After Backfill:**
- 22 teams at 100%
- GSW, LAC at 90%
- SAC at 78%
- DET, HOU, ORL, POR at 82%

**Remaining Gaps (BDL API limitation):**
- Dec 21: HOU, SAC
- Dec 22: DET, GSW, ORL, POR
- Dec 23: DET, HOU, LAC, ORL, POR, SAC

---

## Related Files

- `shared/utils/completeness_checker.py` - Completeness threshold
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` - Player processing logic
- `nba_orchestration.reprocess_attempts` - Circuit breaker tracking table
- `scrapers/balldontlie/bdl_box_scores.py` - BDL boxscores scraper
