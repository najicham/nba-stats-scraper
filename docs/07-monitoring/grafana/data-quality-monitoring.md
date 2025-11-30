# Grafana Data Quality Monitoring Guide

**File:** `docs/07-monitoring/grafana/data-quality-monitoring.md`
**Created:** 2025-11-30
**Purpose:** Monitor player name resolution, circuit breakers, and data integrity
**Status:** Current

---

## Overview

This guide covers monitoring data quality across the NBA Props Platform using the Data Quality Dashboard. The dashboard tracks:

1. **Player Name Resolution** - Unresolved player names that can't be matched to the registry
2. **Circuit Breaker States** - Processor health and failure patterns
3. **Resolution Activity** - Progress on resolving name issues

**Dashboard JSON:** `dashboards/data-quality-dashboard.json`
**SQL Queries:** `dashboards/data-quality-queries.sql`

---

## Key Tables

### `nba_reference.unresolved_player_names`

Tracks player names that couldn't be matched to the registry.

| Column | Description |
|--------|-------------|
| `original_name` | The name as it appeared in source data |
| `normalized_lookup` | Standardized version for matching |
| `source` | Data source (nbac_gamebook, bdl_boxscores, etc.) |
| `team_abbr` | Team abbreviation |
| `occurrences` | How many times this name appeared |
| `status` | pending, resolved, ignored, snoozed |
| `first_seen_date` | When first encountered |
| `last_seen_date` | Most recent occurrence |

### `nba_orchestration.circuit_breaker_state`

Tracks processor health via circuit breaker pattern.

| Column | Description |
|--------|-------------|
| `processor_name` | Name of the processor |
| `state` | CLOSED (healthy), OPEN (blocked), HALF_OPEN (testing) |
| `failure_count` | Number of consecutive failures |
| `success_count` | Successes since last failure |
| `last_failure` | Timestamp of last failure |
| `last_error_message` | Error details |

---

## Dashboard Panels

### Row 1: Key Metrics (Stats)

#### Panel 1: Data Quality Health
**Type:** Stat Panel (Large)

Shows overall health: HEALTHY, WARNING, or CRITICAL

**Thresholds:**
- CRITICAL: >5 OPEN breakers OR >100 unresolved names
- WARNING: Any OPEN breakers OR >50 unresolved names
- HEALTHY: No OPEN breakers AND <50 unresolved names

#### Panel 2: Unresolved Names
Count of pending unresolved player names.

**Thresholds:**
- Green: < 50
- Yellow: 50-100
- Red: > 100

#### Panel 3: Open Circuit Breakers
Count of processors in OPEN state (blocking processing).

**Thresholds:**
- Green: 0
- Yellow: 1-2
- Red: > 3

#### Panel 4: Half-Open Breakers
Count of processors testing recovery.

#### Panel 5: Player Aliases
Total aliases in the registry (coverage indicator).

#### Panel 6: Recently Resolved
Names resolved in last 30 days (progress indicator).

---

### Row 2: Source Analysis

#### Panel 7: Unresolved Names by Source
Table showing breakdown by data source:
- Source name
- Unresolved count
- Teams affected
- Date range
- Total occurrences

**Action:** Focus on sources with highest counts first.

#### Panel 8: Circuit Breaker States
Table showing non-healthy circuit breakers:
- Processor name
- Current state (OPEN/HALF_OPEN)
- Failure count
- Last error preview

**Action:** Investigate OPEN breakers immediately.

---

### Row 3: Trends

#### Panel 9: New Unresolved Names Over Time
Stacked bar chart showing new unresolved names by source over 90 days.

**Use:** Identify if a specific source is generating new issues.

---

### Row 4: Detail Tables

#### Panel 10: Unresolved Names Detail
Top 50 unresolved names sorted by occurrences.

**Columns:** Original name, source, team, season, occurrences, dates

**Action:** Review high-occurrence names for manual resolution.

---

### Row 5: Additional Metrics

#### Panel 11: Circuit Breaker State Changes
Time series showing state changes over 30 days.

**Use:** Identify stability issues and recovery patterns.

#### Panel 12: Resolution Activity
Names resolved by reviewer and resolution type.

**Use:** Track manual resolution progress.

---

### Row 6: Summary

#### Panel 13: Name Resolution Summary
Overall statistics:
- Total names tracked
- Resolved count
- Pending count
- Resolution rate percentage

---

## Health Thresholds

