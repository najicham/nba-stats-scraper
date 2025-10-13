# BigDataBall Play-by-Play Validation Queries

**FILE:** `validation/queries/raw/bigdataball_pbp/README.md`

---

Complete validation system for BigDataBall enhanced play-by-play data.

## 📋 Overview

**Data Source:** BigDataBall Enhanced Play-by-Play  
**Table:** `nba-props-platform.nba_raw.bigdataball_play_by_play`  
**Pattern:** Pattern 3 (Game-Based, Single Event per key)  
**Expected Coverage:** October 2024 - June 2025 (2024-25 season)  
**Expected Volume:** ~400-600 events per game, ~1,200+ games per season

---

## 🔍 Step 0: Discovery Phase (MANDATORY)

**Run these FIRST** to understand what data actually exists:

1. **Discovery Query 1: Actual Date Range**
   - Purpose: Find min/max dates, total events, unique games
   - What to document: Date coverage, games count, avg events per game

2. **Discovery Query 2: Event Volume by Date**
   - Purpose: Check for anomalies in event counts
   - What to look for: Are most games 400-600 events?

3. **Discovery Query 3: Missing Game Days vs Schedule**
   - Purpose: Find scheduled games with no play-by-play data
   - What to document: Number of missing dates, patterns

4. **Discovery Query 4: Date Continuity Gaps**
   - Purpose: Identify large gaps in date coverage
   - What to look for: Off-season gaps (normal), unexpected gaps (investigate)

5. **Discovery Query 5: Event Sequence Integrity**
   - Purpose: Check if event sequences are complete per game
   - What to look for: Gaps or duplicates in sequence numbers

### After Discovery

Document your findings using this template:

```
DISCOVERY FINDINGS
==================
Data Source: BigDataBall Play-by-Play
Table: nba-props-platform.nba_raw.bigdataball_play_by_play

Actual Date Range: [min_date] to [max_date]
Total Games: [count] games
Total Events: [count] events
Avg Events Per Game: [count] events

Missing Dates: [count] dates missing
Event Sequence Issues: [describe any problems]
Coverage Assessment: [X%] complete
```

---

## ✅ Production Validation Queries

### 1. Season Completeness Check
**File:** `season_completeness_check.sql`  
**Purpose:** Verify complete data coverage across all seasons and teams  
**When to run:** After backfills or to verify historical data integrity

**Expected Results:**
- DIAGNOSTICS row: All null counts should be 0
- Regular season: ~1,230 games per season per team (41 home games)
- Playoffs: Variable games based on playoff advancement
- Event counts: ~400-600 per game (reasonable range)
- Shot coverage: 80%+ of shots should have coordinates

**Red Flags:**
- Teams with <82 regular season games
- Min event count <300 (incomplete games)
- Shot coordinate coverage <70%

---

### 2. Find Missing Games
**File:** `find_missing_games.sql`  
**Purpose:** Identify specific games missing from play-by-play data  
**When to run:** When completeness check shows teams with <82 games

**Expected Results:**
- Empty result = all regular season games present
- Any results = specific games need investigation

**Instructions:**
1. Update date range for season you're checking
2. Run query
3. Use results to create backfill plan or investigate scraper

---

### 3. Daily Check Yesterday
**File:** `daily_check_yesterday.sql`  
**Purpose:** Verify yesterday's games were captured correctly  
**When to run:** Every morning at ~9 AM (after scraper/processor)

**Expected Results:**
- Status = "✅ Complete" when all games captured
- Status = "✅ No games scheduled" on off days
- Status = "❌ CRITICAL" requires immediate investigation

**Automation:**
```bash
# Schedule daily check
crontab -e
0 9 * * * cd /path/to/project && ./scripts/validate-bigdataball daily
```

**Quality Thresholds:**
- ✅ Complete: 400+ events, 70%+ coordinate coverage, 15+ players
- ⚠️ Warning: 300-399 events OR <70% coords OR <15 players
- ❌ Critical: <300 events OR no data

---

### 4. Weekly Check Last 7 Days
**File:** `weekly_check_last_7_days.sql`  
**Purpose:** Weekly health check showing daily coverage trends  
**When to run:** Weekly (e.g., Monday mornings)

**Expected Results:**
- Each day: "✅ Complete" or "⚪ No games"
- Multiple "⚠️ Incomplete" = scraper issue

**What to look for:**
- Patterns (specific days consistently failing)
- Event count trends
- Coordinate coverage degradation

---

### 5. Event Quality Checks
**File:** `event_quality_checks.sql`  
**Purpose:** Play-by-play specific quality validation  
**When to run:** After backfills, when investigating data quality issues

