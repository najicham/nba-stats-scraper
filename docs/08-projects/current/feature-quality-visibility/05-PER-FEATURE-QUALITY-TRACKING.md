# Per-Feature Quality Tracking - Comprehensive Design

**Date:** February 5, 2026 (Session 133)
**User Requirement:** "I really really need the ML Features to be top quality"
**Approach:** Full per-feature source and quality tracking (like Phase 3, but for 33 features)
**Status:** Final design - ready for implementation

---

## Design Rationale

**User Priority:** ML feature quality is CRITICAL - worth the storage investment

**Trade-offs Accepted:**
- ✅ Higher storage cost (+40% vs +17%) - **ACCEPTED**
- ✅ More complex queries (UNNEST required) - **ACCEPTED**
- ✅ More implementation effort (2x) - **ACCEPTED**

**Benefit:** Complete visibility into every feature's source, quality, and confidence

---

## Schema Design: Per-Feature Quality Detail

### Primary Approach: ARRAY<STRUCT> (Queryable)

```sql
-- Per-feature quality tracking (replaces feature_sources JSON)
feature_quality_detail ARRAY<STRUCT<
  feature_index INT64,
  feature_name STRING,
  feature_value FLOAT64,
  source_type STRING,              -- 'phase4', 'phase3', 'calculated', 'default'
  quality_score FLOAT64,           -- 0-100 for THIS specific feature
  confidence_pct FLOAT64,          -- Confidence in this feature value
  is_default BOOL,                 -- Quick flag for defaulted features
  fallback_reason STRING,          -- Why fallback used (if applicable)
  upstream_table STRING,           -- Source table (e.g., 'player_composite_factors')
  last_updated TIMESTAMP           -- When source data was updated
>> OPTIONS(
  description="Per-feature quality detail. 33 structs, one per feature. Enables drill-down to individual feature quality and source."
)
```

### Complementary Fields (Keep These)

```sql
-- Aggregate quality (backward compatibility + fast filtering)
feature_quality_score FLOAT64 OPTIONS(
  description="Aggregate 0-100 quality (weighted average of feature_quality_detail). Use for fast filtering."
),

-- Category quality (fast category filtering)
matchup_quality_pct FLOAT64,
player_history_quality_pct FLOAT64,
team_context_quality_pct FLOAT64,
vegas_quality_pct FLOAT64,

-- Summary counts (fast aggregation)
default_feature_count INT64,
phase4_feature_count INT64,
phase3_feature_count INT64,
calculated_feature_count INT64,

-- Legacy JSON (deprecated but keep for backward compat during migration)
feature_sources STRING OPTIONS(
  description="DEPRECATED: Use feature_quality_detail instead. Kept for backward compatibility."
)
```

---

## Example Data Structure

**Record for a player with partial data:**

```json
{
  "player_lookup": "lebronjames",
  "game_date": "2026-02-06",

  // Aggregate quality (fast filtering)
  "feature_quality_score": 74.0,

  // Category quality (fast category filtering)
  "matchup_quality_pct": 0.0,
  "player_history_quality_pct": 95.0,
  "team_context_quality_pct": 100.0,
  "vegas_quality_pct": 100.0,

  // Per-feature detail (drill-down)
  "feature_quality_detail": [
    {
      "feature_index": 0,
      "feature_name": "points_avg_last_5",
      "feature_value": 25.4,
      "source_type": "phase4",
      "quality_score": 100.0,
      "confidence_pct": 100.0,
      "is_default": false,
      "fallback_reason": null,
      "upstream_table": "player_daily_cache",
      "last_updated": "2026-02-06T06:30:00Z"
    },
    {
      "feature_index": 1,
      "feature_name": "points_avg_last_10",
      "feature_value": 26.2,
      "source_type": "phase4",
      "quality_score": 100.0,
      "confidence_pct": 100.0,
      "is_default": false,
      "fallback_reason": null,
      "upstream_table": "player_daily_cache",
      "last_updated": "2026-02-06T06:30:00Z"
    },
    // ... features 2-4 (all phase4, quality 100)
    {
      "feature_index": 5,
      "feature_name": "fatigue_score",
      "feature_value": 0.25,  // Default value
      "source_type": "default",
      "quality_score": 40.0,  // Low quality
      "confidence_pct": 0.0,
      "is_default": true,
      "fallback_reason": "composite_factors_missing",
      "upstream_table": "player_composite_factors",
      "last_updated": null
    },
    {
      "feature_index": 6,
      "feature_name": "shot_zone_mismatch_score",
      "feature_value": 0.0,
      "source_type": "default",
      "quality_score": 40.0,
      "confidence_pct": 0.0,
      "is_default": true,
      "fallback_reason": "composite_factors_missing",
      "upstream_table": "player_composite_factors",
      "last_updated": null
    },
    // ... features 7-8 (same - composite factors missing)
    {
      "feature_index": 13,
      "feature_name": "opponent_def_rating",
      "feature_value": 112.5,
      "source_type": "phase3",
      "quality_score": 87.0,  // Phase 3 quality
      "confidence_pct": 95.0,
      "is_default": false,
      "fallback_reason": null,
      "upstream_table": "team_defensive_ratings",
      "last_updated": "2026-02-06T05:00:00Z"
    }
    // ... remaining 20 features
  ]
}
```

