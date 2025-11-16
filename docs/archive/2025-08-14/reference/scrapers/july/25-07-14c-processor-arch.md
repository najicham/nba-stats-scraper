# NBA Data Pipeline - Processor Architecture

## Overview

Processors are responsible for consuming scraped data files from Google Cloud Storage and persisting them to the database. They operate independently from scrapers, triggered via pub/sub messages, and handle data validation, transformation, and storage.

## Processor Design Principles

### Separation of Concerns
- **Scrapers**: Data collection and basic format validation
- **Processors**: Data transformation, business logic validation, and database persistence
- **Pub/Sub**: Decoupled communication between scrapers and processors

### Independent Operation
- Each processor operates independently
- Processors can be scaled individually based on data volume
- Failure in one processor doesn't affect others

## Processor Granularity

### One Processor Per Data Type
Each data type gets its own dedicated processor for clean separation and easier maintenance:

```
games-processor          → Handles NBA games data
boxscores-processor      → Handles team boxscore data  
player-boxscores-processor → Handles individual player stats
rosters-processor        → Handles team roster data
injuries-processor       → Handles player injury data
player-props-processor   → Handles betting prop odds
events-processor         → Handles betting events/games
play-by-play-processor   → Handles detailed game play-by-play
```

### Processor Responsibilities
- Read files from GCS based on pub/sub messages
- Validate data structure and business logic
- Transform data for database storage
- Handle duplicate data and idempotency
- Manage processing state and error conditions
- Send alerts for validation failures

## Pub/Sub Integration

### Message Format
Single topic with message filtering for processor routing:

```json
{
  "file_path": "/raw-data/ball-dont-lie/games/2025-07-15/20250715_143000.json",
  "data_source": "ball-dont-lie", 
  "data_type": "games",
  "scraper_class": "BdlGamesScraper",
  "status": "success",
  "timestamp": "2025-07-15T14:30:00Z",
  "file_size": 15420,
  "parameters": {"date": "2025-07-15"},
  "error_message": null
}
```

### Message Routing
- **Single topic**: `nba-data-pipeline`
- **Processor subscription filters**: Each processor subscribes with `data_type = "{type}"`
- **Error handling**: Failed scrapers send `status = "failure"` messages

## Processing State Management

### Process Tracking Table
Database table to track file processing status and prevent duplicate processing:

```sql
CREATE TABLE process_tracking (
    file_path VARCHAR(500) PRIMARY KEY,
    data_source VARCHAR(50) NOT NULL,
    data_type VARCHAR(50) NOT NULL,
    status ENUM('pending', 'processing', 'completed', 'failed') NOT NULL,
    processor_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    attempt_count INT DEFAULT 0,
    error_message TEXT,
    file_size INT,
    records_processed INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Processing Status Flow
1. **Pending**: File identified for processing
2. **Processing**: Processor actively working on file
3. **Completed**: Successfully processed and stored in database
4. **Failed**: Processing failed after retries

## Idempotency & Retry Logic

### Idempotency Strategy
```python
def process_file(file_path, processor_name):
    # Check if already processed
    status = get_processing_status(file_path)
    if status == 'completed':
        return  # Skip, already processed
    
    # Mark as processing
    update_status(file_path, 'processing', processor_name)
    
    try:
        # Process file
        records = process_data_file(file_path)
        update_status(file_path, 'completed', records_count=len(records))
    except Exception as e:
        handle_processing_error(file_path, e)
```

### Retry Logic
- **Database connection failures**: Automatic retry with exponential backoff
- **Data validation failures**: Move to error bucket, alert, no retry
- **Partial processing failures**: Restart from beginning (database transactions)
- **Max attempts**: 3 retries for transient failures

### Error Categories
- **Transient errors**: Network issues, database timeouts → Retry
- **Data errors**: Invalid format, missing required fields → Error bucket + alert
- **Logic errors**: Duplicate keys, constraint violations → Alert + manual review

## Processing Patterns

### Standard Processing Flow
1. **Receive pub/sub message** with file path and metadata
2. **Check processing status** in tracking table
3. **Download file** from GCS if not already processed
4. **Validate file format** and required fields
5. **Transform data** for database schema
6. **Begin database transaction**
7. **Insert/update records** with conflict resolution
8. **Commit transaction** and update status to completed
9. **Handle errors** with appropriate retry or alert logic

### File Processing Order
```
Priority 1 (Reference Data):
- rosters-processor
- events-processor  
- schedule-processor

Priority 2 (Game Data):
- games-processor
- injuries-processor

Priority 3 (Dependent Data):
- boxscores-processor
- player-boxscores-processor 
- player-props-processor
- play-by-play-processor
```

## Missing Reference Data Handling

### Graceful Degradation Strategy
- **Process available data**: Don't block on missing dependencies
- **Use fallback data**: Extract team names from boxscores if rosters unavailable
- **Backfill later**: Link data when dependencies become available
- **Flag incomplete records**: Mark records missing reference data for later enrichment

### Cross-Data Dependencies
```
Player Boxscores → Games (preferred, not required)
Player Props → Events (required for odds context)
Play-by-Play → Games (preferred for game context)
Injuries → Players (preferred for player context)
```

### Missing Data Patterns
- **Required dependencies**: Fail processing, retry later
- **Optional dependencies**: Process with available data, enrich later
- **Reference lookups**: Use embedded data from source file as fallback

## Error Handling

### Error File Management
Failed validation files moved to error directory:
```
/error-data/{data-source}/{data-type}/{date}/{timestamp}_{error-type}.json
```

### Alert Categories
- **High Priority**: Required dependency failures, data corruption
- **Medium Priority**: Optional dependency missing, format anomalies  
- **Low Priority**: Performance degradation, retry exhaustion

### Error Recovery
- **Data fixes**: Correct source data, reprocess from error bucket
- **Logic fixes**: Update processor code, reprocess affected files
- **Infrastructure fixes**: Resolve connectivity, automatic retry

## Processor Implementation Guidelines

### File Reading
```python
def read_file_from_gcs(file_path):
    """Read JSON file from GCS with error handling"""
    try:
        return storage_client.download_json(file_path)
    except NotFoundError:
        log_error(f"File not found: {file_path}")
        raise ProcessingError("File not found")
```

### Data Validation
```python
def validate_data_structure(data, expected_schema):
    """Validate required fields and data types"""
    # Check required fields exist
    # Validate data types
    # Check business logic constraints
    # Return validation errors for alerting
```

### Database Operations
```python
def store_with_conflict_resolution(records):
    """Store records with duplicate handling"""
    # Use INSERT ... ON DUPLICATE KEY UPDATE
    # Or UPSERT patterns for conflict resolution
    # Maintain data freshness with timestamps
```

## Monitoring & Observability

### Key Metrics
- **Processing latency**: Time from pub/sub to completion
- **Success rate**: Completed vs failed processing attempts
- **Queue depth**: Pending files in process_tracking table
- **Error rates**: By processor and error type

### Alerting Triggers
- **Processing failures** exceeding threshold
- **Queue backlog** growing beyond capacity
- **Missing critical dependencies** blocking downstream processing
- **Data quality issues** requiring manual intervention

## Deployment Strategy

### Cloud Run Processors
- Each processor deployed as separate Cloud Run service
- Triggered by pub/sub subscriptions with appropriate filters
- Auto-scaling based on message volume
- Shared database connection pooling

### Configuration Management
- Environment variables for database connections
- GCS bucket configurations
- Processor-specific settings (retry counts, timeouts)
- Alert thresholds and notification targets
