# Pattern 02: Dependency Tracking

**Created**: 2025-11-21 14:55 PST
**Last Updated**: 2025-11-21 14:55 PST
**Version**: 1.0

---

## Overview

Dependency Tracking is a pattern for **Phase 3 analytics processors** that automatically:
- Checks if upstream Phase 2 data is available and fresh
- Tracks metadata about source data (freshness, completeness, hash)
- Stores 4 tracking fields per dependency source
- Enables smart reprocessing (see [Pattern 04](./04-smart-reprocessing.md))

**Key Benefits:**
- Automatic dependency validation before processing
- Complete audit trail of source data used
- Foundation for smart reprocessing (skip unchanged sources)
- Clear error messages when dependencies missing
- Hash tracking from Phase 2 smart idempotency

---

## Problem Statement

### Challenge: Analytics Depends on Multiple Sources

Phase 3 analytics processors combine data from multiple Phase 2 tables:

```
Player Game Summary Analytics depends on:
  ├── nbac_gamebook_player_stats (Phase 2)
  ├── nbac_player_boxscore (Phase 2)
  ├── bdl_active_players (Phase 2)
  ├── espn_boxscore (Phase 2)
  ├── nbac_play_by_play (Phase 2)
  └── odds_api_player_points_props (Phase 2)
```

**Problems without dependency tracking:**
1. **No freshness check** - Process with stale data (hours/days old)
2. **No completeness check** - Process with partial data (missing games)
3. **No change detection** - Reprocess even when source data unchanged
4. **No audit trail** - Can't trace which source data was used
5. **Silent failures** - Analytics wrong but no errors logged

### Example Bad Outcome

```
Scenario: Player stats processor runs before boxscore data arrives

Without dependency checking:
  → Processes with 0 rows from nbac_player_boxscore
  → Computes analytics with incomplete data
  → Writes wrong results to BigQuery
  → No error message (looks successful)
  → Bad data used in downstream predictions
  → Users get wrong predictions

With dependency checking:
  → Checks nbac_player_boxscore: 0 rows found (expected 200)
  → Dependency check FAILS
  → Processing stops with clear error message
  → No bad data written
  → Retry later when data available
```

---

## Solution: Dependency Tracking Framework

### Three Components

1. **Dependency Configuration** - Define what data you need
2. **Dependency Checking** - Validate before processing
3. **Source Tracking** - Record what data was used

---

## 1. Dependency Configuration

### Basic Configuration

```python
class PlayerGameSummaryProcessor(AnalyticsProcessor):
    """Analytics processor with dependency tracking."""

    DEPENDENCIES = {
        # Table name → Configuration
        'nbac_gamebook_player_stats': {
            'check_type': 'date_range',
            'expected_count_min': 200,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168
        }
    }
```

### Configuration Options

```python
DEPENDENCIES = {
    'table_name': {
        # Check type (required)
        'check_type': 'date_range',  # or 'date_match', 'lookback_days'

        # Expected data volume
        'expected_count_min': 200,    # Minimum rows expected
        'expected_count_max': 500,    # Maximum rows expected (optional)

        # Freshness thresholds
        'max_age_hours_warn': 48,     # Warn if older than 48 hours
        'max_age_hours_fail': 168,    # Fail if older than 168 hours (7 days)

        # Date field (optional, default: game_date)
        'date_field': 'game_date',

        # Required (optional, default: True)
        'required': True,             # Fail if missing
    }
}
```

### Check Types

**date_range** (most common):
```python
# Checks data exists for entire date range
'check_type': 'date_range'  # start_date to end_date

# Use for: Game stats, boxscores, play-by-play
```

**date_match** (exact match):
```python
# Checks data exists for exact date
'check_type': 'date_match'  # Only start_date

# Use for: Daily standings, daily odds
```

**lookback_days** (rolling window):
```python
# Checks data exists for last N days
'check_type': 'lookback_days'

# Use for: Player movement, injury reports
```

---

## 2. Dependency Checking

