# Option A: MLB Multi-Model System Optimization - Implementation Handoff

**Created**: 2026-01-17
**Status**: Ready for Implementation
**Estimated Duration**: 4-6 hours
**Priority**: Medium (Performance & Quality Improvement)

---

## Executive Summary

Optimize the MLB multi-model prediction worker to improve batch processing efficiency, add feature coverage monitoring, and implement system-specific metrics. The current implementation has inefficiencies in how it loads features for multiple prediction systems and lacks visibility into data quality issues.

### What Gets Better
- **30-40% faster batch predictions** through shared feature loading
- **Data quality visibility** via feature coverage metrics
- **Better reliability** through improved IL pitcher cache handling
- **Operational flexibility** via configurable alert thresholds

---

## Current State (As of 2026-01-17)

### What's Working
- ✅ MLB prediction worker v2.0.0 deployed to Cloud Run
- ✅ Three systems running concurrently (v1_baseline, v1_6_rolling, ensemble_v1)
- ✅ Service healthy at: https://mlb-prediction-worker-756957797294.us-central1.run.app/
- ✅ BigQuery schema migration complete (system_id column exists)
- ✅ Monitoring views created (5 views)

### Current Issues

**Issue 1: Inefficient Batch Feature Loading**
- Location: `/predictions/mlb/worker.py:run_multi_system_batch_predictions()`
- Problem: Loads features using V1 system, then passes same features to V1.6 and Ensemble
- Impact: Unnecessary BigQuery queries, slower batch processing
- Evidence:
  ```python
  # Current implementation (lines ~240-280)
  pitcher_lookups = _get_pitchers_for_game_date(game_date)

  for pitcher_lookup in pitcher_lookups:
      # V1 loads features from BigQuery
      v1_result = v1_predictor.predict(...)

      # V1.6 loads SAME features again from BigQuery
      v1_6_result = v1_6_predictor.predict(...)

      # Ensemble loads SAME features AGAIN
      ensemble_result = ensemble_predictor.predict(...)
  ```

**Issue 2: No Feature Coverage Metrics**
- Location: `/predictions/mlb/base_predictor.py` and all system predictors
- Problem: Missing features default to hardcoded values with no visibility
- Impact: False confidence in low-data scenarios, no way to detect data quality issues
- Example: If 10/35 features are missing, confidence still shows 75%

**Issue 3: IL Pitcher Cache Failure Handling**
- Location: `/predictions/mlb/base_predictor.py:_get_current_il_pitchers()`
- Problem: Falls back to stale cache if BigQuery query fails
- Impact: Could miss recently injured pitchers, generate bad predictions
- Code:
  ```python
  except Exception as e:
      logger.warning(f"IL query failed, using stale cache: {e}")
      return self._il_cache  # Could be hours old
  ```

**Issue 4: Hardcoded Alert Thresholds**
- Location: `scripts/deploy_mlb_multi_model.sh`, alert testing scripts
- Problem: Thresholds not configurable via environment variables
- Impact: Can't tune alert sensitivity without code changes

---

## Objectives & Success Criteria

### Objective 1: Optimize Batch Feature Loading
**Goal**: Load features once, share across all prediction systems

**Success Criteria**:
- [ ] Batch predictions complete 30-40% faster
- [ ] BigQuery query count reduced by ~66% (3 systems → 1 query)
- [ ] All systems still receive correct features
- [ ] Backward compatibility maintained for single predictions

### Objective 2: Implement Feature Coverage Monitoring
**Goal**: Track and report feature completeness per pitcher

**Success Criteria**:
- [ ] Feature coverage percentage calculated for each prediction
- [ ] Confidence reduced if <80% feature coverage
- [ ] Logged to Cloud Logging with structured data
- [ ] BigQuery schema updated with `feature_coverage_pct` column

### Objective 3: Improve IL Cache Reliability
**Goal**: Handle BigQuery failures gracefully without stale data

**Success Criteria**:
- [ ] Failed IL queries return empty set (not stale cache)
- [ ] IL query failures logged as errors (not warnings)
- [ ] Retry logic added (3 attempts with exponential backoff)
- [ ] Cache TTL reduced to 3 hours (from 6)

### Objective 4: Make Alert Thresholds Configurable
**Goal**: Allow alert sensitivity tuning via environment variables

**Success Criteria**:
- [ ] All alert thresholds configurable via env vars
- [ ] Default values preserved (backward compatible)
- [ ] Documented in `/docs/04-deployment/MLB-ENVIRONMENT-VARIABLES.md`
- [ ] Deployment script updated to set env vars

