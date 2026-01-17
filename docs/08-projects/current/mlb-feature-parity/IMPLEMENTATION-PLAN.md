# MLB Feature Parity Implementation Plan

**Created**: 2026-01-16
**Target Completion**: Before Opening Day (Late March 2026)

---

## Phase 1: Monitoring (Priority: CRITICAL)

### Goal
Detect MLB pipeline issues before they affect predictions.

### Deliverables

#### 1.1 MLB Gap Detection (`monitoring/mlb/mlb_gap_detection.py`)
**Purpose**: Detect GCS files that haven't been processed to BigQuery

**Pattern**: Mirror `monitoring/processors/gap_detection/`

**Logic**:
```python
# For each MLB scraper:
# 1. List GCS files for date range
# 2. Query BigQuery for processed records
# 3. Identify gaps (files without matching BQ rows)
# 4. Generate remediation commands
```

**Config needed**:
```yaml
mlb_scrapers:
  - name: bp_pitcher_props
    gcs_path: "bettingpros/mlb/pitcher-props/{date}/"
    bq_table: mlb_raw.bp_pitcher_props
    date_field: game_date
  - name: oddsa_pitcher_props
    gcs_path: "odds-api/mlb/pitcher-props/{date}/"
    bq_table: mlb_raw.oddsa_pitcher_props
    date_field: game_date
  # ... etc
```

#### 1.2 MLB Freshness Checker (`monitoring/mlb/mlb_freshness_checker.py`)
**Purpose**: Alert when data is stale

**Pattern**: Mirror `monitoring/scrapers/freshness/`

**Checks**:
- Schedule data: Should update daily during season
- Pitcher props: Should have today's games by 10 AM ET
- Analytics: Should process within 1 hour of raw data
- Predictions: Should complete 2 hours before first game

#### 1.3 MLB Prediction Coverage (`monitoring/mlb/mlb_prediction_coverage.py`)
**Purpose**: Ensure all scheduled pitchers get predictions

**Logic**:
```python
# 1. Get scheduled pitchers from mlb_schedule
# 2. Get predictions from mlb_predictions.pitcher_strikeouts
# 3. Identify missing pitchers
# 4. Alert if coverage < 95%
```

#### 1.4 MLB Execution Monitor (`monitoring/mlb/mlb_execution_monitor.py`)
**Purpose**: Detect stuck processors

**Pattern**: Mirror `monitoring/processors/execution/`

**Checks**:
- Analytics processor: Should complete in < 10 min
- Precompute processor: Should complete in < 15 min
- Prediction worker: Should complete in < 5 min per pitcher
- Grading processor: Should complete in < 10 min

#### 1.5 MLB Stall Detector (`monitoring/mlb/mlb_stall_detector.py`)
**Purpose**: Detect pipeline stalls

**Pattern**: Mirror `monitoring/stall_detection/`

**Checks**:
- No new raw data in 24 hours (during season)
- No new analytics in 24 hours (during season)
- No new predictions on game day
- Predictions not graded within 6 hours of game end

### Testing

```bash
# Test with historical date
PYTHONPATH=. python monitoring/mlb/mlb_gap_detection.py --date 2025-08-15
PYTHONPATH=. python monitoring/mlb/mlb_freshness_checker.py --date 2025-08-15
PYTHONPATH=. python monitoring/mlb/mlb_prediction_coverage.py --date 2025-08-15
```

---

## Phase 2: Validation (Priority: HIGH)

### Goal
Catch data quality issues before predictions.

### Deliverables

#### 2.1 MLB Schedule Validator (`validation/validators/mlb/mlb_schedule_validator.py`)
**Purpose**: Validate schedule data completeness

**Config** (`validation/configs/mlb/mlb_schedule.yaml`):
```yaml
processor:
  name: mlb_schedule
  type: raw
  table: mlb_raw.mlb_schedule
  partition_required: true
  partition_field: game_date
  layers: [bigquery]

bigquery_validations:
  enabled: true
  completeness:
    target_table: mlb_raw.mlb_schedule
    reference_table: mlb_raw.mlb_schedule  # Self-reference for date presence
    match_field: game_date
    severity: error
  field_validation:
    target_table: mlb_raw.mlb_schedule
    required_not_null:
      - game_pk
      - game_date
      - home_team
      - away_team
      - probable_home_pitcher
      - probable_away_pitcher
```

**Custom checks**:
- Both teams have probable pitchers
- Game times are valid
- No duplicate game_pk

