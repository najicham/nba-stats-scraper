# Backfill Priority Plan - January 21, 2026

## Overview
This document outlines the prioritized backfill plan for 34 missing boxscore games identified across the past 30 days.

---

## Data Completeness Timeline

### December 22-31, 2025: ✅ HEALTHY
- **Status:** 100% complete (62/62 games)
- **Action:** None required

### January 1-10, 2026: ⚠️ PARTIAL
- **Status:** 79% complete (56/71 games)
- **Missing:** 15 games across 6 dates
- **Priority:** Medium (historical data, non-critical)

### January 11-14, 2026: ⚠️ PARTIAL
- **Status:** 85% complete (28/33 games)
- **Missing:** 5 games across 3 dates
- **Priority:** Medium

### January 15-20, 2026: 🔴 CRITICAL
- **Status:** 73% complete (34/47 games)
- **Missing:** 13 games across 6 dates
- **Priority:** HIGH (recent data affects current models)

---

## Priority 1: CRITICAL (Complete Today)

### January 15, 2026 - CRITICAL DATE
**Impact:** 8 missing games on single date (89% missing)
**Root Cause:** Likely infrastructure/scraper failure
**Backfill Command:**
```bash
PYTHONPATH=. python scripts/backfill_boxscores.py --date 2026-01-15
```

**Missing Games:**
1. 0022500584 - NYK @ GSW
2. 0022500586 - CHA @ LAL
3. 0022500580 - BOS @ MIA
4. 0022500579 - PHX @ DET
5. 0022500585 - ATL @ POR
6. 0022500582 - MIL @ SAS
7. 0022500583 - UTA @ DAL
8. 0022500581 - OKC @ HOU

**After Backfill:**
```bash
# Verify completion
PYTHONPATH=. python scripts/check_data_completeness.py --date 2026-01-15

# Re-run analytics
PYTHONPATH=. python scripts/reprocess_analytics.py --date 2026-01-15
```

---

## Priority 2: HIGH (Complete by EOD)

### January 16-20, 2026 - Recent Week
**Impact:** 5 games across 5 dates
**Reason:** Recent data affects current predictions and model performance

**Backfill by Date:**
```bash
# Jan 16 (1 missing)
PYTHONPATH=. python scripts/backfill_boxscores.py --game-id 0022500592

# Jan 17 (2 missing)
PYTHONPATH=. python scripts/backfill_boxscores.py --date 2026-01-17

# Jan 18 (2 missing)
PYTHONPATH=. python scripts/backfill_boxscores.py --date 2026-01-18

# Jan 19 (1 missing)
PYTHONPATH=. python scripts/backfill_boxscores.py --game-id 0022500612

# Jan 20 (3 missing - may auto-resolve)
PYTHONPATH=. python scripts/backfill_boxscores.py --date 2026-01-20
```

**Note on Jan 20:** Gamebook data also missing (0/7 games). Check after 4 AM ET - may auto-resolve with overnight collection.

---

## Priority 3: MEDIUM (Complete this Week)

### January 12-14, 2026
**Impact:** 5 games across 3 dates
**Backfill Command:**
```bash
# Batch backfill
for date in 2026-01-12 2026-01-13 2026-01-14; do
  PYTHONPATH=. python scripts/backfill_boxscores.py --date $date
done
```

**Games:**
- Jan 12: 0022500563, 0022500562 (2 games)
- Jan 13: 0022500569, 0022500570 (2 games)
- Jan 14: 0022500576, 0022500577 (2 games)

---

## Priority 4: LOW (Complete within 2 weeks)

### January 1-7, 2026
**Impact:** 11 games across 5 dates
**Reason:** Older data, less impact on current operations

**Backfill Command:**
```bash
# Batch backfill early January
PYTHONPATH=. python scripts/backfill_boxscores.py \
  --start-date 2026-01-01 \
  --end-date 2026-01-07
```

**Games by Date:**
- Jan 1: 0022500475, 0022500474 (2 games)
- Jan 2: 0022500484, 0022500485 (2 games)
- Jan 3: 0022500492, 0022500493 (2 games)
- Jan 5: 0022500508, 0022500509 (2 games)
- Jan 6: 0022500515 (1 game)
- Jan 7: 0022500526, 0022500527 (2 games)

---

## Team-Specific Investigation (Parallel Track)

### High-Priority Investigation
**Teams Affected:** GSW (7 games), SAC (7 games)
**Pattern:** Consistent failures for specific teams

**Investigation Steps:**

#### 1. Check Team Abbreviation Issues
```bash
# Verify team codes in schedule vs boxscores
bq query --use_legacy_sql=false "
SELECT DISTINCT team_abbr FROM nba_raw.bdl_player_boxscores
WHERE team_abbr IN ('GSW', 'GS', 'SAC', 'SAC')
"
```

