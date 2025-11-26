# 02: Quick Start - Creating a New Processor

**Created**: 2025-11-21 14:45 PST
**Last Updated**: 2025-11-21 14:45 PST
**Version**: 1.0

---

## 5-Minute Quick Start

This guide gets you up and running with a new processor in under 5 minutes. For comprehensive details, see [01-processor-development-guide.md](./01-processor-development-guide.md).

---

## Step 1: Choose Your Processor Type

**Phase 2 (Raw Data)**
- Reads from GCS scraped data
- Writes to `nba_raw` dataset
- Uses smart idempotency (50% write reduction)
- Example: `bdl_active_players_processor.py`

**Phase 3 (Analytics)**
- Reads from Phase 2 tables
- Writes to `nba_analytics` dataset
- Uses dependency checking and hash tracking
- Example: `player_game_summary_processor.py`

---

## Step 2: Create Your Processor File

### Phase 2 Example (with Smart Idempotency)

```python
# data_processors/raw/my_source/my_data_processor.py

from data_processors.raw.raw_base import RawDataProcessor
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

class MyDataProcessor(SmartIdempotencyMixin, RawDataProcessor):
    """Process my data from source X."""

    # Required: Define table details
    TABLE_NAME = "my_data_table"
    UNIQUE_KEYS = ["id", "game_date"]  # Fields that identify unique records

    # Smart idempotency (automatically enabled via mixin)
    # No need to override - just works!

    def __init__(self):
        super().__init__()

    def extract_data(self, start_date: str, end_date: str) -> list:
        """Load data from GCS."""
        # 1. Build GCS paths
        blob_paths = self._build_blob_paths(
            source='my-source',
            file_pattern='data',
            start_date=start_date,
            end_date=end_date
        )

        # 2. Load JSON files
        all_data = []
        for blob_path in blob_paths:
            data = self.load_json_from_gcs(blob_path)
            all_data.extend(data)

        return all_data

    def transform_data(self, raw_data: list) -> list:
        """Transform to BigQuery schema."""
        rows = []
        for item in raw_data:
            row = {
                'id': item['id'],
                'game_date': item['date'],
                'value': item['value'],
                'processed_at': self.run_timestamp
            }
            rows.append(row)

        return rows

    def load_data(self, transformed_data: list) -> bool:
        """Load to BigQuery - smart idempotency handles deduplication."""
        if not transformed_data:
            self.logger.warning("No data to load")
            return False

        # Smart idempotency automatically:
        # 1. Computes data_hash
        # 2. Checks if data changed
        # 3. Skips write if hash unchanged
        # 4. Uses MERGE for updates

        return self.write_to_bigquery(
            transformed_data,
            self.TABLE_NAME,
            write_mode='MERGE_UPDATE'
        )
```

### Phase 3 Example (with Dependency Checking)

```python
# data_processors/analytics/my_analytics/my_analytics_processor.py

from data_processors.analytics.analytics_base import AnalyticsProcessor

class MyAnalyticsProcessor(AnalyticsProcessor):
    """Analytics derived from Phase 2 data."""

    # Required: Define dependencies
    DEPENDENCIES = {
        'my_data_table': {
            'check_type': 'date_range',
            'expected_count_min': 100,
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168
        }
    }

    def __init__(self):
        super().__init__()
        self.target_table = "my_analytics_table"

    def extract_data(self, start_date: str, end_date: str) -> list:
        """Query Phase 2 data."""
        # 1. Check dependencies (automatic hash tracking)
        dep_check = self.check_dependencies(start_date, end_date)
        if not dep_check['success']:
            self.logger.error(f"Dependencies failed: {dep_check['message']}")
            return []

        # 2. Track source usage (includes hash)
        self.track_source_usage('my_data', dep_check['details']['my_data_table'])

        # 3. Query data
        query = f"""
        SELECT *
        FROM nba_raw.my_data_table
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """
        return list(self.bq_client.query(query).result())

    def transform_data(self, raw_rows: list) -> list:
        """Compute analytics."""
        rows = []
        for row in raw_rows:
            analytics_row = {
                'game_date': row['game_date'],
                'computed_metric': row['value'] * 2,

                # Source tracking (4 fields per source)
                **self.build_source_tracking_fields()
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
```

---

## Step 3: Create BigQuery Schema

```sql
-- schemas/bigquery/raw/my_data_tables.sql (Phase 2)

CREATE TABLE IF NOT EXISTS nba_raw.my_data_table (
  id STRING NOT NULL,
  game_date DATE NOT NULL,
  value FLOAT64,

  -- Smart idempotency fields (required)
  data_hash STRING,
  processed_at TIMESTAMP,

  -- Clustering for performance
  CLUSTER BY game_date
);
```

