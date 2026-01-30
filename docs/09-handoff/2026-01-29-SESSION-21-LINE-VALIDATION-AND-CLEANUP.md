# Session 21 Handoff - Comprehensive Line Validation and Cleanup

**Date:** 2026-01-29
**Author:** Claude Opus 4.5
**Status:** READY FOR INVESTIGATION
**Priority:** HIGH

---

## Executive Summary

Session 20 fixed the CatBoost V8 regression (predictions clamped at 60) and implemented safeguards. A historical lines audit revealed significant data quality issues that need investigation and cleanup:

- **15,526 total predictions** (Oct 22, 2025 - Jan 29, 2026)
- **Only 45.6% have real prop lines** (has_prop_line = TRUE)
- **156 predictions with sentinel value** (line = 20.0, legacy fake data)
- **7,694 NULL current_points_line** values
- **~2,000 estimated lines** stored as if they were real

This session should thoroughly investigate, validate, and clean up all line data.

---

## Investigation Strategy

### Use Agents Liberally

This investigation requires exploring multiple data sources. Spawn agents in parallel:

```
Task(subagent_type="Explore", prompt="Find how lines flow from odds_api/bettingpros raw tables to predictions")
Task(subagent_type="Explore", prompt="Investigate the 156 sentinel value predictions with line=20.0")
Task(subagent_type="Explore", prompt="Find all places where estimated lines might be stored as actual")
Task(subagent_type="general-purpose", prompt="Create queries to validate predictions against raw data sources")
```

### Investigation Phases

1. **Phase 1**: Understand the data flow (raw → feature store → predictions)
2. **Phase 2**: Validate each prediction against raw sources
3. **Phase 3**: Identify and categorize invalid lines
4. **Phase 4**: Create cleanup scripts
5. **Phase 5**: Add validation to prevent future issues

---

## Data Sources Reference

### Raw Data Tables (Source of Truth)

#### 1. Odds API Props
```
Table: nba_raw.odds_api_player_points_props
Key Fields:
  - game_date DATE
  - player_lookup STRING
  - bookmaker STRING ('draftkings', 'fanduel', 'betmgm', 'pointsbet', 'caesars')
  - points_line FLOAT64 (the actual line)
  - snapshot_timestamp TIMESTAMP
  - data_source STRING ('current', 'historical', 'backfill')

Priority Order: draftkings > fanduel > betmgm > pointsbet > caesars
```

#### 2. BettingPros Props
```
Table: nba_raw.bettingpros_player_points_props
Key Fields:
  - game_date DATE
  - player_lookup STRING
  - bookmaker STRING
  - points_line FLOAT64
  - opening_line FLOAT64
  - bet_side STRING ('over', 'under')
  - is_active BOOLEAN

Note: Only use rows where is_active = TRUE and bet_side = 'over'
```

### Prediction Table Schema

```
Table: nba_predictions.player_prop_predictions
Key Fields for Line Tracking:
  - current_points_line NUMERIC(4,1)  -- The line value used
  - has_prop_line BOOLEAN             -- TRUE = real line exists
  - line_source STRING                -- 'ACTUAL_PROP', 'ESTIMATED_AVG', 'NO_PROP_LINE'
  - line_source_api STRING            -- 'ODDS_API', 'BETTINGPROS', 'ESTIMATED', NULL
  - estimated_line_value NUMERIC(4,1) -- Value if estimated
  - estimation_method STRING          -- 'points_avg_last_5', 'points_avg_last_10', etc.
  - sportsbook STRING                 -- Which book the line came from
  - was_line_fallback BOOLEAN         -- TRUE if line from fallback source
```

---

## Expected Line Values

### What SHOULD Be in current_points_line

| has_prop_line | line_source | line_source_api | current_points_line |
|---------------|-------------|-----------------|---------------------|
| TRUE | ACTUAL_PROP | ODDS_API | Real line from odds_api table |
| TRUE | ACTUAL_PROP | BETTINGPROS | Real line from bettingpros table |
| FALSE | NO_PROP_LINE | NULL | NULL or estimated value |
| FALSE | ESTIMATED_AVG | ESTIMATED | Player's avg (should be in estimated_line_value) |

### What Should NOT Happen

1. **line = 20.0 exactly** - This is a legacy sentinel value, never a real line
2. **line = 15.5 with no raw source** - Possible default value
3. **has_prop_line = TRUE but no raw data exists** - Data integrity issue
4. **line_source = ACTUAL_PROP but line_source_api = ESTIMATED** - Contradiction
5. **current_points_line = season_avg exactly** - Likely fallback misuse