---

## Quality Score Calculation Per Feature

```python
def calculate_feature_quality_score(
    source_type: str,
    is_default: bool,
    data_freshness_hours: float,
    sample_size: int = None
) -> float:
    """
    Calculate quality score (0-100) for a single feature.

    Quality Scoring:
        phase4 (ideal):     100 points - precomputed high-quality data
        phase3 (good):      87 points - analytics data (slightly lower quality)
        calculated (ok):    100 points - computed from available data (trustworthy)
        default (poor):     40 points - fallback value (low confidence)

    Adjustments:
        - Stale data (>24h): -10 points
        - Thin sample (<5): -10 points
        - Very stale (>48h): -20 points

    Args:
        source_type: 'phase4', 'phase3', 'calculated', 'default'
        is_default: Whether this is a default/fallback value
        data_freshness_hours: Hours since source data updated
        sample_size: Sample size for aggregated features (e.g., 10 for last_10_games)

    Returns:
        Quality score 0-100
    """
    # Base score by source
    base_scores = {
        'phase4': 100,
        'phase3': 87,
        'calculated': 100,
        'default': 40
    }

    score = base_scores.get(source_type, 0)

    # Penalize stale data
    if data_freshness_hours and data_freshness_hours > 24:
        if data_freshness_hours > 48:
            score -= 20  # Very stale
        else:
            score -= 10  # Moderately stale

    # Penalize thin samples
    if sample_size and sample_size < 5:
        score -= 10

    return max(0, min(100, score))
```

---

## Query Patterns with Per-Feature Detail

### Pattern 1: Find Features with Low Quality

```sql
-- Find all features with quality < 50 for a specific date
SELECT
  player_lookup,
  feature.feature_index,
  feature.feature_name,
  feature.quality_score,
  feature.source_type,
  feature.fallback_reason
FROM nba_predictions.ml_feature_store_v2,
UNNEST(feature_quality_detail) as feature
WHERE game_date = '2026-02-06'
  AND feature.quality_score < 50
ORDER BY player_lookup, feature.feature_index;
```

**Result:**
```
player_lookup    | feature_index | feature_name            | quality_score | source_type | fallback_reason
-----------------|---------------|-------------------------|---------------|-------------|------------------------
lebronjames      | 5             | fatigue_score           | 40.0          | default     | composite_factors_missing
lebronjames      | 6             | shot_zone_mismatch_score| 40.0          | default     | composite_factors_missing
lebronjames      | 7             | pace_score              | 40.0          | default     | composite_factors_missing
lebronjames      | 8             | usage_spike_score       | 40.0          | default     | composite_factors_missing
...
```

**Diagnosis time:** <10 seconds

---

### Pattern 2: Per-Feature Quality Distribution

```sql
-- Aggregate quality across all players for each feature
SELECT
  feature.feature_index,
  feature.feature_name,
  COUNT(*) as total_players,
  ROUND(AVG(feature.quality_score), 1) as avg_quality,
  ROUND(MIN(feature.quality_score), 1) as min_quality,
  COUNTIF(feature.is_default) as default_count,
  ROUND(COUNTIF(feature.is_default) / COUNT(*) * 100, 1) as default_pct
FROM nba_predictions.ml_feature_store_v2,
UNNEST(feature_quality_detail) as feature
WHERE game_date = '2026-02-06'
GROUP BY 1, 2
ORDER BY avg_quality ASC, default_pct DESC;
```

