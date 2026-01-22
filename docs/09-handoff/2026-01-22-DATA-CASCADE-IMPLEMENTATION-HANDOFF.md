# Data Cascade Implementation - Handoff Document

**Date:** January 22, 2026
**Purpose:** Implement historical completeness tracking for ML feature pipeline
**Priority:** HIGH
**Status:** ✅ IMPLEMENTED AND DEPLOYED (January 22, 2026)

---

## Implementation Complete

### What Was Done

| Task | Status | Details |
|------|--------|---------|
| Schema Migration | ✅ | Added `historical_completeness` STRUCT to `ml_feature_store_v2` |
| Helper Class | ✅ | Created `shared/validation/historical_completeness.py` |
| Feature Extractor | ✅ | Modified to track game dates + total games available |
| Processor | ✅ | Modified to build and attach completeness metadata |
| Batch Writer | ✅ | Updated MERGE to include new column |
| Monitoring Views | ✅ | `v_historical_completeness_daily`, `v_incomplete_features` |
| CLI Tool | ✅ | `bin/check_cascade.py` for cascade detection |
| Documentation | ✅ | `docs/06-reference/completeness-concepts.md` |

### Verification Results

- **Processor Test:** 156 features for 2026-01-21, 100% complete
- **Monitoring Views:** Working correctly
- **CLI Tool:** Operational

### Key Files Modified/Created

**Created:**
- `shared/validation/historical_completeness.py`
- `bin/check_cascade.py`
- `docs/06-reference/completeness-concepts.md`

**Modified:**
- `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`
- `data_processors/precompute/ml_feature_store/feature_extractor.py`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `data_processors/precompute/ml_feature_store/batch_writer.py`
- `docs/07-monitoring/completeness-validation.md`
- `shared/validation/__init__.py`
- `shared/validation/README.md`

---

## Original Design (For Reference)

This system tracks historical data completeness in the ML feature pipeline. This prevents predictions from silently using incomplete/biased rolling averages.

**This was a CODE IMPLEMENTATION task** - the design was complete and approved.

---

## Quick Context

### The Problem
When historical data is missing (e.g., a game's boxscore wasn't scraped), downstream processing continues with biased rolling averages. The system doesn't detect or flag this.

### The Solution
Track what data was used for each feature calculation. Flag when data is incomplete. Enable cascade reprocessing after backfills.

---

## What to Implement

### Data Structure (Per Feature Record)

```python
historical_completeness = {
    'games_found': 8,           # How many games we got
    'games_expected': 10,       # How many player COULD have (capped at 10)
    'is_complete': False,       # games_found >= games_expected
    'is_bootstrap': False,      # games_expected < 10 (limited history available)
    'contributing_game_dates': ['2026-01-20', '2026-01-18', ...]  # For cascade
}
```

### Key Logic

```python
games_expected = min(games_available_for_player, 10)
is_complete = games_found >= games_expected
is_bootstrap = games_expected < 10  # Player has limited history (new, early season)
```

### Thresholds

- **Minimum 5 games** to generate a feature (below that, skip)
- **10 games** is the target window size
- **Bootstrap** = player has < 10 games available (early season, new player, etc.)

---

## Read First

**Primary design doc (has everything):**
```
docs/08-projects/current/data-cascade-architecture/09-FINAL-DESIGN.md
```

**Implementation plan with code examples:**
```
docs/08-projects/current/data-cascade-architecture/07-IMPLEMENTATION-PLAN.md
```

**Full documentation (if needed):**
```
docs/08-projects/current/data-cascade-architecture/00-INDEX.md
```

---

## Files to Modify/Create

| File | Action | Description |
|------|--------|-------------|
| `shared/validation/historical_completeness.py` | **CREATE** | Completeness helper class |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | MODIFY | Return game dates from extraction |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | MODIFY | Build and attach completeness metadata |
| `data_processors/precompute/ml_feature_store/batch_writer.py` | VERIFY | Handle new STRUCT column |
| `bin/check_cascade.py` | **CREATE** | CLI to find affected features |

---

## Implementation Steps

