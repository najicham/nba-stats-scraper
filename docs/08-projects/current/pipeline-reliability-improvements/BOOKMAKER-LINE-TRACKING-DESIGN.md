# Bookmaker-Specific Line Tracking Design

**Created:** 2026-01-09
**Status:** Design Document for Future Implementation
**Priority:** Medium - Enhancement for user-specific performance tracking

---

## Problem Statement

Currently, we track predictions against "best available" or first-matched prop lines, but:
- Most users bet on **DraftKings**
- Some users bet on **FanDuel**
- Fewer users on smaller books (BetMGM, ESPN Bet, etc.)

Users want to know: **"How would this pick have performed on MY book?"**

---

## Current State

### What We Store

| Table | Field | Values | Notes |
|-------|-------|--------|-------|
| `bettingpros_player_points_props` | `bookmaker` | DraftKings, FanDuel, BetMGM, etc. | Raw data - has ALL lines |
| `upcoming_player_game_context` | `current_points_line_source` | draftkings, fanduel, bettingpros | First match used |
| `player_prop_predictions` | `line_source` | ACTUAL_PROP, ESTIMATED_AVG | No bookmaker info |

### Line Availability (Jan 2026 Sample)

| Metric | Value |
|--------|-------|
| Total player-games | 857 |
| Has DraftKings line | 838 (98%) |
| Has FanDuel line | 837 (98%) |
| Has both DK + FD | 818 (95%) |

### Line Differences (DK vs FD)

| Difference | Occurrences | Percentage |
|------------|-------------|------------|
| 0 points | 646 | 79% |
| 1 point | 166 | 20% |
| 2+ points | 6 | <1% |

**Insight:** Lines are usually identical or differ by 1 point. The 20% that differ by 1 point could swing a pick from WIN to LOSS.

---

## Proposed Architecture

### Option A: Add Bookmaker to Predictions Table (Simple)

**Schema Change:**
```sql
ALTER TABLE player_prop_predictions
ADD COLUMN line_bookmaker STRING,        -- 'draftkings', 'fanduel', etc.
ADD COLUMN draftkings_line NUMERIC,      -- DK line at prediction time
ADD COLUMN fanduel_line NUMERIC;         -- FD line at prediction time
```

**Pros:**
- Simple implementation
- All data in one place
- Easy to query

**Cons:**
- Schema changes to existing table
- Fixed to specific bookmakers
- Redundant storage if lines are same

### Option B: Separate Line Comparison Table (Recommended)

**New Table: `prediction_bookmaker_lines`**
```sql
CREATE TABLE prediction_bookmaker_lines (
  prediction_id STRING,           -- FK to player_prop_predictions
  game_date DATE,
  player_lookup STRING,
  bookmaker STRING,               -- 'draftkings', 'fanduel', 'consensus', etc.
  line_value NUMERIC,             -- The line from this bookmaker
  line_timestamp TIMESTAMP,       -- When line was captured

  -- Populated after grading
  actual_points INT,
  was_over BOOL,                  -- actual > line
  prediction_was_correct BOOL,    -- recommendation matched outcome for THIS line
  edge NUMERIC,                   -- predicted_points - line_value

  PRIMARY KEY (prediction_id, bookmaker)
)
PARTITION BY game_date
CLUSTER BY bookmaker, player_lookup;
```

**Pros:**
- Flexible - can add bookmakers without schema change
- Clean separation of concerns
- Can track line movement over time
- Enables rich analysis

**Cons:**
- Additional table to maintain
- More complex queries (requires JOIN)
- More storage

### Option C: Hybrid Approach

Keep primary bookmaker in predictions table, use separate table for comparison:

```sql
-- Predictions table addition
ALTER TABLE player_prop_predictions
ADD COLUMN primary_bookmaker STRING;  -- The book used for the main prediction

-- New comparison table for multi-book analysis
CREATE TABLE prediction_line_evaluations AS Option B;
```

---

## Recommended Implementation: Option B

### Why Option B?

1. **Flexibility:** Can add/remove bookmakers without schema changes
2. **Analysis:** Enables rich queries like "performance by bookmaker"
3. **Backfill:** Can populate from historical raw data
4. **Line Shopping:** Can identify where prediction wins on one book but loses on another

### Implementation Steps

#### Phase 1: Schema & Backfill

1. Create `prediction_bookmaker_lines` table
2. Backfill from existing data:
   ```sql
   INSERT INTO prediction_bookmaker_lines
   SELECT
     p.prediction_id,
     p.game_date,
     p.player_lookup,
     r.bookmaker,
     r.points_line as line_value,
     r.processed_at as line_timestamp,
     a.points as actual_points,
     a.points > r.points_line as was_over,
     CASE
       WHEN p.recommendation = 'OVER' AND a.points > r.points_line THEN true
       WHEN p.recommendation = 'UNDER' AND a.points < r.points_line THEN true
       ELSE false
     END as prediction_was_correct,
     p.predicted_points - r.points_line as edge
   FROM player_prop_predictions p
   JOIN bettingpros_player_points_props r
     ON p.player_lookup = r.player_lookup AND p.game_date = r.game_date
   LEFT JOIN player_game_summary a
     ON p.player_lookup = a.player_lookup AND p.game_date = a.game_date
   WHERE r.bookmaker IN ('DraftKings', 'FanDuel', 'BettingPros Consensus')
   ```

#### Phase 2: Update Grading Pipeline

Modify `prediction_accuracy_processor.py` to:
1. Look up all bookmaker lines for each prediction
2. Create evaluation records for each major bookmaker
3. Calculate `prediction_was_correct` against each book's line