### HEALTHY
- Unresolved names < 50
- No OPEN circuit breakers
- Resolution rate > 90%

### WARNING
- Unresolved names 50-100
- 1-2 HALF_OPEN breakers
- Resolution rate 80-90%

### CRITICAL
- Unresolved names > 100
- Any OPEN circuit breakers
- Resolution rate < 80%

---

## Common Issues and Actions

### High Unresolved Names from a Single Source

**Symptoms:** One source dominates the unresolved names table.

**Common Causes:**
- `nbac_gamebook`: NBA.com name format changes
- `bdl_boxscores`: Ball Don't Lie API variations
- `espn_rosters`: ESPN roster updates with new names

**Actions:**
1. Check if it's a systematic naming convention change
2. Review names for bulk resolution patterns
3. Consider adding automatic alias rules

### OPEN Circuit Breaker

**Symptoms:** Processor shows OPEN state, blocking processing.

**Immediate Actions:**
1. Check `last_error_message` for root cause
2. Review Cloud Run logs:
   ```bash
   gcloud run services logs read nba-phase3-analytics --region=us-west2 --limit=50
   ```
3. If transient, wait for automatic recovery
4. If persistent, fix root cause and redeploy

### Rising Unresolved Name Trend

**Symptoms:** New unresolved names increasing over time.

**Actions:**
1. Identify which source(s) are contributing
2. Check for data format changes in upstream sources
3. Review name normalization logic
4. Consider adding new alias patterns

---

## Alert Configurations

### Critical Alerts

**Alert 1: Too Many Unresolved Names**
```sql
SELECT COUNT(*) as critical_count
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending' OR status IS NULL
HAVING critical_count > 100
```
**Action:** Review and resolve high-impact names.

**Alert 2: Open Circuit Breakers**
```sql
SELECT COUNT(*) as open_count
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE state = 'OPEN'
HAVING open_count > 0
```
**Action:** Investigate and fix processor issues.

### Warning Alerts

**Alert 3: High-Occurrence Unresolved Name**
```sql
SELECT original_name, occurrences
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE (status = 'pending' OR status IS NULL)
  AND occurrences > 100
```
**Action:** Prioritize resolution of high-impact names.

---

## Manual Resolution Workflow

When resolving unresolved player names:

1. **Identify the player** - Use team, season, and source context
2. **Find canonical name** - Look up in `nba_players_registry`
3. **Add alias** - Insert into `player_aliases` table
4. **Mark resolved** - Update status in `unresolved_player_names`

```sql
-- Example: Add alias
INSERT INTO `nba-props-platform.nba_reference.player_aliases`
  (alias_lookup, nba_canonical_lookup, source, created_at)
VALUES
  ('smith_john_jr', 'smith_john', 'manual', CURRENT_TIMESTAMP());

-- Example: Mark resolved
UPDATE `nba-props-platform.nba_reference.unresolved_player_names`
SET status = 'resolved',
    resolution_type = 'alias_added',
    resolved_to_name = 'smith_john',
    reviewed_by = 'manual',
    reviewed_at = CURRENT_TIMESTAMP()
WHERE normalized_lookup = 'smith_john_jr';
```

---

## Integration with Other Dashboards

**Combined monitoring workflow:**

1. **Pipeline Health** (`pipeline-run-history-dashboard.json`)
   - Are processors running?
   - Any failures?

2. **Data Quality** (this dashboard)
   - Name resolution health
   - Circuit breaker status

3. **Completeness** (`completeness-dashboard.json`)
   - Is data complete?
   - Production readiness

---

## Expected Patterns

### Normal State
- New unresolved names: 0-5 per day
- Resolution rate: > 95%
- All circuit breakers CLOSED
- No OPEN states

### During Roster Changes (Trade deadline, Free agency)
- Higher unresolved name rate (10-20 per day)
- New player names appearing
- Expected and normal - just process backlog

### After Data Source Changes
- Spike in unresolved names from single source
- May need alias pattern updates
- Review and add systematic fixes

---

## Related Documentation

- `setup.md` - Grafana BigQuery setup
- `pipeline-monitoring.md` - Pipeline run history monitoring
- `monitoring-guide.md` - Phase 1 orchestration monitoring
- `dashboards/data-quality-dashboard.json` - Dashboard JSON
- `dashboards/data-quality-queries.sql` - SQL queries

---

**Last Updated:** 2025-11-30
**Version:** 1.0
**Status:** Ready for Implementation
