# Historical Dependency Checking - Query-Based Approach (No Schema Changes)

**Date:** 2025-11-22
**Status:** Recommended Approach
**Priority:** BLOCKER - Required for backfill

---

## Two Different Problems

### Problem 1: Missing Dates (Pattern 09 handles this)
- **What**: Entire dates missing from history (gap detection)
- **Example**: Nov 15 data completely missing
- **Solution**: Pattern 09 Smart Backfill Detection (auto-queue backfill)
- **Schema**: No changes needed

### Problem 2: Historical Window Changes (THIS document)
- **What**: Data within L10/L15 window was updated/corrected
- **Example**: Nov 5 game (in L15 window) was corrected
- **Solution**: Detect changes, reprocess dependent dates
- **Schema**: **NO CHANGES NEEDED!** ✅

---

## The Right Solution: Query-Based Detection

**User's insight**: "I thought the backfill check would not be schema related"

**You're right!** We don't need new columns. We can detect historical changes using queries.

### How It Works

#### Current Approach (Point-in-Time)
```python
# Extract hash from MOST RECENT game only
query = """
SELECT data_hash
FROM upstream_table
WHERE game_date <= analysis_date
ORDER BY processed_at DESC
LIMIT 1  -- Only 1 record!
"""
```

#### New Approach (Historical Window) - NO SCHEMA CHANGES
```python
# Query MAX(processed_at) across ALL games in L15 window
def should_reprocess_entity(entity_id, analysis_date):
    """Check if ANY game in L15 window changed."""

    # Get our existing record
    existing = get_existing_record(entity_id, analysis_date)
    if not existing:
        return True  # No record, must process

    our_processed_at = existing['processed_at']  # When WE last ran

    # Query upstream: MAX(processed_at) across L15 window
    query = f"""
    WITH ranked_games AS (
        SELECT
            processed_at,
            ROW_NUMBER() OVER (
                PARTITION BY defending_team_abbr
                ORDER BY game_date DESC
            ) as game_rank
        FROM `nba_analytics.team_defense_game_summary`
        WHERE game_date <= '{analysis_date}'
          AND game_date >= '{season_start}'
          AND defending_team_abbr = '{entity_id}'
    )
    SELECT MAX(processed_at) as window_last_updated
    FROM ranked_games
    WHERE game_rank <= 15  -- L15 window
    """

    result = bq_client.query(query).to_dataframe()
    window_last_updated = result['window_last_updated'].iloc[0]

    # Compare: If ANY game in L15 was updated after we ran, reprocess
    if window_last_updated > our_processed_at:
        logger.info(f"{entity_id}: Historical window updated, reprocessing")
        return True
    else:
        logger.info(f"{entity_id}: Window unchanged, skipping")
        return False
```

**That's it!** No schema changes. Just smarter queries.

---

## Implementation Details

### Step 1: Add Method to Each Processor

```python
# data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py

def _check_historical_window_unchanged(
    self,
    entity_id: str,
    analysis_date: date
) -> bool:
    """
    Check if historical window (L15 games) unchanged since last processing.

    Returns:
        bool: True if unchanged (safe to skip), False if changed (must reprocess)
    """
    # Get existing record
    existing_query = f"""
    SELECT processed_at
    FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
    WHERE team_abbr = '{entity_id}'
      AND analysis_date = DATE('{analysis_date}')
    LIMIT 1
    """

    existing_result = self.bq_client.query(existing_query).to_dataframe()

    if existing_result.empty:
        logger.info(f"{entity_id}: No existing record")
        return False  # Must process

    our_processed_at = existing_result['processed_at'].iloc[0]

    # Query upstream: MAX(processed_at) across L15 window
    window_query = f"""
    WITH ranked_games AS (
        SELECT
            processed_at,
            ROW_NUMBER() OVER (
                PARTITION BY defending_team_abbr
                ORDER BY game_date DESC
            ) as game_rank
        FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
        WHERE game_date <= DATE('{analysis_date}')
          AND game_date >= DATE('{self.season_start_date}')
          AND defending_team_abbr = '{entity_id}'
          AND processed_at IS NOT NULL
    )
    SELECT MAX(processed_at) as window_last_updated
    FROM ranked_games
    WHERE game_rank <= {self.min_games_required}  -- 15
    """

    window_result = self.bq_client.query(window_query).to_dataframe()

    if window_result.empty or window_result['window_last_updated'].iloc[0] is None:
        logger.warning(f"{entity_id}: No window data found")
        return False  # Must process (data might be new)

    window_last_updated = window_result['window_last_updated'].iloc[0]

    # Compare timestamps
    if window_last_updated > our_processed_at:
        logger.info(
            f"{entity_id}: Window updated "
            f"(upstream: {window_last_updated}, ours: {our_processed_at}) - reprocessing"
        )
        return False  # Must reprocess

    # Window unchanged
    logger.info(
        f"{entity_id}: Window unchanged since {our_processed_at} - skipping"
    )
    return True  # Safe to skip
```

