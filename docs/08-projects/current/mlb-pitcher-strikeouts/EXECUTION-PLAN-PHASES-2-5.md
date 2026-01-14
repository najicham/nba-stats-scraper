# MLB Historical Backfill Execution Plan: Phases 2-5

**Created**: 2026-01-13 21:15
**Status**: Phase 1 (Backfill) RUNNING, Phases 2-5 PREPARED

---

## Overview

This document outlines the complete execution plan for measuring the TRUE hit rate
of our MLB pitcher strikeout prediction model using real historical betting lines.

### Pipeline Flow

```
Phase 1: GCS Scraping        ─── RUNNING (backfill_historical_betting_lines.py)
    ↓
    352 dates → ~5,000 events → GCS JSON files
    ↓
Phase 2: GCS → BigQuery      ─── PREPARED (process_historical_to_bigquery.py)
    ↓
    ~5,000 JSON files → mlb_raw.oddsa_pitcher_props
    ↓
Phase 3: Match Lines         ─── PREPARED (match_lines_to_predictions.py)
    ↓
    oddsa_pitcher_props → pitcher_strikeouts.strikeouts_line
    ↓
Phase 4: Grade Predictions   ─── PREPARED (grade_historical_predictions.py)
    ↓
    actual_strikeouts vs line → is_correct (TRUE/FALSE)
    ↓
Phase 5: Calculate Hit Rate  ─── PREPARED (calculate_hit_rate.py)
    ↓
    ★ TRUE HIT RATE REVEALED ★
```

---

## Current Status

### Phase 1: Backfill (RUNNING)

```bash
# Monitor progress
tail -f logs/mlb_historical_backfill_*.log

# Check current day
grep "Processing" logs/mlb_historical_backfill_*.log | tail -1

# Count GCS files
gsutil ls "gs://nba-scraped-data/mlb-odds-api/pitcher-props-history/**/*.json" | wc -l
```

**Progress**:
- Started: 2026-01-13 20:59
- Current: Day 7/352 (as of 21:15)
- Files created: 131
- Rate: ~3 min/day
- **Revised ETA: 17-18 hours** (completing ~14:00 tomorrow)

---

## Execution Instructions

### Phase 2: Process GCS to BigQuery

**When**: After Phase 1 completes (check for "BACKFILL COMPLETE" in logs)

```bash
# Dry-run first
python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py --dry-run

# Execute
python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py

# Expected runtime: 10-20 minutes
# Expected rows: ~15,000-20,000 (multiple bookmakers per event)
```

**What it does**:
1. Lists all dates in GCS pitcher-props-history/
2. For each date, processes all JSON files
3. Runs MlbPitcherPropsProcessor on each file
4. Appends to `mlb_raw.oddsa_pitcher_props`

**Verification**:
```sql
SELECT
    COUNT(*) as total_rows,
    COUNT(DISTINCT game_date) as dates,
    COUNT(DISTINCT player_lookup) as pitchers
FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
WHERE source_file_path LIKE '%pitcher-props-history%';
```

---

### Phase 3: Match Lines to Predictions

**When**: After Phase 2 completes

```bash
# Dry-run first
python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py --dry-run

# Execute
python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py

# Expected runtime: 1-2 minutes
# Expected updates: 5,000-6,500 predictions
```

**What it does**:
1. Creates consensus line (median across bookmakers) per pitcher/date
2. Updates `pitcher_strikeouts.strikeouts_line` where NULL
3. Sets `line_source = 'historical_odds_api'`

**Verification**:
```sql
SELECT
    line_source,
    COUNT(*) as predictions,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date BETWEEN '2024-04-09' AND '2025-09-28'
GROUP BY line_source;
```

---

### Phase 4: Grade Predictions

**When**: After Phase 3 completes

```bash
# Dry-run first
python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py --dry-run

# Execute
python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py

# Expected runtime: 2-3 minutes
# Expected graded: 5,000-6,500 predictions
```

**What it does**:
1. Joins predictions with actual pitcher stats
2. Compares: actual_strikeouts vs strikeouts_line
3. Sets `is_correct = TRUE/FALSE` based on recommendation
4. Handles pushes (actual == line) separately

**Grading Logic**:
- OVER recommendation + actual > line → is_correct = TRUE
- OVER recommendation + actual < line → is_correct = FALSE
- UNDER recommendation + actual < line → is_correct = TRUE
- UNDER recommendation + actual > line → is_correct = FALSE
- actual == line → is_correct = NULL (push)

---

### Phase 5: Calculate Hit Rate

