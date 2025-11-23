# Historical Dependency Checking - Implementation Plan

**Date:** 2025-11-22
**Status:** Implementation Required Before Deployment
**Priority:** BLOCKER - Required for backfill and production deployment

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Query Pattern Analysis](#query-pattern-analysis)
3. [Solution Design](#solution-design)
4. [Implementation Details](#implementation-details)
5. [Schema Changes](#schema-changes)
6. [Code Changes](#code-changes)
7. [Testing Strategy](#testing-strategy)

---

## Problem Statement

### User Requirement

> "I can't launch the system without backfilled data, and I need the dependency check to work or whatever checks historical data so that I can ensure that all the dates that depend on previous dates are working"

### Current Implementation Gap

**What we have**:
- Point-in-time hash extraction: Gets `data_hash` from most recent upstream record
- Compares to stored hash to decide if reprocessing needed

**What's missing**:
- Detection of changes across historical window (last N games/days)
- Ability to detect backfills of games in middle of window
- Guarantee that ALL historical dependencies are checked

### Impact

**Without proper historical checking**:
- ❌ Cannot confidently backfill 4 seasons of data
- ❌ May miss corrections to historical games
- ❌ Cannot guarantee data consistency across dependent dates
- ❌ **BLOCKER for production deployment**

---

## Query Pattern Analysis

### Processor 1: team_defense_zone_analysis

**Calculation Query** (line 387-402 in processor):
```sql
WITH ranked_games AS (
    SELECT *,
      ROW_NUMBER() OVER (
        PARTITION BY defending_team_abbr
        ORDER BY game_date DESC
      ) as game_rank
    FROM `nba_analytics.team_defense_game_summary`
    WHERE game_date <= '{analysis_date}'
      AND game_date >= '{season_start_date}'
)
SELECT *
FROM ranked_games
WHERE game_rank <= 15  -- LAST 15 GAMES per team
ORDER BY defending_team_abbr, game_date DESC
```

**Key Insights**:
1. Uses `ROW_NUMBER()` to get last N games **per entity** (team)
2. Not a fixed date range - varies by entity's game schedule
3. Window size: 15 games
4. Entity field: `defending_team_abbr`

**Historical Dependency**:
- Output for analysis_date=Nov 15 depends on last 15 games **per team**
- For LAL: might be games from Nov 1, 3, 5, 7... (15 games)
- For GSW: might be games from Oct 30, Nov 1, 3... (15 games, different dates)

**Change Detection Required**:
- If ANY of LAL's last 15 games' `data_hash` or `processed_at` changes → Reprocess
- If ANY of GSW's last 15 games changes → Reprocess

---

### Processor 2: player_shot_zone_analysis

**Similar pattern**:
```sql
WITH ranked_games AS (
    SELECT *,
      ROW_NUMBER() OVER (
        PARTITION BY player_lookup
        ORDER BY game_date DESC
      ) as game_rank
    FROM `nba_analytics.player_game_summary`
    WHERE game_date <= '{analysis_date}'
)
SELECT *
FROM ranked_games
WHERE game_rank <= 10  -- LAST 10 GAMES per player
```

**Historical Dependency**:
- Window size: 10 games (primary), 20 games (trend)
- Entity field: `player_lookup`
- Same logic as team processor

---

### Processor 3: player_daily_cache

**Multiple windows**:
```sql
-- L5 average
WHERE game_rank <= 5

-- L10 average
WHERE game_rank <= 10

-- L7 days fatigue
WHERE game_date BETWEEN DATE_SUB(cache_date, INTERVAL 7 DAY) AND cache_date

-- L14 days fatigue
WHERE game_date BETWEEN DATE_SUB(cache_date, INTERVAL 14 DAY) AND cache_date

-- Season stats
WHERE game_date >= season_start_date AND game_date <= cache_date
```

**Historical Dependency**:
- Multiple window types: game count (L5, L10) AND date range (L7, L14)
- Entity field: `player_lookup`
- Most complex dependency pattern

---

### Processor 4 & 5: player_composite_factors, ml_feature_store

**Cascade pattern**:
- Depend on Phase 4 processors (not Phase 3 directly)
- Inherit historical dependencies from upstream
- Use point-in-time dependencies on Phase 4 output

**Solution**: These work fine with point-in-time hash checking since they depend on Phase 4 tables that already incorporate historical data.

---

## Solution Design

### Approach: "Historical Window Fingerprint"

**Concept**: For each entity (team/player), track the MAX(processed_at) across ALL games in the historical window.

**Why This Works**:
1. Detects ANY change to ANY game in window
2. Handles variable window sizes per entity
3. Works for both game-count windows (L10, L15) and date windows (L7, L14)
4. Simple to implement and understand

### Schema Addition

Add to each Phase 4 processor's output:

```sql
-- For each upstream source with historical dependency
source_{prefix}_window_start_date DATE,           -- First game date in window
source_{prefix}_window_end_date DATE,             -- Last game date in window
source_{prefix}_window_games_count INT64,         -- Number of games in window
source_{prefix}_window_last_updated TIMESTAMP     -- MAX(processed_at) across all games in window
```

**Example for team_defense_zone_analysis**:
```sql
-- Current fields (keep these)
source_team_defense_hash STRING,                  -- Hash from most recent game
source_team_defense_last_updated TIMESTAMP,       -- When most recent game processed

-- NEW fields
source_team_defense_window_start_date DATE,       -- First of L15 games
source_team_defense_window_end_date DATE,         -- Last of L15 games
source_team_defense_window_games_count INT64,     -- Should be 15 (or less early season)
source_team_defense_window_last_updated TIMESTAMP -- MAX(processed_at) from all L15 games
```

---

### Code Pattern

#### Step 1: Extract Historical Window Metadata

```python
def _extract_source_hash_with_window_metadata(self, analysis_date: date) -> dict:
    """
    Extract hash AND historical window metadata from upstream table.

    Returns dict with:
    - most_recent_hash: Hash from most recent game (for current logic)
    - window_start_date: First game in window
    - window_end_date: Last game in window
    - window_games_count: Number of games in window
    - window_last_updated: MAX(processed_at) across all games in window
    """
    query = f"""
    WITH ranked_games AS (
        SELECT
            data_hash,
            game_date,
            processed_at,
            ROW_NUMBER() OVER (
                PARTITION BY defending_team_abbr
                ORDER BY game_date DESC
            ) as game_rank
        FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
        WHERE game_date <= '{analysis_date}'
          AND game_date >= '{self.season_start_date}'
          AND defending_team_abbr = '{entity_id}'  -- For specific team
    ),
    window_games AS (
        SELECT *
        FROM ranked_games
        WHERE game_rank <= {self.min_games_required}  -- 15
    )
    SELECT
        -- Most recent hash (for current logic)
        (SELECT data_hash FROM window_games ORDER BY game_date DESC LIMIT 1) as most_recent_hash,

        -- Window metadata
        MIN(game_date) as window_start_date,
        MAX(game_date) as window_end_date,
        COUNT(*) as window_games_count,
        MAX(processed_at) as window_last_updated  -- CRITICAL: detects ANY change in window
    FROM window_games
    """

    result = self.bq_client.query(query).to_dataframe()

    if result.empty:
        return {
            'most_recent_hash': None,
            'window_start_date': None,
            'window_end_date': None,
            'window_games_count': 0,
            'window_last_updated': None
        }

    row = result.iloc[0]
    return {
        'most_recent_hash': row['most_recent_hash'],
        'window_start_date': row['window_start_date'],
        'window_end_date': row['window_end_date'],
        'window_games_count': int(row['window_games_count']),
        'window_last_updated': row['window_last_updated']
    }
```

#### Step 2: Store Window Metadata in Output

```python
def calculate_precompute(self) -> None:
    """Calculate team defense zone metrics."""

    for team_abbr in all_teams:
        # Extract window metadata for this team
        window_metadata = self._extract_source_hash_with_window_metadata(
            analysis_date=self.opts['analysis_date'],
            entity_id=team_abbr
        )

        # Calculate business logic...
        zone_metrics = self._calculate_zone_defense(team_data, games_count)

        # Build record
        record = {
            # Business fields...
            'team_abbr': team_abbr,
            'analysis_date': self.opts['analysis_date'],
            'paint_pct_allowed_last_15': zone_metrics['paint_pct'],
            # ... all other metrics

            # Current source tracking (keep these)
            'source_team_defense_hash': window_metadata['most_recent_hash'],
            'source_team_defense_last_updated': window_metadata['window_last_updated'],
            'source_team_defense_rows_found': window_metadata['window_games_count'],
            'source_team_defense_completeness_pct':
                (window_metadata['window_games_count'] / self.min_games_required) * 100,

            # NEW: Historical window tracking
            'source_team_defense_window_start_date': window_metadata['window_start_date'],
            'source_team_defense_window_end_date': window_metadata['window_end_date'],
            'source_team_defense_window_games_count': window_metadata['window_games_count'],
            'source_team_defense_window_last_updated': window_metadata['window_last_updated'],

            # Data hash
            'data_hash': self.compute_data_hash(record)
        }

        self.transformed_data.append(record)
```

#### Step 3: Check Historical Window for Changes

```python
def should_reprocess_entity(
    self,
    entity_id: str,
    analysis_date: date
) -> bool:
    """
    Determine if entity needs reprocessing based on historical window changes.

    Args:
        entity_id: Team/player identifier
        analysis_date: Date to check

    Returns:
        bool: True if reprocessing needed
    """
    # Get existing record
    existing = self.get_existing_record(entity_id, analysis_date)

    if not existing:
        logger.info(f"{entity_id}: No existing record - must process")
        return True

    # Extract current window metadata
    current_window = self._extract_source_hash_with_window_metadata(
        analysis_date=analysis_date,
        entity_id=entity_id
    )

    # Check 1: Window composition changed (games added/removed)
    if current_window['window_games_count'] != existing.get('source_team_defense_window_games_count'):
        logger.info(
            f"{entity_id}: Window size changed "
            f"({existing.get('source_team_defense_window_games_count')} → "
            f"{current_window['window_games_count']}) - reprocessing"
        )
        return True

    # Check 2: Window date range changed
    if (current_window['window_start_date'] != existing.get('source_team_defense_window_start_date') or
        current_window['window_end_date'] != existing.get('source_team_defense_window_end_date')):
        logger.info(
            f"{entity_id}: Window date range changed - reprocessing"
        )
        return True

    # Check 3: ANY game in window was updated (CRITICAL CHECK)
    existing_window_updated = existing.get('source_team_defense_window_last_updated')
    current_window_updated = current_window['window_last_updated']

    if existing_window_updated is None:
        logger.warning(f"{entity_id}: No existing window timestamp - reprocessing")
        return True

    if current_window_updated > existing_window_updated:
        logger.info(
            f"{entity_id}: Historical window updated "
            f"({existing_window_updated} → {current_window_updated}) - reprocessing"
        )
        return True

    # Check 4: Output hash changed (safety check)
    current_hash = self.compute_data_hash(existing)
    if current_hash != existing.get('data_hash'):
        logger.info(f"{entity_id}: Output hash mismatch - reprocessing")
        return True

    # All checks passed - safe to skip
    logger.info(
        f"{entity_id}: Window unchanged "
        f"({current_window['window_games_count']} games, "
        f"last updated {current_window_updated}) - skipping"
    )
    return False
```

---

## Implementation Details

### Phase 4 Processor Requirements

| Processor | Window Type | Window Size | Entity Field | Source Table |
|-----------|-------------|-------------|--------------|--------------|
| team_defense_zone_analysis | Game count | 15 games | defending_team_abbr | team_defense_game_summary |
| player_shot_zone_analysis | Game count | 10/20 games | player_lookup | player_game_summary |
| player_daily_cache | Mixed | L5/L7/L10/L14 | player_lookup | Multiple (player_game_summary, team_offense_game_summary) |
| player_composite_factors | Cascade | N/A | player_lookup | Phase 4 tables (point-in-time OK) |
| ml_feature_store | Cascade | N/A | player_lookup | Phase 4 tables (point-in-time OK) |

**Implementation Priority**:
1. **team_defense_zone_analysis** - Single window, 15 games ⭐ START HERE
2. **player_shot_zone_analysis** - Two windows (L10, L20) ⭐
3. **player_daily_cache** - Multiple mixed windows ⭐⭐ MOST COMPLEX
4. **player_composite_factors** - Point-in-time OK (no changes needed)
5. **ml_feature_store** - Point-in-time OK (no changes needed)

---

## Schema Changes

### For Each Processor with Historical Windows

**Add 4 columns per upstream source**:

```sql
ALTER TABLE `nba_precompute.team_defense_zone_analysis`
ADD COLUMN IF NOT EXISTS source_team_defense_window_start_date DATE
  OPTIONS (description="First game date in L15 window"),
ADD COLUMN IF NOT EXISTS source_team_defense_window_end_date DATE
  OPTIONS (description="Last game date in L15 window"),
ADD COLUMN IF NOT EXISTS source_team_defense_window_games_count INT64
  OPTIONS (description="Number of games in L15 window (should be 15 mid-season)"),
ADD COLUMN IF NOT EXISTS source_team_defense_window_last_updated TIMESTAMP
  OPTIONS (description="MAX(processed_at) across all L15 games - detects ANY historical change");
```

**Apply to**:
1. ✅ team_defense_zone_analysis (1 source × 4 fields = 4 new columns)
2. ✅ player_shot_zone_analysis (1 source × 4 fields = 4 new columns)
3. ⚠️ player_daily_cache (4 sources × 4 fields = 16 new columns!)

**Total new columns**: 24 across 3 processors

---

## Code Changes

### Changes Required Per Processor

**1. Update `_extract_source_hash()` method**:
- Change return type from `None` to storing window metadata
- Query to include window aggregations (MIN, MAX, COUNT, MAX(processed_at))
- Store in instance attributes: `self.source_window_*`

**2. Update `calculate_precompute()` record building**:
- Add 4 new fields to each output record
- Map from instance attributes

**3. Add `should_reprocess_entity()` method**:
- Query existing record
- Compare window metadata
- Return boolean decision

**4. Update `extract_raw_data()` or `calculate_precompute()`**:
- Call `should_reprocess_entity()` for each entity
- Skip processing if returns False
- Track skip stats

**Example file changes**:
```
data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py
- Line 513-528: Update _extract_source_hash()
- Line 571-638: Update calculate_precompute() record building
- New method: should_reprocess_entity()
- Line 530-568: Add skip logic in calculate_precompute()
```

---

## Testing Strategy

### Unit Tests

**Test 1: Window Metadata Extraction**
```python
def test_extract_source_hash_with_window_metadata():
    """Test window metadata extraction for L15 games."""
    processor = TeamDefenseZoneAnalysisProcessor()

    # Mock BigQuery data: 15 games for LAL
    metadata = processor._extract_source_hash_with_window_metadata(
        analysis_date=date(2024, 11, 15),
        entity_id='LAL'
    )

    assert metadata['window_games_count'] == 15
    assert metadata['window_start_date'] == date(2024, 11, 1)
    assert metadata['window_end_date'] == date(2024, 11, 15)
    assert metadata['window_last_updated'] is not None
```

**Test 2: Skip Logic - Window Unchanged**
```python
def test_should_reprocess_entity_window_unchanged():
    """Test skip when historical window unchanged."""
    processor = TeamDefenseZoneAnalysisProcessor()

    # Mock existing record with window metadata
    existing = {
        'team_abbr': 'LAL',
        'analysis_date': date(2024, 11, 15),
        'source_team_defense_window_games_count': 15,
        'source_team_defense_window_start_date': date(2024, 11, 1),
        'source_team_defense_window_end_date': date(2024, 11, 15),
        'source_team_defense_window_last_updated': datetime(2024, 11, 15, 10, 0, 0)
    }

    # Mock current window (same as existing)
    # ... mock BigQuery to return same window

    should_process = processor.should_reprocess_entity('LAL', date(2024, 11, 15))

    assert should_process == False  # Should skip
```

**Test 3: Reprocess - Historical Game Updated**
```python
def test_should_reprocess_entity_historical_game_updated():
    """Test reprocess when game in middle of window updated."""
    processor = TeamDefenseZoneAnalysisProcessor()

    # Mock existing record processed at 10:00 AM
    existing = {
        'team_abbr': 'LAL',
        'source_team_defense_window_last_updated': datetime(2024, 11, 15, 10, 0, 0)
    }

    # Mock current window: Game from Nov 5 was backfilled at 11:00 AM
    # MAX(processed_at) across L15 games = Nov 15, 11:00 AM (newer!)
    # ... mock BigQuery

    should_process = processor.should_reprocess_entity('LAL', date(2024, 11, 15))

    assert should_process == True  # Should reprocess
```

### Integration Tests

**Test 4: Full Backfill Scenario**
```python
def test_backfill_4_seasons_dependency_detection():
    """Test historical dependency checking during backfill."""

    # Scenario: Backfill October 2020 season
    # Day 1: Process Oct 20 (3 games per team)
    # Day 10: Process Oct 29 (8 games per team)
    # Day 20: Process Nov 8 (15 games per team)
    # Then: Backfill correction to Oct 25 game
    # Verify: Nov 8 reprocesses (Oct 25 in L15 window)

    # ... detailed test implementation
```

---

## Rollout Plan

### Phase 1: Implement team_defense_zone_analysis (4 hours)

**Steps**:
1. ✅ Add 4 schema columns (30 min)
2. ✅ Update `_extract_source_hash()` method (1 hour)
3. ✅ Update record building (30 min)
4. ✅ Add `should_reprocess_entity()` method (1 hour)
5. ✅ Add unit tests (1 hour)

**Verification**:
- Deploy to dev environment
- Run for 1 date
- Verify 4 new columns populate
- Verify window metadata correct (start/end dates, game count)

### Phase 2: Implement player_shot_zone_analysis (3 hours)

**Similar to Phase 1, slightly faster** (copy pattern from team processor)

### Phase 3: Implement player_daily_cache (6 hours)

**More complex** - 4 sources with multiple window types:
- player_game_summary: L5, L10, season window
- team_offense_game_summary: L10 window
- upcoming_player_game_context: point-in-time (no window)
- player_shot_zone_analysis: depends on Phase 4 (point-in-time)

**Approach**: Create separate window metadata for each source with historical dependency

### Phase 4: Testing & Validation (4 hours)

**Test scenarios**:
1. New date (no existing record) → processes
2. Existing date, window unchanged → skips
3. Existing date, recent game updated → processes
4. Existing date, historical game (middle of window) updated → processes
5. Backfill scenario with gaps

### Phase 5: Documentation (2 hours)

**Update docs**:
- Dependency tracking strategy document
- Backfill operations guide
- Monitoring queries

---

## Estimated Timeline

| Task | Time | Status |
|------|------|--------|
| Schema updates (3 processors) | 1 hour | Pending |
| Code: team_defense_zone_analysis | 4 hours | Pending |
| Code: player_shot_zone_analysis | 3 hours | Pending |
| Code: player_daily_cache | 6 hours | Pending |
| Unit tests | 3 hours | Pending |
| Integration tests | 3 hours | Pending |
| Documentation | 2 hours | Pending |
| **TOTAL** | **22 hours** (~3 days) | **Pending** |

---

## Success Criteria

### Before Deployment

- ✅ All 3 processors have window metadata extraction
- ✅ All 3 processors have skip logic based on window changes
- ✅ Unit tests pass for window metadata extraction
- ✅ Unit tests pass for skip logic (3 scenarios each)
- ✅ Integration test passes for backfill scenario
- ✅ Dev environment runs show:
  - Window columns populate correctly
  - Skip rates match expectations (~70% mid-season)
  - Backfill corrections trigger reprocessing

### After Deployment (Monitoring)

- Monitor skip rates:
  - Early season: 5-10% (lots of changes)
  - Mid-season: 60-80% (stable)
  - Playoffs: 10-20% (frequent corrections)

- Monitor reprocessing triggers:
  - Log WHY each reprocess happened (which check triggered)
  - Verify historical backfills are detected

- Validate data consistency:
  - No unexplained data changes
  - Historical corrections propagate correctly

---

## Decision Point

**User must decide**:

1. **Implement before deployment?** (22 hours, ~3 days)
   - ✅ Guarantees historical dependency checking works
   - ✅ Enables confident backfill
   - ✅ Required for production readiness
   - ❌ Delays deployment by 3 days

2. **Deploy without it?** (Not recommended given user's requirement)
   - ❌ Cannot guarantee backfill works correctly
   - ❌ May miss historical updates
   - ❌ User explicitly stated this is required

**Recommendation**: **Implement before deployment** (Option 1)

This is a deployment blocker per user's requirement: "I can't launch the system without backfilled data, and I need the dependency check to work."

---

## Next Steps

1. **User approval** of this implementation plan
2. **Start with Phase 1** (team_defense_zone_analysis schema + code)
3. **Test Phase 1** in isolation before moving to Phase 2
4. **Iterate** through all 3 processors
5. **Full integration test** with backfill scenario
6. **Deploy** with confidence

**Ready to begin implementation** upon user approval.
