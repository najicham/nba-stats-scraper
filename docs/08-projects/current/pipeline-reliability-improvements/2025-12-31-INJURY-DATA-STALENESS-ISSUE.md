# Critical: Injury Data Staleness Issue

**Date Discovered**: December 31, 2025
**Severity**: 🔴 **CRITICAL**
**Status**: Active Production Issue
**Impact**: Frontend showing incorrect injury statuses, filtering out active players

---

## 🚨 Issue Summary

Injury report data is severely stale, causing the frontend to incorrectly show active players as "out" and hide them from users.

## 📊 Evidence

### Injury Data Freshness
```sql
Latest report date: 2025-12-22
Last processed: 2025-12-22 18:16:35
Days stale: 9 days (as of 2025-12-31)
```

### Affected Players (Examples)

**Stephen Curry**:
- Current Status in DB: `injury_status: "out"`, `injury_reason: "Left Hamstring; Strain"`
- Injury Report Date: **May 14, 2025** (7+ months old!)
- Reality: Playing tonight, has 27.5 points betting line
- Impact: System using playoff injury data from May

**Jimmy Butler**:
- Current Status: Shown as "out" with "Trade Pending" in frontend
- Injury Report Data: No recent records found
- Reality: Recently traded to GSW, has 19.5 points betting line, should be available
- Team: Correctly showing as GSW (recent trade)

### Root Cause

**Injury Report Scraper Not Running**:
- Last successful run: December 22, 2025
- Missing updates: 9+ days of injury reports
- Processor exists: `data_processors/raw/nbacom/nbac_injury_report_processor.py`
- **Problem**: No scheduler or trigger configured to run it daily

## 💥 Production Impact

### User-Facing Issues
1. **Hidden Players**: Active players with betting lines are filtered out as "injured"
2. **Wrong Injury Status**: Players cleared to play still show old injury reasons
3. **User Confusion**: Betting lines exist but players shown as "out"
4. **Lost Revenue**: Users can't bet on hidden players

### Data Quality Metrics
- **Stale Injury Data**: 100% of injury statuses are 9+ days old
- **Conflict Rate**: High - many players have `has_line: true` AND `injury_status: "out"`
- **User Trust**: Critical - users questioning data accuracy

## 🔍 Technical Analysis

### Data Flow
1. **Scraper** (missing/broken): Fetches NBA.com injury reports → GCS
2. **Processor** (exists but not triggered): `nbac_injury_report_processor.py` reads GCS → BigQuery
3. **Exporter** (`tonight_all_players_exporter.py`): Reads `nba_raw.nbac_injury_report` → Frontend API
4. **Frontend**: Filters players based on `injury_status`

### Broken Component
**Missing**: Daily scheduler/trigger for injury report scraping and processing

### Query Used by Frontend Exporter
```sql
-- From tonight_all_players_exporter.py:147-152
SELECT
    player_lookup,
    injury_status,
    reason as injury_reason
FROM `nba-props-platform.nba_raw.nbac_injury_report`
WHERE report_date <= @target_date
ORDER BY report_date DESC
LIMIT 1 PER player_lookup  -- Most recent report
```

**Problem**: "Most recent" is from December 22 for all players

## 💡 Immediate Workaround (Frontend)

The frontend team implemented a workaround in `props-web`:

```typescript
// Show all players with betting lines, regardless of injury_status
.filter((p) => p.has_line)
```

**Rationale**: If bookmakers set a line, player is active (overrides stale injury data)

**Limitation**: Doesn't fix the root cause, injury data still wrong in API

## 🔧 Root Cause Fix Required

### Option 1: Restore Injury Report Scraper (Recommended)

**Action**: Set up daily scraper + processor

1. **Create Scraper**:
   - Fetch NBA.com injury reports daily
   - Upload to GCS: `gs://nba-props-platform-raw/injury-reports/YYYY-MM-DD.json`

2. **Schedule Processor**:
   ```bash
   gcloud scheduler jobs create http injury-report-daily \
     --location=us-west2 \
     --schedule="0 */6 * * *" \  # Every 6 hours
     --uri="https://nba-scrapers-XXXXX.run.app/process-injury-report" \
     --http-method=POST \
     --oidc-service-account-email="scraper@nba-props-platform.iam.gserviceaccount.com"
   ```

3. **Backfill Missing Data**:
   ```bash
   # Manually scrape Dec 23-31 injury reports
   for date in {23..31}; do
     ./scripts/scrape_injury_report.sh 2025-12-$date
   done
   ```

### Option 2: Override with Betting Line Logic

**Action**: Update exporter to trust betting lines over injury status

```sql
-- In tonight_all_players_exporter.py
SELECT
    CASE
        WHEN current_points_line IS NOT NULL THEN 'available'
        ELSE COALESCE(i.injury_status, 'available')
    END as injury_status,
    CASE
        WHEN current_points_line IS NOT NULL AND i.injury_status = 'out'
        THEN 'Cleared (has betting line)'
        ELSE i.injury_reason
    END as injury_reason
FROM ...
```

