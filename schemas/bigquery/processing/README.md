# Infrastructure: Processing Monitoring

**Dataset:** `nba_processing`  
**Purpose:** Pipeline execution logs and data quality tracking

## Tables

- `analytics_processor_runs` - Execution logs with performance metrics
- `analytics_data_issues` - Data quality events
- `analytics_source_freshness` - Data arrival monitoring

## Usage

These tables are populated automatically by all processors.

## Deployment
```bash
# Create dataset
bq query --use_legacy_sql=false < datasets.sql

# Deploy tables
bq query --use_legacy_sql=false < processing_tables.sql
```