#### Phase 3: Create Analysis Views

```sql
-- Performance by bookmaker
CREATE VIEW v_performance_by_bookmaker AS
SELECT
  bookmaker,
  COUNT(*) as total_picks,
  COUNTIF(prediction_was_correct) as wins,
  ROUND(COUNTIF(prediction_was_correct) / COUNT(*) * 100, 1) as hit_rate
FROM prediction_bookmaker_lines
WHERE actual_points IS NOT NULL
GROUP BY bookmaker;

-- Line shopping opportunities
CREATE VIEW v_line_shopping_opportunities AS
SELECT
  p.game_date,
  p.player_lookup,
  p.recommendation,
  dk.line_value as dk_line,
  fd.line_value as fd_line,
  dk.line_value - fd.line_value as line_diff,
  dk.prediction_was_correct as dk_correct,
  fd.prediction_was_correct as fd_correct
FROM player_prop_predictions p
JOIN prediction_bookmaker_lines dk ON p.prediction_id = dk.prediction_id AND dk.bookmaker = 'DraftKings'
JOIN prediction_bookmaker_lines fd ON p.prediction_id = fd.prediction_id AND fd.bookmaker = 'FanDuel'
WHERE dk.prediction_was_correct != fd.prediction_was_correct;  -- Different outcomes!
```

---

## Key Considerations

### 1. Line Timing

**Question:** Which line snapshot to use?
- Opening line (first available)
- Closing line (last before game)
- Line at prediction time

**Recommendation:** Store `line_timestamp` and use closing line for evaluation (most accurate reflection of where user would bet).

### 2. Line Movement

Lines move throughout the day. A pick might be:
- OVER at 10am (line = 24.5)
- UNDER at 6pm (line = 26.5)

**Recommendation:** Track both opening and closing lines for analysis.

### 3. Missing Lines

Not all bookmakers have lines for all players.

| Scenario | Handling |
|----------|----------|
| DK has line, FD doesn't | Create DK record only |
| Neither has line | Use consensus or skip |
| Only small books have line | Flag as "limited availability" |

### 4. Bookmaker Priority

For "primary" line selection:

| Priority | Bookmaker | Reason |
|----------|-----------|--------|
| 1 | DraftKings | Most users |
| 2 | FanDuel | Second most users |
| 3 | BettingPros Consensus | Fallback |
| 4 | BetMGM | Fallback |
| 5 | ESPN Bet | Fallback |

### 5. Performance Variance by Book

Some books may be consistently "softer" (easier to beat). This analysis would reveal:
- Which book has highest hit rate
- Whether to recommend specific books to users
- Line shopping opportunities

---

## Queries for Future Analysis

### Hit Rate by Bookmaker
```sql
SELECT
  bookmaker,
  system_id,
  COUNT(*) as picks,
  ROUND(COUNTIF(prediction_was_correct) / COUNT(*) * 100, 1) as hit_rate
FROM prediction_bookmaker_lines pbl
JOIN player_prop_predictions p ON pbl.prediction_id = p.prediction_id
WHERE pbl.actual_points IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;
```

### Cases Where DK and FD Have Different Outcomes
```sql
SELECT
  COUNT(*) as total_compared,
  COUNTIF(dk.prediction_was_correct AND NOT fd.prediction_was_correct) as dk_wins_fd_loses,
  COUNTIF(NOT dk.prediction_was_correct AND fd.prediction_was_correct) as fd_wins_dk_loses,
  COUNTIF(dk.prediction_was_correct = fd.prediction_was_correct) as same_outcome
FROM prediction_bookmaker_lines dk
JOIN prediction_bookmaker_lines fd
  ON dk.prediction_id = fd.prediction_id
WHERE dk.bookmaker = 'DraftKings'
  AND fd.bookmaker = 'FanDuel'
  AND dk.actual_points IS NOT NULL;
```

### ROI by Bookmaker
```sql
SELECT
  bookmaker,
  COUNT(*) as picks,
  ROUND((COUNTIF(prediction_was_correct) * 91.0 -
         COUNTIF(NOT prediction_was_correct) * 100.0) /
        (COUNT(*) * 100.0) * 100, 1) as roi_pct
FROM prediction_bookmaker_lines
WHERE actual_points IS NOT NULL
GROUP BY 1
ORDER BY roi_pct DESC;
```

---

## Estimated Effort

| Phase | Task | Effort |
|-------|------|--------|
| 1 | Create table schema | 30 min |
| 1 | Write backfill query | 2 hours |
| 1 | Run backfill | 1 hour |
| 2 | Update grading processor | 2-3 hours |
| 2 | Update UPGC to track primary bookmaker | 1 hour |
| 3 | Create analysis views | 1 hour |
| 3 | Update documentation | 1 hour |
| **Total** | | **8-10 hours** |

---

## Success Metrics

After implementation, we should be able to answer:

1. **"What's my hit rate on DraftKings specifically?"**
2. **"Are FanDuel lines easier to beat than DraftKings?"**
3. **"How many picks would have won on FD but lost on DK?"**
4. **"What's the average line difference between books?"**
5. **"Should I line shop before placing this bet?"**

---

## Next Steps for Implementation

1. Review this design document
2. Decide on Option A vs B vs C
3. Create the schema in BigQuery
4. Write and test backfill query
5. Update grading pipeline
6. Create analysis views
7. Build dashboard/reporting

---

## Document History

| Date | Change |
|------|--------|
| 2026-01-09 | Initial design document created |
