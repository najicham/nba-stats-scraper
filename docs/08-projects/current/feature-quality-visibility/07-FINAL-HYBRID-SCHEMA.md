# Final Hybrid Schema - Maximum Safety, Minimum Complexity

**Date:** February 5, 2026 (Session 133)
**Status:** ✅ FINAL - Ready for Implementation
**Approach:** Hybrid - Critical fields as columns, details as JSON
**Priority:** CRITICAL - "Daily data quality issues need to stop"
**User Requirement:** "Safest and easiest, even if inefficient"

---

## Design Rationale

### User Context
- Daily ML feature quality issues
- Need maximum safety and visibility
- Dislike STRUCTs (complex to read/write)
- Want easiest approach for debugging

### Solution: Hybrid Approach
- **74 per-feature columns** for critical attributes (quality + source)
- **JSON strings** for detailed attributes
- **All aggregate/category fields** as flat columns
- **Zero nested STRUCTs** - all flat or JSON

### Why This Works
- 90% of queries use direct columns (fast)
- 10% of queries parse JSON (acceptable)
- Easy to implement in Python
- Easy for other chats/agents to understand
- Manageable schema (~122 fields)

---

## Complete Schema Definition

### SECTION 1: Aggregate Quality (11 fields - FLAT)

```sql
-- Overall quality scores
feature_quality_score FLOAT64 OPTIONS(
  description="Aggregate 0-100 quality score (weighted average of all 37 features). Use for fast filtering. BACKWARD COMPATIBLE."
),

quality_tier STRING OPTIONS(
  description="Overall tier: 'gold' (>95), 'silver' (85-95), 'bronze' (70-85), 'poor' (50-70), 'critical' (<50). Lowercase matches Phase 3."
),

quality_alert_level STRING OPTIONS(
  description="Alert priority: 'green' (healthy), 'yellow' (degraded), 'red' (critical). For real-time monitoring."
),

quality_alerts ARRAY<STRING> OPTIONS(
  description="Specific alerts triggered: ['all_matchup_features_defaulted', 'high_default_rate_20pct']. Matches Phase 3 quality_issues pattern."
),

-- Source distribution totals
default_feature_count INT64 OPTIONS(
  description="Total count of features using defaults. Session 132: 4 defaults (all matchup features)."
),

phase4_feature_count INT64 OPTIONS(
  description="Count of features from Phase 4 precompute (highest quality). Target: 25+ of 37."
),

phase3_feature_count INT64 OPTIONS(
  description="Count of features from Phase 3 analytics (good quality fallback)."
),

calculated_feature_count INT64 OPTIONS(
  description="Count of features calculated on-the-fly (acceptable quality)."
),

-- Production gates
is_production_ready BOOL OPTIONS(
  description="TRUE if safe for production: quality_tier in ('gold','silver','bronze') AND score >= 70 AND matchup_quality_pct >= 50. Bronze floor is 70."
),

is_training_ready BOOL OPTIONS(
  description="TRUE if meets training bar (stricter): quality_tier in ('gold','silver'), matchup >= 70, history >= 80."
),

training_quality_feature_count INT64 OPTIONS(
  description="Count of features meeting training quality bar. Use for filtering: WHERE training_quality_feature_count >= 30."
)
```

---

### SECTION 2: Category-Level Quality (18 fields - FLAT)

