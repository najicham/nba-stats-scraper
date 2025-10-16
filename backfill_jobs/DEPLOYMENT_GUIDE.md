# Deploying Backfill Jobs to Cloud Run

**Last Updated:** January 2025  
**Maintained By:** NBA Props Platform Team

---

## Overview

This guide explains how to deploy backfill jobs to Google Cloud Run Jobs. The deployment system is designed to be simple and consistent across all phases of the data pipeline.

**What You'll Learn:**
- How to deploy any backfill job to Cloud Run
- Testing and validation strategies
- Monitoring deployed jobs
- Troubleshooting common issues

**Prerequisites:**
- Google Cloud CLI (`gcloud`) installed and configured
- Access to `nba-props-platform` GCP project
- Authenticated with appropriate permissions
- Virtual environment activated with dependencies installed

---

## Quick Start

### Deploy Any Job in 3 Steps

```bash
# 1. Navigate to the job directory
cd backfill_jobs/<phase>/<job_name>

# 2. Run the deploy script
./deploy.sh

# 3. Test with a dry run
gcloud run jobs execute <job-name> --args=--dry-run --region=us-west2
```

**Example:**
```bash
cd backfill_jobs/raw/bdl_injuries
./deploy.sh
gcloud run jobs execute bdl-injuries-processor-backfill --args=--dry-run --region=us-west2
```

---

## Deployment Architecture

### How Deployment Works

The deployment system uses a layered architecture:

```
Job Directory (backfill_jobs/raw/bdl_injuries/)
├── deploy.sh                    # Simple wrapper script
├── job-config.env              # Job configuration
└── bdl_injuries_raw_backfill.py  # Job implementation

         ↓ calls

Phase Deployment Script (bin/raw/deploy/deploy_processor_backfill_job.sh)
├── Discovers config file
├── Validates configuration
├── Builds Docker image
└── Creates Cloud Run job

         ↓ uses

Shared Functions (bin/shared/deploy_common.sh)
├── build_and_push_image()
├── deploy_cloud_run_job()
├── discover_config_file()
└── validate_required_vars()

         ↓ uses

Wrapper Functions (bin/shared/deploy_wrapper_common.sh)
├── start_deployment_timer()
├── print_section_header()
└── print_deployment_summary()
```

### Why This Architecture?

- **Consistency:** All jobs deploy the same way
- **Simplicity:** Just run `./deploy.sh` from any job directory
- **Maintainability:** Shared logic in one place
- **Flexibility:** Easy to add new jobs

---

## Deployment Methods

### Method 1: Using Job's Deploy Script (Recommended)

Every job has its own `deploy.sh` that wraps the deployment:

```bash
cd backfill_jobs/<phase>/<job_name>
./deploy.sh
```

**Advantages:**
- ✅ Most convenient - just one command
- ✅ Prints job-specific test commands
- ✅ Shows timing summary
- ✅ Includes validation examples

### Method 2: Using Phase Deployment Script

Call the phase-specific deployment script directly:

```bash
# For raw processors
./bin/raw/deploy/deploy_processor_backfill_job.sh <job_name>

# For scrapers
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh <job_name>

# For analytics
./bin/analytics/deploy/deploy_analytics_processor_backfill.sh <job_name>
```

**Advantages:**
- ✅ Deploy from anywhere in the project
- ✅ Auto-discovers config file
- ✅ Useful for scripting multiple deployments

**Example:**
```bash
./bin/raw/deploy/deploy_processor_backfill_job.sh bdl_injuries
./bin/raw/deploy/deploy_processor_backfill_job.sh bdl_boxscores
./bin/raw/deploy/deploy_processor_backfill_job.sh odds_api_props
```

---

## Understanding job-config.env

Every job has a `job-config.env` file that defines its deployment configuration.

### Example Configuration

```bash
# Job identification
JOB_NAME="bdl-injuries-processor-backfill"
JOB_SCRIPT="backfill_jobs/raw/bdl_injuries/bdl_injuries_raw_backfill.py"
JOB_DESCRIPTION="Process Ball Don't Lie injury reports from GCS to BigQuery"

# Resource allocation
TASK_TIMEOUT="1800"  # 30 minutes in seconds
MEMORY="2Gi"         # Memory allocation
CPU="1"              # Number of CPUs

# Default parameters (passed as environment variables)
START_DATE="2021-10-01"
END_DATE="2025-06-30"
BUCKET_NAME="nba-scraped-data"

# Infrastructure (usually don't need to change)
REGION="us-west2"
SERVICE_ACCOUNT="nba-scrapers@nba-props-platform.iam.gserviceaccount.com"
```

