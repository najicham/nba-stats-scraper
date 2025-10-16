# Backfill Jobs

**Last Updated:** January 2025  
**Maintained By:** NBA Props Platform Team

---

## Overview

Backfill jobs populate historical data for each phase of the NBA Props Platform data pipeline. Each job retrieves or processes data for a specific date range and can be run locally for testing or on Google Cloud Run Jobs for production backfills.

**What Backfill Jobs Do:**
- Process historical data in batch mode
- Support dry-run testing without affecting data
- Include resume logic to skip already-processed data
- Provide detailed logging and progress tracking
- Run on Google Cloud Run with configurable resources

**Key Principles:**
- **Idempotent** - Can be run multiple times safely
- **Resumable** - Skip already-processed data to save time
- **Testable** - Always test locally before deploying
- **Observable** - Detailed logging and monitoring

---

## Quick Start

### Run Locally

```bash
# Test any backfill job locally
./bin/run_backfill.sh <phase>/<job_name> [args...]

# Examples:
./bin/run_backfill.sh raw/bdl_injuries --dry-run --limit=5
./bin/run_backfill.sh analytics/player_game_summary --dry-run
./bin/run_backfill.sh scrapers/odds_api_props --start-date=2024-10-01 --end-date=2024-10-07
```

See **[RUNNING_LOCALLY.md](RUNNING_LOCALLY.md)** for complete local testing guide.

### Deploy to Cloud Run

```bash
# Deploy any backfill job
cd backfill_jobs/<phase>/<job_name>
./deploy.sh

# Test on Cloud Run
gcloud run jobs execute <job-name> --args=--dry-run --region=us-west2
```

See **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** for complete deployment guide.

---

## Directory Structure

This directory is organized by the **6-phase data pipeline architecture**:

```
backfill_jobs/
├── README.md                    # This file - overview and navigation
├── RUNNING_LOCALLY.md          # Guide for local testing
├── DEPLOYMENT_GUIDE.md         # Guide for deploying to Cloud Run
│
├── scrapers/                   # Phase 1: Data Collection
│   ├── README.md              # Scraper phase overview
│   ├── odds_api_props/        # Example scraper job
│   ├── nbac_gamebook/
│   └── ...                    # 12+ scraper backfill jobs
│
├── raw/                        # Phase 2: Data Normalization
│   ├── README.md              # Raw processor phase overview
│   ├── GUIDE.md               # Creating raw processor backfills
│   ├── bdl_injuries/          # Example raw processor job
│   ├── odds_api_props/
│   └── ...                    # 20+ raw processor backfill jobs
│
├── analytics/                  # Phase 3: Analytics Enrichment
│   ├── README.md              # Analytics phase overview
│   ├── player_game_summary/   # Example analytics job
│   ├── team_offense_game_summary/
│   └── ...                    # 4+ analytics backfill jobs
│
├── precompute/                 # Phase 4: Report Precompute (future)
│   └── (to be implemented)
│
├── prediction/                 # Phase 5: Prediction Generation (future)
│   └── (to be implemented)
│
├── publishing/                 # Phase 6: Report Publishing (future)
│   └── (to be implemented)
│
└── reference/                  # Reference Data
    └── gamebook_registry/     # Gamebook metadata registry
```

---

## Phase Overview

### Phase 1: Scrapers (Data Collection)

**Purpose:** Fetch raw data from external APIs and websites, save to GCS