```sql
-- Category quality percentages (0-100)
matchup_quality_pct FLOAT64 OPTIONS(
  description="Quality % for matchup features (5-8: composite, 13-14: opponent defense). 0=all defaults, 100=all high quality. Session 132: This was 0%."
),

player_history_quality_pct FLOAT64 OPTIONS(
  description="Quality % for player history features (0-4, 29-36). 13 features total. Typically 90-100% (good Phase 3 coverage)."
),

team_context_quality_pct FLOAT64 OPTIONS(
  description="Quality % for team context features (22-24). Usually 95-100% (Phase 3 team stats reliable)."
),

vegas_quality_pct FLOAT64 OPTIONS(
  description="Quality % for vegas features (25-28). Expected 40-60% (not all players have lines - NORMAL)."
),

-- Category default counts
matchup_default_count INT64 OPTIONS(
  description="Count of matchup features (6 total: 5-8, 13-14) using defaults. Session 132: 6/6 defaulted."
),

player_history_default_count INT64 OPTIONS(
  description="Count of player history features (0-4, 29-36) using defaults. 13 features total."
),

team_context_default_count INT64 OPTIONS(
  description="Count of team context features using defaults."
),

vegas_default_count INT64 OPTIONS(
  description="Count of vegas features using defaults. High count is NORMAL (not all players have lines)."
),

-- Critical feature flags
has_composite_factors BOOL OPTIONS(
  description="TRUE if composite factors (features 5-8) available from Phase 4. Session 132: All FALSE caused issue."
),

has_opponent_defense BOOL OPTIONS(
  description="TRUE if opponent defense data (features 13-14) available from Phase 3."
),

has_vegas_line BOOL OPTIONS(
  description="TRUE if vegas line available. FALSE is normal for low-volume props."
),

-- Training quality gates
critical_features_training_quality BOOL OPTIONS(
  description="TRUE if ALL critical features (matchup 5-8, defense 13-14) meet training quality bar."
),

critical_feature_count INT64 OPTIONS(
  description="Count of CRITICAL features present with high quality. Missing critical = low model confidence."
),

optional_feature_count INT64 OPTIONS(
  description="Count of optional features present. Missing optional = acceptable."
),

-- Category tiers
matchup_quality_tier STRING OPTIONS(
  description="Matchup category tier: 'gold', 'silver', 'bronze', 'poor', 'critical'. Derived from matchup_quality_pct."
),

game_context_quality_pct FLOAT64 OPTIONS(
  description="Quality % for game context features (9-12, 15-21): rest_advantage, injury_risk, recent_trend, minutes_change, home_away, back_to_back, playoff_game, shot zones. 11 features total."
),

game_context_default_count INT64 OPTIONS(
  description="Count of game context features (11 total: 9-12, 15-21) using defaults."
),

game_context_quality_tier STRING OPTIONS(
  description="Game context category tier: 'gold', 'silver', 'bronze', 'poor', 'critical'. Derived from game_context_quality_pct."
)
```

---

### SECTION 3: Per-Feature Quality Scores (37 fields - FLAT)

```sql
-- Quality score (0-100) for each of 37 features
-- CRITICAL for daily debugging - direct column access

feature_0_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 0 (points_avg_last_5)"),
feature_1_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 1 (points_avg_last_10)"),
feature_2_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 2 (points_avg_season)"),
feature_3_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 3 (points_std_last_10)"),
feature_4_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 4 (games_in_last_7_days)"),

feature_5_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 5 (fatigue_score - CRITICAL)"),
feature_6_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 6 (shot_zone_mismatch_score - CRITICAL)"),
feature_7_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 7 (pace_score - CRITICAL)"),
feature_8_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 8 (usage_spike_score - CRITICAL)"),

feature_9_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 9 (rest_advantage)"),
feature_10_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 10 (injury_risk)"),
feature_11_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 11 (recent_trend)"),
feature_12_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 12 (minutes_change)"),

feature_13_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 13 (opponent_def_rating - CRITICAL)"),
feature_14_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 14 (opponent_pace - CRITICAL)"),

feature_15_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 15 (home_away)"),
feature_16_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 16 (back_to_back)"),
feature_17_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 17 (playoff_game)"),
feature_18_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 18 (pct_paint)"),
feature_19_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 19 (pct_mid_range)"),
feature_20_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 20 (pct_three)"),
feature_21_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 21 (pct_free_throw)"),

feature_22_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 22 (team_pace)"),
feature_23_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 23 (team_off_rating)"),
feature_24_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 24 (team_win_pct)"),

feature_25_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 25 (vegas_points_line)"),
feature_26_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 26 (vegas_opening_line)"),
feature_27_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 27 (vegas_line_move)"),
feature_28_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 28 (has_vegas_line)"),

feature_29_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 29 (avg_points_vs_opponent)"),
feature_30_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 30 (games_vs_opponent)"),
feature_31_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 31 (minutes_avg_last_10)"),
feature_32_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 32 (ppm_avg_last_10)"),

feature_33_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 33 (dnp_rate)"),
feature_34_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 34 (pts_slope_10g)"),
feature_35_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 35 (pts_vs_season_zscore)"),
feature_36_quality FLOAT64 OPTIONS(description="Quality score 0-100 for feature 36 (breakout_flag)")
```

