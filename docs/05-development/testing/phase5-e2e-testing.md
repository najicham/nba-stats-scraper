# Phase 5 End-to-End Test Guide

This document describes how to run an end-to-end test of the Phase 5 Prediction Pipeline using mock data.

---

## Overview

The E2E test validates the complete prediction flow:

```
Coordinator → Pub/Sub → Worker → Feature Loading → Prediction Systems → BigQuery Write
```

### What Gets Tested

| Component | Validation |
|-----------|------------|
| Coordinator | Queries players, publishes to Pub/Sub |
| Worker | Receives requests, loads features, generates predictions |
| Feature Loading | Reads from `ml_feature_store_v2` |
| Prediction Systems | All 4 systems produce valid outputs |
| BigQuery Write | Predictions persisted to `player_prop_predictions` |

---

## Prerequisites

### Services Deployed

Ensure both Cloud Run services are deployed:

```bash
# Check service status
gcloud run services list --project=nba-props-platform --region=us-west2

# Expected services:
# - prediction-coordinator
# - prediction-worker
```

### Deploy if needed:

```bash
# Coordinator
./bin/predictions/deploy/deploy_prediction_coordinator.sh prod

# Worker
./bin/predictions/deploy/deploy_prediction_worker.sh prod
```

### BigQuery Tables

Required tables:
- `nba_analytics.upcoming_player_game_context` (us-west2)
- `nba_predictions.ml_feature_store_v2` (US)
- `nba_predictions.player_prop_predictions` (US)

---

## Step 1: Set Up Mock Data

### 1.1 Choose a Test Date

Use today's date or a recent date. The date must not be filtered out by early-exit checks.

```bash
# Set your test date
TEST_DATE="2025-11-25"
```

### 1.2 Insert Mock Players into upcoming_player_game_context

This table tells the coordinator which players to process.

```bash
bq query --use_legacy_sql=false --location=us-west2 "
INSERT INTO \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
(
  player_lookup, game_date, game_id, team_abbr, opponent_team_abbr,
  home_game, games_played_season, avg_minutes_per_game_last_7,
  points_avg_last_5, points_avg_last_10, usage_rate_last_10,
  days_rest, back_to_back, season, processed_at
)
VALUES
  ('lebron_james', '${TEST_DATE}', '0022400001', 'LAL', 'GSW', true, 20, 35.0, 26.5, 25.8, 28.5, 2, false, '2024-25', CURRENT_TIMESTAMP()),
  ('stephen_curry', '${TEST_DATE}', '0022400001', 'GSW', 'LAL', false, 20, 34.0, 28.2, 27.5, 30.2, 1, false, '2024-25', CURRENT_TIMESTAMP()),
  ('kevin_durant', '${TEST_DATE}', '0022400002', 'PHX', 'DEN', true, 18, 36.0, 29.1, 28.3, 29.8, 2, false, '2024-25', CURRENT_TIMESTAMP()),
  ('giannis_antetokounmpo', '${TEST_DATE}', '0022400003', 'MIL', 'BOS', false, 22, 35.5, 31.2, 30.5, 32.1, 1, true, '2024-25', CURRENT_TIMESTAMP()),
  ('luka_doncic', '${TEST_DATE}', '0022400004', 'DAL', 'LAC', true, 19, 37.0, 33.5, 32.8, 35.2, 3, false, '2024-25', CURRENT_TIMESTAMP()),
  ('nikola_jokic', '${TEST_DATE}', '0022400002', 'DEN', 'PHX', false, 21, 34.5, 26.8, 27.2, 27.5, 2, false, '2024-25', CURRENT_TIMESTAMP()),
  ('jayson_tatum', '${TEST_DATE}', '0022400003', 'BOS', 'MIL', true, 20, 36.5, 27.3, 26.9, 28.8, 1, false, '2024-25', CURRENT_TIMESTAMP()),
  ('damian_lillard', '${TEST_DATE}', '0022400003', 'MIL', 'BOS', false, 20, 35.0, 25.8, 26.2, 29.5, 1, true, '2024-25', CURRENT_TIMESTAMP()),
  ('anthony_davis', '${TEST_DATE}', '0022400001', 'LAL', 'GSW', true, 18, 34.0, 24.5, 25.1, 26.2, 2, false, '2024-25', CURRENT_TIMESTAMP()),
  ('devin_booker', '${TEST_DATE}', '0022400002', 'PHX', 'DEN', true, 21, 35.5, 27.8, 27.2, 28.5, 2, false, '2024-25', CURRENT_TIMESTAMP())
"
```

### 1.3 Insert Mock Features into ml_feature_store_v2

