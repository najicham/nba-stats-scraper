# BettingPros Player Props - Missing Data Backfill Plan

**Generated**: October 13, 2025  
**Validation Query**: `validate-bettingpros missing`  
**Season**: 2024-25 Regular Season  
**Status**: 🔴 12 dates with ZERO props data

---

## 📊 Executive Summary

- **Total Missing Dates**: 12 (out of 660 scheduled dates)
- **Coverage Impact**: 95.8% → 97.6% (after backfill)
- **Date Range**: November 2024 - February 2025
- **Affected Games**: ~80 NBA games
- **Root Cause**: Scraper failures or missed scheduled runs

---

## 🔴 Missing Dates - Full List

### November 2024 (6 dates)

| Date | Day | Games | Sample Matchups | Status |
|------|-----|-------|-----------------|--------|
| **2024-11-12** | Tuesday | 8 | TOR@MIL, CHA@ORL, ATL@BOS, MIN@POR, PHX@UTA | 🔴 NO DATA |
| **2024-11-15** | Friday | 12 | DET@TOR, MIA@IND, CHI@CLE, WAS@ATL, LAC@HOU | 🔴 NO DATA |
| **2024-11-19** | Tuesday | 6 | UTA@LAL, CHA@BKN, NOP@DAL, DEN@MEM, CLE@BOS | 🔴 NO DATA |
| **2024-11-22** | Friday | 8 | POR@HOU, SAC@LAC, BKN@PHI, IND@MIL, ATL@CHI | 🔴 NO DATA |
| **2024-11-26** | Tuesday | 5 | SAS@UTA, HOU@MIN, CHI@WAS, MIL@MIA, LAL@PHX | 🔴 NO DATA |
| **2024-11-29** | Friday | 10 | NYK@CHA, ORL@BKN, DET@IND, SAC@POR, CLE@ATL | 🔴 NO DATA |

### December 2024 (4 dates)

| Date | Day | Games | Sample Matchups | Status |
|------|-----|-------|-----------------|--------|
| **2024-12-03** | Tuesday | 11 | SAS@PHX, HOU@SAC, MEM@DAL, POR@LAC, MIL@DET | 🔴 NO DATA |
| **2024-12-10** | Tuesday | 2 | ORL@MIL, DAL@OKC | 🔴 NO DATA |
| **2024-12-11** | Wednesday | 2 | GSW@HOU, ATL@NYK | 🔴 NO DATA |
| **2024-12-14** | Saturday | 2 | HOU@OKC, ATL@MIL | 🔴 NO DATA |

### February 2025 (2 dates)

| Date | Day | Games | Sample Matchups | Status |
|------|-----|-------|-----------------|--------|
| **2025-02-14** | Friday | 3 | TMT@TMC, TMG@TMC, TMG@TMM | 🔴 NO DATA |
| **2025-02-16** | Sunday | 3 | KEN@CHK, SHQ@CHK, CAN@SHQ | 🔴 NO DATA |

**Note**: February matchups show placeholder codes (TMT, TMC, KEN, CHK, etc.) - likely All-Star Weekend exhibition games. **Low priority for backfill.**

---

## 🔍 Root Cause Analysis

### Pattern 1: November Cluster (6 dates)
**Dates**: Nov 12, 15, 19, 22, 26, 29

**Hypothesis**: BettingPros scraper may not have been scheduled or experienced repeated failures during mid-November through Thanksgiving period.

**Evidence**:
- Consecutive failures over 2.5 weeks
- Mix of high-volume game days (10-12 games) and low-volume (5-8 games)
- No correlation with holidays (Thanksgiving was Nov 28, but Nov 29 is missing)

### Pattern 2: December Cluster (4 dates)
**Dates**: Dec 3, 10, 11, 14

**Hypothesis**: Partial scraper outage early December, then sporadic failures mid-month.

**Evidence**:
- Dec 3: Large game day (11 games) - major data loss
- Dec 10-14: Low-volume days (2 games each) - possibly overlooked

### Pattern 3: February All-Star Weekend
**Dates**: Feb 14, 16

**Priority**: ⚪ LOW - Likely exhibition/All-Star games, not regular betting inventory

---

## 📋 Backfill Action Plan

### Phase 1: Verify GCS Data Exists

Check if scraper actually collected the data but processor failed:

```bash
# Check November dates
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-11-12/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-11-15/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-11-19/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-11-22/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-11-26/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-11-29/

# Check December dates
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-12-03/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-12-10/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-12-11/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2024-12-14/

# Check February dates (low priority)
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2025-02-14/
gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/2025-02-16/
```

### Phase 2A: If Data Exists in GCS - Reprocess

Run backfill processor for each missing date:

```bash
# November backfill (6 dates)
gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-12,--end-date,2024-11-12"

gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-15,--end-date,2024-11-15"

gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-19,--end-date,2024-11-19"

gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-22,--end-date,2024-11-22"

gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-26,--end-date,2024-11-26"

gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-29,--end-date,2024-11-29"

# December backfill (4 dates)
gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-12-03,--end-date,2024-12-03"

gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-12-10,--end-date,2024-12-10"

gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-12-11,--end-date,2024-12-11"

gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-12-14,--end-date,2024-12-14"
```