### Basic Usage

```python
def extract_data(self, start_date: str, end_date: str) -> list:
    """Extract data with dependency checking."""

    # Step 1: Check all dependencies
    dep_check = self.check_dependencies(start_date, end_date)

    if not dep_check['success']:
        self.logger.error(f"Dependencies failed: {dep_check['message']}")
        return []

    # Step 2: Track source usage for each dependency
    for table_name in self.DEPENDENCIES.keys():
        if table_name in dep_check['details']:
            prefix = f"source_{table_name.replace('nbac_', '').replace('bdl_', '')}"
            self.track_source_usage(prefix, dep_check['details'][table_name])

    # Step 3: Query data (dependencies are valid)
    query = f"""
    SELECT *
    FROM nba_raw.my_table
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    """

    return list(self.bq_client.query(query).result())
```

### check_dependencies() Method

```python
# Defined in AnalyticsProcessor base class

def check_dependencies(self, start_date: str, end_date: str) -> Dict:
    """Check all configured dependencies.

    Returns:
        {
            'success': True/False,
            'message': 'All dependencies met' or 'X failed',
            'details': {
                'table_name': {
                    'exists': True,
                    'row_count': 250,
                    'last_updated': datetime(...),
                    'age_hours': 2.5,
                    'completeness_pct': 125.0,  # 250/200 = 125%
                    'data_hash': 'a3f5c2...',   # From Phase 2
                    'status': 'ok' or 'warn' or 'fail'
                }
            }
        }
    """
```

### Dependency Check Flow

```python
# Internal implementation (in analytics_base.py)

def check_dependencies(self, start_date, end_date):
    all_passed = True
    details = {}

    for table_name, config in self.DEPENDENCIES.items():
        # Query table for data in date range
        result = self._check_table_data(
            table_name,
            start_date,
            end_date,
            config
        )

        details[table_name] = result

        # Check row count
        if result['row_count'] < config.get('expected_count_min', 0):
            result['status'] = 'fail'
            all_passed = False

        # Check freshness
        if result['age_hours'] > config.get('max_age_hours_fail', 999):
            result['status'] = 'fail'
            all_passed = False
        elif result['age_hours'] > config.get('max_age_hours_warn', 999):
            result['status'] = 'warn'

    return {
        'success': all_passed,
        'message': 'All dependencies met' if all_passed else 'Some failed',
        'details': details
    }
```

---

## 3. Source Tracking (4 Fields)

### What Gets Tracked

For **each dependency source**, 4 fields are stored:

```python
# Example: tracking nbac_gamebook_player_stats source

source_gamebook_last_updated = '2025-11-21 14:50:00'  # When Phase 2 last updated
source_gamebook_rows_found = 250                       # How many rows found
source_gamebook_completeness_pct = 125.0               # 250/200 = 125%
source_gamebook_hash = 'a3f5c2d9e8b7...'              # From Phase 2 data_hash
```

### track_source_usage() Method

```python
def track_source_usage(self, prefix: str, check_result: Dict):
    """Store source metadata for later inclusion in output.

    Args:
        prefix: Field name prefix (e.g., 'source_gamebook')
        check_result: Result from dependency check
    """
    # Store as instance variables
    setattr(self, f'{prefix}_last_updated', check_result['last_updated'])
    setattr(self, f'{prefix}_rows_found', check_result['row_count'])
    setattr(self, f'{prefix}_completeness_pct', check_result['completeness_pct'])
    setattr(self, f'{prefix}_hash', check_result.get('data_hash'))

# Later, in transform_data()...
```

### build_source_tracking_fields() Method

```python
def build_source_tracking_fields(self) -> Dict:
    """Build dict of all source tracking fields.

    Returns:
        {
            'source_gamebook_last_updated': datetime(...),
            'source_gamebook_rows_found': 250,
            'source_gamebook_completeness_pct': 125.0,
            'source_gamebook_hash': 'a3f5c2...',
            # ... for each tracked source
        }
    """
    fields = {}

    # Get all instance variables starting with 'source_'
    for attr_name in dir(self):
        if attr_name.startswith('source_') and not attr_name.startswith('_'):
            value = getattr(self, attr_name, None)
            if value is not None:
                fields[attr_name] = value

    return fields
```

