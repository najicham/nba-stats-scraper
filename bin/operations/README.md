# Operations Dashboard

Emergency Operations Dashboard for NBA Stats Scraper Platform

## Quick Start

```bash
# Quick status check (30 seconds)
./bin/operations/ops_dashboard.sh quick

# Full dashboard (2-3 minutes)
./bin/operations/ops_dashboard.sh

# Specific sections
./bin/operations/ops_dashboard.sh pipeline    # Pipeline health only
./bin/operations/ops_dashboard.sh errors      # Recent errors only
./bin/operations/ops_dashboard.sh workflows   # Workflow health only
```

## What It Monitors

### 1. Pipeline Health (Phases 1-4)
- **Phase 3 Analytics**: player_game_summary, team_offense/defense, upcoming context
- **Phase 4 Precompute**: player_composite_factors, shot zones, daily cache
- Shows row counts for yesterday's data
- Identifies missing or stale data

### 2. Data Quality Validation
- Feature completeness for ML training (minutes_played, usage_rate, etc.)
- Validation framework status
- Recent validation failures

### 3. Workflow & Orchestration
- 5-workflow system health:
  - early-morning-final-check
  - morning-operations
  - real-time-business
  - post-game-collection
  - late-night-recovery
- Success/failure rates
- Latest execution status

### 4. Backfill Progress
- Detects running backfill orchestrators
- Shows historical coverage (Phase 3/4)
- Real-time progress monitoring

### 5. Recent Errors (24h)
- Integrates with `nba-monitor` for detailed error analysis
- Falls back to gcloud logging if unavailable
- Groups similar errors

### 6. Action Items
- Failed workflows requiring investigation
- Low Phase 4 coverage warnings
- Stale data alerts (>48h old)

## Usage Modes

| Mode | Command | Use Case | Duration |
|------|---------|----------|----------|
| Quick | `ops_dashboard.sh quick` | Morning health check | 30 sec |
| Full | `ops_dashboard.sh` | Incident investigation | 2-3 min |
| Pipeline | `ops_dashboard.sh pipeline` | Data health check | 1 min |
| Validation | `ops_dashboard.sh validation` | Quality assessment | 1 min |
| Workflows | `ops_dashboard.sh workflows` | Orchestration check | 30 sec |
| Errors | `ops_dashboard.sh errors` | Error investigation | 1 min |
| Actions | `ops_dashboard.sh actions` | TODO list | 15 sec |

## Output Interpretation

### Status Icons

- ✓ (Green) = Healthy/Good
- ⚠ (Yellow) = Warning/Needs attention
- ✗ (Red) = Critical/Failed
- ? (Blue) = Unknown/Checking

### Health Thresholds

**Pipeline Health:**
- 80%+ = Healthy (green)
- 50-79% = Warning (yellow)
- <50% = Critical (red)

**Workflows:**
- All succeeded = Healthy
- 75%+ succeeded = Warning
- <75% succeeded = Critical

**Data Freshness:**
- <2 days old = Current
- 2-7 days old = Stale (warning)
- >7 days old = Very stale (critical)

## Integration with Other Tools

### nba-monitor (Python CLI)
```bash
# The dashboard uses nba-monitor for detailed error analysis
python3 monitoring/scripts/nba-monitor status
python3 monitoring/scripts/nba-monitor errors 24
```

### BigQuery Queries
```bash
# Reference queries in bin/operations/monitoring_queries.sql
bq query --use_legacy_sql=false < bin/operations/monitoring_queries.sql
```

### Backfill Progress Monitor
```bash
# For detailed backfill monitoring
python3 bin/infrastructure/monitoring/backfill_progress_monitor.py --continuous
```

## Troubleshooting

### Dashboard is slow
- Use `quick` mode for faster checks
- Check BigQuery quota (may be throttled)
- Reduce query date ranges in script

### "No data for yesterday"
- Normal if no games yesterday
- Check if today's data is available instead
- Verify pipeline ran successfully

### Workflow status shows "UNKNOWN"
- Workflows may not exist in GCP project
- Check gcloud authentication: `gcloud auth list`
- Verify project ID: `gcloud config get-value project`

### Errors not showing
- Verify nba-monitor is installed
- Check Cloud Logging permissions
- Ensure logs are being written

## Daily Operations Workflow

