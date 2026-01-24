# Code Quality Initiative - Changelog

All notable changes made during this project will be documented here.

---

## [Unreleased]

### Session 1 - 2026-01-24

#### Added
- Created project directory: `docs/08-projects/current/code-quality-2026-01/`
- Created README.md with executive summary and priority matrix
- Created PROGRESS.md with detailed task tracking
- Created CHANGELOG.md (this file)

#### Discovery
- Identified 5+ SQL injection vulnerabilities
- Found 17 utility files duplicated 9x each (153+ redundant files)
- Discovered test coverage gaps:
  - Scrapers: 147 files, ~1 test
  - Monitoring: 0 tests
  - Services: 0 tests
  - Tools: 0 tests
- Found 12 files over 1000 lines (largest: 4039 LOC)
- Found 10+ functions over 250 lines (largest: 692 LOC)
- Identified 47+ TODO comments

---

## Task Completion Log

### Security Fixes

### 2026-01-24 - Task #1: Fix SQL Injection Vulnerabilities

**Files Changed:**
- `scripts/validate_historical_season.py` - Converted 6 methods to use parameterized queries (@game_date, @start_date, @end_date)
- `scripts/smoke_test.py` - Converted main query to use parameterized @game_date
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` - Converted _extract_source_hashes to use parameterized @analysis_date

**Pattern Applied:**
```python
# Before (SQL injection risk)
query = f"WHERE game_date = '{game_date}'"

# After (parameterized - safe)
job_config = bigquery.QueryJobConfig(
    query_parameters=[bigquery.ScalarQueryParameter("game_date", "STRING", game_date)]
)
query = "WHERE game_date = @game_date"
result = bq_client.query(query, job_config=job_config)
```

**Verification:**
- [x] Code compiles without errors
- [ ] Manual testing with sample dates

**Notes:**
- `data_freshness_checker.py` uses hardcoded column names from fixed list - lower risk, not modified
- `resolution_cache.py` line 290 is `DELETE WHERE TRUE` - no user input, acceptable

### 2026-01-24 - Task #8: Add Missing Request Timeouts

**Files Changed:**
- `predictions/coordinator/shared/utils/processor_alerting.py` - Added timeout=30 to SendGrid API request
- `tools/health/bdl_data_analysis.py` - Added timeout=30 to BDL API request

**Notes:**
Other files (shared/utils/processor_alerting.py, notification_system.py, etc.) already had proper timeouts.

### 2026-01-24 - Task #11: Improve Error Handling for External APIs

**Files Changed:**
- `predictions/coordinator/shared/utils/processor_alerting.py` - Added try-except with specific RequestException handling
- `tools/health/bdl_data_analysis.py` - Added specific timeout exception handling

**Pattern Applied:**
```python
try:
    response = requests.post(url, json=data, timeout=30)
    # handle response
except requests.exceptions.Timeout:
    logger.error("Request timed out")
    return False
except requests.exceptions.RequestException as e:
    logger.error(f"Request failed: {e}")
    return False
```

**Notes:**
Other files reviewed already had proper error handling.

### Code Quality Improvements

### 2026-01-24 - Task #6: Extract Hardcoded Cloud Run URLs to Config

**Files Created:**
- `shared/config/service_urls.py` - Centralized Cloud Run service URL configuration

**Files Changed:**
- `bin/testing/replay_pipeline.py` - Updated to use centralized config

**Features:**
- Environment variable overrides for each service (e.g., PREDICTION_COORDINATOR_URL)
- Default URLs based on project number pattern
- ExternalAPIs class for non-Cloud Run endpoints (SendGrid, BallDontLie)
- Helper functions: get_service_url(), get_all_service_urls(), get_external_api()

### 2026-01-24 - Task #15: Create Deployment Script for New Cloud Functions

**Files Created:**
- `bin/deploy/deploy_new_cloud_functions.sh` - Deployment script for pipeline-dashboard and auto-backfill-orchestrator

**Notes:**
Script deploys both functions with proper configuration. Run from project root:
```bash
./bin/deploy/deploy_new_cloud_functions.sh
```

### 2026-01-24 - Task #2: Consolidate Duplicate Utility Files (Partial)

**Files Created:**
- `bin/maintenance/sync_shared_utils.py` - Sync script to keep duplicates in sync with canonical versions

**Analysis:**
- Duplicates exist for GCP Cloud Functions deployment (each function needs self-contained code)
- Currently 113 files are identical across all locations (in sync)
- 17 utility files tracked across 9 target directories

**Usage:**
```bash
# Check for differences
python bin/maintenance/sync_shared_utils.py --diff

# Sync all files
python bin/maintenance/sync_shared_utils.py

# Dry run
python bin/maintenance/sync_shared_utils.py --dry-run
```

**Notes:**
Full consolidation would require changing the deployment architecture (e.g., using a shared package).
The sync script maintains consistency for the current architecture.

### Test Coverage Additions

### 2026-01-24 - Task #3: Add Tests for Scrapers Module (Start)

**Files Created:**
- `tests/scrapers/unit/test_scraper_base.py` - 200+ lines of tests for ScraperBase class
- `tests/scrapers/conftest.py` - Shared fixtures for scraper tests

**Test Coverage Added:**
- ScraperOpts dataclass validation
- ScraperBase initialization and configuration
- URL construction hooks
- Retry logic configuration
- Data validation and transformation hooks
- Proxy handling options
- Skip options (skip_download, skip_export)
- Log level definitions

**Test Categories:**
- Unit tests for ScraperOpts
- Unit tests for ScraperBase initialization
- Unit tests for data validation hooks
- Integration tests for complete scraper implementation

**Notes:**
This establishes the testing framework for scrapers. Additional tests needed for:
- Individual scraper implementations (BDL, ESPN, NBA.com, etc.)
- HTTP download functionality with actual retries
- Exporter integration

### Refactoring

(No entries yet)

### Deployments

(No entries yet)

---

## Format

Each entry should follow this format:

```
### [Date] - Task #X: [Task Name]

**Files Changed:**
- `path/to/file1.py` - Description of change
- `path/to/file2.py` - Description of change

**Tests Added:**
- `tests/path/test_file.py` - X tests covering Y

**Verification:**
- [ ] Local tests pass
- [ ] Deployed successfully
- [ ] Verified in production

**Notes:**
Any additional context or follow-up items
```
