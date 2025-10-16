# Creating Raw Processor Backfill Jobs

**Last Updated:** January 2025  
**Maintained By:** NBA Props Platform Team

---

## Overview

Raw processor backfill jobs read scraped data from Google Cloud Storage (GCS) and load it into BigQuery `nba_raw` tables with minimal transformation. These jobs form **Phase 2** of the data pipeline.

**What Raw Processors Do:**
- Read raw JSON/HTML/PDF files from GCS
- Parse and normalize data structure
- Validate required fields
- Load to BigQuery `nba_raw` tables
- Track data quality and processing metadata

**What Raw Processors DON'T Do:**
- Complex analytics or derived metrics (that's Phase 3)
- Aggregations or joins across multiple sources
- Business logic calculations
- Feature engineering

---

## When to Create a Raw Processor Backfill

Create a raw processor backfill when:

✅ **New scraper data needs processing** - A new scraper is collecting data that needs to be loaded to BigQuery  
✅ **Schema changes require reprocessing** - BigQuery table schema changed and historical data needs to be reprocessed  
✅ **Data quality improvements** - Enhanced parsing logic needs to be applied to historical data  
✅ **Backfilling gaps** - Missing data needs to be processed from existing GCS files  

---

## Raw Processor Architecture

### Data Flow

```
GCS Raw Files                    BigQuery nba_raw
┌─────────────────┐             ┌──────────────────────┐
│ JSON/HTML/PDF   │             │ Structured Tables    │
│ from Scrapers   │  ────────▶  │ Ready for Analytics  │
│ (unprocessed)   │             │ (normalized schema)  │
└─────────────────┘             └──────────────────────┘
```

**Process Steps:**
1. **List Files** - Scan GCS for files in date range
2. **Resume Check** - Skip files already processed (optional)
3. **Download & Parse** - Read file content, parse JSON
4. **Transform** - Normalize to BigQuery schema
5. **Validate** - Check required fields, data quality
6. **Load** - Insert rows to BigQuery

### Integration with Processor Classes

Raw processor backfills use **processor classes** that handle transformation and loading:

```python
from data_processors.raw.balldontlie.bdl_injuries_processor import BdlInjuriesProcessor

class BdlInjuriesBackfill:
    def __init__(self):
        self.processor = BdlInjuriesProcessor()  # Reuses existing processor logic
    
    def process_file(self, file_path):
        # Download and parse
        raw_data = self.download_file(file_path)
        
        # Transform using processor
        rows = self.processor.transform_data(raw_data, file_path)
        
        # Load using processor
        result = self.processor.load_data(rows)
```

**Benefits:**
- Backfill and real-time processing use same logic
- Changes to processing logic automatically apply to backfills
- Reduced code duplication
- Consistent data quality

---

## Creating a New Raw Processor Backfill

### Directory Structure

```
backfill_jobs/raw/my_new_processor/
├── my_new_processor_raw_backfill.py   # Main backfill script
├── deploy.sh                           # Deployment wrapper
├── job-config.env                      # Resource configuration
└── README.md                           # Job-specific documentation (optional)
```

### Step 1: Create the Processor Class

First, ensure you have a processor class in `data_processors/raw/`:

```python
# data_processors/raw/mysource/my_processor.py

from data_processors.raw.processor_base import ProcessorBase
from google.cloud import bigquery

class MyProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.my_table'
        self.processing_strategy = 'APPEND_ALWAYS'  # or 'MERGE_UPDATE'
        self.bq_client = bigquery.Client()
    
    def validate_data(self, data: dict) -> list:
        """Validate JSON structure."""
        errors = []
        if 'required_field' not in data:
            errors.append("Missing required_field")
        return errors
    
    def transform_data(self, raw_data: dict, file_path: str) -> list:
        """Transform to BigQuery rows."""
        rows = []
        # Transform logic here
        return rows
    
    def load_data(self, rows: list, **kwargs) -> dict:
        """Load to BigQuery."""
        # Loading logic here
        return {'rows_processed': len(rows), 'errors': []}
```

### Step 2: Create the Backfill Script

**Complete Template:**

```python
#!/usr/bin/env python3
"""
File: backfill_jobs/raw/my_processor/my_processor_raw_backfill.py

Description: Process [data source] from GCS to BigQuery
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.raw.mysource.my_processor import MyProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MyProcessorBackfill:
    """Backfill [data source] from GCS to BigQuery."""
    
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = MyProcessor()
        
        # GCS path pattern - CUSTOMIZE THIS
        self.gcs_prefix = "my-source/my-data"
    
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            prefix = f"{self.gcs_prefix}/{date_str}/"
            
            logger.info(f"Scanning: gs://{self.bucket_name}/{prefix}")
            
            blobs = bucket.list_blobs(prefix=prefix)
            date_files = []
            
            for blob in blobs:
                if blob.name.endswith('.json'):  # Adjust extension as needed
                    file_path = f"gs://{self.bucket_name}/{blob.name}"
                    date_files.append(file_path)
            
            if date_files:
                logger.info(f"Found {len(date_files)} files for {date_str}")
                all_files.extend(date_files)
            else:
                logger.debug(f"No files for {date_str}")
            
            current_date += timedelta(days=1)
        
        logger.info(f"Total files to process: {len(all_files)}")
        return sorted(all_files)
    
    def process_file(self, file_path: str) -> Dict:
        """Process a single file."""
        try:
            logger.info(f"Processing: {file_path}")
            
            # Download file
            blob_name = file_path.replace(f"gs://{self.bucket_name}/", "")
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_name)
            
            if not blob.exists():
                logger.error(f"File not found: {file_path}")
                return {'status': 'not_found', 'file': file_path}
            
            # Parse JSON
            json_content = blob.download_as_text()
            raw_data = json.loads(json_content)
            
            # Validate
            errors = self.processor.validate_data(raw_data)
            if errors:
                logger.warning(f"Validation errors in {file_path}: {errors}")
                return {'status': 'validation_failed', 'errors': errors, 'file': file_path}
            
            # Transform
            rows = self.processor.transform_data(raw_data, file_path)
            
            if not rows:
                logger.warning(f"No data from {file_path}")
                return {'status': 'no_data', 'file': file_path}
            
            # Load
            result = self.processor.load_data(rows)
            
            if result['errors']:
                logger.error(f"Load errors for {file_path}: {result['errors']}")
                return {
                    'status': 'error',
                    'file': file_path,
                    'errors': result['errors']
                }
            
            logger.info(f"✅ Processed {result['rows_processed']} rows from {file_path}")
            return {
                'status': 'success',
                'file': file_path,
                'rows_processed': result['rows_processed']
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON error in {file_path}: {e}")
            return {'status': 'json_error', 'error': str(e), 'file': file_path}
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return {'status': 'error', 'error': str(e), 'file': file_path}
    
    def run_backfill(self, start_date: date, end_date: date, 
                     dry_run: bool = False, limit: int = None) -> Dict:
        """Run the backfill process."""
        
        logger.info(f"=== [Data Source] Backfill ===")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Dry run: {dry_run}")
        logger.info(f"Limit: {limit}")
        
        # List files
        files = self.list_files(start_date, end_date)
        
        if limit:
            files = files[:limit]
            logger.info(f"Limited to first {limit} files")
        
        if dry_run:
            logger.info("=== DRY RUN MODE ===")
            logger.info(f"Would process {len(files)} files:")
            for i, file_path in enumerate(files[:10], 1):
                logger.info(f"  {i}. {file_path}")
            if len(files) > 10:
                logger.info(f"  ... and {len(files) - 10} more files")
            return {'total_files': len(files), 'processed': 0, 'errors': 0}
        
        # Process files
        successful = 0
        failed = 0
        total_rows = 0
        
        for i, file_path in enumerate(files, 1):
            logger.info(f"[{i}/{len(files)}] Processing file...")
            
            result = self.process_file(file_path)
            
            if result['status'] == 'success':
                successful += 1
                total_rows += result.get('rows_processed', 0)
            else:
                failed += 1
            
            # Progress logging
            if i % 50 == 0 or i == len(files):
                logger.info(f"Progress: {i}/{len(files)} files processed "
                           f"({successful} successful, {failed} failed)")
        
        # Summary
        logger.info(f"=== Backfill Complete ===")
        logger.info(f"Total files: {len(files)}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Total rows: {total_rows}")
        
        return {
            'total_files': len(files),
            'processed': successful,
            'errors': failed,
            'total_rows': total_rows
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Backfill [data source] from GCS to BigQuery'
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files')
    parser.add_argument('--bucket', type=str, default='nba-scraped-data', help='GCS bucket')
    
    args = parser.parse_args()
    
    # Parse dates with defaults
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date(2021, 10, 1)
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date.today()
    
    if start_date > end_date:
        logger.error("Start date must be before or equal to end date")
        sys.exit(1)
    
    # Run backfill
    backfiller = MyProcessorBackfill(bucket_name=args.bucket)
    result = backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
        limit=args.limit
    )
    
    # Exit with error if there were failures
    if result['errors'] > 0:
        logger.warning(f"Completed with {result['errors']} errors")
        sys.exit(1)
    else:
        logger.info("Backfill completed successfully")
        sys.exit(0)


if __name__ == "__main__":
    main()
```

### Step 3: Create job-config.env

```bash
# Job identification
JOB_NAME="my-processor-backfill"
JOB_SCRIPT="backfill_jobs/raw/my_processor/my_processor_raw_backfill.py"
JOB_DESCRIPTION="Process [data source] from GCS to BigQuery"

# Resources
TASK_TIMEOUT="1800"  # 30 minutes
MEMORY="2Gi"
CPU="1"

# Default parameters
START_DATE="2021-10-01"
END_DATE="2025-06-30"
BUCKET_NAME="nba-scraped-data"

# Infrastructure
REGION="us-west2"
SERVICE_ACCOUNT="nba-scrapers@nba-props-platform.iam.gserviceaccount.com"
```

### Step 4: Create deploy.sh

```bash
#!/bin/bash
# FILE: backfill_jobs/raw/my_processor/deploy.sh

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

start_deployment_timer

echo "Deploying My Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh my_processor

print_section_header "Test Commands"
echo "  # Dry run:"
echo "  gcloud run jobs execute my-processor-backfill --args=--dry-run,--limit=5 --region=us-west2"
echo ""
echo "  # Small test:"
echo "  gcloud run jobs execute my-processor-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Date range:"
echo "  gcloud run jobs execute my-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""

print_deployment_summary
```

Make it executable:
```bash
chmod +x backfill_jobs/raw/my_processor/deploy.sh
```

---

## Common Patterns

### Pattern 1: Simple Sequential Processing

**Use Case:** Small files, straightforward parsing, no dependencies

**Example: BDL Injuries**

```python
def run_backfill(self, start_date, end_date, dry_run=False, limit=None):
    files = self.list_files(start_date, end_date)
    
    if limit:
        files = files[:limit]
    
    for file_path in files:
        result = self.process_file(file_path)
        # Handle result
```

**Characteristics:**
- One file at a time
- Simple error handling
- Good for light processing loads
- Easy to debug

### Pattern 2: With Retry Logic

**Use Case:** Network issues, transient errors, API rate limits

**Example: BDL Boxscores**

```python
from google.api_core import retry

class MyBackfill:
    @retry.Retry()
    def list_files(self, start_date, end_date):
        """List files with automatic retry on failure."""
        # Implementation
    
    @retry.Retry()
    def download_and_process_file(self, file_path):
        """Process with retry on transient errors."""
        # Implementation
```

**Benefits:**
- Automatically retries on transient failures
- Exponential backoff
- Configurable retry conditions

### Pattern 3: Parallel Processing with Batching

**Use Case:** Large number of files, I/O bound processing

**Example: Odds API Props**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_WORKERS = 4
BATCH_SIZE = 100

def process_batch(self, files, batch_num, total_batches):
    """Process a batch of files in parallel."""
    results = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_file = {
            executor.submit(self.process_file, f): f 
            for f in files
        }
        
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                result = future.result(timeout=60)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed: {file_path}: {e}")
    
    return results

def run_backfill(self, start_date, end_date):
    files = self.list_files(start_date, end_date)
    
    # Process in batches
    for i in range(0, len(files), BATCH_SIZE):
        batch = files[i:i + BATCH_SIZE]
        batch_results = self.process_batch(batch, i//BATCH_SIZE + 1, len(files)//BATCH_SIZE)
```

**Benefits:**
- Much faster for large backlogs
- Better resource utilization
- Progress tracking per batch

**Considerations:**
- More memory usage
- Harder to debug
- Need thread-safe code

### Pattern 4: Special Processing Features

**Use Case:** Complex requirements, filtering, finalization

**Example: NBA.com Gamebook**

```python
def list_files(self, start_date, end_date, team_filter=None):
    """List files with optional team filtering."""
    all_files = []
    
    for current_date in date_range(start_date, end_date):
        files = self.get_files_for_date(current_date)
        
        # Apply team filter
        if team_filter:
            files = [f for f in files if self.file_matches_teams(f, team_filter)]
        
        all_files.extend(files)
    
    return all_files

def process_file(self, file_path, file_index, total_files):
    """Process with progress tracking and finalization."""
    # Progress logging
    if file_index % 50 == 0:
        logger.info(f"Progress: {file_index}/{total_files}")
    
    # Process file
    result = self.processor.transform_data(data, file_path)
    
    # Mark final batch for finalization
    is_final_batch = (file_index == total_files)
    self.processor.load_data(result, is_final_batch=is_final_batch)
```

**Features:**
- Team/game filtering
- Finalization hooks
- Progress tracking
- Custom batch handling

---

## Resume Logic

Resume logic prevents reprocessing already-processed data.

### Strategy 1: Check BigQuery for Existing Records

**When to Use:** When you can uniquely identify records

```python
def date_already_processed(self, process_date: date) -> bool:
    """Check if date already processed in BigQuery."""
    query = f"""
    SELECT COUNT(*) as count
    FROM `{self.project_id}.{self.table_name}`
    WHERE game_date = '{process_date.isoformat()}'
    """
    
    result = list(self.bq_client.query(query))[0]
    exists = result.count > 0
    
    if exists:
        logger.info(f"Skipping {process_date} - already processed")
    
    return exists

def list_files(self, start_date, end_date):
    """List files, skipping already processed dates."""
    all_files = []
    
    current_date = start_date
    while current_date <= end_date:
        if not self.date_already_processed(current_date):
            files = self.get_files_for_date(current_date)
            all_files.extend(files)
        
        current_date += timedelta(days=1)
    
    return all_files
```

### Strategy 2: Check Source File Path

**When to Use:** When tracking which files have been processed

```python
def file_already_processed(self, file_path: str) -> bool:
    """Check if specific file already processed."""
    query = f"""
    SELECT COUNT(*) as count
    FROM `{self.project_id}.{self.table_name}`
    WHERE source_file_path = '{file_path}'
    """
    
    result = list(self.bq_client.query(query))[0]
    return result.count > 0
```

### Strategy 3: No Resume Logic

**When to Use:** 
- APPEND_ALWAYS strategy (tracking all changes over time)
- Small datasets where reprocessing is acceptable
- When you want to reload data with updated processing logic

```python
def run_backfill(self, start_date, end_date):
    """Process all files without checking for existing data."""
    files = self.list_files(start_date, end_date)
    
    for file_path in files:
        # Process every file regardless
        self.process_file(file_path)
```

---

## Data Validation

Always validate data before loading to BigQuery.

### Required Field Validation

```python
def validate_data(self, data: dict) -> List[str]:
    """Validate required fields exist."""
    errors = []
    
    required_fields = ['field1', 'field2', 'field3']
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")
    
    # Check data types
    if not isinstance(data.get('array_field'), list):
        errors.append("'array_field' must be a list")
    
    # Check not empty
    if not data.get('items'):
        errors.append("'items' array is empty")
    
    return errors
```

### Data Quality Validation

```python
def transform_data(self, raw_data: dict, file_path: str) -> List[dict]:
    """Transform with quality checks."""
    rows = []
    quality_issues = []
    
    for item in raw_data['items']:
        # Check for invalid values
        if not item.get('player_name'):
            quality_issues.append({'issue': 'missing_player_name', 'item': item})
            continue
        
        # Check for data anomalies
        points = item.get('points', 0)
        if points < 0 or points > 200:
            quality_issues.append({
                'issue': 'invalid_points',
                'value': points,
                'player': item.get('player_name')
            })
        
        rows.append(self.transform_item(item))
    
    # Log quality issues
    if quality_issues:
        logger.warning(f"Found {len(quality_issues)} quality issues in {file_path}")
        for issue in quality_issues[:5]:  # Log first 5
            logger.warning(f"  {issue}")
    
    return rows
```

---

## BigQuery Integration

### Processing Strategies

**APPEND_ALWAYS** - Add all new data, keep historical versions

```python
class MyProcessor(ProcessorBase):
    def __init__(self):
        self.processing_strategy = 'APPEND_ALWAYS'
    
    def load_data(self, rows: List[dict]) -> dict:
        """Simply append rows."""
        table_id = f"{self.project_id}.{self.table_name}"
        result = self.bq_client.insert_rows_json(table_id, rows)
        
        return {
            'rows_processed': len(rows),
            'errors': result if result else []
        }
```

**MERGE_UPDATE** - Replace existing data with updated versions

```python
class MyProcessor(ProcessorBase):
    def __init__(self):
        self.processing_strategy = 'MERGE_UPDATE'
    
    def load_data(self, rows: List[dict]) -> dict:
        """Delete old data, insert new data."""
        table_id = f"{self.project_id}.{self.table_name}"
        
        # Get unique identifiers
        game_ids = set(row['game_id'] for row in rows)
        
        # Delete existing records
        for game_id in game_ids:
            delete_query = f"""
            DELETE FROM `{table_id}` 
            WHERE game_id = '{game_id}'
            AND DATETIME_DIFF(CURRENT_DATETIME(), DATETIME(processed_at), MINUTE) >= 90
            """
            self.bq_client.query(delete_query).result()
        
        # Insert new records
        result = self.bq_client.insert_rows_json(table_id, rows)
        
        return {
            'rows_processed': len(rows),
            'errors': result if result else []
        }
```

### Handling Streaming Buffer

BigQuery's streaming buffer prevents immediate DML operations on recently inserted data.

**Problem:** You can't delete rows inserted in the last 90 minutes via streaming.

**Solution 1: Check Age Before Deleting**

```python
def safe_delete_existing_data(self, table_id: str, game_id: str) -> dict:
    """Only delete data older than 90 minutes."""
    delete_query = f"""
    DELETE FROM `{table_id}` 
    WHERE game_id = '{game_id}'
    AND DATETIME_DIFF(CURRENT_DATETIME(), DATETIME(processed_at), MINUTE) >= 90
    """
    
    try:
        result = self.bq_client.query(delete_query).result()
        return {'success': True, 'streaming_conflict': False}
    except Exception as e:
        if 'streaming buffer' in str(e).lower():
            logger.warning(f"Streaming buffer prevents deletion: {game_id}")
            return {'success': False, 'streaming_conflict': True}
        raise
```

**Solution 2: Use Batch Loading (Recommended)**

```python
def load_data(self, rows: List[dict]) -> dict:
    """Use batch loading instead of streaming insert."""
    import tempfile
    import json
    
    table_id = f"{self.project_id}.{self.table_name}"
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
        for row in rows:
            f.write(json.dumps(row) + '\n')
        f.flush()
        
        # Batch load (no streaming buffer!)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND
        )
        
        with open(f.name, 'rb') as source_file:
            load_job = self.bq_client.load_table_from_file(
                source_file, table_id, job_config=job_config
            )
            load_job.result()  # Wait for completion
    
    logger.info(f"✅ Batch loaded {len(rows)} rows (no streaming buffer)")
    return {'rows_processed': len(rows), 'errors': []}
```

### Batch Insert for Performance

```python
def load_data_in_batches(self, rows: List[dict], batch_size: int = 500) -> dict:
    """Insert rows in batches for better performance."""
    table_id = f"{self.project_id}.{self.table_name}"
    total_processed = 0
    all_errors = []
    
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        
        result = self.bq_client.insert_rows_json(table_id, batch)
        
        if result:
            all_errors.extend(result)
        else:
            total_processed += len(batch)
        
        if (i // batch_size + 1) % 10 == 0:
            logger.info(f"Loaded {i + len(batch)}/{len(rows)} rows")
    
    return {
        'rows_processed': total_processed,
        'errors': all_errors
    }
```

---

## Testing Raw Processor Backfills

### Local Testing

```bash
# 1. Test with dry run
./bin/run_backfill.sh raw/my_processor --dry-run --limit=10

# 2. Process 1 file
./bin/run_backfill.sh raw/my_processor --limit=1

# 3. Process 1 day
./bin/run_backfill.sh raw/my_processor \
  --start-date=2024-10-01 \
  --end-date=2024-10-01

# 4. Process 1 week
./bin/run_backfill.sh raw/my_processor \
  --start-date=2024-10-01 \
  --end-date=2024-10-07
```

### Cloud Run Testing

```bash
# 1. Deploy the job
cd backfill_jobs/raw/my_processor
./deploy.sh

# 2. Dry run test
gcloud run jobs execute my-processor-backfill \
  --args=--dry-run,--limit=10 \
  --region=us-west2

# 3. Small test (5 files)
gcloud run jobs execute my-processor-backfill \
  --args=--limit=5 \
  --region=us-west2

# 4. One day test
gcloud run jobs execute my-processor-backfill \
  --args=--start-date=2024-10-01,--end-date=2024-10-01 \
  --region=us-west2

# 5. Full backfill (after testing!)
gcloud run jobs execute my-processor-backfill \
  --region=us-west2
```

### Validation Queries

After processing, validate the results:

```sql
-- Check row counts
SELECT 
  COUNT(*) as total_rows,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  COUNT(DISTINCT game_id) as unique_games
FROM `nba-props-platform.nba_raw.my_table`;

-- Check recent data
SELECT 
  game_date,
  COUNT(*) as row_count
FROM `nba-props-platform.nba_raw.my_table`
WHERE DATE(processed_at) = CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 10;

-- Check for nulls in key fields
SELECT 
  COUNT(*) as total_rows,
  COUNTIF(player_name IS NULL) as null_player_names,
  COUNTIF(game_id IS NULL) as null_game_ids,
  COUNTIF(team_abbr IS NULL) as null_teams
FROM `nba-props-platform.nba_raw.my_table`;

-- Check data quality
SELECT 
  MIN(points) as min_points,
  MAX(points) as max_points,
  AVG(points) as avg_points,
  COUNTIF(points < 0) as negative_points,
  COUNTIF(points > 100) as excessive_points
FROM `nba-props-platform.nba_raw.my_table`;
```

---

## Common Issues and Solutions

### Issue: "File not found" errors

**Problem:** GCS files don't exist at expected path

**Solution:**
```bash
# Check what files actually exist
gsutil ls gs://nba-scraped-data/my-source/my-data/2024-10-01/ | head -20

# Verify file path pattern
gsutil ls gs://nba-scraped-data/my-source/** | grep 2024-10 | head -20
```

### Issue: JSON parsing errors

**Problem:** Invalid JSON in GCS file

**Solution:**
```python
def process_file(self, file_path):
    try:
        json_content = blob.download_as_text()
        raw_data = json.loads(json_content)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {file_path}: {e}")
        logger.error(f"Content preview: {json_content[:200]}")
        
        # Log to error tracking file
        self.log_error_file(file_path, 'json_parse_error', str(e))
        return {'status': 'json_error', 'file': file_path}
```

### Issue: BigQuery schema mismatch

**Problem:** Data doesn't match table schema

**Solution:**
```python
def transform_data(self, raw_data, file_path):
    rows = []
    
    for item in raw_data['items']:
        try:
            row = {
                # Ensure correct data types
                'game_id': str(item['game_id']),
                'points': int(item.get('points', 0)),
                'player_name': str(item['player_name']),
                'game_date': self.parse_date(item['date']).isoformat(),
                # Handle nullable fields
                'minutes': float(item['minutes']) if item.get('minutes') else None
            }
            rows.append(row)
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Schema mismatch for item: {item}")
            logger.error(f"Error: {e}")
            continue
    
    return rows
```

### Issue: Duplicate data

**Problem:** Same data processed multiple times

**Solution:**
```python
# Add resume logic to skip already-processed data
def list_files(self, start_date, end_date):
    all_files = []
    
    for current_date in date_range(start_date, end_date):
        # Check if date already processed
        if self.date_already_processed(current_date):
            logger.info(f"Skipping {current_date} - already processed")
            continue
        
        files = self.get_files_for_date(current_date)
        all_files.extend(files)
    
    return all_files

# Or use MERGE_UPDATE strategy to replace existing data
```

### Issue: Memory errors

**Problem:** Processing too much data at once

**Solution:**
```python
# Process in smaller batches
def run_backfill(self, start_date, end_date):
    current_date = start_date
    
    while current_date <= end_date:
        # Process one day at a time
        day_files = self.get_files_for_date(current_date)
        
        for file_path in day_files:
            self.process_file(file_path)
        
        logger.info(f"Completed {current_date}")
        current_date += timedelta(days=1)
```

---

## Best Practices

### Code Organization

✅ **DO:**
- Keep backfill script separate from processor class
- Reuse processor logic between backfill and real-time
- Use clear, descriptive variable names
- Add helpful logging at key points

❌ **DON'T:**
- Duplicate transformation logic
- Mix backfill orchestration with data processing
- Process files without validation
- Ignore errors silently

### Error Handling

✅ **DO:**
```python
def process_file(self, file_path):
    try:
        # Processing logic
        result = self.processor.transform_data(data, file_path)
        return {'status': 'success', 'rows': len(result)}
    except json.JSONDecodeError as e:
        logger.error(f"JSON error in {file_path}: {e}")
        return {'status': 'json_error', 'error': str(e)}
    except Exception as e:
        logger.error(f"Unexpected error in {file_path}: {e}")
        return {'status': 'error', 'error': str(e)}
```

❌ **DON'T:**
```python
def process_file(self, file_path):
    # No error handling - will crash on any error
    data = json.loads(blob.download_as_text())
    result = self.processor.transform_data(data, file_path)
    return result
```

### Logging

✅ **DO:**
```python
# Progress tracking
logger.info(f"Processing {i}/{total} files")

# Milestones
logger.info(f"Completed {current_date}")

# Errors with context
logger.error(f"Failed to process {file_path}: {error}")

# Summary statistics
logger.info(f"Processed {successful}/{total} files successfully")
```

### Data Quality

✅ **DO:**
```python
# Track quality metrics
quality_metrics = {
    'missing_player_names': 0,
    'invalid_dates': 0,
    'null_teams': 0
}

# Validate and track
for item in data['items']:
    if not item.get('player_name'):
        quality_metrics['missing_player_names'] += 1

# Log summary
logger.info(f"Quality metrics: {quality_metrics}")
```

### Performance

✅ **DO:**
- Use batch inserts (500-1000 rows per batch)
- Consider parallel processing for large datasets
- Log progress every 50-100 files
- Use resume logic to avoid reprocessing

❌ **DON'T:**
- Insert one row at a time
- Load entire dataset into memory
- Process without progress tracking
- Reprocess already-loaded data

---

## Complete Examples

### Example 1: Simple Processor (BDL Injuries Pattern)

**Best for:** Small files, simple structure, infrequent updates

```python
class BdlInjuriesBackfill:
    def __init__(self):
        self.storage_client = storage.Client()
        self.processor = BdlInjuriesProcessor()
        self.gcs_prefix = "ball-dont-lie/injuries"
    
    def list_files(self, start_date, end_date):
        """List files by date."""
        all_files = []
        current_date = start_date
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            prefix = f"{self.gcs_prefix}/{date_str}/"
            
            blobs = self.bucket.list_blobs(prefix=prefix)
            for blob in blobs:
                if blob.name.endswith('.json'):
                    all_files.append(f"gs://{self.bucket_name}/{blob.name}")
            
            current_date += timedelta(days=1)
        
        return sorted(all_files)
    
    def process_file(self, file_path):
        """Process single file."""
        # Download and parse
        blob = self.bucket.blob(file_path.replace(f"gs://{self.bucket_name}/", ""))
        raw_data = json.loads(blob.download_as_text())
        
        # Transform
        rows = self.processor.transform_data(raw_data, file_path)
        
        # Load
        result = self.processor.load_data(rows)
        return result
    
    def run_backfill(self, start_date, end_date, dry_run=False, limit=None):
        """Run backfill."""
        files = self.list_files(start_date, end_date)
        
        if limit:
            files = files[:limit]
        
        if dry_run:
            logger.info(f"Would process {len(files)} files")
            return
        
        for i, file_path in enumerate(files, 1):
            self.process_file(file_path)
            
            if i % 50 == 0:
                logger.info(f"Processed {i}/{len(files)} files")
```

### Example 2: Parallel Processing (Odds API Props Pattern)

**Best for:** Many files, I/O bound, need speed

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

class OddsApiPropsBackfill:
    MAX_WORKERS = 4
    BATCH_SIZE = 100
    
    def process_file(self, file_path):
        """Process single file with retry logic."""
        try:
            blob = self.bucket.blob(file_path)
            data = json.loads(blob.download_as_text())
            
            rows = self.processor.transform_data(data, file_path)
            result = self.processor.load_data(rows)
            
            return {'status': 'success', 'file': file_path, 'rows': len(rows)}
        except Exception as e:
            return {'status': 'error', 'file': file_path, 'error': str(e)}
    
    def process_batch(self, files, batch_num):
        """Process batch in parallel."""
        results = []
        
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_file = {
                executor.submit(self.process_file, f): f 
                for f in files
            }
            
            for future in as_completed(future_to_file):
                try:
                    result = future.result(timeout=60)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Batch processing error: {e}")
        
        return results
    
    def run_backfill(self, start_date, end_date):
        """Run backfill with batching."""
        files = self.list_files(start_date, end_date)
        
        total_batches = (len(files) + self.BATCH_SIZE - 1) // self.BATCH_SIZE
        
        for i in range(0, len(files), self.BATCH_SIZE):
            batch = files[i:i + self.BATCH_SIZE]
            batch_num = i // self.BATCH_SIZE + 1
            
            logger.info(f"Processing batch {batch_num}/{total_batches}")
            results = self.process_batch(batch, batch_num)
            
            successful = sum(1 for r in results if r['status'] == 'success')
            logger.info(f"Batch complete: {successful}/{len(batch)} successful")
```

---

## Related Documentation

- **[Deployment Guide](../DEPLOYMENT_GUIDE.md)** - How to deploy backfill jobs to Cloud Run
- **[Running Locally](../RUNNING_LOCALLY.md)** - Test jobs on your local machine
- **[Scrapers Guide](../scrapers/GUIDE.md)** - Creating scraper backfills *(coming soon)*
- **[Analytics Guide](../analytics/GUIDE.md)** - Creating analytics backfills *(coming soon)*
- **[Troubleshooting](../TROUBLESHOOTING.md)** - Common issues *(coming soon)*

---

## Quick Reference

### File Structure Checklist

```
backfill_jobs/raw/my_processor/
├── ✅ my_processor_raw_backfill.py
├── ✅ deploy.sh (executable)
├── ✅ job-config.env
└── ✅ README.md (optional)
```

### Required Methods Checklist

```python
class MyProcessorBackfill:
    ✅ __init__()           # Initialize storage client, processor
    ✅ list_files()         # Find files to process
    ✅ process_file()       # Process single file
    ✅ run_backfill()       # Main orchestration loop
```

### Testing Checklist

- [ ] Local dry run works
- [ ] Local processing of 1 file works
- [ ] BigQuery data validates correctly
- [ ] Deployed to Cloud Run
- [ ] Cloud Run dry run works
- [ ] Cloud Run small test (5 files) works
- [ ] Cloud Run date range test works
- [ ] Full backfill ready to run

---

**Last Updated:** January 2025  
**Next Review:** When new patterns emerge or common issues identified
