# MLB Validator Configurations

Configuration files for MLB data validation framework.

## Available Validators

### 1. MLB Schedule Validator
**File**: `mlb_schedule.yaml`
**Purpose**: Validates MLB schedule data - the source of truth for games and probable pitchers

**Validations**:
- Season completeness (expected ~2430 games)
- Team presence (all 30 MLB teams)
- Probable pitcher completeness (80% target)
- Duplicate detection
- Game time validity
- Date gaps detection

**Usage**:
```bash
PYTHONPATH=. python validation/validators/mlb/mlb_schedule_validator.py \
  --config validation/configs/mlb/mlb_schedule.yaml \
  --start-date 2025-08-01 \
  --end-date 2025-08-31
```

---

### 2. MLB Pitcher Props Validator
**File**: `mlb_pitcher_props.yaml`
**Purpose**: Validates pitcher strikeout props from BettingPros and Odds API

**Validations**:
- Props coverage vs scheduled pitchers (80% target)
- Strikeout line ranges (0.5-15.5)
- Odds validity (-500 to +500)
- Sportsbook diversity
- Duplicate detection
- Odds API secondary source check

**Usage**:
```bash
PYTHONPATH=. python validation/validators/mlb/mlb_pitcher_props_validator.py \
  --config validation/configs/mlb/mlb_pitcher_props.yaml \
  --start-date 2025-08-01 \
  --end-date 2025-08-31
```

---

### 3. MLB Prediction Coverage Validator
**File**: `mlb_prediction_coverage.yaml`
**Purpose**: Validates prediction coverage and quality for pitcher strikeouts

**Validations**:
- Prediction coverage vs props (90% target)
- Prediction quality (confidence, edge, recommendation)
- Model version tracking
- Grading completeness (80% target for completed games)
- High-confidence prediction tracking
- Edge distribution monitoring
- Duplicate detection

**Usage**:
```bash
PYTHONPATH=. python validation/validators/mlb/mlb_prediction_coverage_validator.py \
  --config validation/configs/mlb/mlb_prediction_coverage.yaml \
  --start-date 2025-08-01 \
  --end-date 2025-08-31
```

---

## Configuration Structure

All MLB validator configs follow this structure:

```yaml
processor:
  name: "validator_name"
  description: "Description"
  table: "dataset.table_name"
  partition_required: true/false
  partition_field: "field_name"
  layers:
    - gcs           # GCS file validation
    - bigquery      # BigQuery data validation
    - schedule      # Schedule-aware validation

gcs_validations:
  enabled: true
  file_presence:
    bucket: "bucket_name"
    path_pattern: "path/pattern"
    severity: "error"

bigquery_validations:
  enabled: true
  # Various validation types...

schedule_validations:
  enabled: true
  data_freshness:
    timestamp_field: "created_at"
    max_age_hours: 24
    severity: "warning"

remediation:
  processor_backfill_template: |
    gcloud run jobs execute ...

notifications:
  enabled: true
  channels: ["slack"]
  on_failure: true
  on_success: false
```

---

## Severity Levels

- **error**: Critical issues that block production
- **warning**: Issues that need attention but don't block
- **info**: Informational tracking, no action needed

---

## Target Coverage Metrics

| Validator | Metric | Target | Severity |
|-----------|--------|--------|----------|
| Schedule | Team presence | 30 teams | error |
| Schedule | Probable pitcher completeness | 80% | warning |
| Props | Props coverage vs schedule | 80% | warning |
| Predictions | Prediction coverage vs props | 90% | warning |
| Predictions | Grading completeness | 80% | warning |

---

## Remediation Commands

Each validator config includes remediation templates for:

1. **Scraper backfill** - Re-run scrapers for missing data
2. **Processor backfill** - Re-process raw data to BigQuery
3. **Service backfill** - Re-generate predictions or grading

Example:
```bash
# Scraper backfill
gcloud run jobs execute mlb-bettingpros-pitcher-props-scraper \
  --args=--date=2025-08-15 \
  --region=us-west2

# Processor backfill
gcloud run jobs execute mlb-pitcher-props-processor-backfill \
  --args=--start-date=2025-08-01,--end-date=2025-08-31 \
  --region=us-west2
```

---

## Schedule-Aware Validation

All validators respect the MLB season schedule:

- **Regular Season**: Early April - Early October
- **Postseason**: October
- **Off-season**: November - March

Validations automatically adjust expectations during off-season.

---

## Integration with Base Validator

All configs are consumed by validators that extend `BaseValidator`:

```python
from validation.base_validator import BaseValidator

class MlbScheduleValidator(BaseValidator):
    def __init__(self, config_path: str):
        super().__init__(config_path)

    def _run_custom_validations(self, start_date, end_date, season_year):
        # Custom MLB-specific checks
        pass
```

The base validator handles:
- Config loading and validation
- BigQuery client initialization
- Query execution and caching
- Report generation
- Notification sending

---

## Testing Validators

### Dry Run Mode
```bash
# Test without sending notifications
PYTHONPATH=. python validation/validators/mlb/mlb_schedule_validator.py \
  --config validation/configs/mlb/mlb_schedule.yaml \
  --start-date 2025-08-15 \
  --end-date 2025-08-15 \
  --dry-run
```

### JSON Output
```bash
# Get machine-readable output
PYTHONPATH=. python validation/validators/mlb/mlb_prediction_coverage_validator.py \
  --config validation/configs/mlb/mlb_prediction_coverage.yaml \
  --start-date 2025-08-01 \
  --end-date 2025-08-31 \
  --json > report.json
```

---

## Deployment

Validators should run:

1. **Schedule Validator**: Daily at 6 AM ET (before games)
2. **Props Validator**: Every 4 hours during game days
3. **Prediction Coverage Validator**: 2 hours before first game, and post-games

Deploy via Cloud Run scheduler:
```bash
gcloud scheduler jobs create http mlb-schedule-validator \
  --schedule="0 6 * * *" \
  --time-zone="America/New_York" \
  --uri="https://mlb-validator-service-HASH.run.app/validate" \
  --http-method=POST \
  --message-body='{"validator": "schedule", "date": "today"}' \
  --location=us-west2
```

---

## Related Documentation

- Base Validator: `validation/base_validator.py`
- MLB Validators: `validation/validators/mlb/`
- MLB Feature Parity: `docs/08-projects/current/mlb-feature-parity/`

---

**Created**: 2026-01-16
**Status**: Production Ready
