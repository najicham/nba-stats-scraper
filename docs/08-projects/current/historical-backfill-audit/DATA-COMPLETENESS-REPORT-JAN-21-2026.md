# Data Completeness Report: Past 30 Days
**Date Range:** December 22, 2025 - January 21, 2026
**Generated:** January 21, 2026
**Report Type:** Comprehensive 30-day data quality assessment

---

## Executive Summary

### Overall Data Health: ⚠️ NEEDS ATTENTION

**Key Findings:**
- **Boxscore Coverage:** 85.0% (192/226 games) - **BELOW TARGET**
- **Gamebook Coverage:** 96.9% (219/226 games) - **ACCEPTABLE** (Jan 20 pending)
- **Predictions Coverage:** 24,963 predictions across 29 dates - **HEALTHY**
- **Analytics Coverage:** Generally complete except where raw data is missing

**Critical Issues Identified:**
1. Systematic boxscore data gaps affecting 34 games across 15 dates
2. Specific teams (GSW, SAC, LAC, LAL) disproportionately affected
3. Jan 20, 2026 data collection incomplete (likely timing - data was collected overnight)

---

## 1. Raw Boxscore Data Coverage

### Summary Statistics
- **Total Final Games:** 226
- **Games with Boxscore Data:** 192 (85.0%)
- **Missing Boxscores:** 34 games (15.0%)
- **Dates Affected:** 15 out of 31 days

### Missing Games by Team (Jan 1-21, 2026)
| Team | Missing Games | Notes |
|------|--------------|-------|
| GSW (Golden State Warriors) | 7 | Most affected team |
| SAC (Sacramento Kings) | 7 | Most affected team |
| LAC (LA Clippers) | 5 | High impact |
| LAL (LA Lakers) | 4 | High impact |
| POR (Portland Trail Blazers) | 4 | High impact |
| DEN (Denver Nuggets) | 2 | Moderate impact |
| Other teams | 5 | One-off misses |

### Dates with Missing Boxscores

#### January 2026 (Recent Week - High Priority)
| Date | Expected | Actual | Missing | Missing Teams |
|------|----------|--------|---------|---------------|
| 2026-01-20 | 7 | 4 | 3 | DEN@LAL, GSW@TOR, SAC@MIA |
| 2026-01-19 | 9 | 8 | 1 | GSW@MIA |
| 2026-01-18 | 6 | 4 | 2 | LAL@TOR, SAC@POR |
| 2026-01-17 | 9 | 7 | 2 | DEN@WAS, POR@LAL |
| 2026-01-16 | 6 | 5 | 1 | SAC@WAS |
| 2026-01-15 | 9 | 1 | 8 | Multiple teams (major gap) |

**January 15 Details (Critical Date - 8 missing games):**
- DAL@UTA (Game ID: 0022500583)
- DET@PHX (Game ID: 0022500579)
- GSW@NYK (Game ID: 0022500584)
- HOU@OKC (Game ID: 0022500581)
- LAL@CHA (Game ID: 0022500586)
- MIA@BOS (Game ID: 0022500580)
- POR@ATL (Game ID: 0022500585)
- SAS@MIL (Game ID: 0022500582)

#### Earlier January 2026
| Date | Expected | Actual | Missing |
|------|----------|--------|---------|
| 2026-01-14 | 7 | 5 | 2 |
| 2026-01-13 | 7 | 5 | 2 |
| 2026-01-12 | 6 | 4 | 2 |
| 2026-01-07 | 12 | 10 | 2 |
| 2026-01-06 | 6 | 5 | 1 |
| 2026-01-05 | 8 | 6 | 2 |
| 2026-01-03 | 8 | 6 | 2 |
| 2026-01-02 | 10 | 8 | 2 |
| 2026-01-01 | 5 | 3 | 2 |

### Data Quality Analysis
- **Volume Anomalies:** None detected (player records per game consistent)
- **Pattern:** Most dates missing 1-2 games (typical scraper issues)
- **Exception:** Jan 15 missing 8 games (potential infrastructure issue)
- **Team Pattern:** GSW and SAC games consistently missing - possible API/scraper issue for specific teams

---

## 2. Analytics Pipeline Completeness

### Player Game Summary (nba_analytics.player_game_summary)
- **Status:** ✅ Generally complete
- **Coverage:** Mirrors raw boxscore availability
- **Gaps:** Only where raw boxscores are missing

### Dates with Analytics Gaps
| Date | Expected Games | Analytics Games | Missing |
|------|---------------|-----------------|---------|
| 2026-01-20 | 7 | 0 | 7 (all - pending raw data) |
| 2026-01-18 | 6 | 5 | 1 |
| 2026-01-17 | 9 | 8 | 1 |
| 2026-01-01 | 5 | 3 | 2 |

