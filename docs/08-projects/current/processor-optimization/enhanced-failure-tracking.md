# Enhanced Failure Tracking: DNP vs Data Gap Detection

**Created:** 2025-12-09
**Status:** Proposed
**Priority:** Medium
**Related Session:** 86-87

---

## Problem Statement

Currently, when a completeness check fails, we record:
- `failure_category`: 'INCOMPLETE_DATA'
- `failure_reason`: 'Incomplete data across windows'
- `can_retry`: True

**The problem:** We can't distinguish between:

| Type | Example | Correctable? | Action |
|------|---------|--------------|--------|
| **Player DNP** | LaVine out with COVID protocols | No | Accept & document |
| **Data Gap** | Game played but not ingested | Yes | Re-ingest & retry |

This makes triage difficult:
- Dec 31, 2021 had 140 players fail - all due to COVID protocols (permanent)
- If we had a data ingestion bug, it would look identical (correctable)

---

## Proposed Solution

### Phase 1: Schema Enhancements

#### 1.1 Update `precompute_failures` Table (Phase 4)

```sql
-- Add to nba_processing.precompute_failures
ALTER TABLE nba_processing.precompute_failures ADD COLUMN IF NOT EXISTS
  failure_type STRING;  -- 'PLAYER_DNP', 'DATA_GAP', 'PROCESSING_ERROR', 'UNKNOWN'

ALTER TABLE nba_processing.precompute_failures ADD COLUMN IF NOT EXISTS
  is_correctable BOOL;  -- TRUE = can be fixed by re-ingesting data

ALTER TABLE nba_processing.precompute_failures ADD COLUMN IF NOT EXISTS
  expected_game_count INT64;  -- From schedule

ALTER TABLE nba_processing.precompute_failures ADD COLUMN IF NOT EXISTS
  actual_game_count INT64;  -- From player_game_summary

ALTER TABLE nba_processing.precompute_failures ADD COLUMN IF NOT EXISTS
  missing_game_dates STRING;  -- JSON array of missing dates

ALTER TABLE nba_processing.precompute_failures ADD COLUMN IF NOT EXISTS
  raw_data_checked BOOL;  -- Whether we checked raw box scores

ALTER TABLE nba_processing.precompute_failures ADD COLUMN IF NOT EXISTS
  resolution_status STRING;  -- 'UNRESOLVED', 'RESOLVED', 'PERMANENT', 'INVESTIGATING'

ALTER TABLE nba_processing.precompute_failures ADD COLUMN IF NOT EXISTS
  resolved_at TIMESTAMP;  -- When the issue was resolved
```

#### 1.2 Create Phase 3 Failure Table

```sql
CREATE TABLE IF NOT EXISTS nba_processing.analytics_failures (
  processor_name STRING NOT NULL,
  run_id STRING NOT NULL,
  analysis_date DATE NOT NULL,
  entity_id STRING NOT NULL,  -- player_lookup, team_abbr, or game_id
  entity_type STRING NOT NULL,  -- 'PLAYER', 'TEAM', 'GAME'

  -- Failure details
  failure_category STRING NOT NULL,  -- 'MISSING_RAW_DATA', 'PROCESSING_ERROR', 'VALIDATION_FAILED'
  failure_reason STRING NOT NULL,
  failure_type STRING,  -- 'DATA_GAP', 'EXPECTED_NO_DATA', 'BUG'
  is_correctable BOOL,

  -- Context
  expected_record_count INT64,
  actual_record_count INT64,
  missing_game_ids STRING,  -- JSON array

  -- Resolution tracking
  can_retry BOOL NOT NULL,
  resolution_status STRING DEFAULT 'UNRESOLVED',
  resolved_at TIMESTAMP,

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);
```

#### 1.3 Create Phase 5 Failure Table

