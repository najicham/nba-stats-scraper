# NBA Stats Scraper - Validation Framework

**Location**: `shared/validation/`
**Purpose**: Production-grade data validation for multi-phase NBA stats pipeline
**Status**: Production (actively used in backfills and daily processing)

---

## 📋 Overview

The validation framework provides comprehensive data quality validation across all 5 phases of the NBA stats pipeline:
- **Phase 1**: GCS raw data files
- **Phase 2**: BigQuery raw tables (`nba_raw`)
- **Phase 3**: BigQuery analytics tables (`nba_analytics`)
- **Phase 4**: BigQuery precompute tables (`nba_precompute`)
- **Phase 5**: BigQuery prediction tables (`nba_predictions`)

### Two Types of Completeness

**IMPORTANT:** This system tracks TWO types of completeness (see `docs/06-reference/completeness-concepts.md`):

1. **Schedule Completeness** - "Did we get today's games?" (existing)
2. **Historical Completeness** - "Did rolling averages have all 10 games?" (added Jan 2026)

The `historical_completeness.py` module handles the second type, enabling cascade detection after backfills.

---

## 🏗️ Architecture

### Core Components

```
shared/validation/
├── config.py                      # Central configuration (PROJECT_ID, tables, thresholds)
├── chain_config.py                # Fallback chain definitions
├── feature_thresholds.py          # Feature coverage requirements
├── firestore_state.py             # Real-time orchestration state
├── run_history.py                 # Processor execution tracking
├── time_awareness.py              # Time-based validation logic
├── historical_completeness.py     # Rolling window completeness (Jan 2026)
│
├── context/
│   ├── schedule_context.py        # Game schedule awareness (bootstrap detection)
│   └── player_universe.py         # Active/rostered player sets
│
├── validators/
│   ├── base.py                    # Base classes, common queries
│   ├── phase1_validator.py        # GCS JSON file validation
│   ├── phase2_validator.py        # Raw BigQuery data validation
│   ├── phase3_validator.py        # Analytics table validation
│   ├── phase4_validator.py        # Precompute validation (bootstrap-aware)
│   ├── phase5_validator.py        # Prediction validation
│   ├── chain_validator.py         # Fallback chain validation
│   ├── feature_validator.py       # Feature coverage checks
│   ├── regression_detector.py     # Anomaly/degradation detection
│   └── maintenance_validator.py   # Maintenance operation checks
│
└── output/
    ├── terminal.py                # Console output formatting
    ├── json_output.py             # JSON report generation
    └── backfill_report.py         # Detailed backfill reports
```

---

## 🎯 Key Features

### 1. Phase-Specific Validation
Each phase has dedicated validators that understand:
- Expected data sources
- Coverage requirements
- Quality tiers
- Bootstrap periods (first 14 days of season)
- Edge cases (All-Star weekend, playoffs)

### 2. Fallback Chain Management
Tracks data quality when using fallback sources:
- **Primary Source**: First choice (e.g., NBA.com gamebook)
- **Fallback Source**: Used when primary unavailable (e.g., BDL boxscores)
- **Virtual Source**: Constructed from other sources (e.g., team stats from players)
- Quality impact reported when fallbacks used

### 3. Bootstrap Awareness
Phase 4 processors require 10-15 game history for rolling averages:
- First 14 days of each season: Expected empty (not an error)
- Validation status: `BOOTSTRAP_SKIP` (distinct from `MISSING`)
- Maximum theoretical coverage: ~88% (not 100%)

### 4. Feature Coverage Validation
Enforces minimum coverage thresholds for ML features:
- **minutes_played**: ≥99% (CRITICAL - blocks ML training)
- **usage_rate**: ≥95% (CRITICAL - blocks ML training)
- **shot_zones**: ≥40% (season-dependent, not blocking)
- Configurable per feature in `feature_thresholds.py`

### 5. Regression Detection
Compares new data against historical baseline:
- **REGRESSION**: >10% worse than baseline (FAIL)
- **DEGRADATION**: 5-10% worse (WARNING)
- **OK**: Within 5% of baseline
- **IMPROVEMENT**: >5% better
- Auto-suggests 3-month baseline for comparison

### 6. Context-Aware Validation
- **Game Schedule**: Knows expected games per date
- **Player Universe**: Validates against active/rostered player sets
- **Time-Based**: Different thresholds for daily vs backfill
- **Season Detection**: Auto-detects season boundaries

---

## 📊 Validation Statuses

```python
class ValidationStatus(Enum):
    COMPLETE = 'complete'                # All expected data present
    PARTIAL = 'partial'                  # Some data missing
    MISSING = 'missing'                  # No data found
    BOOTSTRAP_SKIP = 'bootstrap_skip'   # Expected empty (first 14 days)
    NOT_APPLICABLE = 'not_applicable'   # Not relevant for this date
    ERROR = 'error'                      # Error during validation
```