---

## Detailed Implementation Plan

### Step 1: Optimize Batch Feature Loading (90 minutes)

**1.1 Create Shared Feature Loader**

File: `/predictions/mlb/pitcher_loader.py` (modify existing)

```python
def load_batch_features(game_date: str, pitcher_lookups: List[str] = None) -> Dict[str, Dict]:
    """
    Load features for all pitchers in a single BigQuery query.

    Returns:
        Dict mapping pitcher_lookup → feature_dict
        {
            "garrett_crochet": {"f1": 7.2, "f2": 3.1, ...},
            "luis_castillo": {"f1": 6.8, "f2": 2.9, ...}
        }
    """
    query = f"""
    SELECT
        pitcher_lookup,
        -- All V1.6 features (35 total)
        season_k_per_9 as f1,
        rolling_k_3g as f2,
        -- ... all 35 features
    FROM `nba-data-warehouse-422817.nba_precompute.ml_feature_store`
    WHERE game_date = @game_date
    {f"AND pitcher_lookup IN UNNEST(@pitcher_lookups)" if pitcher_lookups else ""}
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "STRING", game_date),
            bigquery.ArrayQueryParameter("pitcher_lookups", "STRING", pitcher_lookups or [])
        ]
    )

    results = bq_client.query(query, job_config=job_config).result()

    feature_map = {}
    for row in results:
        pitcher = row["pitcher_lookup"]
        features = {f"f{i}": row.get(f"f{i}") for i in range(1, 36)}
        feature_map[pitcher] = features

    return feature_map
```

**1.2 Update Worker Batch Prediction Logic**

File: `/predictions/mlb/worker.py:run_multi_system_batch_predictions()`

```python
def run_multi_system_batch_predictions(game_date: str, pitcher_lookups: List[str] = None):
    """Run batch predictions across all active systems."""

    # Load features ONCE for all pitchers
    logger.info(f"Loading features for game_date={game_date}")
    feature_map = pitcher_loader.load_batch_features(game_date, pitcher_lookups)

    if not feature_map:
        logger.warning(f"No pitchers found for {game_date}")
        return []

    all_predictions = []
    systems = get_prediction_systems()

    # For each pitcher
    for pitcher_lookup, features in feature_map.items():
        # Get betting line
        line_info = _get_betting_line(pitcher_lookup, game_date)

        # Run through all systems with SHARED features
        for system_id, predictor in systems.items():
            try:
                result = predictor.predict(
                    pitcher_lookup=pitcher_lookup,
                    game_date=game_date,
                    strikeouts_line=line_info.get("line"),
                    features=features,  # ← Pass preloaded features
                    over_odds=line_info.get("over_odds"),
                    under_odds=line_info.get("under_odds")
                )
                result["system_id"] = system_id
                all_predictions.append(result)
            except Exception as e:
                logger.error(f"System {system_id} failed for {pitcher_lookup}: {e}")
                continue

    return all_predictions
```

**1.3 Testing**
```bash
# Test single-pitcher (should still work)
curl -X POST https://mlb-prediction-worker-756957797294.us-central1.run.app/predict \
  -H "Content-Type: application/json" \
  -d '{"pitcher_lookup": "garrett_crochet", "game_date": "2026-01-20", "strikeouts_line": 7.5}'

# Test batch (should be faster)
time curl -X POST https://mlb-prediction-worker-756957797294.us-central1.run.app/predict-batch \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-20", "write_to_bigquery": false}'

# Compare batch timing before/after
# Before: ~15-20 seconds for 20 pitchers
# After:  ~8-12 seconds for 20 pitchers (30-40% improvement)
```

---

### Step 2: Add Feature Coverage Monitoring (90 minutes)

**2.1 Add Feature Coverage Calculation**

File: `/predictions/mlb/base_predictor.py` (modify `predict()` method in base class)

```python
def _calculate_feature_coverage(self, features: Dict[str, Any]) -> float:
    """
    Calculate percentage of non-null features.

    Returns:
        Float 0-100 representing % of features with real values
    """
    total_features = len(self.REQUIRED_FEATURES)  # e.g., 35 for V1.6
    non_null_features = sum(
        1 for fname in self.REQUIRED_FEATURES
        if features.get(fname) is not None
    )
    return (non_null_features / total_features) * 100 if total_features > 0 else 0.0


def _adjust_confidence_for_coverage(self, base_confidence: float, coverage_pct: float) -> float:
    """
    Reduce confidence if feature coverage is low.

    Thresholds:
        >= 90%: No reduction
        80-89%: -5 points
        70-79%: -10 points
        60-69%: -15 points
        < 60%:  -25 points
    """
    if coverage_pct >= 90:
        return base_confidence
    elif coverage_pct >= 80:
        return base_confidence - 5
    elif coverage_pct >= 70:
        return base_confidence - 10
    elif coverage_pct >= 60:
        return base_confidence - 15
    else:
        return base_confidence - 25
```