### Configuration Fields Explained

**Required Fields:**
- **JOB_NAME** - Unique Cloud Run job name (use hyphens, not underscores)
- **JOB_SCRIPT** - Path to the Python backfill script
- **JOB_DESCRIPTION** - What the job does
- **TASK_TIMEOUT** - Maximum execution time in seconds
- **MEMORY** - Memory allocation (512Mi, 1Gi, 2Gi, 4Gi, 8Gi, 16Gi)
- **CPU** - Number of CPUs (1, 2, 4, 8)

**Optional Fields:**
- **START_DATE/END_DATE** - Default date ranges
- **BATCH_SIZE** - Processing batch size
- **BUCKET_NAME** - GCS bucket name
- **REGION** - GCP region (default: us-west2)
- **SERVICE_ACCOUNT** - Service account to use

### Resource Allocation Guidelines

| Job Type | CPU | Memory | Timeout | Use Case |
|----------|-----|--------|---------|----------|
| Scraper | 1 | 2Gi | 1800s (30m) | API rate-limited jobs |
| Raw Processor | 1-2 | 2-4Gi | 1800s (30m) | JSON parsing, light processing |
| Analytics | 2-4 | 4-8Gi | 3600s (1h) | Complex calculations, aggregations |
| Large Backfill | 4 | 8-16Gi | 7200s (2h) | Processing years of data |

**Tips:**
- Start with lower resources and increase if needed
- Monitor execution times to optimize timeout
- More CPU doesn't always mean faster (I/O bound jobs)
- Increase memory if you see OOM errors

---

## Deployment Process

### Step-by-Step Deployment

#### 1. Prepare Configuration

Ensure your `job-config.env` is properly configured:

```bash
cd backfill_jobs/<phase>/<job_name>
cat job-config.env
```

Verify:
- JOB_NAME is unique
- Resources are appropriate
- Paths are correct

#### 2. Run Deployment

```bash
./deploy.sh
```

**What Happens:**
1. ⏱️ Starts deployment timer
2. 📁 Discovers and loads `job-config.env`
3. ✅ Validates required configuration
4. 🏗️ Builds Docker image (~2-3 minutes)
   - Shows real-time progress indicator
   - Uses appropriate Dockerfile for phase
   - Includes job script and dependencies
5. 📤 Pushes image to Google Container Registry
6. 🗑️ Deletes existing job (if exists)
7. 🆕 Creates new Cloud Run job with configuration
8. 📧 Configures email alerting (if enabled)
9. ⏱️ Shows total deployment time

#### 3. Verify Deployment

Check that the job was created:

```bash
gcloud run jobs describe <job-name> --region=us-west2
```

---

## Testing Deployed Jobs

**ALWAYS** test jobs incrementally before running full backfills.

### Testing Sequence

```bash
# 1. Dry Run (no processing, just shows what would run)
gcloud run jobs execute <job-name> \
  --args=--dry-run \
  --region=us-west2

# 2. Limited Dry Run (check first 10 items)
gcloud run jobs execute <job-name> \
  --args=--dry-run,--limit=10 \
  --region=us-west2

# 3. Small Test (process 5 items)
gcloud run jobs execute <job-name> \
  --args=--limit=5 \
  --region=us-west2

# 4. Date Range Test (one day)
gcloud run jobs execute <job-name> \
  --args=--start-date=2024-10-01,--end-date=2024-10-01 \
  --region=us-west2

# 5. Weekly Test
gcloud run jobs execute <job-name> \
  --args=--start-date=2024-10-01,--end-date=2024-10-07 \
  --region=us-west2

# 6. Full Backfill (only after all tests pass)
gcloud run jobs execute <job-name> --region=us-west2
```

### Passing Arguments to Cloud Run Jobs

Cloud Run jobs accept arguments via the `--args` flag:

```bash
--args=arg1,arg2,arg3
```