---

## Known Issues from Audit

### Issue 1: Sentinel Value (line = 20.0)
```sql
-- Find all sentinel predictions
SELECT
  game_date,
  player_lookup,
  predicted_points,
  current_points_line,
  line_source,
  line_source_api
FROM nba_predictions.player_prop_predictions
WHERE current_points_line = 20.0
  AND system_id = 'catboost_v8'
ORDER BY game_date
```
**Count:** 156 predictions
**Action:** These should be invalidated or updated with correct lines from raw data

### Issue 2: NULL current_points_line with has_prop_line = FALSE
```sql
-- These are expected when no prop exists, but verify they're correct
SELECT
  game_date,
  COUNT(*) as count,
  COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE current_points_line IS NULL
  AND system_id = 'catboost_v8'
GROUP BY game_date
ORDER BY game_date
```
**Count:** 7,694 predictions
**Action:** Verify these players truly had no prop lines in raw data

### Issue 3: ACTUAL_PROP with NULL line_source_api
```sql
-- These have no API source tracked
SELECT
  game_date,
  player_lookup,
  current_points_line,
  line_source,
  line_source_api
FROM nba_predictions.player_prop_predictions
WHERE line_source = 'ACTUAL_PROP'
  AND line_source_api IS NULL
  AND system_id = 'catboost_v8'
LIMIT 100
```
**Count:** 2,089 predictions
**Action:** Cross-reference with raw tables to identify source

### Issue 4: Inconsistent has_prop_line Flag
```sql
-- Find contradictions
SELECT
  has_prop_line,
  line_source,
  line_source_api,
  COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND game_date >= '2025-10-22'
GROUP BY 1, 2, 3
ORDER BY count DESC
```

---

## Validation Queries

### Query 1: Cross-Reference Predictions with Odds API
```sql
-- Find predictions that claim ACTUAL_PROP but have no odds_api data
WITH predictions AS (
  SELECT
    p.game_date,
    p.player_lookup,
    p.current_points_line,
    p.line_source,
    p.line_source_api
  FROM nba_predictions.player_prop_predictions p
  WHERE p.system_id = 'catboost_v8'
    AND p.has_prop_line = TRUE
    AND p.game_date >= '2025-10-22'
),
odds_api AS (
  SELECT DISTINCT
    game_date,
    player_lookup,
    AVG(points_line) as avg_line
  FROM nba_raw.odds_api_player_points_props
  WHERE game_date >= '2025-10-22'
  GROUP BY game_date, player_lookup
)
SELECT
  p.game_date,
  p.player_lookup,
  p.current_points_line as prediction_line,
  o.avg_line as odds_api_line,
  ABS(p.current_points_line - o.avg_line) as diff
FROM predictions p
LEFT JOIN odds_api o ON p.game_date = o.game_date AND p.player_lookup = o.player_lookup
WHERE o.player_lookup IS NULL OR ABS(p.current_points_line - o.avg_line) > 3
ORDER BY diff DESC NULLS FIRST
LIMIT 100
```

### Query 2: Cross-Reference with BettingPros
```sql
-- Find predictions that claim ACTUAL_PROP but have no bettingpros data
WITH predictions AS (
  SELECT
    p.game_date,
    p.player_lookup,
    p.current_points_line,
    p.line_source_api
  FROM nba_predictions.player_prop_predictions p
  WHERE p.system_id = 'catboost_v8'
    AND p.has_prop_line = TRUE
    AND p.line_source_api = 'BETTINGPROS'
    AND p.game_date >= '2025-10-22'
),
bettingpros AS (
  SELECT DISTINCT
    game_date,
    player_lookup,
    AVG(points_line) as avg_line
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date >= '2025-10-22'
    AND bet_side = 'over'
    AND is_active = TRUE
  GROUP BY game_date, player_lookup
)
SELECT
  p.game_date,
  p.player_lookup,
  p.current_points_line as prediction_line,
  b.avg_line as bettingpros_line,
  ABS(p.current_points_line - b.avg_line) as diff
FROM predictions p
LEFT JOIN bettingpros b ON p.game_date = b.game_date AND p.player_lookup = b.player_lookup
WHERE b.player_lookup IS NULL OR ABS(p.current_points_line - b.avg_line) > 3
ORDER BY diff DESC NULLS FIRST
LIMIT 100
```

