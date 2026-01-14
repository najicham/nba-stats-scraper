# Session 36 Handoff: MLB Historical Backfill Execution

**Date**: 2026-01-14
**Status**: BACKFILL RUNNING (Day 10/352)
**Next Priority**: Wait for backfill → Execute Phases 2-5

---

## Quick Start (For Next Session)

### 1. Check Backfill Status

```bash
# Is it still running?
ps aux | grep backfill_historical

# Check progress
grep "Processing" logs/mlb_historical_backfill_*.log | tail -3

# Check if complete
grep "BACKFILL COMPLETE" logs/mlb_historical_backfill_*.log
```

### 2. If Backfill Complete, Execute Phases 2-5

```bash
# Phase 2: Load GCS → BigQuery (~15 min)
python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py

# Phase 3: Match betting lines to predictions (~2 min)
python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py

# Phase 4: Grade predictions (~3 min)
python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py

# Phase 5: Calculate TRUE hit rate (~1 min)
python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py
```

---

## Current State

### Backfill Running

```bash
# Log file
tail -f logs/mlb_historical_backfill_20260113_205840.log

# Check process
ps aux | grep backfill_historical

# Check progress
grep "Processing" logs/mlb_historical_backfill_*.log | tail -5

# Count GCS files
gsutil ls "gs://nba-scraped-data/mlb-odds-api/pitcher-props-history/**/*.json" | wc -l
```

**Progress** (as of Session 36 end):
- Day: 10/352 (2024-04-19)
- Files created: ~150
- Rate: ~3 min/day
- **Revised ETA: ~14:00 tomorrow (17-18 hours total)**

**Config**:
- 352 dates to process (2024-04-09 to 2025-09-28)
- Resume mode: ON (skips existing GCS files)
- Snapshot time: 18:00 UTC (2 PM ET)

---

## What Was Completed (Session 36)

### Phase 1: Backfill Script ✅
**Running**: `scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py`

### Phase 2-5: Execution Scripts ✅ NEW
Created complete pipeline scripts:

| Script | Purpose |
|--------|---------|
| `process_historical_to_bigquery.py` | Load GCS files to BigQuery |
| `match_lines_to_predictions.py` | Link odds to predictions |
| `grade_historical_predictions.py` | Grade win/loss |
| `calculate_hit_rate.py` | Calculate final hit rate |

All scripts have:
- `--dry-run` mode for preview
- Progress logging
- Error handling
- Resume capability

### Execution Plan Doc ✅ NEW
Created: `docs/08-projects/current/mlb-pitcher-strikeouts/EXECUTION-PLAN-PHASES-2-5.md`

---

## Pipeline Flow

```
Phase 1: GCS Scraping        ─── RUNNING (~14:00 tomorrow)
    ↓
    352 dates → ~5,000 events → GCS JSON files
    ↓
Phase 2: GCS → BigQuery      ─── READY (15 min)
    python process_historical_to_bigquery.py
    ↓
Phase 3: Match Lines         ─── READY (2 min)
    python match_lines_to_predictions.py
    ↓
Phase 4: Grade Predictions   ─── READY (3 min)
    python grade_historical_predictions.py
    ↓
Phase 5: Calculate Hit Rate  ─── READY (1 min)
    python calculate_hit_rate.py
    ↓
    ★ TRUE HIT RATE REVEALED ★
```

---

## GCS Data Location

```
gs://nba-scraped-data/mlb-odds-api/pitcher-props-history/
├── 2024-04-09/
├── 2024-04-11/
├── 2024-04-12/
├── ...
├── 2024-04-19/  ← Currently processing
└── ... (352 dates total)
```

---

## Key Files

| File | Purpose |
|------|---------|
| `scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py` | Phase 1: Scrape to GCS |
| `scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py` | Phase 2: GCS → BigQuery |
| `scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py` | Phase 3: Match lines |
| `scripts/mlb/historical_odds_backfill/grade_historical_predictions.py` | Phase 4: Grade |
| `scripts/mlb/historical_odds_backfill/calculate_hit_rate.py` | Phase 5: Hit rate |
| `data_processors/raw/mlb/mlb_pitcher_props_processor.py` | Core processor |

---

## Expected Results

| Metric | Estimate |
|--------|----------|
| Total Predictions | 8,130 |
| Expected Coverage | 70-80% |
| Predictions with Lines | 5,700-6,500 |
| Synthetic Hit Rate | 78.04% |
| **Expected Real Hit Rate** | **60-70%** |
| Profitable Threshold | >54% |

### Interpretation Guide

| Hit Rate | Assessment | Action |
|----------|------------|--------|
| >70% | ★★★ EXCEPTIONAL | Deploy immediately |
| 60-70% | ★★☆ STRONG | Deploy with monitoring |
| 54-60% | ★☆☆ MARGINAL | Tune model first |
| <54% | ☆☆☆ NOT PROFITABLE | Rework model |

---

## Troubleshooting

### If Backfill Interrupted

```bash
# Just restart - resume mode will skip existing files
python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py --resume

# Or skip to specific date
python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py \
    --skip-to-date 2024-07-15
```

### If Phase 2 Fails on Specific File

```bash
# Skip to date and continue
python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py \
    --skip-to-date 2024-07-15
```

### Dry-Run Any Phase

```bash
# Add --dry-run to any script to preview without executing
python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py --dry-run
python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py --dry-run
python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py --dry-run
```

---

## Session Notes

- Backfill started: 2026-01-13 20:59
- Original ETA was 3-4 hours, revised to 17-18 hours based on actual rate
- All Phase 2-5 scripts created and ready
- Detailed execution plan in `EXECUTION-PLAN-PHASES-2-5.md`

**Expected backfill completion**: ~2026-01-14 14:00
**Time to TRUE hit rate after completion**: ~20 minutes

---

## Verification Queries (After All Phases Complete)

```sql
-- Check historical odds loaded
SELECT COUNT(*) as rows, COUNT(DISTINCT game_date) as dates
FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
WHERE source_file_path LIKE '%pitcher-props-history%';

-- Check predictions matched
SELECT line_source, COUNT(*) as count
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE game_date BETWEEN '2024-04-09' AND '2025-09-28'
GROUP BY line_source;

-- Check grading results
SELECT
    SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END) as losses,
    ROUND(100.0 * SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) /
          NULLIF(SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END), 0), 2) as hit_rate
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE line_source = 'historical_odds_api';
```
