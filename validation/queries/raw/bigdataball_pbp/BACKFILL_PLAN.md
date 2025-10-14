# BigDataBall Play-by-Play - Backfill Plan

**FILE:** `validation/queries/raw/bigdataball_pbp/BACKFILL_PLAN.md`

**Created:** October 13, 2025  
**Season:** 2024-25 NBA Regular Season  
**Missing Games:** 100 games across 19 dates  
**Coverage:** 91% (1,111 of 1,236 games present)

---

## 📋 Executive Summary

**Status:** 19 dates from 2024-25 season are missing BigDataBall play-by-play data.

**Impact:**
- 100 missing games (8% of regular season)
- Affects all 30 teams (3-4 games per team)
- Shot analysis unavailable for these games
- Lineup analysis unavailable for these games

**Recommendation:** Run backfill for all 19 dates if BigDataBall has released the data.

---

## 🎯 Missing Dates - Complete List

### November 2024 (8 dates - 43 games)

| Date | Day | Games Missing | Status |
|------|-----|---------------|--------|
| 2024-11-11 | Monday | 6 games | ❌ Missing |
| 2024-11-12 | Tuesday | 5 games | ❌ Missing |
| 2024-11-14 | Thursday | 4 games | ❌ Missing |
| 2024-11-15 | Friday | 8 games | ❌ Missing |
| 2024-11-19 | Tuesday | 6 games | ❌ Missing |
| 2024-11-22 | Friday | 6 games | ❌ Missing |
| 2024-11-26 | Tuesday | 4 games | ❌ Missing |
| 2024-11-29 | Friday | 4 games | ❌ Missing |

**Total November:** 43 games

---

### December 2024 (5 dates - 25 games)

| Date | Day | Games Missing | Status |
|------|-----|---------------|--------|
| 2024-12-03 | Tuesday | 5 games | ❌ Missing |
| 2024-12-10 | Tuesday | 5 games | ❌ Missing |
| 2024-12-11 | Wednesday | 5 games | ❌ Missing |
| 2024-12-12 | Thursday | 5 games | ❌ Missing |
| 2024-12-14 | Saturday | 5 games | ❌ Missing |

**Total December:** 25 games

---

### January 2025 (1 date - 5 games)