### Using in transform_data()

```python
def transform_data(self, raw_rows: list) -> list:
    """Transform data and add source tracking."""

    # Build source tracking fields once
    tracking_fields = self.build_source_tracking_fields()

    rows = []
    for row in raw_rows:
        analytics_row = {
            'game_id': row['game_id'],
            'player_id': row['player_id'],
            'computed_metric': row['value'] * 2,

            # Add all source tracking fields (4 per source)
            **tracking_fields
        }
        rows.append(analytics_row)

    return rows
```

---

## Complete Example

### Processor with Multiple Dependencies

```python
# data_processors/analytics/player_game_summary/player_game_summary_processor.py

from data_processors.analytics.analytics_base import AnalyticsProcessor

class PlayerGameSummaryProcessor(AnalyticsProcessor):
    """Player game performance analytics."""

    # Define 6 dependencies
    DEPENDENCIES = {
        'nbac_gamebook_player_stats': {
            'check_type': 'date_range',
            'expected_count_min': 200,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168
        },
        'nbac_player_boxscore': {
            'check_type': 'date_range',
            'expected_count_min': 200,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168
        },
        'bdl_active_players': {
            'check_type': 'date_match',
            'expected_count_min': 400,
            'max_age_hours_warn': 168,
            'max_age_hours_fail': 720
        },
        'espn_boxscore': {
            'check_type': 'date_range',
            'expected_count_min': 200,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168
        },
        'nbac_play_by_play': {
            'check_type': 'date_range',
            'expected_count_min': 10000,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168
        },
        'odds_api_player_points_props': {
            'check_type': 'date_range',
            'expected_count_min': 100,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168,
            'required': False  # Optional dependency
        }
    }

    def __init__(self):
        super().__init__()
        self.target_table = "player_game_summary"

    def extract_data(self, start_date: str, end_date: str) -> list:
        """Extract with dependency checking."""

        # Check all 6 dependencies
        dep_check = self.check_dependencies(start_date, end_date)

        if not dep_check['success']:
            self.logger.error(f"Dependencies failed: {dep_check['message']}")
            for table, details in dep_check['details'].items():
                if details['status'] != 'ok':
                    self.logger.error(
                        f"  {table}: {details['row_count']} rows "
                        f"(expected {self.DEPENDENCIES[table]['expected_count_min']}+), "
                        f"age: {details['age_hours']:.1f}h"
                    )
            return []

        # Track all 6 sources (24 fields total: 6 × 4)
        self.track_source_usage('source_gamebook', dep_check['details']['nbac_gamebook_player_stats'])
        self.track_source_usage('source_boxscore', dep_check['details']['nbac_player_boxscore'])
        self.track_source_usage('source_active_players', dep_check['details']['bdl_active_players'])
        self.track_source_usage('source_espn', dep_check['details']['espn_boxscore'])
        self.track_source_usage('source_pbp', dep_check['details']['nbac_play_by_play'])
        self.track_source_usage('source_props', dep_check['details']['odds_api_player_points_props'])

        # Query data (dependencies validated)
        query = f"""
        SELECT
          g.*,
          b.points,
          b.rebounds,
          b.assists
        FROM nba_raw.nbac_gamebook_player_stats g
        LEFT JOIN nba_raw.nbac_player_boxscore b
          ON g.game_id = b.game_id AND g.player_id = b.player_id
        WHERE g.game_date BETWEEN '{start_date}' AND '{end_date}'
        """

        return list(self.bq_client.query(query).result())

    def transform_data(self, raw_rows: list) -> list:
        """Compute analytics with source tracking."""

        # Build tracking fields once (24 fields from 6 sources)
        tracking_fields = self.build_source_tracking_fields()

        rows = []
        for row in raw_rows:
            analytics_row = {
                'game_date': row['game_date'],
                'game_id': row['game_id'],
                'player_id': row['player_id'],

                # Computed analytics
                'points': row.get('points', 0),
                'efficiency_rating': self._compute_efficiency(row),

                # Source tracking (24 fields)
                **tracking_fields
            }
            rows.append(analytics_row)

        return rows

    def load_data(self, transformed_data: list) -> bool:
        """Load analytics to BigQuery."""
        if not transformed_data:
            return False

        return self.write_to_bigquery(
            transformed_data,
            self.target_table,
            write_mode='MERGE_UPDATE'
        )

    def _compute_efficiency(self, row):
        """Example analytics calculation."""
        points = row.get('points', 0)
        rebounds = row.get('rebounds', 0)
        assists = row.get('assists', 0)
        return points + rebounds + assists
```