---

### SECTION 4: Per-Feature Sources (37 fields - FLAT)

```sql
-- Source type for each of 37 features
-- CRITICAL for daily debugging - direct column access

feature_0_source STRING OPTIONS(description="Source for feature 0: 'phase4', 'phase3', 'calculated', 'default'"),
feature_1_source STRING OPTIONS(description="Source for feature 1: 'phase4', 'phase3', 'calculated', 'default'"),
feature_2_source STRING OPTIONS(description="Source for feature 2: 'phase4', 'phase3', 'calculated', 'default'"),
feature_3_source STRING OPTIONS(description="Source for feature 3: 'phase4', 'phase3', 'calculated', 'default'"),
feature_4_source STRING OPTIONS(description="Source for feature 4: 'phase4', 'phase3', 'calculated', 'default'"),

feature_5_source STRING OPTIONS(description="Source for feature 5 (fatigue_score - CRITICAL): 'phase4', 'phase3', 'calculated', 'default'"),
feature_6_source STRING OPTIONS(description="Source for feature 6 (shot_zone_mismatch_score - CRITICAL): 'phase4', 'phase3', 'calculated', 'default'"),
feature_7_source STRING OPTIONS(description="Source for feature 7 (pace_score - CRITICAL): 'phase4', 'phase3', 'calculated', 'default'"),
feature_8_source STRING OPTIONS(description="Source for feature 8 (usage_spike_score - CRITICAL): 'phase4', 'phase3', 'calculated', 'default'"),

feature_9_source STRING OPTIONS(description="Source for feature 9: 'phase4', 'phase3', 'calculated', 'default'"),
feature_10_source STRING OPTIONS(description="Source for feature 10: 'phase4', 'phase3', 'calculated', 'default'"),
feature_11_source STRING OPTIONS(description="Source for feature 11: 'phase4', 'phase3', 'calculated', 'default'"),
feature_12_source STRING OPTIONS(description="Source for feature 12: 'phase4', 'phase3', 'calculated', 'default'"),

feature_13_source STRING OPTIONS(description="Source for feature 13 (opponent_def_rating - CRITICAL): 'phase4', 'phase3', 'calculated', 'default'"),
feature_14_source STRING OPTIONS(description="Source for feature 14 (opponent_pace - CRITICAL): 'phase4', 'phase3', 'calculated', 'default'"),

feature_15_source STRING OPTIONS(description="Source for feature 15: 'phase4', 'phase3', 'calculated', 'default'"),
feature_16_source STRING OPTIONS(description="Source for feature 16: 'phase4', 'phase3', 'calculated', 'default'"),
feature_17_source STRING OPTIONS(description="Source for feature 17: 'phase4', 'phase3', 'calculated', 'default'"),
feature_18_source STRING OPTIONS(description="Source for feature 18: 'phase4', 'phase3', 'calculated', 'default'"),
feature_19_source STRING OPTIONS(description="Source for feature 19: 'phase4', 'phase3', 'calculated', 'default'"),
feature_20_source STRING OPTIONS(description="Source for feature 20: 'phase4', 'phase3', 'calculated', 'default'"),
feature_21_source STRING OPTIONS(description="Source for feature 21: 'phase4', 'phase3', 'calculated', 'default'"),

feature_22_source STRING OPTIONS(description="Source for feature 22: 'phase4', 'phase3', 'calculated', 'default'"),
feature_23_source STRING OPTIONS(description="Source for feature 23: 'phase4', 'phase3', 'calculated', 'default'"),
feature_24_source STRING OPTIONS(description="Source for feature 24: 'phase4', 'phase3', 'calculated', 'default'"),

feature_25_source STRING OPTIONS(description="Source for feature 25: 'phase4', 'phase3', 'calculated', 'default'"),
feature_26_source STRING OPTIONS(description="Source for feature 26: 'phase4', 'phase3', 'calculated', 'default'"),
feature_27_source STRING OPTIONS(description="Source for feature 27: 'phase4', 'phase3', 'calculated', 'default'"),
feature_28_source STRING OPTIONS(description="Source for feature 28: 'phase4', 'phase3', 'calculated', 'default'"),

feature_29_source STRING OPTIONS(description="Source for feature 29: 'phase4', 'phase3', 'calculated', 'default'"),
feature_30_source STRING OPTIONS(description="Source for feature 30: 'phase4', 'phase3', 'calculated', 'default'"),
feature_31_source STRING OPTIONS(description="Source for feature 31: 'phase4', 'phase3', 'calculated', 'default'"),
feature_32_source STRING OPTIONS(description="Source for feature 32: 'phase4', 'phase3', 'calculated', 'default'"),

feature_33_source STRING OPTIONS(description="Source for feature 33 (dnp_rate): 'phase4', 'phase3', 'calculated', 'default'"),
feature_34_source STRING OPTIONS(description="Source for feature 34 (pts_slope_10g): 'phase4', 'phase3', 'calculated', 'default'"),
feature_35_source STRING OPTIONS(description="Source for feature 35 (pts_vs_season_zscore): 'phase4', 'phase3', 'calculated', 'default'"),
feature_36_source STRING OPTIONS(description="Source for feature 36 (breakout_flag): 'phase4', 'phase3', 'calculated', 'default'")
```