**Important Rules:**
- ✅ Use commas (`,`) to separate arguments - NO SPACES
- ✅ Use `--param=value` format (equals sign, no spaces)
- ✅ NO quotes around the entire --args value
- ❌ Don't use spaces: `--args="--dry-run, --limit=5"` is WRONG
- ❌ Don't use quotes around individual args: `--args="--dry-run","--limit=5"` is WRONG

**Correct Examples:**
```bash
# Single argument
--args=--dry-run

# Multiple arguments
--args=--dry-run,--limit=10

# Arguments with values
--args=--start-date=2024-01-01,--end-date=2024-01-31

# Combined
--args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07,--limit=100
```

### Special Case: Arguments Containing Commas

If your argument value contains commas (e.g., list of player names), use a custom delimiter:

```bash
# Use ^|^ as delimiter instead of comma
gcloud run jobs execute <job-name> \
  --args="^|^--players=LeBron James,Stephen Curry^|^--limit=10"
```

This is rarely needed for backfill jobs but useful to know.

---

## Monitoring Executions

### List Recent Executions

```bash
# List last 5 executions
gcloud run jobs executions list \
  --job=<job-name> \
  --region=us-west2 \
  --limit=5

# Show detailed format
gcloud run jobs executions list \
  --job=<job-name> \
  --region=us-west2 \
  --format="table(name,status,startTime,completionTime)"
```

### View Logs

#### Real-Time Log Streaming

```bash
# Get the latest execution ID
EXECUTION_ID=$(gcloud run jobs executions list \
  --job=<job-name> \
  --region=us-west2 \
  --limit=1 \
  --format='value(name)')

# Stream logs
gcloud beta run jobs executions logs read $EXECUTION_ID \
  --region=us-west2 \
  --follow
```

#### View Historical Logs

```bash
# View logs from specific execution
gcloud beta run jobs executions logs read <execution-id> \
  --region=us-west2

# View logs from last execution
gcloud beta run jobs executions logs read \
  $(gcloud run jobs executions list --job=<job-name> --region=us-west2 --limit=1 --format='value(name)') \
  --region=us-west2
```

### Using Monitoring Scripts

Many jobs have dedicated monitoring scripts:

```bash
# For scrapers
./bin/scrapers/monitoring/<job>_monitor.sh

# For raw processors
./bin/raw/monitoring/<job>_monitor.sh

# Example
./bin/scrapers/monitoring/bdl_boxscore_monitor.sh
```

---

## Phase-Specific Examples

### Scrapers (Phase 1)

Scrapers fetch raw data from external APIs and save to GCS.

**Example: Deploying Odds API Props Scraper**

```bash
# Navigate and deploy
cd backfill_jobs/scrapers/odds_api_props
./deploy.sh

# Test with dry run
gcloud run jobs execute odds-api-props-scraper-backfill \
  --args=--dry-run \
  --region=us-west2

# Run for recent dates
gcloud run jobs execute odds-api-props-scraper-backfill \
  --args=--start-date=2024-10-01,--end-date=2024-10-15 \
  --region=us-west2

# Validate results in GCS
gsutil ls gs://nba-scraped-data/odds-api/props/2024-10-* | head -20
```

**Scraper Characteristics:**
- Usually CPU=1 (API rate limited)
- Memory=2Gi (lightweight)
- Timeout=30min (depends on rate limits)
- Output: Raw JSON/HTML files in GCS

### Raw Processors (Phase 2)

Raw processors read from GCS and load structured data to BigQuery.

**Example: Deploying BDL Injuries Processor**

```bash
# Navigate and deploy
cd backfill_jobs/raw/bdl_injuries
./deploy.sh

# Test with dry run (first 5 files)
gcloud run jobs execute bdl-injuries-processor-backfill \
  --args=--dry-run,--limit=5 \
  --region=us-west2

# Process one day
gcloud run jobs execute bdl-injuries-processor-backfill \
  --args=--start-date=2024-10-01,--end-date=2024-10-01 \
  --region=us-west2

# Validate results in BigQuery
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) as total_records, 
          MIN(report_date) as earliest, 
          MAX(report_date) as latest
   FROM `nba-props-platform.nba_raw.bdl_injuries`'
```

**Raw Processor Characteristics:**
- CPU=1-2 (I/O and parsing)
- Memory=2-4Gi (depends on file sizes)
- Timeout=30min-1hr
- Output: Structured rows in BigQuery nba_raw tables

### Analytics (Phase 3)

Analytics jobs compute derived metrics from raw data.

