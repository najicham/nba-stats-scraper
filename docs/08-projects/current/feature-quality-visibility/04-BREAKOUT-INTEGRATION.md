# Breakout Classifier Integration - Schema Enhancements

**Date:** February 5, 2026 (Session 133)
**Source:** Feedback from parallel breakout classifier session
**Status:** ✅ INTEGRATED into final schema
**Priority:** P0 - Prevents Session 133 blocker recurrence

---

## Background

While designing the feature quality visibility system, a parallel session working on the breakout classifier blocker provided critical feedback on our schema design. Their recommendations directly address:

1. **Session 133 blocker root cause** - Model/data mismatch
2. **Session 134b issue** - Train/eval feature inconsistency
3. **Model compatibility** - Explicit version tracking

---

## Critical Additions (P0 - Must Implement)

### 1. Model Compatibility Tracking

**Problem:** Session 133 blocker happened because model expected `points_avg_season` that worker didn't provide. No way to detect this before deployment.

**Solution:**
```sql
-- Track feature schema version
feature_schema_version STRING OPTIONS(
  description="Feature schema version: 'v2_37features', 'v3_39features'. Validates model/data compatibility."
),

-- List available features
available_feature_names ARRAY<STRING> OPTIONS(
  description="List of feature names in this record. Runtime validation before prediction."
),

-- Explicit model compatibility
breakout_model_compatible ARRAY<STRING> OPTIONS(
  description="Which breakout models this data supports: ['v2_14features', 'v3_13features']."
)
```

**Usage in Worker:**
```python
# Before making prediction
if model_version not in feature_record['breakout_model_compatible']:
    raise ValueError(
        f"Model {model_version} incompatible with available features. "
        f"Model expects: {model.feature_names_}, "
        f"Available: {feature_record['available_feature_names']}"
    )
```

**Impact:** Prevents Session 133 blocker entirely. Worker will detect incompatibility at runtime and fail gracefully with clear error message.

---

### 2. V3 Feature Availability Flag

**Problem:** V3 features (star_teammate_out, fg_pct_last_game) computed in training query only. Production worker can't access them → model/data mismatch.

**Solution:**
```sql
breakout_v3_features_available BOOL OPTIONS(
  description="TRUE if V3 breakout features available. Required for V3 model predictions."
)
```

**Implementation:**
1. Extend MLFeatureStoreProcessor to compute V3 features
2. Add them to feature_store_values array (indices 37-38)
3. Set `breakout_v3_features_available = TRUE` when present

**Impact:** Training and production use same features. No more Session 134b-style train/eval mismatches.

---

## High Priority Additions (P1 - Recommended)

### 3. Training Data Quality Gate

**Problem:** Want to train only on high-quality data, but no explicit criteria.

**Solution:**
```sql
is_training_ready BOOL OPTIONS(
  description="TRUE if quality sufficient for ML training (stricter than is_production_ready)."
)
```

**Calculation (stricter than production):**
```python
is_training_ready = (
    quality_tier in ('gold', 'silver') and      # Higher bar than production
    matchup_quality_pct >= 70 and               # More strict (vs 50 for prod)
    player_history_quality_pct >= 80 and        # Requires good history
    has_opponent_defense == True and            # Critical feature required
    default_feature_count <= 2 and              # Minimal defaults
    breakout_v3_features_available == True      # If training V3 model
)
```

**Usage in Training:**
```sql
-- Filter training data to high quality only
SELECT * FROM ml_feature_store_v2
WHERE game_date BETWEEN @train_start AND @train_end
  AND is_training_ready = TRUE
  AND breakout_v3_features_available = TRUE  -- For V3 training
```

**Impact:** Higher quality training data → better model performance. Garbage in/garbage out prevention.

---

### 4. Critical Feature Tracking

**Problem:** Current schema tracks source counts, but not which features are critical vs optional.

**Solution:**
```sql
critical_feature_count INT64 OPTIONS(
  description="Count of CRITICAL features present (opponent_def, matchup). Missing = low confidence."
),

optional_feature_count INT64 OPTIONS(
  description="Count of optional features present. Missing = acceptable."
)
```

**Feature Classification:**
```python
CRITICAL_FEATURES = [
    5, 6, 7, 8,      # Composite factors (matchup)
    13, 14,          # Opponent defense
    29, 30           # Matchup history
]

OPTIONAL_FEATURES = [
    25, 26, 27, 28   # Vegas lines (not all players have lines)
]
```

**Impact:** More granular quality assessment. Can quantify "how critical are the missing features?"

---

## Optional Additions (P2 - Nice to Have)

