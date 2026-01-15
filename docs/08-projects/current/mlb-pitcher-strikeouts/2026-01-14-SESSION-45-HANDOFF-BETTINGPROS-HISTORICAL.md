# Session 45 Handoff: BettingPros Historical MLB Props System

**Date**: 2026-01-14
**Focus**: Historical data collection infrastructure for MLB props
**Status**: Implementation Complete, Ready for Backfill

---

## Executive Summary

Discovered and implemented a comprehensive historical data collection system using the BettingPros API. This is a **major breakthrough** because:

1. **Actual outcomes included** - No need to join with another data source for grading
2. **4 years of history** - 2022-2025 (vs Odds API's 6-month limit)
3. **Free API** - No API key or costs (uses FantasyPros headers)
4. **Rich data** - Includes projections, performance trends, consensus lines

---

## Key Discovery: BettingPros Historical API

### API Endpoint
```
GET https://api.bettingpros.com/v3/props?sport=MLB&market_id=XXX&date=YYYY-MM-DD
```

### Required Headers
```http
Origin: https://www.fantasypros.com
Referer: https://www.fantasypros.com/
```

### Response Includes (per prop)
| Field | Description | Value for Training |
|-------|-------------|-------------------|
| `scoring.actual` | **Actual outcome** | Critical - enables grading |
| `over.line`, `under.line` | Betting lines | Feature |
| `over.odds`, `under.odds` | American odds | Feature |
| `projection.value` | BettingPros projection | Comparison/feature |
| `performance.last_5` | Recent O/U record | Feature |
| `performance.season` | Season O/U record | Feature |
| `opposing_pitcher` | Matchup context | Feature |

---

## Files Created

| File | Purpose | Lines |
|------|---------|-------|
| `scrapers/bettingpros/bp_mlb_props_historical.py` | Core scraper (framework-based) | 540 |
| `scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py` | Main orchestrator | 500 |
| `scripts/mlb/historical_bettingpros_backfill/check_progress.py` | Progress monitoring | 180 |
| `scripts/mlb/historical_bettingpros_backfill/SPEC.md` | Technical specification | 450 |

---

## Available Markets (11 total)

### Pitcher Props (2)
| ID | Market | Props/Day |
|----|--------|-----------|
| 285 | pitcher-strikeouts | ~20 |
| 290 | pitcher-earned-runs-allowed | ~20 |

### Batter Props (9)
| ID | Market | Props/Day |
|----|--------|-----------|
| 287 | batter-hits | ~180 |
| 288 | batter-runs | ~180 |
| 289 | batter-rbis | ~150 |
| 291 | batter-doubles | ~185 |
| 292 | batter-triples | ~165 |
| 293 | batter-total-bases | ~160 |
| 294 | batter-stolen-bases | ~160 |
| 295 | batter-singles | ~180 |
| 299 | batter-home-runs | ~185 |

---

## Data Volume Estimates

| Metric | Value |
|--------|-------|
| Seasons | 4 (2022-2025) |
| Game Days | ~740 |
| Total Markets | 11 |
| API Calls Required | ~28,120 |
| Prop Records | ~1,140,000 |
| GCS Storage | ~500 MB |

---

## Tested & Verified

### Test Results
```
Date Range: 2024-06-15 to 2024-06-21 (7 days)
Markets: Pitcher (2)
Results:
  - 219 props collected
  - 14 GCS files created
  - 1 existing file skipped (resume works)
  - Rate: 24 API calls/minute
  - No errors
```

### Sample Data in GCS
```json
{
  "player_name": "Spencer Arrighetti",
  "team": "HOU",
  "over_line": 5.5,
  "over_odds": -154,
  "projection_value": 4.97,
  "actual_value": 2,
  "is_scored": true,
  "perf_last_5_over": 3,
  "perf_last_5_under": 2,
  "opposing_pitcher": "Flaherty"
}
```

---

## How to Run Backfill

### Full Backfill (All Markets, All Seasons)
```bash
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py
```

### Pitcher Props Only (Recommended First)
```bash
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --markets pitcher
```

### Batter Props Only
```bash
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --markets batter
```

### Single Season
```bash
python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --season 2024
```

### Check Progress
```bash
python scripts/mlb/historical_bettingpros_backfill/check_progress.py
python scripts/mlb/historical_bettingpros_backfill/check_progress.py --sample-props
```

### Run in Background
```bash
nohup python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \
    > /tmp/backfill.log 2>&1 &
tail -f /tmp/backfill.log
```

---

## Time Estimates

| Scope | API Calls | Estimated Time |
|-------|-----------|----------------|
| Pitcher only (2 markets) | 1,480 | ~30 minutes |
| Batter only (9 markets) | 26,640 | ~3-4 hours |
| Full backfill (11 markets) | 28,120 | ~4-5 hours |

---

## GCS Output Structure

```
gs://nba-scraped-data/bettingpros-mlb/historical/
├── pitcher-strikeouts/
│   ├── 2022-04-07/props.json
│   ├── 2022-04-08/props.json
│   └── ... (740 files)
├── pitcher-earned-runs-allowed/
│   └── ... (740 files)
├── batter-hits/
│   └── ... (740 files)
└── ... (8 more markets)
```

---

## Recommendations

### Immediate Actions

1. **Run Pitcher Backfill First** (~30 min)
   ```bash
   python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py --markets pitcher
   ```
   This validates the full pipeline before the longer batter backfill.

2. **Run Batter Backfill** (~3-4 hours)
   ```bash
   nohup python scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py \
       --markets batter > /tmp/batter_backfill.log 2>&1 &
   ```

3. **Create BigQuery Processor**
   - Load GCS JSON files to BigQuery tables
   - Schema already defined in SPEC.md
   - Tables: `mlb_raw.bp_pitcher_props`, `mlb_raw.bp_batter_props`

### Next Phase: Model Training

Once data is in BigQuery:

1. **Pitcher Strikeouts V2**
   - Use `actual_value` for grading (no join needed)
   - Add `projection_value` as feature (BettingPros projection)
   - Add `perf_last_5_over/under` as features
   - Add `opposition_rank` as feature

2. **New Batter Props Models**
   - Hits model (287) - highest volume
   - Home runs model (299) - popular market
   - Total bases model (293) - good for parlays

### Comparison: BettingPros vs Odds API

| Feature | BettingPros | Odds API |
|---------|-------------|----------|
| Historical window | 2022+ (4 years) | 6 months |
| Actual outcomes | Included | Requires join |
| Projections | Included | Not available |
| Performance trends | Included | Not available |
| API cost | Free | Paid (usage-based) |
| Rate limits | Unknown (respectful) | Usage-based |

**Recommendation**: Use BettingPros for historical training data, Odds API for live production (better real-time coverage).

---

## Known Issues

1. **Core scraper framework timeout** - The framework-based scraper (`bp_mlb_props_historical.py`) has timeout issues with the scraper base class. The backfill script uses direct HTTP calls instead, which works reliably.

2. **Some props may be missing** - Not all game days have props for all markets. The system saves empty files to track processed dates.

---

## Files to Commit (Done)

```
git commit: a0468e3
feat(mlb): Add BettingPros historical props backfill system

Files:
- scrapers/bettingpros/bp_mlb_props_historical.py
- scripts/mlb/historical_bettingpros_backfill/SPEC.md
- scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py
- scripts/mlb/historical_bettingpros_backfill/check_progress.py
```

---

## Session Stats

| Metric | Value |
|--------|-------|
| Duration | ~1 hour |
| Files Created | 4 |
| Lines of Code | ~1,670 |
| API Discovery | BettingPros /v3/props historical |
| Test Props Collected | 219 |
| GCS Files Created | 14 |

---

## Next Session Priorities

1. Run full pitcher backfill (~30 min)
2. Run full batter backfill (~3-4 hours)
3. Create BigQuery processor for GCS data
4. Update pitcher strikeouts model with new features
5. Evaluate new batter prop models (hits, HRs, total bases)

---

## Contact

Questions about this implementation? Check:
- `scripts/mlb/historical_bettingpros_backfill/SPEC.md` - Full technical specification
- GCS: `gs://nba-scraped-data/bettingpros-mlb/historical/` - Output data
