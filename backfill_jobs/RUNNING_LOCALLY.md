# Running Backfill Jobs Locally

## Overview

This guide explains how to run backfill jobs locally for testing and debugging before deploying them to Google Cloud Run Jobs. Running locally allows you to:

- Test changes quickly without deploying
- Debug issues with full Python debugging tools
- Validate data processing logic
- Test with limited data using `--dry-run` and `--limit` flags

---

## Quick Start

### Method 1: Using the Helper Script (Recommended)

```bash
# From project root
./bin/run_backfill.sh <phase/job_name> [args...]

# Examples:
./bin/run_backfill.sh raw/bdl_injuries --help
./bin/run_backfill.sh raw/bdl_injuries --dry-run --limit 5
./bin/run_backfill.sh analytics/player_game_summary --dry-run
./bin/run_backfill.sh scrapers/odds_api_props --limit 10
```

### Method 2: Using Python Module Syntax Directly

```bash
# From project root
python -m backfill_jobs.<phase>.<job_name>.<job_name>_<phase>_backfill [args...]

# Examples:
python -m backfill_jobs.raw.bdl_injuries.bdl_injuries_raw_backfill --help
python -m backfill_jobs.analytics.player_game_summary.player_game_summary_analytics_backfill --dry-run
```

---

## Backfill Naming Convention

All backfill job files follow this naming pattern:

```
<job_name>_<phase>_backfill.py
```

### Phase Suffixes

| Phase | Directory | Suffix | Example |
|-------|-----------|--------|---------|
| Phase 1: Data Collection | `scrapers/` | `_scraper_backfill.py` | `odds_api_props_scraper_backfill.py` |
| Phase 2: Data Normalization | `raw/` | `_raw_backfill.py` | `bdl_injuries_raw_backfill.py` |
| Phase 3: Analytics Enrichment | `analytics/` | `_analytics_backfill.py` | `player_game_summary_analytics_backfill.py` |
| Phase 4: Report Precompute | `precompute/` | `_precompute_backfill.py` | `opponent_defense_precompute_backfill.py` |
| Phase 5: Prediction Generation | `prediction/` | `_prediction_backfill.py` | `player_report_prediction_backfill.py` |
| Phase 6: Report Publishing | `publishing/` | `_publishing_backfill.py` | `firestore_publishing_backfill.py` |
| Reference Data | `reference/` | `_reference_backfill.py` | `gamebook_registry_reference_backfill.py` |

---

## Helper Script Details

### Location
`bin/run_backfill.sh`

### How It Works
1. Takes a path in format: `phase/job_name`
2. Automatically determines the correct suffix based on phase
3. Converts to proper Python module syntax
4. Runs using `python -m` with all additional arguments passed through

### Usage Pattern
```bash
./bin/run_backfill.sh <phase>/<job_name> [script arguments...]
```

### Common Arguments

Most backfill jobs support these standard arguments:

- `--help` - Show help and available options
- `--dry-run` - Show what would be processed without actually running
- `--limit N` - Process only N items (useful for testing)
- `--start-date YYYY-MM-DD` - Start date for processing
- `--end-date YYYY-MM-DD` - End date for processing
- `--bucket BUCKET_NAME` - GCS bucket to use

---

## Common Testing Patterns

### 1. Check Available Options

```bash
# See what arguments a job accepts
./bin/run_backfill.sh raw/bdl_injuries --help
```

### 2. Dry Run (No Processing)

```bash
# See what would be processed without actually processing
./bin/run_backfill.sh raw/bdl_injuries --dry-run

# Limit to first 10 items in dry run
./bin/run_backfill.sh raw/bdl_injuries --dry-run --limit 10
```

### 3. Limited Processing Test

```bash
# Process only 5 items for testing
./bin/run_backfill.sh raw/bdl_injuries --limit 5

# Process specific date range
./bin/run_backfill.sh raw/bdl_injuries \
  --start-date 2024-10-01 \
  --end-date 2024-10-05 \
  --limit 10
```

### 4. Full Test Run (Longer)

```bash
# Process a full week of data
./bin/run_backfill.sh raw/bdl_injuries \
  --start-date 2024-10-01 \
  --end-date 2024-10-07
```

---

## Examples by Phase

### Phase 1: Scrapers

```bash
# Test scraping odds API props
./bin/run_backfill.sh scrapers/odds_api_props --dry-run --limit 5

# Test scraping NBA.com gamebooks
./bin/run_backfill.sh scrapers/nbac_gamebook --dry-run --limit 3

# Test scraping Basketball Reference rosters
./bin/run_backfill.sh scrapers/br_rosters --dry-run
```