**2.2 Update Prediction Method**

```python
def predict(self, pitcher_lookup: str, game_date: str, ...) -> Dict:
    """Generate prediction with feature coverage tracking."""

    # Load/prepare features
    features = self._prepare_features(...)

    # NEW: Calculate coverage
    coverage_pct = self._calculate_feature_coverage(features)

    # Make prediction
    predicted_k = self.model.predict(...)

    # Calculate base confidence
    base_confidence = self._calculate_confidence(...)

    # NEW: Adjust for coverage
    confidence = self._adjust_confidence_for_coverage(base_confidence, coverage_pct)

    # Log low coverage
    if coverage_pct < 80:
        logger.warning(
            f"Low feature coverage for {pitcher_lookup}",
            extra={
                "pitcher_lookup": pitcher_lookup,
                "game_date": game_date,
                "system_id": self.system_id,
                "coverage_pct": coverage_pct,
                "missing_features": [
                    f for f in self.REQUIRED_FEATURES
                    if features.get(f) is None
                ]
            }
        )

    return {
        ...,
        "feature_coverage_pct": round(coverage_pct, 1),
        "confidence": confidence,
        ...
    }
```

**2.3 Update BigQuery Schema**

File: Create `/migrations/add_feature_coverage_column.sql`

```sql
-- Add feature_coverage_pct column to pitcher_strikeouts table
ALTER TABLE `nba-data-warehouse-422817.mlb_predictions.pitcher_strikeouts`
ADD COLUMN IF NOT EXISTS feature_coverage_pct FLOAT64;

-- Update description
ALTER TABLE `nba-data-warehouse-422817.mlb_predictions.pitcher_strikeouts`
ALTER COLUMN feature_coverage_pct
SET OPTIONS (description = 'Percentage of required features that were non-null (0-100)');

-- Create monitoring view
CREATE OR REPLACE VIEW `nba-data-warehouse-422817.mlb_predictions.feature_coverage_monitoring` AS
SELECT
  game_date,
  system_id,
  COUNT(*) as total_predictions,
  ROUND(AVG(feature_coverage_pct), 1) as avg_coverage_pct,
  COUNTIF(feature_coverage_pct < 80) as low_coverage_count,
  ROUND(COUNTIF(feature_coverage_pct < 80) / COUNT(*) * 100, 1) as low_coverage_pct
FROM `nba-data-warehouse-422817.mlb_predictions.pitcher_strikeouts`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date, system_id
ORDER BY game_date DESC, system_id;
```

**2.4 Run Migration**
```bash
bq query --use_legacy_sql=false < migrations/add_feature_coverage_column.sql
```

**2.5 Testing**
```bash
# Test prediction with full features
curl -X POST .../predict -d '{
  "pitcher_lookup": "garrett_crochet",
  "game_date": "2026-01-20",
  "strikeouts_line": 7.5,
  "features": {"f1": 7.2, "f2": 6.8, ..., "f35": 0.82}
}'
# Expect: feature_coverage_pct: 100.0

# Test with missing features
curl -X POST .../predict -d '{
  "pitcher_lookup": "garrett_crochet",
  "features": {"f1": 7.2}  # Only 1/35 features
}'
# Expect: feature_coverage_pct: 2.9, confidence reduced by -25

# Check monitoring view
bq query --use_legacy_sql=false '
SELECT * FROM `mlb_predictions.feature_coverage_monitoring`
WHERE game_date >= CURRENT_DATE() - 7
ORDER BY game_date DESC
LIMIT 20
'
```

---

### Step 3: Improve IL Cache Reliability (60 minutes)

**3.1 Add Retry Logic**

File: `/predictions/mlb/base_predictor.py:_get_current_il_pitchers()`

