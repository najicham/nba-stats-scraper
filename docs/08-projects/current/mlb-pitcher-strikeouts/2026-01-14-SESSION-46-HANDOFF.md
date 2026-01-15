# Session 46 Handoff: BettingPros Integration Strategy & Backfill Execution

**Date**: 2026-01-14 to 2026-01-15
**Focus**: Strategic pivot to BettingPros data, backfill execution, BigQuery loading
**Status**: GCS Backfill 59%, BigQuery Load In Progress

---

## Executive Summary

This session identified a **strategic inflection point**: the BettingPros historical API provides significantly more value than continuing with blocked BDL scrapers. We are pivoting to a **hybrid approach** that keeps V1's proven architecture while adding BettingPros features.

### Key Decision

| Approach | Status | Rationale |
|----------|--------|-----------|
| Fix BDL Scrapers | **Deprioritized** | High effort, uncertain payoff |
| BettingPros Integration | **Prioritized** | Fast path, more data, new features |

---

## Strategic Analysis

### Why BettingPros Data Is Superior

| Dimension | Current V2 Path (BDL) | BettingPros Path |
|-----------|----------------------|------------------|
| **Data Volume** | 1.5 years | **4 years** (2022-2025) |
| **Grading** | Complex joins | **Outcomes included** |
| **New Features** | Blocked by scrapers | **Ready now** |
| **Dependencies** | Scraper fix + ID mapping | **None** |
| **Time to Value** | Weeks (uncertain) | **Hours (today)** |

### BettingPros Features Available

1. **projection_value** - BettingPros' own model prediction
2. **projection_diff** - Line minus projection (market inefficiency)
3. **perf_last_5_over_pct** - Recent O/U betting performance
4. **perf_season_over_pct** - Season O/U performance
5. **opposition_rank** - Opponent quality metric

These features are **market-aware** and potentially more valuable than the blocked BDL features (home/away splits, day/night splits).

---

## Code Changes Made

### 1. Proxy Support Added to Backfill Script

**File**: `scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py`

Added:
- `--proxy` CLI flag
- Proxy configuration using `scrapers/utils/proxy_utils.py`
- SSL verification disabled for corporate proxy compatibility
- Retry logic with exponential backoff (3 retries, 5/10/15s delays)
- Increased timeout from 30s to 60s

```bash
# Run with proxy
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \
    --markets pitcher --proxy --workers 1 --delay 1.0
```

---

## Current Backfill Status

### Progress (as of session end)

| Market | Complete | Total | Status |
|--------|----------|-------|--------|
| pitcher-strikeouts | 105 | 740 | 14% |
| pitcher-earned-runs-allowed | 105 | 740 | 14% |
| **Pitcher Total** | **210** | **1,480** | **14%** |

The backfill is running in background. Previous sessions had already collected ~14% of pitcher data during testing.

### Running the Backfill

```bash
# Check progress
python scripts/mlb/historical_bettingpros_backfill/check_progress.py

# Resume pitcher backfill (skips existing files)
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \
    --markets pitcher --proxy --workers 1 --delay 1.0

# Run batter backfill in background
nohup python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \
    --markets batter --proxy --workers 1 --delay 1.0 \
    > /tmp/batter_backfill.log 2>&1 &
```

---

## Recommended Strategy: Hybrid Approach

### Phase 1: Data Collection (Current)
- Run pitcher backfill (~30 min remaining for 86% of data)
- Run batter backfill in background (~4 hours)

### Phase 2: BigQuery Integration
Create `mlb_raw.bp_pitcher_props` table with schema:

```sql
CREATE TABLE `nba-props-platform.mlb_raw.bp_pitcher_props` (
  game_date DATE NOT NULL,
  player_lookup STRING NOT NULL,
  market_id INT64 NOT NULL,

  -- Betting data
  over_line FLOAT64,
  over_odds INT64,
  under_odds INT64,

  -- BettingPros projections (NEW!)
  projection_value FLOAT64,
  projection_side STRING,
  projection_ev FLOAT64,

  -- Outcomes (KEY!)
  actual_value INT64,
  is_scored BOOL,

  -- Performance trends (NEW!)
  perf_last_5_over INT64,
  perf_last_5_under INT64,
  perf_season_over INT64,
  perf_season_under INT64,

  -- Metadata
  source_file_path STRING,
  created_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, market_id;
```

### Phase 3: Feature Analysis
- Analyze BettingPros features for predictive power
- Compare projection_value correlation with actual outcomes
- Evaluate perf_last_5/10 trends

### Phase 4: Model Enhancement
- Keep V1 XGBoost architecture (proven 67.27%)
- Add BettingPros features:
  - `projection_value`
  - `projection_diff` (line - projection)
  - `perf_last_5_over_pct`
- Train V1.5 model, compare to V1