### Morning Check (5 minutes)
```bash
# 1. Quick status
./bin/operations/ops_dashboard.sh quick

# 2. If issues detected, run full dashboard
./bin/operations/ops_dashboard.sh

# 3. Investigate specific issues
./bin/operations/ops_dashboard.sh errors      # If errors shown
./bin/operations/ops_dashboard.sh workflows   # If workflow failures
```

### Incident Response
```bash
# 1. Full dashboard for context
./bin/operations/ops_dashboard.sh > /tmp/dashboard_$(date +%Y%m%d_%H%M%S).txt

# 2. Check specific problem area
./bin/operations/ops_dashboard.sh pipeline    # Data issues
./bin/operations/ops_dashboard.sh workflows   # Orchestration issues
./bin/operations/ops_dashboard.sh errors      # Error investigation

# 3. Use action items as checklist
./bin/operations/ops_dashboard.sh actions
```

## Related Documentation

- **Architecture**: `docs/01-architecture/v1.0-architecture-overview.md`
- **Operations**: `docs/02-operations/daily-operations-runbook.md`
- **Monitoring**: `docs/07-monitoring/`
- **Troubleshooting**: `docs/02-operations/troubleshooting-guide.md`

## Version History

- **v1.0** (2026-01-03): Initial release (Session 6)
  - Unified monitoring dashboard
  - Integrated pipeline, workflow, validation, and error tracking
  - Color-coded output with actionable items

## Maintenance

This dashboard integrates with:
- BigQuery tables (nba_analytics, nba_precompute, nba_orchestration)
- Cloud Workflows (5-workflow system)
- Cloud Logging
- Existing monitoring scripts (nba-monitor)

If pipeline architecture changes, update:
1. Table lists in `ops_dashboard.sh` (PHASE3_TABLES, PHASE4_TABLES)
2. Workflow lists (workflows array)
3. Monitoring queries in `monitoring_queries.sql`

## Support

For issues with the dashboard itself:
- Check script permissions: `chmod +x bin/operations/ops_dashboard.sh`
- Verify gcloud config: `gcloud config list`
- Check BigQuery access: `bq ls --project_id=nba-props-platform`

For pipeline issues detected by dashboard:
- See `docs/02-operations/troubleshooting-guide.md`
- Check relevant runbooks in `docs/02-operations/`

---

## Cloud Function Shared Directory Consolidation

### Overview

The `consolidate_cloud_function_shared.sh` script eliminates code duplication across cloud functions by replacing duplicated files with symlinks to the root `/shared/` directory.

**Problem Solved:** Previously, identical files were copied across 7 cloud functions, resulting in:
- 13 MB of duplicated code
- Configuration drift between functions
- 7x maintenance burden for every change

**Solution:** 673 symlinks created, reducing disk usage to 576 KB (95% reduction)

### Quick Start

```bash
# Preview changes without applying
./bin/operations/consolidate_cloud_function_shared.sh --dry-run

# Consolidate all cloud functions
./bin/operations/consolidate_cloud_function_shared.sh

# Verify symlinks are correct
./bin/operations/consolidate_cloud_function_shared.sh --verify

# Or use dedicated verification script
./bin/validation/verify_cloud_function_symlinks.sh
```

### Usage

```bash
# Consolidate all cloud functions
./bin/operations/consolidate_cloud_function_shared.sh

# Consolidate specific cloud function
./bin/operations/consolidate_cloud_function_shared.sh --cloud-function phase2_to_phase3

# Dry run (preview changes)
./bin/operations/consolidate_cloud_function_shared.sh --dry-run

# Verify symlinks
./bin/operations/consolidate_cloud_function_shared.sh --verify
```

### What Gets Consolidated

- **Utils**: completeness_checker.py, bigquery_utils.py, 50+ other utilities
- **Config**: orchestration_config.py (16,142 lines!), feature_flags.py
- **Processors**: early_exit_mixin.py, circuit_breaker_mixin.py, quality_mixin.py
- **Validation**: phase_boundary_validator.py, validation config
- **Directories**: alerts/, backfill/, change_detection/, clients/, etc.

### Impact

**Before:** 13 MB (2.2 MB × 7 cloud functions)
**After:** 576 KB (95% reduction)

**Maintenance:** Edit once in `/shared/`, propagates to all cloud functions automatically

### Documentation

Full documentation: `/docs/architecture/cloud-function-shared-consolidation.md`

### Related Scripts

- `/bin/validation/verify_cloud_function_symlinks.sh` - Verify symlinks
- `/bin/orchestrators/deploy_phase2_to_phase3.sh` - Deploy with symlinks
