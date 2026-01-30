# Prediction Quality Tracking System

**Status:** Design Document
**Created:** Session 39 (2026-01-30)

---

## Problem Statement

When BigDataBall play-by-play data is unavailable at processing time:
1. Phase 3 runs without shot zone data → `paint_attempts = NULL`
2. Phase 4/5 produce predictions with degraded quality
3. **No visibility** that predictions are missing critical features
4. **No automatic re-run** when data becomes available
5. **No audit trail** of what data was available when predictions were made

This caused CatBoost V8 to collapse from 77% → 34% hit rate.

---

## Solution Architecture

### 1. Prediction Quality Metadata

Every prediction should carry quality metadata:

```
prediction_record = {
    # Existing fields
    player_lookup, game_date, prop_type, prediction, confidence,

    # NEW: Quality tracking
    data_quality_tier: 'gold' | 'silver' | 'bronze',
    shot_zones_available: true | false,
    missing_features: ['paint_rate', 'mid_range_rate'],
    feature_sources: {
        'shot_zones': 'bigdataball_pbp' | 'nbac_fallback' | 'unavailable',
        'box_scores': 'nbac_gamebook',
        'betting': 'odds_api'
    },
    processing_version: 'v8.1',
    processed_at: timestamp,

    # Re-run tracking
    is_rerun: false,
    original_prediction_id: null,
    rerun_reason: null
}
```

### 2. Prediction Audit Log Table

Store complete audit trail of every prediction decision:

```sql
CREATE TABLE nba_predictions.prediction_audit_log (
    -- Identifiers
    audit_id STRING NOT NULL,
    prediction_id STRING NOT NULL,
    player_lookup STRING NOT NULL,
    game_date DATE NOT NULL,
    game_id STRING,

    -- Processing context
    processing_run_id STRING,
    processed_at TIMESTAMP NOT NULL,
    model_version STRING,

    -- Data availability at processing time
    data_sources_available ARRAY<STRUCT<
        source STRING,
        available BOOL,
        row_count INT64,
        freshness_hours FLOAT64
    >>,

    -- Feature completeness
    features_requested INT64,
    features_available INT64,
    missing_features ARRAY<STRING>,

    -- Quality assessment
    data_quality_tier STRING,  -- gold, silver, bronze
    quality_issues ARRAY<STRING>,

    -- Prediction details
    prediction_value FLOAT64,
    confidence_score FLOAT64,
    model_features_used JSON,

    -- Re-run tracking
    is_rerun BOOL DEFAULT FALSE,
    supersedes_prediction_id STRING,
    rerun_reason STRING,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);
```

### 3. Data Arrival Detection & Re-run Trigger

```
┌─────────────────┐
│ BDB Data Lands  │
│ in BigQuery     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Cloud Function  │
│ Detects Insert  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ Check: Was this game processed without  │
│ BDB? (query pending_bdb_games)          │
└────────┬────────────────────────────────┘
         │ Yes
         ▼
┌─────────────────────────────────────────┐
│ Check: Is it safe to re-run?            │
│ - Game not started yet?                 │
│ - More than 1 hour before game?        │
└────────┬───────────────┬────────────────┘
         │ Safe          │ Too Late
         ▼               ▼
┌─────────────────┐  ┌─────────────────────┐
│ Trigger Phase 3 │  │ Log: "Late arrival, │
│ Re-run          │  │ prediction locked"  │
└────────┬────────┘  └─────────────────────┘
         │
         ▼
┌─────────────────┐
│ After Phase 3:  │
│ Trigger Phase 4 │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ Phase 5: Generate new predictions       │
│ Mark as: is_rerun=true                  │
│ Reference: original_prediction_id       │
│ Log: rerun_reason="bdb_data_available"  │
└─────────────────────────────────────────┘
```

### 4. Visibility in Predictions API