### Step 2: Use in calculate_precompute()

```python
def calculate_precompute(self) -> None:
    """Calculate team defense zone metrics."""

    all_teams = self.team_mapper.get_all_active_teams()

    for team_abbr in all_teams:
        # Check if we can skip this team
        if self._check_historical_window_unchanged(team_abbr, self.opts['analysis_date']):
            logger.info(f"{team_abbr}: Skipping (window unchanged)")
            self.stats['teams_skipped'] = self.stats.get('teams_skipped', 0) + 1
            continue

        # Process this team
        team_data = self.raw_data[self.raw_data['defending_team_abbr'] == team_abbr]

        if len(team_data) < self.min_games_required:
            # Handle insufficient data...
            continue

        # Calculate metrics...
        zone_metrics = self._calculate_zone_defense(team_data, len(team_data))

        # Build record...
        record = {
            'team_abbr': team_abbr,
            'analysis_date': self.opts['analysis_date'],
            # ... all metrics
        }

        self.transformed_data.append(record)
        self.successful.append(team_abbr)

    logger.info(
        f"Processed {len(self.successful)} teams, "
        f"skipped {self.stats.get('teams_skipped', 0)} (window unchanged)"
    )
```

---

## Advantages of Query-Based Approach

### ✅ No Schema Changes
- Don't need to add 24 new columns
- No ALTER TABLE statements
- No schema migration

### ✅ Simpler Implementation
- One method per processor (~50 lines)
- Uses existing `processed_at` column
- No new metadata to track

### ✅ Accurate
- Detects ANY change to ANY game in window
- Handles corrections to historical data
- Works for backfill scenario

### ✅ Flexible
- Easy to adjust window size (just change WHERE clause)
- Works for game-count windows (L10, L15) and date windows (L7, L14)
- No schema locked in

### ⚠️ Query Cost
- One extra query per entity per run
- ~30 teams × 1 query = 30 queries for team processor
- ~450 players × 1 query = 450 queries for player processor
- **Cost**: ~$0.001 per run (negligible)

---

## Comparison: Schema vs Query Approach

| Aspect | Schema Approach | Query Approach ⭐ |
|--------|----------------|------------------|
| **Schema changes** | 24 new columns | 0 changes |
| **Implementation** | 300 lines/processor | 50 lines/processor |
| **Query cost** | Low (cached metadata) | Slightly higher (~$0.001/run) |
| **Flexibility** | Locked into schema | Easy to adjust |
| **Accuracy** | Same | Same |
| **Complexity** | High | Low |
| **Time to implement** | 3 days | 4-6 hours |

**Recommendation**: **Query Approach** ✅

---

## Implementation Plan (Query-Based)

### Phase 1: team_defense_zone_analysis (2 hours)

**Changes needed**:
1. Add `_check_historical_window_unchanged()` method (1 hour)
2. Update `calculate_precompute()` to use skip logic (30 min)
3. Add unit tests (30 min)

**No schema changes**

### Phase 2: player_shot_zone_analysis (1.5 hours)

**Copy pattern from Phase 1**, adjust for:
- Entity field: `player_lookup` instead of `team_abbr`
- Window size: 10/20 games
- Upstream table: `player_game_summary`