#### 2. Review Error Logs
```bash
# Check scraper logs for GSW/SAC failures
gcloud logging read "resource.type=cloud_function AND jsonPayload.team=GSW" \
  --limit 50 --format json --project nba-props-platform
```

#### 3. Test Direct API Fetch
```bash
# Test BallDontLie API for recent GSW game
curl "https://api.balldontlie.io/v1/stats?game_ids[]=0022500618&per_page=100"
```

#### 4. Review Historical Pattern
```bash
# Check if GSW/SAC issues are ongoing
PYTHONPATH=. python scripts/check_team_coverage.py --team GSW --days 60
PYTHONPATH=. python scripts/check_team_coverage.py --team SAC --days 60
```

### Potential Fixes

**If Team Abbreviation Mismatch:**
```python
# Add to scraper mapping
TEAM_ABBR_MAP = {
    'GS': 'GSW',  # If API returns 'GS' but we use 'GSW'
    # Add other mappings as needed
}
```

**If API Rate Limiting:**
```python
# Add to scraper config
RETRY_CONFIG = {
    'max_retries': 3,
    'backoff_factor': 2,
    'retry_status_codes': [429, 500, 502, 503, 504]
}
```

**If Timing Issue:**
```python
# Add delayed retry for west coast games
WEST_COAST_TEAMS = ['GSW', 'SAC', 'LAL', 'LAC', 'POR']
WEST_COAST_DELAY_HOURS = 2  # Retry 2 hours later
```

---

## Post-Backfill Verification

### Step 1: Verify Boxscore Coverage
```bash
# Check overall coverage
PYTHONPATH=. python scripts/check_30day_completeness.py

# Should show 226/226 games (100%)
```

### Step 2: Re-run Analytics Pipeline
```bash
# Reprocess analytics for all backfilled dates
PYTHONPATH=. python scripts/reprocess_analytics.py \
  --start-date 2026-01-01 \
  --end-date 2026-01-20

# Verify analytics coverage
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2026-01-01' AND '2026-01-20'
GROUP BY game_date
ORDER BY game_date DESC
"
```

### Step 3: Validate Feature Store
```bash
# Check feature store coverage
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2026-01-01' AND '2026-01-20'
GROUP BY game_date
ORDER BY game_date DESC
"
```

### Step 4: Final Health Check
```bash
# Run full system health check
PYTHONPATH=. python scripts/check_live_system_health.py
```

---

## Automation Improvements

### 1. Add Automated Gap Detection
```bash
# Add to crontab (runs daily at 6 AM ET)
0 6 * * * cd /home/naji/code/nba-stats-scraper && \
  PYTHONPATH=. python scripts/check_data_completeness.py --days 7 | \
  mail -s "Daily Data Completeness Report" alerts@yourdomain.com
```

### 2. Add Automatic Retry Logic
```python
# In scraper configuration
AUTO_RETRY_CONFIG = {
    'enabled': True,
    'check_time': '06:00',  # 6 AM ET
    'retry_threshold_hours': 12,  # Retry games older than 12 hours
    'max_attempts': 3
}
```

### 3. Set Up Alerting
```bash
# Alert on coverage below 95%
ALERT_THRESHOLD=95

# In monitoring script
if [ $COVERAGE -lt $ALERT_THRESHOLD ]; then
  python scripts/send_alert.py \
    --title "Boxscore Coverage Below Threshold" \
    --message "Current coverage: ${COVERAGE}%" \
    --severity "warning"
fi
```

---

## Success Criteria

### Immediate (End of Day)
- [ ] Jan 15 backfilled (8 games)
- [ ] Jan 16-20 backfilled (5 games)
- [ ] Boxscore coverage >= 95%
- [ ] Analytics re-run for Priority 1 & 2 dates

### Short-term (End of Week)
- [ ] All 34 games backfilled
- [ ] 100% boxscore coverage for past 30 days
- [ ] Root cause identified for GSW/SAC issues
- [ ] Fix deployed for recurring issues

### Long-term (End of Month)
- [ ] Automated gap detection in place
- [ ] Coverage maintained >= 98%
- [ ] Zero dates with >2 missing games
- [ ] Average time-to-backfill < 24 hours

---

## Reference Files

- **Full Report:** `/home/naji/code/nba-stats-scraper/DATA-COMPLETENESS-REPORT-JAN-21-2026.md`
- **Missing Games List:** `/home/naji/code/nba-stats-scraper/MISSING-GAMES-BACKFILL-LIST.csv`
- **Check Script:** `/home/naji/code/nba-stats-scraper/scripts/check_30day_completeness.py`

## Contact

For questions or issues during backfill:
- Review scraper logs: `gcloud logging read "resource.type=cloud_function"`
- Check BigQuery job status: `bq ls -j -a --max_results=10`
- Platform team: @data-quality-team

---

**Document Version:** 1.0
**Created:** January 21, 2026
**Author:** NBA Props Platform - Data Quality Team
