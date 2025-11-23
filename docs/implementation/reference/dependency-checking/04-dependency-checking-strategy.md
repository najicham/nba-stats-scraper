# Dependency Checking Strategy: Point-in-Time vs Historical Ranges

**File:** `docs/implementation/04-dependency-checking-strategy.md`
**Created:** 2025-11-21 12:00 PM PST
**Last Updated:** 2025-11-21 12:00 PM PST
**Purpose:** Define how to check dependencies for point-in-time vs historical range data
**Status:** Planning

---

## Overview

Our pipeline has two fundamentally different types of dependencies:

1. **Point-in-Time Dependencies** - Single event/record depends on single upstream event/record
2. **Historical Range Dependencies** - Calculation depends on multiple dates of historical data

Each type requires a different dependency checking strategy.

---

## Decision: No Composite Hash

**User Decision:** Do NOT use composite `source_data_hash` field.

**Rationale:**
- Modest value since comparison happens in Python code, not SQL
- Extra complexity to generate and store
- Individual source hashes are sufficient for tracking

**Impact:** Simpler schema, simpler code, same functionality.

---

## Type 1: Point-in-Time Dependencies

### Definition

**A single output record depends on a single input record (or set of records from the same point in time).**

### Examples

**Phase 3: player_game_summary**
```
Input:  nbac_gamebook for game_id=XYZ (single game on 2024-01-15)
Output: player_game_summary for player=lebron, game_date=2024-01-15
```

**Phase 3: upcoming_player_game_context**
```
Input:  Multiple sources, all for upcoming game on 2024-01-16
Output: upcoming_player_game_context for player=lebron, game_date=2024-01-16
```

### How to Track

**Store in database using per-source fields:**

```sql
-- For each dependency source, store 4 fields:
source_{prefix}_data_hash STRING,           -- Hash from Phase 2 (NEW)
source_{prefix}_last_updated TIMESTAMP,     -- When source was last updated
source_{prefix}_rows_found INT64,           -- How many source rows found
source_{prefix}_completeness_pct NUMERIC(5,2)  -- Data quality metric
```

**Example schema (player_game_summary):**

```sql
CREATE TABLE `nba_analytics.player_game_summary` (
  -- Business fields
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,
  game_id STRING NOT NULL,
  points INT64,
  rebounds INT64,
  assists INT64,

  -- SOURCE TRACKING: Dependency 1 - nbac_gamebook_player_stats
  source_nbac_gamebook_data_hash STRING,
  source_nbac_gamebook_last_updated TIMESTAMP,
  source_nbac_gamebook_rows_found INT64,
  source_nbac_gamebook_completeness_pct NUMERIC(5,2),

  -- SOURCE TRACKING: Dependency 2 - bdl_player_boxscores
  source_bdl_boxscores_data_hash STRING,
  source_bdl_boxscores_last_updated TIMESTAMP,
  source_bdl_boxscores_rows_found INT64,
  source_bdl_boxscores_completeness_pct NUMERIC(5,2),

  -- ... repeat for all 6 dependencies

  -- Processing metadata
  processed_at TIMESTAMP NOT NULL
);
```

### How to Check

**In processor code:**

```python
def should_process_player_game(self, player_lookup, game_date, game_id):
    """Check if we need to process this player's game summary."""

    # Step 1: Load current destination record
    existing = self.get_existing_record(
        player_lookup=player_lookup,
        game_date=game_date
    )

    if not existing:
        # No record exists - must process
        return True

    # Step 2: Load source data and compute hashes
    source_hashes = {}

    gamebook_data = self.load_gamebook_data(game_id=game_id)
    source_hashes['nbac_gamebook'] = gamebook_data['data_hash']

    bdl_data = self.load_bdl_boxscore_data(game_id=game_id)
    source_hashes['bdl_boxscores'] = bdl_data['data_hash']

    # ... repeat for all 6 sources

    # Step 3: Compare each source hash
    if existing['source_nbac_gamebook_data_hash'] != source_hashes['nbac_gamebook']:
        return True  # Gamebook data changed

    if existing['source_bdl_boxscores_data_hash'] != source_hashes['bdl_boxscores']:
        return True  # BDL data changed

    # ... check all 6 sources

    # Step 4: All sources unchanged - skip processing
    return False
```

