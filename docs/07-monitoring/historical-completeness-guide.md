# Historical Completeness Guide

**Created:** January 22, 2026
**Purpose:** Guide for using and validating the historical completeness tracking system
**Audience:** Engineers validating data quality, running backfills, or debugging ML features

---

## What is Historical Completeness?

The `historical_completeness` field in `ml_feature_store_v2` tracks whether rolling window calculations (like `points_avg_last_10`) had all the historical data they needed.

**Example:** If a player's last-10-game average only found 8 games instead of 10, the feature is "incomplete" - possibly biased.

### Data Structure

```sql
historical_completeness STRUCT<
    games_found INT64,           -- Actual games retrieved (e.g., 8)
    games_expected INT64,        -- Expected games (e.g., 10)
    is_complete BOOL,            -- games_found >= games_expected
    is_bootstrap BOOL,           -- Player has < 10 games available (not a gap)
    contributing_game_dates ARRAY<DATE>  -- Dates used (for cascade detection)
>
```

### Status Interpretation

| games_expected | games_found | is_complete | is_bootstrap | Meaning |
|----------------|-------------|-------------|--------------|---------|
| 10 | 10 | TRUE | FALSE | **COMPLETE** - All data present |
| 10 | 8 | FALSE | FALSE | **DATA GAP** - Missing 2 games |
| 5 | 5 | TRUE | TRUE | **BOOTSTRAP** - New player, all available data present |
| 0 | 0 | TRUE | TRUE | **NEW PLAYER** - No history yet |

---

## Daily Validation

### Quick Health Check

```bash
# See daily completeness summary (last 7 days)
python bin/check_cascade.py --summary --days 7
```

Expected output for healthy data:
```
Date         Total    Complete   Incomplete   Bootstrap  %
2026-01-22   156      156        0            0          100.0
```

### Check for Data Gaps

```bash
# Find incomplete features (actual data gaps, not bootstrap)
python bin/check_cascade.py --incomplete --start 2026-01-15 --end 2026-01-22
```

If this returns results, you have data gaps that may need investigation.

### Spot Check Feature Calculations

```bash
# Validate random players' calculations are correct
python bin/spot_check_features.py --count 10
```

This verifies:
- `games_found` matches actual games in source data
- `contributing_game_dates` matches actual game dates
- `points_avg_last_10` matches Phase 4 cache values

---

## Tools Reference

| Tool | Purpose | Common Usage |
|------|---------|--------------|
| `bin/check_cascade.py` | Query completeness data | `--summary`, `--incomplete`, `--backfill-date` |
| `bin/spot_check_features.py` | Validate calculations | `--count 20`, `--player X`, `--verbose` |
| `bin/validate_historical_completeness.py` | Full system validation | `--unit-tests`, `--date YYYY-MM-DD` |

### BigQuery Views

```sql
-- Daily summary (last 30 days)
SELECT * FROM nba_predictions.v_historical_completeness_daily;

-- Features with data gaps (not bootstrap)
SELECT * FROM nba_predictions.v_incomplete_features;
```

---

## When to Backfill

### You DON'T need to backfill if:
- You only care about data quality going forward
- Historical predictions have already been made and you're not re-running them
- The pipeline is healthy and you just want monitoring

### You SHOULD backfill if:
- You want to analyze historical data quality
- You need to detect which historical features had gaps
- You're investigating past prediction accuracy issues
- You want `contributing_game_dates` for cascade detection on old data

---

## Backfill Procedure

### Step 1: Decide Scope

| Scope | Command | Time Estimate |
|-------|---------|---------------|
| Last 30 days | `--start-date=$(date -d '-30 days' +%Y-%m-%d)` | ~30 min |
| This season (from Jan 1) | `--start-date=2026-01-01` | ~1 hour |
| Full season (from Oct 22) | `--start-date=2024-10-22` | ~3-4 hours |

### Step 2: Run Phase 4 Backfill

```bash
# Example: Backfill January 2026
./bin/backfill/run_year_phase4.sh --start-date=2026-01-01 --end-date=2026-01-22
```

**What happens:**
- Processor re-runs for each date
- `historical_completeness` gets populated
- Uses `backfill_mode=True` (skips unnecessary checks)
- Idempotent - safe to re-run

### Step 3: Verify

```bash
# Check completeness populated
python bin/check_cascade.py --summary --days 30

# Spot check calculations
python bin/spot_check_features.py --count 20
```

---

## Cascade Detection (After Source Data Backfills)

If you backfill source data (e.g., fix missing games in `player_game_summary`), features that used that data need reprocessing.

**Find affected features:**
```bash
# What features used Jan 5 in their rolling window?
python bin/check_cascade.py --backfill-date 2026-01-05
```

**Reprocess affected dates:**
```bash
# Reprocess the next 21 days (rolling window impact)
./bin/backfill/run_year_phase4.sh --start-date=2026-01-06 --end-date=2026-01-26
```

---

## Troubleshooting

### "No players found with historical_completeness"
The date hasn't been processed since this feature was deployed. Either:
- Wait for daily pipeline to process it, OR
- Run a backfill for that date

### High "Incomplete" count
Indicates actual data gaps. Investigate:
1. Check if source data is missing: `player_game_summary`
2. Check if scrapers failed for those dates
3. Run cascade detection to find root cause

### Spot check failures
If `spot_check_features.py` reports failures:
1. Check the specific check that failed
2. Query raw data to verify
3. May indicate a bug in feature calculation (rare)

---

## Related Documentation

- **Concepts:** `docs/06-reference/completeness-concepts.md` - Explains schedule vs historical completeness
- **Validation Guide:** `docs/07-monitoring/completeness-validation.md` - Full validation procedures
- **Implementation:** `docs/09-handoff/2026-01-22-DATA-CASCADE-IMPLEMENTATION-HANDOFF.md`

---

## Code References

| Component | Location |
|-----------|----------|
| Helper module | `shared/validation/historical_completeness.py` |
| Feature extractor | `data_processors/precompute/ml_feature_store/feature_extractor.py` |
| Processor integration | `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` |
| Schema | `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` |
| Unit tests | `tests/unit/shared/validation/test_historical_completeness.py` |