The worker loads features from this table to generate predictions.

```bash
bq query --use_legacy_sql=false --location=US "
INSERT INTO \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
(
  player_lookup, game_date, game_id, team_abbr, opponent_team_abbr,
  home_game, points_avg_last_5, points_avg_last_10, usage_rate_last_10,
  minutes_avg_last_5, fg_pct_last_10, days_rest, back_to_back,
  opponent_def_rating, opponent_pace, games_played_season,
  points_std_last_10, assists_avg_last_5, rebounds_avg_last_5,
  steals_avg_last_5, blocks_avg_last_5, turnovers_avg_last_5,
  three_pt_pct_last_10, ft_pct_last_10, plus_minus_avg_last_5,
  feature_count, data_source, feature_quality_score, processed_at
)
VALUES
  ('lebron_james', '${TEST_DATE}', '0022400001', 'LAL', 'GSW', true, 26.5, 25.8, 28.5, 35.2, 0.52, 2, false, 112.5, 102.3, 20, 5.2, 8.1, 7.5, 1.2, 0.8, 3.5, 0.38, 0.75, 4.2, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('stephen_curry', '${TEST_DATE}', '0022400001', 'GSW', 'LAL', false, 28.2, 27.5, 30.2, 34.5, 0.48, 1, false, 110.2, 101.5, 20, 6.1, 5.5, 4.2, 0.9, 0.3, 2.8, 0.42, 0.92, 5.5, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('kevin_durant', '${TEST_DATE}', '0022400002', 'PHX', 'DEN', true, 29.1, 28.3, 29.8, 36.2, 0.53, 2, false, 108.5, 100.2, 18, 4.8, 5.2, 6.8, 0.7, 1.5, 3.2, 0.40, 0.88, 6.2, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('giannis_antetokounmpo', '${TEST_DATE}', '0022400003', 'MIL', 'BOS', false, 31.2, 30.5, 32.1, 35.8, 0.58, 1, true, 105.8, 98.5, 22, 5.5, 5.8, 11.5, 1.1, 1.2, 3.8, 0.28, 0.68, 7.5, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('luka_doncic', '${TEST_DATE}', '0022400004', 'DAL', 'LAC', true, 33.5, 32.8, 35.2, 37.2, 0.47, 3, false, 109.2, 99.8, 19, 6.8, 9.2, 8.5, 1.5, 0.5, 4.2, 0.36, 0.78, 8.2, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('nikola_jokic', '${TEST_DATE}', '0022400002', 'DEN', 'PHX', false, 26.8, 27.2, 27.5, 34.8, 0.56, 2, false, 111.5, 101.2, 21, 4.2, 9.5, 12.2, 1.3, 0.9, 3.5, 0.35, 0.82, 9.5, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('jayson_tatum', '${TEST_DATE}', '0022400003', 'BOS', 'MIL', true, 27.3, 26.9, 28.8, 36.5, 0.46, 1, false, 107.2, 100.5, 20, 5.8, 4.8, 8.2, 1.0, 0.7, 2.9, 0.37, 0.85, 6.8, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('damian_lillard', '${TEST_DATE}', '0022400003', 'MIL', 'BOS', false, 25.8, 26.2, 29.5, 35.2, 0.44, 1, true, 107.2, 100.5, 20, 6.2, 7.2, 4.5, 0.8, 0.4, 3.2, 0.39, 0.92, 3.5, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('anthony_davis', '${TEST_DATE}', '0022400001', 'LAL', 'GSW', true, 24.5, 25.1, 26.2, 34.2, 0.55, 2, false, 112.5, 102.3, 18, 5.5, 3.2, 12.5, 1.4, 2.2, 2.5, 0.25, 0.80, 5.2, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP()),
  ('devin_booker', '${TEST_DATE}', '0022400002', 'PHX', 'DEN', true, 27.8, 27.2, 28.5, 35.8, 0.49, 2, false, 108.5, 100.2, 21, 5.2, 4.5, 4.8, 1.0, 0.3, 2.8, 0.38, 0.88, 4.8, 25, 'mock_test', CAST(85.0 AS NUMERIC), CURRENT_TIMESTAMP())
"
```

### 1.4 Verify Mock Data

```bash
# Check upcoming_player_game_context
bq query --use_legacy_sql=false --location=us-west2 "
SELECT player_lookup, game_date, team_abbr, avg_minutes_per_game_last_7
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '${TEST_DATE}'
"

# Check ml_feature_store_v2
bq query --use_legacy_sql=false --location=US "
SELECT player_lookup, game_date, feature_count, data_source
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date = '${TEST_DATE}'
"
```

---

## Step 2: Run the Test

