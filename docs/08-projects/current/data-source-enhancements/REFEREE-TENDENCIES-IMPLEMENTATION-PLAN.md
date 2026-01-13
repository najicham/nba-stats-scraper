# Referee Tendencies Implementation Plan

**Created:** 2026-01-12
**Status:** Ready for Review
**Estimated Effort:** 6-8 hours
**Priority:** P1 (high value, builds on existing data)

---

## Executive Summary

The system scrapes referee assignments but does **NOT calculate or use referee tendencies** in predictions. Research shows referee crews significantly impact game pace and total points - factors directly relevant to player prop predictions.

**Current state:**
1. ✅ Have referee assignments (who refs which game)
2. ✅ Have game results with scores
3. ❌ No historical referee tendencies calculated
4. ❌ `referee_adj = 0.0` hardcoded in composite factors
5. ❌ `referee_avg_points_per_game` and `referee_avg_pace` fields exist but are not populated

**This plan:** Build a referee tendencies processor that calculates rolling stats from historical games, then integrate into predictions.

---

## Why Referee Tendencies Matter

### Research Findings

NBA referee crews have measurable, consistent tendencies:

| Metric | Variance Between Refs | Impact on Props |
|--------|----------------------|-----------------|
| **Total points per game** | ±5-10 points | High-scoring refs = more player points |
| **Pace (possessions/48)** | ±3-5 possessions | More possessions = more scoring chances |
| **Fouls called per game** | ±4-6 fouls | More fouls = more free throws |
| **Over/Under record** | 45%-55% variance | Some refs consistently see overs |

### Example Impact

If a referee crew averages 225 total points vs league average of 220:
- 5 extra points distributed across ~10 rotation players
- Star players (30%+ usage) could see +1.5 points
- This is the difference between hitting/missing a prop

---

## Current Architecture

### What EXISTS ✅

```
┌─────────────────────────────────────────────────────────────────┐
│ nba_raw.nbac_referee_game_assignments                           │
│ ─────────────────────────────────────                           │
│ • One row per official per game                                 │
│ • official_code, official_name, official_position               │
│ • game_id, game_date, home_team, away_team                      │
│ • Partitioned by game_date, clustered by official_code          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ nba_raw.nbac_referee_game_pivot (VIEW)                          │
│ ─────────────────────────────────────                           │
│ • One row per game with pivoted officials                       │
│ • chief_referee, crew_referee_1, crew_referee_2, crew_referee_3 │
│ • Includes official codes for lookups                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ nba_raw.nbac_scoreboard_v2                                      │
│ ─────────────────────────────                                   │
│ • Game results with home_score, away_score                      │
│ • game_state = 'post' for completed games                       │
│ • Can join with referee assignments on game_id                  │
└─────────────────────────────────────────────────────────────────┘
```

### What's MISSING ❌

