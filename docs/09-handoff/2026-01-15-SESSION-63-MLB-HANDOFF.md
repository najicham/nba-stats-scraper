# Session 63 MLB Handoff: Batter Props Backfill + Pre-Season Prep

**Date**: 2026-01-15
**Focus**: Complete batter props backfill (ODDS API + BettingPros), pre-season checklist
**Status**: ODDS API complete, BettingPros ~87% complete

---

## Quick Start for New Chat

```bash
# Read this handoff
cat docs/09-handoff/2026-01-15-SESSION-63-MLB-HANDOFF.md

# Check BettingPros backfill progress (if still running)
tail -10 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output

# If backfill complete, load to BigQuery
PYTHONPATH=. python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter
```

---

## What Was Accomplished This Session

### 1. ODDS API Batter Props - COMPLETE ✅

**Backfill**: All 345 dates scraped (Apr 2024 - Sep 2025)
**BigQuery Load**: 635,497 rows loaded to `mlb_raw.oddsa_batter_props`

**Market Breakdown**:
| Market | Rows | Coverage |
|--------|------|----------|
| batter_hits | 152,035 | Full (345 dates) |
| batter_rbis | 149,404 | Full (345 dates) |
| batter_total_bases | 140,333 | Full (345 dates) |
| batter_home_runs | 104,286 | Full (345 dates) |
| batter_walks | 64,423 | 342 dates |
| batter_strikeouts | 25,016 | **Only 117 dates (through Sep 2024)** ⚠️ |

**Note**: `batter_strikeouts` market was discontinued by ODDS API after Sept 2024.

### 2. BettingPros Batter Props - IN PROGRESS 🔄

**Backfill Progress**: ~87% complete (7086/8140 props)
**Task ID**: `b77281f`
**Monitor**: `tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output`

**When Complete, Run**:
```bash
PYTHONPATH=. python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter
```

### 3. Missing Dates Filled

Retried 4 failed BettingPros dates:
- batter-doubles 2024-09-20: 207 props ✅
- batter-hits 2025-04-04: 207 props ✅
- batter-runs 2025-04-20: 182 props ✅
- batter-stolen-bases 2025-04-21: 0 props ✅

Filled 3 missing ODDS API dates:
- 2025-06-14: 15 events ✅
- 2025-06-15: 14 events ✅
- 2025-08-31: 14 events ✅

### 4. Created Batch Loader for ODDS API Batter Props

**New File**: `scripts/mlb/historical_odds_backfill/batch_load_batter_props_to_bigquery.py`

Features:
- Parallel GCS downloads
- NDJSON batch loading to BigQuery
- Resume capability (tracks loaded dates)
- Expected K calculation for batter strikeouts

### 5. Pre-Season Checklist Doc

**New File**: `docs/08-projects/current/mlb-pitcher-strikeouts/MLB-PRESEASON-CHECKLIST.md`

Contains:
- Critical items before season (8 hrs work)
- Important improvements (can wait)
- Tech debt documentation
- Opening Day checklist

### 6. Architecture Analysis

**Key Finding**: SmartIdempotencyMixin NOT needed for MLB

Reason: MLB processors use `APPEND_ALWAYS` strategy for time-series odds data. SmartIdempotencyMixin only prevents duplicates with `MERGE_UPDATE` strategy - not applicable here.

**Confirmed Working**:
- All MLB processors use ProcessorBase correctly ✅
- Registered in main_processor_service.py ✅
- Batch loaders are one-time scripts (acceptable) ✅

---

## Background Task Status

### BettingPros Backfill (b77281f)

**Status**: Running (~87% complete)
**Current**: June 25, 2025 data
**ETA**: ~10-15 minutes

**When Complete**:
```bash
# 1. Load batter props to BigQuery
PYTHONPATH=. python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter

# 2. Verify data
bq query --use_legacy_sql=false "
SELECT market_name, COUNT(*) as props, COUNT(DISTINCT game_date) as dates
FROM mlb_raw.bp_batter_props
GROUP BY market_name
ORDER BY props DESC"
```

