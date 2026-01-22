# Completeness Concepts: Schedule vs Historical

**File:** `docs/06-reference/completeness-concepts.md`
**Created:** January 22, 2026
**Purpose:** Explain the two types of completeness tracking in the ML feature pipeline
**Audience:** Engineers validating data, fixing historical gaps, or understanding feature quality

---

## Executive Summary

The ML feature pipeline tracks **TWO types of completeness**:

1. **Schedule Completeness** - "Did we get today's games?"
2. **Historical Completeness** - "Did rolling averages have all required data?"

Both are stored in `ml_feature_store_v2` but serve different purposes.

---

## Why Two Types?

### The Problem

When a game's data is missing from the pipeline:

1. **Same-day impact:** Today's features might not be generated (Schedule Completeness catches this)
2. **Forward impact:** Next 21 days of features use biased rolling averages (Historical Completeness catches this)

Example: If Jan 1's data is missing:
- Schedule completeness for Jan 1: **INCOMPLETE** (missing today's game)
- Historical completeness for Jan 2-21: **INCOMPLETE** (rolling averages biased)

### The Solution

Track BOTH types of completeness in `ml_feature_store_v2`:

```
ml_feature_store_v2
├── Schedule completeness fields (existing):
│   ├── expected_games_count
│   ├── actual_games_count
│   ├── completeness_percentage
│   └── is_production_ready
│
└── Historical completeness field (NEW):
    └── historical_completeness STRUCT<
            games_found,
            games_expected,
            is_complete,
            is_bootstrap,
            contributing_game_dates
        >
```

---

## Schedule Completeness (Existing)

### Question
"Did we get today's games from upstream tables?"

### Scope
Single day (the date being processed)

### Fields
| Field | Type | Description |
|-------|------|-------------|
| `expected_games_count` | INT64 | Games expected from schedule |
| `actual_games_count` | INT64 | Games found in upstream |
| `completeness_percentage` | FLOAT64 | Percentage (0-100%) |
| `is_production_ready` | BOOL | True if >= 90% complete |

### Use Cases
- Daily pipeline validation
- Determining if features should be generated
- Circuit breaker decisions

### Example
```
Date: 2026-01-15
Scheduled games: 12
Actual games found: 12
completeness_percentage: 100%
is_production_ready: TRUE
```

---

## Historical Completeness (NEW - Jan 2026)

### Question
"Did rolling window calculations have all required historical data?"

### Scope
60-day lookback window (last 10 games for each player)

### Field Structure
```sql
historical_completeness STRUCT<
    games_found INT64,           -- Actual games in rolling window (e.g., 8)
    games_expected INT64,        -- Expected games (min of available, 10)
    is_complete BOOL,            -- games_found >= games_expected
    is_bootstrap BOOL,           -- games_expected < 10 (limited history)
    contributing_game_dates ARRAY<DATE>  -- Dates used (for cascade detection)
>
```

### Use Cases
1. **Bias Detection:** Identify features calculated with incomplete data
2. **Cascade Detection:** Find features to reprocess after a backfill
3. **Bootstrap Detection:** Distinguish "new player" from "data gap"

### Status Matrix

| games_expected | games_found | is_complete | is_bootstrap | Interpretation |
|----------------|-------------|-------------|--------------|----------------|
| 10 | 10 | TRUE | FALSE | Normal complete |
| 10 | 8 | **FALSE** | FALSE | **DATA GAP** - Missing 2 games |
| 10 | 5 | **FALSE** | FALSE | **DATA GAP** - Missing 5 games |
| 5 | 5 | TRUE | **TRUE** | Bootstrap - New player, all available data present |
| 3 | 3 | TRUE | **TRUE** | Bootstrap - Early in career |
| 0 | 0 | TRUE | **TRUE** | New player - No history yet |

### Key Logic
```python
games_expected = min(games_available_for_player, 10)
is_complete = games_found >= games_expected
is_bootstrap = games_expected < 10

# Data gap = incomplete AND not bootstrap
is_data_gap = not is_complete and not is_bootstrap
```

---

## Comparison Table

| Aspect | Schedule Completeness | Historical Completeness |
|--------|----------------------|------------------------|
| **Question** | Did we get today's games? | Did rolling averages have all 10 games? |
| **Scope** | Single day | 60-day lookback |
| **What it tracks** | Upstream table availability | Rolling window data quality |
| **When it fails** | Scraper/processor failure for today | Historical data gaps |
| **Impact of failure** | Features not generated | Features generated with bias |
| **Fields** | `expected_games_count`, etc. | `historical_completeness` STRUCT |
| **Primary use** | Daily validation | Cascade detection |
| **Bootstrap handling** | `backfill_bootstrap_mode` flag | `is_bootstrap` in STRUCT |

---

## Cascade Detection

### The Problem
When data is backfilled for a date (e.g., Jan 1), features for future dates that used that data in their rolling windows are now stale.

### The Solution
The `contributing_game_dates` array tracks which dates were used:

```sql
-- Find features affected by backfilling Jan 1
SELECT game_date, player_lookup
FROM nba_predictions.ml_feature_store_v2
WHERE DATE('2026-01-01') IN UNNEST(historical_completeness.contributing_game_dates)
  AND game_date > '2026-01-01'
ORDER BY game_date;
```

### CLI Tool
```bash
# Find affected features
python bin/check_cascade.py --backfill-date 2026-01-01

# Find incomplete features
python bin/check_cascade.py --incomplete --start 2026-01-01 --end 2026-01-21

# Daily summary
python bin/check_cascade.py --summary
```

---

## Validation Workflow

### Daily Validation (Schedule Completeness)
```bash
# Check if today's pipeline completed
python bin/validate_pipeline.py today

# Check specific date
python bin/validate_pipeline.py 2026-01-15
```

### Historical Validation (After Backfill)
```bash
# Check daily completeness summary
python bin/check_cascade.py --summary --days 7

# Find features with data gaps
python bin/check_cascade.py --incomplete --start 2026-01-01 --end 2026-01-21

# Find features affected by a backfill
python bin/check_cascade.py --backfill-date 2026-01-01
```

### BigQuery Monitoring Views
```sql
-- Daily historical completeness summary
SELECT * FROM nba_predictions.v_historical_completeness_daily;

-- Features with data gaps (not bootstrap)
SELECT * FROM nba_predictions.v_incomplete_features;
```

---

## When to Use Each

### Use Schedule Completeness When:
- Checking if today's pipeline ran successfully
- Deciding if features should be generated
- Debugging why features weren't created for a date

### Use Historical Completeness When:
- Investigating ML model accuracy issues
- Planning cascade reprocessing after a backfill
- Identifying features with biased rolling averages
- Determining if a player's features are trustworthy

---

## Code References

### Schedule Completeness
- Fields: `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` (lines 83-103)
- Checker: `shared/utils/completeness_checker.py`
- Processor: `ml_feature_store_processor.py` (lines 993-1008)

### Historical Completeness
- Helper: `shared/validation/historical_completeness.py`
- STRUCT: `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` (historical_completeness)
- CLI: `bin/check_cascade.py`
- Views: `v_historical_completeness_daily`, `v_incomplete_features`

---

## Related Documentation

- **Architecture:** `docs/08-projects/current/data-cascade-architecture/09-FINAL-DESIGN.md`
- **Validation Guide:** `docs/07-monitoring/completeness-validation.md`
- **Validation Framework:** `shared/validation/README.md`

---

**Document Author:** Claude Code
**Created:** January 22, 2026
**Status:** Active
