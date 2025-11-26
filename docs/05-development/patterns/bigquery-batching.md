# 07 - BigQuery Batch Loading (Current Implementation)

**Created:** 2025-11-20 12:30 AM PST
**Last Updated:** 2025-11-20 12:30 AM PST
**Pattern:** BigQuery Batch Loading
**Status:** ✅ **Already Implemented** (analytics_base.py:681-814)
**Impact:** High - 90%+ reduction in API calls, 60%+ faster than row-by-row inserts

---

## Overview

Our analytics processors use **BigQuery Load Jobs** to write data efficiently in a single batch operation. This is built into `AnalyticsProcessorBase` and happens automatically - no additional code needed!

**What it does:**
- Collects all transformed data in memory
- Converts to NDJSON format
- Writes entire dataset in **one BigQuery Load Job**
- Handles schema validation and error notifications

**Why it's effective:**
- ✅ **Single API call** per processor run (not one per row)
- ✅ **Load Jobs are faster** than streaming inserts for batch data
- ✅ **Automatic** - every processor inherits this behavior
- ✅ **Schema enforcement** - validates against table schema
- ✅ **Error handling** - handles streaming buffer conflicts gracefully

---

## How It Works

### Automatic Batch Loading

When you create an analytics processor, batch loading is **already enabled**:

```python
# data_processors/analytics/player_game_summary/player_game_summary_processor.py
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    """Batch loading is automatic - no setup needed!"""

    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'

    def calculate_analytics(self) -> None:
        """Your business logic here."""
        # Process data for date range
        results = []

        for game in self.raw_data:
            # Calculate metrics
            result = {
                'player_id': game['player_id'],
                'points': game['points'],
                'game_date': game['game_date'],
                # ... more fields ...
                **self.build_source_tracking_fields()
            }
            results.append(result)

        # Store results - will be batch loaded automatically
        self.transformed_data = results

    # No need to override save_analytics() - batch loading is automatic!
```

### What Happens Behind The Scenes

```python
# analytics_base.py:681-814 (simplified view)
def save_analytics(self) -> None:
    """
    Automatically called after calculate_analytics().
    Batch loads all data in ONE operation.
    """
    # 1. Get all transformed data
    rows = self.transformed_data  # Could be 450 rows

    # 2. Apply MERGE_UPDATE strategy if needed
    if self.processing_strategy == 'MERGE_UPDATE':
        self._delete_existing_data_batch(rows)  # Delete old data

    # 3. Convert to NDJSON format
    ndjson_data = "\n".join(json.dumps(row) for row in rows)
    ndjson_bytes = ndjson_data.encode('utf-8')

    # 4. Create Load Job with schema validation
    job_config = bigquery.LoadJobConfig(
        schema=table_schema,  # Validates against table
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )

    # 5. Single batch write (ALL rows at once)
    load_job = self.bq_client.load_table_from_file(
        io.BytesIO(ndjson_bytes),
        table_id,
        job_config=job_config
    )

    # 6. Wait for completion
    load_job.result()
    logger.info(f"✅ Successfully loaded {len(rows)} rows")
```

---

## Performance Characteristics

### Our Implementation (Load Jobs)

**Typical processor run (450 player records):**
```
Extract:    5 seconds  (query raw tables)
Transform:  3 seconds  (calculate metrics)
Load:       2 seconds  (single Load Job) ← BATCH LOADING
───────────────────────
Total:     10 seconds
API calls:  1
```

### Alternative: Row-by-Row Inserts (DON'T DO THIS)

**If we wrote rows individually:**
```
Extract:    5 seconds
Transform:  3 seconds
Load:      120 seconds (450 × streaming insert) ← SLOW!
───────────────────────
Total:     128 seconds (12.8x slower!)
API calls: 450 (450x more!)
```

### Improvement

- **12.8x faster writes** (2s vs 120s)
- **99.8% fewer API calls** (1 vs 450)
- **Lower BigQuery costs** (fewer operations)
- **Less quota usage** (single operation)

---

## Real-World Example

### Player Game Summary Processor