```python
from google.api_core import retry
import time

def _get_current_il_pitchers(self) -> Set[str]:
    """
    Get current IL pitchers with retry logic and fail-safe behavior.
    """
    cache_age = time.time() - self._il_cache_timestamp
    cache_ttl_seconds = self.config.cache.il_cache_ttl_hours * 3600

    # Return cache if fresh
    if cache_age < cache_ttl_seconds and self._il_cache is not None:
        logger.debug(f"Using cached IL data (age: {cache_age/60:.1f} min)")
        return self._il_cache

    # Query with retry
    query = """
    SELECT DISTINCT LOWER(REPLACE(player_name, ' ', '_')) as pitcher_lookup
    FROM `nba-data-warehouse-422817.mlb_raw.bdl_injuries`
    WHERE status IN ('IL10', 'IL15', 'IL60')
      AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), scraped_at, HOUR) <= 6
    """

    # Retry configuration: 3 attempts, exponential backoff
    retry_config = retry.Retry(
        initial=1.0,      # 1 second initial delay
        maximum=10.0,     # 10 seconds max delay
        multiplier=2.0,   # Double delay each retry
        deadline=30.0,    # 30 seconds total timeout
        predicate=retry.if_exception_type(Exception)
    )

    try:
        results = self.bq_client.query(query, retry=retry_config).result()
        il_pitchers = {row["pitcher_lookup"] for row in results}

        # Update cache
        self._il_cache = il_pitchers
        self._il_cache_timestamp = time.time()

        logger.info(f"IL cache refreshed: {len(il_pitchers)} pitchers on IL")
        return il_pitchers

    except Exception as e:
        logger.error(
            f"IL query failed after retries: {e}",
            extra={
                "error_type": type(e).__name__,
                "cache_age_hours": cache_age / 3600,
                "fallback_action": "return_empty_set"
            }
        )

        # FAIL SAFE: Return empty set (don't skip any pitchers)
        # This is safer than using stale cache - we'd rather NOT skip
        # a pitcher than skip them based on outdated IL status
        return set()
```

**3.2 Reduce Cache TTL**

File: `/predictions/mlb/config.py`

```python
@dataclass
class CacheConfig:
    """Cache configuration."""
    il_cache_ttl_hours: float = 3.0  # Changed from 6.0
```

**3.3 Update Environment Variable Documentation**

File: `/docs/04-deployment/MLB-ENVIRONMENT-VARIABLES.md`

Add:
```markdown
### `MLB_IL_CACHE_TTL_HOURS`
- **Type**: Float
- **Default**: 3.0
- **Description**: Hours to cache IL (Injured List) pitcher data from BigQuery
- **Rationale**: Reduced from 6 hours to 3 for faster injury status updates
- **Impact**: More frequent BigQuery queries, but better data freshness
```

**3.4 Testing**
```bash
# Test IL cache behavior
# 1. Make prediction (should cache IL data)
curl -X POST .../predict -d '{"pitcher_lookup": "test", "game_date": "2026-01-20"}'

# 2. Check logs for "IL cache refreshed" message
gcloud logging read 'resource.type="cloud_run_revision"
  jsonPayload.message=~"IL cache"' \
  --limit 10 --format json

# 3. Simulate BigQuery failure
# (Temporarily revoke BigQuery permissions, make request, verify empty set returned)

# 4. Verify 3-hour TTL
# (Make request, wait 3.1 hours, make another request, verify cache refresh)
```

---

### Step 4: Make Alert Thresholds Configurable (60 minutes)

**4.1 Add Environment Variables**

File: `/predictions/mlb/config.py`

```python
@dataclass
class AlertConfig:
    """Alert threshold configuration."""

    # Fallback prediction alerts
    fallback_rate_threshold: float = field(
        default_factory=lambda: float(os.getenv("MLB_FALLBACK_RATE_THRESHOLD", "10.0"))
    )
    fallback_window_minutes: int = field(
        default_factory=lambda: int(os.getenv("MLB_FALLBACK_WINDOW_MINUTES", "10"))
    )

    # Model loading alerts
    model_load_failure_threshold: int = field(
        default_factory=lambda: int(os.getenv("MLB_MODEL_LOAD_FAILURE_THRESHOLD", "1"))
    )

    # Feature coverage alerts
    low_coverage_threshold: float = field(
        default_factory=lambda: float(os.getenv("MLB_LOW_COVERAGE_THRESHOLD", "80.0"))
    )
    low_coverage_rate_threshold: float = field(
        default_factory=lambda: float(os.getenv("MLB_LOW_COVERAGE_RATE_THRESHOLD", "20.0"))
    )

@dataclass
class MLBConfig:
    """Master MLB configuration."""
    prediction: PredictionConfig = field(default_factory=PredictionConfig)
    red_flags: RedFlagConfig = field(default_factory=RedFlagConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)  # NEW
```

**4.2 Update Deployment Script**