```
┌─────────────────────────────────────────────────────────────────┐
│ nba_analytics.referee_tendencies (DOES NOT EXIST)               │
│ ─────────────────────────────────                               │
│ Need to create:                                                 │
│ • Rolling averages per referee                                  │
│ • Total points, pace, fouls, O/U record                         │
│ • Confidence intervals (games worked)                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Integration Points (BROKEN)                                     │
│ ─────────────────────────────                                   │
│ • daily_game_context has placeholder fields (not populated)     │
│ • player_composite_factors has referee_adj = 0.0 (hardcoded)    │
│ • upcoming_team_game_context doesn't include referee context    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Tasks

### Task 1: Create Referee Tendencies Schema

**File:** `schemas/bigquery/analytics/referee_tendencies_tables.sql`

```sql
-- ============================================================================
-- Referee Tendencies Table
-- Historical performance metrics for NBA referees
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba_analytics.referee_tendencies` (
  -- Referee identification
  official_code INT64 NOT NULL,
  official_name STRING NOT NULL,

  -- Time window
  season STRING NOT NULL,                    -- e.g., '2025-26'
  calculation_date DATE NOT NULL,            -- When these stats were calculated
  rolling_window_days INT64 NOT NULL,        -- e.g., 60, 90, or full season (0)

  -- Volume metrics (for confidence weighting)
  games_worked INT64 NOT NULL,
  games_as_chief INT64,
  games_as_crew INT64,

  -- Scoring tendencies
  avg_total_points NUMERIC(5, 1),            -- Average home + away score
  avg_total_points_vs_league NUMERIC(4, 1),  -- Differential vs league average
  std_dev_total_points NUMERIC(4, 1),        -- Consistency measure

  -- Over/Under record
  games_with_total_line INT64,               -- Games where we have O/U line
  overs_hit INT64,
  unders_hit INT64,
  pushes INT64,
  over_percentage NUMERIC(4, 2),             -- 0.00 to 1.00

  -- Pace metrics
  avg_pace NUMERIC(5, 1),                    -- Possessions per 48 minutes
  avg_pace_vs_league NUMERIC(4, 1),          -- Differential vs league average

  -- Foul tendencies
  avg_personal_fouls NUMERIC(4, 1),          -- Total fouls called
  avg_free_throw_attempts NUMERIC(4, 1),     -- FTA (correlates with fouls)
  avg_fouls_vs_league NUMERIC(4, 1),         -- Differential

  -- Home/Away bias (for spread analysis, not props)
  home_team_win_pct NUMERIC(4, 2),
  avg_home_margin NUMERIC(4, 1),

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  data_hash STRING                           -- For smart idempotency
)
PARTITION BY calculation_date
CLUSTER BY official_code, season
OPTIONS (
  description = "Rolling referee tendency statistics for game context analysis"
);

-- Index view for quick lookups
CREATE OR REPLACE VIEW `nba_analytics.referee_tendencies_current` AS
SELECT *
FROM `nba_analytics.referee_tendencies`
WHERE calculation_date = (
  SELECT MAX(calculation_date)
  FROM `nba_analytics.referee_tendencies`
)
AND rolling_window_days = 60;  -- Default to 60-day rolling window
```

---

### Task 2: Create Referee Tendencies Processor

**File:** `data_processors/analytics/referee_tendencies/referee_tendencies_processor.py`

**Processor Logic:**

```python
class RefereeTendenciesProcessor(AnalyticsProcessorBase):
    """
    Calculate rolling referee statistics by joining:
    - Referee assignments (who reffed which game)
    - Game results (final scores)
    - Betting lines (for O/U record - optional)
    - Team stats (for pace - optional)

    Runs: Daily, after games complete (overnight batch)
    Output: nba_analytics.referee_tendencies
    """

    ROLLING_WINDOWS = [30, 60, 90, 0]  # 0 = full season

    def calculate_referee_stats(self, official_code: int, window_days: int) -> dict:
        """
        Calculate statistics for one referee over a rolling window.
        """
        query = f"""
        WITH referee_games AS (
          -- Get all games this referee worked
          SELECT DISTINCT
            r.game_id,
            r.game_date,
            r.official_position,
            s.home_score,
            s.away_score,
            (s.home_score + s.away_score) as total_points
          FROM `nba_raw.nbac_referee_game_assignments` r
          JOIN `nba_raw.nbac_scoreboard_v2` s
            ON r.game_id = s.game_id
          WHERE r.official_code = @official_code
            AND s.game_state = 'post'
            AND r.game_date >= DATE_SUB(@calc_date, INTERVAL @window_days DAY)
            AND r.game_date < @calc_date
        ),

        league_avg AS (
          -- League average for comparison
          SELECT
            AVG(home_score + away_score) as league_avg_total
          FROM `nba_raw.nbac_scoreboard_v2`
          WHERE game_state = 'post'
            AND game_date >= DATE_SUB(@calc_date, INTERVAL @window_days DAY)
            AND game_date < @calc_date
        )

        SELECT
          COUNT(*) as games_worked,
          SUM(CASE WHEN official_position = 1 THEN 1 ELSE 0 END) as games_as_chief,
          AVG(total_points) as avg_total_points,
          AVG(total_points) - (SELECT league_avg_total FROM league_avg) as avg_total_points_vs_league,
          STDDEV(total_points) as std_dev_total_points
        FROM referee_games
        """
        # Execute and return results
```

**Key Methods:**