**Checks Performed:**
- **Shot Analysis:** Coordinate coverage, shot result availability
- **Event Distribution:** Shots, fouls, rebounds, turnovers, substitutions
- **Lineup Completeness:** 5 home + 5 away players per possession
- **Sequence Integrity:** Event numbering gaps or duplicates
- **Player Coverage:** Unique players identified in events vs lineups

**Quality Thresholds:**
- ✅ Good: 400+ events, 70%+ coords, 80%+ full lineups, <5 sequence gaps
- ⚠️ Warning: 300-399 events OR 50-69% coords OR incomplete lineups
- 🔴 Critical: <300 events OR <50% coords OR >10 sequence gaps

---

### 6. Realtime Scraper Check
**File:** `realtime_scraper_check.sql`  
**Purpose:** Verify scraper/processor is running and current  
**When to run:** Anytime to check data freshness

**Expected Behavior:**
- During active games: Data appears ~2 hours after game completion
- Off days: May show stale data (normal)
- Off season: Shows months-old data (normal)

**Status Guide:**
- ✅ CURRENT: Data up to date with recent games
- ⏳ PROCESSING: Games completed <4 hours ago (normal BigDataBall delay)
- ⚠️ WARNING: Missing expected data
- 🔴 CRITICAL: Games completed >4 hours ago but not in DB
- ⚪ OFF DAY: No games scheduled

---

## 🚨 Common Issues & Solutions

### Issue 1: Low Event Counts
**Symptoms:** Games with <400 events  
**Causes:**
- Scraper timeout (BigDataBall releases data 2+ hours after game)
- Processor error during transformation
- CSV parsing issues

**Solutions:**
1. Check scraper logs for the specific game
2. Verify GCS file exists and is complete
3. Re-run processor for specific date

### Issue 2: Missing Shot Coordinates
**Symptoms:** <70% of shots have coordinates  
**Causes:**
- BigDataBall data format change
- Coordinate field mapping issue in processor

**Solutions:**
1. Check recent games vs historical (did it change?)
2. Verify processor coordinate extraction logic
3. Compare against raw CSV files

### Issue 3: Incomplete Lineups
**Symptoms:** Not all 10 lineup positions filled  
**Causes:**
- Substitution timing during events
- Beginning/end of periods
- Technical timeouts

**Solutions:**
- This is partially expected (substitutions happen)
- >80% full lineups is acceptable
- <80% indicates data quality issue

### Issue 4: Sequence Gaps
**Symptoms:** Missing event_sequence numbers  
**Causes:**
- Events filtered out during processing
- CSV parsing skipped rows
- Data corruption in source

**Solutions:**
1. Compare event count to sequence range
2. Check raw CSV for actual events
3. Verify processor event filtering logic

---

## 📊 Data Quality Standards

### Tier 1: Critical (Must Pass)
- ✅ All scheduled games present
- ✅ >300 events per game minimum
- ✅ No null home/away team assignments
- ✅ Event sequences start at 0 or 1

### Tier 2: High Quality (Target)
- ✅ 400-600 events per game
- ✅ 70%+ shot coordinate coverage
- ✅ 80%+ full lineup coverage
- ✅ <5 sequence gaps per game

### Tier 3: Exceptional (Bonus)
- ✅ 500+ events per game average
- ✅ 90%+ shot coordinate coverage
- ✅ 95%+ full lineup coverage
- ✅ 0 sequence gaps

---

## 🔄 Maintenance Schedule

**Daily (Automated):**
- Morning check (9 AM): `daily_check_yesterday.sql`
- Evening check (9 PM): `realtime_scraper_check.sql`

**Weekly (Monday):**
- Trend analysis: `weekly_check_last_7_days.sql`
- Quality audit: `event_quality_checks.sql`

**Monthly:**
- Full season check: `season_completeness_check.sql`
- Missing games: `find_missing_games.sql`

**After Backfills:**
- All discovery queries (verify coverage)
- Season completeness check
- Event quality checks

---

## 📝 Related Resources

- **Master Validation Guide:** `/validation/NBA_DATA_VALIDATION_MASTER_GUIDE.md`
- **BDL Boxscores (Pattern 3 reference):** `/validation/queries/raw/bdl_boxscores/`
- **Processor Reference:** `/validation/PROCESSOR_REFERENCE.md`
- **BigDataBall Processor:** `/processors/bigdataball_pbp_processor.py`

---

## 🆘 Support

**Issues with queries?**
1. Check that partition filters are present (game_date BETWEEN ...)
2. Verify table name: `nba-props-platform.nba_raw.bigdataball_play_by_play`
3. Confirm date ranges match your actual data coverage

**Need help?**
- Review master validation guide for pattern explanations
- Check processor reference for data structure details
- Examine BDL boxscores queries (same Pattern 3 approach)

---

**Last Updated:** 2025-10-13  
**Version:** 1.0  
**Pattern:** Pattern 3 (Game-Based, Single Event)  
**Coverage:** 2024-25 NBA Season
