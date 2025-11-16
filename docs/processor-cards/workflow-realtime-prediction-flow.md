# Real-Time Prediction Flow - Workflow Card

**Last Updated**: 2025-11-15
**Type**: Workflow Reference Card
**Purpose**: How Phase 5 responds to odds changes and generates predictions throughout the day
**Related**: See `docs/processor-cards/phase5-prediction-coordinator.md` for Phase 5 details

---

## Flow Overview

```
6:00 AM     │ Phase 5 startup, load daily cache
            │
6:00 AM -   │ Odds API updates (every 5-15 min)
11:59 PM    │   ↓
            │ Event triggers prediction pipeline
            │   ↓
            │ Generate predictions (all 5 models)
            │   ↓
            │ Store results, update dashboards
```

---

## Startup Sequence (6:00 AM)

### Step 1: Load Daily Cache (Once!)

**What Happens:**
```python
# Load static data that won't change during the day
player_cache = load_from_bigquery("""
    SELECT * FROM nba_precompute.player_daily_cache
    WHERE cache_date = CURRENT_DATE()
""")  # ~450 players, ~1 second

ml_features = load_from_bigquery("""
    SELECT * FROM nba_predictions.ml_feature_store_v2
    WHERE game_date = CURRENT_DATE()
""")  # ~450 players, ~1 second

# Convert to dict for O(1) lookups
cache_dict = {row['player_lookup']: row for row in player_cache}
features_dict = {row['player_lookup']: row for row in ml_features}
```

**Performance:**
- **Initial load:** ~2 seconds (2 BQ queries)
- **Memory:** ~5-10 MB (450 players × ~50 fields each)
- **Reuse:** Hundreds of times throughout day (no additional BQ queries!)

**Cost Savings:**
- Without cache: 100 updates/day × 450 players × 2 tables = **180,000 BQ queries/day**
- With cache: **2 BQ queries/day** (loaded once at startup)
- **Savings:** 99.99% reduction in BQ query volume

---

### Step 2: Initialize Prediction Models

**What Happens:**
```python
# Load trained models
xgboost_model = load_xgboost_model('models/player_points_v1.json')
moving_avg_model = MovingAveragePredictor()
zone_matchup_model = ZoneMatchupPredictor()
similarity_model = SimilarityPredictor()
ensemble_model = EnsemblePredictor([
    xgboost_model,
    moving_avg_model,
    zone_matchup_model,
    similarity_model
])

logger.info("Phase 5 prediction systems ready")
```

**Startup Time:** ~5-10 seconds
**Ready:** System is now listening for odds updates

---

## Real-Time Update Loop (6:00 AM - 11:59 PM)

### Trigger: Odds API Update Event

**What Happens:**
1. Odds API scraper runs (every 5-15 min during game days)
2. Updates `nba_raw.odds_api_player_points_props`
3. Pub/Sub event published: `odds-updated`
4. Phase 5 prediction service receives event

**Event Payload:**
```json
{
  "event_type": "odds_updated",
  "timestamp": "2025-11-15T14:32:15Z",
  "players_updated": [
    "lebron-james",
    "joel-embiid",
    "nikola-jokic"
  ],
  "update_type": "line_movement"  // or "new_props", "all_refresh"
}
```

---

### Prediction Pipeline (Per Player)

#### Step 1: Load Latest Odds (Dynamic Data)

```python
def get_latest_odds(player_lookup: str, game_date: date) -> dict:
    """
    Query ONLY the odds (changes frequently).
    Everything else comes from cache (static).
    """
    latest_odds = query_bigquery(f"""
        SELECT
            points_line,
            over_price_american,
            under_price_american,
            bookmaker,
            snapshot_timestamp
        FROM nba_raw.odds_api_player_points_props
        WHERE player_lookup = '{player_lookup}'
          AND game_date = '{game_date}'
        ORDER BY snapshot_timestamp DESC
        LIMIT 1
    """)
    return latest_odds
```

**Query Time:** ~100-200ms (indexed query)
**Frequency:** Once per player per odds update

---

#### Step 2: Combine Cache + Odds (O(1) Lookup!)

