# Validation Framework - Practical Usage Guide
**Version**: 1.0
**Created**: January 4, 2026
**Audience**: Developers and operators
**Purpose**: Quick-start guide with real examples

---

## QUICK START - 5 MINUTES

### Scenario 1: "I just finished a backfill, is the data good?"

```bash
cd /home/naji/code/nba-stats-scraper

# Run Phase 3 validation
./scripts/validation/validate_player_summary.sh \
  --start-date 2024-05-01 \
  --end-date 2026-01-02

# Check result
if [ $? -eq 0 ]; then
  echo "✅ PASS - Data is good!"
else
  echo "❌ FAIL - Check output for issues"
fi
```

**What it checks**: Record counts, feature coverage, quality scores

**Time**: ~30 seconds

---

### Scenario 2: "Is my data ready for ML training?"

```bash
# Quick feature coverage check
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_coverage,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_coverage,
  ROUND(100.0 * COUNTIF(paint_attempts IS NOT NULL) / COUNT(*), 1) as paint_coverage
FROM nba_analytics.player_game_summary
WHERE game_date >= '2021-10-01'
"

# Interpret:
# ✅ GOOD: All >90%
# ⚠️ CHECK: Any 70-90%
# ❌ BAD: Any <70%
```

**Time**: ~10 seconds

---

### Scenario 3: "Did my backfill make things better or worse?"

```python
from shared.validation.validators.regression_detector import RegressionDetector
from datetime import date

detector = RegressionDetector()

result = detector.detect_regression(
    baseline_start=date(2023, 10, 1),  # Known good period
    baseline_end=date(2024, 5, 1),
    current_start=date(2024, 5, 2),    # Just backfilled
    current_end=date(2024, 12, 31),
    features=['minutes_played', 'usage_rate']
)

# Check each feature
for feature, status in result.items():
    print(f"{feature}: {status.status} ({status.change:+.1f}% change)")
```

**Interpretation**:
- `IMPROVEMENT`: ✅ Backfill helped!
- `OK`: ✅ No change (expected)
- `DEGRADATION`: ⚠️ Small regression (investigate)
- `REGRESSION`: ❌ Significant problem (fix immediately)

**Time**: ~1 minute

---

## DETAILED SCENARIOS

### Scenario 4: Phase 3 Backfill Validation

**Context**: You just ran a backfill for `player_game_summary` from 2021-10-01 to 2024-05-01

**Step-by-step**:

```bash
# 1. Check if backfill completed
ps aux | grep player_game_summary | grep backfill
# If nothing: backfill is done
# If process: still running

# 2. Count records in BigQuery
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_records,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
"

# Expected: ~72,000 records

# 3. Run full validation
./scripts/validation/validate_player_summary.sh \
  --start-date 2021-10-01 \
  --end-date 2024-05-01

# 4. Check specific features
bq query --use_legacy_sql=false "
SELECT
  'minutes_played' as feature,
  COUNTIF(minutes_played IS NOT NULL) as populated,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as coverage_pct
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'

UNION ALL

SELECT
  'usage_rate',
  COUNTIF(usage_rate IS NOT NULL),
  COUNT(*),
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1)
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
"
```

**Success criteria**:
- ✅ Total records ≥35,000
- ✅ minutes_played ≥99% coverage
- ✅ usage_rate ≥90% coverage (excluding legitimate DNPs)
- ✅ Validation script exits with code 0

---

### Scenario 5: Phase 4 Backfill Validation

**Context**: You ran `player_composite_factors` backfill for date range

**Key insight**: Phase 4 skips early season dates (bootstrap period), so 100% coverage is impossible

```bash
# 1. Check coverage accounting for bootstrap
bq query --use_legacy_sql=false "
WITH date_range AS (
  SELECT game_date
  FROM UNNEST(GENERATE_DATE_ARRAY('2024-10-22', '2025-06-22')) as game_date
),
season_day AS (
  SELECT
    game_date,
    ROW_NUMBER() OVER (PARTITION BY EXTRACT(YEAR FROM game_date) ORDER BY game_date) as day_of_season
  FROM date_range
)
SELECT
  COUNT(*) as total_dates,
  COUNTIF(day_of_season > 14) as processable_dates,
  COUNTIF(pcf.game_date IS NOT NULL) as dates_with_data,
  ROUND(100.0 * COUNTIF(pcf.game_date IS NOT NULL) / COUNTIF(day_of_season > 14), 1) as actual_coverage_pct
FROM season_day sd
LEFT JOIN (SELECT DISTINCT game_date FROM nba_precompute.player_composite_factors) pcf
  ON sd.game_date = pcf.game_date
"

# Expected: ~88% (not 100%!)
```

**Why not 100%?**
- First 14 days of season need rolling windows (L10, L15)
- These dates are SKIPPED BY DESIGN
- Maximum possible coverage: ~88%

---

