# Historical Line Source Handoff

**Date:** 2026-01-23
**Session Focus:** Understanding and improving betting line sources for predictions
**Context Level:** Low - Full context needed for next session

---

## Executive Summary

This session investigated how betting lines are sourced for predictions and implemented improvements. Key finding: **The system DOES have real betting lines for historical data** - they come from BettingPros, not Odds API (which only started May 2023).

### What We Learned

1. **Odds API** started collecting prop data on **May 3, 2023** - no data before that
2. **BettingPros** has full data from **October 19, 2021** - the entire dataset
3. Historical predictions were patched with BettingPros data (marked as `VEGAS_BACKFILL`)
4. The system IS working correctly - BettingPros is the only source for pre-May 2023

### Line Source Breakdown (2024-25 Season)

| Line Source | Count | % | Description |
|-------------|-------|---|-------------|
| VEGAS_BACKFILL | 57,041 | 53% | Real BettingPros lines (patched) |
| NO_VEGAS_DATA | 25,423 | 23% | No line available anywhere |
| ACTUAL_PROP | 17,460 | 16% | Real live lines (Odds API or BP) |
| ESTIMATED_AVG | 8,348 | 8% | **FAKE - needs elimination** |

---

## Data Source Timeline

```
Oct 2021 ─────────────────────── May 2023 ─────────────────────── Jan 2026
    │                                 │                                │
    │  BettingPros ONLY               │  Odds API + BettingPros        │
    │  (2021-22, 2022-23 seasons)     │  (2023-24, 2024-25, 2025-26)   │
    │                                 │                                │
    └─────────────────────────────────┴────────────────────────────────┘
```

### Odds API Monthly Coverage

| Period | Dates | Notes |
|--------|-------|-------|
| May 2023 | 22 | First data (playoffs) |
| Jun 2023 | 5 | Finals |
| Oct-Dec 2023 | 63 | Good coverage |
| 2024 | 181 | Full season |
| 2025 | 176 | Full season |
| 2026 (Jan) | 20 | Current |

---

## Current Fallback System (IMPLEMENTED)

The sportsbook-priority fallback was implemented this session:

```
1. Odds API DraftKings
2. BettingPros DraftKings (if OddsAPI DK unavailable)
3. Odds API FanDuel
4. BettingPros FanDuel (if OddsAPI FD unavailable)
5. Odds API secondary books (BetMGM, PointsBet, Caesars)
6. BettingPros secondary books
7. BettingPros ANY book (last resort)
```

**File:** `predictions/coordinator/player_loader.py`
**Version:** v3.9

This prioritizes **sportsbook quality** (DraftKings > FanDuel > others) over **data source** (Odds API > BettingPros).

---

## User Requirement: No Fake Lines

The user explicitly stated:
> "I really don't want estimates in the system. We can still make a prediction, but I don't want fake lines."

### Current ESTIMATED_AVG Usage

| Season | ESTIMATED_AVG Count | % |
|--------|---------------------|---|
| 2021-22 | 15,635 | 13% |
| 2022-23 | 11,954 | 11% |
| 2023-24 | 11,172 | 10% |
| 2024-25 | 8,348 | 8% |
| 2025-26 | 58,329 | 60% |

### Action Required

1. **Modify coordinator** to NOT generate ESTIMATED lines
2. **Allow predictions without lines** - still predict points, just no OVER/UNDER recommendation
3. **Existing ESTIMATED predictions** should be:
   - Either: Re-run with new fallback (try BettingPros first)
   - Or: Set `has_prop_line = FALSE`, `recommendation = 'NO_LINE'`

---

## Files Changed This Session

### Code Changes

1. **predictions/coordinator/player_loader.py**
   - `_query_actual_betting_line()` - Rewritten with sportsbook-priority fallback
   - `_query_odds_api_betting_line_for_book()` - New: Query specific sportsbook
   - `_query_bettingpros_betting_line_for_book()` - New: Query specific sportsbook
   - `_track_line_source()` - Enhanced tracking by source/book
   - `get_line_source_stats()` - Enhanced reporting with health alerts

### Documentation Created

```
docs/08-projects/current/historical-data-validation/
├── README.md                 # Project overview
├── VALIDATION-FINDINGS.md    # Multi-season audit
├── RESILIENCE-IMPROVEMENTS.md # 10+ improvement ideas
├── LINE-SOURCE-IMPROVEMENT.md # Implementation details
├── BACKFILL-STRATEGY.md      # Comprehensive backfill plan
└── BACKFILL-TRACKER.md       # Status tracker
```

