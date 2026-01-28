# Pipeline Health Dashboard - BigQuery Views

This directory contains BigQuery views that power the Pipeline Health Dashboard, providing real-time visibility into system health across all pipeline phases.

## Views

### 1. `pipeline_processor_health.sql`
**Purpose**: Unified processor health monitoring across all pipeline phases

**Metrics Provided**:
- Per-processor health status (HEALTHY, DEGRADED, UNHEALTHY, STALE, NEVER_RAN)
- Failure tracking (24h, 7d, 30d windows)
- Last success tracking per processor
- Success rate trends
- Performance metrics (avg/max duration)
- Latest error messages
- Alert priority classification

**Key Columns**:
- `health_status`: Processor health classification
- `failures_24h`: Failure count in last 24 hours
- `days_since_success`: Days since last successful run
- `success_rate_7d`: 7-day success rate percentage
- `alert_priority`: CRITICAL, HIGH, MEDIUM, LOW

**Coverage**:
- Phase 1: Scrapers (scraper_execution_log)
- Phase 2: Raw Processing (processor_run_history)
- Phase 3: Analytics (processor_run_history)
- Phase 4: Precompute (processor_run_history + precompute_processor_runs)
- Orchestrators: Phase execution orchestrators

**Usage**:
```sql
-- Processors requiring attention
SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
WHERE health_status IN ('UNHEALTHY', 'STALE', 'NEVER_RAN')
ORDER BY alert_priority, failures_24h DESC;

-- Phase-level health overview
SELECT
  phase,
  COUNT(*) as total_processors,
  COUNTIF(health_status = 'HEALTHY') as healthy_count,
  COUNTIF(health_status = 'UNHEALTHY') as unhealthy_count
FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
GROUP BY phase;
```

### 2. `pipeline_health_summary.sql`
**Purpose**: High-level phase completion metrics

**Metrics Provided**:
- Phase 3/4/5 completion rates (% of games processed)
- Success/failure counts by phase
- Last 24 hours and last 7 days views
- Date coverage percentage

**Key Columns**:
- `completion_percentage`: Overall success rate
- `failure_rate`: Percentage of failed runs
- `date_coverage_percentage`: % of dates with at least one success

**Usage**:
```sql
-- Current health snapshot
SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
WHERE time_window = 'last_24h'
ORDER BY phase_name;
```

### 3. `processor_error_summary.sql`
**Purpose**: Detailed error analysis and retry tracking

**Metrics Provided**:
- Error counts by processor
- Error classification (transient vs permanent)
- Retry success rates
- Top error messages
- Alert priority levels

**Key Columns**:
- `error_count`: Total errors in time window
- `error_type`: 'transient' or 'permanent'
- `retry_success_rate`: % of retries that succeeded
- `alert_priority`: CRITICAL, HIGH, MEDIUM, LOW

**Usage**:
```sql
-- Top failing processors
SELECT * FROM `nba-props-platform.nba_monitoring.processor_error_summary`
WHERE time_window = 'last_24h'
  AND alert_priority IN ('CRITICAL', 'HIGH')
ORDER BY error_count DESC;
```

### 4. `prediction_coverage_metrics.sql`
**Purpose**: Track prediction coverage and gaps

**Metrics Provided**:
- % of players with predictions per game date
- Coverage trend over last 7 days
- Gap breakdown by reason
- Blocked predictions analysis
- Production readiness rates

**Key Columns**:
- `coverage_percentage`: % of players with lines that have predictions
- `coverage_7d_avg`: 7-day rolling average
- `gap_*`: Counts by gap reason (registry, features, etc.)
- `health_status`: HEALTHY, WARNING, DEGRADED, CRITICAL

**Usage**:
```sql
-- Coverage trend
SELECT game_date, coverage_percentage, coverage_7d_avg, health_status
FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;
```

### 5. `pipeline_latency_metrics.sql`
**Purpose**: End-to-end pipeline timing analysis

**Metrics Provided**:
- Time from game start to Phase 3 complete
- Time from Phase 3 to Phase 4 complete
- Time from Phase 4 to predictions ready
- Total end-to-end latency
- 7-day rolling averages

**Key Columns**:
- `phase*_latency_minutes`: Time spent in each phase
- `total_latency_minutes`: Game start to predictions ready
- `pipeline_health`: HEALTHY (<3h), DEGRADED (<6h), SLOW (>6h)

**Usage**:
```sql
-- Latest latency breakdown
SELECT game_date, phase3_latency_minutes, phase4_latency_minutes,
       phase5_latency_minutes, total_latency_minutes
FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
WHERE game_date = CURRENT_DATE();
```

## Deployment

### Create the nba_monitoring dataset (if not exists)
```bash
bq mk --dataset \
  --project_id=nba-props-platform \
  --location=us-east1 \
  --description="Pipeline health monitoring views and metrics" \
  nba_monitoring
```

### Deploy all views
```bash
# From repository root
cd monitoring/bigquery_views

# Deploy each view
bq query --use_legacy_sql=false < pipeline_processor_health.sql
bq query --use_legacy_sql=false < pipeline_health_summary.sql
bq query --use_legacy_sql=false < processor_error_summary.sql
bq query --use_legacy_sql=false < prediction_coverage_metrics.sql
bq query --use_legacy_sql=false < pipeline_latency_metrics.sql
```

