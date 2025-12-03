# Phase 5 Predictions - Operations Guide

**Last Updated:** 2025-12-02
**Purpose:** Operational guide for the prediction system
**Status:** Deployed (Coordinator + Workers)

---

## Overview

Phase 5 generates player points predictions using 5 ML models:

| System | Description | Maturity |
|--------|-------------|----------|
| `moving_average` | Simple baseline (L5, L10 averages) | Production |
| `zone_matchup_v1` | Shot zone vs defense matchup | Production |
| `similarity` | Similar player pattern matching | Production |
| `xgboost_v1` | ML model (currently mock) | Needs training |
| `ensemble` | Weighted combination | Production |

---

## Architecture

```
┌─────────────────────────────────────────┐
│           Prediction Coordinator         │
│  - Loads prop lines (which players)      │
│  - Loads ML features (Phase 4 data)      │
│  - Dispatches to workers                 │
└────────────────┬────────────────────────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
┌────────┐  ┌────────┐  ┌────────┐
│Worker 1│  │Worker 2│  │Worker 3│
│5 models│  │5 models│  │5 models│
└────────┘  └────────┘  └────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  nba_predictions.player_prop_predictions │
└─────────────────────────────────────────┘
```

---

## Cloud Run Services

### Prediction Coordinator

```bash
# Service info
gcloud run services describe prediction-coordinator \
  --project=nba-props-platform --region=us-west2

# View logs
gcloud run services logs read prediction-coordinator \
  --project=nba-props-platform --region=us-west2 --limit=50

# Service URL
https://prediction-coordinator-756957797294.us-west2.run.app
```

### Prediction Worker

```bash
# Service info
gcloud run services describe prediction-worker \
  --project=nba-props-platform --region=us-west2

# View logs
gcloud run services logs read prediction-worker \
  --project=nba-props-platform --region=us-west2 --limit=50
```

---

## Daily Operations

### Trigger Timing

Phase 5 is triggered by:
1. **Phase 4 completion** (via Pub/Sub `nba-phase4-precompute-complete`)
2. **Prop line changes** (real-time updates)
3. **Manual trigger** (for testing)

### Expected Output

| Metric | Expected Value |
|--------|---------------|
| Predictions per day | 100-450 (depends on games) |
| Systems per player | 5 |
| Processing time | 2-5 minutes |
| Confidence threshold | 65+ for OVER/UNDER |

### Check Predictions

```sql
-- Today's predictions
SELECT
  player_lookup,
  system_id,
  predicted_points,
  current_points_line,
  line_margin,
  confidence_score,
  recommendation
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
ORDER BY player_lookup, system_id;

-- Prediction summary
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as players,
  AVG(confidence_score) as avg_confidence,
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'PASS') as pass_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

---

## Prerequisites

Phase 5 requires:

1. **Phase 4 ML Feature Store** - `nba_predictions.ml_feature_store_v2`
2. **Prop Lines** - From odds scrapers
3. **Player Schedule** - Who's playing today

### Check Prerequisites

```sql
-- ML Feature Store ready?
SELECT COUNT(*) as feature_store_rows
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();

-- Prop lines available?
SELECT COUNT(DISTINCT player_lookup) as players_with_props
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date = CURRENT_DATE();
```

---

## Manual Trigger

### Via HTTP (for testing)

```bash
# Trigger coordinator
curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/generate" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2024-01-15"}'
```

### Via Pub/Sub (production pattern)

```bash
# Publish to trigger topic
gcloud pubsub topics publish nba-phase4-precompute-complete \
  --project=nba-props-platform \
  --message='{"game_date": "2024-01-15", "source": "manual_trigger"}'
```

---

## Troubleshooting

### No Predictions Generated

1. **Check Phase 4 data exists**
   ```sql
   SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
   WHERE game_date = CURRENT_DATE()
   ```
   - If 0: Phase 4 didn't run or failed

2. **Check prop lines exist**
   ```sql
   SELECT COUNT(DISTINCT player_lookup)
   FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
   WHERE game_date = CURRENT_DATE()
   ```
   - If 0: Prop scraper didn't run

3. **Check coordinator logs**
   ```bash
   gcloud run services logs read prediction-coordinator \
     --project=nba-props-platform --region=us-west2 --limit=100
   ```

### All Predictions are PASS

- **Cause:** Confidence scores below threshold (65)
- **Check:** Are features populated correctly?
  ```sql
  SELECT
    player_lookup,
    features,
    quality_score
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date = CURRENT_DATE()
  LIMIT 5
  ```
- **Likely issue:** Early season / bootstrap period with insufficient historical data

### Low Confidence Scores

- Normal for:
  - Early season (insufficient history)
  - Players with few games
  - Unusual matchups

- Investigate if:
  - All players have low confidence
  - Confidence suddenly dropped

---

## Performance

### Resource Usage

| Resource | Coordinator | Worker |
|----------|-------------|--------|
| Memory | 512Mi | 1Gi |
| CPU | 1 | 1 |
| Timeout | 300s | 300s |
| Concurrency | 1 | 10 |

### Scaling

- Coordinator: Single instance (orchestration)
- Workers: Auto-scale 0-10 based on load
- Typical: 3-5 workers during prediction generation

---

## Deployment

### Redeploy Coordinator

```bash
./bin/predictions/deploy/deploy_prediction_coordinator.sh
```

### Redeploy Worker

```bash
./bin/predictions/deploy/deploy_prediction_worker.sh
```

---

## Output Schema

Key fields in `player_prop_predictions`:

| Field | Type | Description |
|-------|------|-------------|
| `prediction_id` | STRING | Unique ID |
| `system_id` | STRING | Which model |
| `player_lookup` | STRING | Player identifier |
| `game_date` | DATE | Game date |
| `predicted_points` | FLOAT | Model prediction |
| `confidence_score` | FLOAT | 0-100 confidence |
| `recommendation` | STRING | OVER/UNDER/PASS |
| `current_points_line` | FLOAT | Vegas line |
| `line_margin` | FLOAT | Predicted - Line |

---

## Related Documentation

- [Daily Operations Runbook](../../02-operations/daily-operations-runbook.md)
- [Phase 4 Operations](../phase4-precompute/operations.md)
- [Validation System](../../07-monitoring/validation-system.md)
- [Processor Cards](../../06-reference/processor-cards/)