```sql
CREATE TABLE IF NOT EXISTS nba_processing.prediction_failures (
  processor_name STRING NOT NULL,
  run_id STRING NOT NULL,
  prediction_date DATE NOT NULL,
  entity_id STRING NOT NULL,  -- player_lookup

  -- Failure details
  failure_category STRING NOT NULL,  -- 'MISSING_CACHE', 'STALE_CACHE', 'MODEL_ERROR'
  failure_reason STRING NOT NULL,
  failure_type STRING,  -- 'UPSTREAM_GAP', 'PROCESSING_ERROR'
  is_correctable BOOL,

  -- Upstream dependencies
  missing_upstream_tables STRING,  -- JSON array of missing dependencies
  cache_age_hours FLOAT64,  -- How old the cache was

  -- Resolution tracking
  can_retry BOOL NOT NULL,
  resolution_status STRING DEFAULT 'UNRESOLVED',
  resolved_at TIMESTAMP,

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);
```

---

### Phase 2: Detection Logic

#### 2.1 DNP vs Data Gap Detection Algorithm

```python
def classify_failure(
    player_lookup: str,
    analysis_date: date,
    expected_games: List[date],  # From schedule
    actual_games: List[date],    # From player_game_summary
) -> dict:
    """
    Determine if missing games are due to DNP or data gaps.

    Returns:
        {
            'failure_type': 'PLAYER_DNP' | 'DATA_GAP' | 'MIXED' | 'UNKNOWN',
            'is_correctable': bool,
            'missing_dates': List[date],
            'dnp_dates': List[date],
            'data_gap_dates': List[date],
        }
    """
    missing_dates = set(expected_games) - set(actual_games)

    dnp_dates = []
    data_gap_dates = []

    for missing_date in missing_dates:
        # Check if player appears in raw box score for this date
        raw_exists = check_raw_boxscore_for_player(player_lookup, missing_date)

        if raw_exists:
            # Player was in the game but analytics data missing = DATA_GAP
            data_gap_dates.append(missing_date)
        else:
            # No raw data = Player didn't play = DNP
            dnp_dates.append(missing_date)

    # Classify overall failure
    if len(data_gap_dates) > 0 and len(dnp_dates) == 0:
        failure_type = 'DATA_GAP'
        is_correctable = True
    elif len(dnp_dates) > 0 and len(data_gap_dates) == 0:
        failure_type = 'PLAYER_DNP'
        is_correctable = False
    elif len(data_gap_dates) > 0 and len(dnp_dates) > 0:
        failure_type = 'MIXED'
        is_correctable = True  # Some can be fixed
    else:
        failure_type = 'UNKNOWN'
        is_correctable = None

    return {
        'failure_type': failure_type,
        'is_correctable': is_correctable,
        'missing_dates': list(missing_dates),
        'dnp_dates': dnp_dates,
        'data_gap_dates': data_gap_dates,
    }
```

#### 2.2 Raw Box Score Check

```python
def check_raw_boxscore_for_player(player_lookup: str, game_date: date) -> bool:
    """
    Check if a player appears in raw box score data for a given date.

    This determines if the player actually played (and we're missing data)
    vs the player didn't play (DNP - expected).
    """
    query = f"""
    SELECT COUNT(*) > 0 as player_in_game
    FROM nba_raw.nbac_boxscore_player_traditional
    WHERE game_date = '{game_date}'
      AND player_id IN (
        SELECT player_id
        FROM nba_reference.player_lookup
        WHERE player_lookup = '{player_lookup}'
      )
    """
    result = bq_client.query(query).result()
    return list(result)[0].player_in_game
```

---

### Phase 3: Integration Points

#### 3.1 Completeness Checker Updates

Location: `shared/utils/completeness_checker.py`

```python
def check_completeness_with_classification(
    self,
    player_lookup: str,
    analysis_date: date,
    window_type: str,  # 'games' or 'days'
    window_size: int,
) -> dict:
    """
    Enhanced completeness check that classifies failure type.
    """
    # Existing completeness check
    result = self.check_player_completeness(...)

    if not result['is_complete']:
        # NEW: Classify the failure
        classification = classify_failure(
            player_lookup,
            analysis_date,
            result['expected_games'],
            result['actual_games'],
        )
        result.update(classification)

    return result
```

