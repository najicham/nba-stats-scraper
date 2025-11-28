# Player Boxscore Backfill Recovery Plan

**Created:** 2025-11-27
**Goal:** Get from 63.7% → 100% completion

---

## Current State

| Metric | Count | % |
|--------|-------|---|
| **Total dates** | 853 | 100% |
| ✅ **In BigQuery** | 543 | 63.7% |
| 📁 **In GCS only** | 79 | 9.3% |
| ❌ **Failed (need retry)** | 231 | 27.1% |

**Failure breakdown:**
- 220 dates: HTTP 500 errors (NBA.com API failures)
- 83 dates: Timeouts (NBA.com slow responses)

---

## Recovery Strategy

### Phase 1: Process GCS → BigQuery (79 dates) ⚡ QUICK WIN

**What:** 79 dates have data in GCS but never made it to BigQuery (streaming buffer errors)

**How:** Now that processors are fixed, just process the existing GCS files

**Estimated time:** ~5 minutes (processing local GCS files is fast)

**Commands:**
```bash
# Option A: Process all dates with GCS data
# The processor will automatically find and process GCS files
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
  --start-date=2021-10-01 \
  --end-date=2025-12-31

# Option B: Create a list of the 79 dates and process them specifically
# (safer, more targeted)
```

**Expected result:** 543 → 622 dates in BigQuery (72.9%)

---

### Phase 2: Retry Failed Scrapes (303 dates)

**What:** Dates that failed during scraping (HTTP 500 / timeouts from NBA.com)

**Strategy:** Retry with lower concurrency and longer timeouts

**Recommended approach:**
```bash
# Create CSV from failed dates JSON
cat backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_20251126_162719.json | \
  jq -r '.failed_dates[].game_date' > \
  backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_retry.csv

# Retry with fewer workers and longer timeout
python backfill_jobs/scrapers/nbac_player_boxscore/nbac_player_boxscore_scraper_backfill_v2.py \
  --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app \
  --csv=backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_retry.csv \
  --workers=6 \     # Half the workers (less NBA.com load)
  --timeout=180     # Longer timeout (3 min vs 2 min)
```

**Why this will work better:**
- ✅ Streaming buffer issue is FIXED (processors use batch loading now)
- ✅ Fewer workers = less chance of NBA.com rate limiting
- ✅ Longer timeout = handles slow NBA.com responses
- ✅ Skip logic = won't re-scrape 622 dates already in GCS

**Estimated time:** ~25-30 minutes (303 dates ÷ 6 workers ÷ 60s each)

**Expected result:** 622 → ~800+ dates in BigQuery

---

### Phase 3: Handle Stubborn Failures

After Phase 2, some dates may still fail. Common reasons:

**NBA.com API issues:**
- Specific dates where NBA.com has no data
- Play-In games (like the 6 we documented earlier)
- Dates with API bugs

**Strategy:**
1. Check if dates exist in ESPN or BDL as fallback
2. Document as known gaps if no sources have data
3. Accept high completion rate (95%+) rather than chase impossible 100%

---

## Quick Start Commands

### Step 1: Process GCS files to BigQuery
```bash
cd /home/naji/code/nba-stats-scraper

# Find which dates have GCS files but not in BigQuery
# (We need to create a script for this, or just process all dates)

# For now, simplest: run processor for date range
# It will skip dates already in BigQuery, process GCS files
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
  --start-date=2021-10-01 \
  --end-date=2025-12-31
```

### Step 2: Create retry CSV from failed dates
```bash
# Extract just the dates from the failed JSON
cat backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_20251126_162719.json | \
  jq -r '.failed_dates[].game_date' > \
  backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_retry.csv

# Verify it looks right
head -5 backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_retry.csv
wc -l backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_retry.csv
```

### Step 3: Retry failed scrapes
```bash
# Retry with safer settings (fewer workers, longer timeout)
python backfill_jobs/scrapers/nbac_player_boxscore/nbac_player_boxscore_scraper_backfill_v2.py \
  --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app \
  --csv=backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_retry.csv \
  --workers=6 \
  --timeout=180

# Monitor progress - it will log every 50 dates
```

---

## Expected Timeline

| Phase | Duration | Result |
|-------|----------|--------|
| **Phase 1: GCS → BQ** | ~5 min | 543 → 622 dates (72.9%) |
| **Phase 2: Retry scrapes** | ~30 min | 622 → ~800+ dates (93%+) |
| **Phase 3: Document gaps** | ~10 min | Accept 95%+ as success |
| **Total** | ~45 min | **≥95% completion** |

---

## Success Criteria

✅ **Minimum:** 95% coverage (810/853 dates)
🎯 **Target:** 98% coverage (835/853 dates)
🏆 **Stretch:** 100% coverage (853/853 dates)

**Realistic expectation:** 95-98% is excellent. Some dates may simply not have data available from NBA.com API.

---

## Monitoring Progress

### Check GCS coverage
```bash
gsutil ls gs://nba-scraped-data/nba-com/player-boxscores/ | wc -l
# Target: 853 (100%)
```

### Check BigQuery coverage
```bash
bq query --use_legacy_sql=false \
  "SELECT COUNT(DISTINCT DATE(game_date)) as dates
   FROM \`nba-props-platform.nba_raw.nbac_player_boxscores\`
   WHERE game_date >= '2021-10-01'"
# Target: 853 (100%)
```

### Compare with schedule
```bash
# Should match the original 853 dates
wc -l backfill_jobs/scrapers/nbac_player_boxscore/game_dates_to_scrape.csv
```

---

## Fallback: If Retry Still Fails

If Phase 2 retry still has high failure rate:

1. **Try even more conservative settings:**
   - `--workers=3` (vs 6)
   - `--timeout=300` (5 minutes)
   - Run overnight if needed

2. **Split by season:**
   - Process 2021-22 season separately
   - Process 2022-23 season separately
   - Etc.

3. **Manual investigation:**
   - Check specific failed dates in NBA.com website
   - Try alternate scrapers (ESPN, BDL)
   - Document as known gaps

---

## Notes

- **Streaming buffer is FIXED** ✅ - processors now use batch loading
- **Script already has resume logic** ✅ - won't re-scrape existing GCS data
- **Failed dates saved** ✅ - `failed_dates_20251126_162719.json`
- **New v2 script works** ✅ - tested and operational

**Ready to execute!** 🚀