### Phase 2: Raw Processors

```bash
# Test BDL injuries processor
./bin/run_backfill.sh raw/bdl_injuries --dry-run --limit 10

# Test odds API props processor
./bin/run_backfill.sh raw/odds_api_props --dry-run --limit 5

# Test with specific date range
./bin/run_backfill.sh raw/bdl_boxscores \
  --start-date 2024-10-01 \
  --end-date 2024-10-07 \
  --dry-run
```

### Phase 3: Analytics

```bash
# Test player game summary analytics
./bin/run_backfill.sh analytics/player_game_summary --dry-run --limit 10

# Test team defense analytics
./bin/run_backfill.sh analytics/team_defense_game_summary --dry-run --limit 5

# Test upcoming game context
./bin/run_backfill.sh analytics/upcoming_team_game_context --dry-run
```

### Phase 4: Precompute (Future)

```bash
# When precompute jobs are created
./bin/run_backfill.sh precompute/opponent_defense --dry-run
./bin/run_backfill.sh precompute/game_context --dry-run
```

### Phase 5: Prediction (Future)

```bash
# When prediction jobs are created
./bin/run_backfill.sh prediction/player_report --dry-run --limit 5
```

### Phase 6: Publishing (Future)

```bash
# When publishing jobs are created
./bin/run_backfill.sh publishing/firestore --dry-run
```

### Reference Data

```bash
# Test gamebook registry
./bin/run_backfill.sh reference/gamebook_registry --dry-run
```

---

## Troubleshooting

### Error: "No module named 'data_processors'"

**Problem:** Running the script directly without using `-m` flag or from wrong directory.

**Solution:** Always run from project root using one of these methods:
```bash
# Method 1: Use the helper script
./bin/run_backfill.sh raw/bdl_injuries --help

# Method 2: Use python -m from project root
python -m backfill_jobs.raw.bdl_injuries.bdl_injuries_raw_backfill --help
```

### Error: "No module named 'backfill_jobs.raw/job'"

**Problem:** The helper script has a bug or isn't using the correct syntax.

**Solution:** Verify the helper script converts slashes to dots correctly. The module path should use dots, not slashes:
```bash
# Correct:
python -m backfill_jobs.raw.bdl_injuries.bdl_injuries_raw_backfill

# Wrong:
python -m backfill_jobs.raw/bdl_injuries.bdl_injuries_raw_backfill
```

### Error: "ModuleNotFoundError: No module named 'google'"

**Problem:** Virtual environment not activated or dependencies not installed.

**Solution:**
```bash
# Activate virtual environment
source .venv/bin/activate  # or your venv path

# Install dependencies
pip install -r requirements.txt
```

### Error: GCS authentication issues

**Problem:** Not authenticated to access Google Cloud Storage.

**Solution:**
```bash
# Authenticate with your Google Cloud account
gcloud auth application-default login

# Verify project is set correctly
gcloud config get-value project

# Set project if needed
gcloud config set project nba-props-platform
```

### Job runs but doesn't find any data

**Problem:** Date range or filters don't match available data.

**Solution:**
1. Check what data exists in GCS:
   ```bash
   gsutil ls gs://nba-scraped-data/raw/balldontlie/injuries/ | head -20
   ```
2. Adjust date range to match available data
3. Use `--dry-run` first to see what would be processed

---

## Best Practices

### 1. Always Start with Dry Run

```bash
# First, see what would be processed
./bin/run_backfill.sh raw/bdl_injuries --dry-run --limit 10

# Then run for real if it looks good
./bin/run_backfill.sh raw/bdl_injuries --limit 10
```

### 2. Use Limits for Testing

```bash
# Don't process thousands of records during development
./bin/run_backfill.sh raw/bdl_injuries --limit 5
```

### 3. Test Incrementally

```bash
# Start with 1 item
./bin/run_backfill.sh raw/bdl_injuries --limit 1

# Then 5 items
./bin/run_backfill.sh raw/bdl_injuries --limit 5

# Then a small date range
./bin/run_backfill.sh raw/bdl_injuries --start-date 2024-10-01 --end-date 2024-10-02

# Then full backfill on Cloud Run
```

### 4. Check Logs Carefully

```bash
# Run with full output visible
./bin/run_backfill.sh raw/bdl_injuries --limit 5 2>&1 | tee test_run.log

# Review the log
less test_run.log
```

### 5. Validate Results

After running locally, verify the results:

