# Prediction Quality System - Implementation Guide

**Session 95 - 2026-02-03**

This document details the implementation of the "Predict Once, Never Replace" prediction quality system.

---

## Table of Contents

1. [Problem Summary](#problem-summary)
2. [Design Philosophy](#design-philosophy)
3. [System Components](#system-components)
4. [Quality Gate Logic](#quality-gate-logic)
5. [Schedule Design](#schedule-design)
6. [Alerting System](#alerting-system)
7. [Data Flow](#data-flow)
8. [Configuration](#configuration)
9. [Deployment](#deployment)
10. [Monitoring](#monitoring)
11. [Troubleshooting](#troubleshooting)

---

## Problem Summary

### What Happened (Feb 2, 2026)

1. **Predictions created too late**: 4:38 PM ET instead of 5:11 AM ET
2. **Low quality features**: All players had ~65% quality (missing Phase 4 data)
3. **Top picks all missed**: High-edge picks were actually low-quality predictions

### Root Causes

1. **Timing**: ML Feature Store ran BEFORE Phase 4 completed
2. **No quality gate**: Predictions made regardless of feature quality
3. **No existing-check**: Old predictions replaced without consideration

### Impact

- 0 picks in 11 AM export (predictions didn't exist yet)
- Top 3 high-edge picks all MISSED (missing BDB shot zone data)
- User confusion when predictions changed

---

## Design Philosophy

### Core Principle: "Predict Once, Never Replace"

Instead of making predictions early and replacing them when better data arrives, we:

1. **WAIT** until features are ready (quality >= threshold)
2. Make **ONE** prediction per player per day
3. **NEVER** replace existing predictions
4. **FORCE** only at last call if data never arrives

### Why This Approach?

| Alternative | Problem |
|-------------|---------|
| Predict early, replace later | Users see predictions change; confusing |
| Always wait for perfect data | Some players never get predictions |
| Lower quality threshold | More predictions, but less accurate |

Our approach balances:
- **Stability**: Predictions don't change
- **Coverage**: Eventually all players get predictions
- **Quality**: Most predictions use high-quality data

---

## System Components

### New Files

```
predictions/coordinator/
├── quality_gate.py      # Core quality gate logic
├── quality_alerts.py    # Alerting for quality issues
└── coordinator.py       # Modified to use quality gate
```

### Schema Changes

```sql
-- New columns in player_prop_predictions
feature_quality_score FLOAT64     -- Snapshot at prediction time
low_quality_flag BOOLEAN          -- True if quality < 85%
forced_prediction BOOLEAN         -- True if forced at LAST_CALL
prediction_attempt STRING         -- FIRST, RETRY, FINAL_RETRY, LAST_CALL
```

### Classes

#### QualityGate

```python
class QualityGate:
    def get_existing_predictions(game_date, player_lookups) -> Dict[str, bool]
    def get_feature_quality_scores(game_date, player_lookups) -> Dict[str, float]
    def apply_quality_gate(game_date, player_lookups, mode) -> (results, summary)
```

#### PredictionMode

```python
class PredictionMode(Enum):
    FIRST = "FIRST"           # 85% threshold
    RETRY = "RETRY"           # 85% threshold
    FINAL_RETRY = "FINAL_RETRY"  # 80% threshold
    LAST_CALL = "LAST_CALL"   # 0% threshold (force all)
```

---

## Quality Gate Logic

### Decision Flow

```
For each player:

1. Has existing prediction for this game_date?
   └─ YES → SKIP (never replace)

2. Has feature data available?
   └─ NO → Mode is LAST_CALL?
           └─ YES → PREDICT (forced, flagged)
           └─ NO → SKIP (wait for data)

3. Feature quality >= threshold for mode?
   └─ YES → PREDICT
   └─ NO → Mode is LAST_CALL?
           └─ YES → PREDICT (forced, flagged)
           └─ NO → SKIP (wait for better data)
```

### Thresholds by Mode

| Mode | Threshold | Description |
|------|-----------|-------------|
| FIRST | 85% | First attempt - high quality only |
| RETRY | 85% | Hourly retries - still require high quality |
| FINAL_RETRY | 80% | Last quality-gated attempt - accept medium |
| LAST_CALL | 0% | Force all remaining - flag as low quality |

### Quality Flags

| Flag | When Set | Effect |
|------|----------|--------|
| `low_quality_flag` | quality < 85% | Excluded from "top picks" exports |
| `forced_prediction` | Made at LAST_CALL | Indicates data was incomplete |

---

## Schedule Design

### Timeline (All Times ET)

```
6:00 AM  ┌─────────────────────────────────────────────────────┐
         │ Phase 4 runs (processes overnight game data)        │
         └─────────────────────────────────────────────────────┘

7:00 AM  ┌─────────────────────────────────────────────────────┐
         │ ML Feature Store #1 (uses fresh Phase 4 data)       │
         └─────────────────────────────────────────────────────┘

8:00 AM  ┌─────────────────────────────────────────────────────┐
         │ Predictions FIRST (only if quality >= 85%)          │
         └─────────────────────────────────────────────────────┘

9-12 PM  ┌─────────────────────────────────────────────────────┐
         │ Predictions RETRY (hourly, quality >= 85%)          │
         │ Feature Store refreshes at 10 AM, 1 PM              │
         └─────────────────────────────────────────────────────┘

11:00 AM ┌─────────────────────────────────────────────────────┐
         │ Export #1 (morning - for early bettors)             │
         └─────────────────────────────────────────────────────┘

1:00 PM  ┌─────────────────────────────────────────────────────┐
         │ Predictions FINAL_RETRY (quality >= 80%)            │
         │ Export #2 (mid-day)                                 │
         └─────────────────────────────────────────────────────┘

4:00 PM  ┌─────────────────────────────────────────────────────┐
         │ Predictions LAST_CALL (force all remaining)         │
         └─────────────────────────────────────────────────────┘

5:00 PM  ┌─────────────────────────────────────────────────────┐
         │ Export #3 (pre-game - final for bettors)            │
         └─────────────────────────────────────────────────────┘

7:00 PM  ┌─────────────────────────────────────────────────────┐
         │ Games typically start                                │
         └─────────────────────────────────────────────────────┘
```

### Scheduler Jobs to Update

| Current Job | Current Time | New Time | New Mode |
|-------------|--------------|----------|----------|
| predictions-early | 2:30 AM | DELETE | - |
| predictions-retry | 5:00 AM | DELETE | - |
| overnight-predictions | 7:00 AM | 8:00 AM | FIRST |
| NEW: predictions-9am | - | 9:00 AM | RETRY |
| morning-predictions | 10:00 AM | 10:00 AM | RETRY |
| NEW: predictions-11am | - | 11:00 AM | RETRY |
| NEW: predictions-12pm | - | 12:00 PM | RETRY |
| NEW: predictions-final-retry | - | 1:00 PM | FINAL_RETRY |
| NEW: predictions-last-call | - | 4:00 PM | LAST_CALL |

### ML Feature Store Schedule

| Job | Time | Purpose |
|-----|------|---------|
| ml-feature-store-daily | 11:30 PM (current) | Can keep for overnight |
| ml-feature-store-morning | 7:00 AM | After Phase 4 |
| ml-feature-store-midday | 10:00 AM | Refresh before noon |
| ml-feature-store-afternoon | 1:00 PM | Final refresh |

---

## Alerting System

### Alert Types

| Alert | Trigger | Severity | Action |
|-------|---------|----------|--------|
| LOW_QUALITY_FEATURES | <80% of players have quality >= 85% | WARNING | Check Phase 4 |
| PHASE4_DATA_MISSING | 0 rows in feature store for today | CRITICAL | Investigate pipeline |
| FORCED_PREDICTIONS | >10 players forced at LAST_CALL | WARNING | Review data health |
| LOW_COVERAGE | <80% have predictions by FINAL_RETRY | WARNING | Investigate blockers |

### Alert Channels

- **Slack**: #nba-alerts for all alerts
- **Cloud Logging**: Structured logs with `alert_type` field

### Alert Message Format

```
:warning: *LOW_QUALITY_FEATURES* (WARNING)

Only 65.0% of players have high-quality features (85%+)

*Details:*
  game_date: 2026-02-03
  mode: FIRST
  high_quality_pct: 65.0
  avg_quality: 72.3
```

---

## Data Flow

### Before (Problematic)

```
2:30 AM  Feature Store runs (Phase 4 not ready)
           │
           ▼
         Features have low quality (65%)
           │
6:00 AM  Phase 4 runs (data now available)
           │
           ▼
         Feature Store NOT re-run
           │
7:00 AM  Predictions run with stale features
           │
           ▼
         Low-quality predictions made
           │
1:00 PM  Export runs
           │
           ▼
         Bad predictions exported as "top picks"
```

### After (Fixed)

```
6:00 AM  Phase 4 runs (data ready)
           │
           ▼
7:00 AM  Feature Store runs (high quality)
           │
           ▼
8:00 AM  Predictions FIRST (quality gate)
           │
           ├─ Quality >= 85%? → Predict
           │
           └─ Quality < 85%? → Wait
           │
9-12 PM  Predictions RETRY (quality gate)
           │
           ├─ Already has prediction? → Skip
           │
           ├─ Quality >= 85%? → Predict
           │
           └─ Quality < 85%? → Wait
           │
1:00 PM  Predictions FINAL_RETRY
           │
           ├─ Quality >= 80%? → Predict
           │
           └─ Quality < 80%? → Wait
           │
4:00 PM  Predictions LAST_CALL
           │
           └─ All remaining → Predict (flagged)
```

---

## Configuration

### Environment Variables

No new environment variables required. Uses existing:
- `GCP_PROJECT_ID`
- `PREDICTION_REQUEST_TOPIC`

### Feature Flags

Quality gate is always enabled. To disable (not recommended):
```python
# In coordinator.py - wrap quality gate in try/except (already done)
# If quality gate fails, falls back to old behavior
```

### Thresholds

Defined in `quality_gate.py`:
```python
QUALITY_THRESHOLDS = {
    PredictionMode.FIRST: 85.0,
    PredictionMode.RETRY: 85.0,
    PredictionMode.FINAL_RETRY: 80.0,
    PredictionMode.LAST_CALL: 0.0,
}
```

---

## Deployment

### Steps

1. **Schema update** (already done):
   ```bash
   bq query "ALTER TABLE nba_predictions.player_prop_predictions
              ADD COLUMN IF NOT EXISTS low_quality_flag BOOLEAN"
   # etc.
   ```

2. **Deploy coordinator**:
   ```bash
   ./bin/deploy-service.sh prediction-coordinator
   ```

3. **Update scheduler jobs**:
   ```bash
   # See scheduler job commands below
   ```

4. **Verify**:
   ```bash
   # Trigger a test prediction run
   curl -X POST https://prediction-coordinator-xxx.run.app/start \
     -H "Authorization: Bearer $API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"game_date": "TODAY", "prediction_run_mode": "FIRST"}'
   ```

### Scheduler Job Commands

```bash
# Delete old jobs that are no longer needed
gcloud scheduler jobs delete predictions-early --location=us-west2
gcloud scheduler jobs delete predictions-retry --location=us-west2

# Update overnight-predictions to be FIRST at 8 AM ET
gcloud scheduler jobs update http overnight-predictions \
  --location=us-west2 \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --http-method=POST \
  --uri="https://prediction-coordinator-xxx.run.app/start" \
  --message-body='{"game_date": "TODAY", "prediction_run_mode": "FIRST", "force": true}'

# Create hourly retry jobs (9 AM - 12 PM)
for hour in 9 10 11 12; do
  gcloud scheduler jobs create http predictions-${hour}am \
    --location=us-west2 \
    --schedule="0 ${hour} * * *" \
    --time-zone="America/New_York" \
    --http-method=POST \
    --uri="https://prediction-coordinator-xxx.run.app/start" \
    --message-body="{\"game_date\": \"TODAY\", \"prediction_run_mode\": \"RETRY\", \"force\": true}"
done

# Create FINAL_RETRY at 1 PM
gcloud scheduler jobs create http predictions-final-retry \
  --location=us-west2 \
  --schedule="0 13 * * *" \
  --time-zone="America/New_York" \
  --http-method=POST \
  --uri="https://prediction-coordinator-xxx.run.app/start" \
  --message-body='{"game_date": "TODAY", "prediction_run_mode": "FINAL_RETRY", "force": true}'

# Create LAST_CALL at 4 PM
gcloud scheduler jobs create http predictions-last-call \
  --location=us-west2 \
  --schedule="0 16 * * *" \
  --time-zone="America/New_York" \
  --http-method=POST \
  --uri="https://prediction-coordinator-xxx.run.app/start" \
  --message-body='{"game_date": "TODAY", "prediction_run_mode": "LAST_CALL", "force": true}'
```

---

## Monitoring

### Key Metrics

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Avg quality score | >= 85% | 80-85% | < 80% |
| Players with predictions by 11 AM | >= 80% | 60-80% | < 60% |
| Forced predictions at LAST_CALL | < 5% | 5-10% | > 10% |
| Prediction timing (first batch) | <= 8:30 AM | 8:30-10 AM | > 10 AM |

### Queries

```sql
-- Quality distribution for today
SELECT
  CASE
    WHEN feature_quality_score >= 85 THEN 'High (85%+)'
    WHEN feature_quality_score >= 80 THEN 'Medium (80-85%)'
    ELSE 'Low (<80%)'
  END as tier,
  COUNT(*) as predictions,
  COUNTIF(low_quality_flag) as low_quality_flagged,
  COUNTIF(forced_prediction) as forced
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v9'
GROUP BY tier;

-- Prediction timing by mode
SELECT
  prediction_attempt,
  MIN(created_at) as first_prediction,
  MAX(created_at) as last_prediction,
  COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND system_id = 'catboost_v9'
GROUP BY prediction_attempt;
```

### Logs

Search in Cloud Logging:
```
resource.type="cloud_run_revision"
resource.labels.service_name="prediction-coordinator"
jsonPayload.message=~"QUALITY_GATE"
```

---

## Troubleshooting

### No Predictions by 11 AM

1. **Check Phase 4 ran**: Query `player_composite_factors` for today
2. **Check Feature Store ran**: Query `ml_feature_store_v2` for today
3. **Check coordinator logs**: Look for QUALITY_GATE messages
4. **Manual trigger**: POST to /start with RETRY mode

### All Predictions Low Quality

1. **Phase 4 data missing**: Feature store ran before Phase 4
2. **Fix**: Manually trigger feature store, then predictions

### Many Forced Predictions

1. **Upstream data issue**: BDB or Phase 3 data incomplete
2. **Review**: Check which players were forced and why
3. **Consider**: May need to backfill historical data

### Predictions Not Exported

1. **Check quality filter**: Exports exclude `low_quality_flag = TRUE` for top picks
2. **Timing**: Ensure predictions exist before export runs
3. **Verify**: Query predictions table for the export window

---

## Summary

The prediction quality system ensures:

1. **High quality**: Most predictions use 85%+ quality features
2. **Stability**: Predictions never change once made
3. **Coverage**: All players get predictions by 4 PM ET
4. **Transparency**: Quality flags show which predictions are lower confidence
5. **Alerting**: Issues detected and reported automatically

By 4 PM ET, all predictions are final and won't change.