**Input:** External APIs (Odds API, Ball Don't Lie, NBA.com, etc.)  
**Output:** Raw JSON/HTML/PDF files in Google Cloud Storage  
**Example:** `scrapers/odds_api_props` - Scrape player prop odds from sportsbooks

**Jobs:** 12+ scraper backfill jobs available

**Learn More:** See `scrapers/README.md` and **[scrapers/GUIDE.md](scrapers/GUIDE.md)** *(coming soon)*

### Phase 2: Raw Processors (Data Normalization)

**Purpose:** Read GCS files, parse and normalize, load to BigQuery `nba_raw` tables

**Input:** Raw files from GCS (Phase 1 output)  
**Output:** Structured data in BigQuery `nba_raw` tables  
**Example:** `raw/bdl_injuries` - Process injury reports into structured format

**Jobs:** 20+ raw processor backfill jobs available

**Learn More:** See `raw/README.md` and **[raw/GUIDE.md](raw/GUIDE.md)**

### Phase 3: Analytics (Analytics Enrichment)

**Purpose:** Compute derived metrics, contextual data, feature engineering

**Input:** BigQuery `nba_raw` tables (Phase 2 output)  
**Output:** Enriched analytics in BigQuery `nba_analytics` tables  
**Example:** `analytics/player_game_summary` - Combine player stats with game context

**Jobs:** 4+ analytics backfill jobs available

**Learn More:** See `analytics/README.md` and **[analytics/GUIDE.md](analytics/GUIDE.md)** *(coming soon)*

### Phase 4-6: Future Phases

**Precompute** (Phase 4), **Prediction** (Phase 5), and **Publishing** (Phase 6) are planned for future implementation.

### Reference Data

**Purpose:** Populate reference/lookup tables that support other phases

**Example:** `reference/gamebook_registry` - Track gamebook metadata and coverage

---

## Backfill Job Naming Convention

All backfill job files follow a consistent naming pattern:

```
<job_name>_<phase>_backfill.py
```

### Phase Suffixes

| Phase | Directory | Suffix | Example |
|-------|-----------|--------|---------|
| Scrapers | `scrapers/` | `_scraper_backfill.py` | `odds_api_props_scraper_backfill.py` |
| Raw Processors | `raw/` | `_raw_backfill.py` | `bdl_injuries_raw_backfill.py` |
| Analytics | `analytics/` | `_analytics_backfill.py` | `player_game_summary_analytics_backfill.py` |
| Precompute | `precompute/` | `_precompute_backfill.py` | *(future)* |
| Prediction | `prediction/` | `_prediction_backfill.py` | *(future)* |
| Publishing | `publishing/` | `_publishing_backfill.py` | *(future)* |
| Reference | `reference/` | `_reference_backfill.py` | `gamebook_registry_reference_backfill.py` |

### Job Directory Structure

Each backfill job follows this structure:

```
backfill_jobs/<phase>/<job_name>/
├── <job_name>_<phase>_backfill.py   # Main Python script
├── deploy.sh                         # Deployment wrapper
├── job-config.env                    # Resource configuration
└── README.md                         # Optional: Job-specific docs
```

---

## Common Workflows

### Testing a New Job Locally

```bash
# 1. Check available options
./bin/run_backfill.sh raw/bdl_injuries --help

# 2. Dry run to see what would be processed
./bin/run_backfill.sh raw/bdl_injuries --dry-run --limit=10

# 3. Process a few items
./bin/run_backfill.sh raw/bdl_injuries --limit=5

# 4. Process one day
./bin/run_backfill.sh raw/bdl_injuries \
  --start-date=2024-10-01 \
  --end-date=2024-10-01
```

### Deploying and Running on Cloud Run

```bash
# 1. Navigate to job directory
cd backfill_jobs/raw/bdl_injuries

# 2. Deploy the job
./deploy.sh

# 3. Test with dry run
gcloud run jobs execute bdl-injuries-processor-backfill \
  --args=--dry-run,--limit=5 \
  --region=us-west2

# 4. Small test
gcloud run jobs execute bdl-injuries-processor-backfill \
  --args=--limit=10 \
  --region=us-west2

# 5. Full backfill
gcloud run jobs execute bdl-injuries-processor-backfill \
  --region=us-west2
```

### Monitoring Executions

```bash
# List recent executions
gcloud run jobs executions list \
  --job=bdl-injuries-processor-backfill \
  --region=us-west2 \
  --limit=5

# View logs
gcloud beta run jobs executions logs read <execution-id> \
  --region=us-west2 \
  --follow
```

---

## Documentation Index

### Getting Started Guides

- **[RUNNING_LOCALLY.md](RUNNING_LOCALLY.md)** - Complete guide to running backfill jobs locally
- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** - Complete guide to deploying jobs to Cloud Run

### Phase-Specific Guides

- **[raw/GUIDE.md](raw/GUIDE.md)** - Creating raw processor backfill jobs
- **[scrapers/GUIDE.md](scrapers/GUIDE.md)** - Creating scraper backfill jobs *(coming soon)*
- **[analytics/GUIDE.md](analytics/GUIDE.md)** - Creating analytics backfill jobs *(coming soon)*

### Phase Overviews

- **[scrapers/README.md](scrapers/README.md)** - Scraper phase overview and job list
- **[raw/README.md](raw/README.md)** - Raw processor phase overview and job list
- **[analytics/README.md](analytics/README.md)** - Analytics phase overview and job list

### Additional Resources

- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Common issues and solutions *(coming soon)*
- **[CREATING_NEW_JOBS.md](CREATING_NEW_JOBS.md)** - Step-by-step guide for new jobs *(coming soon)*

---

## Common Arguments

Most backfill jobs support these standard arguments:

| Argument | Description | Example |
|----------|-------------|---------|
| `--help` | Show available options | `--help` |
| `--dry-run` | Show what would be processed without running | `--dry-run` |
| `--limit N` | Process only N items (testing) | `--limit=10` |
| `--start-date` | Start date for processing | `--start-date=2024-10-01` |
| `--end-date` | End date for processing | `--end-date=2024-10-31` |
| `--bucket` | GCS bucket name | `--bucket=nba-scraped-data` |

**Note:** When running on Cloud Run, use comma-separated format with no spaces:
```bash
--args=--dry-run,--start-date=2024-10-01,--end-date=2024-10-31
```

---

## Best Practices

### Before Running Any Backfill

✅ **Test locally first** - Use `./bin/run_backfill.sh` with `--dry-run`  
✅ **Start small** - Test with `--limit=5` before processing everything  
✅ **Verify data** - Check that input data exists and output looks correct  
✅ **Check resources** - Ensure job has adequate memory/CPU/timeout configured

### When Deploying

✅ **Review job-config.env** - Verify resource allocation is appropriate  
✅ **Test on Cloud Run** - Run with `--dry-run` after deployment  
✅ **Monitor first runs** - Watch logs during initial executions  
✅ **Validate output** - Check BigQuery/GCS after test runs

### For Production Backfills

✅ **Schedule appropriately** - Run during off-peak hours if processing large volumes  
✅ **Monitor progress** - Set up alerts or check logs periodically  
✅ **Document results** - Record what was backfilled and when  
✅ **Validate completeness** - Check that all expected data was processed

---

## Getting Help

### For Local Testing Issues
- Check **[RUNNING_LOCALLY.md](RUNNING_LOCALLY.md)** troubleshooting section
- Verify virtual environment is activated
- Ensure dependencies are installed
- Check authentication with `gcloud auth application-default login`

### For Deployment Issues
- Check **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** troubleshooting section
- Verify `job-config.env` is correct
- Check Cloud Build logs in GCP Console
- Ensure service account has required permissions

### For Job-Specific Issues
- Check the job's README if it exists: `backfill_jobs/<phase>/<job>/README.md`
- Review the job's configuration: `backfill_jobs/<phase>/<job>/job-config.env`
- Look at similar jobs in the same phase for examples
- Check phase-specific GUIDE.md for common patterns

### For Phase-Specific Questions
- **Scrapers:** See `scrapers/README.md`
- **Raw Processors:** See `raw/README.md` and `raw/GUIDE.md`
- **Analytics:** See `analytics/README.md`

---

## Related Documentation

- **[Architecture Documentation](../docs/)** - Overall system architecture *(if exists)*
- **[Data Pipeline Documentation](../docs/)** - How the 6 phases work together *(if exists)*
- **[Deployment Scripts](../bin/)** - Helper scripts for deployment and monitoring

---

## Quick Reference Commands

```bash
# List all available backfill jobs
find backfill_jobs -name "*_backfill.py" -type f | sort

# List jobs by phase
find backfill_jobs/scrapers -name "*_backfill.py"
find backfill_jobs/raw -name "*_backfill.py"
find backfill_jobs/analytics -name "*_backfill.py"

# Run any job locally
./bin/run_backfill.sh <phase>/<job> [args]

# Deploy any job
cd backfill_jobs/<phase>/<job> && ./deploy.sh

# Execute on Cloud Run
gcloud run jobs execute <job-name> --region=us-west2

# Monitor executions
gcloud run jobs executions list --job=<job-name> --region=us-west2
```

---

**For questions or support:** Review the phase-specific guides and troubleshooting sections, or consult with the team.

**Contributing:** When creating new backfill jobs, follow the patterns in the phase-specific GUIDE.md files and ensure all required files are included.

---

**Last Updated:** January 2025  
**Next Review:** When new phases are implemented or significant changes made
