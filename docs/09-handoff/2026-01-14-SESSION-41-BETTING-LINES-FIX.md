# Session 41: Betting Lines Fix - Complete Handoff

**Date:** 2026-01-14
**Session:** 41
**Status:** Complete - Core Fix Implemented, Backfill Done

---

## Executive Summary

This session identified and fixed the root cause of betting lines not being joined to predictions. The issue affected predictions since Jan 1, 2026, causing NULL `current_points_line` values and preventing hit rate calculation.

**Key Accomplishments:**
1. Root cause identified: Timing issue + worker bug
2. Created `PredictionLineEnrichmentProcessor` to backfill lines
3. Enriched 1,935 predictions (Jan 1-14)
4. All dates now have hit rates calculable
5. Fixed worker.py to use estimated lines
6. Added coordinator deduplication

---

## Root Cause Analysis

### The Problem
Predictions had `current_points_line = NULL` even though betting props existed in raw data.

### Root Causes Identified

| Issue | Description | Impact |
|-------|-------------|--------|
| **Timing Gap** | Predictions generated ~22:32 UTC (night before), props scraped ~18:05 UTC (game day) | 20+ hour gap where no props exist |
| **Phase 3 Timing** | Phase 3 runs 17:45 UTC, props scraped 18:05 UTC | Phase 3 misses same-day props |
| **Worker Bug** | When `has_prop_line=False`, worker set `current_points_line=None` | Lost estimated lines |
| **Phase 3 Duplicates** | Phase 3 creates NEW rows on re-run instead of UPDATE | Multiple rows per player |
| **No Deduplication** | Coordinator didn't pick latest Phase 3 record | Could process stale data |

### Data Flow (Before Fix)
```
Props scraped: game day 18:05 UTC
Phase 3 runs: game day 17:45 UTC (BEFORE props!)
Predictions run: night before 22:32 UTC
Result: No props exist at prediction time → NULL lines
```

---

## Solution Implemented

### 1. Prediction Line Enrichment Processor (NEW)

**Location:** `data_processors/enrichment/prediction_line_enrichment/`

A post-processing enrichment step that:
- Queries predictions with NULL `current_points_line`
- Joins with `odds_api_player_points_props` to get actual lines
- Updates predictions via BigQuery MERGE
- Fixes `recommendation` from NO_LINE to OVER/UNDER

**Usage:**
```bash
# Single date
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --date 2026-01-14

# Date range
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --start-date 2026-01-01 --end-date 2026-01-14

# Dry run
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --date 2026-01-14 --dry-run

# Fix recommendations only (already enriched)
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --date 2026-01-14 --fix-recommendations-only
```

### 2. Worker Bug Fix (v3.5)

**File:** `predictions/worker/worker.py` (lines 1117-1143)

**Before:**
```python
if has_prop_line:
    current_points_line = round(actual_prop_line or line_value, 1)
else:
    recommendation = 'NO_LINE'
    current_points_line = None  # BUG: Lost estimated lines
```

**After:**
```python
if has_prop_line:
    current_points_line = round(actual_prop_line or line_value, 1)
elif line_value is not None:
    # Use estimated line, recalculate recommendation
    current_points_line = round(line_value, 1)
    recommendation = 'OVER' if predicted > current_points_line else 'UNDER'
else:
    recommendation = 'NO_LINE'
    current_points_line = None
```

### 3. Coordinator Deduplication (v3.5)

**File:** `predictions/coordinator/player_loader.py` (line 294)

Added `QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY created_at DESC) = 1` to pick latest Phase 3 record per player.

---

## Backfill Results

### Predictions Enriched
| Date Range | Enriched | Coverage Before | Coverage After |
|------------|----------|-----------------|----------------|
| Jan 1 | 210 | 0% | 45% |
| Jan 4 | 329 | 43% | 79% |
| Jan 5 | 267 | 22% | 69% |
| Jan 6 | 303 | 0% | 69% |
| Jan 10 | 155 | 80% | 97% |
| Jan 12-14 | 591 | 0% | 75-87% |
| **Total** | **1,935** | - | - |

