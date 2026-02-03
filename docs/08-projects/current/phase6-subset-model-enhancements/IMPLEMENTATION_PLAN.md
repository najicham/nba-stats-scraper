# Phase 6 Enhancements: Subsets & Model Info

**Created**: 2026-02-02
**Status**: Planning
**Session**: 86

## Problem Statement

Phase 6 (Publishing & Exports) currently does not expose two major features to the website:
1. **Dynamic Subsets** - Signal-aware pick filtering system (Sessions 70-71)
2. **Model Attribution** - Model training details and metadata (Session 84)

The backend tracking exists but the website cannot access this data.

## Current State

### What Phase 6 Currently Exports
- `/tonight/all-players.json` - All predictions
- `/predictions/{date}.json` - All predictions by game
- `/best-bets/{date}.json` - Top 15-25 picks (basic edge threshold)
- `/systems/performance.json` - Rolling accuracy metrics
- `/live/{date}.json` - Live scores
- `/trends/*.json` - Various trend endpoints
- `/players/{lookup}.json` - Player profiles

### What's Missing
- ❌ No subset definitions or metadata
- ❌ No daily signal data (GREEN/YELLOW/RED)
- ❌ No subset-filtered picks
- ❌ No subset performance comparison
- ❌ Limited model metadata (no training details, file names, expected performance)
- ❌ No model attribution on predictions

## Solution Design

### New Endpoints to Create

#### 1. `/systems/subsets.json`
**Purpose**: List all available subsets with metadata
**Update frequency**: On subset definition changes (rare)
**Source tables**: `nba_predictions.dynamic_subset_definitions`

**Exporter**: `subset_definitions_exporter.py` (NEW)

**Sample output**:
```json
{
  "generated_at": "2026-02-02T10:00:00Z",
  "subsets": [
    {
      "subset_id": "v9_high_edge_top5",
      "subset_name": "V9 High Edge Top 5",
      "subset_description": "Top 5 ranked picks by composite score",
      "system_id": "catboost_v9",
      "selection_strategy": "RANKED",
      "top_n": 5,
      "min_edge": 5.0,
      "min_confidence": null,
      "signal_condition": "ANY",
      "is_active": true,
      "notes": "Recommended default"
    }
    // ... 8 more subsets
  ]
}
```

---

#### 2. `/signals/{date}.json`
**Purpose**: Daily signal metrics and status
**Update frequency**: Once per day after predictions generated
**Source tables**: `nba_predictions.daily_prediction_signals`

**Exporter**: `daily_signals_exporter.py` (NEW)

**Sample output**:
```json
{
  "game_date": "2026-02-02",
  "system_id": "catboost_v9",
  "signal_metrics": {
    "total_picks": 142,
    "high_edge_picks": 28,
    "premium_picks": 12,
    "pct_over": 32.4,
    "pct_under": 67.6,
    "avg_confidence": 0.68,
    "avg_edge": 2.3,
    "skew_category": "UNDER_HEAVY"
  },
  "signal_status": {
    "daily_signal": "GREEN",
    "signal_explanation": "Balanced market with 32% OVER picks. Historical 82% hit rate on GREEN days.",
    "confidence": "HIGH"
  },
  "signal_performance": {
    "green_days_historical_hr": 82.0,
    "yellow_days_historical_hr": 89.0,
    "red_days_historical_hr": 54.0,
    "sample_size_days": 47
  },
  "generated_at": "2026-02-02T14:30:00Z"
}
```

---

#### 3. `/subsets/{subset_id}/{date}.json`
**Purpose**: Picks from specific subset for a date
**Update frequency**: Once per day after predictions generated
**Source**: Query `player_prop_predictions` with subset filters + signal data

**Exporter**: `subset_picks_exporter.py` (NEW)

**Sample output**:
```json
{
  "game_date": "2026-02-02",
  "subset_id": "v9_high_edge_top5",
  "subset_name": "V9 High Edge Top 5",
  "generated_at": "2026-02-02T14:30:00Z",
  "daily_signal": "GREEN",
  "signal_matches": true,
  "metadata": {
    "total_picks": 5,
    "avg_edge": 6.8,
    "avg_confidence": 0.87,
    "avg_composite_score": 111.5,
    "overs": 2,
    "unders": 3
  },
  "picks": [
    {
      "rank": 1,
      "prediction_id": "abc123",
      "player_lookup": "lebronjames",
      "player_name": "LeBron James",
      "team": "LAL",
      "opponent": "BOS",
      "game_id": "0022600456",
      "predicted_points": 26.1,
      "line_value": 24.5,
      "edge": 1.6,
      "confidence_score": 0.92,
      "composite_score": 115.5,
      "recommendation": "OVER",
      "line_source": "ACTUAL_PROP",
      "sportsbook": "DRAFTKINGS"
    }
    // ... 4 more picks
  ]
}
```