---

### SECTION 5: Per-Feature Details (JSON - 6 fields)

```sql
-- Additional per-feature attributes as JSON strings
-- Used for deep investigation (10% of queries)

feature_fallback_reasons_json STRING OPTIONS(
  description="JSON map of fallback reasons (SPARSE - only defaulted features): {\"5\":\"composite_factors_missing\",\"6\":\"composite_factors_missing\",...}. Why defaults used."
),

feature_sample_sizes_json STRING OPTIONS(
  description="JSON map of sample sizes: {\"0\":5,\"1\":10,\"2\":82,...}. Sample size for rolling-window features (NULL if not applicable)."
),

feature_expected_values_json STRING OPTIONS(
  description="JSON map of expected/default values: {\"5\":0.25,\"6\":0.0,...}. Detect silent calculation failures when feature_value == expected_value for non-default source."
),

feature_value_ranges_valid_json STRING OPTIONS(
  description="JSON map of range validation: {\"0\":true,\"1\":true,\"13\":false,...}. TRUE if value within expected range."
),

feature_upstream_tables_json STRING OPTIONS(
  description="JSON map of upstream tables: {\"0\":\"player_daily_cache\",\"5\":\"player_composite_factors\",...}. Source table per feature."
),

feature_last_updated_json STRING OPTIONS(
  description="JSON map of last_updated timestamps: {\"0\":\"2026-02-06T06:30:00Z\",\"5\":null,...}. Freshness tracking per feature."
)
```

---

### SECTION 6: Model Compatibility (4 fields - FLAT/ARRAY)

```sql
-- Model/data compatibility tracking (Breakout integration + Session 133 blocker prevention)

feature_schema_version STRING OPTIONS(
  description="Feature schema version: 'v2_37features'. Validates model/data compatibility. Prevents Session 133 mismatch."
),

available_feature_names ARRAY<STRING> OPTIONS(
  description="List of feature names available in this record. Runtime validation before prediction."
),

breakout_model_compatible ARRAY<STRING> OPTIONS(
  description="Which breakout model versions this data supports: ['v2_14features', 'v3_13features']. Prevents train/eval mismatch."
),

breakout_v3_features_available BOOL OPTIONS(
  description="TRUE if V3 breakout features (star_teammate_out, fg_pct_last_game) populated. Required for V3 model predictions."
)
```

---

### SECTION 7: Traceability & Debugging (6 fields - FLAT)

