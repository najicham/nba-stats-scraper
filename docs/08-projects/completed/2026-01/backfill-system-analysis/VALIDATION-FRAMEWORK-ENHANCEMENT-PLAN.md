# Validation Framework Enhancement Plan

**Created**: January 3, 2026
**Purpose**: Prevent "claimed complete but wasn't" disasters
**Status**: 🎯 DESIGN COMPLETE - Ready for implementation

---

## 🎯 OBJECTIVE

Enhance `bin/validate_pipeline.py` to provide backfill-specific validation that catches data quality issues like:
- ❌ 0% usage_rate (dependency never filled)
- ❌ 0-70% minutes_played coverage (broken data)
- ❌ Regression (new backfilled data worse than old data)

---

## 📊 CURRENT STATE ANALYSIS

### What Exists Today ✅

**`bin/validate_pipeline.py` already has**:
1. **Mode detection** (`get_validation_mode(game_date)`)
   - Returns `'daily'` for recent dates
   - Returns `'backfill'` for historical dates
   - Switches player universe (roster vs gamebook)

2. **Phase-specific validators**:
   - `validate_phase1()` - GCS files
   - `validate_phase2()` - Raw BigQuery tables
   - `validate_phase3()` - Analytics tables
   - `validate_phase4()` - Precompute tables
   - `validate_phase5()` - Predictions

3. **Flexible arguments**:
   - `--phase N` - Validate specific phase
   - `--format json|terminal` - Output format
   - `--verbose` - Detailed output
   - `--show-missing` - Show missing players
   - Date range support

4. **Cross-phase validation**:
   - Player consistency between phases
   - Chain validation (fallback sources)
   - Run history analysis

### What's Missing ❌

1. **Feature-specific validation**:
   - No way to check `minutes_played` coverage
   - No way to check `usage_rate` coverage
   - No way to check `shot_zones` coverage

2. **Regression detection**:
   - No comparison of new data vs historical baseline
   - No trending analysis
   - No "worse than before" alerts

3. **Backfill-specific thresholds**:
   - Uses same thresholds for daily and backfill
   - Should have relaxed thresholds for backfill (70% vs 95%)

4. **Validation report enhancements**:
   - No clear PASS/FAIL for backfills
   - No "ready for next step" guidance
   - No regression alerts in output

---

## 🏗️ PROPOSED ENHANCEMENTS

### Enhancement 1: Feature Coverage Validation

**New flag**: `--validate-features <feature1,feature2,...>`

**Purpose**: Check NULL rates for specific features

**Example**:
```bash
python3 bin/validate_pipeline.py 2024-05-01 2026-01-02 \
  --phase 3 \
  --validate-features minutes_played,usage_rate,shot_zones
```

**Implementation**:
```python
def validate_feature_coverage(
    client: bigquery.Client,
    game_date_start: date,
    game_date_end: date,
    features: List[str],
    thresholds: dict,
) -> dict:
    """
    Validate feature coverage (NULL rate) for specified features.

    Args:
        client: BigQuery client
        game_date_start: Start date
        game_date_end: End date
        features: List of feature names to check
        thresholds: Dict of feature -> minimum coverage percentage

    Returns:
        Dict with coverage results per feature
    """
    results = {}

    for feature in features:
        query = f"""
        SELECT
          COUNTIF({feature} IS NOT NULL) * 100.0 / COUNT(*) as coverage_pct,
          COUNT(*) as total_records,
          COUNTIF({feature} IS NOT NULL) as records_with_feature,
          COUNTIF({feature} IS NULL) as records_null
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date >= @start_date
          AND game_date <= @end_date
          AND points IS NOT NULL
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", game_date_start),
                bigquery.ScalarQueryParameter("end_date", "DATE", game_date_end),
            ]
        )

        result = client.query(query, job_config=job_config).result()
        row = next(result)

        coverage_pct = float(row.coverage_pct) if row.coverage_pct else 0.0
        threshold = thresholds.get(feature, 95.0)

        results[feature] = {
            'coverage_pct': coverage_pct,
            'total_records': row.total_records,
            'records_with_feature': row.records_with_feature,
            'records_null': row.records_null,
            'threshold': threshold,
            'passed': coverage_pct >= threshold,
            'status': 'PASS' if coverage_pct >= threshold else 'FAIL',
        }

    return results
```