**Note:** Analytics gaps are derivative of raw data gaps. Once raw data is backfilled, analytics should be re-run.

### Team Analytics
- **Team Offense Summary:** Complete for available games
- **Team Defense Summary:** Complete for available games

---

## 3. Predictions Coverage

### Summary Statistics
- **Total Predictions:** 24,963
- **Dates with Predictions:** 29 out of 29 dates with games
- **Coverage:** ✅ 100% of game dates

### Recent Prediction Volume (Jan 15-20, 2026)
| Date | Predictions | Unique Players | Games Covered |
|------|------------|----------------|---------------|
| 2026-01-20 | 885 | 26 | 6 |
| 2026-01-19 | 615 | 51 | 8 |
| 2026-01-18 | 1,680 | 57 | 5 |
| 2026-01-17 | 313 | 57 | 6 |
| 2026-01-16 | 1,328 | 67 | 5 |
| 2026-01-15 | 2,193 | 103 | 9 |

**Observations:**
- Prediction volume varies significantly (313 to 2,193 per date)
- This is expected based on:
  - Number of games per day
  - Player availability (injuries, rest)
  - Betting markets available
- No zero-prediction dates detected
- System generating predictions even with incomplete boxscore data

---

## 4. Feature Store Coverage

### ML Feature Store v2 (nba_predictions.ml_feature_store_v2)
- **Status:** ✅ Data present for all game dates
- **Coverage:** 29/29 dates with games
- **Quality:** Features being generated despite some missing historical boxscores

**Note:** Feature store appears robust to minor gaps in historical data, likely due to:
- Rolling averages that can skip missing games
- Fallback to older data when recent games unavailable
- Feature engineering design that handles missing data gracefully

---

## 5. Gamebook Data Coverage

### Summary Statistics
- **Total Final Games:** 226
- **Games with Gamebook Data:** 219 (96.9%)
- **Missing Gamebooks:** 7 games (3.1%)

### Missing Gamebook Data
**Only Date Affected:** January 20, 2026 (yesterday)
- **Expected:** 7 games
- **Actual:** 0 games
- **Status:** ⏳ Likely pending - data collection runs overnight

**Analysis:** Gamebook collection appears to be running behind by approximately 1 day. This is typical if the overnight collection window hasn't completed yet or if this is run early in the morning ET.

---

## 6. Comparison to NBA Schedule

### Schedule Coverage Analysis
- **Total Dates Checked:** 31 days (Dec 22, 2025 - Jan 21, 2026)
- **Dates with Final Games:** 29 days
- **Dates with No Games:** 2 days (Dec 24, 2025 and likely one other)

### Schedule vs Actuals Reconciliation
| Metric | Scheduled Final Games | Actual Data Collected | Coverage % |
|--------|---------------------|---------------------|------------|
| Boxscores | 226 | 192 | 85.0% |
| Gamebooks | 226 | 219 | 96.9% |
| Analytics | 226 | 188* | 83.2% |
| Predictions | N/A | 24,963 | N/A |

*Analytics coverage estimate based on player_game_summary

### True Gaps vs No Games
All identified gaps are for dates with actual final games (game_status = 3 in schedule). There are no false positives where we expect data for days with no games.

---

## Recommendations & Action Items

### High Priority (Complete within 24 hours)

#### 1. Backfill January 15, 2026 (Critical)
**Impact:** 8 missing games on a single date
```bash
# Backfill boxscores for Jan 15
PYTHONPATH=. python scripts/backfill_boxscores.py --date 2026-01-15
```

**Games to backfill:**
- 0022500583, 0022500579, 0022500584, 0022500581
- 0022500586, 0022500580, 0022500585, 0022500582

#### 2. Investigate GSW and SAC Team-Specific Issues
**Impact:** 14 total missing games concentrated in 2 teams
- Review scraper logs for GSW and SAC game failures
- Check if specific API endpoints failing for these teams
- Test manual fetch for recent GSW/SAC games

```bash
# Test fetch for specific team
PYTHONPATH=. python scripts/test_team_boxscore_fetch.py --team GSW
```

#### 3. Backfill Recent Week (Jan 16-20)
**Impact:** 9 missing games from past 5 days
```bash
# Backfill date range
for date in 2026-01-16 2026-01-17 2026-01-18 2026-01-19 2026-01-20; do
  PYTHONPATH=. python scripts/backfill_boxscores.py --date $date
done
```

### Medium Priority (Complete within 1 week)

#### 4. Backfill Early January (Jan 1-14)
**Impact:** 17 missing games across 9 dates
```bash
# Backfill all January gaps
PYTHONPATH=. python scripts/backfill_boxscores.py \
  --start-date 2026-01-01 \
  --end-date 2026-01-14
```