```sql
-- Processor and pipeline tracking

upstream_processors_ran STRING OPTIONS(
  description="Comma-separated processors that ran for this date: 'PlayerCompositeFactorsProcessor,MLFeatureStoreProcessor'. Session 132: Missing 'PlayerCompositeFactorsProcessor'."
),

missing_processors STRING OPTIONS(
  description="Expected processors that DID NOT run. Session 132: 'PlayerCompositeFactorsProcessor' missing caused all matchup defaults."
),

-- Freshness tracking
feature_store_age_hours FLOAT64 OPTIONS(
  description="Hours since feature store computed. For training data filtering: exclude > 48h."
),

upstream_data_freshness_hours FLOAT64 OPTIONS(
  description="Hours since upstream data (Phase 3/4) updated. Detect stale dependencies."
),

-- Audit trail
quality_computed_at TIMESTAMP OPTIONS(
  description="When quality fields computed. Detect stale quality data."
),

quality_schema_version STRING OPTIONS(
  description="Overall quality schema version: 'v2.1_hybrid'. For handling quality field evolution."
)
```

---

### SECTION 8: Legacy Fields (Keep During Migration)

```sql
-- DEPRECATED - Keep for 3-month migration period
-- Do NOT remove until all consumers updated to new fields

feature_sources STRING OPTIONS(
  description="DEPRECATED: Legacy JSON mapping {\"0\":\"phase4\",\"5\":\"default\",...}. Use feature_N_source columns instead. Remove after 3 months."
),

primary_data_source STRING OPTIONS(
  description="DEPRECATED: Use feature_schema_version instead. Remove after 3 months."
),

matchup_data_status STRING OPTIONS(
  description="DEPRECATED: Use matchup_quality_pct and has_composite_factors instead. Remove after 3 months."
)
```

---

## Complete Field Summary

| Section | Field Type | Count | Purpose |
|---------|-----------|-------|---------|
| **1. Aggregate Quality** | FLAT | 11 | Fast filtering, overall health |
| **2. Category Quality** | FLAT | 18 | Category-level visibility |
| **3. Per-Feature Quality** | FLAT (37 columns) | 37 | Direct quality score access |
| **4. Per-Feature Source** | FLAT (37 columns) | 37 | Direct source type access |
| **5. Per-Feature Details** | JSON (6 strings) | 6 | Deep investigation |
| **6. Model Compatibility** | FLAT/ARRAY | 4 | Prevent Session 133 blocker |
| **7. Traceability** | FLAT | 6 | Debugging, freshness |
| **8. Legacy** | FLAT | 3 | Backward compatibility |
| **TOTAL** | **Mixed** | **122 fields** | Complete visibility |

---

## Storage Analysis

### Per-Record Storage

**Flat fields:**
- Aggregate (11 fields): ~150 bytes
- Category (18 fields): ~200 bytes
- Per-feature quality (37 × 8 bytes): ~296 bytes
- Per-feature source (37 × 10 bytes): ~370 bytes
- Model compat (4 fields): ~100 bytes
- Traceability (6 fields): ~80 bytes
- Legacy (3 fields): ~50 bytes
- **Subtotal flat:** ~1,240 bytes

**JSON strings:**
- 6 JSON fields × ~500 bytes each: ~3,000 bytes

**Total per record:** ~4.2 KB

### Annual Cost

```
200 players/day × 4.2 KB = 0.84 MB/day
0.84 MB × 365 days = 307 MB/year

BigQuery storage: $0.02/GB/month
Cost: 307 MB × $0.02/GB/month = $0.0061/month = $0.07/year
```

**Annual cost: $0.07/year** (negligible)

---

## Query Patterns (Real-World Examples)

### Pattern 1: Session 132 Detection (<5 seconds)

```sql
-- Find all players with bad composite factors (features 5-8)
SELECT
  player_lookup,
  feature_5_quality,  -- Direct column - FAST
  feature_6_quality,  -- Direct column - FAST
  feature_7_quality,  -- Direct column - FAST
  feature_8_quality,  -- Direct column - FAST
  feature_5_source,   -- Direct column - FAST
  feature_6_source,
  feature_7_source,
  feature_8_source
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-06'
  AND (feature_5_quality < 50
       OR feature_6_quality < 50
       OR feature_7_quality < 50
       OR feature_8_quality < 50);

-- Result (Session 132): 201 players, all 4 features at quality=40.0, source='default'
-- Diagnosis time: <5 seconds ✓
```