### Benefits

✅ **Precise skip logic** - Only reprocess when specific source data changes
✅ **Audit trail** - Know exactly which source data was used
✅ **Data quality tracking** - Monitor completeness_pct per source
✅ **Debugging** - "Which source caused this to reprocess?"

### Limitations

✅ Works perfectly for same-day dependencies
❌ Doesn't work for historical range dependencies (see below)

---

## Type 2: Historical Range Dependencies

### Definition

**A single output record depends on multiple dates of historical upstream data.**

### Examples

**Phase 4: player_composite_factors (Last 30 days calculation)**
```
Input:  player_game_summary for last 30 days (2023-12-16 to 2024-01-15)
Output: player_composite_factors for player=lebron, as_of_date=2024-01-15
```

**Phase 4: ML feature store (Last 10 games calculation)**
```
Input:  player_game_summary for last 10 games (variable dates)
Output: ml_feature_store for player=lebron, as_of_date=2024-01-15
```

### Why DB Tracking Doesn't Work

**Problem:** Which hash do we store?

```python
# Option 1: Store hash for each of 30 days?
source_player_game_summary_day1_hash = "abc"
source_player_game_summary_day2_hash = "def"
# ... 30 fields? Doesn't scale!

# Option 2: Store composite hash of all 30 days?
source_player_game_summary_l30_hash = hash(day1 + day2 + ... + day30)
# Problem: This changes EVERY DAY even if data didn't change
# - On 2024-01-15: L30 = Dec 16 - Jan 15
# - On 2024-01-16: L30 = Dec 17 - Jan 16  (different range!)
# Hash will always be different even if individual days unchanged
```

**Conclusion:** Database hash tracking doesn't work for sliding windows.

### How to Track

**Do NOT store source hashes for historical ranges.**

**Instead: Use timestamp-based dependency checks in processor code.**

### How to Check

**In processor code:**

```python
def should_process_composite_factors(self, player_lookup, as_of_date):
    """Check if we need to recompute composite factors for this player."""

    # Step 1: Load current destination record
    existing = self.get_existing_record(
        player_lookup=player_lookup,
        as_of_date=as_of_date
    )

    if not existing:
        # No record exists - must process
        return True

    # Step 2: Check if we have sufficient historical data
    required_dates = self.get_last_n_days(as_of_date, days=30)

    missing_dates = self.find_missing_source_data(
        player_lookup=player_lookup,
        required_dates=required_dates,
        source_table='nba_analytics.player_game_summary'
    )

    if missing_dates:
        # Missing some historical data - might process or skip depending on policy
        logger.warning(f"Missing {len(missing_dates)} days for {player_lookup}")
        # Decision: Process with incomplete data or skip?
        return self.config.process_with_incomplete_data

    # Step 3: Check if ANY of the L30 source data has been updated
    source_max_processed_at = self.get_max_processed_at_in_range(
        player_lookup=player_lookup,
        date_range=required_dates,
        source_table='nba_analytics.player_game_summary'
    )

    our_last_processed_at = existing['processed_at']

    if source_max_processed_at > our_last_processed_at:
        # At least one day in L30 was updated since we last ran
        logger.info(f"Source data updated: {source_max_processed_at} > {our_last_processed_at}")
        return True
    else:
        # All L30 data unchanged since we last processed
        logger.info(f"All L30 data unchanged - skipping")
        return False
```

**Key helper functions:**

