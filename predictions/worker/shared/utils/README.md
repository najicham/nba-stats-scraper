# Shared Utilities

**Location:** `shared/utils/`

Shared utility modules used across scrapers, processors, and monitoring systems.

## Core Utilities

### Logging & Alerting

#### `scraper_logging.py`
Simple, noise-free logging for scrapers that creates clean JSON logs stored in GCS.

```python
from shared.utils.scraper_logging import ScraperLogger

logger = ScraperLogger("bdl_box_scores")

# Option 1: Manual logging
logger.log_start(date="2025-10-14")
try:
    records = scrape_data()
    logger.log_end(status="SUCCESS", records_processed=len(records))
except Exception as e:
    logger.log_end(status="FAILED", error=str(e))
    raise

# Option 2: Context manager (recommended)
with logger.log_run(date="2025-10-14"):
    records = scrape_data()
```

**Features:**
- Minimal noise - only START/END events
- Stores logs in GCS as JSONL format
- Automatic duration tracking
- Daily summary reports

#### `smart_alerting.py`
Intelligent alert system that prevents email floods during backfills.

```python
from shared.utils.smart_alerting import SmartAlertManager

alert_mgr = SmartAlertManager()

# Enable backfill mode to batch errors
alert_mgr.enable_backfill_mode()

try:
    run_backfill()
finally:
    # Send summary email with all errors
    alert_mgr.disable_backfill_mode(send_summary=True)
```

**Features:**
- Rate limiting per error type (default: 60 min cooldown)
- Backfill mode batches errors
- Automatic error grouping
- Summary emails instead of spam

#### `email_alerting.py`
Email notification system for critical errors.

#### `notification_system.py`
Multi-channel notification system (email, Slack, etc.)

#### `processor_alerting.py`
Alerting specifically for data processors.

### Data Access

#### `bigquery_client.py`
BigQuery client wrapper with connection pooling.

#### `storage_client.py`
GCS client wrapper for reading/writing data files.

#### `pubsub_client.py`
Pub/Sub client for event-driven architecture.

### NBA Domain

#### `nba_team_mapper.py`
Maps team names/abbreviations across different data sources.

#### `player_name_normalizer.py`
Normalizes player names for matching across sources.

#### `player_name_resolver.py`
Resolves player identities across different APIs.

#### `player_registry/`
Player identification and resolution system.
- `reader.py` - Read player registry
- `resolver.py` - Resolve player IDs
- `exceptions.py` - Custom exceptions

#### `schedule/`
Schedule management utilities.
- `service.py` - Schedule service
- `database_reader.py` - Read schedule from BigQuery
- `gcs_reader.py` - Read schedule from GCS
- `models.py` - Schedule data models

#### `travel_team_info.py`
Team travel distance calculations.

### Authentication & Configuration

#### `auth_utils.py`
Authentication utilities for GCP services.

#### `sentry_config.py`
Sentry error tracking configuration.

### Odds & Props

#### `odds_preference.py`
Preferred sportsbook selection for game lines.

#### `odds_player_props_preference.py`
Preferred sportsbook selection for player props.

## Usage Patterns

### In Scrapers
```python
from shared.utils.scraper_logging import ScraperLogger
from shared.utils.storage_client import StorageClient

logger = ScraperLogger("my_scraper")
storage = StorageClient()

with logger.log_run(date=target_date):
    data = scrape_external_api()
    storage.upload_json(data, "raw/my_scraper/2025-10-14.json")
```

### In Processors
```python
from shared.utils.bigquery_client import BigQueryClient
from shared.utils.storage_client import StorageClient
from shared.utils.processor_alerting import ProcessorAlerter

bq = BigQueryClient()
storage = StorageClient()
alerter = ProcessorAlerter("my_processor")

try:
    raw_data = storage.download_json("raw/scraper/2025-10-14.json")
    processed = process_data(raw_data)
    bq.insert_rows("dataset.table", processed)
except Exception as e:
    alerter.send_error(e)
    raise
```

### In Workflows
```python
from shared.utils.smart_alerting import SmartAlertManager

alert_mgr = SmartAlertManager()

# For backfill operations
alert_mgr.enable_backfill_mode()
for date in date_range:
    try:
        scrape(date)
    except Exception as e:
        alert_mgr.record_error({
            "scraper": "bdl_box_scores",
            "date": date,
            "error": str(e)
        })

alert_mgr.disable_backfill_mode(send_summary=True)
```

## Adding New Utilities

When adding a new utility module:

1. Create the file in `shared/utils/`
2. Add comprehensive docstrings
3. Include usage examples in docstrings
4. Update this README
5. Add to `shared/requirements.txt` if needed
6. Write tests in `shared/utils/tests/` (if applicable)

## Testing

```bash
# Test individual utilities
python -m pytest shared/utils/tests/

# Test specific module
python -m pytest shared/utils/tests/test_storage_client.py
```

## Dependencies

See `shared/requirements.txt` for all dependencies.

Key dependencies:
- `google-cloud-storage` - GCS access
- `google-cloud-bigquery` - BigQuery access
- `google-cloud-logging` - Cloud Logging
- `google-cloud-pubsub` - Pub/Sub messaging