### Scenario 6: Check If Code Deployment Matches Data

**Context**: You deployed a bug fix, want to verify data was reprocessed with new code

```bash
# 1. Check when processor was deployed
DEPLOY_TIME=$(gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(status.latestReadyRevisionName)" | grep -oP '\d{8}T\d{6}')

echo "Processor deployed at: $DEPLOY_TIME"

# 2. Check when data was processed
bq query --use_legacy_sql=false "
SELECT
  MIN(processed_at) as earliest_process,
  MAX(processed_at) as latest_process,
  COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE DATE(processed_at) = CURRENT_DATE()
"

# 3. Compare timestamps
# If processed_at > deployment_time: ✅ Data has bug fix
# If processed_at < deployment_time: ❌ Data processed with old code
```

---

### Scenario 7: Daily Health Check

**Context**: You want to verify yesterday's data looks good (cron job)

```bash
#!/bin/bash
# File: scripts/monitoring/daily_health_check.sh

YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

echo "🔍 Daily Health Check for $YESTERDAY"

# 1. Check if data exists
RECORD_COUNT=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) FROM nba_analytics.player_game_summary
WHERE game_date = '$YESTERDAY'
" | tail -1)

if [ "$RECORD_COUNT" -lt 100 ]; then
  echo "❌ Only $RECORD_COUNT records found (expected >100)"
  exit 1
fi

# 2. Check feature coverage
bq query --use_legacy_sql=false "
SELECT
  'minutes_played' as feature,
  ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as coverage
FROM nba_analytics.player_game_summary
WHERE game_date = '$YESTERDAY'
UNION ALL
SELECT 'usage_rate', ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1)
FROM nba_analytics.player_game_summary
WHERE game_date = '$YESTERDAY'
"

# 3. Alert if issues
# (Add alerting logic here)
```

**Schedule**: Run daily at 6 AM (after overnight processing)

---

## PYTHON API EXAMPLES

### Example 1: Feature Validator

```python
from shared.validation.validators.feature_validator import FeatureValidator
from datetime import date

# Initialize validator
validator = FeatureValidator()

# Validate specific date range
result = validator.validate_features(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    critical_threshold=99.0,   # minutes_played, etc.
    important_threshold=95.0    # usage_rate, etc.
)

# Check results
print(f"Total records: {result.total_records:,}")
print(f"ML ready: {result.ml_ready_pct:.1f}%")

# Detailed feature breakdown
for feature in result.features:
    status = "✅" if feature.passes else "❌"
    print(f"{status} {feature.name}: {feature.coverage:.1f}% ({feature.status})")

# Overall assessment
if result.is_ml_ready:
    print("\n✅ READY FOR ML TRAINING")
else:
    print(f"\n❌ NOT READY: {len(result.blocking_issues)} blocking issues")
    for issue in result.blocking_issues:
        print(f"  - {issue}")
```

---

### Example 2: Regression Detector

```python
from shared.validation.validators.regression_detector import RegressionDetector
from datetime import date

detector = RegressionDetector()

# Compare two periods
result = detector.compare_periods(
    period1_start=date(2023, 10, 1),
    period1_end=date(2024, 5, 1),
    period1_label="Before Backfill",
    period2_start=date(2024, 5, 2),
    period2_end=date(2024, 12, 31),
    period2_label="After Backfill",
    features=['minutes_played', 'usage_rate', 'paint_attempts']
)

# Analyze changes
for feature_name, change in result.items():
    if change.status == "REGRESSION":
        print(f"🚨 {feature_name}: REGRESSION detected!")
        print(f"   Before: {change.before_coverage:.1f}%")
        print(f"   After: {change.after_coverage:.1f}%")
        print(f"   Change: {change.delta:+.1f}%")
```

---

### Example 3: Backfill Report Generator

```python
from shared.validation.output.backfill_report import BackfillReportGenerator
from datetime import date

# Generate comprehensive report
generator = BackfillReportGenerator()

report = generator.generate_report(
    backfill_name="player_game_summary_2024_backfill",
    date_range_start=date(2024, 1, 1),
    date_range_end=date(2024, 12, 31),
    features_to_validate=['minutes_played', 'usage_rate', 'paint_attempts'],
    compare_to_baseline=True,
    baseline_period_start=date(2023, 1, 1),
    baseline_period_end=date(2023, 12, 31)
)

# Save report
with open('backfill_report.md', 'w') as f:
    f.write(report.to_markdown())

print(report.summary())
```

---

## COMMON VALIDATION QUERIES

### Query 1: Feature Coverage by Season