---

#### 4. `/subsets/performance.json`
**Purpose**: Compare performance across all subsets
**Update frequency**: Daily
**Source**: `v_dynamic_subset_performance` view

**Exporter**: `subset_performance_exporter.py` (NEW)

**Sample output**:
```json
{
  "generated_at": "2026-02-02T10:00:00Z",
  "performance_windows": {
    "last_7_days": {
      "start_date": "2026-01-26",
      "end_date": "2026-02-01",
      "subsets": [
        {
          "subset_id": "v9_high_edge_top5",
          "picks": 35,
          "graded_picks": 32,
          "wins": 24,
          "losses": 8,
          "hit_rate": 75.0,
          "avg_edge": 6.2,
          "avg_confidence": 0.86,
          "roi_estimate": 9.1,
          "overs": 18,
          "unders": 14
        }
        // ... 8 more subsets
      ]
    },
    "last_30_days": { /* ... */ },
    "season": { /* ... */ }
  },
  "signal_breakdown": {
    "v9_high_edge_top5": {
      "green_days": {
        "picks": 89,
        "hit_rate": 82.0,
        "avg_edge": 6.1
      },
      "yellow_days": {
        "picks": 42,
        "hit_rate": 76.8,
        "avg_edge": 6.3
      },
      "red_days": {
        "picks": 16,
        "hit_rate": 56.3,
        "avg_edge": 6.5
      }
    }
    // ... other subsets
  }
}
```

---

