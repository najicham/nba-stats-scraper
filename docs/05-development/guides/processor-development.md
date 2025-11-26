# 01 - NBA Processor Development Guide

**Version**: 4.0
**Created**: 2025-11-21 14:35 PST
**Last Updated**: 2025-11-21 14:35 PST
**Focus**: Code development, schema design, smart idempotency, dependency management, Pub/Sub integration

---

## 📋 What's New in v4.0

- ✅ **Smart Idempotency (Pattern #14)** - Skip writes when data unchanged (50% reduction)
- ✅ **Hash Tracking** - 4 fields per dependency (was 3)
- ✅ **Backfill Detection** - Auto-find missing Phase 3 data
- ✅ **Comprehensive Testing** - Test suites for all patterns
- ✅ **Updated Examples** - All patterns verified 2025-11-21

---

## Architecture Overview

### Data Processing Pipeline

```
scrapers/ → data_processors/raw/ → data_processors/analytics/ → data_processors/precompute/ → predictions/
                     ↓                         ↓                           ↓
          data_processors/reference/ (name resolution support)
```

### Processing Types

**Raw Processors** (`data_processors/raw/`)
- Transform scraped data into clean BigQuery tables
- **NEW**: Smart idempotency - skip writes when data_hash unchanged
- Triggered by: Pub/Sub events from scrapers
- Example: NBA.com boxscores → `nba_raw.game_boxscore`

**Analytics Processors** (`data_processors/analytics/`)
- Create summary analytics from raw data
- **NEW**: Track Phase 2 data_hash for change detection
- Triggered by: Scheduled jobs (Cloud Scheduler)
- Example: Game boxscores → player performance summaries

**Precompute Processors** (`data_processors/precompute/`)
- Pre-calculated features for predictions
- **NEW**: 4-field dependency tracking (includes hash)
- Triggered by: Scheduled jobs
- Example: Player zone analysis, composite factors

**Reference Processors** (`data_processors/reference/`)
- Name resolution and data consistency
- Triggered by: Scheduled jobs or manual
- Example: Player registries, team mappings

---

## Prerequisites & Setup

### Environment Setup

```bash
# Navigate to project root
cd /path/to/nba-stats-scraper

# Activate virtual environment
source .venv/bin/activate

# Set project
export GCP_PROJECT_ID="nba-props-platform"

# Verify environment
python --version  # Should be 3.11+
gcloud config get-value project  # Should be nba-props-platform
```

### Testing Tools (NEW v4.0)

```bash
# Test all Phase 3 processors
python tests/unit/patterns/test_all_phase3_processors.py

# Test hash tracking
python tests/unit/patterns/test_historical_backfill_detection.py

# Verify schema deployment
./bin/maintenance/check_schema_deployment.sh

# Find backfill candidates
python bin/maintenance/phase3_backfill_check.py --dry-run
```

---

## Step-by-Step Processor Creation

### Step 1: Choose Processor Type

Determine which type you're creating:

| Type | Path | Trigger | Smart Idempotency | Hash Tracking |
|------|------|---------|-------------------|---------------|
| Raw | `data_processors/raw/[source]/` | Pub/Sub | ✅ Required | N/A |
| Analytics | `data_processors/analytics/[name]/` | Scheduler | N/A | ✅ 4 fields/source |
| Precompute | `data_processors/precompute/[name]/` | Scheduler | N/A | ✅ 4 fields/source |
| Reference | `data_processors/reference/[name]/` | Manual/Scheduler | N/A | N/A |

### Step 2: Design BigQuery Schema

**For Raw Processors (Phase 2) - Add Smart Idempotency:**

```sql
CREATE TABLE IF NOT EXISTS `nba_raw.[table_name]` (
  -- Business fields
  game_id STRING NOT NULL,
  player_id STRING,
  stat_value FLOAT64,

  -- Smart Idempotency (Pattern #14) - REQUIRED for all Phase 2 tables
  data_hash STRING,  -- SHA256 hash of meaningful fields (excludes metadata)

  -- Standard metadata
  source_file_path STRING NOT NULL,
  scrape_timestamp TIMESTAMP,
  processed_at TIMESTAMP NOT NULL,  -- REQUIRED (not processing_timestamp)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY game_date, player_id;
```

**For Analytics/Precompute Processors - Add Hash Tracking:**

```sql
CREATE TABLE IF NOT EXISTS `nba_analytics.[table_name]` (
  -- Business keys
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,

  -- Business metrics
  your_metric NUMERIC(5,3),

  -- Hash Tracking (4 fields per dependency) - NEW in v4.0
  -- Add one set per upstream source
  source_[prefix]_last_updated TIMESTAMP,
  source_[prefix]_rows_found INT64,
  source_[prefix]_completeness_pct NUMERIC(5,2),
  source_[prefix]_hash STRING,  -- NEW: Track Phase 2 data changes

  -- Processing metadata
  processed_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY game_date, player_lookup;
```

### Step 3: Create Processor Class

**For Raw Processors - WITH Smart Idempotency:**

```python
#!/usr/bin/env python3
from shared.utils.smart_idempotency import SmartIdempotencyMixin
from data_processors.raw.processor_base import ProcessorBase

class YourProcessorName(SmartIdempotencyMixin, ProcessorBase):
    """
    Process [source] [description] data.

    Smart Idempotency: Skips writes when data_hash unchanged
    Expected Impact: 50% reduction in cascade processing
    """

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.[table_name]'
        self.processing_strategy = 'MERGE_UPDATE'

        # CRITICAL: Initialize BigQuery client
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform raw data with hash computation."""
        rows = []

        for item in raw_data.get('data', []):
            row = {
                # Business fields (meaningful data for hash)
                'field1': item.get('field1'),
                'field2': item.get('field2'),

                # Metadata (excluded from hash)
                'source_file_path': file_path,
                'processed_at': datetime.utcnow().isoformat()
            }
            rows.append(row)

        # CRITICAL: Add hash before loading
        self.add_data_hash()  # Computes hash, skips if unchanged

        return rows
```

**For Analytics/Precompute Processors - WITH Dependency Tracking:**

```python
from data_processors.analytics.analytics_base import AnalyticsProcessorBase

class YourAnalyticsProcessor(AnalyticsProcessorBase):
    """
    Process analytics with dependency tracking and hash monitoring.

    Hash Tracking: Monitors Phase 2 data changes (4 fields per source)
    Backfill Detection: Auto-finds missing Phase 3 data
    """

    def __init__(self):
        super().__init__()
        self.table_name = '[table_name]'
        self.dataset_id = 'nba_analytics'

        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

    def get_dependencies(self) -> dict:
        """Define Phase 2 source requirements with hash tracking."""
        return {
            'nba_raw.source_table': {
                'field_prefix': 'source_prefix',  # e.g., 'source_nbac'
                'description': 'Source description',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 200,
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': True
            }
        }

    def extract_raw_data(self) -> None:
        """Extract data with dependency checking."""
        # Dependency check happens automatically in run()
        # Access source metadata after check
        for source, metadata in self.source_metadata.items():
            logger.info(f"Using {source}: hash={metadata['data_hash']}")

        # Your extraction logic...

    def calculate_analytics(self) -> None:
        """Calculate metrics with hash tracking."""
        record = {
            'player_lookup': 'lebron-james',
            'metric': 123.45,

            # One-liner to add all 4 fields per source
            **self.build_source_tracking_fields(),

            'processed_at': datetime.utcnow().isoformat()
        }
        self.transformed_data.append(record)

    # Backfill Detection (NEW v4.0) - Inherited from base class
    # Call: candidates = self.find_backfill_candidates(lookback_days=30)
```

### Step 4: Update Service Integration

**For Raw Processors** - Update `data_processors/raw/main_processor_service.py`:

```python
# 1. ADD IMPORT
from data_processors.raw.[source].[name]_processor import YourProcessorName

# 2. ADD TO PROCESSOR_REGISTRY
PROCESSOR_REGISTRY = {
    # ... existing processors ...
    '[source]/[path]': YourProcessorName,  # GCS path pattern
}
```

---

## Smart Idempotency (Pattern #14)

### How It Works

```python
# SmartIdempotencyMixin automatically:
1. Computes SHA256 hash of meaningful fields
2. Queries BigQuery for existing hash
3. Compares new hash to existing hash
4. Skips write if hash matches
5. Writes data if hash differs or doesn't exist
```

### Expected Impact

- **50% reduction** in cascade processing
- **Faster processing** (skip time vs full write time)
- **Cleaner audit trail** (only writes when data changed)

### Fields to Include in Hash

**Include** (meaningful business data):
- Game IDs, player IDs, team IDs
- Statistics, scores, odds
- Player names, team names
- Game dates, season years

**Exclude** (metadata):
- `processed_at`, `created_at`
- `scrape_timestamp`
- `source_file_path`
- `confidence_score`

### Implementation

```python
# 1. Inherit SmartIdempotencyMixin
from shared.utils.smart_idempotency import SmartIdempotencyMixin

class YourProcessor(SmartIdempotencyMixin, ProcessorBase):
    pass

# 2. Call add_data_hash() before loading
def transform_data(self, raw_data, file_path):
    rows = [...]  # Your transformation
    self.add_data_hash()  # Adds hash, enables skip logic
    return rows

# 3. Schema must have data_hash column
data_hash STRING,
```

**See**: `docs/guides/processor-patterns/01-smart-idempotency.md` for details

---

## Hash Tracking (4 Fields Per Source)

### What Changed in v4.0

**Before (3 fields)**:
```sql
source_nbac_last_updated TIMESTAMP,
source_nbac_rows_found INT64,
source_nbac_completeness_pct NUMERIC(5,2),
```

**After (4 fields)**:
```sql
source_nbac_last_updated TIMESTAMP,
source_nbac_rows_found INT64,
source_nbac_completeness_pct NUMERIC(5,2),
source_nbac_hash STRING,  -- NEW: Enables change detection
```

### Benefits

1. **Change Detection**: Know when Phase 2 data changed
2. **Smart Reprocessing**: Skip Phase 3 when Phase 2 hash unchanged
3. **Audit Trail**: Track upstream data versions
4. **Debugging**: Link Phase 3 records to Phase 2 data state

### Usage

```python
# Automatic via base class methods:
dep_check = self.check_dependencies(start_date, end_date)
self.track_source_usage(dep_check)  # Populates hash fields
fields = self.build_source_tracking_fields()  # Includes hash

# In your records:
record = {
    **self.build_source_tracking_fields(),  # All 4 fields per source
    # ... your data
}
```

**See**: `docs/guides/processor-patterns/02-dependency-tracking.md` for details

---

## Backfill Detection (NEW v4.0)

### Automatic Discovery

Analytics/Precompute processors can now find games with Phase 2 data but missing Phase 3 analytics:

```python
processor = PlayerGameSummaryProcessor()
processor.set_opts({'project_id': 'nba-props-platform'})
processor.init_clients()

# Find missing games
candidates = processor.find_backfill_candidates(lookback_days=30)

# Process each
for game in candidates:
    processor.run({
        'start_date': game['game_date'],
        'end_date': game['game_date']
    })
```

### Automated Maintenance Job

```bash
# Daily backfill check (cron-ready)
python bin/maintenance/phase3_backfill_check.py

# Dry run (check only)
python bin/maintenance/phase3_backfill_check.py --dry-run

# Custom lookback
python bin/maintenance/phase3_backfill_check.py --lookback-days 60
```

**See**: `docs/guides/processor-patterns/03-backfill-detection.md` for details

---

## Testing Your Processor

### 1. Unit Tests

```python
def test_transformation():
    processor = YourProcessor()
    raw_data = {...}  # Sample data

    rows = processor.transform_data(raw_data, 'test.json')

    assert len(rows) > 0
    assert 'data_hash' in rows[0]  # If Phase 2
    assert rows[0]['processed_at']  # Required field
```

### 2. Schema Validation

```bash
# Verify schema deployed
./bin/maintenance/check_schema_deployment.sh
```

### 3. Hash Tracking Test (Phase 3)

```python
# Use comprehensive test suite
python tests/unit/patterns/test_all_phase3_processors.py
```

### 4. Integration Test

```bash
# Test with real Pub/Sub event (Phase 2)
gcloud pubsub topics publish nba-scraper-complete \
  --message='{"scraper_name":"test","gcs_path":"gs://bucket/test.json",...}'

# Test with real GCS file (Phase 3)
python -m data_processors.analytics.your_processor \
  --start-date 2025-11-20 --end-date 2025-11-20
```

---

## Quick Reference Checklist

### Before You Finish Development

**Core Development**:
- [ ] Processor class created with all required methods
- [ ] BigQuery schema designed and documented
- [ ] BigQuery client initialized (`self.bq_client = bigquery.Client()`)
- [ ] All datetime fields use `.isoformat()`
- [ ] `process_file()` method implemented
- [ ] Data validation implemented
- [ ] Error handling comprehensive

**Smart Idempotency (Phase 2 Only)**:
- [ ] Inherits from `SmartIdempotencyMixin`
- [ ] `add_data_hash()` called before loading
- [ ] Schema has `data_hash STRING` column
- [ ] Schema has `processed_at TIMESTAMP` column (not `processing_timestamp`)

**Hash Tracking (Phase 3/4 Only)**:
- [ ] `get_dependencies()` implemented
- [ ] Schema has 4 fields per source (includes `_hash`)
- [ ] `track_source_usage()` called in `extract_raw_data()`
- [ ] `build_source_tracking_fields()` used in output records

**Testing**:
- [ ] Local tests written and passing
- [ ] Schema validation test passes
- [ ] Integration test passes
- [ ] Comprehensive test suite passes (if Phase 3)

---

## Common Patterns

### DateTime Handling

```python
# ❌ WRONG - Will cause BigQuery errors
'created_at': datetime.utcnow()

# ✅ CORRECT - Always use .isoformat()
'created_at': datetime.utcnow().isoformat()
'game_date': date.today().isoformat() if date.today() else None
```

### Null Safety

```python
def safe_float(self, value, default=None):
    if value is None or value == '':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
```

### Error Handling

```python
def validate_data(self, data: Dict) -> List[str]:
    """Return list of error messages (empty if valid)."""
    errors = []

    if 'required_field' not in data:
        errors.append("Missing required_field")

    if 'count' in data and data['count'] < 0:
        errors.append("count cannot be negative")

    return errors
```

---

## Troubleshooting

### Smart Idempotency Issues

**Symptom**: All writes skipped
```python
# Check if hash computation is correct
processor.add_data_hash()
print(processor.rows[0]['data_hash'])  # Should be SHA256

# Verify schema has data_hash column
bq show --schema nba_raw.your_table | grep data_hash
```

### Hash Tracking Issues

**Symptom**: Hash fields all NULL
```python
# Ensure Phase 2 table has data_hash column
bq show --schema nba_raw.source_table | grep data_hash

# Check if track_source_usage() was called
print(self.source_metadata)  # Should have 'data_hash' key
```

### Backfill Detection Issues

**Symptom**: No candidates found
```bash
# Verify Phase 2 data exists
bq query "SELECT COUNT(*) FROM nba_raw.source_table
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)"

# Check for region mismatch (known issue)
bq show nba_raw  # Location
bq show nba_analytics  # Should match
```

---

## Documentation to Review

### Core Guides
- **This Guide**: Complete processor development
- **Quick Start**: `docs/guides/02-quick-start-processor.md`
- **Deployment**: NBA Backfill Job Creation & Deployment Guide

### Pattern Deep-Dives
- **Smart Idempotency**: `docs/guides/processor-patterns/01-smart-idempotency.md`
- **Dependency Tracking**: `docs/guides/processor-patterns/02-dependency-tracking.md`
- **Backfill Detection**: `docs/guides/processor-patterns/03-backfill-detection.md`

### Implementation Status
- **Phase 2 Status**: `docs/implementation/03-phase2-idempotency-status-2025-11-21.md`
- **Implementation Plan**: `docs/implementation/IMPLEMENTATION_PLAN.md`
- **Session Summary**: `docs/SESSION_SUMMARY_2025-11-21.md`

### Reference
- **Pub/Sub Messages**: `docs/specifications/pubsub-message-formats.md`
- **Operations**: `docs/orchestration/phase2_orchestration_current_state.md`

---

## Next Step: Deployment 🚀

Once processor development complete, see deployment guide for:
- Cloud Run deployment
- Backfill job creation
- Monitoring setup
- Production validation

---

**Document Version**: 4.0
**Created**: 2025-11-21 14:35 PST
**Last Updated**: 2025-11-21 14:35 PST
**Changes**: Added Smart Idempotency, Hash Tracking (4 fields), Backfill Detection

**Part of**: NBA Props Platform Documentation
**Previous Version**: 3.0 (November 2025)