```sql
-- schemas/bigquery/analytics/my_analytics_tables.sql (Phase 3)

CREATE TABLE IF NOT EXISTS nba_analytics.my_analytics_table (
  game_date DATE NOT NULL,
  computed_metric FLOAT64,

  -- Hash tracking fields (4 per source)
  source_my_data_last_updated TIMESTAMP,
  source_my_data_rows_found INT64,
  source_my_data_completeness_pct FLOAT64,
  source_my_data_hash STRING,

  -- Clustering for performance
  CLUSTER BY game_date
);
```

---

## Step 4: Deploy Schema

```bash
# Deploy Phase 2 schema
bq query --use_legacy_sql=false < schemas/bigquery/raw/my_data_tables.sql

# Deploy Phase 3 schema
bq query --use_legacy_sql=false < schemas/bigquery/analytics/my_analytics_tables.sql

# Verify deployment
./bin/maintenance/check_schema_deployment.sh
```

---

## Step 5: Test Your Processor

```python
# tests/manual/test_my_processor.py

from data_processors.raw.my_source.my_data_processor import MyDataProcessor

def test_my_processor():
    processor = MyDataProcessor()
    processor.set_opts({'project_id': 'nba-props-platform'})
    processor.init_clients()

    # Test with recent date
    success = processor.run({
        'start_date': '2024-11-20',
        'end_date': '2024-11-20'
    })

    assert success, "Processor run failed"
    print("✅ Test passed!")

if __name__ == "__main__":
    test_my_processor()
```

```bash
# Run test
python tests/manual/test_my_processor.py
```

---

## Step 6: Deploy to Cloud Run

```bash
# Build and deploy
gcloud run deploy my-data-processor \
  --source . \
  --region us-west2 \
  --memory 2Gi \
  --timeout 3600 \
  --set-env-vars "PROJECT_ID=nba-props-platform"
```

---

## Common Patterns

### Pattern 1: Smart Idempotency (Phase 2)

```python
# Just inherit from SmartIdempotencyMixin - that's it!
class MyProcessor(SmartIdempotencyMixin, RawDataProcessor):
    TABLE_NAME = "my_table"
    UNIQUE_KEYS = ["id", "date"]
```

**Benefits:**
- ✅ Automatic hash computation
- ✅ Skip writes when data unchanged (~50% reduction)
- ✅ MERGE strategy for updates
- ✅ No configuration needed

### Pattern 2: Dependency Checking (Phase 3)

```python
# Define dependencies in DEPENDENCIES dict
DEPENDENCIES = {
    'source_table': {
        'check_type': 'date_range',
        'expected_count_min': 100,
        'max_age_hours_warn': 48
    }
}

# Then use in extract_data()
dep_check = self.check_dependencies(start_date, end_date)
self.track_source_usage('source', dep_check['details']['source_table'])
```

**Benefits:**
- ✅ Automatic data freshness checks
- ✅ Hash tracking (4 fields per source)
- ✅ Backfill detection support
- ✅ Clear error messages

### Pattern 3: Historical Backfill

```python
# Phase 3 processors automatically support backfill detection
candidates = processor.find_backfill_candidates(lookback_days=30)
# Returns list of games with Phase 2 data but no Phase 3 analytics
```

---

## Testing Checklist

Before deploying:

- [ ] Schema deployed to BigQuery
- [ ] Manual test passes
- [ ] Smart idempotency working (Phase 2)
- [ ] Dependencies configured correctly (Phase 3)
- [ ] Hash tracking fields populated (Phase 3)
- [ ] Error handling for empty data
- [ ] Logging shows clear progress

---

## Common Issues

**Issue**: "Table not found"
- **Fix**: Deploy schema first: `bq query --use_legacy_sql=false < schema.sql`

**Issue**: "No data to process"
- **Fix**: Check GCS paths with `gsutil ls gs://bucket/path/`

**Issue**: "Dependencies failed"
- **Fix**: Check Phase 2 data exists with BigQuery query

**Issue**: "Hash not tracked"
- **Fix**: Ensure Phase 2 table has `data_hash` column

---

## Next Steps

1. **Read comprehensive guide**: [01-processor-development-guide.md](./01-processor-development-guide.md)
2. **Study patterns**:
   - [Smart Idempotency](./processor-patterns/01-smart-idempotency.md)
   - [Dependency Tracking](./processor-patterns/02-dependency-tracking.md)
   - [Backfill Detection](./processor-patterns/03-backfill-detection.md)
3. **Review existing processors**:
   - Phase 2: `data_processors/raw/balldontlie/bdl_active_players_processor.py`
   - Phase 3: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

---

## Need Help?

- See [IMPLEMENTATION_PLAN.md](../implementation/IMPLEMENTATION_PLAN.md) for current status
- Check [SESSION_SUMMARY_2025-11-21.md](../SESSION_SUMMARY_2025-11-21.md) for recent changes
- Review existing processors for examples

---

**Quick Start Complete!** You're now ready to build production-ready processors with smart idempotency and dependency checking.