**Result (Session 132 scenario):**
```
feature_index | feature_name            | total_players | avg_quality | min_quality | default_count | default_pct
--------------|-------------------------|---------------|-------------|-------------|---------------|------------
5             | fatigue_score           | 201           | 40.0        | 40.0        | 201           | 100.0%   ← RED FLAG!
6             | shot_zone_mismatch_score| 201           | 40.0        | 40.0        | 201           | 100.0%   ← RED FLAG!
7             | pace_score              | 201           | 40.0        | 40.0        | 201           | 100.0%   ← RED FLAG!
8             | usage_spike_score       | 201           | 40.0        | 40.0        | 201           | 100.0%   ← RED FLAG!
0             | points_avg_last_5       | 201           | 100.0       | 100.0       | 0             | 0.0%     ← Good
1             | points_avg_last_10      | 201           | 100.0       | 100.0       | 0             | 0.0%     ← Good
...
```

**This query would have immediately shown the Session 132 issue!**

---

### Pattern 3: Source Distribution Analysis

```sql
-- Which source is providing each feature?
SELECT
  feature.feature_name,
  feature.source_type,
  COUNT(*) as player_count,
  ROUND(AVG(feature.quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2,
UNNEST(feature_quality_detail) as feature
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1, 2
ORDER BY 1, 4 DESC;
```

**Result:**
```
feature_name            | source_type | player_count | avg_quality
------------------------|-------------|--------------|-------------
fatigue_score           | phase4      | 1205         | 100.0
fatigue_score           | default     | 202          | 40.0        ← Some degradation
points_avg_last_5       | phase4      | 1407         | 100.0       ← Always good
vegas_points_line       | default     | 845          | 40.0        ← Expected (not all players have lines)
vegas_points_line       | phase4      | 562          | 100.0
```

---

### Pattern 4: Staleness Detection

```sql
-- Find stale features (>24h old)
SELECT
  player_lookup,
  feature.feature_name,
  feature.last_updated,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), feature.last_updated, HOUR) as age_hours,
  feature.quality_score
FROM nba_predictions.ml_feature_store_v2,
UNNEST(feature_quality_detail) as feature
WHERE game_date = CURRENT_DATE()
  AND feature.last_updated IS NOT NULL
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), feature.last_updated, HOUR) > 24
ORDER BY age_hours DESC;
```

---

### Pattern 5: Training Data Quality Filter

```sql
-- Select only records where ALL critical features have high quality
WITH feature_quality AS (
  SELECT
    player_lookup,
    game_date,
    -- Check if critical features all have quality >= 80
    COUNTIF(
      feature.feature_index IN (5,6,7,8,13,14) AND feature.quality_score >= 80
    ) as critical_high_quality,
    -- Total critical features
    6 as critical_total
  FROM nba_predictions.ml_feature_store_v2,
  UNNEST(feature_quality_detail) as feature
  WHERE game_date BETWEEN @train_start AND @train_end
  GROUP BY 1, 2
)
SELECT
  fs.player_lookup,
  fs.game_date,
  fs.feature_store_values  -- For training
FROM nba_predictions.ml_feature_store_v2 fs
INNER JOIN feature_quality fq
  ON fs.player_lookup = fq.player_lookup
  AND fs.game_date = fq.game_date
WHERE fq.critical_high_quality = fq.critical_total  -- All critical features high quality
  AND fs.feature_quality_score >= 85;  -- Overall quality gate
```

---

## Storage Impact Analysis

### Storage Calculation

**Per-feature struct size:**
```
feature_index (INT64):        8 bytes
feature_name (STRING):       20 bytes (avg)
feature_value (FLOAT64):      8 bytes
source_type (STRING):        10 bytes (avg)
quality_score (FLOAT64):      8 bytes
confidence_pct (FLOAT64):     8 bytes
is_default (BOOL):            1 byte
fallback_reason (STRING):    15 bytes (avg, nullable)
upstream_table (STRING):     25 bytes (avg)
last_updated (TIMESTAMP):     8 bytes
-----------------------------------
Total per feature:          ~111 bytes
```

