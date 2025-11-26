# NBA Backfill Job Creation & Deployment Guide

**Created:** 2025-11-21 17:50:00 PST
**Last Updated:** 2025-11-21 17:50:00 PST

**Complete guide for deploying NBA data processors to production**

Focus: Cloud Run deployment, backfill jobs, production testing

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Dual Deployment Architecture](#dual-deployment-architecture)
3. [Step-by-Step Deployment](#step-by-step-deployment)
4. [Smart Idempotency](#smart-idempotency)
5. [Complete Deployment Sequence](#complete-deployment-sequence)
6. [Testing & Validation](#testing--validation)
7. [Cloud Run Arguments](#cloud-run-arguments)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required

✅ Processor code complete (see [NBA Processor Development Guide](01-processor-development-guide.md))
✅ BigQuery schema created
✅ Local testing passed
✅ GCP project access configured
✅ Docker installed locally (for testing builds)

### Knowledge Requirements

- Docker containerization basics
- Cloud Run service vs job concepts
- GCS file path patterns
- Basic bash scripting

### Environment Setup

```bash
# Ensure you're in the project root
cd /path/to/nba-stats-scraper

# Activate virtual environment
source .venv/bin/activate

# Set project
export GCP_PROJECT_ID="nba-props-platform"
export GCP_REGION="us-west2"

# Verify access
gcloud config get-value project
gcloud auth list
```

---

## Dual Deployment Architecture

### CRITICAL: Two Separate Deployments Required

Modern NBA processors require **TWO distinct deployments** for complete functionality:

1. **Service Deployment (Web Server)** - Real-time processing
2. **Backfill Deployment (Batch Job)** - Historical processing

### Why Two Deployments?

Different use cases require different architectures:

| Aspect | Service (Web Server) | Backfill (Batch Job) |
|--------|---------------------|---------------------|
| **Purpose** | Real-time Pub/Sub processing | Historical data processing |
| **Technology** | Flask + gunicorn web server | Python script execution |
| **Deployment** | Cloud Run Service | Cloud Run Job |
| **Entry Point** | HTTP endpoints | Command-line script |
| **Triggered By** | Pub/Sub messages, API calls | Manual execution, scheduler |
| **Endpoints** | `/health`, `/stats`, `/trigger/*`, `/process` | Command-line args |
| **Timeout** | 3600s (1 hour) | 3600s+ (configurable) |
| **Use Cases** | New data arrives, manual triggers | Data recovery, bulk processing |

### Service Deployment (Web Server)

**Purpose:** Handle real-time Pub/Sub processing and API endpoints

**How it works:**
1. Scraper saves file to GCS
2. GCS publishes message to Pub/Sub topic
3. Service receives message at `/process` endpoint
4. Processor transforms and loads data to BigQuery

**Provides:**
- Health check endpoint: `GET /health`
- Manual trigger endpoints: `POST /trigger/*`
- Pub/Sub message processing: `POST /process`
- Statistics endpoint: `GET /stats`
- Real-time data processing capabilities

**Example service URL:**
```
https://nba-raw-processors-[hash]-uw.a.run.app
```

### Backfill Deployment (Batch Job)

**Purpose:** Process historical data in bulk or date ranges

**How it works:**
1. Job lists files from GCS for date range
2. Processes files in batches
3. Handles historical data and recovery scenarios

**Provides:**
- Date range processing: `--start-date=2025-01-01 --end-date=2025-01-31`
- Dry run testing: `--dry-run --limit=10`
- Bulk operations: `--limit=100`
- Data recovery: Process specific dates

**Example job execution:**
```bash
gcloud run jobs execute nba-team-stats-processor-backfill \
  --args=--start-date=2025-01-01,--end-date=2025-01-07 \
  --region=us-west2
```

### Deployment File Structure

```
docker/
├── raw-service.Dockerfile       # Service: Raw processor web server
├── analytics-service.Dockerfile # Service: Analytics web server
├── reference-service.Dockerfile # Service: Reference web server
├── processor.Dockerfile         # Backfill: Raw processors (existing)
├── analytics.Dockerfile         # Backfill: Analytics jobs
└── reference.Dockerfile         # Backfill: Reference jobs

backfill_jobs/
├── raw/[name]/
│   ├── [name]_backfill_job.py   # Backfill script
│   ├── job-config.env           # Job configuration
│   └── deploy.sh                # Deployment wrapper
├── analytics/[name]/
└── reference/[name]/

bin/
├── shortcuts/                   # Quick deploy commands
├── raw/deploy/
│   ├── deploy_raw_processors.sh           # Service deployment
│   └── deploy_processor_backfill_job.sh   # Backfill deployment
├── analytics/deploy/
└── reference/deploy/
```

### Required Dockerfiles by Processor Type

The deployment scripts look for type-specific Dockerfiles in this order:

**Raw Processors:**
- Service: `docker/raw-service.Dockerfile` → fallback to `docker/reference-service.Dockerfile`
- Backfill: `docker/processor.Dockerfile` (existing)

**Analytics Processors:**
- Service: `docker/analytics-service.Dockerfile` → fallback to `docker/reference-service.Dockerfile`
- Backfill: `docker/analytics.Dockerfile` → fallback to `docker/processor.Dockerfile`

**Reference Processors:**
- Service: `docker/reference-service.Dockerfile` (required)
- Backfill: `docker/reference.Dockerfile` → fallback to `docker/processor.Dockerfile`

---

## Step-by-Step Deployment

### Step 1: Create Backfill Job Script

**File:** `backfill_jobs/[type]/[name]/[name]_backfill_job.py`

**CRITICAL:** Script name must match directory name + `_backfill_job.py`

See full template in appendix or existing backfill jobs for reference.

Key components:
- Import processor class
- `list_files()` method with date range support
- `process_file()` method for single file processing
- `run_backfill()` orchestration method
- Argument parsing for CLI usage

### Step 2: Create Job Configuration

**File:** `backfill_jobs/[type]/[name]/job-config.env`

```bash
# File: backfill_jobs/[type]/[name]/job-config.env
# Description: Cloud Run job configuration for [name] processor backfill

# CRITICAL: Use unique name - add "processor" to distinguish from scraper jobs
JOB_NAME="[name]-processor-backfill"
JOB_SCRIPT="backfill_jobs/[type]/[name]/[name]_backfill_job.py"
JOB_DESCRIPTION="Process [source] [type] data from GCS to BigQuery"

# Resources
TASK_TIMEOUT="3600"  # 1 hour (adjust as needed)
MEMORY="4Gi"
CPU="2"

# Defaults
BUCKET_NAME="nba-scraped-data"
```

**Resource Guidelines:**

| Data Volume | Memory | CPU | Timeout |
|-------------|--------|-----|---------|
| Small (<1K rows/file) | 2Gi | 1 | 1800s |
| Medium (1K-10K rows) | 4Gi | 2 | 3600s |
| Large (>10K rows) | 8Gi | 4 | 7200s |

### Step 3: Update Processor Registry (CRITICAL!)

**File:** `data_processors/raw/main_processor_service.py`

Add your processor to the registry:

```python
# Import processor
from data_processors.raw.nbacom.nbac_team_boxscore_processor import NbacTeamBoxscoreProcessor

# Add to PROCESSOR_REGISTRY
PROCESSOR_REGISTRY = {
    # ... existing processors ...
    'nba-com/team-boxscore': NbacTeamBoxscoreProcessor,  # Add this line
    # ... more processors ...
}
```

**CRITICAL:** Registry key must match GCS path exactly!
- If files are at `gs://nba-scraped-data/nba-com/team-boxscore/...`
- Then registry key must be `'nba-com/team-boxscore'`

### Step 4: Create Deploy Script

**File:** `backfill_jobs/[type]/[name]/deploy.sh`

```bash
#!/bin/bash
# FILE: backfill_jobs/[type]/[name]/deploy.sh
# Deploy [Name] Processor Backfill Job

set -e

echo "Deploying [Name] Processor Backfill Job..."

# Use standardized deployment script based on processor type
./bin/[type]/deploy/deploy_[type]_processor_backfill.sh [name]

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run:"
echo "  gcloud run jobs execute [job-name] \\"
echo "    --args=--dry-run,--limit=10 --region=us-west2"
```

Make executable:
```bash
chmod +x backfill_jobs/[type]/[name]/deploy.sh
```

---

## Smart Idempotency

### What is Smart Idempotency?

Smart idempotency allows processors to skip writing data when it hasn't changed, providing:
- **Cost Savings:** Reduced BigQuery write operations
- **Performance:** Faster processing when data unchanged
- **Reliability:** Avoids streaming buffer conflicts
- **Monitoring:** Hash provides data change tracking

### How It Works

1. **Hash Computation:** Processor computes hash from meaningful fields
2. **Comparison:** Queries BigQuery for existing hash using primary keys
3. **Skip Decision:** If ALL hashes match, skip write entirely
4. **Logging:** Records skip statistics for monitoring

### Implementation Steps

#### 1. Define Hash Fields

In your processor, specify which fields should be included in the hash:

```python
class NbacTeamBoxscoreProcessor(SmartIdempotencyMixin, ProcessorBase):
    # Hash meaningful fields only (exclude metadata)
    HASH_FIELDS = [
        'game_id',
        'team_abbr',
        'is_home',
        'points',
        'assists',
        'rebounds',
        # ... other stats fields ...
    ]
```

**Guidelines:**
- Include primary keys
- Include all data fields that matter for downstream use
- Exclude metadata like `created_at`, `processed_at`
- Exclude fields that change on every run

#### 2. Define Primary Keys

Specify which fields uniquely identify a record:

```python
class NbacTeamBoxscoreProcessor(SmartIdempotencyMixin, ProcessorBase):
    # Primary keys for hash lookup
    PRIMARY_KEYS = ['game_id', 'team_abbr']
```

**For Partitioned Tables:**
The mixin automatically includes the partition column (default: `game_date`) in queries.

#### 3. Add Smart Idempotency Check

In your `save_data()` method:

```python
def save_data(self) -> None:
    """Save transformed data to BigQuery."""
    rows = self.transformed_data

    if not rows:
        logger.warning("No rows to save")
        return

    # Smart idempotency check: Skip write if data unchanged
    if self.should_skip_write():
        logger.info("Skipping write - data unchanged (smart idempotency)")
        return

    # Proceed with delete/insert...
```

#### 4. Test Smart Idempotency

```python
# First run - should insert data
processor.run({'bucket': 'nba-scraped-data', 'file_path': 'path/to/file.json'})
# Output: ✓ Successfully inserted 2 rows

# Second run - should skip
processor.run({'bucket': 'nba-scraped-data', 'file_path': 'path/to/file.json'})
# Output: Smart idempotency: All 2 record(s) unchanged, skipping write
```

### Smart Idempotency for Partitioned Tables

For tables partitioned by `game_date`, the mixin automatically:
- Includes `game_date` in WHERE clauses
- Handles DATE type conversion
- Supports partition elimination

**Example Query Generated:**
```sql
SELECT data_hash
FROM `nba_raw.nbac_team_boxscore`
WHERE game_id = '20241120_ORL_LAC'
  AND team_abbr = 'ORL'
  AND game_date = DATE('2024-11-20')  -- Auto-included for partitions
LIMIT 1
```

### Monitoring Smart Idempotency

Check processor stats to see skip rates:

```python
stats = processor.get_idempotency_stats()
# {
#   'strategy': 'MERGE_UPDATE',
#   'hashes_matched': 2,
#   'total_records': 2,
#   'rows_skipped': 2,
#   'skip_check_performed': True
# }
```

---

## Complete Deployment Sequence

### 1. Create BigQuery Schema

```bash
bq query --use_legacy_sql=false < schemas/bigquery/[type]/[name]_tables.sql
```

Verify:
```sql
SELECT table_name, ddl
FROM `nba-props-platform.nba_raw.INFORMATION_SCHEMA.TABLES`
WHERE table_name = '[your_table]';
```

### 2. Deploy Service (Web Server for Pub/Sub)

**Raw processors:**
```bash
./bin/raw/deploy/deploy_raw_processors.sh
```

**Analytics processors:**
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

**Reference processors:**
```bash
./bin/reference/deploy/deploy_reference_processors.sh
```

**Service provides:**
- Health endpoint: `GET /health`
- Manual triggers: `POST /trigger/*`
- Pub/Sub processing: `POST /process`
- Statistics: `GET /stats`

**Test service health:**
```bash
# Get service URL
gcloud run services describe nba-raw-processors --region=us-west2 --format='value(status.url)'

# Test health endpoint
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://[service-url]/health
```

### 3. Deploy Backfill Job (Batch Processing)

Using type-specific deployment:
```bash
./backfill_jobs/[type]/[name]/deploy.sh
```

Or using shortcuts:
```bash
# For raw processors
./bin/shortcuts/deploy-raw-backfill [name]

# For analytics processors
./bin/shortcuts/deploy-analytics-backfill [name]

# For reference processors
./bin/shortcuts/deploy-reference-backfill [name]
```

**Backfill provides:**
- Historical data processing
- Date range batch operations
- Data recovery capabilities
- Bulk transformation workflows

### 4. Verify Both Deployments

Check service:
```bash
gcloud run services describe nba-[type]-processors --region=us-west2
```

Check backfill job:
```bash
gcloud run jobs describe [job-name]-processor-backfill --region=us-west2
```

Test backfill with dry run:
```bash
gcloud run jobs execute [job-name]-processor-backfill \
  --args=--dry-run,--limit=5 --region=us-west2
```

---

## Testing & Validation

### Complete Testing Procedure

#### 1. Test with Dry Run

```bash
# ✅ CORRECT - Simple dry run
gcloud run jobs execute [job-name]-processor-backfill \
  --args=--dry-run,--limit=10 --region=us-west2

# ✅ CORRECT - Dry run with date range
gcloud run jobs execute [job-name]-processor-backfill \
  --args=--dry-run,--start-date=2025-01-01,--end-date=2025-01-07 \
  --region=us-west2
```

Expected output:
- List of files that would be processed
- No actual data modifications
- Success message

#### 2. Small Sample Test

```bash
# ✅ CORRECT - Process 3-5 files first
gcloud run jobs execute [job-name]-processor-backfill \
  --args=--limit=5 --region=us-west2
```

Monitor logs:
```bash
# Get execution ID
gcloud run jobs executions list \
  --job=[job-name]-processor-backfill \
  --region=us-west2 \
  --limit=1

# View logs
gcloud beta run jobs executions logs read [execution-id] --region=us-west2
```

#### 3. Verify BigQuery Results

```sql
-- Check data was loaded
SELECT COUNT(*) as total_rows
FROM `nba-props-platform.nba_raw.[table_name]`;

-- Check data structure and recency
SELECT
  game_date,
  COUNT(*) as records,
  MIN(created_at) as first_processed,
  MAX(created_at) as last_processed
FROM `nba-props-platform.nba_raw.[table_name]`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Check for errors or nulls
SELECT
  game_date,
  COUNT(*) as total,
  SUM(CASE WHEN field1 IS NULL THEN 1 ELSE 0 END) as null_field1,
  SUM(CASE WHEN field2 IS NULL THEN 1 ELSE 0 END) as null_field2
FROM `nba-props-platform.nba_raw.[table_name]`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

#### 4. Test Smart Idempotency (If Implemented)

```bash
# Run same file twice
gcloud run jobs execute [job-name]-processor-backfill \
  --args=--start-date=2024-11-20,--end-date=2024-11-20 \
  --region=us-west2

# Check logs for skip message
# Expected: "Smart idempotency: All X record(s) unchanged, skipping write"
```

---

## Cloud Run Arguments

### CRITICAL: Argument Syntax

Cloud Run argument parsing is extremely sensitive to syntax.

#### For Simple Parameters (No Commas in Values)

```bash
# ✅ CORRECT - Equals syntax without quotes or spaces
--args=--dry-run,--limit=10,--start-date=2025-01-01,--end-date=2025-01-31

# ✅ CORRECT - Single flag
--args=--dry-run

# ✅ CORRECT - Date ranges
--args=--start-date=2025-01-01,--end-date=2025-01-31
```

#### For Comma-Separated Values (CRITICAL)

When passing comma-separated values, use custom delimiter syntax:

```bash
# ✅ CORRECT - Use custom delimiter syntax for comma-separated values
--args="^|^--seasons=2021,2022,2023,2024|--limit=100"

# ✅ CORRECT - Multiple comma-separated parameters
--args="^|^--seasons=2021,2022|--teams=LAL,GSW,BOS|--dry-run"

# How it works: ^|^ changes delimiter from comma to pipe
# This preserves commas within individual argument values
```

#### Common Failures to Avoid

```bash
# ❌ WRONG - Spaces break parsing
--args="--dry-run --limit 10"

# ❌ WRONG - Comma in value without delimiter syntax
--args="--seasons=2021,2022,2023"  # 2022 and 2023 become separate args!

# ❌ WRONG - Quotes with commas still get split incorrectly
--args='--start-date,2025-01-01,--end-date,2025-01-31'

# ❌ WRONG - Multiple --args flags
--args="--start-date","2025-01-01","--end-date","2025-01-31"
```

---

## Troubleshooting

### Common Issues & Solutions

#### "No processor found for file"

**Cause:** `PROCESSOR_REGISTRY` key doesn't match GCS path

**Solution:**
- Check `PROCESSOR_REGISTRY` key matches GCS path exactly
- Use `gsutil ls` to confirm actual file paths
- Remember: if `'nba-com/scoreboard-v2'` is your key, it must appear in the file path

```python
# In main_processor_service.py
PROCESSOR_REGISTRY = {
    'nba-com/scoreboard-v2': ScoreboardProcessor,  # Key must match GCS path
}
```

#### "'NoneType' object has no attribute 'query'"

**Cause:** Missing BigQuery client initialization in `__init__`

**Solution:**
```python
def __init__(self):
    super().__init__()
    # Add these two lines
    self.bq_client = bigquery.Client()
    self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
```

#### "Cannot query over table without filter over partition column"

**Cause:** DELETE or SELECT queries on partitioned tables need partition filter

**Solution:**
```python
# ❌ WRONG - No partition filter
DELETE FROM `nba_raw.nbac_team_boxscore`
WHERE game_id = '20241120_ORL_LAC'

# ✅ CORRECT - Include partition column
DELETE FROM `nba_raw.nbac_team_boxscore`
WHERE game_id = '20241120_ORL_LAC'
  AND game_date = DATE('2024-11-20')
```

**Note:** Smart idempotency mixin automatically adds partition column to queries.

---

## Final Checklist

### Before Deployment

- [ ] Processor code complete and tested locally
- [ ] BigQuery schema created
- [ ] Backfill job script created with correct name
- [ ] Job configuration file created
- [ ] Service Dockerfile exists (web server)
- [ ] Backfill Dockerfile exists (batch job)
- [ ] Service requirements.txt includes Flask/gunicorn
- [ ] Deploy script created and executable
- [ ] **Processor added to main_processor_service.py registry**
- [ ] **PRIMARY_KEYS defined (if using smart idempotency)**
- [ ] **HASH_FIELDS defined (if using smart idempotency)**

### After Service Deployment

- [ ] Service deployment successful
- [ ] Health endpoint responding
- [ ] Service URL obtained and tested
- [ ] Pub/Sub integration verified (if applicable)
- [ ] Manual trigger endpoints working (if applicable)

### After Backfill Deployment

- [ ] Backfill job deployment successful
- [ ] Dry run test successful
- [ ] Small sample test (5 files) successful
- [ ] BigQuery tables populated correctly
- [ ] Data structure verified in BigQuery
- [ ] Date range processing tested
- [ ] Error handling verified
- [ ] **Smart idempotency tested (second run skips)**

### Monitoring Setup

- [ ] Log monitoring configured
- [ ] Alert queries created (if needed)
- [ ] Documentation updated
- [ ] Team notified of new processor

---

**Document Version:** 3.0
**Last Updated:** November 2025
**Part of:** NBA Props Platform Documentation
**See Also:** [Processor Development Guide](01-processor-development-guide.md), [Quick Start](02-quick-start-processor.md)