File: `scripts/deploy_mlb_multi_model.sh`

```bash
# Add after existing env vars (around line 100)

# Alert thresholds (configurable)
MLB_FALLBACK_RATE_THRESHOLD=${MLB_FALLBACK_RATE_THRESHOLD:-10.0}
MLB_FALLBACK_WINDOW_MINUTES=${MLB_FALLBACK_WINDOW_MINUTES:-10}
MLB_MODEL_LOAD_FAILURE_THRESHOLD=${MLB_MODEL_LOAD_FAILURE_THRESHOLD:-1}
MLB_LOW_COVERAGE_THRESHOLD=${MLB_LOW_COVERAGE_THRESHOLD:-80.0}
MLB_LOW_COVERAGE_RATE_THRESHOLD=${MLB_LOW_COVERAGE_RATE_THRESHOLD:-20.0}

# Add to env vars YAML
cat > /tmp/mlb_env_vars.yaml <<EOF
MLB_ACTIVE_SYSTEMS: "${MLB_ACTIVE_SYSTEMS}"
MLB_V1_MODEL_PATH: "${MLB_V1_MODEL_PATH}"
MLB_V1_6_MODEL_PATH: "${MLB_V1_6_MODEL_PATH}"
...
MLB_FALLBACK_RATE_THRESHOLD: "${MLB_FALLBACK_RATE_THRESHOLD}"
MLB_FALLBACK_WINDOW_MINUTES: "${MLB_FALLBACK_WINDOW_MINUTES}"
MLB_MODEL_LOAD_FAILURE_THRESHOLD: "${MLB_MODEL_LOAD_FAILURE_THRESHOLD}"
MLB_LOW_COVERAGE_THRESHOLD: "${MLB_LOW_COVERAGE_THRESHOLD}"
MLB_LOW_COVERAGE_RATE_THRESHOLD: "${MLB_LOW_COVERAGE_RATE_THRESHOLD}"
EOF
```

**4.3 Document Variables**

File: `/docs/04-deployment/MLB-ENVIRONMENT-VARIABLES.md`

```markdown
## Alert Threshold Variables

### `MLB_FALLBACK_RATE_THRESHOLD`
- **Type**: Float (percentage)
- **Default**: 10.0
- **Description**: Threshold for fallback prediction rate alert (%)
- **Example**: If 10% of predictions use fallback in 10-min window, alert fires

### `MLB_FALLBACK_WINDOW_MINUTES`
- **Type**: Integer
- **Default**: 10
- **Description**: Time window for fallback rate calculation (minutes)

### `MLB_MODEL_LOAD_FAILURE_THRESHOLD`
- **Type**: Integer
- **Default**: 1
- **Description**: Number of model load failures before alerting
- **Rationale**: Even 1 failure is critical (indicates missing model file)

### `MLB_LOW_COVERAGE_THRESHOLD`
- **Type**: Float (percentage)
- **Default**: 80.0
- **Description**: Minimum acceptable feature coverage (%)

### `MLB_LOW_COVERAGE_RATE_THRESHOLD`
- **Type**: Float (percentage)
- **Default**: 20.0
- **Description**: If >20% of predictions have coverage below threshold, alert
```

**4.4 Testing**
```bash
# Test custom alert thresholds
export MLB_FALLBACK_RATE_THRESHOLD=5.0  # More sensitive
export MLB_FALLBACK_WINDOW_MINUTES=5    # Shorter window
./scripts/deploy_mlb_multi_model.sh phase3

# Verify env vars set
gcloud run services describe mlb-prediction-worker \
  --region us-central1 \
  --format="value(spec.template.spec.containers[0].env)" \
  | grep ALERT

# Expected output:
# MLB_FALLBACK_RATE_THRESHOLD=5.0
# MLB_FALLBACK_WINDOW_MINUTES=5
# ...
```

---

### Step 5: Deploy & Validate (60 minutes)

**5.1 Pre-Deployment Checklist**
```bash
# Verify all changes compile
cd /home/naji/code/nba-stats-scraper
python3 -m py_compile predictions/mlb/worker.py
python3 -m py_compile predictions/mlb/base_predictor.py
python3 -m py_compile predictions/mlb/pitcher_loader.py
python3 -m py_compile predictions/mlb/config.py

# Run unit tests (if available)
pytest predictions/mlb/tests/ -v

# Verify Docker image builds
docker build -f docker/mlb-prediction-worker.Dockerfile -t test-mlb-worker .
```