### Query 3: Find Players Who Should Have Lines But Don't
```sql
-- Players in raw data but with NULL lines in predictions
WITH raw_lines AS (
  SELECT DISTINCT game_date, player_lookup
  FROM nba_raw.odds_api_player_points_props
  WHERE game_date >= '2025-10-22'
  UNION DISTINCT
  SELECT DISTINCT game_date, player_lookup
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date >= '2025-10-22'
),
predictions AS (
  SELECT game_date, player_lookup, current_points_line, has_prop_line
  FROM nba_predictions.player_prop_predictions
  WHERE system_id = 'catboost_v8'
    AND game_date >= '2025-10-22'
)
SELECT
  r.game_date,
  r.player_lookup,
  p.current_points_line,
  p.has_prop_line
FROM raw_lines r
LEFT JOIN predictions p ON r.game_date = p.game_date AND r.player_lookup = p.player_lookup
WHERE p.has_prop_line = FALSE OR p.current_points_line IS NULL
ORDER BY r.game_date
LIMIT 100
```

---

## Cleanup Procedures

### Step 1: Invalidate Sentinel Values
```sql
-- Mark sentinel value predictions as invalid
UPDATE nba_predictions.player_prop_predictions
SET
  invalidation_reason = 'sentinel_value_20',
  invalidated_at = CURRENT_TIMESTAMP(),
  is_active = FALSE
WHERE current_points_line = 20.0
  AND system_id = 'catboost_v8'
```

### Step 2: Backfill Missing Lines from Raw Data
```sql
-- Create backfill data
CREATE OR REPLACE TABLE nba_predictions.line_backfill AS
WITH predictions_missing AS (
  SELECT
    prediction_id,
    game_date,
    player_lookup,
    current_points_line,
    line_source,
    line_source_api
  FROM nba_predictions.player_prop_predictions
  WHERE system_id = 'catboost_v8'
    AND (current_points_line IS NULL OR current_points_line = 20.0)
    AND game_date >= '2025-10-22'
),
raw_consensus AS (
  SELECT
    game_date,
    player_lookup,
    AVG(points_line) as consensus_line,
    'ODDS_API' as source
  FROM nba_raw.odds_api_player_points_props
  GROUP BY game_date, player_lookup

  UNION ALL

  SELECT
    game_date,
    player_lookup,
    AVG(points_line) as consensus_line,
    'BETTINGPROS' as source
  FROM nba_raw.bettingpros_player_points_props
  WHERE bet_side = 'over' AND is_active = TRUE
  GROUP BY game_date, player_lookup
)
SELECT
  p.prediction_id,
  p.game_date,
  p.player_lookup,
  p.current_points_line as old_line,
  r.consensus_line as new_line,
  r.source as new_source
FROM predictions_missing p
JOIN raw_consensus r ON p.game_date = r.game_date AND p.player_lookup = r.player_lookup
```

### Step 3: Apply Backfill
```sql
-- Apply the backfill (run after reviewing backfill table)
UPDATE nba_predictions.player_prop_predictions p
SET
  current_points_line = b.new_line,
  line_source = 'VEGAS_BACKFILL',
  line_source_api = b.new_source,
  has_prop_line = TRUE,
  updated_at = CURRENT_TIMESTAMP()
FROM nba_predictions.line_backfill b
WHERE p.prediction_id = b.prediction_id
```

---

## Prevention Mechanisms

### 1. Pre-Save Validation
Add validation before saving predictions:
```python
def validate_line_source(prediction):
    """Validate line source consistency"""
    issues = []

    if prediction['has_prop_line'] and prediction['current_points_line'] is None:
        issues.append("has_prop_line=TRUE but current_points_line is NULL")

    if prediction['current_points_line'] == 20.0:
        issues.append("current_points_line=20.0 is sentinel value")

    if prediction['line_source'] == 'ACTUAL_PROP' and prediction['line_source_api'] == 'ESTIMATED':
        issues.append("line_source=ACTUAL_PROP but line_source_api=ESTIMATED")

    return issues
```

### 2. Raw Data Cross-Reference
Before storing a line, verify it exists in raw data:
```python
def verify_line_exists(game_date, player_lookup, line_value):
    """Verify line exists in raw data sources"""
    query = f"""
    SELECT COUNT(*) as count
    FROM (
      SELECT points_line FROM nba_raw.odds_api_player_points_props
      WHERE game_date = '{game_date}' AND player_lookup = '{player_lookup}'
      UNION ALL
      SELECT points_line FROM nba_raw.bettingpros_player_points_props
      WHERE game_date = '{game_date}' AND player_lookup = '{player_lookup}'
    )
    WHERE ABS(points_line - {line_value}) < 0.5
    """
    return execute_query(query) > 0
```