### 5. Freshness Tracking

**Problem:** Training might use stale feature store data without knowing.

**Solution:**
```sql
feature_store_age_hours FLOAT64 OPTIONS(
  description="Hours since feature store computed. Filter training data (exclude > 48h)."
),

upstream_data_freshness_hours FLOAT64 OPTIONS(
  description="Hours since upstream data updated. Detect stale dependencies."
)
```

**Usage:**
```sql
-- Exclude stale data from training
SELECT * FROM ml_feature_store_v2
WHERE game_date BETWEEN @train_start AND @train_end
  AND feature_store_age_hours < 48  -- Exclude stale features
  AND is_training_ready = TRUE
```

---

## Schema Summary with Breakout Integration

**Total New Fields: 26**
- 16 fields from original quality visibility design
- 10 fields from breakout integration (3 P0, 4 P1, 3 P2)

**Prioritization:**

| Priority | Fields | Purpose | Must Implement? |
|----------|--------|---------|-----------------|
| **P0** | 3 | Prevent Session 133 blocker | ✅ YES |
| **P1** | 4 | Training quality + granular diagnostics | ✅ RECOMMENDED |
| **P2** | 3 | Freshness tracking | ⚠️ OPTIONAL |

---

## Implementation Strategy

### Phase 1: Add P0 Fields (Blocker Prevention) - 30 min

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS
  feature_schema_version STRING,
  available_feature_names ARRAY<STRING>,
  breakout_model_compatible ARRAY<STRING>,
  breakout_v3_features_available BOOL;
```

**Computation Logic:**
```python
# In ml_feature_store_processor.py
def _build_feature_store_record(self, ...):
    # ... existing code ...

    # P0: Model compatibility
    record['feature_schema_version'] = 'v2_37features'  # Current version
    record['available_feature_names'] = self._get_available_feature_names(feature_sources)
    record['breakout_model_compatible'] = self._determine_compatible_models(feature_sources)
    record['breakout_v3_features_available'] = self._has_v3_features(feature_sources)

    return record

def _determine_compatible_models(self, feature_sources: dict) -> list:
    """Determine which breakout models this data supports."""
    compatible = []

    # V2 requires 14 core features
    if self._has_v2_features(feature_sources):
        compatible.append('v2_14features')

    # V3 requires V2 + star_teammate_out + fg_pct_last_game
    if self._has_v3_features(feature_sources):
        compatible.append('v3_13features')

    return compatible
```

---

### Phase 2: Add P1 Fields (Training Quality) - 30 min

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS
  is_training_ready BOOL,
  critical_feature_count INT64,
  optional_feature_count INT64;
```

**Computation Logic:**
```python
def _calculate_training_readiness(self, quality_tier, matchup_quality_pct,
                                  player_history_quality_pct, has_opponent_defense,
                                  default_feature_count, breakout_v3_available):
    """Stricter quality bar for training."""
    return (
        quality_tier in ('gold', 'silver') and
        matchup_quality_pct >= 70 and
        player_history_quality_pct >= 80 and
        has_opponent_defense == True and
        default_feature_count <= 2
        # Note: Don't require breakout_v3_available for all training,
        # only when training V3 models specifically
    )

def _count_critical_features(self, feature_sources: dict) -> int:
    """Count critical features present."""
    CRITICAL_INDICES = [5, 6, 7, 8, 13, 14, 29, 30]
    return sum(
        1 for idx in CRITICAL_INDICES
        if feature_sources.get(idx) in ('phase4', 'phase3', 'calculated')
    )
```

---

### Phase 3: Add P2 Fields (Freshness) - Optional

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS
  feature_store_age_hours FLOAT64,
  upstream_data_freshness_hours FLOAT64;
```

---

## Testing with Session 133 Scenario

**Scenario:** Model expects `points_avg_season` but worker doesn't provide it.

**Before (Session 133 blocker):**
```python
# Worker tries to predict
probabilities = model.predict_proba(feature_vector)
# ❌ CatBoostError: Feature points_avg_season is present in model but not in pool
```

**After (with P0 fields):**
```python
# Worker checks compatibility BEFORE prediction
feature_record = load_feature_store_record(player_lookup, game_date)

if 'v3_13features' not in feature_record['breakout_model_compatible']:
    logger.error(
        f"Model v3_13features incompatible with available features. "
        f"Feature schema: {feature_record['feature_schema_version']}, "
        f"Available: {feature_record['available_feature_names']}, "
        f"V3 features available: {feature_record['breakout_v3_features_available']}"
    )
    # Use fallback model (v2) or skip breakout classification
    return {'is_breakout_candidate': False, 'confidence': 'incompatible_data'}

