# Data Source Quality Monitoring

## Overview

This document describes the infrastructure for monitoring data source quality, particularly for backup sources like BDL (Ball Don't Lie API).

**Created:** Session 41 (2026-01-30)
**Status:** Active

---

## BDL Quality Monitoring

### Background

BDL was disabled as a backup data source in Session 8 (2026-01-28) due to data quality issues. The API returns incorrect data (~50% of actual minutes/points) for many players.

**Current Status:** `USE_BDL_DATA = False` in `player_game_summary_processor.py`

### Monitoring Infrastructure

| Component | Location | Purpose |
|-----------|----------|---------|
| Cloud Function | `data-quality-alerts` | Daily quality check at 7 PM ET |
| Storage Table | `nba_orchestration.source_discrepancies` | Historical quality data |
| Trend View | `nba_orchestration.bdl_quality_trend` | Quality trend with readiness indicator |

### Daily Automated Check

The `data-quality-alerts` Cloud Function runs daily at 7 PM ET and:
1. Compares BDL vs NBAC (NBA.com gamebook) data
2. Calculates coverage % and discrepancy rates
3. Stores metrics in `source_discrepancies` table
4. Sends Slack alerts if thresholds exceeded

### Checking BDL Quality

```sql
-- Check BDL quality trend over last 7 days
SELECT
  game_date,
  total_players,
  bdl_coverage,
  coverage_pct,
  major_discrepancies,
  major_discrepancy_pct,
  rolling_7d_major_pct,
  bdl_readiness
FROM nba_orchestration.bdl_quality_trend
ORDER BY game_date DESC
LIMIT 7;
```

### Readiness Levels

| Level | Criteria | Action |
|-------|----------|--------|
| `READY_TO_ENABLE` | <5% major discrepancies for 7 consecutive days | Safe to re-enable BDL |
| `IMPROVING` | <10% major discrepancies | Keep monitoring |
| `NOT_READY` | >10% major discrepancies | Keep BDL disabled |

### Re-enabling BDL

When `bdl_readiness = 'READY_TO_ENABLE'` for the latest date:

1. Verify quality has been stable for at least 7 days
2. Edit `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
3. Set `USE_BDL_DATA = True`
4. Deploy Phase 3 analytics processors
5. Monitor for 24-48 hours after re-enabling

---

## Soft Dependencies (80% Threshold)

### Background

Added in Session 41 to prevent all-or-nothing dependency failures. When a critical dependency has partial data (but coverage >= 80%), processing can continue in "degraded" mode.

### Configuration

In any processor that extends `AnalyticsProcessorBase`:

```python
class MyProcessor(AnalyticsProcessorBase):
    use_soft_dependencies = True          # Enable soft thresholds
    soft_dependency_threshold = 0.80      # 80% minimum coverage
```

### How It Works

1. `check_dependencies()` calculates coverage for each dependency:
   - `coverage = row_count / expected_count_min`
2. If coverage >= threshold, processing continues with warning
3. Stats track degraded state:
   - `stats['is_degraded_dependency_run'] = True`
   - `stats['overall_coverage'] = 0.85`  # Example

### Monitoring Degraded Runs

Check logs for warnings like:
```
⚠️ DEGRADED DEPENDENCY RUN: Processing with 85.0% coverage
```

Or query `processor_run_history` for runs with `is_degraded_dependency_run = true`.

---

## Related Documentation

- [Daily Validation Runbook](./daily-runbook.md)
- [Completeness Monitoring](./completeness-monitoring.md)
- [CLAUDE.md](../../CLAUDE.md) - BDL Data Quality Issues section

## Files

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/data_quality_alerts/main.py` | Daily quality checks |
| `data_processors/analytics/mixins/dependency_mixin.py` | Soft dependency logic |
| `schemas/bigquery/nba_orchestration/source_discrepancies.sql` | Schema + views |
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | `USE_BDL_DATA` flag |
