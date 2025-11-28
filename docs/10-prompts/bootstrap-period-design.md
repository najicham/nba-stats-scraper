# Bootstrap Period Design Prompt

## Context

When running analytics calculations, there are situations where the required historical data doesn't exist yet. This happens in two scenarios:

### Scenario 1: Historical Backfill Bootstrap

When backfilling analytics from the beginning of our data (2021-10-19), the first N days won't have enough historical data for rolling calculations.

**Example:**
- Calculation: "Player's rolling 10-game points average"
- Day 1 of backfill: Only 1 game exists, need 10
- Day 10 of backfill: Now have 10 games ✓

**Current behavior:** Calculation uses whatever data is available (might be 3 games instead of 10)

**Questions:**
1. Should we skip these calculations entirely during bootstrap?
2. Should we flag them as "incomplete" in the output?
3. Should we use a different calculation (e.g., available games instead of 10)?

### Scenario 2: Season Start Bootstrap (Recurring)

At the start of each NBA season (October), calculations that use "current season only" data face the same issue.

**Example:**
- Calculation: "Player's season-to-date scoring average"
- Oct 22 (game 1): Only 1 game this season
- Nov 15 (game 15): Now have meaningful average ✓

**Current behavior:** Unknown - need to audit processors

**Questions:**
1. How do processors currently handle early-season data?
2. Should we fall back to prior season data during bootstrap?
3. Should we use a weighted blend (e.g., 70% prior season, 30% current early on)?

## Current Implementation

### Player Game Summary Processor

Location: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

Key calculations that might be affected:
- Rolling averages (5-game, 10-game)
- Season-to-date averages
- Trend calculations

### Relevant Code to Audit

```python
# Check how these calculations handle insufficient data:
# 1. Rolling window calculations
# 2. Season filtering logic
# 3. Minimum sample size requirements
```

## Design Questions to Answer

### For Historical Backfill

1. **What is the "epoch date"?**
   - First date with any data: 2021-10-19
   - Should this be configurable per processor?

2. **What is the bootstrap period?**
   - Depends on the calculation window (10-game avg → ~20 days)
   - Should processors declare their required history?

3. **How should calculations behave during bootstrap?**
   - Option A: Use available data, flag as incomplete
   - Option B: Skip calculation, return NULL
   - Option C: Use minimum threshold (e.g., need at least 3 games)

### For Season Start

1. **How do we detect "early season"?**
   - First N games of season?
   - First N weeks?
   - Until player has X games?

2. **What's the fallback strategy?**
   - Option A: Use prior season data
   - Option B: Use career averages
   - Option C: Use league averages
   - Option D: Weighted blend of options

3. **When does bootstrap end?**
   - After N games played?
   - After specific date (Nov 15)?
   - When confidence interval is acceptable?

## Proposed Configuration

```python
class PlayerGameSummaryProcessor:
    # Bootstrap configuration
    BOOTSTRAP_CONFIG = {
        'rolling_10_game': {
            'min_games_required': 3,      # Minimum to calculate
            'optimal_games': 10,           # Full calculation
            'flag_incomplete': True,       # Add is_bootstrap flag
        },
        'season_average': {
            'min_games_required': 5,
            'fallback_strategy': 'prior_season_weighted',
            'fallback_weight_decay': 0.1,  # Reduce prior season weight per game
        }
    }
```

## Output Schema Additions

Consider adding bootstrap-related fields:

```sql
-- In player_game_summary table
is_bootstrap_period BOOLEAN,        -- True if during bootstrap
bootstrap_games_available INTEGER,  -- Games available for calculation
bootstrap_games_required INTEGER,   -- Games ideally needed
calculation_confidence FLOAT,       -- 0.0-1.0 based on data completeness
```

## Tasks

1. [ ] Audit player_game_summary processor for rolling calculations
2. [ ] Identify which calculations are affected by bootstrap
3. [ ] Design bootstrap detection logic
4. [ ] Design fallback strategies
5. [ ] Add bootstrap flags to output schema
6. [ ] Implement and test
7. [ ] Document behavior for downstream consumers

## References

- Early Exit Pattern: `docs/05-development/patterns/early-exit-pattern.md`
- Player Game Summary Processor: `data_processors/analytics/player_game_summary/`
- Backfill Script: `backfill_jobs/analytics/player_game_summary/`