Or use the deployment script:
```bash
./deploy_monitoring_views.sh
```

## Scheduled Queries

To materialize these views for faster dashboard loading, set up scheduled queries (see `scheduled_queries/` directory).

### Benefits of Scheduled Queries
1. **Performance**: Pre-computed results load instantly
2. **Cost**: Reduce repeated query execution
3. **History**: Maintain historical snapshots
4. **Alerting**: Enable threshold-based alerts

### Setup
```bash
cd scheduled_queries
./setup_scheduled_queries.sh
```

This creates hourly scheduled queries that populate:
- `nba_monitoring.pipeline_processor_health_materialized`
- `nba_monitoring.pipeline_health_summary_materialized`
- `nba_monitoring.processor_error_summary_materialized`
- `nba_monitoring.prediction_coverage_metrics_materialized`
- `nba_monitoring.pipeline_latency_metrics_materialized`

## Monitoring Queries

### Health Check
```sql
-- Per-processor health status
SELECT
  phase,
  COUNT(*) as total_processors,
  COUNTIF(health_status = 'HEALTHY') as healthy,
  COUNTIF(health_status = 'DEGRADED') as degraded,
  COUNTIF(health_status = 'UNHEALTHY') as unhealthy,
  COUNTIF(health_status = 'STALE') as stale,
  COUNTIF(health_status = 'NEVER_RAN') as never_ran
FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
GROUP BY phase
ORDER BY phase;

-- Overall phase health (aggregate view)
SELECT
  'Pipeline Health' as metric,
  CASE
    WHEN AVG(completion_percentage) >= 90 THEN 'HEALTHY'
    WHEN AVG(completion_percentage) >= 75 THEN 'DEGRADED'
    ELSE 'CRITICAL'
  END as status
FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
WHERE time_window = 'last_24h';
```

### Alert Triggers
```sql
-- Processors requiring immediate attention (from health view)
SELECT
  phase,
  processor_name,
  health_status,
  failures_24h,
  days_since_success,
  alert_priority,
  last_error_message
FROM `nba-props-platform.nba_monitoring.pipeline_processor_health`
WHERE health_status IN ('UNHEALTHY', 'STALE', 'NEVER_RAN')
ORDER BY alert_priority, failures_24h DESC
LIMIT 20;

-- Error detail analysis (from error summary)
SELECT
  processor_name,
  error_count,
  error_type,
  top_error_message
FROM `nba-props-platform.nba_monitoring.processor_error_summary`
WHERE time_window = 'last_24h'
  AND alert_priority = 'CRITICAL'
ORDER BY error_count DESC;
```

### Coverage Monitoring
```sql
-- Coverage degradation alert
SELECT
  game_date,
  coverage_percentage,
  coverage_7d_avg,
  coverage_gap_count
FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND coverage_percentage < 80  -- Alert threshold
ORDER BY game_date DESC;
```

### Latency Monitoring
```sql
-- Slow pipeline detection
SELECT
  game_date,
  total_latency_minutes,
  phase3_latency_minutes,
  phase4_latency_minutes,
  pipeline_health
FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND pipeline_health IN ('DEGRADED', 'SLOW')
ORDER BY total_latency_minutes DESC;
```

## Dashboard Integration

These views are designed to power:
1. **Cloud Monitoring Dashboard**: Real-time GCP console dashboard
2. **HTML Dashboard**: Standalone dashboard for quick access
3. **Alerting**: Cloud Monitoring alert policies
4. **Reporting**: Daily/weekly health reports

See `../dashboards/pipeline_health/` for dashboard configurations.

## Maintenance

### View Updates
When schemas change, update views and redeploy:
```bash
bq query --use_legacy_sql=false < view_name.sql
```

### Performance Optimization
- Views use clustering and partitioning from source tables
- Consider materializing for dashboards with high query frequency
- Monitor view query costs in Cloud Monitoring

### Data Retention
Views respect source table retention policies:
- `processor_run_history`: 365 days (partitioned)
- `precompute_processor_runs`: 365 days (partitioned)
- `player_prop_predictions`: No expiration (partitioned)
- `phase_execution_log`: 90 days (partitioned)

## Troubleshooting

### View Creation Fails
- Verify dataset exists: `bq ls --project_id=nba-props-platform nba_monitoring`
- Check permissions: Requires `bigquery.datasets.create` and `bigquery.tables.create`
- Validate SQL: Test query in BigQuery console first

### Missing Data
- Check source table population: Views depend on upstream data
- Verify date ranges: Views use relative date filters
- Review partitioning: Ensure partitioned tables are up to date

### Performance Issues
- Check query execution time in BigQuery console
- Consider materializing frequently-accessed views
- Review clustering effectiveness for common filters

## Related Documentation
- [Cloud Monitoring Dashboard Setup](../dashboards/pipeline_health/README.md)
- [Scheduled Queries Configuration](../dashboards/pipeline_health/scheduled_queries/README.md)
- [Alert Policies](../../alert-policies/README.md)
