# Workstream 1: Validation Hardening

## Mission
Make the daily validation system catch issues BEFORE they become problems, and provide clear morning visibility into overnight processing health.

## Current State

### What Exists
- `/validate-daily` skill in `.claude/skills/validate-daily/SKILL.md`
- `scripts/validate_tonight_data.py` - main validation script
- `bin/monitoring/daily_health_check.sh` - bash health check
- `scripts/spot_check_data_accuracy.py` - data quality spot checks
- `scripts/verify_golden_dataset.py` - golden dataset verification

### Known Issues
1. **Validation runs AFTER problems occur** - no pre-flight checks
2. **No automated morning alert** - user manually runs validation
3. **Missing tables cause errors** - e.g., `scraper_run_history` doesn't exist
4. **Thresholds not strict enough** - 63% minutes coverage wasn't flagged as critical
5. **Phase completion not validated** - 2/5 processors completing wasn't caught

### Recent Fixes (Session 8)
- Added two-level thresholds (WARNING 80-90%, CRITICAL <80%)
- Added explicit Phase 3 completion count check (must be 5/5)
- Added graceful fallbacks for missing tables
- Updated SKILL.md with better checks

## Goals

### 1. Morning Dashboard Query
Create a single query/script that shows overnight health at a glance:
```
Morning Health Summary - 2026-01-29
====================================
Yesterday's Games (2026-01-28): 9 games played

Phase 1 (Scrapers):     ✅ 9/9 games scraped
Phase 2 (Raw):          ✅ All processors complete
Phase 3 (Analytics):    ✅ 5/5 processors, 100% minutes coverage
Phase 4 (ML Features):  ✅ 305 features generated
Phase 5 (Predictions):  ✅ 2,629 predictions for 9 games

Data Quality:
- Minutes coverage: 100%
- Usage rate coverage: 98%
- Spot check accuracy: 97%

Alerts: None
```

### 2. Pre-Flight Checks (Run at 5 PM before games)
- Verify betting data is loaded
- Verify game context is ready
- Verify ML features exist for tonight's games
- Verify prediction worker is healthy

### 3. Post-Processing Verification (Run at 6 AM)
- Verify all games from yesterday have box scores
- Verify Phase 3 analytics completed for all games
- Verify predictions were graded
- Alert if any phase is stuck

### 4. Slack Integration
- Critical failures → #app-error-alerts
- Warnings → #nba-alerts
- Daily summary → #daily-orchestration

## Key Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `bin/monitoring/morning_health_check.sh` | CREATE | Single command morning dashboard |
| `scripts/validate_tonight_data.py` | MODIFY | Add pre-flight mode |
| `.claude/skills/validate-daily/SKILL.md` | MODIFY | Add morning dashboard instructions |
| `orchestration/cloud_functions/daily_health_check/main.py` | MODIFY | Add Slack alerts |

## Validation Queries to Add

### 1. Overnight Processing Summary
```sql
-- Single query showing overnight health
WITH game_counts AS (
  SELECT COUNT(DISTINCT game_id) as games_played
  FROM nba_analytics.player_game_summary
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),
phase3_status AS (
  SELECT
    COUNT(*) as total_records,
    COUNTIF(minutes_played IS NOT NULL) as has_minutes,
    ROUND(COUNTIF(minutes_played IS NOT NULL) * 100.0 / NULLIF(COUNT(*), 0), 1) as minutes_pct
  FROM nba_analytics.player_game_summary
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),
phase4_status AS (
  SELECT COUNT(*) as features
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),
phase5_status AS (
  SELECT COUNT(*) as predictions
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND is_active = TRUE
)
SELECT
  g.games_played,
  p3.total_records as player_records,
  p3.minutes_pct,
  p4.features,
  p5.predictions
FROM game_counts g, phase3_status p3, phase4_status p4, phase5_status p5
```

### 2. Stuck Phase Detection
```sql
-- Find phases that started but never completed
SELECT
  phase_name,
  game_date,
  start_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) as minutes_since_start
FROM nba_orchestration.phase_execution_log
WHERE status IN ('started', 'running')
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), start_time, MINUTE) > 60
```

### 3. Scraper Gap Summary
```sql
-- Quick view of scraper health
SELECT
  scraper_name,
  COUNT(*) as gap_count,
  MIN(game_date) as oldest_gap
FROM nba_orchestration.scraper_failures
WHERE backfilled = FALSE
GROUP BY scraper_name
HAVING COUNT(*) >= 3
```

## Success Criteria

1. **Morning check takes < 30 seconds** - Single command, clear output
2. **Critical issues trigger Slack alerts** - No manual checking needed
3. **Pre-flight catches missing data** - Before games start
4. **Zero false positives** - Graceful handling of edge cases
5. **Clear actionable output** - Not just "FAILED" but "FAILED: 63% minutes coverage, run X to fix"

## Testing Plan

1. Run morning check against last 3 days of data
2. Verify it catches the issues we found today (63% minutes, 2/5 phase completion)
3. Test Slack integration
4. Document in runbook

## Related Documentation
- `docs/02-operations/daily-operations-runbook.md`
- `docs/02-operations/troubleshooting-matrix.md`
- `docs/06-testing/SPOT-CHECK-SYSTEM.md`