#### 2.2 MLB Pitcher Props Validator (`validation/validators/mlb/mlb_pitcher_props_validator.py`)
**Purpose**: Validate betting lines loaded

**Custom checks**:
- Has props for 80%+ of scheduled pitchers
- Lines are reasonable (0.5 < strikeouts_line < 15)
- Multiple sportsbooks present

#### 2.3 MLB Pitcher Stats Validator (`validation/validators/mlb/mlb_pitcher_stats_validator.py`)
**Purpose**: Validate game stats for grading

**Custom checks**:
- Actual strikeouts recorded after game end
- Stats match across data sources
- No duplicate records

#### 2.4 MLB Prediction Coverage Validator (`validation/validators/mlb/mlb_prediction_coverage_validator.py`)
**Purpose**: Validate prediction completeness

**Custom checks**:
- 95%+ of pitchers with props have predictions
- Predictions have valid confidence scores
- No duplicate predictions

#### 2.5 MLB Analytics Validator (`validation/validators/mlb/mlb_analytics_validator.py`)
**Purpose**: Validate rolling stats computed

**Custom checks**:
- Rolling averages calculated for all pitchers
- No NULL values in key features
- Recent games included in windows

### Testing

```bash
# Run validators
PYTHONPATH=. python -c "
from validation.validators.mlb.mlb_schedule_validator import MlbScheduleValidator
v = MlbScheduleValidator('validation/configs/mlb/mlb_schedule.yaml')
v.validate(start_date='2025-08-01', end_date='2025-08-31')
"
```

---

## Phase 3: Publishing (Priority: HIGH)

### Goal
Export predictions and performance data to GCS for API consumption.

### Deliverables

#### 3.1 MLB Base Exporter (`data_processors/publishing/mlb/mlb_base_exporter.py`)
**Purpose**: Base class for MLB exporters

**Extends**: `data_processors/publishing/base_exporter.py`

**MLB-specific**:
- Bucket: `mlb-props-platform-api` (or same bucket with `/mlb/` prefix)
- API version: `v1`
- Date handling for MLB season

#### 3.2 MLB Predictions Exporter (`data_processors/publishing/mlb/mlb_predictions_exporter.py`)
**Purpose**: Export daily predictions

**Output path**: `gs://bucket/v1/mlb/predictions/{date}.json`

**Schema**:
```json
{
  "generated_at": "2025-08-15T10:00:00Z",
  "game_date": "2025-08-15",
  "predictions": [
    {
      "pitcher_name": "Garrett Crochet",
      "pitcher_id": "garrett_crochet",
      "team": "CWS",
      "opponent": "DET",
      "strikeouts_line": 7.5,
      "predicted_strikeouts": 8.2,
      "recommendation": "OVER",
      "confidence": 72,
      "edge": 0.7,
      "model_version": "V1.6"
    }
  ],
  "summary": {
    "total_predictions": 15,
    "over_picks": 8,
    "under_picks": 5,
    "pass_picks": 2
  }
}
```

#### 3.3 MLB Best Bets Exporter (`data_processors/publishing/mlb/mlb_best_bets_exporter.py`)
**Purpose**: Export high-confidence plays

**Criteria**:
- Confidence >= 70%
- Edge >= 1.0
- No red flags active

**Output path**: `gs://bucket/v1/mlb/best-bets/{date}.json`

#### 3.4 MLB System Performance Exporter (`data_processors/publishing/mlb/mlb_system_performance_exporter.py`)
**Purpose**: Export model accuracy metrics

**Output path**: `gs://bucket/v1/mlb/performance/{date}.json`

**Schema**:
```json
{
  "generated_at": "2025-08-16T06:00:00Z",
  "period": "2025-08-01_to_2025-08-15",
  "models": {
    "V1.4": {
      "total_predictions": 150,
      "correct": 95,
      "accuracy": 63.3,
      "over_accuracy": 58.0,
      "under_accuracy": 71.0
    },
    "V1.6": {
      "total_predictions": 150,
      "correct": 105,
      "accuracy": 70.0,
      "over_accuracy": 65.0,
      "under_accuracy": 76.0
    }
  },
  "recommendation": "V1.6 outperforming by 6.7%"
}
```

#### 3.5 MLB Pitcher Profile Exporter (`data_processors/publishing/mlb/mlb_pitcher_profile_exporter.py`)
**Purpose**: Export pitcher detail pages

