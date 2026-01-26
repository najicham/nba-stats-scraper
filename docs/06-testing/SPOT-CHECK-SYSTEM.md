# Spot Check System - Data Accuracy Verification

## Overview

The Spot Check System is an automated data validation framework that randomly samples player-date combinations and verifies that calculated fields match expected values from raw data. This system helps detect calculation errors, missing data joins, transformation bugs, and cross-table consistency issues before they impact predictions.

## Purpose

Data accuracy is critical for reliable predictions. The spot check system provides:

1. **Early Detection**: Catches calculation errors before they propagate to predictions
2. **Continuous Validation**: Regular sampling ensures data quality remains high
3. **Regression Prevention**: Prevents bugs like the Nov 3, 2025 minutes parsing issue
4. **Cross-Table Verification**: Ensures consistency across analytics, precompute, and raw tables

## Architecture

### Components

```
scripts/spot_check_data_accuracy.py     # Main spot check script
scripts/validate_tonight_data.py        # Integration point (runs 5 spot checks daily)
```

### Data Flow

```
Random Sampling
    ↓
player_game_summary → Check A: Rolling Averages
    ↓
player_game_summary + team_offense → Check B: Usage Rate
    ↓
nbac_gamebook_player_stats → Check C: Minutes Parsing
    ↓
ml_feature_store_v2 + player_game_summary → Check D: ML Feature Consistency
    ↓
player_daily_cache + player_game_summary → Check E: Cache L0 Features
    ↓
player_game_summary → Check F: Points Total Arithmetic
    ↓
Validation Report
```

## Checks Implemented

### Check A: Rolling Averages

**Purpose**: Verify `points_avg_last_5` and `points_avg_last_10` match recalculated values from game history

**Formula**:
```sql
-- Expected points_avg_last_5
SELECT AVG(points)
FROM (
  SELECT points
  FROM player_game_summary
  WHERE player_lookup = ? AND game_date < ?
  ORDER BY game_date DESC
  LIMIT 5
)
```

**Data Sources**:
- `nba_analytics.player_game_summary` (stored values + history)

**Tolerance**: 2% (floating point precision)

**Typical Failures**:
- Missing games in history (incomplete data)
- Off-by-one errors in date filtering
- Incorrect ORDER BY causing wrong games selected

### Check B: Usage Rate Calculation

**Purpose**: Verify `usage_rate` matches the standard NBA formula

**Formula**:
```
usage_rate = 100 × (FGA + 0.44 × FTA + TO) × 48 / (MP × Team_Usage)
where Team_Usage = Team_FGA + 0.44 × Team_FTA + Team_TO
```

**Data Sources**:
- `nba_analytics.player_game_summary` (player stats)
- `nba_analytics.team_offense_game_summary` (team stats)

**Tolerance**: 2%

**Typical Failures**:
- Team stats missing (expected: usage_rate should be NULL)
- Join failure on game_id/team_abbr
- Division by zero when minutes = 0

### Check C: Minutes Parsing

**Purpose**: Verify `minutes_played` correctly parsed from MM:SS format

**Background**: On Nov 3, 2025, `_clean_numeric_columns()` destroyed MM:SS data by coercing "35:47" → NULL. This check prevents regression.

**Data Sources**:
- `nba_analytics.player_game_summary` (processed minutes)
- `nba_raw.nbac_gamebook_player_stats` (raw MM:SS format)

**Tolerance**: 0.1 minutes (6 seconds, rounding error)

**Typical Failures**:
- MM:SS parsing logic regression
- Wrong data source used (BDL vs Gamebook)
- Name matching issues in raw data lookup

### Check D: ML Feature Store Consistency

**Purpose**: Verify `ml_feature_store_v2` values match source tables

**Data Sources**:
- `nba_predictions.ml_feature_store_v2` (feature arrays)
- `nba_analytics.player_game_summary` (source values)

**Features Checked**:
- `points_avg_last_5` (must match player_game_summary)
- `points_avg_last_10` (must match player_game_summary)

**Tolerance**: 2%

**Typical Failures**:
- Stale feature store (not recomputed after source update)
- Feature extraction bug (wrong index in array)
- Data cascade issue (feature computed from old cache)