```python
def get_max_processed_at_in_range(self, player_lookup, date_range, source_table):
    """Get the most recent processed_at for any record in date range."""
    query = f"""
        SELECT MAX(processed_at) as max_processed_at
        FROM `{source_table}`
        WHERE player_lookup = @player_lookup
          AND game_date BETWEEN @start_date AND @end_date
    """

    result = self.bq_client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("start_date", "DATE", date_range[0]),
                bigquery.ScalarQueryParameter("end_date", "DATE", date_range[-1])
            ]
        )
    ).result()

    return list(result)[0]['max_processed_at']

def find_missing_source_data(self, player_lookup, required_dates, source_table):
    """Find which dates are missing from source table."""
    query = f"""
        SELECT game_date
        FROM `{source_table}`
        WHERE player_lookup = @player_lookup
          AND game_date IN UNNEST(@required_dates)
    """

    result = self.bq_client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ArrayQueryParameter("required_dates", "DATE", required_dates)
            ]
        )
    ).result()

    found_dates = {row['game_date'] for row in result}
    missing_dates = [d for d in required_dates if d not in found_dates]

    return missing_dates
```

### Benefits

✅ **Simple** - No complex hash generation for ranges
✅ **Accurate** - Detects when ANY day in range changed
✅ **Flexible** - Works for L30, L10, or any window size
✅ **Handles gaps** - Can detect and respond to missing historical data

### Limitations

⚠️ **Less precise** - Can't tell WHICH specific day changed
⚠️ **More queries** - Need to check timestamp ranges vs single hash comparison
⚠️ **No audit trail in DB** - Don't know which exact L30 data was used

---

## Schema Implications

### Phase 2: Raw Tables (ALL 22 tables)

**Add 1 field:**
```sql
data_hash STRING  -- Hash of meaningful fields only
```

**No changes to this approach.**

---

### Phase 3: Analytics Tables (5 tables)

**Point-in-time dependencies → Use DB tracking**

**Add 4 fields per dependency (NO composite hash):**
```sql
-- For each dependency:
source_{prefix}_data_hash STRING,
source_{prefix}_last_updated TIMESTAMP,
source_{prefix}_rows_found INT64,
source_{prefix}_completeness_pct NUMERIC(5,2)
```

**Example (player_game_summary with 6 dependencies):**
- 6 dependencies × 4 fields = 24 source tracking fields
- ~~No composite hash field~~ ← **REMOVED**

---

### Phase 4: Precompute Tables (5 tables)

**Hybrid approach - depends on the table:**

**Tables with point-in-time dependencies:**
- Add source tracking fields (4 per dependency)
- Example: `player_daily_cache` that aggregates same-day data

**Tables with historical range dependencies:**
- Do NOT add source tracking fields
- Use timestamp-based checks in code
- Example: `player_composite_factors` with L30 calculations

**Decision:** Determine per table when designing Phase 4 processors.

---

### Phase 5: Predictions Tables

**Likely point-in-time dependencies on Phase 4 precompute output.**

**If Phase 4 output is daily:**
- Add source tracking fields for the specific date's precompute data

**If Phase 4 output is historical range:**
- Use timestamp-based checks

**Decision:** Determine when designing Phase 5 prediction worker.

---

## Implementation Guidelines

### When to Use DB Tracking (Source Hash Fields)

✅ **Use when:**
- Output record depends on single input record
- Output record depends on multiple inputs from the SAME point in time (same game, same day)
- The relationship is 1:1 or 1:N within a single event

✅ **Examples:**
- player_game_summary ← nbac_gamebook (same game)
- upcoming_player_game_context ← multiple sources (same upcoming game)
- team_defense_game_summary ← team boxscore (same game)

### When to Use Code-Based Timestamp Checks

✅ **Use when:**
- Output record depends on MULTIPLE dates of historical data
- The date range is a sliding window (L30, L10, etc.)
- The relationship is 1:MANY across different time periods