### 3. Daily Validation
Run daily checks (already created in Session 20):
```bash
python monitoring/daily_prediction_quality.py
```

---

## Files to Review

| File | Purpose |
|------|---------|
| `predictions/coordinator/player_loader.py` | Loads lines from raw data |
| `predictions/worker/worker.py` | Creates prediction records with line info |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Extracts Vegas features |
| `bin/audit/audit_historical_lines.py` | Audit script from Session 20 |
| `monitoring/daily_prediction_quality.py` | Daily quality checks |

---

## Agent Investigation Tasks

### Task 1: Trace Line Flow
```
Explore the code to understand exactly how lines flow from raw tables to predictions:
1. How does player_loader.py query odds_api and bettingpros?
2. What's the priority/fallback logic?
3. Where are has_prop_line, line_source, line_source_api set?
4. What happens when no line is found?
```

### Task 2: Investigate Sentinel Values
```
Find where the sentinel value 20.0 could have been introduced:
1. Search for hardcoded 20.0 values
2. Check historical patches or migrations
3. Look at legacy code paths
4. Find when these 156 predictions were created
```

### Task 3: Validate All ACTUAL_PROP Lines
```
For every prediction with line_source='ACTUAL_PROP':
1. Query the raw odds_api table for that date/player
2. Query the raw bettingpros table for that date/player
3. Compare the stored current_points_line to raw values
4. Flag any that differ by more than 1 point
```

### Task 4: Identify Data Gaps
```
Find periods where line data might be incomplete:
1. Compare daily prediction counts to expected (based on games played)
2. Find dates with high NULL line rates
3. Check if raw data collection had outages
4. Correlate with any system changes
```

### Task 5: Create Comprehensive Fix Script
```
Create a Python script that:
1. Queries all problematic predictions
2. Attempts to find correct lines from raw data
3. Logs all discrepancies
4. Generates SQL to fix issues
5. Validates fixes before committing
```

---

## Success Criteria

After this session:
- [ ] All 156 sentinel value predictions invalidated or fixed
- [ ] All ACTUAL_PROP predictions verified against raw data
- [ ] NULL lines validated (confirm no raw data exists)
- [ ] line_source_api populated for all ACTUAL_PROP predictions
- [ ] No contradictions between has_prop_line, line_source, and line_source_api
- [ ] Daily monitoring running to catch future issues
- [ ] Documentation of root causes for each issue type

---

## Key Questions to Answer

1. **Where did the sentinel value 20.0 come from?**
   - Was it a default in legacy code?
   - Was it a migration artifact?

2. **Why do 2,089 ACTUAL_PROP predictions have NULL line_source_api?**
   - Was the field added later?
   - Is there a code path that doesn't set it?

3. **Are the 7,694 NULL lines correct?**
   - Verify these players truly had no prop lines
   - Check if raw data exists but wasn't used

4. **What caused the inconsistent line_source values?**
   - ACTUAL_PROP with ESTIMATED api (24 predictions)
   - ESTIMATED_AVG with ODDS_API api (122 predictions)

---

## Existing Audit Results Reference

From Session 20 audit (`bin/audit/audit_historical_lines.py`):

```
Line Source Breakdown:
  NO_PROP_LINE         | NULL            | 6,000 predictions
  ACTUAL_PROP          | ODDS_API        | 4,033 predictions
  ACTUAL_PROP          | NULL            | 2,089 predictions
  NO_PROP_LINE         | ESTIMATED       | 1,694 predictions
  ACTUAL_PROP          | BETTINGPROS     | 930 predictions
  ESTIMATED_AVG        | ESTIMATED       | 252 predictions
  ACTUAL_PROP          | ODDS_API        | 218 predictions (has_prop=FALSE!)
  NULL                 | NULL            | 155 predictions
  ESTIMATED_AVG        | ODDS_API        | 122 predictions (contradiction!)
  ACTUAL_PROP          | ESTIMATED       | 24 predictions (contradiction!)
  ACTUAL_PROP          | BETTINGPROS     | 5 predictions (has_prop=FALSE!)
  VEGAS_BACKFILL       | NULL            | 4 predictions
```

---

*Created: 2026-01-29*
*Author: Claude Opus 4.5*