```python
def _calculate_over_under_record(self, official_code: int, window_days: int) -> dict:
    """
    Calculate O/U record by joining with betting lines.

    Returns:
        {
            'games_with_line': int,
            'overs_hit': int,
            'unders_hit': int,
            'pushes': int,
            'over_percentage': float
        }
    """
    query = """
    SELECT
      COUNT(*) as games_with_line,
      SUM(CASE WHEN (home_score + away_score) > total_line THEN 1 ELSE 0 END) as overs,
      SUM(CASE WHEN (home_score + away_score) < total_line THEN 1 ELSE 0 END) as unders,
      SUM(CASE WHEN (home_score + away_score) = total_line THEN 1 ELSE 0 END) as pushes
    FROM referee_games rg
    JOIN betting_lines bl ON rg.game_id = bl.game_id
    WHERE bl.total_line IS NOT NULL
    """

def _calculate_pace_metrics(self, official_code: int, window_days: int) -> dict:
    """
    Calculate pace metrics by joining with team box scores.

    Pace = possessions per 48 minutes
    Approximation: (FGA + 0.44*FTA - ORB + TOV) per team

    Returns:
        {
            'avg_pace': float,
            'avg_pace_vs_league': float
        }
    """

def _calculate_foul_metrics(self, official_code: int, window_days: int) -> dict:
    """
    Calculate foul tendencies from box scores.

    Returns:
        {
            'avg_personal_fouls': float,
            'avg_free_throw_attempts': float,
            'avg_fouls_vs_league': float
        }
    """
```

**Scheduling:**
- Run daily at 11:30 PM ET (after games complete)
- Process all referees who worked in the last 24 hours
- Also refresh any referee scheduled to work tomorrow

---

### Task 3: Create Referee Crew Aggregation View

For predictions, we need **crew-level** tendencies, not just chief referee.

**File:** `schemas/bigquery/analytics/referee_crew_tendencies_view.sql`

```sql
-- ============================================================================
-- Referee Crew Tendencies View
-- Aggregates individual referee stats into crew-level metrics
-- ============================================================================

CREATE OR REPLACE VIEW `nba_analytics.referee_crew_tendencies` AS
WITH upcoming_games AS (
  -- Get referee assignments for upcoming games
  SELECT
    game_id,
    game_date,
    chief_referee_code,
    crew_referee_1_code,
    crew_referee_2_code,
    crew_referee_3_code
  FROM `nba_raw.nbac_referee_game_pivot`
  WHERE game_date >= CURRENT_DATE()
),

crew_stats AS (
  -- Get individual tendencies for each crew member
  SELECT
    ug.game_id,
    ug.game_date,

    -- Chief referee stats (weighted more heavily)
    chief.avg_total_points as chief_avg_points,
    chief.avg_total_points_vs_league as chief_points_vs_league,
    chief.over_percentage as chief_over_pct,
    chief.games_worked as chief_games,

    -- Crew averages
    AVG(crew.avg_total_points) as crew_avg_points,
    AVG(crew.avg_total_points_vs_league) as crew_points_vs_league,
    AVG(crew.over_percentage) as crew_over_pct,

    -- Combined crew games (for confidence)
    chief.games_worked + COALESCE(c1.games_worked, 0) +
    COALESCE(c2.games_worked, 0) + COALESCE(c3.games_worked, 0) as total_crew_games

  FROM upcoming_games ug
  LEFT JOIN `nba_analytics.referee_tendencies_current` chief
    ON ug.chief_referee_code = chief.official_code
  LEFT JOIN `nba_analytics.referee_tendencies_current` c1
    ON ug.crew_referee_1_code = c1.official_code
  LEFT JOIN `nba_analytics.referee_tendencies_current` c2
    ON ug.crew_referee_2_code = c2.official_code
  LEFT JOIN `nba_analytics.referee_tendencies_current` c3
    ON ug.crew_referee_3_code = c3.official_code
  GROUP BY 1, 2, 3, 4, 5, 6, chief.games_worked, c1.games_worked, c2.games_worked, c3.games_worked
)

SELECT
  game_id,
  game_date,

  -- Weighted crew average (chief = 40%, crew = 60% split evenly)
  ROUND(
    0.40 * COALESCE(chief_avg_points, 220) +
    0.60 * COALESCE(crew_avg_points, 220),
    1
  ) as crew_avg_total_points,

  ROUND(
    0.40 * COALESCE(chief_points_vs_league, 0) +
    0.60 * COALESCE(crew_points_vs_league, 0),
    1
  ) as crew_points_vs_league,

  ROUND(
    0.40 * COALESCE(chief_over_pct, 0.50) +
    0.60 * COALESCE(crew_over_pct, 0.50),
    3
  ) as crew_over_percentage,

  total_crew_games,

  -- Confidence flag (need minimum games for reliable stats)
  CASE
    WHEN total_crew_games >= 100 THEN 'HIGH'
    WHEN total_crew_games >= 50 THEN 'MEDIUM'
    ELSE 'LOW'
  END as confidence_level

FROM crew_stats;
```