### Check E: Player Daily Cache L0 Features

**Purpose**: Verify cached features match computed values from source tables

**Cache Semantics**:
- `cache_date` = date features were computed "as of"
- For game on 2025-12-15, check cache_date = 2025-12-14
- Cache contains pre-game features (no data from game_date itself)

**Data Sources**:
- `nba_precompute.player_daily_cache` (cached values)
- `nba_analytics.player_game_summary` (source for recalculation)

**Features Checked**:
- `points_avg_last_5`
- `points_avg_last_10`
- `minutes_avg_last_10`

**Tolerance**: 2%

**Typical Failures**:
- Cache not refreshed (stale data)
- Wrong date filter (included game_date in history)
- Cache invalidation bug (old values persisted)

### Check F: Points Total Arithmetic

**Purpose**: Verify `points` field matches arithmetic formula to detect data corruption

**Formula**:
```
points = 2 × (FG made - 3P made) + 3 × (3P made) + FT made
points = 2 × (2P made) + 3 × (3P made) + FT made
```

**Data Sources**:
- `nba_analytics.player_game_summary` (all stats)

**Tolerance**: 0 (exact match required)

**Example**:
- Spencer Dinwiddie: 20 points = 2×3 (2P) + 3×3 (3P) + 5 (FT) ✓
- Dyson Daniels: 18 points = 2×6 (2P) + 3×1 (3P) + 3 (FT) ✓

**Typical Failures**:
- Data corruption in points field
- Incorrect manual entry in raw data source
- Database integrity violation
- Data migration error

**Note**: This check catches a different class of bugs than other checks. While Checks A-E verify calculation logic, Check F detects raw data corruption.

## Usage

### Standalone Script

#### Random Spot Checks (Recommended)
```bash
# Run 20 random spot checks from last 30 days
python scripts/spot_check_data_accuracy.py --samples 20

# Check specific date range
python scripts/spot_check_data_accuracy.py \
  --start-date 2025-11-01 \
  --end-date 2025-11-30 \
  --samples 50
```

#### Specific Player/Date (Debugging)
```bash
# Check specific player by lookup
python scripts/spot_check_data_accuracy.py \
  --player-lookup lebron_james \
  --date 2025-12-15

# Check specific player by ID
python scripts/spot_check_data_accuracy.py \
  --player-id 203566 \
  --date 2025-12-15
```

#### Selective Check Execution
```bash
# Only run specific checks (faster)
python scripts/spot_check_data_accuracy.py \
  --samples 10 \
  --checks rolling_avg,usage_rate

# Available checks:
# - rolling_avg: Check A (Rolling Averages)
# - usage_rate: Check B (Usage Rate)
# - minutes: Check C (Minutes Parsing)
# - ml_features: Check D (ML Feature Store)
# - cache: Check E (Player Daily Cache)
# - points_total: Check F (Points Arithmetic)
```

#### Verbose Output (Detailed Diagnostics)
```bash
# Show all check details, including SQL queries
python scripts/spot_check_data_accuracy.py \
  --samples 5 \
  --verbose
```

### Integrated Validation

Spot checks run automatically as part of daily validation:

```bash
# Runs 5 spot checks (rolling_avg + usage_rate only)
python scripts/validate_tonight_data.py --date 2025-12-15
```

**Integration Behavior**:
- Samples 5 random player-dates from last 7 days
- Runs only core checks (rolling_avg, usage_rate) for speed
- Threshold: 95% accuracy required
- Failures trigger warnings (not errors) to avoid blocking deployment

## Output Format

### Summary Report

```
======================================================================
SPOT CHECK REPORT: Data Accuracy Verification
======================================================================
Date: 2026-01-26 14:35:22
Samples: 20 player-date combinations

======================================================================
SUMMARY
======================================================================
Total checks: 80
  ✅ Passed:  76 (95.0%)
  ❌ Failed:  3 (3.8%)
  ⏭️  Skipped: 1 (1.2%)
  ⚠️  Errors:  0 (0.0%)

Samples: 18/20 passed (90.0%)
```

### Failure Details

