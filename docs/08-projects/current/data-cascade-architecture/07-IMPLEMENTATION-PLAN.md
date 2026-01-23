# Implementation Plan

**Document:** 07-IMPLEMENTATION-PLAN.md
**Updated:** January 22, 2026
**Status:** Ready for Implementation

---

## Final Design Reference

See `09-FINAL-DESIGN.md` for the approved design. Key points:

```python
historical_completeness = {
    'games_found': 8,
    'games_expected': 10,
    'is_complete': False,      # games_found >= games_expected
    'is_bootstrap': False,     # games_expected < 10 (limited history)
    'contributing_game_dates': [...]  # For cascade detection
}
```

---

## Implementation Phases

| Phase | Focus | Effort |
|-------|-------|--------|
| 1 | Schema + Core Logic | 2-3 hours |
| 2 | Feature Extractor Integration | 2-3 hours |
| 3 | Processor Integration | 2-3 hours |
| 4 | Cascade Tools | 3-4 hours |
| 5 | Monitoring & Views | 1-2 hours |

---

## Phase 1: Schema + Core Logic

### Task 1.1: Schema Migration

**File:** Create migration script or run directly

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

### Task 1.2: Create Completeness Helper

**File:** `shared/validation/historical_completeness.py` (NEW)

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
    """
    Assess completeness for a player's rolling window.

    Args:
        games_found: Number of games we retrieved
        games_available: Number of games that exist for this player in window
        window_size: Target window size (default 10)
        contributing_dates: Dates of games we used

    Returns:
        CompletenessResult with status flags
    """
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

---

## Phase 2: Feature Extractor Integration

### Task 2.1: Modify Batch Extraction

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

**Method:** `_batch_extract_last_10_games()`

**Changes:**
1. Return game dates along with game data
2. Calculate games available per player
3. Return metadata for completeness assessment

```python
def _batch_extract_last_10_games(self, game_date):
    """
    Extract last 10 games with completeness metadata.

    Returns dict per player:
    {
        'games': [...],
        'game_dates': [date, ...],
        'games_found': int,
        'games_available': int  # Total in 60-day window
    }
    """
    query = """
    WITH player_games AS (
        SELECT
            player_lookup,
            game_date,
            points, minutes_played, ...
            ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY game_date DESC
            ) as game_num,
            COUNT(*) OVER (PARTITION BY player_lookup) as total_games
        FROM player_game_summary
        WHERE game_date < @target_date
          AND game_date >= DATE_SUB(@target_date, INTERVAL 60 DAY)
    )
    SELECT *
    FROM player_games
    WHERE game_num <= 10
    ORDER BY player_lookup, game_date DESC
    """
    # Process results to include metadata
```

---

## Phase 3: Processor Integration

### Task 3.1: Build Completeness Metadata

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Add to `_generate_player_features()`:**

```python
from shared.validation.historical_completeness import assess_completeness

def _generate_player_features(self, player_lookup, game_date, extraction_data):
    player_data = extraction_data.get(player_lookup, {})

    # Build completeness metadata
    completeness = assess_completeness(
        games_found=player_data.get('games_found', 0),
        games_available=player_data.get('games_available', 0),
        window_size=10,
        contributing_dates=player_data.get('game_dates', [])
    )

    # Skip if too sparse (< 5 games)
    if completeness.games_found < 5:
        return None  # Don't generate feature

    # Log if incomplete
    if not completeness.is_complete and not completeness.is_bootstrap:
        self.logger.warning(
            f"Incomplete data for {player_lookup} on {game_date}: "
            f"{completeness.games_found}/{completeness.games_expected} games"
        )

    # Generate features (existing logic)
    features = self._calculate_features(...)

    # Attach completeness metadata
    features['historical_completeness'] = completeness.to_bq_struct()

    return features
```

### Task 3.2: Update Batch Writer

**File:** `data_processors/precompute/ml_feature_store/batch_writer.py`

Ensure the writer handles the new STRUCT column properly.

---

## Phase 4: Cascade Tools

### Task 4.1: Cascade Detection Query

**File:** `bin/check_cascade.py` (NEW)

```python
#!/usr/bin/env python3
"""
Find features affected by backfilling a specific date.

Usage:
    python bin/check_cascade.py --backfilled-date 2026-01-01
"""

def find_affected_features(backfilled_date):
    query = """
    SELECT DISTINCT game_date, player_lookup
    FROM nba_predictions.ml_feature_store_v2
    WHERE DATE(@backfilled_date) IN UNNEST(historical_completeness.contributing_game_dates)
      AND game_date > @backfilled_date
    ORDER BY game_date, player_lookup
    """
    # Execute and return results
```

### Task 4.2: Find Incomplete Features

```python
def find_incomplete_features(start_date, end_date):
    query = """
    SELECT game_date, player_lookup,
        historical_completeness.games_found,
        historical_completeness.games_expected
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date BETWEEN @start AND @end
      AND NOT historical_completeness.is_complete
      AND NOT historical_completeness.is_bootstrap
    ORDER BY game_date
    """
```

---

## Phase 5: Monitoring & Views

### Task 5.1: Create Views

```sql
-- Daily completeness summary
CREATE OR REPLACE VIEW nba_predictions.v_daily_completeness AS
SELECT
    game_date,
    COUNT(*) as total_features,
    COUNTIF(historical_completeness.is_complete) as complete,
    COUNTIF(NOT historical_completeness.is_complete) as incomplete,
    COUNTIF(historical_completeness.is_bootstrap) as bootstrap
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Incomplete features (data gaps only, not bootstrap)
CREATE OR REPLACE VIEW nba_predictions.v_incomplete_features AS
SELECT
    game_date,
    player_lookup,
    historical_completeness.games_found,
    historical_completeness.games_expected
FROM nba_predictions.ml_feature_store_v2
WHERE NOT historical_completeness.is_complete
  AND NOT historical_completeness.is_bootstrap
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
```

---

## Testing Checklist

- [ ] Schema migration runs without error
- [ ] Feature generation produces completeness metadata
- [ ] Bootstrap correctly identified for early season dates
- [ ] Incomplete correctly identified for data gaps
- [ ] Features skipped when games_found < 5
- [ ] Cascade query returns expected results
- [ ] Views work correctly

---

## Files to Modify/Create

| File | Action |
|------|--------|
| `shared/validation/historical_completeness.py` | CREATE |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | MODIFY |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | MODIFY |
| `data_processors/precompute/ml_feature_store/batch_writer.py` | VERIFY |
| `bin/check_cascade.py` | CREATE |
| `bin/check_completeness.py` | CREATE |

---

**Document Status:** Ready for Implementation