---

## 🔧 Usage

### Basic Validation Example

```python
from shared.validation.validators.phase3_validator import Phase3Validator
from datetime import date

# Initialize validator
validator = Phase3Validator()

# Validate player_game_summary for a date
result = validator.validate_table(
    table_name='player_game_summary',
    game_date=date(2025, 12, 25),
    expected_scope='all_rostered'  # or 'active_only', 'teams'
)

print(f"Status: {result.status}")
print(f"Records: {result.record_count}")
print(f"Expected: {result.expected_count}")
print(f"Coverage: {result.coverage_pct}%")
print(f"Quality: {result.quality_distribution}")
```

### Feature Coverage Check

```python
from shared.validation.validators.feature_validator import FeatureValidator

validator = FeatureValidator()

# Check usage_rate coverage for training data
result = validator.validate_feature(
    table='nba_analytics.player_game_summary',
    feature='usage_rate',
    start_date='2021-10-01',
    end_date='2024-05-01'
)

if result.passes_threshold:
    print(f"✅ usage_rate: {result.coverage_pct}% (threshold: {result.threshold}%)")
else:
    print(f"❌ usage_rate: {result.coverage_pct}% (threshold: {result.threshold}%)")
    print(f"   CRITICAL: {result.is_critical}")
```

### Regression Detection

```python
from shared.validation.validators.regression_detector import RegressionDetector

detector = RegressionDetector()

# Compare new backfill data vs historical baseline
result = detector.detect_regression(
    table='nba_analytics.player_game_summary',
    new_data_range=('2024-05-01', '2026-01-02'),
    baseline_range=('2024-02-01', '2024-04-30'),  # 3 months before
    features=['minutes_played', 'usage_rate', 'paint_attempts']
)

for feature, status in result.items():
    print(f"{feature}: {status.status} ({status.delta_pct:+.1f}%)")
```

### Chain Validation

```python
from shared.validation.validators.chain_validator import ChainValidator

validator = ChainValidator()

# Validate fallback chain for player stats
result = validator.validate_chain(
    chain_name='player_boxscores',
    game_date=date(2025, 12, 25)
)

print(f"Source used: {result.source_used}")  # PRIMARY, FALLBACK, or VIRTUAL
print(f"Quality impact: {result.quality_impact}")
print(f"Completeness: {result.completeness_pct}%")
```

---

## ⚙️ Configuration

### Central Config (`config.py`)

```python
# Project
PROJECT_ID = 'nba-props-platform'

# Expected prediction systems (update when adding/removing)
EXPECTED_PREDICTION_SYSTEMS = [
    'moving_average',
    'zone_matchup_v1',
    'similarity_balanced_v1',
    'xgboost_v1',
    'ensemble_v1',
]

# Quality tiers
QUALITY_TIERS = {
    'gold': {'min_score': 95, 'production_ready': True},
    'silver': {'min_score': 75, 'production_ready': True},
    'bronze': {'min_score': 50, 'production_ready': True},
    'poor': {'min_score': 25, 'production_ready': False},
    'unusable': {'min_score': 0, 'production_ready': False},
}
```

### Feature Thresholds (`feature_thresholds.py`)

```python
FEATURE_THRESHOLDS = {
    # CRITICAL features (block if below threshold)
    'minutes_played': {'threshold': 99.0, 'critical': True},
    'usage_rate': {'threshold': 95.0, 'critical': True},

    # Shot distribution (season-dependent)
    'paint_attempts': {'threshold': 40.0, 'critical': False},
    'mid_range_attempts': {'threshold': 40.0, 'critical': False},
    'three_pt_attempts': {'threshold': 99.0, 'critical': True},

    # Core stats
    'points': {'threshold': 99.5, 'critical': True},
    'fg_attempts': {'threshold': 99.0, 'critical': True},
}
```

---

## 🚀 Integration Points

### 1. Backfill Scripts
```python
from shared.validation.validators.phase3_validator import Phase3Validator

# After backfill completes, validate results
validator = Phase3Validator()
result = validator.validate_date_range(
    table='player_game_summary',
    start_date='2021-10-19',
    end_date='2026-01-02'
)

if result.passes_validation:
    print("✅ Backfill validated successfully")
else:
    print(f"❌ Validation failed: {result.failures}")
```

### 2. Orchestrator Integration
```bash
# scripts/backfill_orchestrator.sh uses validation scripts
./scripts/validation/validate_team_offense.sh --start-date 2021-10-19 --end-date 2026-01-02

# Returns exit code 0 (PASS) or 1 (FAIL)
```