---

### Task 4: Integrate Into Game Context

**Option A: Add to upcoming_team_game_context (Recommended)**

Modify `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`:

```python
# In extraction phase, add:
self.referee_tendencies = self._load_referee_tendencies()

# Add new method:
def _get_referee_context(self, game_id: str) -> dict:
    """
    Get referee crew tendencies for a game.

    Returns:
        {
            'chief_referee': str,
            'referee_crew_id': str,  # Composite key for crew
            'referee_avg_points_per_game': float,
            'referee_points_vs_league': float,
            'referee_over_percentage': float,
            'referee_confidence': str  # HIGH/MEDIUM/LOW
        }
    """
    query = """
    SELECT
      rp.chief_referee,
      CONCAT(rp.chief_referee_code, '_',
             COALESCE(rp.crew_referee_1_code, 0), '_',
             COALESCE(rp.crew_referee_2_code, 0)) as referee_crew_id,
      rct.crew_avg_total_points as referee_avg_points_per_game,
      rct.crew_points_vs_league as referee_points_vs_league,
      rct.crew_over_percentage as referee_over_percentage,
      rct.confidence_level as referee_confidence
    FROM `nba_raw.nbac_referee_game_pivot` rp
    LEFT JOIN `nba_analytics.referee_crew_tendencies` rct
      ON rp.game_id = rct.game_id
    WHERE rp.game_id = @game_id
    """
```

**Add to output schema:**
```python
ANALYTICS_FIELDS = [
    # ... existing fields ...

    # Referee Context (NEW)
    'chief_referee',
    'referee_crew_id',
    'referee_avg_points_per_game',
    'referee_points_vs_league',
    'referee_over_percentage',
    'referee_confidence',
]
```

**Option B: Add to daily_game_context (Alternative)**

The schema already has placeholder fields:
```sql
referee_crew_id STRING,
chief_referee STRING,
referee_avg_points_per_game NUMERIC(5, 1),
referee_avg_pace NUMERIC(5, 1),
```

Just need to populate them in the processor.

---

### Task 5: Add Referee Adjustment to Composite Factors

**File:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Replace line 217:**
```python
# BEFORE
referee_adj = 0.0

# AFTER
referee_adj = self._calculate_referee_adjustment(player_row_dict)
```

**Add new method:**
```python
def _calculate_referee_adjustment(self, player_row: dict) -> float:
    """
    Calculate point adjustment based on referee crew tendencies.

    Logic:
    - High-scoring ref crews = positive adjustment
    - Low-scoring ref crews = negative adjustment
    - Scale based on player usage (stars affected more)
    - Weight by confidence (more games = more reliable)

    Returns: -2.0 to +2.0 (point adjustment)
    """
    # Get referee context from player row
    # (This requires referee data to flow through player context)
    ref_points_vs_league = player_row.get('referee_points_vs_league', 0) or 0
    ref_confidence = player_row.get('referee_confidence', 'LOW')
    player_usage = player_row.get('avg_usage_rate_last_7_games', 20) or 20

    # No adjustment if we don't have referee data
    if ref_points_vs_league == 0:
        return 0.0

    # === CONFIDENCE WEIGHTING ===
    # Don't trust refs with few games
    confidence_multiplier = {
        'HIGH': 1.0,    # 100+ games, full weight
        'MEDIUM': 0.6,  # 50-99 games, partial weight
        'LOW': 0.3      # <50 games, minimal weight
    }.get(ref_confidence, 0.3)

    # === BASE ADJUSTMENT ===
    # ref_points_vs_league is typically -5 to +5
    # If ref crew averages +4 points vs league, that's significant
    #
    # Distribute extra points based on usage:
    # - 30% usage player gets 30% of extra points
    # - League average ~220 points, so +5 from refs
    # - Star player (30% usage) gets: 5 * 0.30 * (1/2 teams) = 0.75 points

    usage_factor = player_usage / 100  # Convert to decimal
    base_adj = ref_points_vs_league * usage_factor * 0.5  # Half goes to each team

    # Apply confidence weighting
    weighted_adj = base_adj * confidence_multiplier

    # Cap adjustment
    return max(-2.0, min(2.0, weighted_adj))
```