**5.2 Deploy to Production**
```bash
# Deploy with new optimizations
./scripts/deploy_mlb_multi_model.sh phase3

# Script will:
# 1. Build Docker image with optimizations
# 2. Deploy to Cloud Run
# 3. Run health check
# 4. Validate service info
```

**5.3 Post-Deployment Validation**

```bash
# Test 1: Single prediction still works
curl -X POST https://mlb-prediction-worker-756957797294.us-central1.run.app/predict \
  -H "Content-Type: application/json" \
  -d '{
    "pitcher_lookup": "garrett_crochet",
    "game_date": "2026-01-20",
    "strikeouts_line": 7.5
  }' | jq .

# Expected: feature_coverage_pct field present

# Test 2: Batch prediction speed test
time curl -X POST https://mlb-prediction-worker-756957797294.us-central1.run.app/predict-batch \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-20", "write_to_bigquery": false}' | jq .

# Expected: 30-40% faster than before (measure baseline first)

# Test 3: Feature coverage monitoring
bq query --use_legacy_sql=false '
SELECT * FROM `mlb_predictions.feature_coverage_monitoring`
WHERE game_date >= CURRENT_DATE()
ORDER BY game_date DESC
LIMIT 10'

# Expected: Rows with coverage statistics

# Test 4: IL cache retry logging
gcloud logging read 'resource.type="cloud_run_revision"
  jsonPayload.message=~"IL"
  timestamp>="2026-01-17T00:00:00Z"' \
  --limit 20 --format json

# Expected: "IL cache refreshed" messages

# Test 5: Alert thresholds
gcloud run services describe mlb-prediction-worker \
  --region us-central1 \
  --format="value(spec.template.spec.containers[0].env)" \
  | grep -E "(FALLBACK|COVERAGE)"

# Expected: Alert threshold env vars visible
```

**5.4 Performance Baseline Measurement**

Create: `/scripts/measure_mlb_performance.sh`

```bash
#!/bin/bash

echo "Measuring MLB prediction worker performance..."
echo "Date: $(date)"
echo ""

# Test single prediction latency
echo "=== Single Prediction Latency ==="
for i in {1..10}; do
  curl -s -w "Time: %{time_total}s\n" -o /dev/null \
    -X POST https://mlb-prediction-worker-756957797294.us-central1.run.app/predict \
    -H "Content-Type: application/json" \
    -d '{"pitcher_lookup": "garrett_crochet", "game_date": "2026-01-20", "strikeouts_line": 7.5}'
done | awk '{sum+=$2; count++} END {print "Average: " sum/count "s"}'

echo ""
echo "=== Batch Prediction Latency (20 pitchers) ==="
for i in {1..5}; do
  curl -s -w "Time: %{time_total}s\n" -o /dev/null \
    -X POST https://mlb-prediction-worker-756957797294.us-central1.run.app/predict-batch \
    -H "Content-Type: application/json" \
    -d '{"game_date": "2026-01-20", "write_to_bigquery": false}'
done | awk '{sum+=$2; count++} END {print "Average: " sum/count "s"}'

echo ""
echo "=== BigQuery Query Count (last 5 minutes) ==="
bq ls -j -a --max_results=1000 | \
  grep -E "(mlb_predictions|nba_precompute)" | \
  wc -l
```

Run before and after deployment:
```bash
# Before optimization
./scripts/measure_mlb_performance.sh > /tmp/mlb_performance_before.txt

# ... deploy optimizations ...

# After optimization
./scripts/measure_mlb_performance.sh > /tmp/mlb_performance_after.txt

# Compare
diff /tmp/mlb_performance_before.txt /tmp/mlb_performance_after.txt
```

---

## Key Files & Locations

### Files to Modify
```
/predictions/mlb/
├── worker.py                           # Batch prediction optimization
├── base_predictor.py                   # Feature coverage, IL cache retry
├── pitcher_loader.py                   # Shared feature loading function
├── config.py                           # Alert threshold env vars
└── prediction_systems/
    ├── v1_baseline_predictor.py       # REQUIRED_FEATURES list
    └── v1_6_rolling_predictor.py      # REQUIRED_FEATURES list

/scripts/
├── deploy_mlb_multi_model.sh          # Add alert env vars
└── measure_mlb_performance.sh         # NEW: Performance measurement

/migrations/
└── add_feature_coverage_column.sql    # NEW: Schema migration

/docs/04-deployment/
└── MLB-ENVIRONMENT-VARIABLES.md       # Document new env vars
```