### Hit Rates Now Available
| Date | Graded | With Line | Hit Rate |
|------|--------|-----------|----------|
| Jan 1 | 420 | 195 | 74.4% |
| Jan 2 | 988 | 692 | 34.2% |
| Jan 6 | 357 | 302 | 58.9% |
| Jan 9 | 995 | 995 | 83.2% |
| Jan 13 | 271 | 252 | 46.0% |

---

## Files Changed

| File | Change |
|------|--------|
| `data_processors/enrichment/__init__.py` | NEW - Enrichment module |
| `data_processors/enrichment/prediction_line_enrichment/__init__.py` | NEW |
| `data_processors/enrichment/prediction_line_enrichment/prediction_line_enrichment_processor.py` | NEW - Main processor |
| `predictions/worker/worker.py` | FIX - Use estimated lines when no prop |
| `predictions/coordinator/player_loader.py` | FIX - Add Phase 3 deduplication |

---

## Remaining Work

### HIGH Priority
- [ ] **Schedule enrichment processor** - Run daily ~19:30 UTC after props scraping

### MEDIUM Priority
- [ ] **Fix Phase 3 UPSERT** - Use MERGE instead of INSERT to prevent duplicates
- [ ] **Adjust Phase 3 timing** - Move from 17:45 to 19:00 UTC (after props)

### LOW Priority
- [ ] Add monitoring alert for >20% NULL lines
- [ ] Automate grading re-run after enrichment
- [ ] Add unit tests for enrichment processor
- [ ] Create Cloud Monitoring auth error alert (from Session 40)

### Investigation
- [ ] Jan 9 hit rate 83.2% vs Jan 11 hit rate 31.4% - variance analysis

---

## Verification Commands

```bash
# Check line coverage by date
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as total,
       COUNTIF(current_points_line IS NOT NULL) as with_line,
       ROUND(COUNTIF(current_points_line IS NOT NULL) / COUNT(*) * 100, 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= "2026-01-01"
GROUP BY game_date ORDER BY game_date'

# Check hit rates
bq query --use_legacy_sql=false '
SELECT game_date,
       COUNTIF(line_value IS NOT NULL) as with_line,
       ROUND(COUNTIF(prediction_correct = TRUE) / NULLIF(COUNTIF(line_value IS NOT NULL), 0) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= "2026-01-01"
GROUP BY game_date ORDER BY game_date'

# Run enrichment for today
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor
```

---

## Architecture Diagram

```
CURRENT FLOW (with enrichment fix):

Props scraped ─────────────────────────────────────┐
  18:05 UTC                                        │
                                                   │
Phase 3 runs ──────────────────────────────────────┤
  17:45 UTC                                        │
  (creates players, has_prop_line=FALSE)           │
                                                   │
Predictions run ───────────────────────────────────┤
  22:32 UTC (night before)                         │
  (current_points_line=NULL initially)             │
                                                   ▼
                                         ┌─────────────────────┐
                                         │ ENRICHMENT PROCESSOR │
                                         │ (NEW - 19:30 UTC)    │
                                         │                      │
                                         │ 1. Find NULL lines   │
                                         │ 2. Join with props   │
                                         │ 3. UPDATE predictions │
                                         │ 4. Fix recommendations│
                                         └─────────────────────┘
                                                   │
                                                   ▼
                                         Predictions now have lines
                                         Hit rate can be calculated
```

---

## Context for New Session

The betting lines issue is now **mostly resolved**:
1. Enrichment processor created and tested
2. Historical data backfilled (Jan 1-14)
3. Worker and coordinator bugs fixed

**Remaining:** Schedule enrichment processor in Cloud Scheduler to run daily after props scraping (~19:30 UTC).