---

## Commits Made

1. **729c489a** - Historical Odds API backfill documentation
2. **8fcd8765** - Validation findings report
3. **b0854258** - Historical data validation project
4. **755401ea** - Line source improvement proposal
5. **3e2cd667** - Sportsbook-priority fallback implementation
6. **3b082cdf** - Documentation updates

---

## Outstanding Tasks

### P0: Remove Estimated Lines
- [ ] Modify `_get_betting_line_info()` to NOT fall back to estimated
- [ ] Return `has_prop_line = FALSE` when no real line found
- [ ] Set `recommendation = 'NO_LINE'` for predictions without lines
- [ ] Deploy and test

### P0: Reliable Grading with Real Lines Only
- [ ] **Only grade predictions that have real betting lines** (`has_prop_line = TRUE`)
- [ ] Exclude ESTIMATED lines from grading (they contaminate accuracy metrics)
- [ ] Verify grading queries filter on `has_prop_line = TRUE AND line_source != 'ESTIMATED_AVG'`
- [ ] Update grading processor if needed to enforce this

### P1: Fix Existing ESTIMATED Predictions
- [ ] Query predictions with `line_source = 'ESTIMATED_AVG'`
- [ ] Re-run with new fallback OR mark as `NO_LINE`
- [ ] Re-grade affected predictions

### P1: Deploy Code Changes
- [ ] Push to Cloud Run
- [ ] Test with a few dates
- [ ] Monitor line source distribution

### P1: Verify Performance After Corrections
- [ ] Review performance analysis guide: `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md`
- [ ] Re-run performance queries after backfilling with real lines
- [ ] Verify CatBoost V8 performance metrics are accurate
- [ ] Check that win rates and MAE are based on real lines only
- [ ] Compare before/after metrics to validate corrections

### P2: Season-Start Bootstrap Gap
- [ ] Oct 22 - Nov 4, 2024 have no predictions (14 dates)
- [ ] Same pattern in all seasons (~14 days missing)
- [ ] Need to investigate root cause

---

## Key Queries for Next Session

### Check Line Source Distribution
```sql
SELECT
  line_source,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE AND game_date >= '2025-10-22'
GROUP BY 1
ORDER BY 2 DESC;
```

### Find ESTIMATED Predictions to Fix
```sql
SELECT game_date, COUNT(*) as estimated_count
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE AND line_source = 'ESTIMATED_AVG'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 30;
```

### Verify BettingPros Coverage
```sql
SELECT
  FORMAT_DATE('%Y', game_date) as year,
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as rows
FROM `nba_raw.bettingpros_player_points_props`
WHERE game_date >= '2021-01-01'
GROUP BY 1
ORDER BY 1;
```

---

## Important Context

### Why BettingPros, Not Odds API, for History?

1. **Odds API Historical Endpoint** - Requires specific timestamp, costs API calls
2. **BettingPros** - We scrape regularly, have full historical data
3. **Data Quality** - Both have DraftKings/FanDuel lines, similar accuracy

### What is VEGAS_BACKFILL?

A patch was run (see `bin/patches/patch_fake_lines.sql`) that:
1. Found predictions with fake `line=20.0`
2. Looked up real lines from BettingPros
3. Updated predictions with real lines, marked as `VEGAS_BACKFILL`
4. Predictions without matches were marked `NO_VEGAS_DATA`

### What Should Happen Going Forward?

1. **New predictions** - Use Odds API first (DK→FD), fall back to BettingPros
2. **No estimated lines** - If no real line exists, predict points but no recommendation
3. **Existing ESTIMATED** - Should be re-run or marked as NO_LINE

---

## Project Documentation Location

All findings and plans are documented in:
```
docs/08-projects/current/historical-data-validation/
```

This is the authoritative location for:
- Validation findings across all seasons
- Line source improvement details
- Backfill strategy and tracker
- Resilience improvement ideas

---

## Summary for Next Session

1. **Code is ready** - Sportsbook-priority fallback implemented
2. **Need to deploy** - Push to Cloud Run
3. **Need to eliminate ESTIMATED** - Modify code to not use estimates
4. **Need to fix existing ESTIMATED** - Re-run or mark as NO_LINE
5. **Documentation is updated** - See docs/08-projects/current/historical-data-validation/

---

## Performance Verification (CRITICAL)

After backfilling and correcting line sources, the next session MUST verify that performance metrics are accurate.

### Performance Analysis Guide Location

```
docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md
```

### Key Metrics to Verify (CatBoost V8)

