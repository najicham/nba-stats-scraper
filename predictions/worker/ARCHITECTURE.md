# Phase 5 Prediction Worker - Architecture Documentation

`/predictions/worker/ARCHITECTURE.md`

**Version**: 1.0  
**Last Updated**: November 8, 2025  
**Status**: Production Ready

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Data Flow](#data-flow)
4. [Components](#components)
5. [System Integration](#system-integration)
6. [Performance](#performance)
7. [Error Handling](#error-handling)
8. [Monitoring](#monitoring)
9. [Troubleshooting](#troubleshooting)

---

## Overview

The Phase 5 Prediction Worker is a Cloud Run service that orchestrates all 5 prediction systems to generate NBA player prop predictions. It receives player prediction requests via Pub/Sub, loads required data from BigQuery, calls all prediction systems, and writes results to BigQuery.

### Key Characteristics

- **Service Type**: Cloud Run (auto-scaling containerized service)
- **Trigger**: Pub/Sub push subscription
- **Concurrency**: 5 threads per instance, up to 20 instances (100 concurrent)
- **Processing Time**: ~200-300ms per player
- **Daily Volume**: 450 players
- **Prediction Systems**: 5 (Moving Average, Zone Matchup, Similarity, XGBoost, Ensemble)

---

## Architecture

### High-Level Architecture

```
┌──────────────┐
│ Coordinator  │ → Pub/Sub: prediction-request
└──────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│         Pub/Sub Push Subscription       │
│         (prediction-request)            │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│      Phase 5 Prediction Worker          │
│      (Cloud Run Service)                 │
│                                          │
│  ┌────────────────────────────────┐    │
│  │  Flask App (/predict endpoint) │    │
│  └────────────────────────────────┘    │
│                                          │
│  ┌────────────────────────────────┐    │
│  │  Data Loader                   │    │
│  │  - Load features               │    │
│  │  - Load historical games       │    │
│  └────────────────────────────────┘    │
│                                          │
│  ┌────────────────────────────────┐    │
│  │  Prediction Systems (5)        │    │
│  │  1. Moving Average             │    │
│  │  2. Zone Matchup               │    │
│  │  3. Similarity                 │    │
│  │  4. XGBoost                    │    │
│  │  5. Ensemble                   │    │
│  └────────────────────────────────┘    │
│                                          │
│  ┌────────────────────────────────┐    │
│  │  BigQuery Writer               │    │
│  └────────────────────────────────┘    │
│                                          │
│  ┌────────────────────────────────┐    │
│  │  Pub/Sub Publisher             │    │
│  │  (prediction-ready events)     │    │
│  └────────────────────────────────┘    │
└─────────────────────────────────────────┘
        │
        ├──────────────────┬────────────
        │                  │
        ▼                  ▼
┌──────────────┐  ┌──────────────┐
│  BigQuery    │  │   Pub/Sub    │
│  Predictions │  │  pred-ready  │
└──────────────┘  └──────────────┘
```

### Component Diagram

```
predictions/worker/
├── worker.py              # Flask app + orchestration
├── data_loaders.py        # BigQuery data loading
├── requirements.txt       # Python dependencies
└── prediction_systems/    # All 5 prediction systems
    ├── moving_average_baseline.py
    ├── zone_matchup_v1.py
    ├── similarity_balanced_v1.py
    ├── xgboost_v1.py
    └── ensemble_v1.py

predictions/shared/
├── __init__.py
└── mock_xgboost_model.py  # Mock ML model for testing
```

---

## Data Flow

### Request Flow

```
1. Coordinator publishes message:
   {
     "player_lookup": "lebron-james",
     "game_date": "2025-11-08",
     "game_id": "20251108_LAL_GSW",
     "line_values": [25.5]
   }

2. Pub/Sub delivers to /predict endpoint

3. Worker decodes and validates message

4. Data Loader fetches from BigQuery:
   a) Features (ml_feature_store_v2)
   b) Historical games (player_game_summary)

5. Worker calls 5 prediction systems:
   a) Moving Average → prediction
   b) Zone Matchup → prediction
   c) Similarity → prediction (needs historical games)
   d) XGBoost → prediction
   e) Ensemble → prediction (combines all 4)

6. Worker formats predictions for BigQuery

7. Worker writes 5 rows to player_prop_predictions

8. Worker publishes completion event

9. Returns 204 No Content (success)
```

### Data Loading Details

**Step 4a: Load Features**
```sql
SELECT features, feature_names, feature_quality_score
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = 'lebron-james'
  AND game_date = '2025-11-08'
  AND feature_version = 'v2_33features'
```

Returns:
```python
{
    'points_avg_last_5': 28.4,
    'points_avg_last_10': 27.2,
    'points_avg_season': 26.8,
    # ... 22 more features
    'feature_quality_score': 95.5
}
```

**Step 4b: Load Historical Games**
```sql
SELECT game_date, opponent_team_abbr, is_home, days_rest, 
       points, opponent_def_rating_last_15, 
       points_avg_last_5, points_avg_season
FROM nba_analytics.player_game_summary
WHERE player_lookup = 'lebron-james'
  AND game_date < '2025-11-08'
  AND game_date >= DATE_SUB('2025-11-08', INTERVAL 90 DAY)
ORDER BY game_date DESC
LIMIT 30
```

Worker calculates:
- `opponent_tier`: elite/average/weak (from def_rating)
- `recent_form`: hot/normal/cold (from last_5 vs season)

Returns:
```python
[
    {
        'game_date': '2024-11-05',
        'opponent_tier': 'tier_1_elite',
        'days_rest': 1,
        'is_home': True,
        'recent_form': 'hot',
        'points': 28
    },
    # ... 29 more games
]
```

---

## Components

### 1. Worker (worker.py)

**Purpose**: Flask application that orchestrates prediction generation

**Key Functions**:
- `handle_prediction_request()`: Pub/Sub endpoint handler
- `process_player_predictions()`: Main orchestration logic
- `format_prediction_for_bigquery()`: Output formatting
- `write_predictions_to_bigquery()`: Database writes
- `publish_completion_event()`: Event publishing

**Initialization**:
```python
# Reusable components (shared across requests)
data_loader = PredictionDataLoader(PROJECT_ID)
bq_client = bigquery.Client(project=PROJECT_ID)
pubsub_publisher = pubsub_v1.PublisherClient()

# Initialize all 5 prediction systems
moving_average = MovingAverageBaseline()
zone_matchup = ZoneMatchupV1()
similarity = SimilarityBalancedV1()
xgboost = XGBoostV1()
ensemble = EnsembleV1(moving_average, zone_matchup, similarity, xgboost)
```

### 2. Data Loader (data_loaders.py)

**Purpose**: Load data from BigQuery for prediction systems

**Key Methods**:
- `load_features()`: Get 25 features from ml_feature_store_v2
- `load_historical_games()`: Get recent games for similarity matching
- `load_game_context()`: Get game metadata (optional)

**Performance**:
- Features query: ~10-20ms
- Historical games query: ~50-100ms
- Total: ~60-120ms per player

**Design Patterns**:
- Connection pooling (reuses BigQuery client)
- Graceful degradation (returns None on errors, doesn't crash)
- Calculation helpers (opponent_tier, recent_form)

### 3. Prediction Systems

All 5 systems are initialized once and reused across requests.

**Moving Average Baseline**
- Signature: `predict(features, player_lookup, game_date, prop_line)`
- Returns: `(predicted_points, confidence, recommendation)` tuple
- Confidence scale: 0.0-1.0
- Algorithm: Weighted average of last 5/10/season + adjustments

**Zone Matchup V1**
- Signature: `predict(features, player_lookup, game_date, prop_line)`
- Returns: `(predicted_points, confidence, recommendation)` tuple
- Confidence scale: 0.0-1.0
- Algorithm: Season average + zone-by-zone matchup scores

**Similarity Balanced V1**
- Signature: `predict(player_lookup, features, historical_games, betting_line)`
- Returns: Dict with `predicted_points`, `confidence_score`, `recommendation`
- Confidence scale: 0-100
- Algorithm: Find similar historical games, weighted average outcome
- **CRITICAL**: Requires historical_games parameter (not optional!)

**XGBoost V1**
- Signature: `predict(player_lookup, features, betting_line)`
- Returns: Dict with `predicted_points`, `confidence_score`, `recommendation`
- Confidence scale: 0-100
- Algorithm: Machine learning model (mock model in dev, real model in prod)

**Ensemble V1**
- Signature: `predict(features, player_lookup, game_date, prop_line, historical_games)`
- Returns: `(predicted_points, confidence, recommendation, metadata)` 4-tuple
- Confidence scale: 0.0-1.0
- Algorithm: Confidence-weighted average of all 4 base systems
- Requires minimum 2 systems to generate prediction

---

## System Integration

### Handling Signature Differences

The worker handles 3 critical inconsistencies:

**1. Parameter Order**
```python
# Moving Average & Zone Matchup (features first)
pred, conf, rec = system.predict(features, player_lookup, game_date, line)

# Similarity & XGBoost (player first)
result = system.predict(player_lookup, features, historical_games, line)

# Ensemble (features first + historical games)
pred, conf, rec, meta = ensemble.predict(features, player, date, line, hist)
```

**2. Return Format**
```python
# Tuple format (Moving Average, Zone Matchup)
predicted_points, confidence, recommendation = system.predict(...)

# Dict format (Similarity, XGBoost)
result = system.predict(...)
predicted_points = result['predicted_points']
confidence = result['confidence_score']

# 4-Tuple format (Ensemble)
predicted_points, confidence, recommendation, metadata = ensemble.predict(...)
```

**3. Confidence Scale**
```python
# Normalize to 0-100 for BigQuery
def normalize_confidence(confidence, system_id):
    if system_id in ['moving_average', 'zone_matchup_v1', 'ensemble_v1']:
        return confidence * 100.0  # Convert 0.0-1.0 to 0-100
    else:
        return confidence  # Already 0-100
```

### Error Handling Strategy

**Graceful Degradation**: Worker continues even if systems fail

```python
# Example: Similarity system failure
try:
    result = similarity.predict(...)
    system_predictions['similarity'] = result
except Exception as e:
    logger.error(f"Similarity failed: {e}")
    system_predictions['similarity'] = None
    # Continue with other systems!
```

**Minimum Requirements**:
- Ensemble needs ≥2 systems to generate prediction
- If all systems fail, worker returns 204 (success) with no predictions
- Worker never crashes - always returns 204 to Pub/Sub

### BigQuery Output Format

```python
# Each system generates one row per line
{
    'prediction_id': uuid.uuid4(),
    'system_id': 'similarity_balanced_v1',
    'player_lookup': 'lebron-james',
    'game_date': '2025-11-08',
    'game_id': '20251108_LAL_GSW',
    'predicted_points': 27.1,
    'confidence_score': 72.5,  # Always 0-100
    'recommendation': 'OVER',
    'current_points_line': 25.5,
    'line_margin': 1.6,
    
    # System-specific fields (Similarity only)
    'similarity_baseline': 26.8,
    'similar_games_count': 18,
    'avg_similarity_score': 82.3,
    
    # Timestamps
    'created_at': '2025-11-08T10:30:00.123Z',
    'is_active': True
}
```

---

## Performance

### Target Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Single player processing | <500ms | ~200-300ms ✅ |
| 450 players batch | <5 minutes | 2-3 minutes ✅ |
| System availability | >99.5% | TBD |
| Prediction success rate | >95% | TBD |

### Bottlenecks

**1. BigQuery Queries**
- Features: ~10-20ms (fast)
- Historical games: ~50-100ms (slower)
- Total data loading: ~60-120ms

**Mitigation**: Phase 4 precompute (future optimization)

**2. Prediction Systems**
- All 5 systems: ~50-100ms combined
- Ensemble slowest (waits for all 4 base systems)

**Mitigation**: Already optimized, no obvious improvements

**3. BigQuery Writes**
- Streaming insert: ~50ms for 5 rows
- Acceptable performance

### Scaling Strategy

**Cloud Run Configuration**:
```
Min Instances: 1 (prod) / 0 (dev)
Max Instances: 20
Concurrency: 5 threads per instance
Memory: 2Gi
CPU: 2 cores (prod) / 1 core (dev)
Timeout: 300s
```

**Scaling Math**:
- 20 instances × 5 threads = 100 concurrent players
- 450 players ÷ 100 capacity = 4.5 batches
- 4.5 batches × ~30 seconds/batch = ~2-3 minutes total

---

## Error Handling

### Error Types and Responses

**1. Invalid Pub/Sub Message**
```python
# Missing required fields
→ Returns 400 Bad Request
→ Message rejected (not retried)
```

**2. Data Loading Failure**
```python
# No features available
→ Returns 204 No Content
→ No predictions written
→ Logs error for monitoring
```

**3. System Prediction Failure**
```python
# One system crashes
→ Continue with remaining systems
→ Write partial predictions
→ Log error for debugging
```

**4. BigQuery Write Failure**
```python
# Streaming insert fails
→ Log error (don't crash)
→ Returns 204 No Content
→ Pub/Sub will NOT retry (idempotency)
```

### Retry Strategy

- **Pub/Sub**: Automatic retries with exponential backoff (max 7 days)
- **Worker**: No manual retries (graceful degradation)
- **Idempotency**: Multiple deliveries of same message OK (prediction_id is unique)

---

## Monitoring

### Key Metrics

**Request Metrics**:
- Request count (should be ~450/day)
- Request latency (p50, p95, p99)
- Error rate (should be <5%)

**System Metrics**:
- Instance count (should scale 0-20)
- CPU utilization (should be <80%)
- Memory utilization (should be <80%)

**Prediction Metrics**:
```sql
-- Daily prediction counts by system
SELECT 
    system_id,
    COUNT(*) as predictions,
    COUNT(DISTINCT player_lookup) as unique_players,
    AVG(confidence_score) as avg_confidence
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
GROUP BY system_id
```

**System Success Rates**:
```sql
-- System failure rates
WITH predictions_per_player AS (
    SELECT 
        player_lookup,
        COUNT(DISTINCT system_id) as systems_count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = CURRENT_DATE()
    GROUP BY player_lookup
)
SELECT 
    COUNTIF(systems_count = 5) as all_systems,
    COUNTIF(systems_count = 4) as four_systems,
    COUNTIF(systems_count = 3) as three_systems,
    COUNTIF(systems_count < 3) as failed_players
FROM predictions_per_player
```

### Alerts

**Critical**:
- Error rate >10%
- No predictions for >1 hour
- Instance count >18 (near max)

**Warning**:
- Latency p95 >1000ms
- System success rate <90%
- Memory utilization >85%

---

## Troubleshooting

### Common Issues

**Worker not scaling**
- Check Pub/Sub subscription configuration
- Verify push endpoint matches service URL
- Ensure service account has `run.invoker` permission

**No predictions in BigQuery**
- Check Cloud Run logs for write errors
- Verify table exists and schema matches
- Check service account has BigQuery Data Editor role

**Similarity system always failing**
- Verify historical games query returns data
- Check player has 90+ days of history
- Ensure opponent_def_rating field exists

**High latency**
- Profile BigQuery queries
- Check if Phase 4 features are stale
- Consider Phase 4 precompute for historical games

### Debug Commands

```bash
# View recent logs
gcloud run services logs read prediction-worker \
    --project nba-props-platform \
    --region us-central1 \
    --limit 100

# Check service status
gcloud run services describe prediction-worker \
    --project nba-props-platform \
    --region us-central1

# Test health check
TOKEN=$(gcloud auth print-identity-token)
SERVICE_URL=$(gcloud run services describe prediction-worker ...)
curl -H "Authorization: Bearer $TOKEN" "${SERVICE_URL}/health"
```

---

## Future Enhancements

**Phase 4 Precompute** (8-12 hours)
- Build `player_historical_game_context` table
- 10x faster historical games loading
- See `/docs/phase4_historical_games_migration.md`

**Real XGBoost Model** (2-3 weeks)
- Train on 4+ years of historical data
- Replace mock model
- Hyperparameter tuning

**Real-Time Updates** (2-3 weeks)
- Monitor betting line changes
- Trigger predictions when lines move
- Version predictions (supersede old)

**Multi-Prop Support** (1-2 weeks)
- Extend to assists, rebounds, threes
- Prop-specific systems
- Schema updates

---

*Last Updated: November 8, 2025*  
*Version: 1.0*