```python
# This processor writes ~200-450 player records per day
# Batch loading handles it in ONE operation

class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'

    def get_dependencies(self) -> dict:
        """Define Phase 2 data sources."""
        return {
            'nba_raw.nbac_gamebook_player_stats': {
                'date_field': 'game_date',
                'critical': True
            },
            'nba_raw.bdl_player_boxscores': {
                'date_field': 'game_date',
                'critical': True
            }
        }

    def calculate_analytics(self) -> None:
        """Process ~200-450 players."""
        results = []

        # Process each player's game
        for _, row in self.raw_data.iterrows():
            result = {
                'universal_player_id': self._get_player_id(row),
                'game_date': row['game_date'],
                'points': row['pts'],
                'rebounds': row['reb'],
                'assists': row['ast'],
                'plus_minus': row.get('plus_minus'),
                # ... 30+ more fields ...
                **self.build_source_tracking_fields()
            }
            results.append(result)

        # Store results
        self.transformed_data = results
        # ✅ save_analytics() is called automatically
        # ✅ All ~450 rows written in SINGLE Load Job
        # ✅ Takes ~2 seconds total
```

**Execution log:**
```
INFO: Processing date range 2025-11-18 to 2025-11-18
INFO: Extracted 245 records from Phase 2 sources
INFO: Calculated analytics for 245 players
INFO: Inserting 245 rows to nba_analytics.player_game_summary using batch INSERT
INFO: Using schema with 48 fields
INFO: ✅ Successfully loaded 245 rows
INFO: Total duration: 8.3 seconds
```

---

## Key Features

### 1. Automatic Schema Validation

```python
# analytics_base.py:750-756
table = self.bq_client.get_table(table_id)
table_schema = table.schema
logger.info(f"Using schema with {len(table_schema)} fields")

# Load job validates against schema
job_config = bigquery.LoadJobConfig(
    schema=table_schema,  # Ensures data matches table
    autodetect=False      # Strict validation
)
```

**Benefits:**
- Catches schema mismatches before writing
- Ensures data types are correct
- Prevents partial writes from bad data

### 2. Streaming Buffer Conflict Handling

```python
# analytics_base.py:785-792
except Exception as load_e:
    if "streaming buffer" in str(load_e).lower():
        logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
        logger.info("Records will be processed on next run")
        self.stats["rows_skipped"] = len(rows)
        return  # Graceful skip
    else:
        raise load_e
```

**What this means:**
- BigQuery has a streaming buffer that can block Load Jobs
- We detect this specific error and skip gracefully
- Next processor run will succeed (buffer cleared)
- Prevents spurious failures

### 3. MERGE_UPDATE Strategy Support

```python
# analytics_base.py:735-741
if self.processing_strategy == 'MERGE_UPDATE':
    self._delete_existing_data_batch(rows)
    # Then: batch INSERT new data
```

**How it works:**
1. Delete existing records for date range
2. Insert all new records in batch
3. Allows multi-pass enrichment (Pass 1: basic stats, Pass 2: shot zones)

### 4. Comprehensive Error Notifications

```python
# analytics_base.py:797-814
except Exception as e:
    notify_error(
        title=f"Analytics Processor Batch Insert Failed: {self.__class__.__name__}",
        message=f"Failed to batch insert {len(rows)} analytics rows",
        details={
            'processor': self.__class__.__name__,
            'table': table_id,
            'rows_attempted': len(rows),
            'error_type': type(e).__name__,
            'error': str(e),
            'date_range': f"{start_date} to {end_date}"
        }
    )
    raise
```

**Benefits:**
- Detailed error context in Cloud Logging
- Helps debug issues quickly
- Includes all relevant metadata

---

## When Our Implementation is Optimal

Our **single batch Load Job** approach is perfect for:

✅ **Date range processing** (our current architecture)
- Process 1 day or 7 days of data
- All data collected before writing
- Single batch write at end

✅ **Offline/scheduled processing**
- Cloud Scheduler triggers processor
- Not time-sensitive (can wait 2 seconds for batch)
- Predictable data volumes

✅ **Medium data volumes (100-10,000 rows)**
- Load Jobs are efficient for this range
- Single operation is simple and fast
- No progressive batching needed

✅ **Schema-validated data**
- Table schema is known
- Data must match schema exactly
- Validation before write is valuable

---

## When You'd Need Progressive Batching

The pattern document shows **progressive batching** (500 rows at a time with time-based flushing). This is better for:

❌ **Real-time streaming** (not our architecture)
- Continuous data flow
- Process each record immediately
- Can't wait to collect full batch

❌ **Very large datasets (100k+ rows)**
- Load Job might timeout
- Need to chunk into smaller batches
- Progressive writes reduce memory

❌ **Long-running processors (> 30 minutes)**
- Risk of timeout before write
- Need periodic checkpoints
- Progressive batching reduces loss