**Example: Deploying Player Game Summary Analytics**

```bash
# Navigate and deploy
cd backfill_jobs/analytics/player_game_summary
./deploy.sh

# Test with dry run
gcloud run jobs execute player-game-summary-analytics-backfill \
  --args=--dry-run,--start-date=2024-10-01,--end-date=2024-10-07 \
  --region=us-west2

# Process one week
gcloud run jobs execute player-game-summary-analytics-backfill \
  --args=--start-date=2024-10-01,--end-date=2024-10-07 \
  --region=us-west2

# Validate results in BigQuery
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) as games_analyzed,
          COUNT(DISTINCT player_id) as unique_players,
          MIN(game_date) as earliest,
          MAX(game_date) as latest
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE DATE(created_at) = CURRENT_DATE()'
```

**Analytics Characteristics:**
- CPU=2-4 (computation intensive)
- Memory=4-8Gi (aggregations and joins)
- Timeout=1-2hrs
- Output: Enriched analytics in BigQuery nba_analytics tables

---

## Troubleshooting

### Common Deployment Issues

#### Error: "Could not find config file"

**Problem:** Config file not found or wrong job name.

**Solution:**
```bash
# List available jobs in phase
find backfill_jobs/<phase>/ -name "job-config.env" | sed 's|/job-config.env||'

# Use exact job directory name
./bin/<phase>/deploy/deploy_*_backfill_job.sh <exact_job_name>
```

#### Error: "Image build failed"

**Problem:** Docker build error.

**Solution:**
1. Check that JOB_SCRIPT path in config is correct
2. Verify job script has no syntax errors:
   ```bash
   python -m py_compile backfill_jobs/<phase>/<job>/<script>.py
   ```
3. Check Dockerfile exists
4. Review build logs in Cloud Build console

#### Error: "Job creation failed"

**Problem:** Invalid configuration or permissions.

**Solution:**
1. Check resource values are valid (see guidelines above)
2. Verify project permissions:
   ```bash
   gcloud projects get-iam-policy nba-props-platform \
     --flatten="bindings[].members" \
     --filter="bindings.members:user:$(gcloud config get-value account)"
   ```
3. Ensure service account exists and has permissions

#### Error: "Task timeout exceeded"

**Problem:** Job ran longer than TASK_TIMEOUT.

**Solution:**
1. Check logs to see where it timed out
2. Increase TASK_TIMEOUT in job-config.env:
   ```bash
   TASK_TIMEOUT="3600"  # 1 hour
   ```
3. Redeploy with updated config
4. Consider processing in smaller batches

#### Error: "Out of memory"

**Problem:** Job exceeded memory allocation.

**Solution:**
1. Check logs for memory usage
2. Increase MEMORY in job-config.env:
   ```bash
   MEMORY="4Gi"  # Double the memory
   ```
3. Optimize code to use less memory
4. Process in smaller batches

### Execution Issues

#### Job Starts But No Data Processed

**Possible Causes:**
- Date range doesn't match available data
- Resume logic skipping already-processed data
- Data availability issue

**Debugging:**
```bash
# Check what data exists
gsutil ls gs://nba-scraped-data/<path>/<date>/ | head -20

# Run with dry-run to see what would process
gcloud run jobs execute <job-name> \
  --args=--dry-run,--start-date=2024-10-01,--end-date=2024-10-07 \
  --region=us-west2

# Check logs for skip messages
gcloud beta run jobs executions logs read <execution-id> --region=us-west2 | grep -i "skip"
```

#### Job Fails Intermittently

**Possible Causes:**
- API rate limiting
- Network issues
- Transient BigQuery errors

**Solutions:**
1. Check error patterns in logs
2. Add retries in job script
3. Reduce batch sizes
4. Add delays between API calls

---

## Service Accounts and Permissions

### Default Service Account

Most jobs use: `nba-scrapers@nba-props-platform.iam.gserviceaccount.com`

**Required Permissions:**
- ✅ BigQuery Data Editor (to write to tables)
- ✅ Storage Object Admin (to read/write GCS)
- ✅ Cloud Run Invoker (to call scraper services)
- ✅ Logs Writer (to write logs)

### Checking Permissions

```bash
# View service account permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:nba-scrapers@nba-props-platform.iam.gserviceaccount.com"
```

### Custom Service Accounts

To use a different service account, add to `job-config.env`:

