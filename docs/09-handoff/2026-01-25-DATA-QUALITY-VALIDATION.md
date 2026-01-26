# Data Quality Validation Report - player_game_summary

**Date:** 2026-01-25
**Scope:** Oct 2025 - Jan 2026 (Current Season)
**Focus:** minutes_played and usage_rate field quality
**Status:** ⚠️ **CRITICAL ISSUES FOUND**

---

## Executive Summary

Comprehensive validation of 2025-26 season data quality revealed **critical pipeline failures** affecting ML model predictions:

### Key Findings

1. **✅ FIXED:** `minutes_played` bug from Nov 3-Jan 2 has been resolved
   - Current coverage: 56-100% (recovering)
   - Issue: Numeric coercion destroyed "MM:SS" format data

2. **❌ NOT DEPLOYED:** `usage_rate` fix deployed Jan 3 but **NOT running in production**
   - Current coverage: 0-54.1% (only Jan 24 has data)
   - Issue: Team stats join only executed on Jan 24, not running daily

3. **⚠️ ML PREDICTIONS DEGRADED:** Oct 2025 - Jan 2026 using default values
   - `minutes_avg_last_10` defaulting to 28.0 for most players (Nov-Dec)
   - Model cannot distinguish starters from bench players during failure period

---

## Detailed Findings

### 1. Monthly Data Quality Trends (Oct 2025 - Jan 2026)

| Month | Total Records | minutes_played Coverage | usage_rate Coverage | Status |
|-------|--------------|------------------------|---------------------|--------|
| Oct 2025 | 1,566 | **64.2%** ⚠️ | 0.0% ❌ | Degrading |
| Nov 2025 | 7,493 | **64.8%** ⚠️ | 1.2% ❌ | Failed (NULL bug) |
| Dec 2025 | 5,563 | **77.7%** ⚠️ | 2.9% ❌ | Failed (NULL bug) |
| Jan 2026 | 4,382 | **89.8%** ✅ | 4.0% ❌ | Partial recovery |

**Comparison to 2024-25 Season:**
- Oct 2024 - May 2025: **99-100%** coverage for both fields
- Oct 2025 - Jan 2026: **64-90%** minutes, **0-4%** usage_rate

**Impact:** ~15,000 player-game records with degraded data quality over 4 months.

---

### 2. Daily Data Quality (January 2026)

| Date | Total | minutes_played | usage_rate | Team Stats Join | Notes |
|------|-------|---------------|------------|----------------|-------|
| Jan 1 | 118 | 87.3% | 0% | ✅ Joined (but calc failed) | Anomaly |
| Jan 2-7 | 1,296 | 100% | 0% | ❌ Not joined | Fixed (minutes) |
| **Jan 8** | **79** | **100%** | **98.7%** | ❌ Not joined | **Backfill/test run?** |
| Jan 9-23 | 2,697 | 56-100% | 0% | ❌ Not joined | Not deployed |
| **Jan 24** | **183** | **68.3%** | **54.1%** | ✅ **Joined (2026-01-25 11:30)** | **Production run** |

**Key Observations:**

1. **Jan 8 Anomaly:**
   - 98.7% usage_rate coverage
   - NO team stats join timestamp
   - Suggests data from pre-Nov processor or backfill with old code

2. **Jan 24 Production Run:**
   - First record of team stats join (`source_team_last_updated = 2026-01-25 11:30:05`)
   - Only 54.1% coverage (partial success)
   - Confirms processor fix is working BUT not running daily

3. **Jan 9-23 Gap:**
   - 15 consecutive days with 0% usage_rate
   - Team stats available in source table (100% coverage)
   - Processor either not running or not joining team stats

---

### 3. Root Cause Analysis

#### Issue #1: Processor Not Running Daily

**Evidence:**
- Team stats available for ALL days in Jan 2026 (6-24 records per day)
- `source_team_last_updated` timestamp only exists for Jan 1 and Jan 24
- 22 out of 24 days have 0% usage_rate despite team stats being available

**Conclusion:** The player_game_summary processor with team stats join is **NOT running daily**. Only manual/ad-hoc runs on Jan 1 and Jan 24.

#### Issue #2: Partial Calculation Failures (Jan 24)

**Jan 24 Data:**
- Total records: 183
- With team timestamp: 183 (100%)
- With usage_rate: 99 (54.1%)

**Why 45.9% still NULL?**

Possible reasons:
1. **Players with 0 minutes** - calculation requires `minutes_played > 0`
2. **Team stats incomplete** - some games missing FGA/FTA/TO
3. **Data type issues** - team stats NULL or invalid format
4. **Calculation logic bugs** - edge cases causing NaN

---

## Recommendations

### Immediate Actions (P0)

1. **Enable Daily Processor Runs**
   - Verify player_game_summary processor is in daily cron/scheduler
   - Check Cloud Scheduler / Airflow DAG status
   - Ensure it runs AFTER team_offense_game_summary processor

2. **Investigate Jan 24 Partial Failures**
   - Run diagnostic query to find records with team stats but no usage_rate
   - Check for data type mismatches or calculation edge cases
   - Fix any remaining bugs in usage_rate calculation

3. **Backfill Oct 2025 - Jan 23**
   - Re-run player_game_summary processor for affected dates
   - Use `--backfill-mode` to overwrite bad data
   - Verify coverage improves to >95%

### Short-term Fixes (P1)

4. **Add Data Quality Monitoring**
   ```sql
   -- Daily alert query
   SELECT
       game_date,
       ROUND(100.0 * COUNTIF(minutes_played IS NULL) / COUNT(*), 1) as minutes_null_pct,
       ROUND(100.0 * COUNTIF(usage_rate IS NULL) / COUNT(*), 1) as usage_null_pct
   FROM `nba_analytics.player_game_summary`
   WHERE game_date = CURRENT_DATE() - 1
   -- Alert if either >10%
   ```

5. **Validate Team Stats Dependency**
   - Add pre-execution check: team_offense_game_summary must exist for date range
   - Fail processor if dependency stale/missing
   - Log warning when LEFT JOIN returns NULLs

---

## Validation Queries

### Check Current Status

```sql
-- 1. Overall coverage for recent dates
SELECT
    game_date,
    COUNT(*) as total,
    COUNTIF(minutes_played IS NOT NULL) as has_minutes,
    COUNTIF(usage_rate IS NOT NULL) as has_usage,
    COUNTIF(source_team_last_updated IS NOT NULL) as has_team_join,
    ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
    ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_pct
FROM `nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

### Diagnose Failures

```sql
-- Find records with team stats but no usage_rate
SELECT
    game_date,
    player_full_name,
    team_abbr,
    minutes_played,
    fg_attempts,
    usage_rate,
    source_team_last_updated
FROM `nba_analytics.player_game_summary`
WHERE game_date = '2026-01-24'
  AND source_team_last_updated IS NOT NULL
  AND usage_rate IS NULL
  AND minutes_played > 0
ORDER BY minutes_played DESC
LIMIT 20;
```

---

## Related Documents

- [ML Feature Quality Investigation](2026-01-25-ML-FEATURE-QUALITY-INVESTIGATION.md) - Root cause analysis
- [Session Handoff](SESSION-HANDOFF-2026-01-25.md) - Previous session work

---

**Report prepared by:** Claude Sonnet 4.5
**Date:** 2026-01-25
**Status:** Validation complete, remediation needed