**Our processors don't have these characteristics**, so our simpler approach is better!

---

## Load Jobs vs Streaming Inserts

### Load Jobs (What We Use)

**Characteristics:**
- Batch operation (all rows at once)
- Uses `load_table_from_file()`
- Fast for batch data (100-10k rows)
- Schema validation required
- May be blocked by streaming buffer

**Best for:**
- Scheduled/offline processing (✅ us)
- Predictable data volumes
- When you have all data upfront

**Cost:** Free up to 2TB/day, then $0.02/GB

### Streaming Inserts (Alternative)

**Characteristics:**
- Individual row inserts
- Uses `insert_rows_json()`
- Optimized for real-time
- More flexible schema
- Never blocked by streaming buffer

**Best for:**
- Real-time event processing
- Unpredictable arrival times
- When you need immediate availability

**Cost:** $0.01 per 200MB ($0.05/GB) - 2.5x more expensive

**For our use case:** Load Jobs are cheaper and faster!

---

## Monitoring Batch Loading

### Check Processor Logs

```bash
# See batch loading in action
gcloud logging read "
  resource.type=cloud_run_revision
  jsonPayload.message=~'Successfully loaded.*rows'
" --limit 10 --format json
```

**Example output:**
```
INFO: ✅ Successfully loaded 245 rows
INFO: Total duration: 8.3 seconds
INFO: Records processed: 245
```

### Query Processor Performance

```sql
-- See batch loading performance by processor
SELECT
    processor_name,
    DATE(run_date) as date,
    AVG(duration_seconds) as avg_duration_sec,
    AVG(records_processed) as avg_rows,
    AVG(records_processed / duration_seconds) as rows_per_sec
FROM `nba_processing.analytics_processor_runs`
WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND success = TRUE
GROUP BY processor_name, date
ORDER BY date DESC, avg_rows DESC;
```

**Expected results:**
- Duration: 5-15 seconds typical
- Rows: 100-500 per run
- Throughput: 50-100 rows/sec

### BigQuery Job Monitoring

```sql
-- See BigQuery Load Jobs from our processors
SELECT
    creation_time,
    job_id,
    destination_table.table_id,
    total_bytes_processed,
    total_slot_ms,
    TIMESTAMP_DIFF(end_time, start_time, MILLISECOND) as duration_ms,
    output_rows
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE job_type = 'LOAD'
  AND destination_table.dataset_id = 'nba_analytics'
  AND creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
ORDER BY creation_time DESC
LIMIT 20;
```

---

## Common Patterns

### Pattern 1: Single Date Processing (Most Common)

```python
class YourProcessor(AnalyticsProcessorBase):
    def calculate_analytics(self) -> None:
        # Process one day's data
        results = []
        for record in self.raw_data:
            results.append(self.process_record(record))

        self.transformed_data = results
        # ✅ Batch loaded automatically (1 Load Job)
```

### Pattern 2: Date Range Processing

```python
class YourProcessor(AnalyticsProcessorBase):
    def calculate_analytics(self) -> None:
        # Process multiple days (e.g., last 7 days)
        results = []

        for date in date_range:
            date_data = self.raw_data[self.raw_data['game_date'] == date]
            for record in date_data:
                results.append(self.process_record(record))

        self.transformed_data = results
        # ✅ Batch loaded automatically (1 Load Job for all 7 days)
```

### Pattern 3: Multi-Source Aggregation

```python
class YourProcessor(AnalyticsProcessorBase):
    def calculate_analytics(self) -> None:
        # Combine data from multiple Phase 2 sources
        merged = pd.merge(
            self.source1_data,
            self.source2_data,
            on='player_id',
            how='left'
        )

        results = merged.to_dict('records')
        self.transformed_data = results
        # ✅ Batch loaded automatically
```

### Pattern 4: Incremental Processing with MERGE_UPDATE

```python
class YourProcessor(AnalyticsProcessorBase):
    def __init__(self):
        super().__init__()
        self.processing_strategy = 'MERGE_UPDATE'  # Enable delete-first

    def calculate_analytics(self) -> None:
        # Process data (may overlap with existing)
        results = []
        for record in self.raw_data:
            results.append(self.process_record(record))

        self.transformed_data = results
        # ✅ Old data deleted, then batch loaded
```

---

## Best Practices

### ✅ DO: Let Batch Loading Handle Everything

```python
# Good - simple and efficient
def calculate_analytics(self) -> None:
    results = [self.process(r) for r in self.raw_data]
    self.transformed_data = results
    # Done! Batch loading is automatic
```