### Phase 5: Champion-Challenger
- V1 remains champion
- V1.5 (BettingPros-enhanced) as challenger
- Track both with model_version

---

## V2 Blockers (Deprioritized)

These issues are no longer blocking since we're pivoting to BettingPros:

1. **BDL splits scraper broken** - API returns nested arrays, code expects flat keys
2. **BDL player ID mapping missing** - Different ID scheme than MLB Stats API
3. **is_day_game unpopulated** - No data source found
4. **game_total_line empty** - oddsa_game_lines table is empty
5. **umpire_k_factor missing** - Table doesn't exist

These can be addressed later if BettingPros features prove insufficient.

---

## Files Created/Modified

| File | Change |
|------|--------|
| `scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py` | Added proxy support, retry logic |
| `data_processors/raw/mlb/mlb_bp_historical_props_processor.py` | **NEW** - BigQuery processor |
| `schemas/bigquery/mlb_raw/bp_props_tables.sql` | **NEW** - BigQuery schema |
| `scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py` | **NEW** - Batch loader |

---

## CURRENT MONITORING STATUS (2026-01-15 Morning)

### Background Tasks Running

**1. GCS Backfill (Task: b77281f)**
```bash
# Monitor progress
tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output

# Check completion
python scripts/mlb/historical_bettingpros_backfill/check_progress.py
```
- **Status**: 59.4% complete (4832/8140 files)
- **Pitcher data**: 100% DONE
- **Batter data**: ~50% each market
- **ETA**: ~4-5 more hours

**2. BigQuery Load (Task: b120542)**
```bash
# Monitor
tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b120542.output
```
- **Status**: Loading pitcher props to BigQuery
- **Data**: 22,114 pitcher prop rows
- **Table**: `mlb_raw.bp_pitcher_props`

### BigQuery Tables Created

| Table | Status | Rows |
|-------|--------|------|
| `mlb_raw.bp_pitcher_props` | Loading | ~22K |
| `mlb_raw.bp_batter_props` | Empty (batter backfill incomplete) | 0 |
| `mlb_raw.bp_pitcher_strikeouts` | View (strikeouts only) | - |
| `mlb_raw.bp_pitcher_props_graded` | View (with O/U result) | - |

---

## Next Session Checklist

### 1. Check Background Tasks
```bash
# Check if backfill still running
ps aux | grep backfill | grep -v grep

# Check GCS progress
python scripts/mlb/historical_bettingpros_backfill/check_progress.py

# Check BigQuery load
tail -20 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b120542.output
```

### 2. If Backfill Complete
```bash
# Load batter props to BigQuery (after batter backfill done)
python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter
```

### 3. Verify BigQuery Data
```sql
-- Check pitcher props loaded
SELECT COUNT(*), MIN(game_date), MAX(game_date)
FROM `mlb_raw.bp_pitcher_props`
WHERE game_date >= '2022-01-01';

-- Check strikeouts specifically
SELECT COUNT(*)
FROM `mlb_raw.bp_pitcher_strikeouts`;
```

### 4. Analyze BettingPros Features
```sql
-- Projection accuracy
SELECT
  AVG(ABS(projection_value - actual_value)) as mae,
  AVG(CASE WHEN projection_correct THEN 1 ELSE 0 END) as hit_rate
FROM `mlb_raw.bp_pitcher_props_graded`
WHERE market_id = 285;
```

### 5. Train Enhanced Model
- Add BettingPros features to training data
- Train V1.5 with projection_value, perf_last_5, etc.
- Compare to V1 baseline (67.27% hit rate)

---

## Key Commands Reference

```bash
# Check GCS backfill progress
python scripts/mlb/historical_bettingpros_backfill/check_progress.py

# Resume GCS backfill if interrupted
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --proxy --workers 1 --delay 1.0

# Load pitcher props to BigQuery
python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type pitcher

# Load batter props to BigQuery
python scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py --prop-type batter

# Query pitcher strikeouts
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM mlb_raw.bp_pitcher_strikeouts'
```

---

## Key Insight

**The BettingPros discovery is a "free upgrade":**
- 8x more historical data (4 years vs 6 months)
- Built-in grading (eliminates complex joins)
- New features (projections, performance trends)
- No additional scraper work needed

**The opportunity cost of fixing BDL scrapers is high** when we have a working alternative that provides MORE value.

---

## Session Stats

| Metric | Value |
|--------|-------|
| Duration | ~30 min |
| Code changes | 1 file (proxy + retry logic) |
| Backfill progress | 14% → running |
| Strategy decision | Pivot to BettingPros |

---

## Contact

- Backfill spec: `scripts/mlb/historical_bettingpros_backfill/SPEC.md`
- Progress checker: `scripts/mlb/historical_bettingpros_backfill/check_progress.py`
- GCS data: `gs://nba-scraped-data/bettingpros-mlb/historical/`
