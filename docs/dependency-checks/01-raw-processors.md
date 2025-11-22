# Phase 2: Raw Processors - Dependency Checks
**Detailed Specification**
**Version**: 1.0
**Last Updated**: 2025-11-21

📖 **Parent Document**: [Dependency Checking System Overview](./00-overview.md)

---

## Table of Contents

1. [Phase 2 Overview](#phase-2-overview)
2. [Dependency Check Pattern](#dependency-check-pattern)
3. [Processor Specifications](#processor-specifications)
4. [Failure Scenarios](#failure-scenarios)
5. [Logging & Monitoring](#logging--monitoring)
6. [Database Field Mappings](#database-field-mappings)

---

## Phase 2 Overview

### Purpose

Phase 2 processors ingest raw data from Phase 1 scrapers (GCS JSON files) and transform it into structured BigQuery tables (`nba_raw.*`).

### Key Characteristics

- **22 Total Processors** across 7 data sources
- **Primary Dependency**: GCS file existence from Phase 1 scrapers
- **Smart Idempotency**: Enabled on 21/22 processors (Pattern #14)
- **Processing Strategy**: MERGE_UPDATE (most), APPEND_ALWAYS (injuries, props)
- **Output**: Structured data in `nba_raw.*` tables

### Data Flow

```
Phase 1 (Scrapers)
    ↓ writes JSON to GCS
    gs://nba-scraped-data/{source}/{data-type}/{date}/{timestamp}.json
    ↓
Phase 2 (Raw Processors) - THIS PHASE
    ├─ Dependency Check: File exists in GCS?
    ├─ Validation: JSON structure valid?
    ├─ Transform: JSON → BigQuery schema
    ├─ Smart Idempotency: Data hash matches existing?
    └─ Load: Insert/merge to nba_raw.* table
    ↓
Phase 3 (Analytics Processors)
```

---

## Dependency Check Pattern

### Standard Dependency Check (All Phase 2 Processors)

```python
class ProcessorBase:
    """Base class with standard dependency checking."""

    def check_gcs_file_exists(self, file_path: str) -> Dict[str, Any]:
        """
        Check if GCS file exists and is accessible.

        Args:
            file_path: Full GCS path (gs://bucket/path/to/file.json)

        Returns:
            {
                'exists': bool,
                'file_size': int,  # bytes
                'created_at': str,  # ISO timestamp
                'status': 'available'|'missing'|'error'
            }
        """
        try:
            # Parse GCS path
            if not file_path.startswith('gs://'):
                return {'exists': False, 'status': 'error', 'error': 'Invalid GCS path'}

            path_parts = file_path[5:].split('/', 1)
            bucket_name = path_parts[0]
            blob_name = path_parts[1]

            # Check blob existence
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            if blob.exists():
                blob.reload()  # Get metadata
                return {
                    'exists': True,
                    'file_size': blob.size,
                    'created_at': blob.time_created.isoformat(),
                    'status': 'available'
                }
            else:
                logger.warning(f"GCS file not found: {file_path}")
                return {
                    'exists': False,
                    'status': 'missing'
                }

        except Exception as e:
            logger.error(f"Error checking GCS file: {e}")
            return {
                'exists': False,
                'status': 'error',
                'error': str(e)
            }
```

### When to Abort vs Continue

| Scenario | Action | Reason |
|----------|--------|--------|
| File missing | **Abort** | No data to process |
| File < 100 bytes | **Abort** | Likely empty/corrupt |
| Invalid JSON | **Abort** | Cannot parse |
| Missing required fields | **Abort** | Cannot transform |
| Partial data (70-99% complete) | **Continue with warning** | Better than no data |
| Partial data (30-70% complete) | **Continue with critical warning** | Flag for investigation |
| Partial data (< 30% complete) | **Abort** | Too incomplete to be useful |

---

## Processor Specifications

### Data Source Groups

Phase 2 has 22 processors organized by data source:

1. **NBA.com (9 processors)** - Official NBA data
2. **Ball Don't Lie (3 processors)** - NBA API alternative
3. **ESPN (3 processors)** - ESPN sports data
4. **Odds API (1 processor)** - Sports betting lines
5. **BettingPros (1 processor)** - Betting prop lines
6. **BigDataBall (1 processor)** - Play-by-play advanced stats
7. **Basketball Reference (1 processor)** - Historical rosters
8. **NBA.com CDN (3 processors)** - Static CDN data

---

### Processor Template

Each processor follows this standardized format:

```markdown
## Processor Name

**File**: `data_processors/raw/{source}/{processor_name}.py`
**Table**: `nba_raw.{table_name}`
**Processing Strategy**: MERGE_UPDATE | APPEND_ALWAYS
**Smart Idempotency**: Enabled | Disabled
**Expected Frequency**: Daily | 4-6x daily | Real-time

### Primary Dependency

**GCS Path Pattern**: `gs://nba-scraped-data/{source}/{data-type}/{date}/{timestamp}.json`
**Example**: `gs://nba-scraped-data/nba-com/injury-report/2025-11-21/1732219200.json`

### Expected Data Volume

| Metric | Typical | Warning Threshold | Critical Threshold |
|--------|---------|-------------------|-------------------|
| File size | XXX KB | < XX KB | < X KB |
| Record count | ~XXX | < XXX (XX%) | < XX (XX%) |
| Players/teams | XXX | < XXX | < XX |

### Dependency Check Logic

```python
def check_dependencies(self) -> Dict[str, Any]:
    # Implementation
```

### Partial Data Handling

**What happens if file incomplete?**
- 70-100% complete: [Action]
- 30-70% complete: [Action]
- < 30% complete: [Action]

### Failure Scenarios & Logging

**Scenario 1: File Missing**
- **Log Level**: ERROR
- **Message**: `"GCS file not found: {file_path}"`
- **Notification**: Error notification sent
- **Action**: Abort processing
- **Retry**: Scraper will retry in next scheduled run

**Scenario 2: Invalid JSON**
- **Log Level**: ERROR
- **Message**: `"JSON parse error: {error}"`
- **Notification**: Error notification sent
- **Action**: Abort processing
- **Retry**: Manual investigation required

**Scenario 3: Partial Data**
- **Log Level**: WARNING
- **Message**: `"Partial data: {completeness_pct}% ({actual}/{expected})"`
- **Notification**: Warning notification sent
- **Action**: Continue processing with flag
- **Retry**: Monitor for improvement

### Database Fields

**Core Fields**:
- `{business_key}`: Primary identifier
- `game_date` / `date_recorded`: Partitioning field
- `data_hash`: Smart idempotency hash (16 chars)
- `source_file_path`: GCS path for debugging
- `processing_confidence`: 0.0-1.0 based on completeness
- `data_quality_flags`: Comma-separated warnings
- `processed_at`: Processing timestamp

**Smart Idempotency Hash Fields**:
```python
HASH_FIELDS = [
    'field1',  # Business-critical field 1
    'field2',  # Business-critical field 2
    # ... (exclude metadata like processed_at)
]
```

### Historical Data Requirements

**Lookback Window**: N/A (real-time processing)
**Minimum History**: None (processes current scrape only)

---

```

Now let me create detailed entries for a few key processors as examples:

---

## 1. NBA.com Injury Report Processor

**File**: `data_processors/raw/nbacom/nbac_injury_report_processor.py`
**Table**: `nba_raw.nbac_injury_report`
**Processing Strategy**: APPEND_ALWAYS
**Smart Idempotency**: ✅ Enabled
**Expected Frequency**: 4-6x daily
**Priority**: 🔴 **CRITICAL** (affects all prediction systems)

### Primary Dependency

**GCS Path Pattern**: `gs://nba-scraped-data/nba-com/injury-report/{date}/{timestamp}.json`
**Example**: `gs://nba-scraped-data/nba-com/injury-report/2025-11-21/1732219200.json`

### Expected Data Volume

| Metric | Typical | Warning Threshold | Critical Threshold |
|--------|---------|-------------------|-------------------|
| File size | 50-150 KB | < 20 KB | < 5 KB |
| Player records | 40-60 | < 30 (50%) | < 15 (25%) |
| Teams represented | 20-30 | < 15 | < 10 |

**Context**: NBA typically has 40-60 players on injury report at any time (out, questionable, probable). Fewer than 30 indicates scraper may have failed mid-stream.

### Dependency Check Logic

```python
def check_dependencies(self) -> Dict[str, Any]:
    """
    Check if injury report GCS file exists and has valid structure.
    """
    file_path = self.opts.get('file_path')

    # Check 1: File exists
    file_check = self.check_gcs_file_exists(file_path)
    if not file_check['exists']:
        return {
            'all_met': False,
            'can_proceed': False,
            'errors': ['GCS file not found'],
            'file_status': file_check
        }

    # Check 2: File size reasonable
    if file_check['file_size'] < 5000:  # 5 KB minimum
        return {
            'all_met': False,
            'can_proceed': False,
            'errors': [f"File too small: {file_check['file_size']} bytes"],
            'file_status': file_check
        }

    # Check 3: JSON valid (happens in load_data)
    return {
        'all_met': True,
        'can_proceed': True,
        'warnings': [],
        'errors': [],
        'file_status': file_check
    }
```

### Partial Data Handling

**What happens if injury report incomplete?**

- **70-100% complete** (28-42 players):
  - ✅ Continue processing
  - ℹ️ Log info: "Normal injury report volume"
  - 💾 Write all records with `processing_confidence = 1.0`

- **30-70% complete** (12-28 players):
  - ⚠️ Continue processing with warning
  - 📊 Log warning: "Low injury report volume: X players (expected ~40)"
  - 📬 Send warning notification
  - 💾 Write all records with `processing_confidence = 0.7`
  - 🏷️ Set `data_quality_flags = "low_volume"`

- **< 30% complete** (< 12 players):
  - 🛑 Abort processing
  - 🚨 Log error: "Critical: Injury report severely incomplete"
  - 📬 Send error notification
  - 🔄 Scraper will retry on next scheduled run

**Rationale**: Injury data critically affects predictions. Publishing incomplete injury data is worse than no data (leads to incorrect predictions). Better to wait for scraper retry.

### Failure Scenarios & Logging

#### Scenario 1: File Missing

```python
# Log
logger.error(
    "GCS file not found for injury report",
    extra={
        'file_path': file_path,
        'expected_date': date_str,
        'processor': 'nbac_injury_report'
    }
)

# Notification
notify_error(
    title="Injury Report File Missing",
    message=f"Scraper may have failed for {date_str}",
    details={
        'file_path': file_path,
        'date': date_str,
        'expected_time': 'Within 2 hours of scraper run',
        'next_scrape': 'In 4 hours',
        'action_required': 'Monitor next scrape. If persists, check scraper logs.'
    },
    processor_name="NBA.com Injury Report Processor"
)

# Action
return {
    'rows_processed': 0,
    'errors': ['File not found'],
    'status': 'aborted'
}
```

#### Scenario 2: Invalid JSON Structure

```python
# Log
logger.error(
    "Invalid JSON structure in injury report",
    extra={
        'file_path': file_path,
        'error': str(e),
        'processor': 'nbac_injury_report'
    }
)

# Notification
notify_error(
    title="Injury Report: Invalid JSON",
    message=f"JSON parsing failed: {str(e)[:100]}",
    details={
        'file_path': file_path,
        'parse_error': str(e),
        'file_size': file_size,
        'action_required': 'Check if NBA.com changed API format. May need scraper update.'
    },
    processor_name="NBA.com Injury Report Processor"
)

# Action
return {
    'rows_processed': 0,
    'errors': ['JSON parse error'],
    'status': 'aborted'
}
```

#### Scenario 3: Low Volume Warning

```python
# Log
logger.warning(
    f"Low injury report volume: {player_count} players (expected ~40-60)",
    extra={
        'file_path': file_path,
        'player_count': player_count,
        'completeness_pct': completeness_pct,
        'processor': 'nbac_injury_report'
    }
)

# Notification
notify_warning(
    title="Injury Report: Low Volume",
    message=f"Only {player_count} players found (expected 40-60)",
    details={
        'file_path': file_path,
        'player_count': player_count,
        'completeness_pct': f"{completeness_pct:.1f}%",
        'status': 'processing_with_flag',
        'impact': 'Predictions may have reduced confidence for games with affected players'
    }
)

# Action
# Continue processing but flag data quality
for row in rows:
    row['processing_confidence'] = 0.7
    row['data_quality_flags'] = 'low_volume'

return {
    'rows_processed': len(rows),
    'warnings': ['Low volume'],
    'status': 'completed_with_warnings'
}
```

### Database Fields

**Table**: `nba_raw.nbac_injury_report`

**Core Fields**:
```sql
-- Business keys
player_lookup STRING NOT NULL,     -- Normalized player name
team STRING,                        -- Team abbreviation
game_date DATE NOT NULL,            -- Date of affected game
game_id STRING,                     -- Game identifier

-- Injury details
injury_status STRING NOT NULL,     -- OUT, QUESTIONABLE, PROBABLE, GTD
reason STRING,                      -- Injury description
reason_category STRING,             -- Body part category

-- Smart Idempotency (Pattern #14)
data_hash STRING,                   -- SHA256 hash (16 chars) of meaningful fields
-- Hash includes: player_lookup, team, game_date, game_id, injury_status, reason, reason_category

-- Processing metadata
source_file_path STRING,            -- GCS path for debugging
processing_confidence NUMERIC(3,2), -- 0.0-1.0 based on data completeness
data_quality_flags STRING,          -- Comma-separated flags (e.g., "low_volume,partial_data")
scrape_timestamp TIMESTAMP,         -- When scraper ran
processed_at TIMESTAMP,             -- When processor ran
created_at TIMESTAMP                -- Record creation time
```

**Partitioning**: `PARTITION BY DATE(game_date)`

### Historical Data Requirements

**Lookback Window**: N/A (processes current injuries only)
**Minimum History**: None
**Retention**: 90 days (for historical analysis)

**Rationale**: Injury reports are point-in-time snapshots. Historical injuries tracked via `APPEND_ALWAYS` strategy, allowing analysis of injury trends over time.

### Impact on Downstream Phases

**Phase 3 Impact**:
- `player_game_summary` uses injury status as critical feature
- Missing injury data → `source_nbac_completeness_pct = 0%`

**Phase 4 Impact**:
- XGBoost model: Injury feature has high importance (top 5)
- Missing injury → Prediction confidence drops 10-15%

**Phase 5 Impact**:
- Ensemble coordinator weights predictions with injury data higher
- Missing injury → Final prediction marked "Medium Confidence" (max)

---

## 2. NBA.com Player Boxscores Processor

**File**: `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`
**Table**: `nba_raw.nbac_player_boxscores`
**Processing Strategy**: MERGE_UPDATE
**Smart Idempotency**: ✅ Enabled
**Expected Frequency**: Daily (morning after games)
**Priority**: 🔴 **CRITICAL** (primary stats source)

### Primary Dependency

**GCS Path Pattern**: `gs://nba-scraped-data/nba-com/leaguegamelog/{date}/{timestamp}.json`
**Example**: `gs://nba-scraped-data/nba-com/leaguegamelog/2025-11-21/1732252800.json`

### Expected Data Volume

| Metric | Typical | Warning Threshold | Critical Threshold |
|--------|---------|-------------------|-------------------|
| File size | 200-500 KB | < 100 KB | < 50 KB |
| Player records | 200-250 | < 150 (60%) | < 100 (40%) |
| Games represented | 8-15 | < 5 | < 3 |

**Context**: Typical NBA night has 8-15 games × ~15-20 active players per team = 240-300 total records. Early processing may catch only finished games.

### Dependency Check Logic

```python
def check_dependencies(self) -> Dict[str, Any]:
    """
    Check if leaguegamelog file exists with expected game count.
    """
    file_path = self.opts.get('file_path')

    # Check 1: File exists
    file_check = self.check_gcs_file_exists(file_path)
    if not file_check['exists']:
        return {
            'all_met': False,
            'can_proceed': False,
            'errors': ['GCS file not found']
        }

    # Check 2: File size indicates data present
    if file_check['file_size'] < 50000:  # 50 KB
        return {
            'all_met': False,
            'can_proceed': False,
            'errors': [f"File suspiciously small: {file_check['file_size']} bytes"],
            'warnings': ['May indicate no games played or scraper failure']
        }

    # Check 3: Expected game count (validated in transform_data)
    return {
        'all_met': True,
        'can_proceed': True,
        'warnings': [],
        'file_status': file_check
    }
```

### Partial Data Handling

**KEY SCENARIO**: **Boxscore timing issue**

Early morning processing (7 AM PT) may only have East Coast games completed:
- **Early run**: 3-5 games finished (East Coast)
- **Later run**: 8-12 games finished (all games)

**How Smart Idempotency Helps**:

```python
# First run at 7 AM PT
games_found = [game1, game2, game3]  # East Coast games
# Process and write to BigQuery with data_hash

# Second run at 10 AM PT
games_found = [game1, game2, game3, game4, game5, game6, game7, game8]
# game1, game2, game3: data_hash matches existing → SKIP (no cascade!)
# game4-8: New games → WRITE
# Result: Only 5 new games cascade to Phase 3+
```

**Without Smart Idempotency**:
- Second run would DELETE all 8 games, re-insert all 8
- All 8 games would cascade to Phase 3, 4, 5
- **Unnecessary work**: 3 games × 3 phases = 9 extra operations

**With Smart Idempotency**:
- Only 5 new games cascade
- **Savings**: 9 - 5 = 4 operations saved (44% reduction)

This pattern repeats 4-6x daily across 22 processors = **4500+ operations saved daily**.

### Failure Scenarios & Logging

#### Scenario 1: Zero Games (Off-Day or All-Star Weekend)

```python
# This is VALID, not an error
if len(games_found) == 0:
    logger.info(
        "No games found in leaguegamelog (off-day or All-Star Weekend)",
        extra={
            'file_path': file_path,
            'date': date_str,
            'is_all_star_weekend': check_if_all_star_weekend(date_str)
        }
    )

    # No notification needed - this is expected
    return {
        'rows_processed': 0,
        'status': 'completed',
        'info': ['Zero games is valid for off-days']
    }
```

#### Scenario 2: Low Game Count (Unexpected)

```python
# Expected 8-12 games, found only 3
if len(games_found) < 5 and not is_off_day:
    logger.warning(
        f"Unusually low game count: {len(games_found)} games",
        extra={
            'file_path': file_path,
            'games_found': len(games_found),
            'expected': '8-12',
            'possible_causes': ['Early processing', 'Scraper failure', 'PPD games']
        }
    )

    notify_warning(
        title="Player Boxscores: Low Game Count",
        message=f"Only {len(games_found)} games found (expected 8-12)",
        details={
            'games_found': len(games_found),
            'game_ids': [g['game_id'] for g in games_found],
            'status': 'processing_partial_data',
            'recommendation': 'Schedule re-run in 2-3 hours to capture remaining games'
        }
    )

    # Continue processing available games
    # Smart idempotency will prevent duplicates on re-run
```

### Database Fields

**Table**: `nba_raw.nbac_player_boxscores`

**Smart Idempotency Hash Fields**:
```python
HASH_FIELDS = [
    'game_id',
    'player_lookup',
    'points',
    'rebounds',
    'assists',
    'minutes',
    'field_goals_made',
    'field_goals_attempted'
]
```

**Partitioning**: `PARTITION BY DATE(game_date)`

### Historical Data Requirements

**Lookback Window**: N/A (processes current games only)
**Minimum History**: None required for Phase 2
**Note**: Phase 3 analytics will look back 10-20 games for rolling averages

---

## 3. Odds API Props Processor

**File**: `data_processors/raw/oddsapi/odds_api_props_processor.py`
**Table**: `nba_raw.odds_api_player_props`
**Processing Strategy**: APPEND_ALWAYS
**Smart Idempotency**: ✅ Enabled
**Expected Frequency**: 6-8x daily (lines change frequently)
**Priority**: 🔴 **CRITICAL** (core betting lines)

### Primary Dependency

**GCS Path Pattern**: `gs://nba-scraped-data/odds-api/props/{date}/{timestamp}.json`
**Example**: `gs://nba-scraped-data/odds-api/props/2025-11-21/1732219200.json`

### Expected Data Volume

| Metric | Typical | Warning Threshold | Critical Threshold |
|--------|---------|-------------------|-------------------|
| File size | 500 KB - 2 MB | < 200 KB | < 100 KB |
| Prop records | 3000-5000 | < 2000 (40%) | < 1000 (20%) |
| Players | 400-450 | < 300 | < 200 |
| Bookmakers | 8-12 | < 5 | < 3 |

**Context**: Each game has ~30 props per player × 30 players × 10 bookmakers = ~9000 records. Multiple scrapes per day capture line movements.

### Dependency Check Logic

```python
def check_dependencies(self) -> Dict[str, Any]:
    """Check Odds API file with bookmaker validation."""
    file_path = self.opts.get('file_path')

    file_check = self.check_gcs_file_exists(file_path)
    if not file_check['exists']:
        return {'all_met': False, 'can_proceed': False}

    # Odds API files should be substantial (many bookmakers)
    if file_check['file_size'] < 100000:  # 100 KB
        return {
            'all_met': False,
            'can_proceed': False,
            'errors': ['File too small - may indicate API quota exceeded']
        }

    return {'all_met': True, 'can_proceed': True}
```

### Partial Data Handling

**APPEND_ALWAYS Strategy**: Every scrape adds new records (tracks line movements over time).

**Smart Idempotency Role**: Monitor only, does NOT skip writes.

```python
# Even if data_hash matches previous scrape, STILL write
# (line may have same value but different timestamp = meaningful)

for row in rows:
    row['data_hash'] = self.compute_data_hash(row)
    # Always insert, hash used for monitoring duplicate detection
```

**Completeness Checks**:

- **70-100% complete** (2800-4000 props):
  - ✅ Healthy volume
  - Write all records with `processing_confidence = 1.0`

- **30-70% complete** (1200-2800 props):
  - ⚠️ Low but acceptable
  - Check if specific bookmakers missing
  - Write all records with `processing_confidence = 0.7`
  - Flag: `data_quality_flags = "low_bookmaker_coverage"`

- **< 30% complete** (< 1200 props):
  - 🚨 Critical - likely API failure
  - Log error, send notification
  - Write available data but flag heavily
  - `processing_confidence = 0.3`
  - Flag: `data_quality_flags = "critical_low_volume,api_failure_suspected"`

### Failure Scenarios & Logging

#### Scenario 1: API Quota Exceeded

```python
# Odds API free tier: 500 requests/month
# File will be tiny (error message JSON)

if file_size < 10000 and 'quota' in content.lower():
    logger.error(
        "Odds API quota exceeded",
        extra={
            'file_path': file_path,
            'file_size': file_size,
            'error_message': content[:200]
        }
    )

    notify_error(
        title="Odds API: Quota Exceeded",
        message="Odds API returned quota error - no props data",
        details={
            'api': 'The Odds API',
            'quota_type': 'Free tier (500 req/month)',
            'resolution': 'Upgrade to paid tier or reduce scrape frequency',
            'impact': 'No prop lines available for predictions',
            'urgency': 'HIGH - affects core product'
        },
        processor_name="Odds API Props Processor"
    )

    return {'rows_processed': 0, 'errors': ['API quota exceeded']}
```

#### Scenario 2: Bookmaker Missing

```python
# Expected bookmakers: DraftKings, FanDuel, BetMGM, Caesars, etc.
expected_bookmakers = {'draftkings', 'fanduel', 'betmgm', 'caesars', 'pointsbet'}
found_bookmakers = set(row['bookmaker'] for row in rows)
missing = expected_bookmakers - found_bookmakers

if missing:
    logger.warning(
        f"Missing bookmakers in Odds API response: {missing}",
        extra={
            'expected': list(expected_bookmakers),
            'found': list(found_bookmakers),
            'missing': list(missing),
            'coverage_pct': (len(found_bookmakers) / len(expected_bookmakers)) * 100
        }
    )

    notify_warning(
        title="Odds API: Bookmakers Missing",
        message=f"Missing {len(missing)} expected bookmakers",
        details={
            'missing_bookmakers': list(missing),
            'found_bookmakers': list(found_bookmakers),
            'impact': 'Reduced line shopping options',
            'action': 'Monitor - may be temporary API issue'
        }
    )

    # Continue processing with available bookmakers
    for row in rows:
        row['processing_confidence'] = 0.8
        row['data_quality_flags'] = f"missing_bookmakers:{','.join(missing)}"
```

### Database Fields

**Table**: `nba_raw.odds_api_player_props`

**Smart Idempotency Hash Fields** (monitoring only, doesn't skip writes):
```python
HASH_FIELDS = [
    'player_lookup',
    'game_date',
    'game_id',
    'bookmaker',
    'points_line',        # The actual prop value
    'snapshot_timestamp'  # When line was scraped
]
```

**Note**: Hash includes `snapshot_timestamp` because same line at different times is meaningful (confirms line hasn't moved).

---

## Summary: Phase 2 Dependency Patterns

### Common Patterns Across All 22 Processors

1. **Primary Dependency**: GCS file from Phase 1 scraper
2. **Validation**: JSON structure + expected fields
3. **Completeness Check**: Record count vs expected
4. **Smart Idempotency**: Hash meaningful fields, skip unchanged
5. **Logging**: Structured logs with processor context
6. **Notifications**: Error/Warning/Info based on severity
7. **Confidence Scoring**: Flag partial data quality

### Phase 2 Success Criteria

✅ **Healthy Processing**:
- All 22 processors run daily
- 95%+ availability rate
- 85%+ average completeness
- < 5% fallback usage (where applicable)

⚠️ **Warning Signs**:
- Multiple processors missing files (scraper issue)
- Consistent low completeness (data source issue)
- Increasing fallback usage (primary source degrading)

🚨 **Critical Issues**:
- Injury report missing (blocks predictions)
- Zero boxscores on game day (core data missing)
- Odds API quota exceeded (affects product)

---

## Smart Idempotency Implementation

### Why It Matters for Phase 2

**Problem**: Without smart idempotency, every scraper run triggers downstream cascade.

**Example Cascade**:
```
Injury scraper runs 4x/day (no changes)
→ Phase 2 writes 4x, updates processed_at
→ Phase 3 sees "new" data, reprocesses 450 players
→ Phase 4 sees "new" data, reprocesses features
→ Phase 5 regenerates all predictions
= 3,600+ unnecessary operations/day
```

### How It Works

**Step 1**: Hash only meaningful fields
```python
# Injury Report Example
HASH_FIELDS = ['player_lookup', 'injury_status', 'reason']
EXCLUDED = ['scrape_time', 'source_file_path']  # Metadata
```

**Step 2**: Check if hash changed
```python
existing_hash = get_existing_hash(player_lookup, game_date)
new_hash = compute_hash(new_data, HASH_FIELDS)

if existing_hash == new_hash:
    logger.info("Data unchanged - skipping write")
    return SKIPPED
```

**Step 3**: Only write if changed
```python
# Only these changes trigger downstream
injury_status: "Probable" → "Out"  ✅ Write
reason: "Ankle" → "Knee"           ✅ Write
scrape_time: 10am → 2pm            ❌ Skip
```

**Result**: 75% reduction in downstream processing

**See**: [Phase 2 Processor Hash Strategy](../reference/phase2-processor-hash-strategy.md) for field-by-field analysis

---

## Related Documentation

### Detailed Processor Specs
- [Processor Cards](../processor-cards/README.md) - Quick reference for each processor
- [Phase 2 Architecture](../architecture/09-phase2-phase3-implementation-roadmap.md)

### Implementation Guides
- [Smart Idempotency Guide](../implementation/03-smart-idempotency-implementation-guide.md)
- [Dependency Checking Strategy](../implementation/04-dependency-checking-strategy.md)
- [Phase 2 Hash Strategy](../reference/phase2-processor-hash-strategy.md)

### Operations
- [Cross-Phase Troubleshooting](../operations/cross-phase-troubleshooting-matrix.md) §2.1
- [BigQuery Schemas](../orchestration/03-bigquery-schemas.md)

---

**Next**: [Phase 3 Dependency Checks](./02-analytics-processors.md)

**Last Updated**: 2025-11-21 15:00:00 PST
**Version**: 1.1