```
======================================================================
FAILURES (2)
======================================================================

1. Player: lebron_james (203566)
   Date: 2025-12-15
   Status: ❌ FAILED - 1 check(s) failed

   ❌ Rolling Averages:
      - points_avg_last_5 mismatch: 4.2%
      ✗ Expected 28.40, Got 27.20 (diff: 4.2%)

2. Player: jayson_tatum (1628369)
   Date: 2026-01-10
   Status: ❌ FAILED - 1 check(s) failed

   ❌ Usage Rate Calculation:
      - usage_rate is NULL but should be calculated
      ✗ Expected usage_rate: 31.20, Got: NULL
```

### Exit Codes

- **0**: All checks passed (100% accuracy)
- **1**: Failures detected (accuracy < 100%)

## Configuration

### Tolerance Settings

Located in `scripts/spot_check_data_accuracy.py`:

```python
TOLERANCE = 0.02  # 2% tolerance for floating point comparisons
```

**Rationale**:
- Accounts for floating point precision differences
- Allows for minor rounding variations (e.g., 28.4 vs 28.40001)
- Too strict (0.01%) causes false positives from legitimate rounding

### Sampling Strategy

```python
# Random sampling with constraints
WHERE game_date BETWEEN start_date AND end_date
  AND minutes_played > 0  # Only players who actually played
  AND points IS NOT NULL  # Skip records with missing data
ORDER BY RAND()
LIMIT sample_count
```

**Design Decisions**:
- Filter to active players (minutes > 0) to ensure meaningful checks
- Exclude NULL data to avoid false negatives from expected missing values
- Randomization ensures broad coverage over time

## Thresholds and Alerts

### Daily Validation Thresholds

| Metric | Threshold | Action |
|--------|-----------|--------|
| Spot check accuracy | ≥ 95% | Pass (silent) |
| Spot check accuracy | < 95% | Warning (logged, not blocking) |
| Spot check samples | ≥ 1 | Continue |
| Spot check samples | 0 | Warning (insufficient data) |

### Standalone Script Thresholds

- **Pass**: accuracy = 100%
- **Fail**: accuracy < 100%