### BigQuery Resources
```
nba-data-warehouse-422817.mlb_predictions
├── pitcher_strikeouts                 # Add feature_coverage_pct column
└── feature_coverage_monitoring        # NEW: Monitoring view

nba-data-warehouse-422817.nba_precompute
└── ml_feature_store                   # Source for batch features
```

### Cloud Resources
- **Service**: `mlb-prediction-worker` (us-central1)
- **Image**: `gcr.io/nba-data-warehouse-422817/mlb-prediction-worker`
- **Logs**: Cloud Logging (`resource.type="cloud_run_revision"`)

---

## Testing & Validation Checklist

### Pre-Deployment Tests
- [ ] Code compiles without errors
- [ ] Docker image builds successfully
- [ ] Unit tests pass (if available)
- [ ] Baseline performance measured

### Post-Deployment Tests
- [ ] Health endpoint returns 200
- [ ] Single prediction includes `feature_coverage_pct`
- [ ] Batch predictions 30-40% faster
- [ ] Feature coverage monitoring view has data
- [ ] IL cache retry logic appears in logs
- [ ] Alert threshold env vars set correctly
- [ ] All 3 systems still working (v1_baseline, v1_6_rolling, ensemble_v1)

### Validation Queries
```sql
-- Check feature coverage distribution
SELECT
  ROUND(feature_coverage_pct, -1) as coverage_bucket,
  COUNT(*) as prediction_count,
  ROUND(AVG(confidence), 1) as avg_confidence
FROM `mlb_predictions.pitcher_strikeouts`
WHERE game_date >= CURRENT_DATE()
GROUP BY coverage_bucket
ORDER BY coverage_bucket DESC;

-- Find low coverage predictions
SELECT
  pitcher_lookup,
  game_date,
  system_id,
  feature_coverage_pct,
  confidence,
  recommendation
FROM `mlb_predictions.pitcher_strikeouts`
WHERE game_date >= CURRENT_DATE()
  AND feature_coverage_pct < 80
ORDER BY feature_coverage_pct ASC
LIMIT 20;

-- Verify batch prediction count
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions
FROM `mlb_predictions.pitcher_strikeouts`
WHERE game_date >= CURRENT_DATE()
GROUP BY game_date, system_id;
-- Expect: 3 rows per pitcher (one per system)
```

---

## Rollback Procedure

### If Batch Predictions Fail

**Symptom**: `/predict-batch` endpoint returns errors or no results

**Rollback**:
```bash
# 1. Revert worker.py changes
git checkout HEAD~1 predictions/mlb/worker.py
git checkout HEAD~1 predictions/mlb/pitcher_loader.py

# 2. Redeploy
./scripts/deploy_mlb_multi_model.sh phase3

# 3. Verify single predictions still work
curl -X POST .../predict -d '{...}'
```

**Root Cause Investigation**:
- Check Cloud Logging for BigQuery errors
- Verify feature_map structure
- Test feature loading function in isolation

### If Feature Coverage Breaks Confidence

**Symptom**: All predictions have very low confidence

**Quick Fix**:
```python
# Temporarily disable coverage adjustment
# In base_predictor.py:_adjust_confidence_for_coverage()
def _adjust_confidence_for_coverage(self, base_confidence: float, coverage_pct: float) -> float:
    return base_confidence  # Bypass adjustment
```

**Redeploy and Investigate**:
- Check REQUIRED_FEATURES list completeness
- Verify ml_feature_store has expected columns
- Test coverage calculation logic

### If IL Cache Fails

**Symptom**: All pitchers skipped with "Currently on IL" red flag

**Quick Fix**:
```python
# In base_predictor.py:_get_current_il_pitchers()
def _get_current_il_pitchers(self) -> Set[str]:
    return set()  # Return empty set, skip IL checking temporarily
```

**Redeploy and Investigate**:
- Check BigQuery permissions
- Verify `mlb_raw.bdl_injuries` table exists
- Test IL query manually

### Complete Rollback

**If all optimizations need reverting**:
```bash
# Find commit before optimizations
git log --oneline predictions/mlb/ | head -10

# Revert to previous commit
git checkout <commit-hash> predictions/mlb/

# Redeploy
./scripts/deploy_mlb_multi_model.sh phase3

# Verify baseline functionality
curl https://mlb-prediction-worker-756957797294.us-central1.run.app/health
```

---

## Known Risks & Dependencies

### Risks

**Risk 1: BigQuery Query Cost Increase**
- **Likelihood**: Low
- **Impact**: Minor ($5-10/month increase)
- **Mitigation**: Feature coverage queries only add 1 view, batch optimization REDUCES queries
- **Monitoring**: Check BigQuery usage dashboard weekly