#### 5. `/systems/models.json`
**Purpose**: Model registry with training details
**Update frequency**: On model deployment (monthly)
**Source**: Code-based (prediction_systems/*.py TRAINING_INFO) + BigQuery

**Exporter**: `model_registry_exporter.py` (NEW)

**Sample output**:
```json
{
  "generated_at": "2026-02-02T10:00:00Z",
  "production_model": "catboost_v9",
  "models": [
    {
      "system_id": "catboost_v9",
      "model_name": "CatBoost V9 - Current Season",
      "model_file_name": "catboost_v9_feb_02_retrain.cbm",
      "model_version": "v9.0",
      "status": "PRODUCTION",
      "deployed_at": "2026-02-02T10:15:00Z",
      "training_info": {
        "training_start_date": "2025-11-02",
        "training_end_date": "2026-01-31",
        "training_days": 91,
        "training_samples": 180000,
        "evaluation_samples": 8500,
        "approach": "current_season_only",
        "feature_count": 33,
        "feature_version": "v2_33features"
      },
      "expected_performance": {
        "mae": 4.12,
        "high_edge_hit_rate": 74.6,
        "premium_hit_rate": 56.5
      },
      "retraining_schedule": {
        "frequency": "MONTHLY",
        "next_retrain_date": "2026-03-01",
        "strategy": "rolling_90_day_window"
      },
      "model_path": "gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm"
    },
    {
      "system_id": "ensemble_v1",
      "model_name": "Ensemble V1",
      "status": "PRODUCTION",
      "deployed_at": "2025-12-15T08:00:00Z"
      // ... more fields
    }
  ]
}
```

---

### Modifications to Existing Endpoints

#### Enhance `/systems/performance.json`
**Exporter**: `system_performance_exporter.py` (MODIFY)

Add model metadata and tier breakdown to each system:

```json
{
  "systems": [
    {
      "system_id": "catboost_v9",
      "display_name": "CatBoost V9",
      // ... existing fields (win_rate, mae, etc.) ...

      // NEW: Model metadata
      "model_info": {
        "model_file": "catboost_v9_feb_02_retrain.cbm",
        "trained_at": "2026-02-02T10:15:00Z",
        "training_period": "2025-11-02 to 2026-01-31",
        "expected_mae": 4.12,
        "expected_hit_rate": 74.6,
        "feature_count": 33
      },

      // NEW: Tier breakdown
      "tier_breakdown": {
        "premium": {
          "filter_description": "confidence >= 92% AND edge >= 3",
          "picks": 84,
          "hit_rate": 56.5,
          "avg_edge": 4.8,
          "mae": 3.2
        },
        "high_edge": {
          "filter_description": "edge >= 5 (any confidence)",
          "picks": 142,
          "hit_rate": 72.2,
          "avg_edge": 6.4,
          "mae": 3.8
        },
        "all_predictions": {
          "picks": 847,
          "hit_rate": 56.4,
          "avg_edge": 2.1,
          "mae": 4.18
        }
      }
    }
  ]
}
```

---

#### Add Model Attribution to `/predictions/{date}.json`
**Exporter**: `predictions_exporter.py` (MODIFY)

Add to each prediction object:

```json
{
  "predictions": [
    {
      // ... existing fields ...

      // NEW: Model attribution (from Session 84 fields)
      "model_attribution": {
        "model_file_name": "catboost_v9_feb_02_retrain.cbm",
        "model_trained_at": "2026-02-02T10:15:00Z",
        "training_start_date": "2025-11-02",
        "training_end_date": "2026-01-31",
        "model_expected_mae": 4.12,
        "model_expected_hit_rate": 74.6,
        "build_commit_sha": "a1b2c3d",
        "deployment_revision": "prediction-worker-00042-abc"
      }
    }
  ]
}
```

---

#### Add Model Attribution to `/best-bets/{date}.json`
**Exporter**: `best_bets_exporter.py` (MODIFY)

Same model_attribution fields as predictions export.

---

## Implementation Steps

### Phase 1: Subset Infrastructure (Priority 1)

**Files to create:**
1. `data_processors/publishing/subset_definitions_exporter.py`
2. `data_processors/publishing/daily_signals_exporter.py`
3. `data_processors/publishing/subset_picks_exporter.py`
4. `data_processors/publishing/subset_performance_exporter.py`

**Orchestration changes:**
- Add 4 new exporters to `orchestration/cloud_functions/phase6_export/main.py`
- Trigger daily after predictions complete

**Testing:**
```bash
# Test individual exporters
PYTHONPATH=. python -c "
from data_processors.publishing.subset_definitions_exporter import SubsetDefinitionsExporter
exporter = SubsetDefinitionsExporter()
exporter.export('2026-02-02')
"

# Verify GCS output
gsutil ls gs://nba-props-platform-api/v1/systems/subsets.json
gsutil ls gs://nba-props-platform-api/v1/signals/2026-02-02.json
gsutil ls gs://nba-props-platform-api/v1/subsets/v9_high_edge_top5/2026-02-02.json
gsutil ls gs://nba-props-platform-api/v1/subsets/performance.json
```

---

### Phase 2: Model Metadata (Priority 2)

**Files to create:**
1. `data_processors/publishing/model_registry_exporter.py`

**Files to modify:**
1. `data_processors/publishing/system_performance_exporter.py` (add model_info, tier_breakdown)
2. `data_processors/publishing/predictions_exporter.py` (add model_attribution)
3. `data_processors/publishing/best_bets_exporter.py` (add model_attribution)

**Testing:**
```bash
# Test model registry export
PYTHONPATH=. python -c "
from data_processors.publishing.model_registry_exporter import ModelRegistryExporter
exporter = ModelRegistryExporter()
exporter.export('2026-02-02')
"

# Verify GCS output
gsutil cat gs://nba-props-platform-api/v1/systems/models.json | jq '.models[0].training_info'
gsutil cat gs://nba-props-platform-api/v1/systems/performance.json | jq '.systems[0].model_info'
gsutil cat gs://nba-props-platform-api/v1/predictions/2026-02-02.json | jq '.predictions[0].model_attribution'
```

---

### Phase 3: Integration & Testing

**End-to-end flow:**
1. Run predictions for a test date
2. Verify Phase 5 completion
3. Trigger Phase 6 export
4. Check all new endpoints exist in GCS
5. Validate JSON structure matches specs above

**Validation queries:**
```bash
# Check all subset endpoints exist
for subset in v9_high_edge_top5 v9_high_edge_balanced v9_premium_safe; do
  gsutil ls gs://nba-props-platform-api/v1/subsets/$subset/2026-02-02.json
done

# Validate signal data
gsutil cat gs://nba-props-platform-api/v1/signals/2026-02-02.json | jq '.signal_status.daily_signal'

# Check model info added to performance
gsutil cat gs://nba-props-platform-api/v1/systems/performance.json | jq '.systems[] | select(.system_id == "catboost_v9") | .model_info'
```

---

## Database Sources

### Subsets Data

**Tables:**
- `nba_predictions.dynamic_subset_definitions` - Subset metadata
- `nba_predictions.daily_prediction_signals` - Signal metrics per day
- `nba_predictions.player_prop_predictions` - Raw predictions (filter by subset criteria)

**Views:**
- `nba_predictions.v_dynamic_subset_performance` - Pre-aggregated subset performance

**Query patterns:**
```sql
-- Get subset definitions
SELECT * FROM nba_predictions.dynamic_subset_definitions
WHERE is_active = TRUE
ORDER BY subset_id;

-- Get today's signal
SELECT * FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9';

-- Get subset picks (example: v9_high_edge_top5)
SELECT p.*,
  (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score
FROM nba_predictions.player_prop_predictions p
WHERE p.game_date = CURRENT_DATE()
  AND p.system_id = 'catboost_v9'
  AND p.is_active = TRUE
  AND ABS(p.predicted_points - p.current_points_line) >= 5
ORDER BY composite_score DESC
LIMIT 5;

-- Get subset performance
SELECT * FROM nba_predictions.v_dynamic_subset_performance
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY subset_id, game_date;
```

---

### Model Data

**Tables:**
- `nba_predictions.player_prop_predictions` - Has model attribution fields (Session 84)
  - `model_file_name`
  - `model_training_start_date`
  - `model_training_end_date`
  - `model_expected_mae`
  - `model_expected_hit_rate`
  - `model_trained_at`

**Code sources:**
- `predictions/worker/prediction_systems/catboost_v9.py` - TRAINING_INFO dict
- `predictions/worker/prediction_systems/ensemble_v1.py` - Ensemble metadata

**Query patterns:**
```sql
-- Get model attribution for today's predictions
SELECT DISTINCT
  system_id,
  model_file_name,
  model_training_start_date,
  model_training_end_date,
  model_expected_mae,
  model_expected_hit_rate,
  model_trained_at
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE;

-- Get tier breakdown
SELECT
  system_id,
  'premium' as tier,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(pa.prediction_correct = TRUE) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(p.predicted_points - p.current_points_line)), 1) as avg_edge
FROM nba_predictions.player_prop_predictions p
LEFT JOIN nba_predictions.prediction_accuracy pa USING (prediction_id)
WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND p.confidence_score >= 0.92
  AND ABS(p.predicted_points - p.current_points_line) >= 3
GROUP BY system_id;
```

---

## Frontend Integration Notes

### Subset Display Examples

**Homepage - "Today's Best Bets" Section:**
```javascript
// Fetch subset picks
const response = await fetch('https://api.nba-props.com/v1/subsets/v9_high_edge_top5/2026-02-02.json');
const data = await response.json();

// Display signal indicator
<SignalBadge signal={data.daily_signal} /> // GREEN/YELLOW/RED

// Render picks
data.picks.map(pick => (
  <PickCard
    rank={pick.rank}
    player={pick.player_name}
    team={pick.team}
    prediction={pick.predicted_points}
    line={pick.line_value}
    edge={pick.edge}
    confidence={pick.confidence_score}
    recommendation={pick.recommendation}
  />
))
```

**Subset Comparison Page:**
```javascript
// Fetch performance data
const response = await fetch('https://api.nba-props.com/v1/subsets/performance.json');
const data = await response.json();

// Render comparison table
<SubsetComparisonTable>
  {data.performance_windows.last_30_days.subsets.map(subset => (
    <tr>
      <td>{subset.subset_id}</td>
      <td>{subset.hit_rate}%</td>
      <td>{subset.picks}</td>
      <td>{subset.avg_edge}</td>
      <td>{subset.roi_estimate}%</td>
    </tr>
  ))}
</SubsetComparisonTable>
```

---

### Model Display Examples

**Model Info Card:**
```javascript
// Fetch model registry
const response = await fetch('https://api.nba-props.com/v1/systems/models.json');
const data = await response.json();
const model = data.models.find(m => m.system_id === 'catboost_v9');

<ModelInfoCard>
  <h3>{model.model_name}</h3>
  <p>Status: <StatusBadge status={model.status} /></p>
  <p>Deployed: {formatDate(model.deployed_at)}</p>
  <p>Training Period: {model.training_info.training_start_date} to {model.training_info.training_end_date}</p>
  <p>Expected MAE: {model.expected_performance.mae} points</p>
  <p>Expected Hit Rate: {model.expected_performance.high_edge_hit_rate}%</p>
  <p>Next Retrain: {model.retraining_schedule.next_retrain_date}</p>
</ModelInfoCard>
```

**Prediction Card with Model Attribution:**
```javascript
// Fetch predictions
const response = await fetch('https://api.nba-props.com/v1/predictions/2026-02-02.json');
const prediction = response.data.predictions[0];

<PredictionCard>
  {/* ... prediction details ... */}

  <ModelAttribution>
    <small>
      Generated by: {prediction.model_attribution.model_file_name}<br/>
      Model trained: {formatDate(prediction.model_attribution.model_trained_at)}<br/>
      Expected accuracy: {prediction.model_attribution.model_expected_hit_rate}%
    </small>
  </ModelAttribution>
