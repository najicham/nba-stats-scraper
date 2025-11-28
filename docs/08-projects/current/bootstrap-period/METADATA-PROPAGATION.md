# Metadata Propagation Through Pipeline

**Purpose:** Document what metadata flows from Phase 4 → Phase 5 and ML model
**Created:** 2025-11-27
**Status:** ✅ Current Implementation Documented

---

## TL;DR - Your Question Answered

**Q: "Is metadata for each field being passed to downstream processors?"**

**Answer: Partially ✅ / ⏳**

**What IS passed:**
- ✅ **Aggregate metadata** - Overall quality score for the whole record
- ✅ **Source-level metadata** - Completeness per upstream table (4 sources)
- ✅ **Processor-level metadata** - early_season_flag, insufficient_data_reason

**What is NOT passed (per-field granularity):**
- ❌ **Per-feature quality** - Which specific features are partial vs full
- ❌ **Per-feature games_used** - How many games each specific feature used
- ⏳ **Planned but deferred** - Schema designed but not implemented

**Impact:**
- ML model sees overall quality (70%) but doesn't know feature[0] is 100% and feature[1] is 70%
- This is OK for now - overall quality is good proxy
- Can enhance later if needed

---

## Data Flow Diagram

```
Phase 3 Analytics
  └─> player_game_summary (raw game data)
      ↓
Phase 4 Upstream (player_daily_cache)
  ├─> points_avg_last_5: 22.4          ✅ VALUE
  ├─> points_avg_last_10: 21.8         ✅ VALUE
  ├─> points_avg_last_5_games_used: 5  ⏳ PER-FIELD METADATA (not implemented)
  ├─> points_avg_last_10_games_used: 7 ⏳ PER-FIELD METADATA (not implemented)
  └─> early_season_flag: false         ✅ AGGREGATE METADATA
      ↓
Phase 4 ML Feature Store
  ├─> features: [22.4, 21.8, ...]            ✅ VALUES (array)
  ├─> feature_names: ['points_avg_last_5'...] ✅ LABELS (array)
  ├─> feature_quality_score: 72.0            ✅ AGGREGATE QUALITY
  ├─> source_daily_cache_completeness: 70%   ✅ SOURCE-LEVEL METADATA
  └─> early_season_flag: false               ✅ AGGREGATE METADATA
      ↓
Phase 5 Predictions
  ├─> Receives: features array + aggregate metadata
  ├─> Does NOT receive: per-feature quality
  └─> ML Model sees: overall quality_score only
```

---

## Current Implementation Details

### Level 1: Phase 4 Upstream Processors

**Example: player_daily_cache table**

```sql
-- Schema (current)
CREATE TABLE player_daily_cache (
  -- FEATURE VALUES ✅
  points_avg_last_5 NUMERIC(5,1),
  points_avg_last_10 NUMERIC(5,1),
  points_avg_season NUMERIC(5,1),

  -- PER-FIELD METADATA ⏳ (designed but NOT implemented)
  -- points_avg_last_5_games_used INT64,    -- Would show: 5
  -- points_avg_last_10_games_used INT64,   -- Would show: 7
  -- points_avg_season_games_used INT64,    -- Would show: 7

  -- AGGREGATE METADATA ✅ (implemented)
  early_season_flag BOOLEAN,
  insufficient_data_reason STRING,

  -- SOURCE TRACKING ✅ (implemented)
  source_player_game_completeness_pct NUMERIC(5,2),
  source_player_game_rows_found INT64,
  ...
)
```

**Actual record (day 7):**
```json
{
  // VALUES
  "points_avg_last_5": 22.4,
  "points_avg_last_10": 21.8,
  "points_avg_season": 21.8,

  // PER-FIELD METADATA - NOT IMPLEMENTED
  // Would be here if implemented:
  // "points_avg_last_5_games_used": 5,
  // "points_avg_last_10_games_used": 7,

  // AGGREGATE METADATA - YES
  "early_season_flag": false,
  "insufficient_data_reason": null,

  // SOURCE METADATA - YES
  "source_player_game_completeness_pct": 70.0,
  "source_player_game_rows_found": 7
}
```