### Schema with Source Tracking Fields

```sql
-- schemas/bigquery/analytics/player_game_summary_tables.sql

CREATE TABLE IF NOT EXISTS nba_analytics.player_game_summary (
  game_date DATE NOT NULL,
  game_id STRING NOT NULL,
  player_id STRING NOT NULL,

  -- Analytics
  points INT64,
  efficiency_rating FLOAT64,

  -- Source tracking: nbac_gamebook_player_stats (4 fields)
  source_gamebook_last_updated TIMESTAMP,
  source_gamebook_rows_found INT64,
  source_gamebook_completeness_pct FLOAT64,
  source_gamebook_hash STRING,

  -- Source tracking: nbac_player_boxscore (4 fields)
  source_boxscore_last_updated TIMESTAMP,
  source_boxscore_rows_found INT64,
  source_boxscore_completeness_pct FLOAT64,
  source_boxscore_hash STRING,

  -- Source tracking: bdl_active_players (4 fields)
  source_active_players_last_updated TIMESTAMP,
  source_active_players_rows_found INT64,
  source_active_players_completeness_pct FLOAT64,
  source_active_players_hash STRING,

  -- Source tracking: espn_boxscore (4 fields)
  source_espn_last_updated TIMESTAMP,
  source_espn_rows_found INT64,
  source_espn_completeness_pct FLOAT64,
  source_espn_hash STRING,

  -- Source tracking: nbac_play_by_play (4 fields)
  source_pbp_last_updated TIMESTAMP,
  source_pbp_rows_found INT64,
  source_pbp_completeness_pct FLOAT64,
  source_pbp_hash STRING,

  -- Source tracking: odds_api_player_points_props (4 fields)
  source_props_last_updated TIMESTAMP,
  source_props_rows_found INT64,
  source_props_completeness_pct FLOAT64,
  source_props_hash STRING,

  -- Total: 24 tracking fields (6 sources × 4 fields each)

  CLUSTER BY game_date
);
```

---

## Hash Tracking Integration

### How Hashes Flow Through Pipeline

```
Phase 2 (Smart Idempotency)
  ↓
  Computes data_hash for each table
  ↓
  Writes to BigQuery with data_hash column
  ↓
Phase 3 (Dependency Tracking)
  ↓
  Queries Phase 2 tables
  ↓
  Extracts data_hash from each source
  ↓
  Stores in source_xxx_hash fields
  ↓
Future Enhancement (Smart Reprocessing)
  ↓
  Compare current hash vs previous hash
  ↓
  Skip processing if hash unchanged
```

### Hash Query (Internal)

```python
# In analytics_base.py _check_table_data() method

query = f"""
SELECT
    COUNT(*) as row_count,
    MAX(processed_at) as last_updated,
    ARRAY_AGG(data_hash IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
FROM `{self.project_id}.{table_name}`
WHERE {date_field} BETWEEN '{start_date}' AND '{end_date}'
"""

# Returns:
# - row_count: 250
# - last_updated: 2025-11-21 14:50:00
# - representative_hash: 'a3f5c2d9...' ← From Phase 2 smart idempotency
```