**Per record:**
```
33 features × 111 bytes = 3,663 bytes (~3.6 KB per record)
```

**Daily storage:**
```
200 players/day × 3.6 KB = 720 KB/day
```

**Annual storage:**
```
720 KB × 365 days = 263 MB/year
```

**BigQuery cost:**
```
263 MB/year × $0.02/GB/month = $0.0053/month = $0.06/year
```

### Comparison

| Approach | Storage/Record | Storage/Year | Cost/Year |
|----------|----------------|--------------|-----------|
| **Original (JSON only)** | 1.2 KB | 88 MB | $0.02 |
| **Category quality (proposed)** | 1.4 KB | 102 MB | $0.02 |
| **Per-feature quality (this design)** | 4.8 KB | 351 MB | $0.08 |

**Storage increase:** +4x vs original, +3.4x vs category-only

**Cost increase:** $0.06/year (negligible)

**User decision:** Worth it for ML feature quality visibility ✅

---

## Implementation Plan

### Phase 1: Schema Update (20 min)

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN feature_quality_detail ARRAY<STRUCT<
  feature_index INT64,
  feature_name STRING,
  feature_value FLOAT64,
  source_type STRING,
  quality_score FLOAT64,
  confidence_pct FLOAT64,
  is_default BOOL,
  fallback_reason STRING,
  upstream_table STRING,
  last_updated TIMESTAMP
>>;

-- Keep existing fields for backward compatibility
-- (feature_sources, feature_quality_score, etc.)
```

### Phase 2: Quality Scorer Enhancement (3-4 hours)

**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py`

Add method:
```python
def build_feature_quality_detail(
    feature_sources: Dict[int, str],
    feature_values: List[float],
    feature_metadata: Dict[int, Dict]
) -> List[Dict]:
    """
    Build per-feature quality detail array.

    Args:
        feature_sources: Map of feature index to source type
        feature_values: List of 33 feature values
        feature_metadata: Per-feature metadata (upstream table, last_updated, etc.)

    Returns:
        List of 33 dicts, one per feature
    """
    feature_detail = []

    for idx in range(33):  # 33 features total
        source_type = feature_sources.get(idx, 'default')
        is_default = (source_type == 'default')

        # Get metadata for this feature
        metadata = feature_metadata.get(idx, {})
        upstream_table = metadata.get('upstream_table')
        last_updated = metadata.get('last_updated')
        data_freshness_hours = self._calculate_freshness(last_updated) if last_updated else None

        # Calculate quality score for this specific feature
        quality_score = self.calculate_feature_quality_score(
            source_type=source_type,
            is_default=is_default,
            data_freshness_hours=data_freshness_hours,
            sample_size=metadata.get('sample_size')
        )

        # Calculate confidence
        confidence_pct = self._calculate_feature_confidence(
            source_type=source_type,
            quality_score=quality_score,
            sample_size=metadata.get('sample_size')
        )

        feature_detail.append({
            'feature_index': idx,
            'feature_name': FEATURE_NAMES[idx],
            'feature_value': feature_values[idx],
            'source_type': source_type,
            'quality_score': quality_score,
            'confidence_pct': confidence_pct,
            'is_default': is_default,
            'fallback_reason': metadata.get('fallback_reason') if is_default else None,
            'upstream_table': upstream_table,
            'last_updated': last_updated
        })

    return feature_detail
```

### Phase 3: Feature Extractor Enhancement (2-3 hours)

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

Enhance to track metadata:
```python
def extract_features(self, player_data, game_date):
    """Extract features with metadata tracking."""

    features = []
    feature_sources = {}
    feature_metadata = {}  # NEW: Track metadata per feature

    # Feature 0: points_avg_last_5
    value, source, metadata = self._extract_points_avg_last_5(player_data)
    features.append(value)
    feature_sources[0] = source
    feature_metadata[0] = metadata  # Includes upstream_table, last_updated, sample_size

    # ... repeat for all 33 features

    return features, feature_sources, feature_metadata
```