```bash
SERVICE_ACCOUNT="custom-sa@nba-props-platform.iam.gserviceaccount.com"
```

---

## Email Alerting

The deployment system automatically configures email alerting if credentials are available in `.env` file.

### Email Configuration Status

After deployment, you'll see:

```
📧 Email Alerting Status: ENABLED
   Alert Recipients: you@example.com
   Critical Recipients: you@example.com
   From Email: nba-alerts@yourdomain.com
```

or

```
📧 Email Alerting Status: DISABLED
   Missing required environment variables in .env file
```

### What Gets Alerted

Jobs send email alerts for:
- ✅ Backfill completion with summary
- ⚠️ High error rates (>10% failures)
- ❌ Critical failures
- 📊 Data quality issues

Email alerting is automatic - no action needed if already configured.

---

## Best Practices

### Before Deployment

- ✅ Test locally first: `./bin/run_backfill.sh <phase>/<job> --dry-run`
- ✅ Review resource allocation in job-config.env
- ✅ Check that service account has required permissions
- ✅ Verify input data exists in GCS or APIs are accessible

### During Deployment

- ✅ Watch build progress - builds should complete in 2-3 minutes
- ✅ Check for warnings about email config or missing files
- ✅ Save the deployment output test commands

### After Deployment

- ✅ Always run dry-run test first
- ✅ Test with limited data before full backfill
- ✅ Monitor first few executions closely
- ✅ Validate output data in BigQuery/GCS

### For Production Backfills

- ✅ Schedule during off-peak hours if large volume
- ✅ Monitor resource usage and adjust if needed
- ✅ Set up monitoring/alerting for long-running jobs
- ✅ Document any special considerations for the job

---

## Quick Reference

### Common Commands Cheatsheet

```bash
# DEPLOYMENT
cd backfill_jobs/<phase>/<job> && ./deploy.sh

# TESTING
gcloud run jobs execute <job-name> --args=--dry-run --region=us-west2
gcloud run jobs execute <job-name> --args=--dry-run,--limit=10 --region=us-west2
gcloud run jobs execute <job-name> --args=--start-date=2024-10-01,--end-date=2024-10-01 --region=us-west2

# MONITORING
gcloud run jobs executions list --job=<job-name> --region=us-west2 --limit=5
gcloud beta run jobs executions logs read <execution-id> --region=us-west2 --follow

# VALIDATION
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `nba-props-platform.nba_raw.<table>`'
gsutil ls gs://nba-scraped-data/<path>/ | head -20

# MANAGEMENT
gcloud run jobs describe <job-name> --region=us-west2
gcloud run jobs delete <job-name> --region=us-west2
```

### Job Naming Pattern

| Phase | Suffix Pattern | Example |
|-------|---------------|---------|
| Scraper | `-scraper-backfill` | `odds-api-props-scraper-backfill` |
| Raw | `-processor-backfill` | `bdl-injuries-processor-backfill` |
| Analytics | `-analytics-backfill` | `player-game-summary-analytics-backfill` |
| Reference | `-reference-backfill` | `gamebook-registry-reference-backfill` |

---

## Related Documentation

- **[Running Locally](RUNNING_LOCALLY.md)** - Test jobs on your machine before deploying
- **[Scrapers Guide](scrapers/GUIDE.md)** - Creating and deploying scraper backfills *(coming soon)*
- **[Raw Processors Guide](raw/GUIDE.md)** - Creating and deploying raw processor backfills *(coming soon)*
- **[Analytics Guide](analytics/GUIDE.md)** - Creating and deploying analytics backfills *(coming soon)*
- **[Troubleshooting Guide](TROUBLESHOOTING.md)** - Common issues and solutions *(coming soon)*

---

## Getting Help

**If deployment fails:**
1. Check this guide's troubleshooting section
2. Review deployment output for specific errors
3. Check Cloud Build logs in GCP Console
4. Verify configuration in job-config.env

**If execution fails:**
1. Review execution logs
2. Test locally with same parameters
3. Check input data availability
4. Review job-specific README if available

**For questions:**
- Check phase-specific READMEs in `backfill_jobs/<phase>/`
- Review example jobs in the same phase
- Check `bin/<phase>/monitoring/` for monitoring scripts

---

**Last Updated:** January 2025  
**Next Review:** Quarterly or when deployment process changes