### Phase 3: player_daily_cache (3 hours)

**More complex** - multiple windows:
- L5 games: Check MAX(processed_at) for last 5 games
- L10 games: Check MAX(processed_at) for last 10 games
- L7 days: Check MAX(processed_at) for last 7 days
- L14 days: Check MAX(processed_at) for last 14 days

**Approach**: Check each window separately, reprocess if ANY changed

### Total Timeline

| Task | Time | Cumulative |
|------|------|------------|
| team_defense_zone_analysis | 2 hours | 2 hours |
| player_shot_zone_analysis | 1.5 hours | 3.5 hours |
| player_daily_cache | 3 hours | 6.5 hours |
| Integration tests | 1.5 hours | 8 hours |
| Documentation | 1 hour | 9 hours |
| **TOTAL** | **9 hours** | **~1.5 days** |

**vs Schema Approach**: 22 hours (~3 days)

**Savings**: 13 hours, no schema migration!

---

## Example Queries

### Query 1: Team Defense (L15 window)

```sql
-- Check if LAL's last 15 games changed since we last processed
WITH our_record AS (
    SELECT processed_at as our_timestamp
    FROM `nba_precompute.team_defense_zone_analysis`
    WHERE team_abbr = 'LAL'
      AND analysis_date = '2024-11-22'
),
upstream_window AS (
    SELECT
        processed_at,
        ROW_NUMBER() OVER (
            PARTITION BY defending_team_abbr
            ORDER BY game_date DESC
        ) as game_rank
    FROM `nba_analytics.team_defense_game_summary`
    WHERE game_date <= '2024-11-22'
      AND game_date >= '2024-10-20'
      AND defending_team_abbr = 'LAL'
),
window_max AS (
    SELECT MAX(processed_at) as upstream_timestamp
    FROM upstream_window
    WHERE game_rank <= 15
)
SELECT
    o.our_timestamp,
    w.upstream_timestamp,
    CASE
        WHEN w.upstream_timestamp > o.our_timestamp THEN 'REPROCESS'
        ELSE 'SKIP'
    END as decision
FROM our_record o
CROSS JOIN window_max w;
```

### Query 2: Player Shot Zone (L10 window)

```sql
-- Check if LeBron's last 10 games changed
WITH our_record AS (
    SELECT processed_at as our_timestamp
    FROM `nba_precompute.player_shot_zone_analysis`
    WHERE player_lookup = 'lebronjames'
      AND analysis_date = '2024-11-22'
),
upstream_window AS (
    SELECT
        processed_at,
        ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY game_date DESC
        ) as game_rank
    FROM `nba_analytics.player_game_summary`
    WHERE game_date <= '2024-11-22'
      AND player_lookup = 'lebronjames'
),
window_max AS (
    SELECT MAX(processed_at) as upstream_timestamp
    FROM upstream_window
    WHERE game_rank <= 10
)
SELECT
    o.our_timestamp,
    w.upstream_timestamp,
    w.upstream_timestamp > o.our_timestamp as should_reprocess
FROM our_record o
CROSS JOIN window_max w;
```

### Query 3: Player Daily Cache (Multiple Windows)

```sql
-- Check if any of player's historical windows changed
WITH our_record AS (
    SELECT processed_at as our_timestamp
    FROM `nba_precompute.player_daily_cache`
    WHERE player_lookup = 'lebronjames'
      AND cache_date = '2024-11-22'
),
-- Check L5 games window
l5_window AS (
    SELECT MAX(processed_at) as l5_timestamp
    FROM (
        SELECT
            processed_at,
            ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
        FROM `nba_analytics.player_game_summary`
        WHERE game_date <= '2024-11-22'
          AND player_lookup = 'lebronjames'
    )
    WHERE rn <= 5
),
-- Check L10 games window
l10_window AS (
    SELECT MAX(processed_at) as l10_timestamp
    FROM (
        SELECT
            processed_at,
            ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
        FROM `nba_analytics.player_game_summary`
        WHERE game_date <= '2024-11-22'
          AND player_lookup = 'lebronjames'
    )
    WHERE rn <= 10
),
-- Check L7 days window
l7_days AS (
    SELECT MAX(processed_at) as l7_timestamp
    FROM `nba_analytics.player_game_summary`
    WHERE game_date BETWEEN DATE_SUB('2024-11-22', INTERVAL 7 DAY) AND '2024-11-22'
      AND player_lookup = 'lebronjames'
)
SELECT
    o.our_timestamp,
    l5.l5_timestamp,
    l10.l10_timestamp,
    l7.l7_timestamp,
    CASE
        WHEN l5.l5_timestamp > o.our_timestamp
          OR l10.l10_timestamp > o.our_timestamp
          OR l7.l7_timestamp > o.our_timestamp
        THEN 'REPROCESS'
        ELSE 'SKIP'
    END as decision
FROM our_record o
CROSS JOIN l5_window l5
CROSS JOIN l10_window l10
CROSS JOIN l7_days l7;
```