✅ **Examples:**
- player_composite_factors ← L30 days of player_game_summary
- ml_feature_store ← L10 games of player_game_summary
- rolling_averages ← L5 games of team_offense_summary

---

## Code Patterns

### Pattern 1: Point-in-Time Dependency Check

```python
class PlayerGameSummaryProcessor(BaseAnalyticsProcessor):
    """Phase 3 processor with point-in-time dependencies."""

    # Define dependencies (from Phase 2)
    DEPENDENCIES = {
        'nbac_gamebook': 'nba_raw.nbac_gamebook_player_stats',
        'bdl_boxscores': 'nba_raw.bdl_player_boxscores',
        'nbac_boxscore': 'nba_raw.nbac_player_boxscores',
        # ... etc
    }

    def should_process(self, player_lookup, game_date, game_id):
        """Check if processing needed based on source hashes."""

        # Load existing record
        existing = self.get_existing_record(player_lookup, game_date)
        if not existing:
            return True

        # Load and check each dependency
        for dep_name, dep_table in self.DEPENDENCIES.items():
            source_data = self.load_dependency_data(
                table=dep_table,
                game_id=game_id
            )

            if not source_data:
                continue  # Missing dependency - skip or error

            # Compare hash
            existing_hash = existing[f'source_{dep_name}_data_hash']
            current_hash = source_data['data_hash']

            if existing_hash != current_hash:
                logger.info(f"{dep_name} data changed - reprocessing")
                return True

        # All dependencies unchanged
        return False

    def process_and_write(self, player_lookup, game_date, game_id):
        """Process and write with source tracking."""

        # Load all dependencies
        deps_data = self.load_all_dependencies(game_id)

        # Compute business logic
        summary = self.compute_player_game_summary(deps_data)

        # Add source tracking metadata
        for dep_name, dep_data in deps_data.items():
            summary[f'source_{dep_name}_data_hash'] = dep_data['data_hash']
            summary[f'source_{dep_name}_last_updated'] = dep_data['processed_at']
            summary[f'source_{dep_name}_rows_found'] = dep_data['row_count']
            summary[f'source_{dep_name}_completeness_pct'] = dep_data['completeness']

        # Write to BigQuery
        self.write_to_bigquery(summary)
```

---

### Pattern 2: Historical Range Dependency Check

```python
class PlayerCompositeFactorsProcessor(BasePrecomputeProcessor):
    """Phase 4 processor with historical range dependencies."""

    # Define historical window
    LOOKBACK_DAYS = 30

    # Define dependency (from Phase 3)
    SOURCE_TABLE = 'nba_analytics.player_game_summary'

    def should_process(self, player_lookup, as_of_date):
        """Check if processing needed based on timestamp comparison."""

        # Load existing record
        existing = self.get_existing_record(player_lookup, as_of_date)
        if not existing:
            return True

        # Get date range
        required_dates = self.get_last_n_days(as_of_date, self.LOOKBACK_DAYS)

        # Check for missing data
        missing_dates = self.find_missing_source_data(
            player_lookup=player_lookup,
            required_dates=required_dates
        )

        if len(missing_dates) > self.config.max_missing_days:
            logger.warning(f"Too much missing data: {len(missing_dates)} days")
            return False  # Skip - insufficient data

        # Check if ANY source data updated
        source_max_processed_at = self.get_max_processed_at_in_range(
            player_lookup=player_lookup,
            date_range=required_dates
        )

        our_processed_at = existing['processed_at']

        if source_max_processed_at > our_processed_at:
            logger.info(f"Source data updated - reprocessing")
            return True

        # All source data unchanged
        logger.info(f"All L{self.LOOKBACK_DAYS} data unchanged - skipping")
        return False

    def process_and_write(self, player_lookup, as_of_date):
        """Process L30 data - NO source hash tracking."""

        # Load historical data
        l30_data = self.load_historical_data(
            player_lookup=player_lookup,
            as_of_date=as_of_date,
            lookback_days=self.LOOKBACK_DAYS
        )

        # Compute composite factors
        factors = self.compute_composite_factors(l30_data)

        # NO source tracking fields needed
        # processed_at timestamp is sufficient

        # Write to BigQuery
        self.write_to_bigquery(factors)
```