**Feature Thresholds**:
```python
FEATURE_THRESHOLDS = {
    'minutes_played': 99.0,      # CRITICAL
    'usage_rate': 95.0,          # CRITICAL
    'paint_attempts': 40.0,      # Lower for 2024-25 season
    'mid_range_attempts': 40.0,  # Lower for 2024-25 season
    'assisted_fg_makes': 40.0,   # Lower for 2024-25 season
}
```

---

### Enhancement 2: Regression Detection

**New flag**: `--check-regression`

**Purpose**: Compare new backfilled data against historical baseline

**Example**:
```bash
python3 bin/validate_pipeline.py 2024-05-01 2026-01-02 \
  --phase 3 \
  --check-regression
```

**Implementation**:
```python
def detect_regression(
    client: bigquery.Client,
    new_data_start: date,
    new_data_end: date,
    baseline_start: date,
    baseline_end: date,
    features: List[str],
) -> dict:
    """
    Detect if new backfilled data has worse coverage than historical baseline.

    Args:
        client: BigQuery client
        new_data_start/end: Date range for newly backfilled data
        baseline_start/end: Date range for known-good baseline data
        features: Features to check

    Returns:
        Dict with regression analysis per feature
    """
    results = {}

    for feature in features:
        # Query baseline coverage
        baseline_query = f"""
        SELECT
          COUNTIF({feature} IS NOT NULL) * 100.0 / COUNT(*) as coverage_pct
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date >= @start_date
          AND game_date <= @end_date
          AND points IS NOT NULL
        """

        baseline_job = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", baseline_start),
                bigquery.ScalarQueryParameter("end_date", "DATE", baseline_end),
            ]
        )
        baseline_result = client.query(baseline_query, job_config=baseline_job).result()
        baseline_row = next(baseline_result)
        baseline_coverage = float(baseline_row.coverage_pct) if baseline_row.coverage_pct else 0.0

        # Query new data coverage
        new_job = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", new_data_start),
                bigquery.ScalarQueryParameter("end_date", "DATE", new_data_end),
            ]
        )
        new_result = client.query(baseline_query, job_config=new_job).result()
        new_row = next(new_result)
        new_coverage = float(new_row.coverage_pct) if new_row.coverage_pct else 0.0

        # Calculate change
        change = new_coverage - baseline_coverage
        change_pct = (change / baseline_coverage * 100) if baseline_coverage > 0 else 0

        # Determine status
        if new_coverage < baseline_coverage * 0.90:
            status = 'REGRESSION'  # >10% worse
        elif new_coverage < baseline_coverage * 0.95:
            status = 'DEGRADATION'  # 5-10% worse
        elif new_coverage >= baseline_coverage * 0.95:
            status = 'OK'  # Within 5%
        else:
            status = 'IMPROVEMENT'

        results[feature] = {
            'baseline_coverage': baseline_coverage,
            'new_coverage': new_coverage,
            'change': change,
            'change_pct': change_pct,
            'status': status,
        }

    return results
```

---

### Enhancement 3: Backfill-Specific Validation Mode

**New flag**: `--backfill-mode`

**Purpose**: Force backfill validation thresholds even for recent dates

**Example**:
```bash
# Force backfill mode for recent dates
python3 bin/validate_pipeline.py today \
  --backfill-mode \
  --validate-features minutes_played,usage_rate
```

**Current Behavior**:
```python
# In validate_date() function (line 124-126)
validation_mode = get_validation_mode(game_date)  # Auto-detects based on date
```

**Enhanced Behavior**:
```python
# Enhanced with flag override
def validate_date(
    game_date: date,
    client: Optional[bigquery.Client] = None,
    phases: Optional[List[int]] = None,
    verbose: bool = False,
    show_missing: bool = False,
    skip_phase1_phase2: bool = False,
    backfill_mode: bool = False,  # NEW
    validate_features: Optional[List[str]] = None,  # NEW
    check_regression: bool = False,  # NEW
) -> ValidationReport:

    # Determine validation mode
    if backfill_mode:
        validation_mode = 'backfill'  # Force backfill mode
    else:
        validation_mode = get_validation_mode(game_date)  # Auto-detect
```

---

### Enhancement 4: Unified Validation Report

**Purpose**: Clear PASS/FAIL with actionable next steps