#### 3.2 PDC Processor Updates

Location: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

Update failure recording to include new fields:
```python
def _record_failure(self, player_lookup: str, failure_info: dict):
    """Record failure with enhanced classification."""
    failure_record = {
        'entity_id': player_lookup,
        'failure_category': failure_info['category'],
        'failure_reason': failure_info['reason'],
        'can_retry': failure_info['can_retry'],
        # NEW fields
        'failure_type': failure_info.get('failure_type', 'UNKNOWN'),
        'is_correctable': failure_info.get('is_correctable'),
        'expected_game_count': failure_info.get('expected_count'),
        'actual_game_count': failure_info.get('actual_count'),
        'missing_game_dates': json.dumps(failure_info.get('missing_dates', [])),
        'raw_data_checked': failure_info.get('raw_data_checked', False),
        'resolution_status': 'UNRESOLVED',
    }
    self.failed_entities.append(failure_record)
```

---

### Phase 4: Queries for Triage

#### Find Correctable Failures

```sql
-- Failures that can be fixed by re-ingesting data
SELECT
  analysis_date,
  COUNT(*) as correctable_failures,
  ARRAY_AGG(DISTINCT entity_id LIMIT 10) as sample_entities
FROM nba_processing.precompute_failures
WHERE failure_type = 'DATA_GAP'
  AND is_correctable = TRUE
  AND resolution_status = 'UNRESOLVED'
GROUP BY analysis_date
ORDER BY analysis_date DESC;
```

#### Find Permanent Failures (DNP)

```sql
-- Failures due to player DNP - no action needed
SELECT
  analysis_date,
  COUNT(*) as dnp_failures
FROM nba_processing.precompute_failures
WHERE failure_type = 'PLAYER_DNP'
  AND is_correctable = FALSE
GROUP BY analysis_date
ORDER BY analysis_date DESC;
```

#### Mark Failures as Resolved

```sql
-- After fixing data gaps, mark as resolved
UPDATE nba_processing.precompute_failures
SET
  resolution_status = 'RESOLVED',
  resolved_at = CURRENT_TIMESTAMP()
WHERE analysis_date = '2021-12-31'
  AND failure_type = 'DATA_GAP'
  AND resolution_status = 'UNRESOLVED';
```

---

## Implementation Plan

### Step 1: Schema Updates (Low Risk)
- Add new columns to `precompute_failures`
- Create new tables for Phase 3 and Phase 5
- All additive, no breaking changes

### Step 2: Detection Logic (Medium Risk)
- Implement `classify_failure()` function
- Add raw box score check
- Unit test with known DNP cases (Dec 2021 COVID)

### Step 3: Integration (Medium Risk)
- Update completeness checker
- Update PDC processor failure recording
- Add to other Phase 4 processors (PCF, MLFS, PSZA, TDZA)

### Step 4: Phase 3 Integration (Low Risk)
- Update PGS processor to record failures
- Update TDGS processor to record failures

### Step 5: Monitoring & Dashboards
- Create alerting for DATA_GAP failures (correctable)
- Create dashboard showing failure breakdown by type

---

## Success Criteria

1. **Accurate Classification**: 95%+ accuracy distinguishing DNP vs DATA_GAP
2. **Automated Triage**: Correctable failures flagged for investigation
3. **Reduced Manual Work**: No need to manually investigate known DNP failures
4. **Clear Resolution Path**: Each failure type has documented resolution steps

---

## Files to Modify

1. `schemas/bigquery/processing/processing_tables.sql` - Schema updates
2. `shared/utils/completeness_checker.py` - Detection logic
3. `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` - PDC integration
4. `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` - PCF integration
5. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` - MLFS integration
6. `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` - PSZA integration
7. `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py` - TDZA integration
8. `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - PGS integration
9. `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py` - TDGS integration

---

## Related Documentation

- [Completeness Failure Guide](../../../02-operations/backfill/completeness-failure-guide.md)
- [Completeness Investigation Findings](./completeness-investigation-findings.md)