---

## Migration from Current Approach

### Current State (Some Processors)

Some processors already track dependencies using existing patterns from the wiki guide.

**Fields currently used:**
```sql
source_{prefix}_last_updated TIMESTAMP,
source_{prefix}_rows_found INT64,
source_{prefix}_completeness_pct NUMERIC(5,2)
```

### New State (After Smart Idempotency)

**For point-in-time dependencies, ADD:**
```sql
source_{prefix}_data_hash STRING  -- NEW field
```

**For historical range dependencies:**
- Keep existing fields for data quality monitoring
- Do NOT add `data_hash` fields
- Use code-based timestamp checks

---

## Testing Strategy

### Test Point-in-Time Dependency Checking

```python
def test_point_in_time_dependency_skip():
    """Test that we skip when source hash unchanged."""

    # Setup: Existing record with source hashes
    existing = {
        'player_lookup': 'lebronjames',
        'game_date': '2024-01-15',
        'source_nbac_gamebook_data_hash': 'abc123',
        'processed_at': datetime(2024, 1, 15, 10, 0, 0)
    }

    # Mock: Source data unchanged (same hash)
    mock_source = {
        'data_hash': 'abc123',  # Same hash!
        'processed_at': datetime(2024, 1, 15, 9, 0, 0)
    }

    # Test
    processor = PlayerGameSummaryProcessor()
    should_process = processor.should_process('lebronjames', '2024-01-15', 'game123')

    # Assert: Should skip (hash unchanged)
    assert should_process == False

def test_point_in_time_dependency_reprocess():
    """Test that we reprocess when source hash changed."""

    # Setup: Existing record with old hash
    existing = {
        'player_lookup': 'lebronjames',
        'game_date': '2024-01-15',
        'source_nbac_gamebook_data_hash': 'abc123',
        'processed_at': datetime(2024, 1, 15, 10, 0, 0)
    }

    # Mock: Source data changed (different hash)
    mock_source = {
        'data_hash': 'xyz789',  # Different hash!
        'processed_at': datetime(2024, 1, 15, 11, 0, 0)
    }

    # Test
    processor = PlayerGameSummaryProcessor()
    should_process = processor.should_process('lebronjames', '2024-01-15', 'game123')

    # Assert: Should reprocess (hash changed)
    assert should_process == True
```

### Test Historical Range Dependency Checking

```python
def test_historical_range_dependency_skip():
    """Test that we skip when all L30 data unchanged."""

    # Setup: Existing record processed recently
    existing = {
        'player_lookup': 'lebronjames',
        'as_of_date': '2024-01-15',
        'processed_at': datetime(2024, 1, 15, 10, 0, 0)
    }

    # Mock: L30 source data, all older than our processed_at
    mock_max_processed_at = datetime(2024, 1, 15, 9, 0, 0)  # Older!

    # Test
    processor = PlayerCompositeFactorsProcessor()
    should_process = processor.should_process('lebronjames', '2024-01-15')

    # Assert: Should skip (all source data older)
    assert should_process == False

def test_historical_range_dependency_reprocess():
    """Test that we reprocess when ANY L30 data updated."""

    # Setup: Existing record processed at 10am
    existing = {
        'player_lookup': 'lebronjames',
        'as_of_date': '2024-01-15',
        'processed_at': datetime(2024, 1, 15, 10, 0, 0)
    }

    # Mock: L30 source data, one day updated at 11am
    mock_max_processed_at = datetime(2024, 1, 15, 11, 0, 0)  # Newer!

    # Test
    processor = PlayerCompositeFactorsProcessor()
    should_process = processor.should_process('lebronjames', '2024-01-15')

    # Assert: Should reprocess (at least one source updated)
    assert should_process == True
```

