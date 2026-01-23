# Historical Data Cleanup Plan

**Date:** 2026-01-23
**Status:** Planning
**Priority:** P1

---

## Executive Summary

After investigation, most ESTIMATED_AVG predictions are for players that BettingPros genuinely didn't cover (role players, bench players). Only **6,417 predictions from 2025-26** can be converted to real lines.

**Recommendation:**
1. Convert the 6,417 fixable predictions
2. Add `estimated_points_line` column for future predictions (reference baseline)
3. Keep historical ESTIMATED_AVG as-is (they won't be graded anyway)

---

## Investigation Results

### Convertibility by Season

| Season | ESTIMATED_AVG Predictions | BettingPros Coverage | Convertible |
|--------|---------------------------|----------------------|-------------|
| 2021-22 | 15,635 | No overlap | 0% |
| 2022-23 | 11,954 | No overlap | 0% |
| 2023-24 | 11,172 | No overlap | 0% |
| 2024-25 | 8,348 | No overlap | 0% |
| 2025-26 | 58,329 | 6,417 match | **11%** |

### Why Most Are Not Convertible

ESTIMATED_AVG predictions were made for players like:
- `jarenjacksonjr`, `delonwright`, `troybrownjr` (role players)

BettingPros covers players like:
- `lebronjames`, `nikolajokic`, `demarderozan` (stars)

**These are genuinely different player sets.** The system correctly used real lines when available, and fell back to estimates for players without market coverage.

### What's Fixable

The 6,417 predictions in 2025-26 that CAN be converted are likely:
- Games where our sportsbook-priority fallback didn't find the line
- Recent improvements to BettingPros coverage
- Potential player_lookup mapping gaps

---

## Proposed Plan

### Phase 1: Convert Fixable 2025-26 Predictions (P1)

**Goal:** Convert 6,417 ESTIMATED_AVG → ACTUAL_PROP for 2025-26

**Approach:**
1. Query predictions with `line_source = 'ESTIMATED_AVG'` AND matching BettingPros data
2. Update `line_source`, `line_source_api`, `sportsbook`, `current_points_line`
3. Recalculate `recommendation` (OVER/UNDER) based on real line
4. These predictions can then be graded

**SQL:**
```sql
-- Find convertible predictions
WITH convertible AS (
  SELECT
    p.prediction_id,
    p.predicted_points,
    b.line_value as real_line,
    b.bookmaker as sportsbook
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_raw.bettingpros_player_points_props b
    ON p.player_lookup = b.player_lookup
    AND p.game_date = b.game_date
  WHERE p.line_source = 'ESTIMATED_AVG'
    AND p.is_active = TRUE
    AND p.game_date >= '2025-10-01'
)
-- Then UPDATE these records
```

**Estimated Impact:** 6,417 predictions become gradable

### Phase 2: Schema Enhancement - Add Estimated Line Column (P2)

**Goal:** Separate real lines from estimated baselines

**Current Schema:**
```sql
current_points_line NUMERIC(4,1)  -- Sometimes real, sometimes estimated (confusing!)
line_source STRING               -- 'ACTUAL_PROP' or 'ESTIMATED_AVG'
```

**Proposed Schema:**
```sql
current_points_line NUMERIC(4,1)    -- Real Vegas line only (NULL if none)
estimated_points_line NUMERIC(4,1)  -- Player's L5 average (always populated)
line_source STRING                  -- 'ACTUAL_PROP', 'NO_PROP_LINE'
```

**Benefits:**
- Clear separation: Vegas line vs player baseline
- Can track: "How far was our prediction from player's average?"
- Can track: "How far was Vegas from player's average?"
- Grading only uses `current_points_line` (real lines)
- `estimated_points_line` is reference data only

**Migration:**
1. Add new column `estimated_points_line`
2. For existing records: populate from `upcoming_player_game_context.points_avg_last_5`
3. For ESTIMATED_AVG records: copy `current_points_line` → `estimated_points_line`, set `current_points_line` = NULL
4. Update code to populate both columns

### Phase 3: Historical ESTIMATED_AVG Cleanup (P3 - Optional)

**Options:**

**Option A: Leave As-Is (Recommended)**
- Historical ESTIMATED_AVG won't be graded (filter excludes them)
- Predictions exist for historical reference
- No action needed

**Option B: Delete Historical ESTIMATED_AVG**
- Clean up 47K+ records
- Lose historical predicted_points data
- Not recommended unless storage is a concern

**Option C: Update Historical to NO_PROP_LINE**
- Change `line_source` from 'ESTIMATED_AVG' to 'NO_PROP_LINE'
- Set `current_points_line` = NULL
- Keep `predicted_points` for MAE tracking
- More accurate representation

---

## Implementation Details

### Phase 1 SQL (Convert 6,417 Predictions)

```sql
-- Step 1: Create temp table with conversions
CREATE TEMP TABLE convertible_predictions AS
WITH best_lines AS (
  SELECT
    game_date,
    player_lookup,
    -- Pick DraftKings/FanDuel first, then any book
    ARRAY_AGG(
      STRUCT(line_value, bookmaker)
      ORDER BY
        CASE bookmaker
          WHEN 'draftkings' THEN 1
          WHEN 'fanduel' THEN 2
          ELSE 3
        END
      LIMIT 1
    )[OFFSET(0)] as best_line
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date >= '2025-10-01'
  GROUP BY 1, 2
)
SELECT
  p.prediction_id,
  p.predicted_points,
  b.best_line.line_value as real_line,
  UPPER(b.best_line.bookmaker) as sportsbook,
  CASE
    WHEN p.predicted_points > b.best_line.line_value THEN 'OVER'
    WHEN p.predicted_points < b.best_line.line_value THEN 'UNDER'
    ELSE 'PASS'
  END as new_recommendation
FROM nba_predictions.player_prop_predictions p
JOIN best_lines b
  ON p.player_lookup = b.player_lookup
  AND p.game_date = b.game_date
WHERE p.line_source = 'ESTIMATED_AVG'
  AND p.is_active = TRUE
  AND p.game_date >= '2025-10-01';

-- Step 2: Update predictions
UPDATE nba_predictions.player_prop_predictions p
SET
  line_source = 'ACTUAL_PROP',
  line_source_api = 'BETTINGPROS',
  sportsbook = c.sportsbook,
  current_points_line = c.real_line,
  recommendation = c.new_recommendation,
  has_prop_line = TRUE,
  updated_at = CURRENT_TIMESTAMP()
FROM convertible_predictions c
WHERE p.prediction_id = c.prediction_id;
```

### Phase 2 Schema Migration

```sql
-- Add new column
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN estimated_points_line NUMERIC(4,1);

-- Backfill for ESTIMATED_AVG records
UPDATE nba_predictions.player_prop_predictions
SET estimated_points_line = current_points_line
WHERE line_source = 'ESTIMATED_AVG';

-- For ACTUAL_PROP records, join with context table
-- (separate script needed)
```

---

## Success Criteria

### Phase 1
- [ ] 6,417 predictions converted to ACTUAL_PROP
- [ ] Converted predictions appear in grading runs
- [ ] No ESTIMATED_AVG with matching BettingPros data

### Phase 2
- [ ] New `estimated_points_line` column exists
- [ ] All predictions have `estimated_points_line` populated
- [ ] `current_points_line` is NULL for NO_PROP_LINE predictions
- [ ] Grading still works (uses `current_points_line`)

### Phase 3 (if chosen)
- [ ] No 'ESTIMATED_AVG' line_source in table
- [ ] Historical records updated to 'NO_PROP_LINE'

---

## Decision Points

1. **Do we want the `estimated_points_line` column?**
   - Pro: Clear separation, useful for analysis
   - Con: Schema change, migration needed

2. **Should we delete or keep historical ESTIMATED_AVG?**
   - Keep: Historical reference, no harm (not graded)
   - Delete: Cleaner data, but lose predicted_points

3. **Priority of each phase?**
   - Phase 1: P1 (immediate value - 6,417 gradable predictions)
   - Phase 2: P2 (structural improvement)
   - Phase 3: P3 (optional cleanup)

---

## Next Steps

1. Review and approve plan
2. Execute Phase 1 (convert 6,417 predictions)
3. Decide on Phase 2 (schema enhancement)
4. Re-run grading for affected dates
