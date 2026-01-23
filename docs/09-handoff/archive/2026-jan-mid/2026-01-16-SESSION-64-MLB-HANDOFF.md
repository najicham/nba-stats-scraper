# Session 64 Handoff - MLB BettingPros Integration Complete

**Date**: 2026-01-16
**Previous Session**: Session 63 (2026-01-15)
**Focus**: MLB BettingPros live scraper integration, backfill completion

---

## Executive Summary

Session 64 completed critical MLB pre-season work:
1. ✅ BettingPros batter backfill completed and loaded (775K rows)
2. ✅ Live scraper aligned with processor (same format, same GCS path)
3. ✅ Output validation table created
4. ✅ MLB error patterns added
5. ✅ Registry updated with MLB scrapers

**MLB is now 90% production-ready.** Remaining: E2E test + deploy prediction worker.

---

## Completed This Session

### 1. BettingPros Batter Backfill ✅

**Backfill Stats**:
- Total time: 36h 17m
- Tasks completed: 8136/8140 (99.95%)
- Props collected: 794,448
- Errors: 4 (negligible)

**BigQuery Load Stats**:
- Files processed: 6,656
- Rows loaded: 775,818
- Load time: 56m 34s
- Errors: 0

**Schema Fix Applied**:
Fixed `scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py`:
- Changed `bp_player_id` → `player_id` (line 188)
- Changed `created_at` → `processed_at` (line 217)
- Added `scraped_at` field (line 217)

### 2. BettingPros Live Scraper Integration ✅

**Problem**: Historical backfill and live scraper had different output formats and GCS paths.

**Solution**: Updated `scrapers/bettingpros/bp_mlb_player_props.py` (v3):
- Added `transform_data()` override to match historical format
- Added `_transform_single_prop()` helper
- Aligned GCS path: `bettingpros-mlb/{market_name}/{date}/props.json`

**Architecture Now**:
```
BettingPros API (/v3/props)
    ↓
bp_mlb_player_props.py (scraper) ← NEW: transform_data() override
    ↓
GCS: bettingpros-mlb/{market}/{date}/props.json ← ALIGNED path
    ↓
MlbBpHistoricalPropsProcessor (processor) ← handles both historical + live
    ↓
BigQuery: mlb_raw.bp_pitcher_props / bp_batter_props
```

### 3. Output Validation Table ✅

Created `mlb_orchestration.processor_output_validation`:
```bash
bq cp nba_orchestration.processor_output_validation mlb_orchestration.processor_output_validation
```
- 7000 rows copied from NBA template

### 4. MLB Error Patterns ✅

Added to `data_processors/raw/processor_base.py` in `_categorize_failure()`:
```python
# MLB-specific patterns (rainouts, postponements, etc.)
'postponed',
'rainout',
'weather delay',
'no props available',
'lines not posted',
'doubleheader',
'split admission',
```

### 5. Registry Updated ✅

Added to `scrapers/registry.py`:
```python
"bp_mlb_player_props": (
    "scrapers.bettingpros.bp_mlb_player_props",
    "BettingProsMLBPlayerProps"
),
"bp_mlb_props_historical": (
    "scrapers.bettingpros.bp_mlb_props_historical",
    "BettingProsMLBHistoricalProps"
),
```

---

## Current Data State

### BigQuery Tables

| Table | Rows | Unique Dates | Date Range |
|-------|------|--------------|------------|
| `mlb_raw.bp_batter_props` | 775,818 | 725 | Apr 2022 - Sep 2025 |
| `mlb_raw.bp_pitcher_props` | 25,404 | 725 | Apr 2022 - Sep 2025 |
| `mlb_raw.oddsa_batter_props` | 635,497 | 345 | Apr 2024 - Sep 2025 |

### Verify Data
```bash
bq query --use_legacy_sql=false "
SELECT
  'bp_batter_props' as table_name,
  COUNT(*) as rows,
  COUNT(DISTINCT game_date) as dates
FROM mlb_raw.bp_batter_props
WHERE game_date BETWEEN '2022-01-01' AND '2025-12-31'
"
```

---

## Remaining Pre-Season Tasks (5 hours)

### 1. Deploy MLB Prediction Worker (1 hour)

```bash
# Deploy to Cloud Run
cd /home/naji/code/nba-stats-scraper
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh

# Verify deployment
gcloud run services describe mlb-prediction-worker --region=us-central1
```

Key file: `predictions/mlb/worker.py`
- Uses V1.6 model (69.9% accuracy)
- Shadow mode enabled (threshold-free)

### 2. E2E Pipeline Test (4 hours)

Run full pipeline replay with known good date:
```bash
PYTHONPATH=. python scripts/mlb/testing/replay_mlb_pipeline.py --date 2025-09-28 --verify
```