| Metric | Expected Range | Query Filter |
|--------|----------------|--------------|
| MAE | 4.5-5.0 | `has_prop_line = TRUE` |
| Win Rate | 50-55% | `recommendation IN ('OVER', 'UNDER')` |
| Picks/Day | 30-60 | `has_prop_line = TRUE` |

### Verification Queries

**Check grading is using real lines only:**
```sql
SELECT
  line_source,
  COUNT(*) as graded_count,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01' AND system_id = 'catboost_v8'
GROUP BY 1
ORDER BY 2 DESC;
```

**Expected:** ESTIMATED_AVG should have 0 graded predictions (or be excluded).

**Verify accurate performance after corrections:**
```sql
SELECT
  COUNT(*) as total_picks,
  COUNTIF(prediction_correct = TRUE) as wins,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= '2025-10-01'
  AND system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
  AND line_source NOT IN ('ESTIMATED_AVG', 'NO_VEGAS_DATA')  -- REAL LINES ONLY
```

### Why This Matters

The current performance metrics may be contaminated by:
1. **ESTIMATED lines** (8-13% of predictions) - fake lines skew accuracy
2. **NO_VEGAS_DATA** lines - predictions without real lines shouldn't be graded
3. **Default line=20** contamination (historical issue, mostly patched)

After corrections, we need to re-verify that:
- CatBoost V8 is still performing at ~50% win rate
- MAE is in the 4.5-5.0 range
- High confidence tiers have higher win rates (calibration)

---

## Context for Next Session

### Documents to Review (Priority Order)

**P0 - Must Read:**
1. `docs/08-projects/current/historical-data-validation/README.md` - Project overview and status
2. `docs/08-projects/current/historical-data-validation/BACKFILL-STRATEGY.md` - Backfill plan
3. `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md` - How to verify performance

**P1 - Should Read:**
4. `docs/08-projects/current/historical-data-validation/LINE-SOURCE-IMPROVEMENT.md` - Implementation details
5. `docs/08-projects/current/historical-data-validation/RESILIENCE-IMPROVEMENTS.md` - Future improvements

**P2 - Reference as Needed:**
6. `docs/08-projects/current/historical-data-validation/VALIDATION-FINDINGS.md` - Full audit results
7. `docs/06-reference/scrapers.md` - Historical Odds API backfill section

### Parts of System to Study (Use Agents)

**Recommended Agent Tasks:**

1. **Understand the grading system:**
   ```
   Explore the grading system in data_processors/grading/. How does prediction_accuracy_processor.py
   grade predictions? What filters does it apply? Does it exclude estimated lines?
   ```

2. **Understand how line_source is set:**
   ```
   Explore predictions/coordinator/player_loader.py. How does _get_betting_line_info() determine
   line_source? Where does ESTIMATED_AVG come from? How can we prevent estimated lines?
   ```

3. **Understand the prediction output schema:**
   ```
   What fields are in player_prop_predictions table? Check schemas/bigquery/nba_predictions/
   and understand what line_source, has_prop_line, and line_source_api mean.
   ```

4. **Understand BettingPros data structure:**
   ```
   Explore the BettingPros scraper and processor. Where does the data come from? How is it
   stored? What sportsbooks are available? Check scrapers/bettingpros/ and data_processors/raw/
   ```

### Key Code Files

| File | Purpose | Review When |
|------|---------|-------------|
| `predictions/coordinator/player_loader.py` | Line source fallback (MODIFIED) | Deploying changes |
| `predictions/coordinator/coordinator.py` | Prediction orchestration | Understanding flow |
| `data_processors/grading/prediction_accuracy/` | Grading logic | Fixing grading |
| `bin/patches/patch_fake_lines.sql` | Historical patch | Understanding VEGAS_BACKFILL |

### Quick Start Commands

```bash
# Check current line source distribution
bq query --use_legacy_sql=false "
SELECT line_source, COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE is_active = TRUE AND game_date >= '2025-10-22'
GROUP BY 1 ORDER BY 2 DESC"

# Check grading health
bq query --use_legacy_sql=false "
SELECT
  line_source,
  COUNT(*) as graded,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2025-10-01' AND system_id = 'catboost_v8'
GROUP BY 1 ORDER BY 2 DESC"

# Deploy code to Cloud Run
gcloud run deploy prediction-coordinator \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform
```

---

**Start command for next session:**
```
Read docs/09-handoff/2026-01-23-HISTORICAL-LINE-SOURCE-HANDOFF.md for full context. Then read docs/08-projects/current/historical-data-validation/README.md and docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md.
```