### Pattern 2: Training Data Filtering (<10 seconds)

```sql
-- Select only high-quality records for training
SELECT *
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2025-11-01' AND '2026-01-31'
  AND is_training_ready = TRUE
  AND critical_features_training_quality = TRUE
  AND feature_5_quality >= 85  -- Direct column check
  AND feature_6_quality >= 85
  AND feature_7_quality >= 85
  AND feature_8_quality >= 85;
```

### Pattern 3: Per-Feature Quality Distribution (<10 seconds)

```sql
-- Which features have the worst quality across all players?
SELECT
  'feature_0' as feature_name, AVG(feature_0_quality) as avg_quality, COUNTIF(feature_0_source = 'default') as default_count FROM ml_feature_store_v2 WHERE game_date = '2026-02-06'
UNION ALL
SELECT 'feature_1', AVG(feature_1_quality), COUNTIF(feature_1_source = 'default') FROM ml_feature_store_v2 WHERE game_date = '2026-02-06'
UNION ALL
SELECT 'feature_5', AVG(feature_5_quality), COUNTIF(feature_5_source = 'default') FROM ml_feature_store_v2 WHERE game_date = '2026-02-06'
UNION ALL
-- ... repeat for all 37 features
ORDER BY avg_quality ASC;

-- Result (Session 132): Features 5-8 at bottom with 40.0 avg quality, 201 defaults
```

### Pattern 4: Deep Dive with JSON (<30 seconds)

```sql
-- Why did feature 5 use defaults? Get full context
SELECT
  player_lookup,
  feature_5_quality,  -- Column
  feature_5_source,   -- Column
  JSON_EXTRACT_SCALAR(feature_fallback_reasons_json, '$.5') as fallback_reason,
  JSON_EXTRACT_SCALAR(feature_sample_sizes_json, '$.5') as sample_size,
  JSON_EXTRACT_SCALAR(feature_expected_values_json, '$.5') as expected_value,
  JSON_EXTRACT_SCALAR(feature_upstream_tables_json, '$.5') as upstream_table
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-06'
  AND feature_5_source = 'default'
LIMIT 10;

-- Result: fallback_reason='composite_factors_missing', upstream_table='player_composite_factors'
```

---

## Implementation Guide

### Python Code (Easy!)

