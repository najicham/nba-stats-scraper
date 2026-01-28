# Scheduled Queries

This directory contains BigQuery scheduled queries for automated monitoring.

## Overview

Scheduled queries run automatically on a defined schedule and write results to BigQuery tables for:
- Historical tracking
- Trend analysis
- Alerting and notifications

## Queries

### source_reconciliation.sql

**Purpose**: Daily cross-source data reconciliation (NBA.com vs BDL)

**Schedule**: Daily at 8:00 AM ET (after overnight box score processing)

**What it does**:
- Compares NBA.com official stats vs Ball Don't Lie stats for yesterday
- Flags discrepancies in points, assists, rebounds
- Writes results to `nba_monitoring.source_reconciliation_results` table

**Health Thresholds**:
- **CRITICAL**: Point difference >2 (affects prop settlement)
- **WARNING**: Assists/rebounds difference >2
- **MINOR_DIFF**: Any stat difference 1-2
- **MATCH**: Perfect match (expected 95%+)

**Setup**:

1. Create destination table:
   ```bash
   bq mk --table \
     --time_partitioning_field=run_timestamp \
     --time_partitioning_type=DAY \
     --time_partitioning_expiration=7776000 \
     --clustering_fields=health_status,game_date,team_abbr \
     --description="Daily source reconciliation results (NBA.com vs BDL)" \
     nba-props-platform:nba_monitoring.source_reconciliation_results \
     run_timestamp:TIMESTAMP,game_date:DATE,game_id:STRING,player_lookup:STRING,player_name:STRING,team_abbr:STRING,starter:BOOLEAN,presence_status:STRING,nbac_points:INT64,nbac_assists:INT64,nbac_rebounds:INT64,bdl_points:INT64,bdl_assists:INT64,bdl_rebounds:INT64,point_diff:INT64,assist_diff:INT64,rebound_diff:INT64,health_status:STRING,discrepancy_summary:STRING,stat_comparison:STRING,checked_at:TIMESTAMP
   ```

2. Create scheduled query:
   ```bash
   bq query \
     --use_legacy_sql=false \
     --schedule="0 8 * * *" \
     --location=us-west2 \
     --display_name="Source Reconciliation Daily" \
     --destination_table=nba-props-platform:nba_monitoring.source_reconciliation_results \
     --append_table=true \
     --replace=true \
     "$(cat monitoring/scheduled_queries/source_reconciliation.sql)"
   ```

3. Monitor via `/validate-daily` skill (Phase 3C section)

**Query Results**:
```bash
# View latest results
bq query --use_legacy_sql=false "
  SELECT health_status, COUNT(*) as count
  FROM \`nba-props-platform.nba_monitoring.source_reconciliation_results\`
  WHERE DATE(run_timestamp) = CURRENT_DATE()
  GROUP BY health_status
  ORDER BY FIELD(health_status, 'CRITICAL', 'WARNING', 'MINOR_DIFF', 'MATCH')
"

# View critical issues
bq query --use_legacy_sql=false "
  SELECT player_name, team_abbr, discrepancy_summary, stat_comparison
  FROM \`nba-props-platform.nba_monitoring.source_reconciliation_results\`
  WHERE DATE(run_timestamp) = CURRENT_DATE()
    AND health_status = 'CRITICAL'
"
```

## Adding New Scheduled Queries

1. Create a `.sql` file in this directory with:
   - Clear header comment with purpose, schedule, destination
   - Well-documented query logic
   - Example alerting queries in comments

2. Document the query in this README with:
   - Purpose and schedule
   - Setup instructions (table creation, scheduled query)
   - Example usage queries

3. Add monitoring section to `/validate-daily` skill if relevant

4. Test manually first:
   ```bash
   bq query --use_legacy_sql=false < monitoring/scheduled_queries/your_query.sql
   ```

## Best Practices

- **Schedule timing**: Run after upstream data is ready (e.g., 8 AM after overnight processing)
- **Partition tables**: Use `run_timestamp` for time-based partitioning
- **Cluster tables**: Cluster by common query filters (status, date, entity)
- **Retention**: Set expiration (e.g., 90 days) to control costs
- **Sampling**: For high-volume matches, store a sample (e.g., 10%) for trend analysis
- **Idempotency**: Use `WRITE_APPEND` not `WRITE_TRUNCATE` for audit trail

## Related Files

- `monitoring/bigquery_views/` - Views used by scheduled queries
- `.claude/skills/validate-daily/SKILL.md` - Daily validation that queries results
- `docs/02-operations/daily-operations-runbook.md` - Operations procedures