**What flows downstream:**
- ✅ Feature values (22.4, 21.8, 21.8)
- ✅ Aggregate metadata (early_season_flag=false)
- ✅ Source completeness (70%)
- ❌ Per-feature games_used (not implemented)

---

### Level 2: Phase 4 ML Feature Store

**Schema:**
```sql
CREATE TABLE ml_feature_store_v2 (
  -- FEATURE ARRAY ✅
  features ARRAY<FLOAT64>,              -- [22.4, 21.8, 21.8, ...]
  feature_names ARRAY<STRING>,          -- ['points_avg_last_5', ...]
  feature_count INT64,                  -- 25

  -- AGGREGATE QUALITY ✅
  feature_quality_score NUMERIC(5,2),  -- 72.0 (overall for all 25 features)

  -- PER-FEATURE QUALITY ❌ (NOT implemented)
  -- feature_quality_scores ARRAY<FLOAT64>,  -- Would be [100, 70, 70, ...]
  -- feature_games_used ARRAY<INT64>,        -- Would be [5, 7, 7, ...]

  -- SOURCE-LEVEL METADATA ✅ (4 sources)
  source_daily_cache_completeness_pct NUMERIC(5,2),
  source_composite_completeness_pct NUMERIC(5,2),
  source_shot_zones_completeness_pct NUMERIC(5,2),
  source_team_defense_completeness_pct NUMERIC(5,2),

  -- AGGREGATE METADATA ✅
  early_season_flag BOOLEAN,
  insufficient_data_reason STRING,
  is_production_ready BOOLEAN,
  completeness_percentage FLOAT64,
  ...
)
```

**Actual record:**
```json
{
  // FEATURE ARRAY
  "features": [22.4, 21.8, 21.8, 3.2, 4, ...],  // 25 values
  "feature_names": ["points_avg_last_5", "points_avg_last_10", ...],
  "feature_count": 25,

  // AGGREGATE QUALITY
  "feature_quality_score": 72.0,  // One score for ALL features

  // PER-FEATURE QUALITY - NOT IMPLEMENTED
  // "feature_quality_scores": [100, 70, 70, ...],  // Would show per-feature
  // "feature_games_used": [5, 7, 7, ...],          // Would show games per feature

  // SOURCE-LEVEL METADATA
  "source_daily_cache_completeness_pct": 70.0,
  "source_composite_completeness_pct": 85.0,
  "source_shot_zones_completeness_pct": 90.0,
  "source_team_defense_completeness_pct": 95.0,

  // AGGREGATE METADATA
  "early_season_flag": false,
  "insufficient_data_reason": "partial_window_L10_7_of_10_games",
  "is_production_ready": true,
  "completeness_percentage": 70.0
}
```

**What flows downstream:**
- ✅ Feature values array [22.4, 21.8, ...]
- ✅ Feature names array
- ✅ One quality score (72.0) for all features
- ✅ Source-level completeness (4 scores)
- ✅ Aggregate metadata
- ❌ Per-feature quality scores

---

### Level 3: Phase 5 Predictions

**What Phase 5 receives from data loader:**

```python
# From data_loaders.py load_features()
features = {
    # FEATURE VALUES
    'points_avg_last_5': 22.4,
    'points_avg_last_10': 21.8,
    'points_avg_season': 21.8,
    # ... 22 more features ...

    # ARRAYS
    'features_array': [22.4, 21.8, 21.8, ...],
    'feature_names': ['points_avg_last_5', ...],

    # AGGREGATE METADATA
    'feature_quality_score': 72.0,  # Single score
    'data_source': 'phase4',

    # COMPLETENESS METADATA
    'completeness': {
        'expected_games_count': 10,
        'actual_games_count': 7,
        'completeness_percentage': 70.0,
        'is_production_ready': True,
        'backfill_bootstrap_mode': False,
        'processing_decision_reason': 'partial_window_L10_7_of_10_games'
    },

    # PER-FEATURE METADATA - NOT AVAILABLE
    # 'feature_quality_scores': [100, 70, 70, ...],  # Doesn't exist
    # 'feature_games_used': [5, 7, 7, ...],          # Doesn't exist
}
```

**What ML model sees:**