### ❌ DON'T: Try to Write Data Yourself

```python
# Bad - bypasses batch loading!
def calculate_analytics(self) -> None:
    for record in self.raw_data:
        result = self.process(record)
        # DON'T DO THIS:
        self.bq_client.insert_rows_json(table, [result])  # ❌ Slow!
```

### ✅ DO: Process All Data Before Storing

```python
# Good - collect everything first
def calculate_analytics(self) -> None:
    results = []
    for record in self.raw_data:
        result = self.process(record)
        results.append(result)  # Collect in memory

    self.transformed_data = results  # Store once
```

### ✅ DO: Include Source Tracking Fields

```python
# Good - always include source tracking
def calculate_analytics(self) -> None:
    results = []
    for record in self.raw_data:
        result = {
            'player_id': record['player_id'],
            'points': record['points'],
            **self.build_source_tracking_fields()  # ✅ Critical!
        }
        results.append(result)

    self.transformed_data = results
```

### ✅ DO: Handle Empty Results Gracefully

```python
# Good - check for empty data
def calculate_analytics(self) -> None:
    results = [self.process(r) for r in self.raw_data if self.is_valid(r)]

    if not results:
        logger.warning("No valid records to process")
        self.transformed_data = []
        return  # save_analytics() handles empty gracefully

    self.transformed_data = results
```

---

## Memory Considerations

### Typical Processor (200-500 rows)

**Memory usage:** ~1-5 MB
- Raw data: ~500 KB
- Transformed data: ~1 MB
- NDJSON encoding: ~1 MB
- **Total:** Well under Cloud Run limits (512 MB default)

### Large Processor (5000+ rows)

**Memory usage:** ~20-50 MB
- Still very manageable
- Load Jobs handle this efficiently
- No need for progressive batching

### When to Worry

**Only if processing 100k+ rows:**
- Consider splitting by date ranges
- Or implement progressive batching (rare for us)
- Or increase Cloud Run memory limit

**For our current processors:** Memory is never an issue!

---

## Troubleshooting

### Issue: "Streaming buffer" Error

```
⚠️ Load blocked by streaming buffer - 245 rows skipped
```

**Cause:** BigQuery's streaming buffer blocks Load Jobs temporarily

**Solution:**
- Automatic retry on next processor run (usually 1 hour later)
- Buffer clears within 90 minutes
- No action needed - gracefully handled

**Prevention:** Use MERGE_UPDATE sparingly (streaming buffer issue)

### Issue: Schema Validation Errors

```
ERROR: Batch insert failed: Field 'player_id' type mismatch
```

**Cause:** Data doesn't match table schema

**Solution:**
1. Check table schema: `bq show nba_analytics.your_table`
2. Validate data types in `calculate_analytics()`
3. Ensure all required fields present

### Issue: Load Job Timeout

```
ERROR: Load job timed out after 10 minutes
```

**Cause:** Very large dataset (rare for us)

**Solution:**
1. Check data volume: `len(self.transformed_data)`
2. If > 100k rows, consider splitting by date
3. Or contact support to increase timeout

**For our processors:** This should never happen (< 10k rows typical)

---

## Summary

**What we have:**
- ✅ Automatic batch loading via Load Jobs
- ✅ Single API call per processor run
- ✅ 12.8x faster than row-by-row inserts
- ✅ Built into AnalyticsProcessorBase
- ✅ Schema validation and error handling
- ✅ No additional code needed!

**Why it's optimal for us:**
- Date range processing (not streaming)
- Offline/scheduled execution
- Medium data volumes (100-10k rows)
- Simple and efficient

**What you need to do:**
- Nothing! Just extend AnalyticsProcessorBase
- Set `self.transformed_data` in calculate_analytics()
- Batch loading happens automatically

**Implementation location:**
- data_processors/analytics/analytics_base.py:681-814

---

## References

- [AnalyticsProcessorBase Implementation](../../data_processors/analytics/analytics_base.py) - Lines 681-814
- [Player Game Summary Example](../../data_processors/analytics/player_game_summary/player_game_summary_processor.py) - Real usage
- [BigQuery Load Jobs Documentation](https://cloud.google.com/bigquery/docs/loading-data) - Google's guide
- [Optimization Pattern Catalog](../reference/02-optimization-pattern-catalog.md) - Pattern #9

---

**Remember:** Batch loading is automatic - you get this performance for free by extending AnalyticsProcessorBase!