**Enhanced Output**:
```
════════════════════════════════════════════════════════
  BACKFILL VALIDATION REPORT
════════════════════════════════════════════════════════

Date Range: 2024-05-01 to 2026-01-02
Mode: Backfill (gamebook player universe)
Phases: 3 (Analytics)

PHASE 3 ANALYTICS: player_game_summary
  ✅ Record count: 38,547 (expected: 35,000+)
  ✅ Game coverage: 100% (245/245 dates)
  ✅ Success rate: 99.2%

FEATURE COVERAGE:
  ✅ minutes_played: 99.4% (threshold: 99%+)      PASS
  ✅ usage_rate: 97.2% (threshold: 95%+)          PASS
  ⚠️  shot_zones: 42.1% (threshold: 40%+)         PASS (acceptable)

QUALITY METRICS:
  ✅ Avg quality score: 81.2 (threshold: 75+)
  ✅ Production ready: 96.1% (threshold: 95%+)
  ✅ Gold/Silver tier: 84.3%

REGRESSION ANALYSIS:
  ✅ minutes_played: 99.4% new vs 99.5% old (-0.1%, OK)
  ✅ usage_rate: 97.2% new vs 0.0% old (IMPROVEMENT!)
  ⚠️  shot_zones: 42.1% new vs 87.0% old (-44.9%, DEGRADATION)
      └─ Expected: BigDataBall format change in Oct 2024

OVERALL STATUS: ✅ PASS

Next Steps:
  1. ✅ Phase 3 validated - ready to proceed
  2. ⏭️  Run Phase 4 backfill (precompute)
  3. ⏭️  Train ML model (expected MAE: 4.0-4.2)

════════════════════════════════════════════════════════
```

---

## 📋 IMPLEMENTATION PLAN

### Phase 1: Core Functions (15 min)

**Files to create**:
- `shared/validation/validators/feature_validator.py` - Feature coverage validation
- `shared/validation/validators/regression_detector.py` - Regression detection

**Functions to add**:
```python
# feature_validator.py
def validate_feature_coverage(client, start_date, end_date, features, thresholds) -> dict
def get_default_feature_thresholds() -> dict

# regression_detector.py
def detect_regression(client, new_start, new_end, baseline_start, baseline_end, features) -> dict
def suggest_baseline_period(new_start: date) -> tuple[date, date]
```

### Phase 2: CLI Enhancements (10 min)

**File to modify**: `bin/validate_pipeline.py`

**Changes**:
1. Add new CLI arguments:
   ```python
   parser.add_argument('--backfill-mode', action='store_true',
                      help='Force backfill validation mode')
   parser.add_argument('--validate-features', type=str,
                      help='Comma-separated features to validate (minutes_played,usage_rate,...)')
   parser.add_argument('--check-regression', action='store_true',
                      help='Compare new data against historical baseline')
   parser.add_argument('--baseline-period', type=str,
                      help='Baseline date range for regression check (start,end)')
   ```

2. Modify `validate_date()` signature to accept new parameters

3. Call new validation functions when flags present

### Phase 3: Output Enhancements (10 min)

**Files to create**:
- `shared/validation/output/backfill_report.py` - Backfill-specific report formatting

**Functions**:
```python
def format_backfill_report(
    validation_report: ValidationReport,
    feature_results: dict,
    regression_results: dict,
) -> str:
    """Format comprehensive backfill validation report."""
```

### Phase 4: Integration (10 min)

**Wire everything together**:
1. Call feature validation when `--validate-features` present
2. Call regression detection when `--check-regression` present
3. Format unified report with all results
4. Return clear exit code (0 = pass, 1 = fail)

---

## 🔧 USAGE EXAMPLES

### Example 1: Basic Feature Validation
```bash
python3 bin/validate_pipeline.py 2024-05-01 2026-01-02 \
  --phase 3 \
  --validate-features minutes_played,usage_rate
```

**Output**:
```
FEATURE COVERAGE:
  ✅ minutes_played: 99.4% (threshold: 99%+)
  ✅ usage_rate: 97.2% (threshold: 95%+)

STATUS: PASS
```

### Example 2: Regression Detection
```bash
python3 bin/validate_pipeline.py 2024-05-01 2026-01-02 \
  --check-regression
```