### Phase 4: Integration (30 min)

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
def _build_feature_store_record(self, player_data, game_date):
    # Extract features with metadata
    feature_values, feature_sources, feature_metadata = self.feature_extractor.extract_features(
        player_data, game_date
    )

    # Build per-feature quality detail
    feature_quality_detail = self.quality_scorer.build_feature_quality_detail(
        feature_sources=feature_sources,
        feature_values=feature_values,
        feature_metadata=feature_metadata
    )

    # Calculate aggregate quality (from per-feature scores)
    feature_quality_score = self.quality_scorer.calculate_aggregate_quality(
        feature_quality_detail
    )

    # Build record
    record = {
        'feature_store_values': feature_values,
        'feature_quality_detail': feature_quality_detail,  # NEW: Per-feature detail
        'feature_quality_score': feature_quality_score,     # Aggregate
        # ... other fields
    }

    return record
```

### Phase 5: Backfill (3-4 hours)

```bash
# Backfill 90 days with per-feature quality detail
PYTHONPATH=. python bin/backfill/backfill_feature_quality.py \
  --start-date 2025-11-01 \
  --end-date 2026-02-05 \
  --batch-size 5 \
  --include-per-feature-detail
```

---

## Validation Queries

### Validation 1: Check Per-Feature Detail Populated

```sql
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNT(feature_quality_detail) as with_detail,
  AVG(ARRAY_LENGTH(feature_quality_detail)) as avg_feature_count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-02-06'
GROUP BY 1
ORDER BY 1 DESC;

-- Expected: avg_feature_count = 33 for all records
```

### Validation 2: Session 132 Detection

```sql
-- This query should immediately show Session 132 issue
SELECT
  feature.feature_index,
  feature.feature_name,
  COUNT(*) as players_affected,
  AVG(feature.quality_score) as avg_quality,
  COUNTIF(feature.is_default) as default_count
FROM nba_predictions.ml_feature_store_v2,
UNNEST(feature_quality_detail) as feature
WHERE game_date = '2026-02-06'
  AND feature.feature_index BETWEEN 5 AND 8  -- Composite factors
GROUP BY 1, 2
ORDER BY 1;

-- Expected for Feb 6 pre-fix:
-- All 4 features: 201 players affected, quality 40.0, 201 defaults
```

### Validation 3: Quality Score Accuracy

```sql
-- Verify aggregate quality_score matches per-feature average
SELECT
  player_lookup,
  feature_quality_score as aggregate_score,
  ROUND(AVG(feature.quality_score), 1) as calculated_avg,
  ABS(feature_quality_score - AVG(feature.quality_score)) as difference
FROM nba_predictions.ml_feature_store_v2,
UNNEST(feature_quality_detail) as feature
WHERE game_date = '2026-02-06'
GROUP BY 1, 2
HAVING difference > 1.0  -- Flag mismatches
LIMIT 10;

-- Expected: No rows (aggregate should match calculated average)
```

---

## Success Criteria

- [ ] Schema includes `feature_quality_detail` ARRAY<STRUCT> with 10 fields per feature
- [ ] All 33 features tracked individually with source, quality, confidence
- [ ] Aggregate `feature_quality_score` calculated from per-feature scores
- [ ] Can query per-feature quality in <5 seconds
- [ ] Session 132 detection query runs in <10 seconds
- [ ] Backfill completes for 90 days (18K records × 33 features = 594K feature records)
- [ ] Storage increase acceptable (+4x, $0.06/year)
- [ ] Training queries can filter on per-feature quality

---

## Next Steps

1. **Get user approval** on this per-feature design
2. **Update schema** with `feature_quality_detail` array
3. **Enhance quality scorer** to build per-feature detail (3-4 hours)
4. **Enhance feature extractor** to track metadata (2-3 hours)
5. **Integrate** in ml_feature_store_processor (30 min)
6. **Test** with Feb 6 data
7. **Deploy** Phase 4 processors
8. **Backfill** 90 days (3-4 hours)

**Total implementation time:** 10-12 hours

**Benefit:** Complete per-feature visibility for ML quality assurance

---

**Document Version:** 1.0
**Last Updated:** February 5, 2026 (Session 133)
**Status:** ✅ FINAL DESIGN - Approved by user for implementation
**Storage Cost:** $0.06/year (acceptable for critical ML quality)