```python
# Model training/inference
X = features['features_array']  # [22.4, 21.8, 21.8, ...]

# Could include as additional features:
quality_score = features['feature_quality_score']  # 72.0
completeness = features['completeness']['completeness_percentage']  # 70.0

# Model sees:
prediction_input = {
    'feature_values': [22.4, 21.8, 21.8, ...],  # 25 features
    'overall_quality': 72.0,                     # 1 quality score
    'completeness': 70.0                         # 1 completeness score
}

# Model does NOT see:
# - Which specific features are partial (feature[0] vs feature[1])
# - How many games each feature used
# - Per-feature quality scores
```

---

## Metadata Granularity Comparison

### Current Implementation (Aggregate Metadata)

**Pros:**
- ✅ Simpler schema (fewer fields)
- ✅ Faster queries (less data)
- ✅ Good enough for most cases
- ✅ Overall quality is reasonable proxy

**Cons:**
- ❌ Can't distinguish which features are weak
- ❌ Model can't weight features differently based on quality
- ❌ Harder to debug feature-specific issues

**Example:**
```json
{
  "features": [22.4, 21.8, 21.8, 3.2, 4, ...],
  "feature_quality_score": 72.0,  // All features treated as 72% quality

  // Reality:
  // feature[0] (L5) has 5/5 games = 100% quality ✅
  // feature[1] (L10) has 7/10 games = 70% quality ⚠️
  // But model doesn't know this distinction!
}
```

---

### Future Enhancement (Per-Feature Metadata)

**What it would look like:**

```sql
-- ml_feature_store_v2 enhanced schema
CREATE TABLE ml_feature_store_v2 (
  features ARRAY<FLOAT64>,                    -- [22.4, 21.8, ...]
  feature_names ARRAY<STRING>,                -- ['points_avg_last_5', ...]

  -- AGGREGATE (keep)
  feature_quality_score NUMERIC(5,2),         -- 72.0

  -- PER-FEATURE (add)
  feature_quality_scores ARRAY<FLOAT64>,      -- [100, 70, 70, ...]
  feature_games_used ARRAY<INT64>,            -- [5, 7, 7, ...]
  feature_completeness_pct ARRAY<FLOAT64>,    -- [100, 70, 70, ...]
  feature_data_sources ARRAY<STRING>,         -- ['daily_cache', 'daily_cache', ...]
)
```

**Record:**
```json
{
  "features": [22.4, 21.8, 21.8, 3.2, 4, ...],
  "feature_names": ["points_avg_last_5", "points_avg_last_10", ...],

  // AGGREGATE
  "feature_quality_score": 72.0,

  // PER-FEATURE
  "feature_quality_scores": [100, 70, 70, 90, 100, ...],  // 25 scores
  "feature_games_used": [5, 7, 7, 15, 7, ...],            // 25 counts
  "feature_completeness_pct": [100, 70, 70, 100, 100, ...] // 25 percentages
}
```

**ML Model could use:**
```python
# Model sees per-feature quality
for i, feature_value in enumerate(features):
    feature_quality = feature_quality_scores[i]

    if feature_quality < 50:
        # Don't use this feature or weight it down
        weight = 0.5
    elif feature_quality < 80:
        weight = 0.8
    else:
        weight = 1.0

    weighted_feature = feature_value * weight
```

**Pros:**
- ✅ Model can weight features by quality
- ✅ Better handling of mixed-quality scenarios
- ✅ More granular debugging

**Cons:**
- ❌ More complex schema
- ❌ More storage (3 arrays vs 1 score)
- ❌ More complex ML model
- ❌ Might not improve accuracy much

---

## What Metadata Actually Propagates

### Table: Metadata Availability by Phase

| Metadata | Phase 4 Upstream | ML Feature Store | Phase 5 Predictions | ML Model |
|----------|------------------|------------------|---------------------|----------|
| **Feature values** | ✅ Individual fields | ✅ Array | ✅ Dict + Array | ✅ Array |
| **Overall quality** | ✅ processor-level | ✅ feature_quality_score | ✅ Yes | ✅ Yes (can use) |
| **Per-feature quality** | ⏳ Designed, not impl | ❌ No | ❌ No | ❌ No |
| **Games used (aggregate)** | ✅ games_played_season | ✅ actual_games_count | ✅ Yes | ✅ Yes (can use) |
| **Games used (per-feature)** | ⏳ Designed, not impl | ❌ No | ❌ No | ❌ No |
| **Early season flag** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes (can use) |
| **Completeness %** | ✅ Source-level | ✅ Overall | ✅ Yes | ✅ Yes (can use) |
| **Insufficient data reason** | ✅ Yes | ✅ Yes | ✅ Yes | ❌ Not used in model |
| **Source tracking** | ✅ Per upstream table | ✅ Per upstream table (4) | ✅ Yes | ❌ Not used in model |