```python
def prepare_prediction_input(player_lookup: str, game_date: date):
    """
    Combine cached data (loaded once at 6 AM) with latest odds.
    """
    # O(1) dict lookups - no BQ queries!
    static_data = cache_dict.get(player_lookup)
    ml_features = features_dict.get(player_lookup)

    # Only fresh odds data requires BQ query
    latest_odds = get_latest_odds(player_lookup, game_date)

    if not static_data or not ml_features:
        logger.warning(f"Player {player_lookup} not in cache - skipping")
        return None

    # Combine everything
    prediction_input = {
        # From cache (loaded once at 6 AM)
        'points_avg_last_5': static_data['points_avg_last_5'],
        'points_avg_last_10': static_data['points_avg_last_10'],
        'team_pace': static_data['team_pace_last_10'],
        'games_in_last_7_days': static_data['games_in_last_7_days'],

        # From ML feature store (loaded once at 6 AM)
        'features': ml_features['features'],  # Array of 25 features
        'feature_quality_score': ml_features['feature_quality_score'],

        # From latest odds (queried now)
        'current_line': latest_odds['points_line'],
        'over_price': latest_odds['over_price_american'],
        'under_price': latest_odds['under_price_american']
    }

    return prediction_input
```

**Performance:**
- Cache lookups: <1ms (in-memory dict)
- Odds query: ~150ms (BigQuery)
- **Total time:** ~150ms per player

---

#### Step 3: Generate Predictions (All 5 Models)

```python
def generate_all_predictions(prediction_input: dict) -> dict:
    """
    Run all 5 prediction models in parallel.
    """
    predictions = {}

    # Model 1: XGBoost (uses 25 ML features)
    predictions['xgboost'] = xgboost_model.predict(
        prediction_input['features']
    )

    # Model 2: Moving Average (uses recent performance)
    predictions['moving_avg'] = moving_avg_model.predict(
        points_last_5=prediction_input['points_avg_last_5'],
        points_last_10=prediction_input['points_avg_last_10']
    )

    # Model 3: Zone Matchup (uses shot zones + opponent defense)
    predictions['zone_matchup'] = zone_matchup_model.predict(
        player_zones=prediction_input.get('player_shot_zones'),
        opponent_defense=prediction_input.get('opponent_defense_zones')
    )

    # Model 4: Similarity (uses player comparisons)
    predictions['similarity'] = similarity_model.predict(
        player_lookup=prediction_input['player_lookup'],
        game_context=prediction_input
    )

    # Model 5: Ensemble (weighted combination)
    predictions['ensemble'] = ensemble_model.predict(
        xgboost=predictions['xgboost'],
        moving_avg=predictions['moving_avg'],
        zone_matchup=predictions['zone_matchup'],
        similarity=predictions['similarity'],
        quality_score=prediction_input['feature_quality_score']
    )

    return predictions
```

**Model Performance:**
- XGBoost: ~5-10ms
- Moving Average: ~1ms
- Zone Matchup: ~2-3ms
- Similarity: ~10-20ms
- Ensemble: ~1ms
- **Total:** ~20-35ms per player

---

#### Step 4: Calculate Edge and Confidence

```python
def calculate_betting_edge(predictions: dict, current_line: float) -> dict:
    """
    Compare prediction to current line to find betting edge.
    """
    ensemble_prediction = predictions['ensemble']

    # Edge calculation
    edge = ensemble_prediction - current_line
    edge_pct = (edge / current_line) * 100

    # Confidence based on feature quality and model agreement
    model_agreement = calculate_model_agreement(predictions)
    feature_quality = predictions.get('feature_quality_score', 75)

    confidence = (model_agreement * 0.6) + (feature_quality * 0.4)

    # Recommendation
    if edge_pct >= 5.0 and confidence >= 75:
        recommendation = 'STRONG_OVER'
    elif edge_pct >= 3.0 and confidence >= 70:
        recommendation = 'OVER'
    elif edge_pct <= -5.0 and confidence >= 75:
        recommendation = 'STRONG_UNDER'
    elif edge_pct <= -3.0 and confidence >= 70:
        recommendation = 'UNDER'
    else:
        recommendation = 'PASS'

    return {
        'predicted_points': ensemble_prediction,
        'current_line': current_line,
        'edge': edge,
        'edge_pct': edge_pct,
        'confidence': confidence,
        'recommendation': recommendation
    }
```

---

#### Step 5: Store Results

