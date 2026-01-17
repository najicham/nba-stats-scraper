# MLB Multi-Model Prediction Architecture

**Version**: 2.0.0
**Status**: ✅ Ready for Deployment

## Quick Start

### 1. Run BigQuery Migration
```bash
cd /home/naji/code/nba-stats-scraper

# Add system_id column and backfill historical data
bq query --use_legacy_sql=false < schemas/bigquery/mlb_predictions/migration_add_system_id.sql

# Create monitoring views
bq query --use_legacy_sql=false < schemas/bigquery/mlb_predictions/multi_system_views.sql
```

### 2. Deploy (Recommended: Start with Phase 1)
```bash
# Phase 1: V1 Baseline only (safe mode)
./scripts/deploy_mlb_multi_model.sh phase1

# After validation, enable all systems
./scripts/deploy_mlb_multi_model.sh phase3
```

### 3. Validate Deployment
```bash
# Get service URL from deployment output, then validate
python3 scripts/validate_mlb_multi_model.py \
  --service-url https://mlb-prediction-worker-XXX.run.app \
  --project-id nba-props-platform
```

### 4. Monitor System Health
```bash
# Check daily coverage
bq query "SELECT * FROM \`nba-props-platform.mlb_predictions.daily_coverage\` WHERE game_date = CURRENT_DATE()"

# Check system performance
bq query "SELECT * FROM \`nba-props-platform.mlb_predictions.system_performance\`"

# Check system agreement
bq query "SELECT * FROM \`nba-props-platform.mlb_predictions.system_agreement\` WHERE game_date = CURRENT_DATE()"
```

## Architecture Overview

```
predictions/mlb/
├── base_predictor.py              # Abstract base class
├── prediction_systems/            # All prediction systems
│   ├── v1_baseline_predictor.py   # V1.4 (25 features)
│   ├── v1_6_rolling_predictor.py  # V1.6 (35 features)
│   └── ensemble_v1.py             # Weighted ensemble
├── worker.py                      # Multi-system orchestration
├── config.py                      # System configuration
└── pitcher_strikeouts_predictor.py # Legacy (keep for compatibility)
```

## Active Systems

| System ID | Description | Features | Weight |
|-----------|-------------|----------|--------|
| `v1_baseline` | V1.4 baseline model | 25 | 30% in ensemble |
| `v1_6_rolling` | V1.6 with statcast + BP | 35 | 50% in ensemble |
| `ensemble_v1` | Weighted average | N/A | N/A |

## Configuration

### Environment Variables
```bash
# Active systems (comma-separated)
export MLB_ACTIVE_SYSTEMS=v1_baseline,v1_6_rolling,ensemble_v1

# Model paths
export MLB_V1_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json
export MLB_V1_6_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json

# Ensemble weights
export MLB_ENSEMBLE_V1_WEIGHT=0.3
export MLB_ENSEMBLE_V1_6_WEIGHT=0.5
```

## Testing

### Run Unit Tests
```bash
# Test base predictor
pytest tests/mlb/test_base_predictor.py -v

# Test ensemble
pytest tests/mlb/prediction_systems/test_ensemble_v1.py -v

# Run all MLB tests
pytest tests/mlb/ -v
```

### Manual Testing
```bash
# Test health endpoint
curl https://mlb-prediction-worker-XXX.run.app/

# Test batch predictions
curl -X POST https://mlb-prediction-worker-XXX.run.app/predict-batch \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-20", "write_to_bigquery": false}'
```

## Key Features

✅ **Multiple Systems**: V1, V1.6, and Ensemble run concurrently
✅ **Multiple Rows per Pitcher**: One row per system in BigQuery
✅ **Circuit Breaker**: Individual system failures don't cascade
✅ **Ensemble Logic**: Weighted average with agreement bonus
✅ **Backward Compatible**: Existing API consumers still work
✅ **Easy Extensibility**: Add V2.0+ by creating new system class

## Data Model

### Before (Single-Model)
```
gerrit-cole on 2026-01-15 → 1 row (V1.6)
```

### After (Multi-Model)
```
gerrit-cole on 2026-01-15 → 3 rows
  - system_id: v1_baseline   (6.0 K predicted)
  - system_id: v1_6_rolling  (6.8 K predicted)
  - system_id: ensemble_v1   (6.5 K predicted, weighted)
```

## Rollback

### Quick Rollback (V1 only)
```bash
./scripts/deploy_mlb_multi_model.sh rollback
```

### Emergency Rollback (Previous Code)
```bash
git checkout HEAD~1 predictions/mlb/worker.py
gcloud run deploy mlb-prediction-worker
```

## Monitoring

### Critical Alerts
- ❗ All systems failing (zero predictions)
- ❗ API 500 errors > 5%
- ❗ Zero predictions written to BigQuery

### Warning Alerts
- ⚠️ Single system circuit breaker open
- ⚠️ System agreement < 80%
- ⚠️ Ensemble deviates > 2 K from V1.6

### Daily Checks
```sql
-- Ensure all systems ran
SELECT * FROM `nba-props-platform.mlb_predictions.daily_coverage`
WHERE game_date = CURRENT_DATE();
-- Expected: min_systems_per_pitcher = max_systems_per_pitcher = 3

-- Check system performance
SELECT * FROM `nba-props-platform.mlb_predictions.system_performance`;

-- Check system agreement
SELECT * FROM `nba-props-platform.mlb_predictions.system_agreement`
WHERE game_date = CURRENT_DATE();
```

## Success Criteria

- ✅ All 3 systems running concurrently
- ✅ Zero breaking changes to API
- ✅ Circuit breaker prevents cascade failures
- ⏳ Ensemble win rate ≥ V1.6 baseline (82.3%) - measure after 30 days
- ⏳ Zero data loss during migration - verify after deployment

## Documentation

- **Full Implementation Guide**: `MULTI_MODEL_IMPLEMENTATION.md`
- **Session Handoff**: `docs/handoffs/session_80_mlb_multi_model_implementation.md`
- **Deployment Script**: `scripts/deploy_mlb_multi_model.sh`
- **Validation Script**: `scripts/validate_mlb_multi_model.py`

## Support

### Check Logs
```bash
gcloud logging tail \
  --project=nba-props-platform \
  --resource-type=cloud_run_revision \
  --filter='resource.labels.service_name=mlb-prediction-worker'
```

### Common Issues

**Issue**: Systems not all running
**Fix**: Check `MLB_ACTIVE_SYSTEMS` environment variable

**Issue**: system_id is NULL in BigQuery
**Fix**: Run migration: `bq query < schemas/bigquery/mlb_predictions/migration_add_system_id.sql`

**Issue**: Views not found
**Fix**: Create views: `bq query < schemas/bigquery/mlb_predictions/multi_system_views.sql`

**Issue**: Ensemble predictions missing
**Fix**: Ensure `ensemble_v1` in `MLB_ACTIVE_SYSTEMS`

## Next Steps

1. ✅ Implementation complete
2. ⏳ Run BigQuery migration
3. ⏳ Deploy to staging (Phase 1)
4. ⏳ Validate V1 baseline matches legacy
5. ⏳ Enable all systems (Phase 3)
6. ⏳ Monitor for 7 days
7. ⏳ Make `system_id` NOT NULL after 30 days

---

**Last Updated**: 2026-01-17
**Version**: 2.0.0
**Status**: ✅ Ready for Deployment