| Date | Day | Games Missing | Status |
|------|-----|---------------|--------|
| 2025-01-01 | Wednesday | 5 games | ❌ Missing (New Year's Day) |

**Total January:** 5 games

---

### February 2025 (3 dates - 14 games)

| Date | Day | Games Missing | Status | Notes |
|------|-----|---------------|--------|-------|
| 2025-02-02 | Sunday | 8 games | ❌ Missing | |
| 2025-02-14 | Friday | 0 games | ⚪ All-Star Break | No games scheduled |
| 2025-02-16 | Sunday | 6 games | ⚪ All-Star Sunday | Exhibition games only |

**Total February:** 14 games (2 actionable dates - Feb 14/16 are All-Star weekend, may not have data)

---

### March 2025 (1 date - 5 games)

| Date | Day | Games Missing | Status |
|------|-----|---------------|--------|
| 2025-03-03 | Monday | 5 games | ❌ Missing |

**Total March:** 5 games

---

### April 2025 (1 date - 8 games)

| Date | Day | Games Missing | Status |
|------|-----|---------------|--------|
| 2025-04-04 | Friday | 8 games | ❌ Missing |

**Total April:** 8 games

---

## 📊 Summary Statistics

**Total Missing:**
- **Dates:** 19 dates
- **Games:** 100 games
- **Percentage:** 8% of regular season (100 of 1,236 games)

**By Month:**
- November 2024: 43 games (8 dates)
- December 2024: 25 games (5 dates)
- January 2025: 5 games (1 date)
- February 2025: 14 games (3 dates) *includes All-Star*
- March 2025: 5 games (1 date)
- April 2025: 8 games (1 date)

**Priority Dates (Most Games Missing):**
1. November 15, 2024 - 8 games
2. February 2, 2025 - 8 games  
3. April 4, 2025 - 8 games

---

## 🔍 Investigation Checklist

Before running backfill, verify why data is missing:

### Step 1: Check BigDataBall Availability
```bash
# Check if files exist in GCS
gsutil ls gs://nba-scraped-data/big-data-ball/2024-25/2024-11-11/

# Expected: Multiple CSV files for each game
# If empty: BigDataBall never released this data
```

**Questions to answer:**
- [ ] Does BigDataBall have this data available on their site?
- [ ] Did our scraper fail to collect it?
- [ ] Did the processor fail to process it?

---

### Step 2: Check Scraper Logs
```bash
# Check scraper execution logs for these dates
grep "2024-11-11" ~/logs/bigdataball_scraper.log
grep "2024-11-15" ~/logs/bigdataball_scraper.log

# Look for:
# - Scraper execution timestamps
# - Error messages
# - HTTP errors (404, 503)
# - Timeout issues
```

---

### Step 3: Check Processor Logs
```bash
# Check processor logs
grep "2024-11-11" ~/logs/bigdataball_processor.log

# Look for:
# - Processing errors
# - CSV parsing failures
# - BigQuery insertion errors
```

---

## 🛠️ Backfill Execution Plan

### Option 1: Scraper Re-run (If Data Available on BigDataBall)

```bash
# Run scraper for specific dates
python scrapers/bigdataball/bigdataball_pbp.py \
  --start-date 2024-11-11 \
  --end-date 2024-11-11 \
  --force

# Repeat for each missing date
```

**Dates to backfill:**
```bash
# November 2024
2024-11-11, 2024-11-12, 2024-11-14, 2024-11-15
2024-11-19, 2024-11-22, 2024-11-26, 2024-11-29

# December 2024
2024-12-03, 2024-12-10, 2024-12-11, 2024-12-12, 2024-12-14

# January 2025
2025-01-01

# February 2025
2025-02-02
# Skip 2025-02-14, 2025-02-16 (All-Star weekend - may not have data)

# March 2025
2025-03-03

# April 2025
2025-04-04
```

---

### Option 2: Processor Re-run (If Files Already in GCS)

```bash
# Check if files exist
gsutil ls gs://nba-scraped-data/big-data-ball/2024-25/2024-11-11/

# If files exist, re-run processor
gcloud run jobs execute bigdataball-pbp-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-11,--end-date,2024-11-11"
```

---

### Option 3: Batch Backfill (All Dates at Once)

**⚠️ Warning:** Only use if data is confirmed available for all dates.

```bash
# Scraper batch backfill
python scrapers/bigdataball/bigdataball_pbp.py \
  --dates-file missing_dates.txt \
  --force

# Where missing_dates.txt contains:
# 2024-11-11
# 2024-11-12
# ... etc
```

Or processor batch:
```bash
# Process multiple months
gcloud run jobs execute bigdataball-pbp-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-01,--end-date,2024-11-30"
```

---

## ✅ Verification Procedure

After running backfill, verify data was loaded correctly.

### Step 1: Re-run Missing Games Query

```bash
cd ~/code/nba-stats-scraper

# Check missing games again
./scripts/validate-bigdataball missing > missing_after_backfill.txt

# Count remaining missing
grep '"game_date"' missing_after_backfill.txt | wc -l

# Expected: Should decrease from 100
```

**Success Criteria:**
- Missing games count decreases
- Specific dates no longer appear in results

---

### Step 2: Verify Specific Dates

```bash
# Check specific date was loaded
bq query --use_legacy_sql=false "
SELECT 
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as events,
  ROUND(AVG(events_per_game), 1) as avg_events
FROM (
  SELECT 
    game_date,
    game_id,
    COUNT(*) as events_per_game
  FROM \`nba-props-platform.nba_raw.bigdataball_play_by_play\`
  WHERE game_date = '2024-11-11'
  GROUP BY game_date, game_id
)
GROUP BY game_date
"

# Expected:
# - games: 6 (for Nov 11)
# - avg_events: ~450-500
```

---

### Step 3: Season Completeness Check

```bash
# Re-run season check
./scripts/validate-bigdataball season > season_after_backfill.txt

# Check games per team increased
grep '"reg_games"' season_after_backfill.txt | head -5

# Expected: 
# - Before: 73-76 games per team
# - After: Closer to 82 games per team
```

---

### Step 4: Event Quality Check

```bash
# Verify backfilled games have good quality
bq query --use_legacy_sql=false "
SELECT 
  game_id,
  COUNT(*) as total_events,
  COUNT(CASE WHEN event_type = 'shot' THEN 1 END) as shots,
  COUNT(CASE WHEN original_x IS NOT NULL THEN 1 END) as shots_with_coords,
  ROUND(COUNT(CASE WHEN original_x IS NOT NULL THEN 1 END) * 100.0 / 
        NULLIF(COUNT(CASE WHEN event_type = 'shot' THEN 1 END), 0), 1) as coord_pct
FROM \`nba-props-platform.nba_raw.bigdataball_play_by_play\`
WHERE game_date = '2024-11-11'
GROUP BY game_id
"

# Expected for each game:
# - total_events: 400-600
# - shots: 80-120
# - coord_pct: >50%
```

---

### Step 5: Cross-Validation with BDL Box Scores

```bash
# Verify games match BDL box scores
bq query --use_legacy_sql=false "
SELECT 
  b.game_date,
  b.game_id,
  COUNT(DISTINCT b.player_lookup) as bdl_players,
  p.has_pbp_data
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\` b
LEFT JOIN (
  SELECT DISTINCT game_id, TRUE as has_pbp_data
  FROM \`nba-props-platform.nba_raw.bigdataball_play_by_play\`
  WHERE game_date = '2024-11-11'
) p ON b.game_id = p.game_id
WHERE b.game_date = '2024-11-11'
GROUP BY b.game_date, b.game_id, p.has_pbp_data
ORDER BY b.game_id
"

# Expected:
# - All games should have has_pbp_data = TRUE
# - bdl_players should be ~20-30 per game
```

---

## 📋 Backfill Tracking Template

Use this to track backfill progress:

```markdown
## Backfill Progress Tracker

**Started:** [Date]
**Completed:** [Date]
**Executed By:** [Name]

### November 2024
- [ ] 2024-11-11 (6 games) - Status: _____ - Verified: _____
- [ ] 2024-11-12 (5 games) - Status: _____ - Verified: _____
- [ ] 2024-11-14 (4 games) - Status: _____ - Verified: _____
- [ ] 2024-11-15 (8 games) - Status: _____ - Verified: _____
- [ ] 2024-11-19 (6 games) - Status: _____ - Verified: _____
- [ ] 2024-11-22 (6 games) - Status: _____ - Verified: _____
- [ ] 2024-11-26 (4 games) - Status: _____ - Verified: _____
- [ ] 2024-11-29 (4 games) - Status: _____ - Verified: _____

### December 2024
- [ ] 2024-12-03 (5 games) - Status: _____ - Verified: _____
- [ ] 2024-12-10 (5 games) - Status: _____ - Verified: _____
- [ ] 2024-12-11 (5 games) - Status: _____ - Verified: _____
- [ ] 2024-12-12 (5 games) - Status: _____ - Verified: _____
- [ ] 2024-12-14 (5 games) - Status: _____ - Verified: _____

### January 2025
- [ ] 2025-01-01 (5 games) - Status: _____ - Verified: _____

### February 2025
- [ ] 2025-02-02 (8 games) - Status: _____ - Verified: _____
- [ ] 2025-02-14 (N/A) - All-Star Break - Skip
- [ ] 2025-02-16 (6 games) - All-Star Sunday - Skip or verify

### March 2025
- [ ] 2025-03-03 (5 games) - Status: _____ - Verified: _____

### April 2025
- [ ] 2025-04-04 (8 games) - Status: _____ - Verified: _____

**Final Verification:**
- [ ] Missing games count: Before _____ → After _____
- [ ] Season completeness improved: Yes / No
- [ ] All dates verified with quality checks
- [ ] Documentation updated
```

---

## 🚨 Known Issues & Special Cases

### All-Star Weekend (Feb 14-16, 2025)
**Issue:** BigDataBall may not provide play-by-play for All-Star exhibition games.

**Action:** 
- Feb 14: No games scheduled (skip)
- Feb 16: Check if BigDataBall has data for All-Star Game before backfilling

---

### New Year's Day (Jan 1, 2025)
**Issue:** Holiday may have affected scraper scheduling.

**Action:** Manual backfill likely required.

---

### Playoff Games with 0% Coordinates (Apr 15-18, 2025)
**Issue:** 7 playoff games have 0% shot coordinates (different issue than missing games).

**Action:** 
- This is a **BigDataBall data quality issue**, not a missing data issue
- These games ARE in the database but have incomplete coordinate data
- Monitor if future BigDataBall releases fix the coordinates
- May need to accept 0% coordinates for these specific games

---

## 📞 Support & Resources

**Validation Queries:**
- Missing games: `./scripts/validate-bigdataball missing`
- Season check: `./scripts/validate-bigdataball season`
- Quality check: `./scripts/validate-bigdataball quality`

**Documentation:**
- Validation guide: `validation/queries/raw/bigdataball_pbp/README.md`
- Discovery findings: `validation/queries/raw/bigdataball_pbp/DISCOVERY_FINDINGS.md`

**Processor:**
- Processor reference: `validation/PROCESSOR_REFERENCE.md` (Section 14)
- GCS path: `gs://nba-scraped-data/big-data-ball/2024-25/`

---

## ✅ Success Criteria

Backfill is complete when:

1. **Missing games ≤ 10** (from 100)
2. **Teams have 80-82 games** each (from 73-76)
3. **All dates verified** with quality checks passing
4. **Event counts normal** (400-600 per game)
5. **Shot coordinates present** (>50% for most games)

---

**Last Updated:** October 13, 2025  
**Status:** Ready for Execution  
**Priority:** Medium (8% missing data)  
**Timeline:** Execute when BigDataBall data availability confirmed
