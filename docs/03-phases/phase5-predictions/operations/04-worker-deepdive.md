# Phase 5 Worker Deep-Dive

**File:** `docs/processors/12-phase5-worker-deepdive.md`
**Created:** 2025-11-09 15:30 PST
**Last Updated:** 2025-11-15 17:00 PST
**Purpose:** Advanced technical deep-dive into Phase 5 worker internals - model loading, concurrency, performance optimization
**Status:** Draft (awaiting deployment)

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Why Worker Orchestration is Complex](#complexity)
3. [Model Loading & Lifecycle Management](#model-loading)
4. [Feature Loading Strategy](#feature-loading)
5. [Worker Concurrency Model](#concurrency-model)
6. [BigQuery Write Strategy](#bigquery-writes)
7. [System Integration & Interface Handling](#system-integration)
8. [Detailed Data Flow](#data-flow)
9. [Performance Optimization](#performance-optimization)
10. [Related Documentation](#related-docs)

---

## 🎯 Overview {#overview}

### The Challenge

The Phase 5 Prediction Worker is the most operationally complex component in the platform because it:

- **Manages 5 Different Prediction Systems** - Each with unique interfaces and requirements
- **Handles Real-Time Scaling** - 0 to 20 instances based on queue depth
- **Loads Data from Multiple Sources** - Features (Phase 4) + Historical Games (Phase 3)
- **Writes High-Volume Data** - 11,250 predictions daily with streaming inserts
- **Maintains Low Latency** - Must process 450 players in 2-3 minutes
- **Ensures Graceful Degradation** - Continues even when systems fail

### Critical Success Factors

| Factor | Requirement | Impact if Failed |
|--------|-------------|------------------|
| **Model Initialization** | All 5 systems loaded at startup | Worker crashes or gives wrong predictions |
| **Feature Quality** | Quality score ≥70 | Unreliable predictions |
| **System Availability** | ≥4/5 systems working | Ensemble predictions fail |
| **Write Performance** | <100ms per player | Queue backup, timeout failures |
| **Cold Start Time** | <30 seconds | Slow scaling during batch start |

### Position in Phase 5 Pipeline

```
PHASE 5 WORKER - COMPLETE DATA FLOW
════════════════════════════════════════════════════════════════

6:15 AM ┌─────────────────────────────────┐
        │ Coordinator                     │ (1 min)
        │ - Query 450 players             │
        │ - Publish 450 messages          │
        └─────────────────────────────────┘
             ↓ (publishes: prediction-request × 450)

6:16 AM ┌─────────────────────────────────┐
        │ Workers: 0 → 5 instances        │ (cold start: 30s)
        │ Auto-scaling begins             │
        └─────────────────────────────────┘
             ↓

6:16:30 ┌─────────────────────────────────┐
        │ Workers: 5 → 20 instances       │
        │ Full capacity: 100 concurrent   │
        │                                 │
        │ ⭐ THIS COMPONENT ⭐            │
        │                                 │
        │ Per-Worker Processing:          │
        │ 1. Load features (10-20ms)      │
        │ 2. Load historical (50-100ms)   │
        │ 3. Run 5 systems (50-100ms)     │
        │ 4. Write to BigQuery (50ms)     │
        │ 5. Publish completion (10ms)    │
        │                                 │
        │ Total: ~200-300ms per player    │
        └─────────────────────────────────┘
             ↓ (2-3 min processing)

6:18:30 ┌─────────────────────────────────┐
        │ Workers complete                │
        │ All 450 players processed       │
        │ 11,250 predictions written      │
        └─────────────────────────────────┘
```

---

## 🔧 Why Worker Orchestration is Complex {#complexity}

### 1. Five Different System Interfaces

Unlike Phase 4 processors (uniform interface), Phase 5 systems have inconsistent APIs:

```python
# System 1 & 2: Tuple return, features first
predicted_points, confidence, recommendation = moving_average.predict(
    features=features,
    player_lookup=player_lookup,
    game_date=game_date,
    prop_line=line_value
)

# System 3 & 4: Dict return, player first
result = similarity.predict(
    player_lookup=player_lookup,
    features=features,
    historical_games=historical_games,  # REQUIRED!
    betting_line=line_value
)
predicted_points = result['predicted_points']

# System 5: 4-tuple return, combines all
predicted, confidence, recommendation, metadata = ensemble.predict(
    features=features,
    player_lookup=player_lookup,
    game_date=game_date,
    prop_line=line_value,
    historical_games=historical_games  # Optional
)
```

**Challenge:** Worker must handle 3 different calling conventions and 3 different return formats.

### 2. Confidence Scale Normalization

Systems use different confidence scales:

```python
# Moving Average, Zone Matchup, Ensemble
confidence = 0.65  # 0.0-1.0 scale (65%)

# Similarity, XGBoost
confidence = 72.5  # 0-100 scale (72.5%)
```

**Challenge:** Must normalize to 0-100 for BigQuery storage:

```python
def normalize_confidence(confidence: float, system_id: str) -> float:
    if system_id in ['moving_average', 'zone_matchup_v1', 'ensemble_v1']:
        return confidence * 100.0  # Convert 0.0-1.0 to 0-100
    else:
        return confidence  # Already 0-100
```

### 3. Data Dependencies Vary by System

| System | Needs Features | Needs Historical Games | Can Function Without History |
|--------|----------------|------------------------|------------------------------|
| Moving Average | ✅ Required | ❌ Not used | ✅ Yes |
| Zone Matchup | ✅ Required | ❌ Not used | ✅ Yes |
| Similarity | ✅ Required | ✅ REQUIRED | ❌ No - skipped if missing |
| XGBoost | ✅ Required | ❌ Not used | ✅ Yes |
| Ensemble | ✅ Required | ⚠️ Optional | ✅ Yes (passes to Similarity) |

**Challenge:** Must load historical games even though only 1 system needs them.

### 4. Graceful Degradation Requirements

```python
# What happens if systems fail?
system_predictions = {}

try:
    system_predictions['moving_average'] = moving_average.predict(...)
except Exception as e:
    logger.error(f"Moving Average failed: {e}")
    system_predictions['moving_average'] = None
    # ✅ Continue with remaining systems!

try:
    system_predictions['zone_matchup'] = zone_matchup.predict(...)
except Exception as e:
    logger.error(f"Zone Matchup failed: {e}")
    system_predictions['zone_matchup'] = None
    # ✅ Continue!

# Ensemble requires ≥2 base systems to work
# If 0-1 systems work → No ensemble prediction
# If 2-4 systems work → Ensemble still works!
```

**Challenge:** Must track failures, continue processing, and still write partial results.

### 5. Cold Start Performance

```
Worker Instance Lifecycle:
──────────────────────────
0s     - Cloud Run receives first request
0-5s   - Container starts, Flask initializes
5-10s  - Import prediction system modules
10-25s - Initialize all 5 systems:
         • Moving Average: ~2s (simple)
         • Zone Matchup: ~3s (zone calculations)
         • Similarity: ~5s (similarity scoring setup)
         • XGBoost: ~8s (load mock model - 500MB in prod!)
         • Ensemble: ~2s (wire up base systems)
25-30s - Worker ready to handle requests

First request latency: 30 seconds (cold start)
Subsequent requests: ~200-300ms (warm)
```

**Challenge:** 30-second cold start delays batch processing start. Need warm instances or fast initialization.

---

## 🚀 Model Loading & Lifecycle Management {#model-loading}

### Current Implementation: Module-Level Initialization

**Location:** `predictions/worker/worker.py` (lines 30-60)

```python
# ============================================================================
# MODULE-LEVEL INITIALIZATION (runs ONCE at import time)
# ============================================================================

# Initialize components (reused across requests)
data_loader = PredictionDataLoader(PROJECT_ID)
bq_client = bigquery.Client(project=PROJECT_ID)
pubsub_publisher = pubsub_v1.PublisherClient()

# Initialize player registry for universal_player_id lookup
logger.info("Initializing player registry...")
player_registry = RegistryReader(
    project_id=PROJECT_ID,
    source_name='prediction_worker',
    cache_ttl_seconds=300  # 5-minute cache
)

# Initialize prediction systems (LOADED ONCE, REUSED FOREVER)
logger.info("Initializing prediction systems...")
moving_average = MovingAverageBaseline()
zone_matchup = ZoneMatchupV1()
similarity = SimilarityBalancedV1()
xgboost = XGBoostV1()  # Loads mock model by default

# Initialize ensemble with base systems
ensemble = EnsembleV1(
    moving_average_system=moving_average,
    zone_matchup_system=zone_matchup,
    similarity_system=similarity,
    xgboost_system=xgboost
)

logger.info("All prediction systems initialized successfully")

# Now Flask app starts...
app = Flask(__name__)
```

### Why Module-Level?

**Advantages ✅:**
- Memory Efficient - Models loaded once, shared across all requests
- Fast Request Handling - No per-request model loading overhead
- Simple Code - No explicit model caching logic needed
- Thread-Safe - Python modules are imported once per process

**Disadvantages ❌:**
- Slow Cold Start - 30 seconds to initialize everything
- Inflexible - Can't reload models without restarting instance
- Memory Footprint - All models always in memory (even if not used)

### Memory Footprint Analysis

```
Per Worker Instance Memory Usage:
─────────────────────────────────
Base Flask App:           ~100 MB
BigQuery Client:          ~50 MB
Pub/Sub Publisher:        ~20 MB
Player Registry Cache:    ~10 MB
Data Loader:              ~10 MB

Prediction Systems:
├─ Moving Average:        ~5 MB  (minimal - just formulas)
├─ Zone Matchup:          ~10 MB (zone scoring tables)
├─ Similarity:            ~20 MB (similarity scoring logic)
├─ XGBoost (Mock):        ~50 MB (mock model)
│  └─ XGBoost (Prod):     ~500 MB (REAL model - trained on 4 years!)
└─ Ensemble:              ~5 MB  (wrapper around base systems)

Thread Overhead (5 threads):
├─ Thread 1-5:            ~2 MB each = ~10 MB

Total (Dev):              ~280 MB
Total (Prod with real XGBoost): ~730 MB
Cloud Run Allocation:     2 Gi (2048 MB)
Headroom:                 ~1.3 GB (sufficient)
```

### Cold Start Optimization Strategy

**Current:** 30-second cold start

**Optimization 1: Pre-Load Models in Container (saves 5s)**

```dockerfile
# In Dockerfile
RUN python -c "from prediction_systems import *"
# Pre-compile Python bytecode, cache imports
```

**Optimization 2: Lazy Loading (saves 15s, but complicates code)**

```python
# Don't load all systems at startup
# Load on first use per system

@lru_cache(maxsize=1)
def get_xgboost_system():
    """Lazy-load XGBoost only when first needed"""
    logger.info("Loading XGBoost model...")
    return XGBoostV1()

# First request using XGBoost: ~8s delay
# Subsequent requests: instant (cached)
```

**Recommendation:** Keep module-level for v1.0 (simplicity). Consider lazy loading only if cold start becomes problem.

### Model Update Strategy

**Question:** How to deploy new model versions without downtime?

**Option A: Rolling Update (Current approach)**

```bash
# Deploy new model version
gcloud run services update prediction-worker \
  --image gcr.io/.../prediction-worker:v1.1 \
  --region us-central1

# Cloud Run gradually shifts traffic:
# - Starts new instances with v1.1
# - Drains old instances with v1.0
# - Zero downtime (old requests finish on old instances)
```

**Option B: Blue-Green Deployment (Future)**

```bash
# Deploy v1.1 to separate service (prediction-worker-v1-1)
# Test with 10% traffic
# Switch 100% traffic if tests pass
# Rollback instantly if problems
```

**Recommendation:** Use Rolling Update (Option A) for v1.0. Simple and sufficient.

---

## 📊 Feature Loading Strategy {#feature-loading}

### Current Implementation: Per-Message Query

**Location:** `predictions/worker/data_loaders.py` `load_features()`

```python
def load_features(
    self,
    player_lookup: str,
    game_date: date,
    feature_version: str = 'v1_baseline_25'
) -> Optional[Dict]:
    """
    Load 25 features from ml_feature_store_v2

    Performance: ~10-20ms per player
    """
    query = """
    SELECT
        features,
        feature_names,
        feature_quality_score,
        data_source
    FROM `{project}.nba_predictions.ml_feature_store_v2`
    WHERE player_lookup = @player_lookup
      AND game_date = @game_date
      AND feature_version = @feature_version
    LIMIT 1
    """

    # Execute query
    results = self.client.query(query, job_config=job_config).result()
    row = next(results, None)

    if row is None:
        logger.warning(f"No features found for {player_lookup}")
        return None

    # Convert arrays to dict with named features
    feature_array = row.features
    feature_names = row.feature_names
    features = dict(zip(feature_names, feature_array))

    # Add metadata
    features['feature_count'] = len(feature_array)
    features['feature_version'] = feature_version
    features['data_source'] = row.data_source
    features['feature_quality_score'] = float(row.feature_quality_score)

    return features
```

### Performance Characteristics

**Single Player Query:**
- Query compilation: ~2-5ms
- BigQuery execution: ~5-10ms
- Network transfer: ~3-5ms
- **Total: ~10-20ms per player**

**Daily Volume:**
- 450 players × 1 query each = 450 queries
- 450 queries × 15ms avg = 6,750ms = 6.75 seconds total
- This is distributed across 20 workers, so per-worker: ~0.34 seconds

**Cost:**
```
Data Scanned per Query:
- ml_feature_store_v2 is tiny (~1 MB per day, partitioned by game_date)
- Each query scans ~2 KB (one player row)
- 450 queries × 2 KB = 900 KB = 0.0009 GB

BigQuery Cost:
- $5 per TB scanned
- 0.0009 GB = 0.0000009 TB
- 0.0000009 TB × $5 = $0.0000045 per day (~half a cent per month)
```

**Verdict:** Current approach is fast enough and cheap. No optimization needed for v1.0.

### Why Not Batch Load?

**Option:** Coordinator Pre-Loads Features

Advantages:
- 135x faster (50ms for all 450 vs 6.75s for 450 individual queries)

Disadvantages:
- Must include features in Pub/Sub message (large payload: ~5 KB per player)
- Coordinator query time increases (50ms is noticeable)
- Worker doesn't validate features (trusts coordinator)

**Recommendation:** Keep current approach for v1.0. Consider batch if query time becomes bottleneck (it won't - 6.75s distributed across 20 workers = 0.34s each).

### Feature Validation (NEW in v1.1)

```python
def validate_features(features: Dict, min_quality_score: float = 70.0) -> tuple:
    """
    Validate features before running predictions

    Checks:
    1. All 25 required fields present
    2. No null/NaN values
    3. Quality score ≥ threshold (default 70)
    4. Values in reasonable ranges

    Returns:
        (is_valid, list_of_errors)
    """
    errors = []

    # Check 1: Required fields
    required_fields = [
        'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
        # ... 22 more fields
    ]
    missing = [f for f in required_fields if f not in features]
    if missing:
        errors.append(f"Missing fields: {', '.join(missing)}")
        return False, errors

    # Check 2: Quality threshold
    quality = features.get('feature_quality_score', 0)
    if quality < min_quality_score:
        errors.append(f"Quality {quality} < {min_quality_score}")
        return False, errors

    # Check 3: No nulls
    for field in required_fields:
        if features[field] is None:
            errors.append(f"{field} is None")

    # Check 4: Range validation
    if not (0 <= features['points_avg_season'] <= 60):
        errors.append("points_avg_season out of range")

    return (len(errors) == 0), errors
```

**Usage in Worker:**

```python
features = data_loader.load_features(player_lookup, game_date)

# NEW: Validate before running predictions
is_valid, errors = validate_features(features, min_quality_score=70.0)
if not is_valid:
    logger.error(f"Invalid features for {player_lookup}: {errors}")
    return []  # Skip player, don't crash

# Features validated - proceed with predictions
for system in prediction_systems:
    system.predict(features, ...)
```

**Why This Matters:**
- Prevents predictions on bad data (early season, incomplete Phase 4)
- Logs specific validation errors (easier debugging)
- Graceful degradation (skip player, continue batch)

---

## ⚡ Worker Concurrency Model {#concurrency-model}

### Cloud Run Native Concurrency

**Key Concept:** Cloud Run handles threading automatically using `--concurrency` flag.

```bash
# Cloud Run Configuration
concurrency: 5              # Handle 5 concurrent HTTP requests per instance
max-instances: 20           # Scale up to 20 instances
min-instances: 0            # Scale to zero when idle (dev)
               1            # Keep 1 warm (prod)
timeout: 300s               # 5 minutes per request
memory: 2Gi                 # 2 GB RAM
cpu: 2                      # 2 vCPUs
```

### How It Works

```
Single Worker Instance:
─────────────────────────────────────────────────────

┌──────────────────────────────────────────────────┐
│  Cloud Run Instance (2 vCPU, 2 GB RAM)           │
│                                                   │
│  ┌────────────────────────────────────────────┐ │
│  │  Flask App (1 process)                     │ │
│  │                                            │ │
│  │  Thread 1: /predict (lebron-james)        │ │
│  │  Thread 2: /predict (stephen-curry)       │ │
│  │  Thread 3: /predict (luka-doncic)         │ │
│  │  Thread 4: /predict (kevin-durant)        │ │
│  │  Thread 5: /predict (giannis-antetokounmpo)│ │
│  │                                            │ │
│  │  All threads share:                        │ │
│  │  - prediction_systems (models)             │ │
│  │  - data_loader (BigQuery client)           │ │
│  │  - bq_client (connection pool)             │ │
│  │  - pubsub_publisher                        │ │
│  └────────────────────────────────────────────┘ │
│                                                   │
│  Processing:                                      │
│  - Thread 1-5 run independently                  │
│  - No explicit locks needed (models are read-only)│
│  - Each thread has own request context           │
│  - Avg time per thread: ~200-300ms              │
│                                                   │
└──────────────────────────────────────────────────┘
```

### Thread Safety Considerations

**Q: Are shared objects thread-safe?**

**Prediction Systems ✅ Thread-Safe**

```python
# All 5 systems are STATELESS (no mutable shared state)
# Each predict() call is independent
# Multiple threads can call predict() simultaneously

moving_average.predict(features, ...)  # Thread 1
moving_average.predict(features, ...)  # Thread 2 (simultaneous)
# ✅ No problem - no shared mutable state
```

**BigQuery Client ✅ Thread-Safe**

```python
# BigQuery client uses connection pooling internally
# Thread-safe by design

bq_client.query(...)  # Thread 1
bq_client.query(...)  # Thread 2 (simultaneous)
# ✅ No problem - connection pool handles concurrency
```

**Pub/Sub Publisher ✅ Thread-Safe**

```python
# Pub/Sub publisher is thread-safe

pubsub_publisher.publish(...)  # Thread 1
pubsub_publisher.publish(...)  # Thread 2 (simultaneous)
# ✅ No problem - internal batching/buffering
```

**No Locks Needed:** All shared objects are either:
- Stateless (prediction systems)
- Internally thread-safe (BigQuery, Pub/Sub clients)

---

## 💾 BigQuery Write Strategy {#bigquery-writes}

### Current Implementation: Streaming Insert Per Player

**Location:** `predictions/worker/worker.py` `write_predictions_to_bigquery()`

```python
def write_predictions_to_bigquery(predictions: List[Dict]):
    """
    Write predictions to BigQuery player_prop_predictions table

    Uses streaming insert for low latency

    Args:
        predictions: List of prediction dicts (5 rows per player)
    """
    if not predictions:
        logger.warning("No predictions to write")
        return

    table_id = f"{PROJECT_ID}.{PREDICTIONS_TABLE}"

    try:
        # Streaming insert (immediate, no batching)
        errors = bq_client.insert_rows_json(table_id, predictions)

        if errors:
            logger.error(f"Errors writing to BigQuery: {errors}")
            # Don't raise - log and continue (graceful degradation)
        else:
            logger.info(f"Successfully wrote {len(predictions)} predictions")

    except Exception as e:
        logger.error(f"Error writing to BigQuery: {e}")
        # Don't raise - log and continue
```

### Write Pattern: Immediate Per-Player

```
Worker Processing Flow:
───────────────────────────────────────────────────

Worker receives message for "lebron-james"
    ↓
Load features (~15ms)
    ↓
Load historical games (~75ms)
    ↓
Run 5 prediction systems (~100ms)
    ↓
Format 5 predictions for BigQuery (~5ms)
    ↓
Write 5 rows to BigQuery (~50ms) ← HERE
    ↓
Publish completion event (~10ms)
    ↓
Total: ~255ms per player

BigQuery Writes per Day:
- 450 players × 5 systems = 2,250 rows (single line mode)
- 450 players × 5 lines × 5 systems = 11,250 rows (multi-line mode)
- Each write: 5 rows (one player, all 5 systems)
- Total writes: 450 writes per day
```

### Streaming Insert Characteristics

**Advantages ✅:**
- Low Latency - Data available immediately in BigQuery (~1-2 seconds)
- Simple Code - One API call, no batching logic
- Reliable - BigQuery handles deduplication, retries internally
- Idempotent - Safe to retry same write (unique prediction_id)

**Disadvantages ❌:**
- Cost - Streaming insert costs 5x more than batch load ($0.05 per GB vs $0.01 per GB)
- Not DML - Can't UPDATE rows (must INSERT new versions)
- Buffer Lag - 90-minute buffer before data appears in streaming buffer

**Cost Analysis:**

```
Row Size: ~1 KB (prediction record with all fields)
Daily Volume (single line mode):
  450 players × 5 systems × 1 KB = 2,250 KB = 2.2 MB per day

Streaming Insert Cost:
  $0.05 per GB
  0.0022 GB × $0.05 = $0.00011 per day
  $0.00011 × 30 = $0.0033 per month (less than half a cent!)

Multi-line Mode (5 lines per player):
  11,250 rows × 1 KB = 11 MB per day
  0.011 GB × $0.05 = $0.00055 per day
  $0.00055 × 30 = $0.0165 per month (~2 cents)
```

**Verdict:** Cost is negligible. Use streaming insert for v1.0.

---

## 🔗 System Integration & Interface Handling {#system-integration}

### The Interface Challenge

Phase 5 has 5 prediction systems built at different times with inconsistent APIs.

### Worker Integration Strategy

**Step 1: Normalize System Calls**

```python
# In worker.py process_player_predictions()
system_predictions = {}

# Call each system with try-catch (graceful degradation)
for system_id, system in SYSTEMS.items():
    try:
        if system_id == 'moving_average':
            pred, conf, rec = system.predict(
                features=features,
                player_lookup=player_lookup,
                game_date=game_date,
                prop_line=line_value
            )
            system_predictions[system_id] = {
                'predicted_points': pred,
                'confidence': conf,
                'recommendation': rec,
                'system_type': 'tuple'
            }

        elif system_id == 'similarity_balanced_v1':
            # Check historical games available (REQUIRED!)
            if not historical_games:
                logger.debug(f"Skipping Similarity - no historical games")
                system_predictions[system_id] = None
                continue

            result = system.predict(
                player_lookup=player_lookup,
                features=features,
                historical_games=historical_games,
                betting_line=line_value
            )

            if result['predicted_points'] is not None:
                system_predictions[system_id] = {
                    'predicted_points': result['predicted_points'],
                    'confidence': result['confidence_score'],
                    'recommendation': result['recommendation'],
                    'system_type': 'dict',
                    'metadata': result  # Keep full dict for component fields
                }
            else:
                system_predictions[system_id] = None

        # ... similar for other systems

    except Exception as e:
        logger.error(f"{system_id} failed for {player_lookup}: {e}")
        system_predictions[system_id] = None
```

**Step 2: Normalize Confidence Scores**

```python
def normalize_confidence(confidence: float, system_id: str) -> float:
    """
    Normalize confidence to 0-100 scale for BigQuery

    Different systems use different scales:
    - Moving Average, Zone Matchup, Ensemble: 0.0-1.0
    - Similarity, XGBoost: 0-100
    """
    if system_id in ['moving_average', 'zone_matchup_v1', 'ensemble_v1']:
        # Convert 0.0-1.0 to 0-100
        return confidence * 100.0
    elif system_id in ['similarity_balanced_v1', 'xgboost_v1']:
        # Already 0-100
        return confidence
    else:
        logger.warning(f"Unknown system_id {system_id}, assuming 0-100")
        return confidence
```

### Handling System Failures

**Graceful Degradation Matrix:**

| Failed System | Impact | Ensemble Behavior |
|---------------|--------|-------------------|
| Moving Average | Low | Ensemble uses remaining 3 systems |
| Zone Matchup | Low | Ensemble uses remaining 3 systems |
| Similarity | Medium | Ensemble uses remaining 3 systems |
| XGBoost | Medium | Ensemble uses remaining 3 systems |
| 2 systems fail | High | Ensemble still works (uses 2 remaining) |
| 3+ systems fail | Critical | Ensemble cannot generate prediction (needs ≥2) |

**Minimum System Requirements:**

```python
# In ensemble_v1.py
def predict(self, features, player_lookup, game_date, prop_line, historical_games=None):
    """
    Ensemble requires minimum 2 base systems to function
    """
    # Collect predictions from all 4 base systems
    base_predictions = []

    try:
        pred, conf, rec = self.moving_average_system.predict(...)
        base_predictions.append({'system': 'moving_average', 'pred': pred, 'conf': conf})
    except:
        pass

    try:
        pred, conf, rec = self.zone_matchup_system.predict(...)
        base_predictions.append({'system': 'zone_matchup', 'pred': pred, 'conf': conf})
    except:
        pass

    # ... try Similarity and XGBoost

    # Check minimum requirement
    if len(base_predictions) < 2:
        logger.error(f"Ensemble needs ≥2 systems, only {len(base_predictions)} available")
        return (None, None, None, {'error': 'insufficient_systems'})

    # Weighted average of available systems
    total_weight = sum(p['conf'] for p in base_predictions)
    weighted_pred = sum(p['pred'] * p['conf'] for p in base_predictions) / total_weight

    # Ensemble confidence based on agreement
    variance = np.var([p['pred'] for p in base_predictions])
    ensemble_confidence = 0.7 if variance < 2.0 else 0.5

    return (weighted_pred, ensemble_confidence, recommendation, metadata)
```

---

## 📊 Detailed Data Flow {#data-flow}

### Complete Request Processing

```
PHASE 5 WORKER - COMPLETE DATA FLOW
════════════════════════════════════════════════════════════════

┌────────────────────────────────────────────────────────────┐
│ INPUT: Pub/Sub Push Request                                │
│                                                            │
│ POST /predict                                              │
│ Headers: Content-Type: application/json                   │
│ Body: {"message": {"data": "base64_encoded_json"}}        │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ STEP 1: Decode & Parse (5ms)                              │
│ Extracted: player_lookup, game_date, line_values          │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ STEP 2: Load Features from BigQuery (10-20ms)             │
│ Result: 25 features + quality_score                       │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ STEP 2b: Validate Features (2ms)                          │
│ Checks: 25 fields present, quality ≥ 70, no nulls         │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ STEP 3: Load Historical Games (50-100ms)                  │
│ Result: 30 recent games with context                      │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ STEP 4: Run Prediction Systems (50-100ms total)           │
│                                                            │
│ System 1: Moving Average (~10ms)                          │
│ System 2: Zone Matchup (~15ms)                            │
│ System 3: Similarity (~25ms)                              │
│ System 4: XGBoost (~20ms)                                 │
│ System 5: Ensemble (~30ms)                                │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ STEP 5: Format Predictions for BigQuery (5ms)             │
│ Result: 5 prediction records (one per system)             │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ STEP 6: Write to BigQuery (50ms)                          │
│ Streaming Insert: 5 rows written                          │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ STEP 7: Publish Completion Event (10ms)                   │
│ Pub/Sub: "prediction-ready" message                       │
└────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────┐
│ OUTPUT: HTTP 204 No Content                                │
│ Total Processing Time: ~200-300ms                         │
└────────────────────────────────────────────────────────────┘
```

### Data Volume Analysis

**Per-Player Data Flow:**
- Input (Pub/Sub message): ~500 bytes JSON
- Features (BigQuery): ~2 KB
- Historical Games (BigQuery): ~5 KB
- Predictions (BigQuery write): ~5 KB
- Completion Event (Pub/Sub): ~300 bytes
- **Total per player:** ~12.8 KB

**Daily Volume:**

Single Line Mode:
```
450 players × 12.8 KB = 5.76 MB input/output
450 players × 5 systems × 1 KB = 2.25 MB stored
```

Multi-Line Mode:
```
450 players × 5 lines × 12.8 KB = 28.8 MB input/output
450 players × 5 lines × 5 systems × 1 KB = 11.25 MB stored
```

---

## ⚡ Performance Optimization {#performance-optimization}

### Current Performance Baseline

```
Processor: prediction_worker
Players: 450
Duration: 2-3 minutes (target), 5 minutes (max)
Per-player: ~200-300ms average

Breakdown:
  Features load: 10-20ms (10%)
  Historical games load: 50-100ms (40%)
  5 systems predict: 50-100ms (40%)
  BigQuery write: 50ms (20%)
  Pub/Sub publish: 10ms (5%)
  Overhead: 20-50ms (10%)
```

### Optimization 1: Batch Historical Games Loading

**Current:** 450 separate queries (one per player)

```python
for player in players:
    historical = data_loader.load_historical_games(player, game_date)
    # Each query: ~75ms
# Total: 450 × 75ms = 33,750ms = 33.75 seconds
```

**Optimized:** Single batch query

```python
def load_historical_games_batch(
    player_list: List[str],
    game_date: date
) -> Dict[str, List[Dict]]:
    """
    Load historical games for multiple players in one query

    Performance: 450 players in ~500ms (vs 33.75s)
    Speedup: 67x faster!
    """
    query = """
    WITH recent_games AS (
      SELECT
        player_lookup,
        game_date,
        opponent_team_abbr,
        is_home,
        days_rest,
        points,
        opponent_def_rating_last_15,
        points_avg_last_5,
        points_avg_season,
        ROW_NUMBER() OVER (
          PARTITION BY player_lookup
          ORDER BY game_date DESC
        ) as game_rank
      FROM `{project}.nba_analytics.player_game_summary`
      WHERE player_lookup IN UNNEST(@player_list)
        AND game_date < @game_date
        AND game_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
    )
    SELECT *
    FROM recent_games
    WHERE game_rank <= 30  -- Max 30 games per player
    ORDER BY player_lookup, game_date DESC
    """

    results = self.client.query(
        query,
        query_parameters=[
            bigquery.ArrayQueryParameter("player_list", "STRING", player_list),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    ).result()

    # Group results by player
    games_by_player = {}
    for row in results:
        player = row.player_lookup
        if player not in games_by_player:
            games_by_player[player] = []

        games_by_player[player].append({
            'game_date': row.game_date.isoformat(),
            'opponent_tier': self._calculate_opponent_tier(row.opponent_def_rating_last_15),
            'recent_form': self._calculate_recent_form(row.points_avg_last_5, row.points_avg_season),
            'points': float(row.points),
            # ... other fields
        })

    return games_by_player
```

**Tradeoffs:**
- **Pros:** 67x faster, reduces BigQuery queries from 450 to 1
- **Cons:** Larger Pub/Sub messages (~10 KB instead of 500 bytes), coordinator takes longer (but only once)

**Estimated Impact:** Reduces per-player processing from 300ms to 225ms (25% faster)

### Optimization 2: Model Warm-Up Script

**Current:** Cold start takes 30 seconds

**Optimized:** Pre-warm models in container build

```dockerfile
# In Dockerfile
FROM python:3.11-slim

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-import and warm up prediction systems
COPY predictions /app/predictions
WORKDIR /app

# NEW: Warm up at build time
RUN python -c "
from predictions.worker.prediction_systems import *
import logging
logging.basicConfig(level=logging.INFO)

# Initialize all systems (compiles code, loads models)
print('Warming up prediction systems...')
ma = MovingAverageBaseline()
zm = ZoneMatchupV1()
sb = SimilarityBalancedV1()
xg = XGBoostV1()
ens = EnsembleV1(ma, zm, sb, xg)
print('Warm-up complete!')
"

# Continue with normal container setup
CMD ["python", "predictions/worker/worker.py"]
```

**Estimated Impact:** Reduces cold start from 30s to 20s (33% faster)

### Cumulative Impact

**If all optimizations implemented:**

```
Baseline: 300ms per player
  - Historical games batch: -75ms (300 → 225ms)
  - Concurrent systems: -80ms (225 → 145ms)
  - Buffer batching: -50ms (145 → 95ms)

Optimized: 95ms per player (68% faster!)

Total batch time:
  Baseline: 450 × 300ms / 100 concurrent = 1,350ms = 1.35 min
  Optimized: 450 × 95ms / 100 concurrent = 428ms = 0.43 min

Speedup: 3.1x faster (1.35min → 0.43min)
```

**Recommendation:** Implement Optimization 1 (batch historical games) in v1.1 for biggest impact with minimal complexity.

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 Docs:**
- **Operations Guide:** `09-phase5-operations-guide.md` - Coordinator/worker configuration, Pub/Sub topics
- **Scheduling Strategy:** `10-phase5-scheduling-strategy.md` - Cloud Scheduler, dependency management, retry strategy
- **Troubleshooting:** `11-phase5-troubleshooting.md` - Failure scenarios, incident response, manual operations

**Upstream Dependencies:**
- **Phase 4 Deep-Dive:** `08-phase4-ml-feature-store-deepdive.md` - Feature generation (ml_feature_store_v2)
- **Phase 3 Operations:** `02-phase3-operations-guide.md` - Upcoming player game context

**Architecture:**
- **Pipeline Overview:** `docs/01-architecture/pipeline-design.md`
- **v1.0 Orchestration:** `docs/01-architecture/orchestration/`

---

**Last Updated:** 2025-11-15 17:00 PST
**Next Review:** After Phase 5 performance benchmarking
**Status:** Draft - Ready for implementation review