</PredictionCard>
```

---

## Success Metrics

### Functional Requirements
- [ ] All 5 new endpoints successfully export to GCS
- [ ] Modified endpoints include new fields
- [ ] Export runs automatically after Phase 5 completion
- [ ] JSON structure validates against examples above
- [ ] All subset IDs (9 total) have picks exported
- [ ] Signal data matches BigQuery source
- [ ] Model attribution fields populated from Session 84 work

### Data Quality
- [ ] Subset picks match database query results
- [ ] Signal calculations (pct_over, daily_signal) are correct
- [ ] Performance metrics match v_dynamic_subset_performance view
- [ ] Model file names match deployed models
- [ ] Tier breakdowns (premium, high-edge) match hit rate standards

### Performance
- [ ] All exports complete within 5 minutes
- [ ] GCS upload latency < 10 seconds per file
- [ ] No BigQuery quota errors
- [ ] Circuit breaker doesn't trip on normal operation

---

## Rollback Plan

If issues arise:

1. **Disable new exporters** in Phase 6 orchestrator:
   ```python
   # In orchestration/cloud_functions/phase6_export/main.py
   # Comment out new exporters temporarily
   # exporters = [
   #     SubsetDefinitionsExporter(),
   #     DailySignalsExporter(),
   #     ...
   # ]
   ```

2. **Revert modified exporters** using git:
   ```bash
   git checkout HEAD~1 -- data_processors/publishing/system_performance_exporter.py
   git checkout HEAD~1 -- data_processors/publishing/predictions_exporter.py
   git checkout HEAD~1 -- data_processors/publishing/best_bets_exporter.py
   ```

3. **Redeploy Phase 6 function**:
   ```bash
   gcloud functions deploy phase6-export \
     --source orchestration/cloud_functions/phase6_export \
     --runtime python311 \
     --region us-west2
   ```

---

## Documentation Updates Needed

After implementation:

1. **Update CLAUDE.md** - Add Phase 6 subset/model endpoints to quick reference
2. **Create Phase 6 runbook** - `docs/02-operations/phase6-export-runbook.md`
3. **Update API documentation** - Document new endpoints for frontend team
4. **Session handoff** - Document implementation in Session 86 handoff

---

## Questions for Clarification

Before implementation, decide:

1. **Subset export scope**: Export all 9 subsets or just top 3-4 most popular?
2. **Historical depth**: How many days of `/signals/{date}.json` to backfill?
3. **Cache TTL**: What cache headers for new endpoints?
   - Subsets performance: 1 hour?
   - Daily signals: 5 minutes?
   - Model registry: 1 day?
4. **Model info source**: Pull from code (TRAINING_INFO dicts) or BigQuery only?
5. **Tier definitions**: Hardcode premium/high-edge filters or make configurable?

---

## Related Sessions & Documentation

**Subset System:**
- Session 70-71: Pre-game signals and dynamic subsets implementation
- `docs/08-projects/current/subset-pick-system/`
- `docs/08-projects/current/pre-game-signals-strategy/`
- `/.claude/skills/subset-picks/`
- `/.claude/skills/subset-performance/`

**Model Attribution:**
- Session 84: Model attribution tracking fields added
- `docs/08-projects/current/model-attribution-tracking/`

**Phase 6 Current:**
- `data_processors/publishing/` - Existing exporters
- `orchestration/cloud_functions/phase6_export/` - Export orchestration
