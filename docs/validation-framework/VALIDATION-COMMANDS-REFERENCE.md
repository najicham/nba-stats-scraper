# Validation Commands - Quick Reference
**Purpose**: Fast access to all validation commands
**Updated**: 2026-01-05

---

## Table of Contents
1. [Pre-Flight Validation](#pre-flight-validation)
2. [Post-Flight Validation](#post-flight-validation)
3. [Phase-Specific Validation](#phase-specific-validation)
4. [Data Quality Checks](#data-quality-checks)
5. [Continuous Monitoring](#continuous-monitoring)
6. [Emergency Validation](#emergency-validation)

---

## Pre-Flight Validation

### Before Phase 3 Backfill
```bash
# Validate prerequisites (Phase 2 raw data complete)
python bin/backfill/preflight_comprehensive.py \
  --target-phase 3 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22

# Strict mode (fail on warnings)
python bin/backfill/preflight_comprehensive.py \
  --target-phase 3 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --strict

# JSON output for automation
python bin/backfill/preflight_comprehensive.py \
  --target-phase 3 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --json > preflight_phase3.json
```

### Before Phase 4 Backfill
```bash
# CRITICAL: Checks ALL 5 Phase 3 tables
python bin/backfill/preflight_comprehensive.py \
  --target-phase 4 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22

# Should show:
# ✅ player_game_summary: 95.0%+
# ✅ team_defense_game_summary: 95.0%+
# ✅ team_offense_game_summary: 95.0%+
# ✅ upcoming_player_game_context: 95.0%+
# ✅ upcoming_team_game_context: 95.0%+
```

### Before Phase 5 Backfill
```bash
# Validate Phase 4 complete
python bin/backfill/preflight_comprehensive.py \
  --target-phase 5 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22
```

---

## Post-Flight Validation

### After Phase 3 Backfill
```bash
# Comprehensive validation with report
python bin/backfill/postflight_comprehensive.py \
  --phase 3 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --report logs/phase3_validation_$(date +%Y%m%d).json

# Review report
jq '.results[] | {table: .table_name, status: .status, coverage: .coverage_pct}' \
  logs/phase3_validation_$(date +%Y%m%d).json

# Expected output:
# {
#   "table": "player_game_summary",
#   "status": "COMPLETE",
#   "coverage": 96.5
# }
# ... (4 more tables)
```

### After Phase 4 Backfill
```bash
# Validate Phase 4 completion
python bin/backfill/postflight_comprehensive.py \
  --phase 4 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --report logs/phase4_validation_$(date +%Y%m%d).json

# Check bootstrap periods excluded
jq '.bootstrap_dates_excluded' logs/phase4_validation_$(date +%Y%m%d).json
```

### After Phase 5 Backfill
```bash
# Validate predictions
python bin/backfill/postflight_comprehensive.py \
  --phase 5 \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --report logs/phase5_validation_$(date +%Y%m%d).json
```

---

## Phase-Specific Validation

### Phase 3: Verify for Phase 4 Readiness
```bash
# Using existing verify script
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22

# Verbose mode (show missing dates)
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --verbose

# Expected output:
# ✅ PHASE 3 IS READY for Phase 4 backfill
# All tables have >95% coverage for the requested date range.
```

### Phase 3: Check Specific Table Coverage

**player_game_summary:**
```sql
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22';
```

**team_defense_game_summary:**
```sql
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  COUNT(DISTINCT team_abbr) as unique_teams,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22';
```

**team_offense_game_summary:**
```sql
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  COUNTIF(team_pace IS NOT NULL) * 100.0 / COUNT(*) as pace_coverage_pct
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22';
```

**upcoming_player_game_context:**
```sql
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  COUNTIF(has_prop_line = TRUE) * 100.0 / COUNT(*) as prop_coverage_pct
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22';
```

**upcoming_team_game_context:**
```sql
SELECT
  COUNT(DISTINCT game_date) as dates_with_data,
  COUNTIF(spread IS NOT NULL) * 100.0 / COUNT(*) as betting_lines_pct
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22';
```

### Phase 4: ML Training Readiness
```bash
# Comprehensive ML readiness check
python bin/backfill/validate_ml_ready.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22

# Expected output:
# ✅ ML TRAINING READY
# - ml_feature_store_v2: 88.5% coverage
# - All 21 features present
# - No NaN/Inf values detected
```

### Phase 4: Feature Coverage
```bash
# Validate specific features
python scripts/validation/validate_backfill_features.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22

# Check feature NULL rates
python scripts/validation/validate_backfill_features.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --check-nulls
```

---

## Data Quality Checks

### Check for Duplicates (All Phases)

**Phase 3 - player_game_summary:**
```sql
SELECT
  game_id,
  game_date,
  player_lookup,
  COUNT(*) as dup_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22'
GROUP BY game_id, game_date, player_lookup
HAVING COUNT(*) > 1
ORDER BY dup_count DESC
LIMIT 10;

-- Expected: 0 rows
```

**Phase 4 - player_composite_factors:**
```sql
SELECT
  game_id,
  game_date,
  player_lookup,
  COUNT(*) as dup_count
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22'
GROUP BY game_id, game_date, player_lookup
HAVING COUNT(*) > 1
ORDER BY dup_count DESC
LIMIT 10;

-- Expected: 0 rows
```

### Check NULL Rates

**minutes_played (critical field):**
```sql
SELECT
  COUNTIF(minutes_played IS NULL) as null_count,
  COUNT(*) as total_count,
  ROUND(COUNTIF(minutes_played IS NULL) * 100.0 / COUNT(*), 1) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22'
  AND points IS NOT NULL;  -- Exclude DNPs

-- Expected: null_pct <10%
```

**usage_rate:**
```sql
SELECT
  COUNTIF(usage_rate IS NULL) as null_count,
  COUNT(*) as total_count,
  ROUND(COUNTIF(usage_rate IS NULL) * 100.0 / COUNT(*), 1) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22'
  AND minutes_played > 0;

-- Expected: null_pct <55% (accounting for pre-2024 data)
```

**Phase 4 features:**
```sql
SELECT
  COUNTIF(fatigue_factor IS NULL) * 100.0 / COUNT(*) as fatigue_null_pct,
  COUNTIF(shot_zone_mismatch IS NULL) * 100.0 / COUNT(*) as zone_null_pct,
  COUNTIF(pace_differential IS NULL) * 100.0 / COUNT(*) as pace_null_pct
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22';

-- Expected: All <5%
```

### Check Quality Score Distribution
```sql
SELECT
  quality_tier,
  COUNT(*) as record_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= '2025-06-22'
GROUP BY quality_tier
ORDER BY quality_tier;

-- Expected:
-- gold: 40-50%
-- silver: 30-40%
-- bronze: 10-20%
-- poor/unusable: <5%
```

### Check for Future Dates (Data Integrity)
```sql
SELECT game_date, COUNT(*) as record_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date > CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date;

-- Expected: 0 rows (no future dates)
```

---

## Continuous Monitoring

### Daily Validation (Run at 8 AM)
```bash
# Daily health check
python scripts/monitoring/daily_validation.py

# Alert on failures
python scripts/monitoring/daily_validation.py --alert-on-failure

# Cron schedule:
# 0 8 * * * cd /home/naji/code/nba-stats-scraper && python scripts/monitoring/daily_validation.py --alert-on-failure
```

### Weekly Coverage Report (Run Monday 9 AM)
```bash
# Generate weekly report
python scripts/monitoring/weekly_coverage_report.py \
  --email \
  --output reports/coverage_$(date +%Y-%m-%d).pdf

# Cron schedule:
# 0 9 * * 1 cd /home/naji/code/nba-stats-scraper && python scripts/monitoring/weekly_coverage_report.py --email
```

### Real-time Pipeline Health
```bash
# Check last 7 days
python scripts/validation/validate_pipeline_completeness.py \
  --start-date $(date -d '7 days ago' +%Y-%m-%d) \
  --end-date $(date +%Y-%m-%d)

# Alert on gaps
python scripts/validation/validate_pipeline_completeness.py \
  --start-date $(date -d '30 days ago' +%Y-%m-%d) \
  --end-date $(date +%Y-%m-%d) \
  --alert-on-gaps
```

### Coverage Trend Analysis
```sql
-- Weekly coverage trend (last 12 weeks)
WITH weekly_coverage AS (
  SELECT
    DATE_TRUNC(game_date, WEEK) as week,
    COUNT(DISTINCT game_date) as dates_with_data
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 WEEK)
  GROUP BY week
),
expected_weekly AS (
  SELECT
    DATE_TRUNC(game_date, WEEK) as week,
    COUNT(DISTINCT game_date) as expected_dates
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 WEEK)
  GROUP BY week
)
SELECT
  w.week,
  e.expected_dates,
  w.dates_with_data,
  ROUND(w.dates_with_data * 100.0 / e.expected_dates, 1) as coverage_pct
FROM weekly_coverage w
JOIN expected_weekly e ON w.week = e.week
ORDER BY w.week DESC;
```

---

## Emergency Validation

### Quick Health Check (All Phases)
```bash
# 30-day health check
python scripts/validation/validate_pipeline_completeness.py \
  --start-date $(date -d '30 days ago' +%Y-%m-%d) \
  --end-date $(date +%Y-%m-%d) \
  --alert-on-gaps

# Expected output:
# ✅ ALL VALIDATIONS PASSED
```

### Full Pipeline Audit
```bash
# Comprehensive audit (takes ~10 minutes)
python scripts/validation/full_pipeline_audit.py \
  --start-date 2021-10-19 \
  --end-date 2025-06-22 \
  --output audit_report_$(date +%Y%m%d).html

# Open in browser
open audit_report_$(date +%Y%m%d).html
```

### Identify Missing Date Ranges
```sql
-- Find gaps in Phase 3
WITH expected_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22'
),
actual_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-19'
    AND game_date <= '2025-06-22'
),
gaps AS (
  SELECT e.game_date as missing_date
  FROM expected_dates e
  LEFT JOIN actual_dates a ON e.game_date = a.game_date
  WHERE a.game_date IS NULL
)
SELECT
  MIN(missing_date) as gap_start,
  MAX(missing_date) as gap_end,
  COUNT(*) as days_missing
FROM (
  SELECT
    missing_date,
    DATE_DIFF(missing_date, LAG(missing_date) OVER (ORDER BY missing_date), DAY) as day_diff,
    SUM(CASE WHEN DATE_DIFF(missing_date, LAG(missing_date) OVER (ORDER BY missing_date), DAY) > 1 THEN 1 ELSE 0 END)
      OVER (ORDER BY missing_date) as gap_group
  FROM gaps
)
GROUP BY gap_group
ORDER BY gap_start;
```

### Phase 3 All-Tables Coverage Summary
```bash
# One-liner to check all 5 Phase 3 tables
for table in player_game_summary team_defense_game_summary team_offense_game_summary upcoming_player_game_context upcoming_team_game_context; do
  echo "Checking $table..."
  bq query --use_legacy_sql=false --format=csv "
    WITH expected AS (
      SELECT COUNT(DISTINCT game_date) as exp
      FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
      WHERE game_date >= '2021-10-19' AND game_date <= '2025-06-22'
    ),
    actual AS (
      SELECT COUNT(DISTINCT game_date) as act
      FROM \`nba-props-platform.nba_analytics.$table\`
      WHERE game_date >= '2021-10-19' AND game_date <= '2025-06-22'
    )
    SELECT exp, act, ROUND(act * 100.0 / exp, 1) as coverage_pct
    FROM expected, actual
  "
done

# Expected output for all 5 tables:
# exp,act,coverage_pct
# 1300,1285,98.8
```

---

## Troubleshooting Commands

### If Coverage Drops Below Threshold
```bash
# 1. Identify missing dates
bq query --use_legacy_sql=false --format=pretty "
  WITH expected AS (
    SELECT DISTINCT game_date
    FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
    WHERE game_date >= '2024-01-01'
  ),
  actual AS (
    SELECT DISTINCT game_date
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '2024-01-01'
  )
  SELECT e.game_date
  FROM expected e
  LEFT JOIN actual a ON e.game_date = a.game_date
  WHERE a.game_date IS NULL
  ORDER BY e.game_date DESC
  LIMIT 20
"

# 2. Run incremental backfill for missing dates
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2024-MM-DD \
  --end-date 2024-MM-DD

# 3. Re-run validation
python bin/backfill/postflight_comprehensive.py \
  --phase 3 \
  --start-date 2024-01-01 \
  --end-date 2024-12-31
```

### If Duplicates Detected
```bash
# 1. Count duplicates
bq query --use_legacy_sql=false "
  SELECT COUNT(*) as dup_count
  FROM (
    SELECT game_id, game_date, player_lookup, COUNT(*) as cnt
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    GROUP BY game_id, game_date, player_lookup
    HAVING COUNT(*) > 1
  )
"

# 2. Run deduplication script
python scripts/maintenance/deduplicate_table.py \
  --table nba_analytics.player_game_summary \
  --key-columns game_id,game_date,player_lookup

# 3. Verify duplicates removed
bq query --use_legacy_sql=false "
  SELECT COUNT(*) as dup_count
  FROM (
    SELECT game_id, game_date, player_lookup, COUNT(*) as cnt
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    GROUP BY game_id, game_date, player_lookup
    HAVING COUNT(*) > 1
  )
"
# Expected: dup_count = 0
```

---

## Automated Validation Integration

### In Backfill Scripts
```python
# Add to backfill script header
import subprocess
import sys

def run_preflight_validation(phase, start_date, end_date):
    """Run pre-flight validation before backfill."""
    result = subprocess.run([
        'python',
        'bin/backfill/preflight_comprehensive.py',
        '--target-phase', str(phase),
        '--start-date', start_date,
        '--end-date', end_date
    ], capture_output=True)

    if result.returncode != 0:
        print("❌ PRE-FLIGHT VALIDATION FAILED")
        print(result.stderr.decode())
        sys.exit(1)

    print("✅ PRE-FLIGHT VALIDATION PASSED")

# Use in backfill
if __name__ == "__main__":
    run_preflight_validation(4, '2021-10-19', '2025-06-22')
    # ... continue with backfill
```

### In Orchestrators
```bash
# Add to orchestrator script
run_validation_gate() {
    local phase=$1
    local start_date=$2
    local end_date=$3

    echo "Running validation gate for Phase $phase..."

    if ! python bin/backfill/postflight_comprehensive.py \
        --phase $phase \
        --start-date "$start_date" \
        --end-date "$end_date" \
        --report "logs/phase${phase}_validation.json"; then

        echo "❌ VALIDATION FAILED - aborting"
        exit 1
    fi

    echo "✅ VALIDATION PASSED - proceeding"
}

# Use after each phase
run_validation_gate 3 "$START_DATE" "$END_DATE"
```

---

## Summary: Essential Commands

**Before ANY backfill:**
```bash
python bin/backfill/preflight_comprehensive.py --target-phase N --start-date X --end-date Y
```

**After EVERY backfill:**
```bash
python bin/backfill/postflight_comprehensive.py --phase N --start-date X --end-date Y --report validation.json
```

**Daily monitoring:**
```bash
python scripts/monitoring/daily_validation.py --alert-on-failure
```

**When in doubt:**
```bash
python bin/backfill/verify_phase3_for_phase4.py --start-date X --end-date Y --verbose
```

---

**Save this file for quick reference during backfill operations!**