### 2.1 Clear Any Existing Predictions (Optional)

```bash
bq query --use_legacy_sql=false --location=US "
DELETE FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '${TEST_DATE}'
"
```

### 2.2 Start a Prediction Batch

```bash
curl -s -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Content-Type: application/json" \
  -d "{\"game_date\": \"${TEST_DATE}\", \"force\": true}"
```

Expected response:
```json
{
  "batch_id": "batch_2025-11-25_1764125331",
  "status": "started",
  "published": 10,
  "total_requests": 10,
  "game_date": "2025-11-25",
  "summary": {
    "total_players": 10,
    "total_games": 6,
    "avg_projected_minutes": 32.5
  }
}
```

### 2.3 Monitor Progress

```bash
# Check batch status (replace BATCH_ID)
curl -s "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status?batch_id=BATCH_ID"

# Watch worker logs
gcloud run services logs read prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --limit=50
```

Look for these log messages:
- `Successfully generated 4 predictions for [player_name]`
- `Successfully wrote 4 predictions to BigQuery`

---

## Step 3: Verify Results

### 3.1 Count Predictions

```bash
bq query --use_legacy_sql=false --location=US "
SELECT
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT system_id) as systems
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '${TEST_DATE}'
"
```

Expected output:
```
+-------------------+----------------+---------+
| total_predictions | unique_players | systems |
+-------------------+----------------+---------+
|                40 |             10 |       4 |
+-------------------+----------------+---------+
```

### 3.2 View Sample Predictions

```bash
bq query --use_legacy_sql=false --location=US "
SELECT
  player_lookup,
  system_id,
  predicted_points,
  confidence_score,
  recommendation
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '${TEST_DATE}'
ORDER BY player_lookup, system_id
LIMIT 20
"
```

### 3.3 Validate All Systems Present

```bash
bq query --use_legacy_sql=false --location=US "
SELECT
  system_id,
  COUNT(*) as predictions,
  AVG(predicted_points) as avg_predicted,
  AVG(confidence_score) as avg_confidence
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '${TEST_DATE}'
GROUP BY system_id
ORDER BY system_id
"
```

Expected systems:
- `ensemble_v1`
- `moving_average`
- `xgboost_v1`
- `zone_matchup_v1`

---

## Step 4: Clean Up (Optional)

### Remove Mock Data

```bash
# Remove test predictions
bq query --use_legacy_sql=false --location=US "
DELETE FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '${TEST_DATE}'
"

# Remove mock features
bq query --use_legacy_sql=false --location=US "
DELETE FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date = '${TEST_DATE}' AND data_source = 'mock_test'
"

# Remove mock player context
bq query --use_legacy_sql=false --location=us-west2 "
DELETE FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '${TEST_DATE}'
"
```

---

## Troubleshooting

### "No players found"

**Cause**: Players don't meet `avg_minutes_per_game_last_7 >= 15` filter

**Fix**: Ensure mock data has `avg_minutes_per_game_last_7` >= 15

### "No features found"

**Cause**: No matching records in `ml_feature_store_v2`

**Fix**: Verify mock features match player_lookup, game_date, game_id

### "Error writing to BigQuery"

**Cause**: Schema mismatch (array vs string, missing fields)

**Fix**: Check worker logs for specific field errors. The format_prediction_for_bigquery function in worker.py should convert complex types to JSON strings.

### Worker Not Processing

**Cause**: Pub/Sub subscription not connected

**Fix**:
```bash
# Check subscription
gcloud pubsub subscriptions describe prediction-request-prod \
  --project=nba-props-platform

# Should show pushConfig pointing to worker URL
```

---

## Success Criteria

The E2E test passes if:

| Check | Expected |
|-------|----------|
| Batch starts | `status: "started"`, `published: 10` |
| Worker logs | "Successfully generated 4 predictions" for each player |
| Worker logs | "Successfully wrote 4 predictions to BigQuery" for each player |
| BigQuery count | 40 predictions (10 players × 4 systems) |
| Systems present | All 4: moving_average, zone_matchup_v1, xgboost_v1, ensemble_v1 |

---

## Test History

| Date | Result | Notes |
|------|--------|-------|
| 2025-11-25 | PASS | Initial E2E validation with mock data |

---

## Related Documentation

- [Phase 5 Deployment Guide](../deployment/06-phase5-prediction-deployment-plan.md)
- [Handoff: E2E Test Complete](../handoff/2025-11-25-phase5-e2e-test-complete.md)
- [Prediction Worker Code](../../predictions/worker/worker.py)
- [Prediction Coordinator Code](../../predictions/coordinator/coordinator.py)