```bash
# Check BigQuery for new rows
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) FROM `nba-props-platform.nba_raw.bdl_injuries` 
   WHERE DATE(created_at) = CURRENT_DATE()'

# Check GCS for output files
gsutil ls gs://nba-scraped-data/path/to/output/ | tail -20
```

---

## Comparison: Local vs Cloud Run

| Aspect | Local Testing | Cloud Run Jobs |
|--------|--------------|----------------|
| **Speed** | Depends on local machine | Dedicated resources |
| **Cost** | Free | Charged per second |
| **Debugging** | Full IDE support | Logs only |
| **Data Access** | Requires local auth | Service account |
| **Best For** | Development, testing | Production, large backfills |
| **Limits** | Network, local CPU | Configurable resources |

### When to Use Each

**Use Local Testing When:**
- Developing new backfill jobs
- Testing logic changes
- Debugging issues
- Running small test batches
- Validating data transformations

**Use Cloud Run Jobs When:**
- Running full historical backfills
- Processing large amounts of data
- Running production workloads
- Need guaranteed resources
- Want automatic retry on failure

---

## Workflow: Development to Production

### 1. Develop Locally

```bash
# Write your backfill job
vim backfill_jobs/raw/new_job/new_job_raw_backfill.py

# Test with dry run
./bin/run_backfill.sh raw/new_job --dry-run --limit 5

# Test with limited data
./bin/run_backfill.sh raw/new_job --limit 10
```

### 2. Test with Representative Data

```bash
# Run with a full day
./bin/run_backfill.sh raw/new_job \
  --start-date 2024-10-01 \
  --end-date 2024-10-01

# Run with a full week
./bin/run_backfill.sh raw/new_job \
  --start-date 2024-10-01 \
  --end-date 2024-10-07
```

### 3. Deploy to Cloud Run

```bash
# Deploy the job
cd backfill_jobs/raw/new_job
./deploy.sh

# Test on Cloud Run with dry run
gcloud run jobs execute new-job-raw-backfill \
  --args=--dry-run,--limit=5 \
  --region=us-west2

# Run small test on Cloud Run
gcloud run jobs execute new-job-raw-backfill \
  --args=--limit=10 \
  --region=us-west2
```

### 4. Run Full Backfill

```bash
# Run full historical backfill on Cloud Run
gcloud run jobs execute new-job-raw-backfill \
  --region=us-west2
```

---

## Quick Reference

### List All Available Backfill Jobs

```bash
# List all backfill jobs
find backfill_jobs -name "*_backfill.py" -type f | sort

# List by phase
find backfill_jobs/scrapers -name "*_backfill.py" -type f
find backfill_jobs/raw -name "*_backfill.py" -type f
find backfill_jobs/analytics -name "*_backfill.py" -type f
```

### Get Help for Any Job

```bash
# Pattern
./bin/run_backfill.sh <phase>/<job> --help

# Examples
./bin/run_backfill.sh raw/bdl_injuries --help
./bin/run_backfill.sh analytics/player_game_summary --help
./bin/run_backfill.sh scrapers/odds_api_props --help
```

### Common Test Commands

```bash
# Quick test: dry run with 5 items
./bin/run_backfill.sh raw/bdl_injuries --dry-run --limit 5

# Small test: process 10 items
./bin/run_backfill.sh raw/bdl_injuries --limit 10

# Date range test: one week
./bin/run_backfill.sh raw/bdl_injuries \
  --start-date 2024-10-01 \
  --end-date 2024-10-07 \
  --dry-run

# Full local test: process one day
./bin/run_backfill.sh raw/bdl_injuries \
  --start-date 2024-10-01 \
  --end-date 2024-10-01
```

---

## Additional Resources

- **Deployment Guide**: See `docs/deployment_guide.md` (or respective phase deployment docs)
- **Job Configuration**: See `backfill_jobs/<phase>/<job>/job-config.env`
- **Architecture**: See `docs/phase_naming_architecture.md`
- **Monitoring**: Use `bin/<phase>/monitoring/` scripts for Cloud Run jobs

---

## Need Help?

1. **Check the job's help**: `./bin/run_backfill.sh <phase>/<job> --help`
2. **Check the job's README**: `backfill_jobs/<phase>/<job>/README.md`
3. **Review logs**: Look at console output for error messages
4. **Check GCS data**: Verify input data exists in the expected location
5. **Verify authentication**: Ensure `gcloud auth application-default login` is current

---

**Last Updated:** October 2025  
**Maintained By:** NBA Props Platform Team

