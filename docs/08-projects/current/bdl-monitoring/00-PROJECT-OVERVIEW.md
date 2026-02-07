# BDL (Ball Don't Lie) Monitoring & Issue Tracking

**Status:** BDL disabled since 2026-01-28. Full outage for 33+ consecutive days.
**Decision:** Pending vendor contact/cancellation.
**Last Updated:** Session 149 (2026-02-07)

## Current BDL Status

| Metric | Value |
|--------|-------|
| Monitoring period | Jan 1 - Feb 7, 2026 (33 days) |
| Full outage days | 32/33 (97%) |
| Data delivery rate | 0.4% (1/254 games) |
| When data arrived | 125h late (5+ days after game) |
| Major data mismatches | 57 (wrong minutes/points) |
| Total scrape attempts | 1,203 (all failed except 1 game) |

## Where BDL Is Disabled

```python
# data_processors/analytics/player_game_summary/player_game_summary_processor.py
USE_BDL_DATA = False  # Disabled 2026-01-28 due to data quality issues
```

## Monitoring Infrastructure

### Views & Tables

| Resource | Purpose | Query |
|----------|---------|-------|
| `nba_orchestration.bdl_service_issues` | Daily BDL health timeline | `SELECT * FROM nba_orchestration.bdl_service_issues ORDER BY game_date DESC LIMIT 30` |
| `nba_orchestration.bdl_game_scrape_attempts` | Per-game scrape tracking with latency | Partitioned by game_date |
| `nba_orchestration.source_discrepancies` | Field-level data mismatches | Filter: `backup_source = 'bdl'` |
| `nba_orchestration.bdl_quality_trend` | Rolling quality + readiness metric | `bdl_readiness` column: READY_TO_ENABLE / IMPROVING / NOT_READY |

### Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `bin/monitoring/bdl_issue_report.py` | Generate vendor report (markdown/text) | `PYTHONPATH=. python bin/monitoring/bdl_issue_report.py --output report.md` |
| `bin/monitoring/bdl_quality_alert.py` | Daily Slack quality alerts | Runs via GitHub Actions at 10 AM UTC |
| `bin/monitoring/check_bdl_data_quality.py` | Manual quality inspection | `python bin/monitoring/check_bdl_data_quality.py --days 7` |
| `bin/monitoring/cross_source_validator.py` | Cross-source validation | Stores results to `source_discrepancies` |
| `bin/bdl_latency_report.py` | Detailed latency report | `python bin/bdl_latency_report.py --start 2026-01-01 --end 2026-02-07` |
| `bin/bdl_completeness_check.py` | Find missing games | `python bin/bdl_completeness_check.py --days 7` |
| `tools/health/bdl_ping.py` | API liveness check | `python tools/health/bdl_ping.py` |

### Automated Monitoring

| System | Schedule | Channel |
|--------|----------|---------|
| `bdl_quality_alert.py` | Daily 10 AM UTC (GitHub Actions) | `#nba-alerts` |
| `bdl_availability_logger.py` | Every scrape attempt | `#nba-alerts` (missing games) |

### bdl_service_issues View Columns

The consolidated view tracks per day:
- `games_expected` - Games scheduled that day
- `games_eventually_available` - Games that eventually returned data (across all retry attempts)
- `games_never_available` - Games that never returned data despite retries
- `total_scrape_attempts` - Total API calls made
- `avg_hours_to_data` / `max_hours_to_data` - Latency when data did arrive
- `major_issues` / `minor_issues` - Data quality mismatches vs NBA.com
- `issue_type` - Classification: FULL_OUTAGE, MAJOR_OUTAGE, PARTIAL_OUTAGE, QUALITY_DEGRADATION, LATE_DATA, OPERATIONAL
- `issue_summary` - Human-readable description

### View SQL Definition

Source-controlled at: `schemas/bigquery/views/bdl_service_issues.sql`

To recreate the view:
```bash
cat schemas/bigquery/views/bdl_service_issues.sql | bq query --use_legacy_sql=false
```

## Re-enablement Path

When `bdl_readiness = 'READY_TO_ENABLE'` in the `bdl_quality_trend` view (< 5% major discrepancies for 7 consecutive days):

1. Set `USE_BDL_DATA = True` in `player_game_summary_processor.py`
2. Deploy the analytics service
3. Monitor quality for 1 week

## Known BDL Issues (Historical)

1. **Full API outage** (Jan 1 - present): Zero data returned for nearly all games
2. **Data accuracy** (when data was available): ~50% of players had wrong minutes/points
3. **Extreme latency**: Data arriving 5+ days after games
4. **West Coast game delays**: Historically worse coverage for late games
5. **Coverage gaps**: ~95% game coverage even when "working" (vs NBA.com 100%)

## Remaining BDL References in Code

Config/declaration files (NOT active queries, safe to leave):
- `shared/config/scraper_retry_config.yaml`
- `shared/config/data_sources/fallback_config.yaml`
- `shared/validation/config.py`, `chain_config.py`
- `shared/processors/patterns/smart_skip_mixin.py`, `fallback_source_mixin.py`, `quality_columns.py`
- `shared/validation/phase_boundary_validator.py`
- `shared/validation/validators/phase1_validator.py`, `phase2_validator.py`

Clean these up when BDL is formally decommissioned.

## Session History

- **Session 8**: BDL disabled due to data quality issues
- **Session 41**: Comprehensive BDL latency/quality investigation
- **Session 148**: Change detector migrated from BDL to nbac
- **Session 149**: All remaining active BDL queries migrated, issue tracking view + report created