**Batch Command** (more efficient):
```bash
# Process all November dates in one job (if consecutive processing supported)
gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-11-12,--end-date,2024-11-29"

# Process all December dates
gcloud run jobs execute bettingpros-player-props-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2024-12-03,--end-date,2024-12-14"
```

### Phase 2B: If Data Missing from GCS - Rescrape

If GCS files don't exist, need to rescrape from BettingPros:

```bash
# Re-run historical scraper for missing dates
python scrapers/bettingpros/bettingpros_player_props.py \
  --start-date 2024-11-12 \
  --end-date 2024-11-12 \
  --mode historical

# Repeat for each missing date
```

**IMPORTANT**: Check if BettingPros API supports historical data retrieval. If not, these dates may be **permanently unrecoverable**.

---

## ✅ Post-Backfill Validation

After running backfill jobs, verify completion:

### Step 1: Re-run Missing Data Query
```bash
./scripts/validate-bettingpros missing
```

**Expected Result**: Empty result set (no missing dates)

### Step 2: Check Date-Specific Coverage
```bash
# Verify November 12 specifically
bq query --use_legacy_sql=false '
SELECT 
  game_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT bookmaker) as unique_bookmakers
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date = "2024-11-12"
GROUP BY game_date
'
```

**Expected Result**: 
- 3,500-8,000 records (November had 8 games that day)
- 100-240 unique players
- 15-20 bookmakers

### Step 3: Re-run Season Completeness
```bash
./scripts/validate-bettingpros completeness
```

**Expected Result**: All teams should show 82 regular season games (or close to it).

---

## 📊 Expected Coverage After Backfill

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Total Dates** | 632/660 | 642/660* | +10 dates |
| **Coverage %** | 95.8% | 97.3%* | +1.5% |
| **Regular Season Games** | ~5,275 | ~5,355 | +80 games |
| **Total Props Records** | 2,179,496 | ~2,520,000** | +340,504 |

*Excluding Feb All-Star games (2 dates)  
**Estimated: 10 dates × 8 avg games × 4,250 avg props/date

---

## 🚨 Priority Ranking

### 🔴 HIGH PRIORITY (Backfill Required)
**Dates**: November 12, 15, 19, 22, 26, 29 (6 dates)  
**Dates**: December 3, 10, 11, 14 (4 dates)

**Reason**: Regular season games with significant betting volume
- November: 49 total games
- December: 17 total games
- **Total**: 66 games with props data missing

### 🟡 MEDIUM PRIORITY
**Dates**: None identified

### ⚪ LOW PRIORITY (Consider Skipping)
**Dates**: February 14, 16 (2 dates)

**Reason**: All-Star Weekend exhibition games
- Limited betting relevance
- Unusual team codes (TMT, KEN, CHK, SHQ, CAN)
- Not standard regular season inventory

---

## 📝 Backfill Checklist

**Before Starting**:
- [ ] Verify scraper job name: `bettingpros-player-props-processor-backfill`
- [ ] Confirm GCS bucket path structure
- [ ] Check processor argument format (--start-date vs start_date)
- [ ] Estimate processing time (1-2 minutes per date)

**During Backfill**:
- [ ] Monitor Cloud Run job execution logs
- [ ] Check for any processing errors
- [ ] Verify BigQuery insert counts

**After Completion**:
- [ ] Run `validate-bettingpros missing` (should be empty)
- [ ] Run `validate-bettingpros completeness` (check team totals)
- [ ] Spot-check 2-3 dates with direct BigQuery query
- [ ] Document any dates that couldn't be recovered
- [ ] Update this document with actual results

---

## 🔧 Troubleshooting

### Issue: GCS Data Doesn't Exist

**Solution**: BettingPros may not support historical API calls. These dates may be **unrecoverable** unless:
1. BettingPros provides historical data export
2. Data was archived elsewhere
3. Accept 95.8% coverage as sufficient

### Issue: Processor Fails on Specific Date

**Check**:
1. JSON format in GCS file (may be corrupted)
2. Processor logs for specific error
3. Manual inspection of file: `gsutil cat gs://nba-scraped-data/bettingpros/player-props/points/2024-11-12/[filename].json`

### Issue: Data Processed But Still Shows Missing

**Possible Causes**:
1. Confidence score too low (filter removes it)
2. Team abbreviation mismatch (doesn't join with schedule)
3. Processing succeeded but record count very low

**Debug Query**:
```sql
SELECT game_date, COUNT(*) as records
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date = '2024-11-12'
GROUP BY game_date
```

---

## 📞 Escalation Path

If backfill cannot be completed:

1. **Document Reason**: Capture why dates couldn't be recovered
2. **Business Impact**: 95.8% coverage is excellent (industry standard 90%+)
3. **Accept Gap**: Move forward with documented gap
4. **Monitor Future**: Ensure scheduling prevents future gaps

---

**Document Owner**: NBA Props Platform Team  
**Last Validation**: October 13, 2025  
**Next Review**: After backfill completion