**Output**:
```
REGRESSION ANALYSIS:
  ✅ minutes_played: 99.4% new vs 99.5% old (-0.1%, OK)
  ✅ usage_rate: 97.2% new vs 0.0% old (IMPROVEMENT!)
  ⚠️  shot_zones: 42.1% new vs 87.0% old (-44.9%, DEGRADATION)

STATUS: PASS (with warnings)
```

### Example 3: Comprehensive Backfill Validation
```bash
python3 bin/validate_pipeline.py 2024-05-01 2026-01-02 \
  --backfill-mode \
  --phase 3 \
  --validate-features minutes_played,usage_rate,shot_zones \
  --check-regression \
  --format terminal
```

**Output**: Full validation report with all checks

### Example 4: JSON Output for Automation
```bash
python3 bin/validate_pipeline.py 2024-05-01 2026-01-02 \
  --validate-features minutes_played,usage_rate \
  --check-regression \
  --format json > /tmp/validation_results.json

# Check exit code
if [ $? -eq 0 ]; then
  echo "Validation passed - proceed to next phase"
else
  echo "Validation failed - manual review required"
fi
```

---

## 🔗 INTEGRATION WITH BACKFILL JOBS

### How Backfill Jobs Will Use This

**In `player_game_summary_analytics_backfill.py`** (lines ~370-380):

```python
# After backfill completes
logger.info("=" * 80)
logger.info("Backfill complete - running validation...")

# Run validation with feature checks
validation_cmd = [
    "python3", "bin/validate_pipeline.py",
    start_date.isoformat(), end_date.isoformat(),
    "--phase", "3",
    "--validate-features", "minutes_played,usage_rate,shot_zones",
    "--check-regression",
    "--format", "terminal",
]

result = subprocess.run(validation_cmd, capture_output=True, text=True)

if result.returncode == 0:
    logger.info("✅ Validation PASSED - data quality confirmed")
    logger.info(result.stdout)
else:
    logger.error("❌ Validation FAILED - data quality issues detected")
    logger.error(result.stdout)
    logger.warning("Backfill completed but validation failed - manual review required")

logger.info("=" * 80)
```

### Benefits

1. **Automatic quality checks** after every backfill
2. **Clear PASS/FAIL** status
3. **No silent failures** (like 0% usage_rate)
4. **Regression detection** (new data worse than old)
5. **Actionable output** (what to do next)

---

## 🎯 SUCCESS CRITERIA

### Feature Coverage Validation
- [x] Can validate specific features (minutes_played, usage_rate, etc.)
- [x] Uses configurable thresholds per feature
- [x] Reports coverage percentage and PASS/FAIL
- [x] Works for date ranges

### Regression Detection
- [x] Compares new data vs baseline
- [x] Detects degradation (>5% worse)
- [x] Detects regression (>10% worse)
- [x] Provides context for expected degradation

### Integration
- [x] CLI flags work correctly
- [x] Backfill jobs can call validation
- [x] Clear exit codes (0 = pass, 1 = fail)
- [x] JSON output for automation

### Prevents Disasters
- [x] Would catch 0% usage_rate immediately
- [x] Would catch 0-70% minutes_played
- [x] Would prevent "claimed complete" with broken data
- [x] Would detect regressions automatically

---

## 📁 FILES TO CREATE/MODIFY

### New Files
1. `shared/validation/validators/feature_validator.py` (~150 lines)
2. `shared/validation/validators/regression_detector.py` (~120 lines)
3. `shared/validation/output/backfill_report.py` (~100 lines)
4. `shared/validation/config/feature_thresholds.py` (~30 lines)

### Modified Files
1. `bin/validate_pipeline.py` (~50 lines changed)
   - Add CLI arguments
   - Call new validators
   - Integrate output

---

## ⏭️ NEXT STEPS

### Tonight (While Orchestrator Runs)
- [x] Design validation framework enhancements (THIS DOC)
- [ ] Implement core validation functions (45 min)
- [ ] Test with current data
- [ ] Document usage examples

### Future Session
- [ ] Integrate into backfill jobs
- [ ] Add to daily monitoring
- [ ] Create Grafana dashboards
- [ ] Schedule automated validation runs

---

**Created**: January 3, 2026, 14:05 UTC
**Status**: 🎯 DESIGN COMPLETE - Ready for implementation
**Estimated implementation time**: 45-60 min
**Risk**: Zero (won't touch running processes)
**Impact**: High (prevents future "claimed complete" disasters)