```sql
SELECT
  season_year,
  COUNT(*) as records,

  -- Core features
  ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_pct,
  ROUND(100.0 * COUNTIF(points IS NOT NULL) / COUNT(*), 1) as points_pct,

  -- Shot distribution
  ROUND(100.0 * COUNTIF(paint_attempts IS NOT NULL) / COUNT(*), 1) as paint_pct,
  ROUND(100.0 * COUNTIF(three_pt_attempts IS NOT NULL) / COUNT(*), 1) as three_pt_pct

FROM nba_analytics.player_game_summary
WHERE game_date >= '2021-10-01'
GROUP BY season_year
ORDER BY season_year
```

---

### Query 2: Daily Coverage Trend

```sql
SELECT
  game_date,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_coverage,
  ROUND(AVG(CASE WHEN usage_rate IS NOT NULL THEN usage_rate END), 1) as avg_usage_rate
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 30
```

---

### Query 3: Find Data Gaps

```sql
WITH expected_dates AS (
  SELECT date_value as game_date
  FROM UNNEST(GENERATE_DATE_ARRAY('2024-10-22', '2025-06-22')) as date_value
),
actual_dates AS (
  SELECT DISTINCT game_date
  FROM nba_analytics.player_game_summary
)
SELECT
  ed.game_date as missing_date,
  EXTRACT(DAYOFWEEK FROM ed.game_date) as day_of_week
FROM expected_dates ed
LEFT JOIN actual_dates ad ON ed.game_date = ad.game_date
WHERE ad.game_date IS NULL
ORDER BY ed.game_date
```

---

## TROUBLESHOOTING

### Issue: Validation script fails with "Table not found"

**Symptom**: `ERROR: Table nba_analytics.player_game_summary not found`

**Solutions**:
```bash
# 1. Check you're in right GCP project
gcloud config get-value project
# Should be: nba-props-platform

# 2. Verify table exists
bq ls nba-props-platform:nba_analytics

# 3. Check permissions
bq show nba-props-platform:nba_analytics.player_game_summary
```

---

### Issue: Coverage looks lower than expected

**Symptom**: usage_rate shows 40% but you expected 90%+

**Investigation**:
```sql
-- Check if DNP players are included in denominator
SELECT
  COUNT(*) as total,
  COUNTIF(minutes_played IS NULL) as dnp_count,
  COUNTIF(minutes_played IS NOT NULL AND usage_rate IS NULL) as played_but_no_usage,
  COUNTIF(usage_rate IS NOT NULL) as has_usage
FROM nba_analytics.player_game_summary
WHERE game_date >= '2024-01-01'
```

**Interpretation**:
- If `played_but_no_usage` is high: ❌ Real problem
- If `dnp_count` is high: ✅ Expected (DNPs should be NULL)

**Fix**: Adjust query to exclude DNPs:
```sql
-- Correct coverage calculation (exclude DNPs)
SELECT
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNTIF(minutes_played IS NOT NULL), 1) as usage_coverage
FROM nba_analytics.player_game_summary
WHERE game_date >= '2024-01-01'
```

---

### Issue: "Regression detected" but backfill should have helped

**Symptom**: Regression detector shows REGRESSION but you fixed bugs

**Investigation**:
```bash
# Check when data was actually processed
bq query --use_legacy_sql=false "
SELECT
  DATE(processed_at) as process_date,
  COUNT(*) as records,
  COUNTIF(usage_rate IS NOT NULL) as usage_populated
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2024-01-01' AND '2024-12-31'
GROUP BY process_date
ORDER BY process_date DESC
"
```

**Common cause**: Comparing old data (before fix) to old data (also before fix)

**Solution**: Use processed_at to filter to only recently processed data:
```python
result = detector.detect_regression(
    baseline_start=date(2023, 10, 1),
    baseline_end=date(2024, 5, 1),
    current_start=date(2024, 5, 2),
    current_end=date(2024, 12, 31),
    processed_after=datetime(2026, 1, 3, 23, 0, 0)  # After bug fix deployment
)
```

---

## CHEAT SHEET

### Quick Commands

```bash
# Validate Phase 3
./scripts/validation/validate_player_summary.sh --start-date 2024-01-01 --end-date 2024-12-31

# Validate Phase 4
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_precompute.player_composite_factors WHERE game_date >= '2024-01-01'"

# Check recent processing
bq query --use_legacy_sql=false "SELECT MAX(processed_at) FROM nba_analytics.player_game_summary"

# Feature coverage quick check
bq query --use_legacy_sql=false "SELECT COUNTIF(usage_rate IS NOT NULL)/COUNT(*)*100 as usage_pct FROM nba_analytics.player_game_summary WHERE game_date >= '2024-01-01'"
```

### Critical Thresholds

| Feature | Target | Critical? |
|---------|--------|-----------|
| minutes_played | ≥99% | YES |
| usage_rate | ≥90% | YES |
| points | ≥99% | YES |
| paint_attempts | ≥40% (2024+), ≥80% (historical) | Important |
| Total records (ML training) | ≥50,000 | YES |

---

**Document Version**: 1.0
**Last Updated**: January 4, 2026
**Next Review**: After next backfill operation