**Update output to include referee context:**
```python
# In the output record builder, add:
'referee_adjustment_context': {
    'referee_points_vs_league': ref_points_vs_league,
    'referee_confidence': ref_confidence,
    'player_usage': player_usage,
    'raw_adjustment': base_adj,
    'confidence_multiplier': confidence_multiplier,
    'final_adjustment': referee_adj
}
```

---

## Data Flow (After Implementation)

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2: Raw Data                                               │
│                                                                 │
│ nbac_referee_game_assignments ───┐                              │
│ nbac_scoreboard_v2 (scores) ─────┼──▶ referee_tendencies_proc   │
│ odds_api_game_lines (totals) ────┘                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 3: Analytics                                              │
│                                                                 │
│ nba_analytics.referee_tendencies (NEW)                          │
│   • Per-referee rolling stats                                   │
│   • Total points, O/U record, pace, fouls                       │
│                                                                 │
│ nba_analytics.referee_crew_tendencies (VIEW)                    │
│   • Aggregated crew-level stats                                 │
│   • Weighted by position (chief vs crew)                        │
│                                                                 │
│ upcoming_team_game_context                                      │
│   • Now includes: referee_avg_points_per_game,                  │
│     referee_points_vs_league, referee_confidence                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 4: Precompute                                             │
│                                                                 │
│ player_composite_factors                                        │
│   • referee_adj now calculated (not 0.0)                        │
│   • Affects total_composite_adjustment                          │
│   • Includes referee_adjustment_context                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 5: Predictions                                            │
│                                                                 │
│ ML models now have referee features                             │
│ Predictions account for ref crew tendencies                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Testing Plan

### Unit Tests

1. **Referee stats calculation**
   - Known referee with 50+ games → verify averages
   - New referee with 5 games → verify low confidence flag
   - Referee with no games → verify graceful handling

2. **Crew aggregation**
   - Full crew (4 refs) → verify weighted average
   - Partial crew (missing refs) → verify fallback to defaults
   - Chief-only → verify 40% weight applied

3. **Adjustment calculation**
   - High-scoring crew (+5 vs league) + high-usage player → positive adj
   - Low-scoring crew (-4 vs league) + low-usage player → small negative adj
   - No referee data → return 0.0

### Integration Tests

1. **Full pipeline**
   - Process date with known referee assignments
   - Verify tendencies calculated correctly
   - Verify adjustment flows to composite factors

2. **Edge cases**
   - Referee assignments not yet announced → graceful handling
   - Game with substitute referee → use available data
   - First game of season → use prior season data

### Validation Queries