### 3. Daily Pipeline
```python
# Processors can validate their own output
from shared.validation.validators.base import ValidationStatus

result = validate_processor_output(processor_name, date)
if result.status != ValidationStatus.COMPLETE:
    send_alert(f"Incomplete data: {result.status}")
```

---

## 📈 Monitoring

### Firestore State Tracking
Real-time completion monitoring:
```python
from shared.validation.firestore_state import check_phase_completion

# Check if Phase 3 complete for a date
completion = check_phase_completion(
    phase=3,
    game_date=date(2025, 12, 25)
)

print(f"Phase 3: {completion.completed_count}/{completion.expected_count}")
print(f"Processors complete: {completion.processor_list}")
```

### Run History
Historical tracking in BigQuery:
```python
from shared.validation.run_history import query_processor_history

# Get recent runs for a processor
runs = query_processor_history(
    processor_name='PlayerGameSummaryProcessor',
    days=7
)

for run in runs:
    print(f"{run.timestamp}: {run.status} ({run.records_processed} records)")
```

---

## 🛠️ Development

### Adding a New Validator

1. Create new file in `validators/` (e.g., `phase6_validator.py`)
2. Inherit from `BaseValidator`
3. Implement required methods:
   - `validate_table()`
   - `validate_date_range()`
   - `get_expected_count()`
4. Add to `validators/__init__.py`
5. Update documentation

### Adding a New Feature Threshold

1. Edit `feature_thresholds.py`
2. Add feature definition:
```python
'new_feature': {
    'threshold': 95.0,
    'critical': True,  # Blocks ML training if below
    'description': 'Description of feature'
}
```
3. Update validation queries in `feature_validator.py`

### Testing

```bash
# Run validation tests
pytest shared/validation/tests/

# Test specific validator
pytest shared/validation/tests/test_phase3_validator.py

# Integration test with live data
PYTHONPATH=. python -m shared.validation.validators.phase3_validator --date 2025-12-25
```

---

## 📚 Related Documentation

- **User Guide**: `docs/validation-framework/VALIDATION-GUIDE.md`
- **Backfill Validation**: `docs/validation-framework/BACKFILL-VALIDATION.md`
- **Shell Scripts**: `scripts/validation/README.md`
- **Thresholds Config**: `scripts/config/backfill_thresholds.yaml`
- **Architecture**: `docs/validation-framework/ARCHITECTURE.md`

---

## 🔍 Common Use Cases

### 1. Validate Backfill Before Proceeding
```bash
# Use shell script for quick validation
./scripts/validation/validate_player_summary.sh \
  --start-date 2024-05-01 \
  --end-date 2026-01-02 \
  --threshold-config scripts/config/backfill_thresholds.yaml
```

### 2. Check if ML Training Ready
```python
from shared.validation.validators.feature_validator import check_ml_readiness

result = check_ml_readiness(
    training_start='2021-10-01',
    training_end='2024-05-01',
    required_features=['minutes_played', 'usage_rate', ...]
)

if result.ready:
    print("✅ Ready for ML training")
else:
    print(f"❌ Missing features: {result.missing_features}")
```

### 3. Compare Two Date Ranges
```python
from shared.validation.validators.regression_detector import compare_periods

result = compare_periods(
    table='nba_analytics.player_game_summary',
    period1=('2021-10-01', '2022-06-01'),
    period2=('2024-10-01', '2025-06-01'),
    features=['minutes_played', 'usage_rate']
)

print(f"Regression detected: {result.has_regression}")
```

---

## ⚠️ Important Notes

### Bootstrap Period
Phase 4 data **intentionally missing** for first 14 days of each season:
- This is **NOT an error**
- Processors need 10-15 game history
- Maximum coverage: ~88% (not 100%)
- Validation returns `BOOTSTRAP_SKIP` status

### Shot Zone Coverage
BigDataBall format changed Oct 2024:
- Historical (2021-2023): 86-88% coverage
- Current (2024-2026): 40-50% coverage
- This is **expected** due to data source limitations
- Threshold lowered to 40% for 2024+ seasons

### Critical vs Non-Critical Features
- **Critical**: Blocks ML training if below threshold
- **Non-Critical**: Logs warning but allows continuation
- Configure in `feature_thresholds.py`

---

## 🤝 Contributing

When adding new features:
1. Update `config.py` if adding tables/systems
2. Update `feature_thresholds.py` if adding ML features
3. Add validators for new data sources
4. Update shell scripts in `scripts/validation/`
5. Document in `docs/validation-framework/`
6. Add tests

---

## 📞 Support

For questions or issues:
- Check documentation: `docs/validation-framework/`
- Review examples in `shared/validation/examples/`
- Check shell scripts: `scripts/validation/`
- See orchestrator integration: `scripts/backfill_orchestrator.sh`

---

**Last Updated**: January 4, 2026
**Version**: 2.0 (Production)
**Status**: Active