**Pros**:
- Immediate fix
- Uses reliable data (betting lines)
- Handles stale injury data gracefully

**Cons**:
- Doesn't fix underlying data staleness
- Won't catch real injuries if bookmaker makes mistake

### Option 3: Use Alternative Injury Data Source

**Action**: Integrate with BallDontLie injuries API

```python
# Already exists: data_processors/raw/balldontlie/bdl_injuries_processor.py
# Schedule it to run daily
```

**Pros**:
- Third-party maintained
- Free API available
- Already have processor code

**Cons**:
- Different data format
- May not have same coverage
- Still needs scheduling

## 📋 Recommended Action Plan

### Immediate (< 1 hour)
1. ✅ Document issue (this file)
2. Verify frontend workaround is deployed
3. Check BallDontLie injuries processor as temp solution

### Urgent (< 24 hours)
1. Investigate why NBA.com injury scraper stopped running
2. Restore injury report scraping (daily schedule)
3. Backfill missing 9 days of injury data

### Short-Term (< 1 week)
1. Implement betting line override logic (Option 2)
2. Add monitoring for injury data staleness:
   ```sql
   SELECT
     DATEDIFF(CURRENT_DATE(), MAX(report_date)) as days_stale
   FROM nba_raw.nbac_injury_report
   ```
3. Alert if days_stale > 1

### Long-Term (< 1 month)
1. Add dual-source injury data (NBA.com + BallDontLie)
2. Implement data freshness indicators in API:
   ```json
   {
     "injury_status": "out",
     "injury_data_age_hours": 216,  // 9 days * 24
     "injury_data_stale": true
   }
   ```
3. Create injury data quality dashboard
4. Add alerting for scraper failures

## 🔬 Investigation Checklist

- [ ] Check if scraper ever existed (search for injury scraper code)
- [ ] Check Cloud Scheduler for disabled jobs
- [ ] Check Cloud Functions for injury-related functions
- [ ] Check GCS bucket for recent injury report files:
  ```bash
  gsutil ls -l gs://nba-props-platform-raw/injury-reports/ | tail -20
  ```
- [ ] Review December 22 logs - what happened after that date?
- [ ] Check if BallDontLie injuries processor can be used instead

## 📊 Monitoring Queries

### Check Injury Data Freshness
```sql
SELECT
  MAX(report_date) as latest_report,
  CURRENT_DATE() - MAX(report_date) as days_stale,
  COUNT(DISTINCT player_lookup) as players_tracked
FROM nba_raw.nbac_injury_report
WHERE report_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
```

### Find Conflicts (Has Line but Marked Out)
```sql
SELECT
  p.player_lookup,
  p.current_points_line,
  i.injury_status,
  i.injury_reason,
  i.report_date,
  CURRENT_DATE() - i.report_date as days_old
FROM nba_analytics.upcoming_player_game_context p
LEFT JOIN (
  SELECT player_lookup, injury_status, reason as injury_reason, report_date
  FROM nba_raw.nbac_injury_report
  WHERE report_date = (SELECT MAX(report_date) FROM nba_raw.nbac_injury_report)
) i ON p.player_lookup = i.player_lookup
WHERE p.game_date = CURRENT_DATE()
  AND p.current_points_line IS NOT NULL
  AND i.injury_status = 'out'
```

## 🔗 Related Files

**Processors**:
- `data_processors/raw/nbacom/nbac_injury_report_processor.py` - NBA.com processor (exists)
- `data_processors/raw/balldontlie/bdl_injuries_processor.py` - BDL processor (exists)

**Exporters**:
- `data_processors/publishing/tonight_all_players_exporter.py:147-152` - Uses injury data

**Frontend**:
- `/home/naji/code/props-web/docs/07-reference/BACKEND-DATA-QUALITY-ISSUES.md` - User reports

**Tests**:
- `scripts/test_nbac_injury_report_processor.py` - Processor test script

## 📝 Notes

### Why This Matters
- **Betting lines are the ground truth**: If a bookmaker sets a line, that player WILL play
- **Injury reports are for awareness**: Help users understand risk/uncertainty
- **Stale data is worse than no data**: Better to show "unknown" than wrong "out"

### Frontend Recommendation (Already Implemented)
✅ Filter by `has_line` rather than `injury_status != "out"`
- Correct approach given stale backend data
- Booking odds are more reliable than 9-day-old injury reports

### Backend Responsibility
- Fix the injury data pipeline
- Don't rely on frontend to work around bad data
- Implement proper data freshness monitoring

---

**Status**: Awaiting investigation and fix
**Owner**: Backend team (nba-stats-scraper)
**Urgency**: HIGH - Affecting user experience daily
**Next Steps**: Investigate scraper status, restore daily injury updates
