# BigQuery Schema Definitions

This directory contains SQL schema definitions for BigQuery tables used by the NBA stats pipeline.

## Tables

### Monitoring Tables

#### `nba_monitoring.phase_boundary_validations`
**Purpose:** Stores validation results from phase transitions (Phase 1→2, Phase 2→3, Phase 3→4)

**Created by:** Robustness Improvements Implementation (Jan 21, 2026)

**Schema File:** `phase_boundary_validations.sql`

**Retention:** 90 days (configurable via `partition_expiration_days`)

**Partitioning:** Partitioned by `validation_timestamp` (daily), clustered by `phase_name`, `validation_type`, `is_valid`

**Usage:**
```sql
-- Get recent validation failures
SELECT * FROM nba_monitoring.phase_boundary_validations
WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
AND is_valid = FALSE
ORDER BY validation_timestamp DESC;
```

## Creating Tables

### Option 1: Using bq CLI
```bash
# From repository root
bq query --use_legacy_sql=false < orchestration/bigquery_schemas/phase_boundary_validations.sql
```

### Option 2: Using BigQuery Console
1. Go to [BigQuery Console](https://console.cloud.google.com/bigquery)
2. Select your project
3. Click "Compose New Query"
4. Paste the SQL from the schema file
5. Click "Run"

### Option 3: Automated (via deployment script)
```bash
# Create all monitoring tables
./orchestration/scripts/create_monitoring_tables.sh
```

## Table Maintenance

### Check Table Size
```bash
bq show --format=prettyjson nba_monitoring.phase_boundary_validations | jq '.numBytes'
```

### Check Partition Expiration
```bash
bq show --format=prettyjson nba_monitoring.phase_boundary_validations | jq '.timePartitioning'
```

### Manually Delete Old Partitions (if needed)
```sql
-- Delete partitions older than 120 days
DELETE FROM nba_monitoring.phase_boundary_validations
WHERE validation_timestamp < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 120 DAY);
```

## Monitoring Queries

### Validation Success Rate by Phase
```sql
SELECT
  phase_name,
  validation_type,
  COUNT(*) as total_validations,
  SUM(CASE WHEN is_valid THEN 1 ELSE 0 END) as valid_count,
  ROUND(AVG(CASE WHEN is_valid THEN 1 ELSE 0 END) * 100, 2) as success_rate_pct
FROM nba_monitoring.phase_boundary_validations
WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY phase_name, validation_type
ORDER BY success_rate_pct ASC;
```

### Daily Validation Failures
```sql
SELECT
  DATE(validation_timestamp) as date,
  phase_name,
  validation_type,
  COUNT(*) as failure_count,
  STRING_AGG(message, '\n' LIMIT 5) as sample_messages
FROM nba_monitoring.phase_boundary_validations
WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
AND is_valid = FALSE
GROUP BY date, phase_name, validation_type
ORDER BY date DESC, failure_count DESC;
```

### Game Count Trends
```sql
SELECT
  DATE(validation_timestamp) as date,
  phase_name,
  AVG(actual_value) as avg_actual_games,
  AVG(expected_value) as avg_expected_games,
  AVG(actual_value / NULLIF(expected_value, 0)) as avg_ratio
FROM nba_monitoring.phase_boundary_validations
WHERE validation_type = 'game_count'
AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date, phase_name
ORDER BY date DESC;
```

## Access Control

### Grant Read Access
```bash
# Grant read access to monitoring tables
bq add-iam-policy-binding \
  --member="serviceAccount:nba-pipeline@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer" \
  nba_monitoring
```

### Grant Write Access
```bash
# Grant write access for pipeline services
bq add-iam-policy-binding \
  --member="serviceAccount:nba-pipeline@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor" \
  nba_monitoring
```

## Related Documentation

- **Validation Framework:** `/shared/validation/phase_boundary_validator.py`
- **Configuration:** `/shared/config/rate_limit_config.py`
- **Implementation Plan:** `/docs/08-projects/current/robustness-improvements/`

---

**Last Updated:** January 21, 2026
**Owner:** Data Platform Team