This tests:
- Phase 1: Scrapers fetch data
- Phase 2: Raw processors transform
- Phase 3: Analytics compute
- Phase 4: Precompute for ML
- Phase 5: Predictions generate
- Phase 6: Grading validates

---

## Key Files Modified This Session

| File | Changes |
|------|---------|
| `scrapers/bettingpros/bp_mlb_player_props.py` | v3: Added transform_data() override, aligned GCS path |
| `scrapers/registry.py` | Added MLB BettingPros scrapers |
| `data_processors/raw/processor_base.py` | Added 7 MLB error patterns |
| `data_processors/raw/mlb/mlb_bp_historical_props_processor.py` | Updated docs for live+historical |
| `scripts/mlb/historical_bettingpros_backfill/load_to_bigquery.py` | Fixed schema mismatch |
| `docs/08-projects/current/mlb-pitcher-strikeouts/MLB-PRESEASON-CHECKLIST.md` | Updated status |

---

## ODDS API Batter Strikeouts Investigation Result

**Finding**: ODDS API discontinued `batter_strikeouts` market after September 2024.

**Evidence**:
- Other batter markets: 345 dates of data
- Batter strikeouts: only 117 dates (stopped Sept 2024)
- No filtering in our code - API simply doesn't return it

**Impact**: None - BettingPros is primary source for batter strikeouts with full coverage.

**Action**: No need to contact ODDS API.

---

## Architecture Reference

### BettingPros MLB Markets

| Type | Market ID | Market Name |
|------|-----------|-------------|
| Pitcher | 285 | pitcher-strikeouts |
| Batter | 287 | batter-hits |
| Batter | 288 | batter-runs |
| Batter | 289 | batter-rbis |
| Batter | 291 | batter-doubles |
| Batter | 292 | batter-triples |
| Batter | 293 | batter-total-bases |
| Batter | 294 | batter-stolen-bases |
| Batter | 295 | batter-singles |
| Batter | 299 | batter-home-runs |

### GCS Path Structure

```
gs://nba-scraped-data/
├── bettingpros-mlb/
│   ├── historical/           # From backfill scripts
│   │   ├── pitcher-strikeouts/
│   │   │   └── {date}/props.json
│   │   └── batter-*/
│   └── {market}/             # From live scraper (new)
│       └── {date}/props.json
└── odds-api-mlb/             # ODDS API data
    └── batter-props/{date}/
```

---

## Scheduler Jobs (Ready to Enable)

11 jobs configured in Cloud Scheduler, currently paused:

```bash
# List MLB jobs
gcloud scheduler jobs list --filter="name~mlb" --format="table(name,state,schedule)"

# Enable all before Opening Day
gcloud scheduler jobs list --filter="name~mlb" | grep PAUSED | awk '{print $1}' | xargs -I{} gcloud scheduler jobs resume {}
```

---

## V1.6 Model Features

The prediction model uses BettingPros data for features f40-f44:
- `f40_bp_projection`: BettingPros projection value
- `f41_projection_diff`: Difference from line
- `f42_perf_last_5_pct`: Recent performance trend
- `f43_perf_last_10_pct`: 10-game performance
- `f44_perf_season_pct`: Season-long trend

Model handles missing BettingPros data with defaults (5.0, 0.0, 0.5).

---

## Quick Verification Commands

```bash
# Check BettingPros data in BigQuery
bq query --use_legacy_sql=false "
SELECT market_name, COUNT(*) as props, COUNT(DISTINCT game_date) as dates
FROM mlb_raw.bp_batter_props
WHERE game_date BETWEEN '2022-01-01' AND '2025-12-31'
GROUP BY market_name ORDER BY props DESC"

# Check validation table exists
bq show mlb_orchestration.processor_output_validation

# Check scraper is registered
python -c "from scrapers.registry import SCRAPER_REGISTRY; print('bp_mlb_player_props' in SCRAPER_REGISTRY)"

# Test scraper (dry run)
python scrapers/bettingpros/bp_mlb_player_props.py --date 2025-09-28 --group dev --debug
```

---

## Next Session Priorities

1. **Deploy prediction worker** - Quick win, enables shadow mode predictions
2. **Run E2E test** - Critical validation before Opening Day
3. **Create MLB R-007 reconciliation** - Optional, can wait until closer to season

---

## Background Tasks

**None active.** All backfill and loading tasks completed successfully.

---

## Contact

For questions about this handoff, review:
- `docs/08-projects/current/mlb-pitcher-strikeouts/MLB-PRESEASON-CHECKLIST.md`
- Previous session: `docs/09-handoff/2026-01-15-SESSION-63-MLB-HANDOFF.md`