```python
def build_feature_quality_fields(feature_sources, feature_values, feature_metadata):
    """
    Build hybrid schema fields - NO STRUCT complexity!

    Returns dict with 122 flat/JSON fields ready for BigQuery insert.
    """

    # Calculate quality scores for all 37 features
    quality_scores = {}
    quality_tiers = {}
    is_default = {}
    fallback_reasons = {}
    sample_sizes = {}
    expected_values = {}

    for idx in range(37):
        source = feature_sources.get(idx, 'default')
        metadata = feature_metadata.get(idx, {})

        # Calculate quality
        quality_scores[idx] = calculate_quality_score(source, metadata)
        quality_tiers[idx] = get_quality_tier(quality_scores[idx])
        is_default[idx] = (source == 'default')

        if is_default[idx]:
            fallback_reasons[idx] = metadata.get('fallback_reason')

        sample_sizes[idx] = metadata.get('sample_size')
        expected_values[idx] = metadata.get('expected_value')

    # Calculate category quality
    matchup_quality = calculate_category_quality([5,6,7,8,13,14], quality_scores)

    # Build record - ALL FLAT + JSON
    record = {
        # === SECTION 1: Aggregate Quality (11 fields) ===
        'feature_quality_score': sum(quality_scores.values()) / 37,
        'quality_tier': get_overall_tier(quality_scores),
        'quality_alert_level': calculate_alert_level(quality_scores),
        'quality_alerts': calculate_alerts(quality_scores, feature_sources),
        'default_feature_count': sum(is_default.values()),
        'phase4_feature_count': sum(1 for s in feature_sources.values() if s == 'phase4'),
        'phase3_feature_count': sum(1 for s in feature_sources.values() if s == 'phase3'),
        'calculated_feature_count': sum(1 for s in feature_sources.values() if s == 'calculated'),
        'is_production_ready': determine_production_ready(quality_scores),
        'is_training_ready': determine_training_ready(quality_scores),
        'training_quality_feature_count': sum(1 for q in quality_scores.values() if q >= 85),

        # === SECTION 2: Category Quality (18 fields) ===
        'matchup_quality_pct': matchup_quality,
        'player_history_quality_pct': calculate_category_quality([0,1,2,3,4,29,30,31,32,33,34,35,36], quality_scores),
        'team_context_quality_pct': calculate_category_quality([22,23,24], quality_scores),
        'vegas_quality_pct': calculate_category_quality([25,26,27,28], quality_scores),
        'matchup_default_count': sum(is_default[i] for i in [5,6,7,8,13,14]),
        'player_history_default_count': sum(is_default[i] for i in [0,1,2,3,4,29,30,31,32,33,34,35,36]),
        'team_context_default_count': sum(is_default[i] for i in [22,23,24]),
        'vegas_default_count': sum(is_default[i] for i in [25,26,27,28]),
        'has_composite_factors': not any(is_default[i] for i in [5,6,7,8]),
        'has_opponent_defense': not any(is_default[i] for i in [13,14]),
        'has_vegas_line': not is_default[28],
        'critical_features_training_quality': check_critical_training_quality(quality_scores),
        'critical_feature_count': count_critical_features(quality_scores),
        'optional_feature_count': count_optional_features(quality_scores),
        'matchup_quality_tier': get_quality_tier(matchup_quality),
        'game_context_quality_pct': calculate_category_quality([9,10,11,12,15,16,17,18,19,20,21], quality_scores),
        'game_context_default_count': sum(is_default[i] for i in [9,10,11,12,15,16,17,18,19,20,21]),
        'game_context_quality_tier': get_quality_tier(calculate_category_quality([9,10,11,12,15,16,17,18,19,20,21], quality_scores)),

        # === SECTION 3: Per-Feature Quality (37 columns) ===
        'feature_0_quality': quality_scores[0],
        'feature_1_quality': quality_scores[1],
        'feature_2_quality': quality_scores[2],
        # ... all 37 features
        'feature_32_quality': quality_scores[32],
        'feature_33_quality': quality_scores[33],
        'feature_34_quality': quality_scores[34],
        'feature_35_quality': quality_scores[35],
        'feature_36_quality': quality_scores[36],

        # === SECTION 4: Per-Feature Source (37 columns) ===
        'feature_0_source': feature_sources[0],
        'feature_1_source': feature_sources[1],
        'feature_2_source': feature_sources[2],
        # ... all 37 features
        'feature_32_source': feature_sources[32],
        'feature_33_source': feature_sources[33],
        'feature_34_source': feature_sources[34],
        'feature_35_source': feature_sources[35],
        'feature_36_source': feature_sources[36],

        # === SECTION 5: Per-Feature Details (6 JSON strings) ===
        'feature_fallback_reasons_json': json.dumps({k:v for k,v in fallback_reasons.items() if v}),  # Sparse
        'feature_sample_sizes_json': json.dumps({k:v for k,v in sample_sizes.items() if v is not None}),
        'feature_expected_values_json': json.dumps(expected_values),
        'feature_value_ranges_valid_json': json.dumps(calculate_value_ranges_valid(feature_values)),
        'feature_upstream_tables_json': json.dumps(extract_upstream_tables(feature_metadata)),
        'feature_last_updated_json': json.dumps(extract_last_updated(feature_metadata)),

        # === SECTION 6: Model Compatibility (4 fields) ===
        'feature_schema_version': 'v2_37features',
        'available_feature_names': list(FEATURE_NAMES),  # All 37 names
        'breakout_model_compatible': determine_breakout_compatibility(quality_scores),
        'breakout_v3_features_available': False,  # Update when V3 implemented

        # === SECTION 7: Traceability (6 fields) ===
        'upstream_processors_ran': 'PlayerCompositeFactorsProcessor,MLFeatureStoreProcessor',
        'missing_processors': detect_missing_processors(),
        'feature_store_age_hours': calculate_age_hours(),
        'upstream_data_freshness_hours': calculate_freshness_hours(feature_metadata),
        'quality_computed_at': datetime.utcnow(),
        'quality_schema_version': 'v2.1_hybrid',

        # === SECTION 8: Legacy (3 fields) ===
        'feature_sources': json.dumps(feature_sources),  # Keep for migration
        'primary_data_source': determine_primary_source(feature_sources),
        'matchup_data_status': 'MATCHUP_UNAVAILABLE' if matchup_quality < 50 else 'COMPLETE',
    }

    return record

# Usage - SIMPLE!
record = build_feature_quality_fields(feature_sources, feature_values, feature_metadata)
bq_client.insert_rows_json(table, [record])
```