---

## Data Pipeline Summary

### BigQuery Tables Status

| Table | Rows | Status |
|-------|------|--------|
| `mlb_raw.oddsa_batter_props` | 635,497 | ✅ Complete |
| `mlb_raw.oddsa_pitcher_props` | ~200K | ✅ Complete (prior session) |
| `mlb_raw.bp_batter_props` | 0 | ⏳ Waiting for load |
| `mlb_raw.bp_pitcher_props` | ~30K | ✅ Complete (prior session) |

### Date Coverage

| Source | Type | Date Range | Notes |
|--------|------|------------|-------|
| **BettingPros** | Pitcher | Apr 2022 - Sep 2025 | 740 dates, complete |
| **BettingPros** | Batter | Apr 2022 - Sep 2025 | 740 dates, backfill running |
| **ODDS API** | Pitcher | Apr 2024 - Sep 2025 | 345 dates, complete |
| **ODDS API** | Batter | Apr 2024 - Sep 2025 | 345 dates, loaded |

---

## Pre-Season Critical Path

### Must Complete Before Opening Day (8 hours)

1. **Verify output validation table** (1 hr)
   ```bash
   bq show mlb_orchestration.processor_output_validation
   ```

2. **Add MLB error patterns** (2 hrs)
   - Add rainout/postponement patterns to `_categorize_failure()`

3. **Deploy MLB prediction worker** (1 hr)
   ```bash
   ./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
   ```

4. **E2E pipeline test** (4 hrs)
   ```bash
   PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28
   ```

---

## Files Created/Modified

### New Files
- `scripts/mlb/historical_odds_backfill/batch_load_batter_props_to_bigquery.py`
- `docs/08-projects/current/mlb-pitcher-strikeouts/MLB-PRESEASON-CHECKLIST.md`

### Modified Files
- `scripts/mlb/historical_bettingpros_backfill/current_run_failures.json` (cleared after retries)

---

## Key Findings

### ODDS API Limitations
- Historical endpoint returns 404 for prop markets
- Data was scraped LIVE during 2024-2025 seasons
- Cannot backfill earlier than April 2024
- `batter_strikeouts` market discontinued after Sept 2024

### BettingPros Advantages
- 3+ years of data (2022-2025)
- Complete daily coverage (no gaps during seasons)
- Includes actual outcomes for grading
- Better source for historical analysis

### Architecture Alignment
- MLB processors follow NBA patterns correctly
- SmartIdempotencyMixin not needed (APPEND_ALWAYS)
- Batch loaders acceptable for one-time use
- No major tech debt blocking season

---

## Scheduler Jobs Status

All 11 MLB scheduler jobs configured and **PAUSED**:
- `mlb-shadow-mode-daily` (1:30 PM)
- `mlb-shadow-grading-daily` (10:30 AM)
- Plus 9 other scraper/processing jobs

Enable before Opening Day (late March).

---

## Commands Reference

```bash
# Monitor BettingPros backfill
tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output

# Load BettingPros batter props (after backfill)
PYTHONPATH=. python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter

# Verify ODDS API data
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM mlb_raw.oddsa_batter_props"

# Verify BettingPros data (after load)
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM mlb_raw.bp_batter_props"

# Test shadow mode
PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py --date 2025-09-28 --dry-run

# Deploy worker
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
```

---

## Session Statistics

- **Duration**: ~3 hours
- **ODDS API rows loaded**: 635,497
- **BettingPros dates retried**: 4
- **ODDS API dates filled**: 3
- **Documents created**: 2

---

## Next Session Priorities

1. ⏳ Complete BettingPros batter props BigQuery load
2. Verify all data loaded correctly
3. Run E2E pipeline test
4. Deploy MLB prediction worker with shadow mode fixes
5. (Optional) Add MLB-specific error patterns

---

**Primary Outcome**: ODDS API batter props fully loaded (635K rows), BettingPros backfill 87% complete, pre-season checklist documented