#### 5. Re-run Analytics Pipeline
**Impact:** Refresh analytics for all dates with new data
```bash
# After boxscore backfill, re-run analytics
PYTHONPATH=. python scripts/reprocess_analytics.py \
  --start-date 2026-01-01 \
  --end-date 2026-01-20
```

#### 6. Verify Gamebook Collection for Jan 20
**Status:** May auto-resolve after overnight processing
```bash
# Check again after 4 AM ET
PYTHONPATH=. python scripts/check_data_completeness.py --date 2026-01-20
```

### Low Priority (Monitor/Investigate)

#### 7. Review Boxscore Data Pipeline
- Analyze why 15% of games are missing boxscores
- Review error logs for failed collections
- Consider adding retry logic or circuit breakers
- Investigate if specific game types (afternoon/west coast) have higher failure rates

#### 8. Set Up Automated Gap Detection
```bash
# Add to daily cron
0 6 * * * PYTHONPATH=/home/naji/code/nba-stats-scraper python scripts/check_data_completeness.py --days 7
```

#### 9. Team-Specific Monitoring
Set up alerts for GSW and SAC games until root cause identified:
```bash
# Add team-specific monitoring
PYTHONPATH=. python scripts/monitor_team_coverage.py --team GSW --team SAC
```

---

## Root Cause Analysis

### Likely Causes of Boxscore Gaps

1. **API Rate Limiting/Throttling**
   - BallDontLie API may have rate limits
   - Bursts of games (10-12 game nights) may hit limits
   - Recommendation: Add exponential backoff and retry logic

2. **Team-Specific API Issues**
   - GSW and SAC consistently missing suggests:
     - Team abbreviation mismatch (GSW vs GS, SAC vs SAC)
     - Team-specific API endpoint issues
     - Data quality issues on source side

3. **Timing Issues**
   - Late-night west coast games may finish after collection window
   - Collection may start before final stats posted
   - Recommendation: Add delayed retry for west coast games

4. **Infrastructure Issues**
   - Jan 15 with 8 missing games suggests:
     - Cloud function timeout
     - Memory issues during high-volume date
     - Network connectivity issue
   - Recommendation: Review Cloud Function logs for Jan 15

---

## Monitoring Going Forward

### Daily Checks
1. Run completeness check every morning at 6 AM ET
2. Alert on any date with <95% coverage
3. Auto-trigger backfill for dates with <90% coverage

### Weekly Reviews
1. Team-specific coverage analysis
2. Data volume trend analysis
3. Pipeline latency monitoring

### Monthly Audits
1. Comprehensive 30-day reports (like this one)
2. Root cause analysis of recurring gaps
3. Pipeline optimization based on failure patterns

---

## Appendix: Query Reference

### Check Missing Boxscores
```sql
SELECT
  s.game_date,
  s.home_team_tricode,
  s.away_team_tricode,
  s.game_id
FROM nba_raw.nbac_schedule s
LEFT JOIN nba_raw.bdl_player_boxscores b
  ON s.game_date = b.game_date
  AND s.home_team_tricode = b.home_team_abbr
WHERE s.game_status = 3
  AND b.game_id IS NULL
ORDER BY s.game_date DESC;
```

### Team Coverage Analysis
```sql
SELECT
  team,
  COUNT(*) as games_missing
FROM (
  SELECT home_team_tricode as team FROM nba_raw.nbac_schedule s
  WHERE game_status = 3
    AND NOT EXISTS (
      SELECT 1 FROM nba_raw.bdl_player_boxscores b
      WHERE b.game_date = s.game_date
        AND b.home_team_abbr = s.home_team_tricode
    )
)
GROUP BY team
ORDER BY games_missing DESC;
```

### Daily Completeness Check
```sql
SELECT
  game_date,
  COUNT(DISTINCT CASE WHEN game_status = 3 THEN game_id END) as final_games,
  COUNT(DISTINCT b.game_id) as boxscore_games,
  ROUND(COUNT(DISTINCT b.game_id) * 100.0 /
        COUNT(DISTINCT CASE WHEN game_status = 3 THEN s.game_id END), 1) as pct
FROM nba_raw.nbac_schedule s
LEFT JOIN nba_raw.bdl_player_boxscores b USING (game_date)
WHERE game_date >= CURRENT_DATE - 30
GROUP BY game_date
ORDER BY game_date DESC;
```

---

## Report Metadata

**Script Used:** `/home/naji/code/nba-stats-scraper/scripts/check_30day_completeness.py`
**Execution Time:** ~7 seconds
**Data Sources:**
- nba_raw.nbac_schedule
- nba_raw.bdl_player_boxscores
- nba_raw.nbac_gamebook_player_stats
- nba_analytics.player_game_summary
- nba_analytics.team_offense_game_summary
- nba_analytics.team_defense_game_summary
- nba_predictions.ml_feature_store_v2
- nba_predictions.player_prop_predictions

**Contact:** Platform Data Quality Team