---

## Testing Strategy

### Unit Test 1: Window Unchanged

```python
def test_check_historical_window_unchanged():
    """Test skip when L15 window unchanged."""
    processor = TeamDefenseZoneAnalysisProcessor()

    # Mock existing record: processed at 10:00 AM
    # Mock upstream L15 games: all processed before 10:00 AM
    # Expected: True (safe to skip)

    result = processor._check_historical_window_unchanged('LAL', date(2024, 11, 22))
    assert result == True
```

### Unit Test 2: Window Changed

```python
def test_check_historical_window_changed():
    """Test reprocess when game in L15 updated."""
    processor = TeamDefenseZoneAnalysisProcessor()

    # Mock existing record: processed at 10:00 AM
    # Mock upstream L15 games: one game updated at 11:00 AM
    # Expected: False (must reprocess)

    result = processor._check_historical_window_unchanged('LAL', date(2024, 11, 22))
    assert result == False
```

### Integration Test: Backfill Scenario

```python
def test_backfill_correction_detection():
    """Test detection of historical correction during backfill."""

    # Day 1: Process Nov 22 (LAL's last 15 games: Nov 1-21)
    # Day 2: Backfill corrects Nov 5 game
    # Day 3: Reprocess Nov 22
    # Expected: Nov 22 detects Nov 5 change, reprocesses

    # ... test implementation
```

---

## Cost Analysis

### Query Cost

**Per entity check**:
- 1 query to get our processed_at (cached)
- 1 query to get MAX(processed_at) from upstream window
- **Cost**: ~$0.000001 per entity

**Per processor run**:
- team_defense_zone_analysis: 30 teams × $0.000001 = $0.00003
- player_shot_zone_analysis: 450 players × $0.000001 = $0.00045
- player_daily_cache: 450 players × $0.000001 = $0.00045

**Total per day**: ~$0.001 (negligible)

**Monthly**: ~$0.03

**vs Schema approach**: Saves 24 columns × storage cost

---

## Recommendation

**Use Query-Based Approach** ✅

**Why:**
1. **No schema changes** - simpler, faster to implement
2. **Flexible** - easy to adjust window sizes
3. **Accurate** - detects all historical changes
4. **Low cost** - ~$0.03/month in queries
5. **Fast implementation** - 1.5 days vs 3 days

**When to start:**
- Implement team_defense_zone_analysis first (2 hours)
- Test with sample data
- If works well, apply to other processors

**Trade-off:**
- Slightly more query cost (~$0.03/month)
- But saves 13 hours of implementation time
- And avoids schema migration complexity

---

## Next Steps

**If approved:**

1. **Implement team_defense_zone_analysis** (2 hours)
   - Add `_check_historical_window_unchanged()` method
   - Update `calculate_precompute()` with skip logic
   - Test with Nov 22 data

2. **Validate approach** (30 min)
   - Run queries manually to verify logic
   - Check skip rates make sense
   - Verify reprocessing triggers correctly

3. **Apply to other processors** (4.5 hours)
   - player_shot_zone_analysis
   - player_daily_cache

4. **Integration test** (1.5 hours)
   - Backfill scenario
   - Historical correction scenario

5. **Deploy** with confidence

**Total time**: 8-9 hours (~1.5 days)

**Ready to start?**