```sql
-- Verify referee tendencies populated
SELECT
  official_name,
  games_worked,
  avg_total_points,
  avg_total_points_vs_league,
  over_percentage
FROM nba_analytics.referee_tendencies_current
ORDER BY games_worked DESC
LIMIT 20;

-- Verify crew tendencies for upcoming games
SELECT
  game_id,
  game_date,
  crew_avg_total_points,
  crew_points_vs_league,
  confidence_level
FROM nba_analytics.referee_crew_tendencies
WHERE game_date = CURRENT_DATE();

-- Verify adjustment in composite factors
SELECT
  player_lookup,
  referee_favorability_score,
  total_composite_adjustment
FROM nba_precompute.player_composite_factors
WHERE game_date = CURRENT_DATE()
  AND referee_favorability_score != 0
ORDER BY ABS(referee_favorability_score) DESC
LIMIT 20;
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Referee assignments late (5-6 PM ET) | High | Medium | Run processor twice: early (no refs) + late (with refs) |
| Insufficient historical data | Medium | Medium | Use prior season data; set minimum games threshold |
| Overfitting to small samples | Medium | High | Confidence weighting; minimum 50 games for MEDIUM, 100 for HIGH |
| Referee substitutions game-day | Low | Low | Log warning; use available crew data |
| Pace calculation complexity | Medium | Low | Start with total points only; add pace later |

---

## Rollout Plan

### Phase 1: Development (Day 1-2)
1. Create referee_tendencies schema
2. Build referee_tendencies_processor
3. Create crew aggregation view
4. Unit tests

### Phase 2: Backfill (Day 2-3)
1. Backfill referee tendencies for current season
2. Optionally backfill prior season for new refs
3. Validate data quality

### Phase 3: Integration (Day 3-4)
1. Add referee context to upcoming_team_game_context
2. Add referee adjustment to composite factors
3. Integration tests

### Phase 4: Deployment (Day 4-5)
1. Deploy processor to Cloud Run
2. Add to nightly pipeline (after games complete)
3. Add to pre-game pipeline (after refs announced)
4. Monitor for errors

### Phase 5: Validation (Week 2)
1. Compare predictions with/without referee factor
2. Track accuracy on high-scoring vs low-scoring ref games
3. Tune adjustment formula if needed

---

## Success Criteria

1. ✅ referee_tendencies table populated for all active referees
2. ✅ Crew tendencies available for all games with announced refs
3. ✅ referee_favorability_score non-zero in composite factors
4. ✅ No errors in production pipeline
5. ✅ Backtest shows referee tendencies correlate with game totals

---

## Files to Create/Modify

### New Files
| File | Description |
|------|-------------|
| `schemas/bigquery/analytics/referee_tendencies_tables.sql` | Table + view schemas |
| `data_processors/analytics/referee_tendencies/referee_tendencies_processor.py` | Main processor |
| `data_processors/analytics/referee_tendencies/__init__.py` | Module init |
| `tests/processors/analytics/referee_tendencies/test_unit.py` | Unit tests |

### Modified Files
| File | Changes |
|------|---------|
| `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py` | Add referee context fields |
| `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` | Calculate referee_adj |
| `schemas/bigquery/analytics/upcoming_team_game_context_tables.sql` | Add referee fields to schema |

---

## Appendix A: Sample Referee Data

Based on historical NBA data, here are typical referee tendencies:

| Referee | Games | Avg Total | vs League | Over % |
|---------|-------|-----------|-----------|--------|
| Scott Foster | 1200+ | 218.5 | -2.1 | 47.2% |
| Tony Brothers | 1100+ | 223.1 | +2.5 | 53.8% |
| Ed Malloy | 900+ | 220.8 | +0.2 | 50.5% |
| Kane Fitzgerald | 600+ | 216.4 | -4.2 | 44.1% |

Note: These are illustrative. Actual tendencies should be calculated from your data.

---

## Appendix B: Adjustment Examples

### Example 1: High-Scoring Crew, Star Player
```
Referee crew points vs league: +4.0
Referee confidence: HIGH (120 games)
Player usage rate: 28%

Calculation:
- base_adj = 4.0 * 0.28 * 0.5 = 0.56
- confidence_multiplier = 1.0
- final_adj = 0.56 * 1.0 = +0.56 points

Impact: Player prediction increased by ~0.5 points
```

### Example 2: Low-Scoring Crew, Role Player
```
Referee crew points vs league: -3.5
Referee confidence: MEDIUM (75 games)
Player usage rate: 15%

Calculation:
- base_adj = -3.5 * 0.15 * 0.5 = -0.26
- confidence_multiplier = 0.6
- final_adj = -0.26 * 0.6 = -0.16 points

Impact: Player prediction decreased by ~0.2 points
```

### Example 3: Unknown Crew, Any Player
```
Referee crew points vs league: 0 (no data)
Referee confidence: LOW

Calculation:
- No referee data → return 0.0

Impact: No adjustment (neutral)
```

---

## Reviewer Notes

**Questions for reviewer:**

1. Should we weight chief referee more than 40%? Some argue chief controls the game more.

2. Should referee adjustment be added to fatigue_score (0-100 scale) or kept as separate adjustment?

3. For O/U percentage calculation, should we use opening line or closing line?

4. Should we include prior season data for new referees, or only current season?

5. How to handle playoff games? Referee assignments are different (more experienced crews).

6. Should pace metrics be included in v1, or defer to v2 after validating total points works?

7. Minimum games threshold: 50 for MEDIUM, 100 for HIGH - are these appropriate?