---

## Migration Strategy

### Phase 1: Schema Update (Instant - Metadata Only)

```bash
# Add all 122 fields to table
bq update --schema schemas/bigquery/predictions/ml_feature_store_v2_hybrid.json \
  nba_predictions.ml_feature_store_v2

# This is instant - just metadata update
```

### Phase 2: Deploy Code (Dual-Write)

```python
# Write BOTH old and new fields during migration
record = {
    # NEW fields (122 total)
    'feature_5_quality': 40.0,
    'feature_5_source': 'default',
    'matchup_quality_pct': 0.0,
    # ... all new fields

    # OLD fields (keep for 3 months)
    'feature_sources': json.dumps({...}),
    'primary_data_source': 'mixed',
    'matchup_data_status': 'MATCHUP_UNAVAILABLE'
}
```

### Phase 3: Backfill (90 days)

```bash
# Backfill 90 days in batches
python bin/backfill/backfill_hybrid_quality.py \
  --start-date 2025-11-01 \
  --end-date 2026-02-05 \
  --batch-size 5
```

### Phase 4: Update Consumers (3 months)

Update all queries to use new fields:
- Replace `feature_sources` parsing with `feature_N_source` columns
- Replace aggregate checks with category fields
- Update training filters to use new gates

### Phase 5: Drop Legacy (After 3 months)

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
DROP COLUMN feature_sources,
DROP COLUMN primary_data_source,
DROP COLUMN matchup_data_status;
```

---

## Success Criteria

### Detection Speed
- [ ] Session 132-style issues detected in <5 seconds
- [ ] Per-feature quality queries run without JSON parsing (direct columns)
- [ ] Category filtering works with simple WHERE clauses

### Ease of Use
- [ ] Python code simple (no STRUCT nesting)
- [ ] SQL queries simple (no complex UNNEST)
- [ ] Other chats/agents can understand schema immediately

### Training Quality
- [ ] Can filter to high-quality features with direct column checks
- [ ] Training quality gates work correctly
- [ ] Critical features validated before training

### Debugging
- [ ] Can identify bad features in <10 seconds
- [ ] Can drill down to root cause with minimal JSON parsing
- [ ] Full traceability to upstream sources

### Backfill
- [ ] 90 days backfilled successfully
- [ ] Historical trend queries work
- [ ] Storage cost within $0.10/year

---

## Next Steps for Implementation

1. **Review this document** - Get final approval from another chat
2. **Create schema file** - `schemas/bigquery/predictions/ml_feature_store_v2_hybrid.json`
3. **Update quality_scorer.py** - Implement quality calculation for all 37 features
4. **Update ml_feature_store_processor.py** - Build hybrid record structure
5. **Test with Feb 6 data** - Verify Session 132 detection works
6. **Deploy Phase 4 processors** - `./bin/deploy-service.sh nba-phase4-precompute-processors`
7. **Backfill 90 days** - Run backfill script
8. **Monitor for 1 week** - Verify no issues

---

**Document Version:** 1.0 (FINAL)
**Last Updated:** February 5, 2026 (Session 133)
**Schema Type:** Hybrid (74 per-feature columns + JSON details + aggregates)
**Total Fields:** 122 fields
**Storage Cost:** $0.07/year
**Status:** ✅ READY FOR FINAL REVIEW
**Next:** Have another chat review and approve