---

## Testing

### Unit Test

```python
# tests/unit/patterns/test_dependency_tracking.py

def test_dependency_checking():
    """Test dependency validation."""
    processor = PlayerGameSummaryProcessor()
    processor.set_opts({'project_id': 'nba-props-platform'})
    processor.init_clients()

    # Check yesterday's dependencies
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    dep_check = processor.check_dependencies(yesterday, yesterday)

    # Should have details for all 6 dependencies
    assert 'nbac_gamebook_player_stats' in dep_check['details']
    assert 'nbac_player_boxscore' in dep_check['details']
    # ... etc

    # Each should have 4 tracking fields + metadata
    for table, details in dep_check['details'].items():
        assert 'row_count' in details
        assert 'last_updated' in details
        assert 'completeness_pct' in details
        assert 'data_hash' in details  # From Phase 2

def test_source_tracking_fields():
    """Test that all source tracking fields are built."""
    processor = PlayerGameSummaryProcessor()

    # Manually set source tracking (simulating dependency check)
    processor.source_gamebook_last_updated = datetime.now()
    processor.source_gamebook_rows_found = 250
    processor.source_gamebook_completeness_pct = 125.0
    processor.source_gamebook_hash = 'a3f5c2...'

    # Build fields
    fields = processor.build_source_tracking_fields()

    # Should have 4 fields
    assert 'source_gamebook_last_updated' in fields
    assert 'source_gamebook_rows_found' in fields
    assert 'source_gamebook_completeness_pct' in fields
    assert 'source_gamebook_hash' in fields

    assert fields['source_gamebook_rows_found'] == 250
```

### Integration Test

```python
# tests/manual/test_player_game_summary_e2e.py

def test_dependency_tracking_e2e():
    """Test end-to-end dependency tracking."""
    processor = PlayerGameSummaryProcessor()
    processor.set_opts({'project_id': 'nba-props-platform'})
    processor.init_clients()

    # Run processor
    success = processor.run({
        'start_date': '2024-11-20',
        'end_date': '2024-11-20'
    })

    assert success, "Processor run failed"

    # Query result to verify tracking fields
    query = """
    SELECT
      source_gamebook_hash,
      source_boxscore_hash,
      source_gamebook_rows_found
    FROM nba_analytics.player_game_summary
    WHERE game_date = '2024-11-20'
    LIMIT 1
    """

    results = list(processor.bq_client.query(query).result())
    assert len(results) > 0, "No data written"

    row = results[0]
    assert row['source_gamebook_hash'] is not None, "Hash not tracked"
    assert row['source_gamebook_rows_found'] > 0, "Row count not tracked"

    print("✅ Dependency tracking working end-to-end!")
```

---

## Troubleshooting

### Issue: "Dependency check failed: 0 rows found"

**Cause**: Phase 2 data not yet processed for date range

**Fix**:
1. Check if Phase 2 processor ran: `bq query "SELECT MAX(game_date) FROM nba_raw.table_name"`
2. Run Phase 2 processor first
3. Then run Phase 3 processor

### Issue: "data_hash is None"

**Cause**: Phase 2 table missing `data_hash` column

**Fix**:
```sql
-- Add column to Phase 2 table
ALTER TABLE nba_raw.my_table ADD COLUMN IF NOT EXISTS data_hash STRING;

-- Rerun Phase 2 processor to populate hash
```

### Issue: "Dependency check always fails"

**Cause**: `expected_count_min` set too high

**Fix**: Adjust thresholds based on actual data:
```python
# Check actual row counts
bq query "SELECT COUNT(*) FROM nba_raw.table_name WHERE game_date = '2024-11-20'"

# Update DEPENDENCIES
'expected_count_min': 50,  # Lower threshold for testing
```

### Issue: "Source tracking fields not in output"

**Cause**: Forgot to call `build_source_tracking_fields()`