---

## Summary

| Aspect | Point-in-Time Dependencies | Historical Range Dependencies |
|--------|---------------------------|------------------------------|
| **Example** | player_game_summary ← gamebook (same game) | player_composite_factors ← L30 player_game_summary |
| **DB Tracking** | ✅ Yes - 4 fields per dependency | ❌ No - timestamp checks only |
| **Fields Added** | `source_{prefix}_data_hash`, `last_updated`, `rows_found`, `completeness_pct` | None (use existing `processed_at`) |
| **Check Method** | Compare source `data_hash` to stored hash | Compare `MAX(source.processed_at)` to `our.processed_at` |
| **Precision** | High - know exact source that changed | Medium - know something changed, not what |
| **Query Cost** | Low - single field comparison | Medium - range query with MAX() |
| **Audit Trail** | High - exact source data tracked | Low - only know "data refreshed" |
| **Applies To** | Phase 3 (most tables), some Phase 4 | Phase 4 (some tables), some Phase 5 |

---

## Next Steps

1. ~~Update schema plan~~ - ✅ Complete (composite hash removed)
2. ~~Implement Phase 2 & Phase 3 schemas~~ - ✅ Complete (all deployed)
3. ~~Design Phase 4 processors~~ - ✅ Complete (see Phase 4 analysis below)
4. **Implement helper functions** - `get_max_processed_at_in_range()`, `find_missing_source_data()`
5. **Test both patterns** - Unit tests for each approach

---

## Phase 4 Implementation Status (2025-11-22)

### Analysis Complete ✅

All Phase 4 processors have been analyzed for historical range dependencies. See **[05-phase4-historical-dependencies-complete.md](./05-phase4-historical-dependencies-complete.md)** for full details.

**Summary of Findings**:

| Processor | Type | Historical Range | Hash Tracking Status |
|-----------|------|------------------|---------------------|
| team_defense_zone_analysis | Historical Range | Last 15 games | ⚠️ Partial (point-in-time hash) |
| player_shot_zone_analysis | Historical Range | Last 10/20 games | ⚠️ Partial (point-in-time hash) |
| player_daily_cache | Historical Range | Last 5/7/10/14 games, 180 days | ⚠️ Partial (point-in-time hash) |
| player_composite_factors | Point-in-Time* | Cascade from upstream | ✅ Works (cascade model) |
| ml_feature_store | Point-in-Time* | Cascade from upstream | ✅ Works (cascade model) |

\* *Technically point-in-time for their own logic, but depend on processors with historical ranges*

### Current Implementation

**What Works** ✅:
- Smart idempotency (skip BigQuery writes when output unchanged)
- Dependency checking (validates upstream data exists)
- Early season handling (placeholder rows for insufficient data)
- Cascade model (later processors inherit quality flags)

**What's Incomplete** ⚠️:
- Historical range change detection (doesn't detect backfills in middle of L10/L15 window)
- May over-reprocess when historical data unchanged
- May miss reprocessing when historical data backfilled

**Impact**:
- **BigQuery cost savings**: Still works perfectly (output hash comparison)
- **Smart reprocessing**: Works but less precise (may over/under-reprocess)
- **Production risk**: Low (worst case is inefficiency, not data corruption)

### Recommendation

**Deploy current implementation**, monitor for 1 week, then add historical range checking if needed.

See [05-phase4-historical-dependencies-complete.md](./05-phase4-historical-dependencies-complete.md) for:
- Detailed processor-by-processor analysis
- Backfill strategy (4 seasons ago)
- Partial data handling matrix
- Alert & retry strategy
- Implementation recommendations

---

**Last Updated:** 2025-11-22 Evening
**Status:** Phase 4 analysis complete, ready for deployment decision