```python
def store_prediction(player_lookup: str, game_date: date,
                     predictions: dict, edge_analysis: dict):
    """
    Store prediction results for tracking and display.
    """
    record = {
        'player_lookup': player_lookup,
        'game_date': game_date,
        'prediction_timestamp': datetime.now(),

        # All model predictions
        'xgboost_prediction': predictions['xgboost'],
        'moving_avg_prediction': predictions['moving_avg'],
        'zone_matchup_prediction': predictions['zone_matchup'],
        'similarity_prediction': predictions['similarity'],
        'ensemble_prediction': predictions['ensemble'],

        # Edge analysis
        'current_line': edge_analysis['current_line'],
        'edge': edge_analysis['edge'],
        'edge_pct': edge_analysis['edge_pct'],
        'confidence': edge_analysis['confidence'],
        'recommendation': edge_analysis['recommendation'],

        # Metadata
        'feature_quality_score': predictions.get('feature_quality_score'),
        'model_agreement_score': calculate_model_agreement(predictions)
    }

    # Write to BigQuery
    insert_into_bigquery('nba_predictions.player_points_predictions', [record])

    # Optionally publish to Pub/Sub for real-time dashboard updates
    publish_prediction_event(record)
```

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 6:00 AM - STARTUP (ONCE)                                    │
│                                                              │
│ Load player_daily_cache        → cache_dict (450 players)   │
│ Load ml_feature_store_v2       → features_dict (450)        │
│ Load prediction models         → 5 models ready             │
│                                                              │
│ Time: ~10 seconds                                           │
│ Memory: ~10 MB                                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 6:00 AM - 11:59 PM - REAL-TIME LOOP                         │
│                                                              │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ Odds API Update (every 5-15 min)                    │    │
│ │   ↓                                                  │    │
│ │ Pub/Sub Event: "odds-updated"                       │    │
│ │   ↓                                                  │    │
│ │ Phase 5 receives event                              │    │
│ └─────────────────────────────────────────────────────┘    │
│                            ↓                                 │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ FOR EACH PLAYER:                                    │    │
│ │                                                      │    │
│ │ 1. Load latest odds (~150ms BQ query)               │    │
│ │ 2. Get cached data (<1ms dict lookup) ✨             │    │
│ │ 3. Get ML features (<1ms dict lookup) ✨             │    │
│ │ 4. Run 5 prediction models (~30ms)                  │    │
│ │ 5. Calculate edge/confidence (~1ms)                 │    │
│ │ 6. Store prediction (~50ms BQ write)                │    │
│ │                                                      │    │
│ │ Total time per player: ~230ms                       │    │
│ └─────────────────────────────────────────────────────┘    │
│                            ↓                                 │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ Batch process 450 players                           │    │
│ │   → Total time: ~1-2 minutes (parallel processing)  │    │
│ └─────────────────────────────────────────────────────┘    │
│                            ↓                                 │
│ ┌─────────────────────────────────────────────────────┐    │
│ │ Publish to dashboards                               │    │
│ │ Alert on high-confidence picks                      │    │
│ └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Performance Metrics

### Per-Player Prediction (Single Update)

| Step | Time | BQ Queries | Notes |
|------|------|------------|-------|
| Load latest odds | 150ms | 1 | Indexed query |
| Get cached data | <1ms | 0 | In-memory dict lookup ✨ |
| Get ML features | <1ms | 0 | In-memory dict lookup ✨ |
| Run 5 models | 30ms | 0 | In-process computation |
| Calculate edge | 1ms | 0 | Simple math |
| Store prediction | 50ms | 1 | BQ insert |
| **Total** | **~230ms** | **2** | **Per player** |

### Batch Processing (All Players)

**Sequential Processing:**
- 450 players × 230ms = **103 seconds** (~1.7 minutes)

**Parallel Processing (10 workers):**
- 450 players ÷ 10 workers = 45 players/worker
- 45 × 230ms = **10 seconds** per worker
- **Total: ~10-15 seconds** for all 450 players

---

## Daily Volume Estimates

### BigQuery Queries

**Without Cache (Old Approach):**
- 100 odds updates/day
- 450 players per update
- 2 tables per player (cache + features)
- **Total:** 100 × 450 × 2 = **90,000 queries/day**

**With Cache (New Approach):**
- 1 cache load at 6 AM (2 queries)
- 100 odds updates × 450 players × 1 query = 45,000 queries
- **Total:** 2 + 45,000 = **45,002 queries/day**
- **Savings:** 50% reduction (plus much faster!)

### Processing Time

**Per Odds Update:**
- Parallel processing: ~10-15 seconds for 450 players
- **Total time per day:** 100 updates × 15 sec = **25 minutes/day**

---

## Cache Refresh Strategy

