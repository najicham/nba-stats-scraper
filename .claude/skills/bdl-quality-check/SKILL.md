---
name: bdl-quality-check
description: Check BDL service status, generate issue reports for vendor contact
---

# BDL Service Status Check

<command-name>/bdl-quality</command-name>

## Purpose

Check the current status of the BDL (Ball Don't Lie) API service, view issue history, and generate reports for vendor communication/cancellation.

## Usage

```
/bdl-quality                    # Quick status summary (last 14 days)
/bdl-quality report             # Generate full markdown report for vendor
/bdl-quality 30                 # Check last 30 days
```

## What This Skill Does

1. **Queries `nba_orchestration.bdl_service_issues`** view for daily service health
2. **Shows issue timeline** grouped by outage/quality/operational periods
3. **Reports retry & latency metrics** - did data eventually arrive? how late?
4. **Generates vendor-ready reports** via `bin/monitoring/bdl_issue_report.py`

## Instructions

### Step 1: Quick Status Check

Run this query to get the recent BDL status:

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  games_expected,
  games_eventually_available,
  games_never_available,
  total_scrape_attempts,
  avg_hours_to_data,
  issue_type,
  issue_summary
FROM nba_orchestration.bdl_service_issues
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
ORDER BY game_date DESC
"
```

### Step 2: Summary Statistics

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as days_tracked,
  COUNTIF(issue_type = 'FULL_OUTAGE') as full_outage_days,
  COUNTIF(issue_type IN ('MAJOR_OUTAGE', 'PARTIAL_OUTAGE')) as partial_outage_days,
  COUNTIF(issue_type LIKE '%QUALITY%') as quality_issue_days,
  COUNTIF(issue_type = 'OPERATIONAL') as operational_days,
  SUM(games_expected) as total_games,
  SUM(games_eventually_available) as games_got_data,
  SUM(games_never_available) as games_no_data,
  SUM(total_scrape_attempts) as total_attempts,
  ROUND(100.0 * SUM(games_eventually_available) / SUM(games_expected), 1) as delivery_pct
FROM nba_orchestration.bdl_service_issues
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 45 DAY)
"
```

### Step 3: Generate Report (if user asks for "report")

```bash
PYTHONPATH=. python bin/monitoring/bdl_issue_report.py --format markdown --days 45
```

Or save to file:
```bash
PYTHONPATH=. python bin/monitoring/bdl_issue_report.py --output bdl_cancellation_report.md --days 45
```

## Output Format

Provide a summary like:

```
## BDL Service Status

**Current Status:** FULL_OUTAGE (since YYYY-MM-DD)

### Last 14 Days
| Date | Games | Available | Attempts | Latency | Status |
|------|-------|-----------|----------|---------|--------|
| ...  | ...   | ...       | ...      | ...     | ...    |

### Overall (45 days)
- X days full outage, Y days partial, Z days operational
- Data delivery rate: X.X% (N/M games)
- N games never received data despite M scrape attempts
- When data arrived: avg Xh delay, max Yh delay

### Recommendation
[Based on current data - re-enable, continue monitoring, or cancel]
```

## Key Columns in bdl_service_issues

| Column | Meaning |
|--------|---------|
| `games_eventually_available` | Games that got data on ANY retry attempt |
| `games_never_available` | Games that never got data despite all retries |
| `total_scrape_attempts` | Total API calls (multiple per game) |
| `avg_hours_to_data` | Average latency when data did arrive |
| `max_hours_to_data` | Worst-case latency |
| `issue_type` | FULL_OUTAGE / MAJOR_OUTAGE / PARTIAL_OUTAGE / QUALITY_DEGRADATION / LATE_DATA / OPERATIONAL |

## Background

- BDL API disabled 2026-01-28 due to persistent data quality issues
- All active queries migrated to NBA.com (`nbac_gamebook_player_stats`) in Session 149
- Monitoring continues via automated scrape attempts + this view
- Re-enablement requires `bdl_readiness = 'READY_TO_ENABLE'` in `nba_orchestration.bdl_quality_trend`

## Related Files

- Issue tracking view: `schemas/bigquery/views/bdl_service_issues.sql`
- Report generator: `bin/monitoring/bdl_issue_report.py`
- Quality alerts: `bin/monitoring/bdl_quality_alert.py` (daily via GitHub Actions)
- Project docs: `docs/08-projects/current/bdl-monitoring/00-PROJECT-OVERVIEW.md`