```json
GET /api/predictions/tonight

{
  "predictions": [
    {
      "player": "LeBron James",
      "prop": "points",
      "line": 25.5,
      "prediction": "over",
      "confidence": 0.72,

      "quality": {
        "tier": "gold",
        "shot_zones_available": true,
        "all_features_available": true
      }
    },
    {
      "player": "Anthony Davis",
      "prop": "points",
      "line": 24.5,
      "prediction": "over",
      "confidence": 0.58,

      "quality": {
        "tier": "silver",
        "shot_zones_available": false,
        "missing_features": ["paint_rate", "mid_range_rate", "three_pt_rate"],
        "warning": "Shot zone data unavailable - prediction may be less accurate"
      }
    }
  ],

  "data_status": {
    "bigdataball_pbp": {
      "available": false,
      "last_update": "2026-01-29T23:00:00Z",
      "games_missing": ["LAL@BOS", "MIA@NYK"]
    }
  }
}
```

---

## Implementation Plan

### Phase 1: Prediction Quality Flags (Immediate)

1. Add quality columns to `player_prop_predictions` table
2. Modify prediction worker to populate quality fields
3. Add quality info to tonight API response

### Phase 2: Audit Log (This Week)

1. Create `prediction_audit_log` table
2. Log every prediction with full context
3. Add query tools for investigation

### Phase 3: Automatic Re-run (Next Week)

1. Create Cloud Function for BDB arrival detection
2. Implement safe re-run logic (check game start time)
3. Create re-run tracking in predictions

### Phase 4: Dashboard & Alerts (Following Week)

1. Create data quality dashboard
2. Add Slack alerts for degraded predictions
3. Historical analysis tools

---

## Key Design Decisions

### Q: Should we change predictions after they're made?

**A: Only if safe (>1 hour before game start)**

Reasoning:
- Users may have already bet based on our prediction
- Changing predictions close to game time is confusing
- But early re-runs with better data improve accuracy

### Q: How to handle the "locked" predictions?

**A: Keep original, log that better data arrived late**

```json
{
  "prediction_id": "abc123",
  "status": "locked",
  "quality": "silver",
  "late_data_arrival": {
    "bdb_arrived_at": "2026-01-30T18:30:00Z",
    "game_start_at": "2026-01-30T19:00:00Z",
    "reason_not_rerun": "less_than_2_hours_before_game"
  }
}
```

### Q: What quality tier should block predictions entirely?

**A: None - always generate, but flag quality**

Reasoning:
- Some prediction is better than none
- Users can see quality and decide
- We learn from all predictions (even degraded ones)

---

## Schema Changes Required

### 1. player_prop_predictions (add columns)

```sql
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN IF NOT EXISTS data_quality_tier STRING,
ADD COLUMN IF NOT EXISTS shot_zones_available BOOL,
ADD COLUMN IF NOT EXISTS missing_features ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS feature_sources JSON,
ADD COLUMN IF NOT EXISTS is_rerun BOOL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS original_prediction_id STRING,
ADD COLUMN IF NOT EXISTS rerun_reason STRING;
```

### 2. prediction_audit_log (new table)

See schema above.

### 3. pending_bdb_games (already created)

Used to track games awaiting BDB data.

---

## Monitoring & Alerts

### Daily Quality Report

```
📊 Prediction Quality Report - 2026-01-30

Games processed: 12
├── Gold quality: 10 (83%)
├── Silver quality: 2 (17%)
└── Bronze quality: 0 (0%)

BDB Coverage: 10/12 games (83%)
Missing: LAL@BOS, MIA@NYK

Actions:
- BDB retry triggered for missing games
- Will re-run if data arrives before 5 PM ET
```

### Slack Alerts

- **Immediate**: When BDB missing for >3 games
- **Warning**: When any game processed at silver/bronze
- **Critical**: When >50% of games at degraded quality

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `predictions/worker/prediction_systems/catboost_v8.py` | Add quality tracking |
| `predictions/worker/quality_tracker.py` | NEW: Quality assessment |
| `predictions/worker/audit_logger.py` | NEW: Audit log writer |
| `orchestration/cloud_functions/bdb_arrival_trigger/` | NEW: Re-run trigger |
| `shared/api/tonight_predictions.py` | Add quality to API |
| `schemas/bigquery/nba_predictions/prediction_audit_log.sql` | NEW: Schema |