### When to Reload Cache

**Scenario 1: Daily Refresh (Normal)**
- Cache loaded at 6:00 AM
- Valid until 11:59 PM
- Next day: New cache loaded at 6:00 AM

**Scenario 2: Mid-Day Refresh (Optional)**
- If critical Phase 4 data updated mid-day
- Manually trigger cache reload
- Rare - only for data corrections

**Scenario 3: Emergency Refresh**
- Player injury mid-day
- Team trade deadline moves
- Trigger targeted cache update for affected players

```python
def refresh_cache_for_players(player_lookups: list):
    """
    Refresh cache for specific players (injury updates, etc.)
    """
    for player_lookup in player_lookups:
        # Reload from BigQuery
        updated_cache = query_player_cache(player_lookup)
        updated_features = query_ml_features(player_lookup)

        # Update in-memory dicts
        cache_dict[player_lookup] = updated_cache
        features_dict[player_lookup] = updated_features

    logger.info(f"Refreshed cache for {len(player_lookups)} players")
```

---

## Error Handling

### Player Not in Cache

```python
if player_lookup not in cache_dict:
    logger.warning(f"Player {player_lookup} not in cache")

    # Option 1: Skip (most common)
    return None

    # Option 2: Fallback to real-time query (slower)
    cache_data = query_player_cache_realtime(player_lookup)
    if cache_data:
        return generate_prediction(cache_data, latest_odds)

    # Option 3: Use last-known data (stale but better than nothing)
    cache_data = query_player_cache_yesterday(player_lookup)
    if cache_data:
        logger.warning("Using yesterday's cache data")
        return generate_prediction(cache_data, latest_odds)
```

### Low Feature Quality

```python
if feature_quality_score < 70:
    logger.warning(f"Low quality features for {player_lookup}: {feature_quality_score}")

    # Downgrade confidence
    confidence = confidence * 0.8

    # Add warning flag
    prediction['quality_warning'] = True
    prediction['warning_reason'] = 'insufficient_historical_data'
```

### Model Disagreement

```python
model_std = np.std([
    predictions['xgboost'],
    predictions['moving_avg'],
    predictions['zone_matchup'],
    predictions['similarity']
])

if model_std > 3.0:  # Models disagree by >3 points
    logger.warning(f"High model disagreement for {player_lookup}: {model_std}")

    # Reduce confidence
    confidence = confidence * 0.7

    # Flag for review
    prediction['disagreement_flag'] = True
    prediction['model_std_dev'] = model_std
```

---

## Monitoring & Alerts

### Real-Time Metrics

| Metric | Threshold | Severity |
|--------|-----------|----------|
| Prediction latency (per player) | > 500ms | Warning |
| Prediction latency (per player) | > 1000ms | Critical |
| Cache hit rate | < 95% | Warning |
| Feature quality avg | < 80 | Warning |
| Model agreement avg | < 70 | Warning |
| Predictions/minute | < 20 (during active hours) | Warning |

### Daily Aggregates

| Metric | Expected | Threshold |
|--------|----------|-----------|
| Total predictions | 40,000-50,000/day | < 30,000 = Warning |
| Avg confidence | 75-85 | < 70 = Warning |
| High-confidence picks | 50-100/day | < 30 = Warning |
| Cache reloads | 1/day | > 3 = Warning |

---

## Quick Links

- 🤖 **Phase 5 Processor Card**: `docs/processor-cards/phase5-prediction-coordinator.md`
- 🎯 **Phase 5 Getting Started**: `docs/predictions/tutorials/01-getting-started.md`
- 📄 **Phase 5 Deployment**: `docs/predictions/operations/01-deployment-guide.md`
- 🔍 **Phase 5 Troubleshooting**: `docs/predictions/operations/03-troubleshooting.md`
- 📊 **Daily Timeline**: `docs/processor-cards/workflow-daily-processing-timeline.md`
- 📊 **ML Feature Store**: `docs/processor-cards/phase4-ml-feature-store-v2.md`
- 🗂️ **Player Daily Cache**: `docs/processor-cards/phase4-player-daily-cache.md`
- 📈 **All Processor Cards**: `docs/processor-cards/README.md`

---

**Card Version**: 1.1
**Created**: 2025-11-15
**Last Updated**: 2025-11-15
**Verified Against**: Phase 5 prediction architecture (design doc)
**Changes**: v1.1 - Added Phase 5 processor card references and quick links