**Risk 2: Feature Coverage False Positives**
- **Likelihood**: Medium
- **Impact**: Medium (legitimate predictions marked low quality)
- **Mitigation**: Set threshold at 80% (not 90%), log missing features for analysis
- **Monitoring**: Review `feature_coverage_monitoring` view daily for first week

**Risk 3: IL Cache Empty Set Behavior**
- **Likelihood**: Low
- **Impact**: Medium (injured pitchers not skipped)
- **Mitigation**: Retry logic reduces query failures, log all IL errors
- **Monitoring**: Alert on "IL query failed" errors (>5 in 1 hour)

**Risk 4: Batch Prediction Breaking Change**
- **Likelihood**: Low
- **Impact**: High (all batch predictions fail)
- **Mitigation**: Extensive testing, backward compatibility for single predictions
- **Rollback**: Git revert + redeploy (~5 minutes)

### Dependencies

**External Services**:
- BigQuery API (must be available)
- Cloud Storage (for model files)
- Cloud Run (for hosting)

**Data Dependencies**:
- `nba_precompute.ml_feature_store` must have recent data
- `mlb_raw.bdl_injuries` must update regularly (6-hour freshness)
- Betting lines must be available in game schedule

**Code Dependencies**:
- XGBoost library version compatibility
- Flask routing unchanged
- Gunicorn configuration unchanged

---

## Estimated Timeline

### Time Breakdown
- **Step 1**: Optimize batch loading - 90 minutes
- **Step 2**: Feature coverage monitoring - 90 minutes
- **Step 3**: IL cache retry - 60 minutes
- **Step 4**: Configurable alerts - 60 minutes
- **Step 5**: Deploy & validate - 60 minutes
- **Buffer**: 30 minutes

**Total**: 6.5 hours (estimated 4-6 hours with efficiency)

### Parallelization Opportunities
- Steps 1, 2, 3 can be coded in parallel (if multiple developers)
- Testing can overlap with documentation updates
- Migration scripts can be written during code development

### Critical Path
1. Step 1 (batch loading) → blocks batch testing
2. Step 2 (coverage) → blocks schema migration
3. Step 5 (deploy) → must be sequential

---

## Success Metrics

### Performance Metrics
- [ ] Batch prediction latency reduced by 30-40%
- [ ] BigQuery query count reduced by ~66% for batch operations
- [ ] Single prediction latency unchanged (<1% variance)

### Quality Metrics
- [ ] Feature coverage calculated for 100% of predictions
- [ ] Low coverage predictions (<80%) logged and monitored
- [ ] IL cache refresh success rate >99.5%

### Operational Metrics
- [ ] Alert threshold changes deployable without code changes
- [ ] Zero production incidents during deployment
- [ ] Rollback procedure tested and documented

### Monitoring Metrics
- [ ] `feature_coverage_monitoring` view populated
- [ ] IL cache errors visible in Cloud Logging
- [ ] Alert threshold env vars visible in service config

---

## References

### Documentation
- Main handoff: `/docs/09-handoff/2026-01-17-SESSION-80-DEPLOYMENT-HANDOFF.md`
- MLB deployment runbook: `/docs/mlb_multi_model_deployment_runbook.md`
- Environment variables: `/docs/04-deployment/MLB-ENVIRONMENT-VARIABLES.md`

### Code
- Worker: `/predictions/mlb/worker.py`
- Base predictor: `/predictions/mlb/base_predictor.py`
- Config: `/predictions/mlb/config.py`
- Deployment script: `/scripts/deploy_mlb_multi_model.sh`

### Monitoring
- Service health: https://mlb-prediction-worker-756957797294.us-central1.run.app/health
- Cloud Run console: https://console.cloud.google.com/run/detail/us-central1/mlb-prediction-worker
- BigQuery monitoring views: `mlb_predictions.{view_name}`

### Related Sessions
- Session 80: MLB multi-model deployment
- Session 82: NBA alerting Week 1 implementation
- Session 57: SwStr% backtest and red flag tuning

---

## Contact & Support

**Questions During Implementation**:
- Refer to this handoff document first
- Check `/docs/04-deployment/` for additional context
- Review Cloud Logging for runtime errors

**If Stuck**:
1. Check rollback procedures above
2. Review testing & validation checklist
3. Examine recent git commits for similar patterns
4. Deploy rollback, investigate offline

**Post-Implementation**:
- Update this document with actual times and learnings
- Document any new issues discovered
- Add performance measurements to references

---

**End of Handoff Document**
