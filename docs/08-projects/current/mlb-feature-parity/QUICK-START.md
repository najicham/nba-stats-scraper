# MLB Feature Parity - Quick Start Guide

**For the next session**: Everything you need to deploy and use the new MLB infrastructure.

---

## What Was Built

21 files implementing monitoring, validation, publishing, and alerting for MLB:
- **5 monitoring modules** (gap detection, freshness, coverage, stall detection)
- **4 validators** (schedule, props, prediction coverage)
- **5 exporters** (predictions, best bets, performance, results)
- **4 services updated** (AlertManager integration)

---

## Quick Test Commands

```bash
# Test all monitors with historical data
PYTHONPATH=. python monitoring/mlb/mlb_gap_detection.py --date 2025-08-15 --dry-run
PYTHONPATH=. python monitoring/mlb/mlb_freshness_checker.py --date 2025-08-15 --dry-run
PYTHONPATH=. python monitoring/mlb/mlb_prediction_coverage.py --date 2025-08-15 --dry-run
PYTHONPATH=. python monitoring/mlb/mlb_stall_detector.py --date 2025-08-15 --dry-run

# Test exporters
PYTHONPATH=. python data_processors/publishing/mlb/mlb_predictions_exporter.py --date 2025-08-15 --dry-run
PYTHONPATH=. python data_processors/publishing/mlb/mlb_best_bets_exporter.py --date 2025-08-15 --dry-run

# Test validators
PYTHONPATH=. python validation/validators/mlb/mlb_schedule_validator.py --start-date 2025-08-01 --end-date 2025-08-31
```

---

## Priority 1: Deploy Monitoring (1-2 hours)

### Step 1: Create Cloud Run Jobs

```bash
# Gap Detection (daily)
gcloud run jobs create mlb-gap-detection \
  --image gcr.io/nba-props-platform/mlb-monitoring:latest \
  --command python \
  --args "monitoring/mlb/mlb_gap_detection.py,--date,\$(date -d 'yesterday' +%Y-%m-%d)" \
  --region us-west2 \
  --schedule "0 8 * * *" \
  --timezone "America/New_York"

# Freshness Checker (every 2 hours)
gcloud run jobs create mlb-freshness-checker \
  --image gcr.io/nba-props-platform/mlb-monitoring:latest \
  --command python \
  --args "monitoring/mlb/mlb_freshness_checker.py,--date,\$(date +%Y-%m-%d)" \
  --region us-west2 \
  --schedule "0 */2 * * *"

# Prediction Coverage (2 hours before games)
gcloud run jobs create mlb-prediction-coverage \
  --image gcr.io/nba-props-platform/mlb-monitoring:latest \
  --command python \
  --args "monitoring/mlb/mlb_prediction_coverage.py,--date,\$(date +%Y-%m-%d)" \
  --region us-west2 \
  --schedule "0 15 * * *"  # 3 PM ET

# Stall Detector (hourly during games)
gcloud run jobs create mlb-stall-detector \
  --image gcr.io/nba-props-platform/mlb-monitoring:latest \
  --command python \
  --args "monitoring/mlb/mlb_stall_detector.py,--date,\$(date +%Y-%m-%d)" \
  --region us-west2 \
  --schedule "0 * * * *"
```

### Step 2: Verify Alerts Work

```bash
# Trigger a test alert by running monitor on bad date
python monitoring/mlb/mlb_freshness_checker.py --date 2020-01-01

# Should send Slack alert if configured
```

---

## Priority 2: Deploy Exporters (1 hour)

### Step 1: Create Export Jobs

```bash
# Predictions Exporter (1 hour before games)
gcloud run jobs create mlb-predictions-exporter \
  --image gcr.io/nba-props-platform/mlb-exporters:latest \
  --command python \
  --args "data_processors/publishing/mlb/mlb_predictions_exporter.py,--date,\$(date +%Y-%m-%d)" \
  --region us-west2 \
  --schedule "0 16 * * *"  # 4 PM ET

# Best Bets Exporter
gcloud run jobs create mlb-best-bets-exporter \
  --image gcr.io/nba-props-platform/mlb-exporters:latest \
  --command python \
  --args "data_processors/publishing/mlb/mlb_best_bets_exporter.py,--date,\$(date +%Y-%m-%d)" \
  --region us-west2 \
  --schedule "0 16 * * *"

# System Performance Exporter (daily morning)
gcloud run jobs create mlb-system-performance-exporter \
  --image gcr.io/nba-props-platform/mlb-exporters:latest \
  --command python \
  --args "data_processors/publishing/mlb/mlb_system_performance_exporter.py,--lookback-days,30" \
  --region us-west2 \
  --schedule "0 6 * * *"

# Results Exporter (nightly)
gcloud run jobs create mlb-results-exporter \
  --image gcr.io/nba-props-platform/mlb-exporters:latest \
  --command python \
  --args "data_processors/publishing/mlb/mlb_results_exporter.py,--date,\$(date -d 'yesterday' +%Y-%m-%d)" \
  --region us-west2 \
  --schedule "0 2 * * *"
```

### Step 2: Test GCS Output