**Fix**:
```python
def transform_data(self, raw_rows):
    tracking_fields = self.build_source_tracking_fields()  # ← Add this

    rows = []
    for row in raw_rows:
        analytics_row = {
            'game_id': row['game_id'],
            **tracking_fields  # ← Add this
        }
        rows.append(analytics_row)

    return rows
```

---

## Best Practices

### 1. Set Realistic Thresholds

```python
# ❌ Bad: Too strict (will fail often)
'expected_count_min': 500  # Regular season ~240 players/day

# ✅ Good: Reasonable threshold
'expected_count_min': 200  # Allows for playoff games (~200 players)

# ✅ Good: Dynamic threshold (future enhancement)
expected_count = self._calculate_expected_count(start_date, end_date)
```

### 2. Use Appropriate Check Types

```python
# Game-level data → date_range
'nbac_player_boxscore': {'check_type': 'date_range'}

# Daily aggregates → date_match
'bdl_standings': {'check_type': 'date_match'}

# Rolling data → lookback_days
'bdl_injuries': {'check_type': 'lookback_days'}
```

### 3. Track All Dependencies

```python
# ❌ Bad: Forgot to track source
dep_check = self.check_dependencies(start_date, end_date)
# ... query data ...

# ✅ Good: Track all sources
dep_check = self.check_dependencies(start_date, end_date)
for table in self.DEPENDENCIES.keys():
    self.track_source_usage(f'source_{table}', dep_check['details'][table])
```

### 4. Log Dependency Status

```python
# ✅ Good: Clear logging
if not dep_check['success']:
    self.logger.error("Dependencies failed:")
    for table, details in dep_check['details'].items():
        if details['status'] != 'ok':
            self.logger.error(
                f"  {table}: {details['row_count']} rows "
                f"(expected {self.DEPENDENCIES[table]['expected_count_min']}+)"
            )
```

---

## Related Enhancement: Smart Reprocessing

### Now Implemented! (2025-11-21)

Dependency tracking provides the foundation for **Smart Reprocessing** - a separate pattern that skips Phase 3 processing when Phase 2 source data unchanged.

```python
# Smart Reprocessing uses hashes from dependency tracking

def extract_data(self, start_date, end_date):
    # Dependency tracking already ran (in base class)
    # Current hashes stored as attributes: self.source_gamebook_hash, etc.

    # Smart reprocessing: Compare with previous run
    skip, reason = self.should_skip_processing(start_date)

    if skip:
        self.logger.info(f"✅ SKIPPING: {reason}")
        return []  # Skip processing

    self.logger.info(f"🔄 PROCESSING: {reason}")
    # Continue with processing...
```

**Impact**: 30-50% reduction in Phase 3 processing
**Status**: Implemented in all 5 Phase 3 processors
**Details**: See **[Pattern 04: Smart Reprocessing](./04-smart-reprocessing.md)**

**Key Point**: Dependency tracking and smart reprocessing are **separate patterns**:
- Dependency tracking = Data validation framework (always runs)
- Smart reprocessing = Processing optimization (uses dependency data)

---

## Related Patterns

- **[Pattern 01: Smart Idempotency](./01-smart-idempotency.md)** - Phase 2 produces hashes that this pattern tracks
- **[Pattern 03: Backfill Detection](./03-backfill-detection.md)** - Uses dependency tracking to find missing data
- **[Pattern 04: Smart Reprocessing](./04-smart-reprocessing.md)** - Uses hashes to skip processing

---

## Summary

Dependency Tracking provides:
- ✅ Automatic validation of upstream data
- ✅ 4 tracking fields per source (last_updated, rows_found, completeness_pct, hash)
- ✅ Complete audit trail of source data
- ✅ Foundation for smart reprocessing (skip unchanged sources)
- ✅ Clear error messages when dependencies fail

**Adoption Status**: 5/5 Phase 3 processors (100% coverage)

---

**Next**: See [03-backfill-detection.md](./03-backfill-detection.md) for historical data gap detection.