Stricter than daily validation because:
- Standalone runs are intentional (debugging/verification)
- Not time-critical (won't block deployment)
- User expects full accuracy

## Troubleshooting

### Common Issues

#### Issue: "No samples found in date range"

**Cause**: No player_game_summary data in specified date range

**Solution**:
```bash
# Check data availability
bq query --use_legacy_sql=false "
SELECT MIN(game_date) as earliest, MAX(game_date) as latest, COUNT(*) as rows
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE minutes_played > 0
"

# Adjust date range
python scripts/spot_check_data_accuracy.py \
  --start-date 2024-10-01 \
  --end-date 2024-12-31 \
  --samples 20
```

#### Issue: High skip rate (> 50%)

**Cause**: Missing upstream data (team stats, raw data, etc.)

**Solution**:
1. Check which checks are skipping:
   ```bash
   python scripts/spot_check_data_accuracy.py --samples 10 --verbose
   ```

2. Verify upstream table freshness:
   ```bash
   # Check team_offense_game_summary for usage_rate
   bq query --use_legacy_sql=false "
   SELECT MAX(game_date) FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
   "

   # Check nbac_gamebook_player_stats for minutes parsing
   bq query --use_legacy_sql=false "
   SELECT MAX(game_date) FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
   "
   ```

3. Run upstream scrapers/processors if data is stale

#### Issue: Usage rate always NULL

**Cause**: team_offense_game_summary missing or join failure

**Solution**:
```bash
# Check if team stats exist for sample game
bq query --use_legacy_sql=false "
SELECT game_id, team_abbr, fg_attempts, ft_attempts, turnovers
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date = '2025-12-15'
ORDER BY team_abbr
"

# If empty, check team_offense processor logs
# If present, check game_id/team_abbr join logic
```

#### Issue: Minutes parsing failures

**Cause**: Player name mismatch between analytics and raw tables

**Solution**:
```bash
# Check name format in both tables
bq query --use_legacy_sql=false "
SELECT DISTINCT player_lookup
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE player_lookup LIKE '%lebron%'
"

bq query --use_legacy_sql=false "
SELECT DISTINCT player_name
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE LOWER(player_name) LIKE '%lebron%'
"

# Note: player_lookup uses underscores (lebron_james)
# Raw data uses spaces (LeBron James)
# Spot check converts with .replace('_', ' ')
```

#### Issue: Check E (cache) failures after backfill

**Cause**: Cache was backfilled with different data than current source

**Solution**:
1. Identify scope of issue:
   ```bash
   python scripts/spot_check_data_accuracy.py \
     --start-date 2025-11-01 \
     --end-date 2025-11-30 \
     --samples 50 \
     --checks cache
   ```

2. If backfill is known good, adjust tolerance temporarily
3. If source is correct, invalidate and regenerate cache:
   ```sql
   DELETE FROM `nba-props-platform.nba_precompute.player_daily_cache`
   WHERE cache_date BETWEEN '2025-11-01' AND '2025-11-30'
   ```

4. Rerun player_daily_cache processor

## Performance

### Execution Time

| Sample Size | Checks | Typical Duration |
|-------------|--------|------------------|
| 5 samples | rolling_avg, usage_rate | 15-30 seconds |
| 20 samples | all checks | 2-4 minutes |
| 50 samples | all checks | 5-10 minutes |

**Bottlenecks**:
- BigQuery query latency (60s timeout per query)
- Network round-trips (6-12 queries per sample with all checks)
- Sequential processing (could parallelize in future)

### Cost

- **Free**: All queries use cached results where possible
- **Minimal scan**: Partitioned queries on game_date (efficient)
- **Estimated cost per run**: < $0.01 (negligible)

## Best Practices

### When to Run

1. **After schema changes**: Verify calculations still work
2. **After processor updates**: Ensure no regression
3. **Before major releases**: Confidence in data quality
4. **Investigating anomalies**: Debug specific player/date issues

### Sample Size Recommendations

| Use Case | Sample Size | Checks |
|----------|-------------|--------|
| Quick sanity check | 5-10 | rolling_avg, usage_rate |
| Daily validation | 5 | rolling_avg, usage_rate |
| Pre-deployment verification | 20 | all |
| Post-backfill validation | 50-100 | all |
| Investigating specific issue | 1 (specific player/date) | all |

### Integration Guidelines

- **DO** run spot checks in daily validation (already implemented)
- **DO** set reasonable thresholds (95% for warnings, not errors)
- **DO** sample recent data (last 7 days) for relevance
- **DO** use warnings for failures (don't block deployment)

- **DON'T** run all checks in daily validation (too slow)
- **DON'T** fail builds on spot check failures (may have legitimate data gaps)
- **DON'T** sample too far back (old data may have known issues)
- **DON'T** expect 100% pass rate (some data gaps are expected)

## Future Enhancements

### Planned Features

1. **Parallel Execution**: Process multiple samples concurrently (3-5x speedup)
2. **Historical Trending**: Track accuracy over time, alert on degradation
3. **Check Priority Levels**: Critical vs nice-to-have checks
4. **Smart Sampling**: Target high-stakes players (popular props, high usage)
5. **Regression Detection**: Flag consistent failures in specific checks
6. **Integration with Monitoring**: Push metrics to Datadog/Prometheus

### Potential New Checks

- **Check F**: Opponent defense rating consistency (team_defense_game_summary)
- **Check G**: Shot zone totals sum to FG totals
- **Check H**: Plus/minus matches team point differential
- **Check I**: Prop predictions within reasonable bounds (0-60 points)
- **Check J**: Feature version consistency across ml_feature_store_v2

## Related Documentation

- [Testing Strategy](./TESTING-STRATEGY.md) - Overall testing approach
- [Data Quality Guide](../04-data-quality/DATA-QUALITY-FRAMEWORK.md) - Quality metrics
- [Validation Pipeline](../05-pipelines/VALIDATION-PIPELINE.md) - Validation workflow

## Maintenance

### Owner
Data Engineering Team

### Last Updated
2026-01-26

### Review Cadence
Quarterly (or after major schema changes)

### Contact
For questions or issues with the spot check system, contact the data engineering team or file an issue in the project repository.