# ✅ Safe to predict
probabilities = model.predict_proba(feature_vector)
```

---

## Backfill Considerations

### P0 Fields (Required)

**feature_schema_version:**
- All historical records: `'v2_37features'` (current schema)
- After V3 implementation: `'v3_39features'`

**breakout_model_compatible:**
- All historical records: `['v2_14features']`
- After V3 features added: `['v2_14features', 'v3_13features']`

**breakout_v3_features_available:**
- All historical records: `FALSE` (V3 features not computed yet)
- After V3 processor implementation: `TRUE` (if features present)

### P1 Fields (Recommended)

**is_training_ready:**
- Compute for all backfilled records using quality criteria
- Expected: 70-80% of records are training-ready

**critical_feature_count:**
- Recompute for all backfilled records
- Session 132 issue: Feb 6 had critical_feature_count = 2 (only opponent defense, no composite factors)

---

## Integration with Worker

**File:** `predictions/worker/prediction_systems/breakout_classifier_v1.py`

**Add compatibility check:**
```python
def classify(self, player_data, feature_store_data):
    """Classify breakout risk with compatibility validation."""

    # P0: Check model compatibility
    model_version = self.model_version  # e.g., 'v3_13features'
    compatible_models = feature_store_data.get('breakout_model_compatible', [])

    if model_version not in compatible_models:
        logger.warning(
            f"Model {model_version} incompatible. "
            f"Feature schema: {feature_store_data.get('feature_schema_version')}, "
            f"Compatible models: {compatible_models}"
        )
        return {
            'is_breakout_candidate': False,
            'breakout_probability': 0.0,
            'confidence': 'incompatible_features',
            'skip_reason': f'Model requires {model_version}, data supports {compatible_models}'
        }

    # P0: Check V3 features if using V3 model
    if model_version.startswith('v3') and not feature_store_data.get('breakout_v3_features_available'):
        logger.warning(
            f"V3 model requires V3 features but breakout_v3_features_available = FALSE"
        )
        # Fallback to V2 model
        return self._classify_with_v2_fallback(player_data, feature_store_data)

    # Safe to proceed with prediction
    feature_vector = self._prepare_feature_vector(player_data, feature_store_data)
    probabilities = self.model.predict_proba(feature_vector)

    return {
        'is_breakout_candidate': probabilities[1] > self.threshold,
        'breakout_probability': probabilities[1],
        'confidence': 'high' if probabilities[1] > 0.769 else 'medium',
        'model_version': model_version,
        'feature_schema_version': feature_store_data['feature_schema_version']
    }
```

---

## Success Criteria

### P0 (Blocker Prevention)

- [x] Schema includes feature_schema_version, available_feature_names, breakout_model_compatible
- [ ] Worker checks compatibility before prediction
- [ ] Graceful degradation if incompatible (use fallback model or skip)
- [ ] Session 133 blocker cannot recur (incompatibility detected at runtime)

### P1 (Training Quality)

- [ ] Schema includes is_training_ready, critical_feature_count, optional_feature_count
- [ ] Training queries filter to is_training_ready = TRUE
- [ ] Can query "how many training samples are high quality?"
- [ ] Training data quality improves (less garbage in → better model out)

### P2 (Freshness)

- [ ] Schema includes feature_store_age_hours, upstream_data_freshness_hours
- [ ] Training excludes stale data (>48h)
- [ ] Can detect upstream staleness issues

---

## Final Recommendation

**Implement P0 + P1 fields immediately (7 total):**

| Priority | Field | Why |
|----------|-------|-----|
| P0 | feature_schema_version | Compatibility tracking |
| P0 | available_feature_names | Runtime validation |
| P0 | breakout_model_compatible | Explicit compatibility list |
| P0 | breakout_v3_features_available | V3 feature tracking |
| P1 | is_training_ready | Training quality gate |
| P1 | critical_feature_count | Granular diagnostics |
| P1 | optional_feature_count | Granular diagnostics |

**Total:** 26 new fields (16 quality + 3 P0 + 4 P1 + 3 P2 optional)

**Storage impact:** +250 bytes/record (vs +200 bytes for quality only)

**Annual cost:** <$0.03/year (negligible)

**Benefit:** Prevents Session 133 blocker + improves training quality + enables detailed diagnostics

---

**Document Version:** 1.0
**Last Updated:** February 5, 2026 (Session 133)
**Status:** ✅ READY FOR IMPLEMENTATION
**Integration:** Feedback from breakout classifier session incorporated