**When**: After Phase 4 completes

```bash
# Full report
python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py

# JSON output
python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py --json > hit_rate_results.json
```

**What it calculates**:
- Overall hit rate (wins / total bets)
- Hit rate by recommendation (OVER vs UNDER)
- Hit rate by edge bucket (0.5-1.0, 1.0-1.5, etc.)
- Hit rate by season (2024 vs 2025)
- Hit rate by month

---

## Expected Results

Based on synthetic analysis (78% using rolling averages), real results should be:

| Metric | Synthetic | Expected Real | Threshold |
|--------|-----------|---------------|-----------|
| Total Predictions | 8,130 | 8,130 | - |
| With Lines | 5,327 | 5,700-6,500 | - |
| Hit Rate | 78.04% | 60-70% | >54% profitable |
| Edge vs Breakeven | +24% | +6-16% | >0% profitable |

### Interpretation Guide

| Hit Rate | Assessment | Action |
|----------|------------|--------|
| >70% | ★★★ EXCEPTIONAL | Deploy immediately |
| 60-70% | ★★☆ STRONG | Deploy with monitoring |
| 54-60% | ★☆☆ MARGINAL | Tune before deployment |
| <54% | ☆☆☆ NOT PROFITABLE | Model needs rework |

---

## Risk Analysis

### Known Risks

1. **Coverage Gap** (~20-30%)
   - Some predictions won't have historical betting lines
   - API may not have data for all games/times
   - Mitigation: Already factored into estimates

2. **Name Matching**
   - Player lookup normalization must match between predictions and odds
   - Mitigation: Both use same `normalize_name_for_lookup()` function

3. **Bookmaker Line Variance**
   - Different bookmakers have different lines
   - Mitigation: Using median consensus line

4. **Snapshot Timing**
   - Historical snapshot at 18:00 UTC may not capture late line moves
   - Impact: Minor - lines usually stable by game time

### Contingency Plans

**If backfill interrupted**:
```bash
# Resume with skip-to-date
python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py \
    --skip-to-date YYYY-MM-DD
```

**If processing fails on specific file**:
```bash
# Skip and continue
python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py \
    --skip-to-date YYYY-MM-DD
```

---

## Scripts Reference

| Script | Purpose | Phase |
|--------|---------|-------|
| `backfill_historical_betting_lines.py` | Scrape historical odds to GCS | 1 |
| `process_historical_to_bigquery.py` | Load GCS to BigQuery | 2 |
| `match_lines_to_predictions.py` | Link odds to predictions | 3 |
| `grade_historical_predictions.py` | Grade win/loss | 4 |
| `calculate_hit_rate.py` | Calculate final hit rate | 5 |

All scripts located in: `scripts/mlb/historical_odds_backfill/`

---

## Ultrathink Analysis

### Why This Matters

The synthetic hit rate of 78% was calculated using 10-game rolling averages as
proxy betting lines. This is useful for relative performance but doesn't reflect
what would happen betting against actual sportsbook lines.

Real sportsbook lines are:
- **Sharper**: Set by professional oddsmakers
- **More efficient**: Quickly adjust to new information
- **Harder to beat**: Edge will be smaller than synthetic

A 60-70% real hit rate would still be excellent:
- 60% = +6% edge over breakeven (highly profitable)
- 65% = +11% edge (exceptional)
- 70% = +16% edge (world-class)

### What We'll Learn

1. **True model value**: Is this model actually profitable?
2. **Edge calibration**: Do larger predicted edges = better results?
3. **Seasonal patterns**: Is the model consistent or streaky?
4. **OVER vs UNDER bias**: Does the model favor one direction?

### Next Steps After Results

**If profitable (>54%)**:
1. Deploy forward validation (live predictions with real-time odds)
2. Set up daily performance tracking
3. Consider increasing bet sizing for high-edge predictions

**If not profitable (<54%)**:
1. Analyze edge buckets - maybe only high-edge bets are profitable
2. Check for data quality issues
3. Consider model adjustments

---

## Timeline

| Phase | Duration | Status |
|-------|----------|--------|
| Phase 1: Backfill | ~17-18 hrs | RUNNING |
| Phase 2: GCS→BQ | ~15 min | Prepared |
| Phase 3: Match | ~2 min | Prepared |
| Phase 4: Grade | ~3 min | Prepared |
| Phase 5: Calculate | ~1 min | Prepared |
| **Total** | **~18 hours** | |

**Expected completion**: 2026-01-14 ~14:00

---

*Document created by Session 36 as part of MLB Pitcher Strikeouts validation project*