```bash
# Run exporter without --dry-run
python data_processors/publishing/mlb/mlb_predictions_exporter.py --date 2025-08-15

# Verify file in GCS
gsutil cat gs://nba-props-platform-api/mlb/predictions/2025-08-15.json
```

---

## Priority 3: Create Validator Configs (30 minutes)

### validation/configs/mlb/mlb_schedule.yaml

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
    reference_table: mlb_raw.mlb_schedule
    match_field: game_date
    severity: error

  field_validation:
    target_table: mlb_raw.mlb_schedule
    required_not_null:
      - game_pk
      - game_date
      - home_team
      - away_team
      - home_probable_pitcher_name
      - away_probable_pitcher_name
    severity: error
```

### validation/configs/mlb/mlb_pitcher_props.yaml

```yaml
processor:
  name: mlb_pitcher_props
  type: raw
  table: mlb_raw.bp_pitcher_props
  partition_required: true
  partition_field: game_date
  layers: [bigquery]

bigquery_validations:
  enabled: true
  completeness:
    target_table: mlb_raw.bp_pitcher_props
    reference_table: mlb_raw.mlb_schedule
    match_field: game_date
    min_coverage_pct: 70
    severity: warning

  field_validation:
    target_table: mlb_raw.bp_pitcher_props
    required_not_null:
      - game_date
      - player_lookup
      - market_name
      - over_line
    severity: error
```

### validation/configs/mlb/mlb_prediction_coverage.yaml

```yaml
processor:
  name: mlb_prediction_coverage
  type: predictions
  table: mlb_predictions.pitcher_strikeouts
  partition_required: true
  partition_field: game_date
  layers: [bigquery]

bigquery_validations:
  enabled: true
  completeness:
    target_table: mlb_predictions.pitcher_strikeouts
    reference_table: mlb_raw.bp_pitcher_props
    match_field: game_date
    min_coverage_pct: 90
    severity: error

  field_validation:
    target_table: mlb_predictions.pitcher_strikeouts
    required_not_null:
      - pitcher_lookup
      - predicted_strikeouts
      - confidence
      - recommendation
    severity: error
```

---

## AlertManager Configuration

### Environment Variables (Already Integrated)

```bash
# In Cloud Run service configuration, add:
BACKFILL_MODE=false  # Set true during historical backfills
SLACK_WEBHOOK_URL=<secret>  # From Secret Manager
ALERT_RECIPIENTS=your-email@example.com
```

### Alert Categories Created

- `mlb_analytics_failure` - Analytics processor errors
- `mlb_precompute_failure` - Precompute processor errors
- `mlb_grading_failure` - Grading processor errors
- `mlb_prediction_failure` - Prediction worker errors
- `mlb_processing_gap` - Gap detection alerts
- `mlb_data_freshness` - Freshness checker alerts
- `mlb_prediction_coverage` - Coverage monitor alerts
- `mlb_pipeline_stall` - Stall detector alerts

---

## Common Issues & Fixes

### Issue: "Bucket does not exist" in gap detection
**Fix**: Expected when running locally. Will work in Cloud Run with proper service account.

### Issue: "Unrecognized name: scraped_at"
**Fix**: Already fixed - we use `created_at` instead.

### Issue: Validators not found
**Fix**: Create YAML configs in `validation/configs/mlb/` (templates above).

### Issue: GCS permission denied
**Fix**: Service account needs `roles/storage.objectAdmin` on bucket.

---

## File Locations Reference

```
monitoring/mlb/
├── __init__.py
├── mlb_gap_detection.py
├── mlb_freshness_checker.py
├── mlb_prediction_coverage.py
└── mlb_stall_detector.py

validation/validators/mlb/
├── __init__.py
├── mlb_schedule_validator.py
├── mlb_pitcher_props_validator.py
└── mlb_prediction_coverage_validator.py

validation/configs/mlb/  # <-- CREATE THESE
├── mlb_schedule.yaml
├── mlb_pitcher_props.yaml
└── mlb_prediction_coverage.yaml

data_processors/publishing/mlb/
├── __init__.py
├── mlb_predictions_exporter.py
├── mlb_best_bets_exporter.py
├── mlb_system_performance_exporter.py
└── mlb_results_exporter.py

# Services with AlertManager integration:
data_processors/analytics/mlb/main_mlb_analytics_service.py
data_processors/precompute/mlb/main_mlb_precompute_service.py
data_processors/grading/mlb/main_mlb_grading_service.py
predictions/mlb/worker.py
```

---

## Success Criteria

- [ ] All monitors run successfully on scheduler
- [ ] Slack alerts arrive when issues detected
- [ ] Exporters write to GCS successfully
- [ ] Validators run without errors
- [ ] AlertManager rate limiting prevents spam during backfills

---

## Need Help?

See full documentation:
- `docs/09-handoff/2026-01-16-SESSION-70-MLB-FEATURE-PARITY-HANDOFF.md`
- `docs/08-projects/current/mlb-feature-parity/GAP-ANALYSIS.md`
- `docs/08-projects/current/mlb-feature-parity/IMPLEMENTATION-PLAN.md`