**Output path**: `gs://bucket/v1/mlb/pitchers/{pitcher_id}.json`

#### 3.6 MLB Results Exporter (`data_processors/publishing/mlb/mlb_results_exporter.py`)
**Purpose**: Export game outcomes for grading display

**Output path**: `gs://bucket/v1/mlb/results/{date}.json`

#### 3.7 MLB Status Exporter (`data_processors/publishing/mlb/mlb_status_exporter.py`)
**Purpose**: Export pipeline health status

**Output path**: `gs://bucket/v1/mlb/status/current.json`

### Testing

```bash
# Test exporters
PYTHONPATH=. python -c "
from data_processors.publishing.mlb.mlb_predictions_exporter import MlbPredictionsExporter
e = MlbPredictionsExporter()
result = e.generate_json(game_date='2025-08-15')
print(result)
"
```

---

## Phase 4: Alert Integration (Priority: MEDIUM)

### Goal
Verify MLB services use AlertManager correctly.

### Deliverables

#### 4.1 Audit MLB Services
Check these files for AlertManager usage:
- `services/analytics/main_mlb_analytics_service.py`
- `services/precompute/main_mlb_precompute_service.py`
- `predictions/mlb/worker.py`
- `services/grading/main_mlb_grading_service.py`

#### 4.2 Add AlertManager Integration
If not present, add to each service:

```python
from shared.alerts.alert_manager import get_alert_manager

# Initialize with backfill awareness
alert_mgr = get_alert_manager(
    backfill_mode=os.environ.get('BACKFILL_MODE', 'false').lower() == 'true'
)

# On error
alert_mgr.send_alert(
    severity='warning',
    title=f'MLB Analytics Failed: {game_date}',
    message=str(error),
    category='mlb_analytics_failure',
    context={'game_date': game_date, 'processor': 'pitcher_game_summary'}
)
```

#### 4.3 Add Alert Categories
Define MLB-specific alert categories:
- `mlb_scraper_failure`
- `mlb_analytics_failure`
- `mlb_precompute_failure`
- `mlb_prediction_failure`
- `mlb_grading_failure`
- `mlb_data_gap`
- `mlb_data_stale`
- `mlb_low_coverage`

---

## Implementation Order

### Week 1: Monitoring
```
Day 1: mlb_gap_detection.py + config
Day 2: mlb_freshness_checker.py
Day 3: mlb_prediction_coverage.py + mlb_execution_monitor.py
Day 4: mlb_stall_detector.py + testing
Day 5: Deploy monitoring to Cloud Run scheduler
```

### Week 2: Validation
```
Day 1: mlb_schedule_validator.py + config
Day 2: mlb_pitcher_props_validator.py + config
Day 3: mlb_pitcher_stats_validator.py + config
Day 4: mlb_prediction_coverage_validator.py + config
Day 5: mlb_analytics_validator.py + testing
```

### Week 3: Publishing
```
Day 1: mlb_base_exporter.py
Day 2: mlb_predictions_exporter.py + mlb_best_bets_exporter.py
Day 3: mlb_system_performance_exporter.py
Day 4: mlb_pitcher_profile_exporter.py + mlb_results_exporter.py
Day 5: mlb_status_exporter.py + testing + deployment
```

### Week 4: Alert Integration + Polish
```
Day 1: Audit existing services
Day 2: Add AlertManager to services missing it
Day 3: Test alert flow end-to-end
Day 4: Documentation updates
Day 5: Final testing with historical data
```

---

## Verification Checklist

### Monitoring
- [ ] Gap detection finds known gaps
- [ ] Freshness checker alerts on stale data
- [ ] Coverage monitor catches missing predictions
- [ ] Execution monitor detects stuck processors
- [ ] Stall detector triggers on pipeline halts

### Validation
- [ ] Schedule validator catches missing pitchers
- [ ] Props validator catches missing lines
- [ ] Stats validator catches missing results
- [ ] Coverage validator catches incomplete predictions
- [ ] Analytics validator catches NULL features

### Publishing
- [ ] Predictions export to correct GCS path
- [ ] Best bets filter correctly
- [ ] Performance metrics accurate
- [ ] Pitcher profiles complete
- [ ] Results match predictions

### Alerting
- [ ] Alerts fire on failures
- [ ] Rate limiting prevents spam
- [ ] Backfill mode suppresses non-critical
- [ ] Slack messages formatted correctly