**Legend:**
- ✅ Implemented and passed
- ⏳ Designed but schema not migrated
- ❌ Not implemented

---

## Practical Examples

### Example 1: Day 7 - Mixed Feature Quality

**Reality (what's calculated):**
```python
# In player_daily_cache:
L5_games = 5   # Full window
L10_games = 7  # Partial window
L30_games = 7  # Partial window (if implemented)
```

**What gets stored (current):**
```json
{
  // VALUES
  "points_avg_last_5": 22.4,   // From 5 games
  "points_avg_last_10": 21.8,  // From 7 games

  // AGGREGATE METADATA
  "overall_quality": 72.0,     // Average across all features
  "games_played_season": 7,    // Total games available

  // PER-FEATURE - NOT STORED
  // "l5_games_used": 5,
  // "l10_games_used": 7,
}
```

**What ML Feature Store sees:**
```json
{
  "features": [22.4, 21.8, ...],
  "feature_quality_score": 72.0,  // One score for all

  // Doesn't know:
  // - feature[0] is 100% quality (5/5 games)
  // - feature[1] is 70% quality (7/10 games)
}
```

**What ML model uses:**
```python
# Current approach:
prediction = model.predict([22.4, 21.8, ...])
# Treats all features equally

# Model could use overall quality as feature:
prediction = model.predict([22.4, 21.8, ..., 72.0])  # Add quality as feature
# But still treats feature[0] and feature[1] equally
```

---

### Example 2: Player Injury - Most Features Full, Some Partial

**Reality (mid-season player returns from injury):**
```python
games_played_season = 5        # Only 5 games (most players have 30)
L5_games = 5                   # Full L5 window ✅
L10_games = 5                  # Partial L10 window ⚠️
season_avg_games = 5           # All available games
```

**What gets stored (current):**
```json
{
  // VALUES
  "points_avg_last_5": 18.2,   // From 5 games (good quality)
  "points_avg_last_10": 18.2,  // From 5 games (poor quality)

  // AGGREGATE METADATA
  "overall_quality": 60.0,     // Low because L10 is partial
  "completeness_percentage": 25.0,  // Only 5/20 expected games

  // PER-FEATURE - NOT STORED
  // If it were:
  // "l5_quality": 100,         // 5/5 games
  // "l10_quality": 50,         // 5/10 games
}
```

**What ML model sees:**
```python
# Current: Treats all features as 60% quality
# Reality: L5 is 100%, L10 is 50%
# Model can't distinguish!
```

---

## How Current Approach Handles This

### Proxy Metadata (What We Use Now)

**1. Overall Quality Score**
```python
# Calculated in ML Feature Store quality_scorer
quality_score = calculate_overall_quality(
    source_completeness=[70, 85, 90, 95],  # 4 sources
    early_season=False,
    games_available=7
)
# Result: 72.0

# This is reasonable proxy:
# - If L10 is 70%, most features probably 70-80%
# - Close enough for model to learn
```

**2. Source-Level Completeness**
```json
{
  // We track completeness PER SOURCE TABLE (4 sources)
  "source_daily_cache_completeness_pct": 70.0,     // Has L5, L10, season avg
  "source_composite_completeness_pct": 85.0,       // Has fatigue, pace, usage
  "source_shot_zones_completeness_pct": 90.0,      // Has shot zone tendencies
  "source_team_defense_completeness_pct": 95.0     // Has opponent defense
}
```

**This gives some granularity:**
- Features from daily_cache (features 0-4) → 70% quality
- Features from composite (features 5-8) → 85% quality
- Features from shot_zones (features 18-20) → 90% quality
- Features from team_defense (features 13-14) → 95% quality

**Model could use this:**
```python
# Map features to their sources
feature_source_map = {
    0: 'daily_cache',     # points_avg_last_5
    1: 'daily_cache',     # points_avg_last_10
    5: 'composite',       # fatigue_score
    13: 'team_defense',   # opponent_def_rating
    # ...
}

# Apply source-level quality
for i, feature in enumerate(features):
    source = feature_source_map[i]
    source_quality = source_completeness[source]

    # Weight feature by source quality
    weighted_feature = feature * (source_quality / 100)
```

**We don't do this currently, but COULD without schema changes!**

---

## Should We Add Per-Feature Metadata?

### Arguments FOR (Add It)

**1. Better ML Model**
- Model can weight features by individual quality
- More accurate when features have mixed quality
- Better handling of injuries, trades, late starts

**2. Better Debugging**
- "Why was prediction wrong?" → "L30 only had 5 games"
- Can identify which features are weak
- Better production monitoring

**3. Future Flexibility**
- Enables advanced ML techniques (feature-specific confidence)
- Supports explainable AI (which features drove prediction)
- Better A/B testing capabilities

### Arguments AGAINST (Keep Aggregate)

**1. Complexity**
- More complex schema (3-4 arrays vs 1 score)
- More complex queries
- More storage costs

**2. Diminishing Returns**
- Overall quality is good proxy
- Source-level metadata gives some granularity
- Model may not improve much with per-feature quality

**3. Not Blocking**
- Current implementation works
- Can add later if needed
- Schema migration is deferred, not abandoned

### Recommendation

**Phase 1 (Now): Keep aggregate metadata ✅**
- Already implemented
- Good enough for MVP
- Can validate approach

**Phase 2 (Post-October 2025): Evaluate need**
- Collect data on prediction accuracy
- See if mixed-quality features cause issues
- Check if model would benefit from per-feature quality

**Phase 3 (If beneficial): Add per-feature metadata**
- Migrate schema to add arrays
- Update processors to populate
- Train new model with per-feature quality
- A/B test vs aggregate approach

---

## Summary: Your Question Answered

### Q: "Is metadata for each field being passed to downstream processors?"

**Answer:**

**YES - Aggregate level:**
- ✅ Overall quality score (one number for all 25 features)
- ✅ Source-level completeness (4 numbers, one per upstream table)
- ✅ Processor-level metadata (early_season_flag, insufficient_data_reason)

**NO - Per-feature level:**
- ❌ Per-feature quality scores (25 numbers, one per feature)
- ❌ Per-feature games_used (25 numbers, one per feature)
- ⏳ Designed but schema migration deferred

**Implication:**
- ML model sees: "Overall quality is 72%"
- ML model doesn't see: "Feature[0] is 100%, feature[1] is 70%"
- This is OK for now - overall quality is reasonable proxy
- Can enhance later if accuracy requires it

**What downstream CAN determine:**
- Is this early season? (early_season_flag)
- Is quality acceptable? (feature_quality_score >= 70)
- Which sources are weak? (source_*_completeness_pct)
- Is data production ready? (is_production_ready)

**What downstream CANNOT determine:**
- Which specific features are partial vs full
- Exactly how many games each feature used
- Per-feature confidence scores

---

## Verification Queries

### See what metadata actually flows:

```sql
-- What ML Feature Store has
SELECT
  player_lookup,
  game_date,

  -- AGGREGATE METADATA (what we have)
  feature_quality_score,
  early_season_flag,
  completeness_percentage,

  -- SOURCE-LEVEL METADATA (what we have)
  source_daily_cache_completeness_pct,
  source_composite_completeness_pct,

  -- PER-FEATURE METADATA (what we DON'T have)
  -- feature_quality_scores,  -- Doesn't exist
  -- feature_games_used       -- Doesn't exist

FROM ml_feature_store_v2
WHERE game_date = '2024-10-31'
LIMIT 5;
```

---

## References

- IMPLEMENTATION-PLAN.md - Q1 on partial windows with metadata
- PARTIAL-WINDOWS-AND-NULL-HANDLING.md - How we handle insufficient data
- player_daily_cache.sql (lines 41+) - Where games_used WOULD go
- ml_feature_store_v2.sql (line 30) - Current quality_score field

---

**Excellent question! This is important for ML model design.** ✅

**Current approach: Aggregate metadata is sufficient for MVP**
**Future: Can add per-feature metadata if accuracy requires it**