### Step 1: Schema Migration

Run in BigQuery:
```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS historical_completeness STRUCT<
    games_found INT64,
    games_expected INT64,
    is_complete BOOL,
    is_bootstrap BOOL,
    contributing_game_dates ARRAY<DATE>
>;
```

### Step 2: Create Completeness Helper

Create `shared/validation/historical_completeness.py`:

```python
from dataclasses import dataclass
from datetime import date
from typing import List

@dataclass
class CompletenessResult:
    games_found: int
    games_expected: int
    is_complete: bool
    is_bootstrap: bool
    contributing_game_dates: List[date]

    def to_bq_struct(self) -> dict:
        return {
            'games_found': self.games_found,
            'games_expected': self.games_expected,
            'is_complete': self.is_complete,
            'is_bootstrap': self.is_bootstrap,
            'contributing_game_dates': [d.isoformat() for d in self.contributing_game_dates]
        }

def assess_completeness(
    games_found: int,
    games_available: int,
    window_size: int = 10,
    contributing_dates: List[date] = None
) -> CompletenessResult:
    games_expected = min(games_available, window_size)
    is_complete = games_found >= games_expected
    is_bootstrap = games_expected < window_size

    return CompletenessResult(
        games_found=games_found,
        games_expected=games_expected,
        is_complete=is_complete,
        is_bootstrap=is_bootstrap,
        contributing_game_dates=contributing_dates or []
    )
```

### Step 3: Modify Feature Extractor

In `feature_extractor.py`, modify `_batch_extract_last_10_games()` to:
1. Return game dates along with game data
2. Calculate total games available per player (for bootstrap detection)

Key query change - add `COUNT(*) OVER (PARTITION BY player_lookup) as total_games` to get games available.

### Step 4: Modify Processor

In `ml_feature_store_processor.py`, in feature generation:
1. Call `assess_completeness()` with extraction results
2. Skip if `games_found < 5`
3. Log warning if incomplete (and not bootstrap)
4. Attach `historical_completeness` to feature record

### Step 5: Create Monitoring Views

```sql
CREATE OR REPLACE VIEW nba_predictions.v_daily_completeness AS
SELECT
    game_date,
    COUNT(*) as total_features,
    COUNTIF(historical_completeness.is_complete) as complete,
    COUNTIF(NOT historical_completeness.is_complete) as incomplete,
    COUNTIF(historical_completeness.is_bootstrap) as bootstrap
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date;
```

---

## Key Design Decisions (Already Made)

| Decision | Rationale |
|----------|-----------|
| Store `contributing_game_dates` | Needed for cascade detection |
| Don't store `missing_game_dates` | Can be derived when needed |
| Bootstrap vs Incomplete | Bootstrap = have all available; Incomplete = missing data |
| Minimum 5 games | Below that, data too sparse for useful features |
| Flag don't block | Generate features but track issues |

---

## Testing

1. **Schema**: Verify column added correctly
2. **Bootstrap**: Test with early season date (should show `is_bootstrap=True`)
3. **Complete**: Test with mid-season player (should show `is_complete=True`)
4. **Incomplete**: Manually create gap scenario (should show `is_complete=False`)
5. **Cascade**: Verify `contributing_game_dates` can be queried

---

## Existing Infrastructure to Leverage

- `shared/config/nba_season_dates.py` - Season start dates, `is_early_season()`
- `shared/validation/config.py` - `BOOTSTRAP_DAYS = 14`
- `shared/utils/completeness_checker.py` - Existing patterns (but we're simplifying)

---

## Success Criteria

- [ ] All new feature records have `historical_completeness` populated
- [ ] Bootstrap correctly detected for early season / new players
- [ ] Incomplete correctly flagged for data gaps
- [ ] `contributing_game_dates` populated for cascade detection
- [ ] Monitoring view shows daily completeness stats

---

## Out of Scope (For Later)

- Cascade reprocessing automation (just detection for now)
- Backfill existing records (new records only)
- Prediction filtering based on completeness (future enhancement)

---

**Document Author:** Claude Code
**Design Session:** January 22, 2026
