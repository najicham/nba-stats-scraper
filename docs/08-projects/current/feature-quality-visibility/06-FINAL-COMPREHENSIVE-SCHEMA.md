# Final Comprehensive Schema - ML Feature Store V2 Quality Tracking

**Date:** February 5, 2026 (Session 133)
**Status:** ✅ FINAL - Opus Validated with Enhancements
**Versions:** Opus reviewed and enhanced the per-feature design
**Priority:** Critical - "I really really need the ML Features to be top quality"

---

## Executive Summary

This document defines the **complete, final schema** for ML feature store quality tracking, incorporating:
1. Original quality visibility design (Session 132 analysis)
2. Breakout classifier integration (Session 133)
3. Per-feature quality tracking (user requirement)
4. **Opus enhancements (comprehensive review)**

**Total new fields:** 40+ fields for complete ML feature quality visibility

---

## Schema Structure Overview

### Three Levels of Granularity

```
┌─────────────────────────────────────────────────────────────┐
│ LEVEL 1: Per-Feature Detail (ARRAY<STRUCT>)                │
│ • 33 features × 16-20 fields each = complete visibility    │
│ • Source, quality, confidence, validation per feature      │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ LEVEL 2: Category Aggregates (Flat Fields)                 │
│ • 4 categories: matchup, history, team, vegas              │
│ • Fast filtering without UNNEST                            │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ LEVEL 3: Record-Level Aggregates (Flat Fields)             │
│ • Single quality score, tier, alert level                  │
│ • Model compatibility, training readiness                  │
└─────────────────────────────────────────────────────────────┘
```

---

## LEVEL 1: Per-Feature Quality Detail

### Complete STRUCT Definition (Opus Enhanced)

```sql
feature_quality_detail ARRAY<STRUCT<
  -- CORE IDENTIFICATION
  feature_index INT64 OPTIONS(
    description="Feature index 0-32 in feature_store_values array"
  ),

  feature_name STRING OPTIONS(
    description="Human-readable feature name: 'points_avg_last_5', 'fatigue_score', etc."
  ),

  feature_category STRING OPTIONS(
    description="Category: 'matchup', 'player_history', 'team_context', 'vegas'. Enables direct category filtering. (Opus P2)"
  ),

  -- FEATURE VALUE & VALIDATION
  feature_value FLOAT64 OPTIONS(
    description="Actual feature value used in model"
  ),

  expected_value FLOAT64 OPTIONS(
    description="Expected/default value. Use to detect drift: if feature_value == expected_value for non-default source, indicates silent calculation failure. (Opus P1)"
  ),

  original_value FLOAT64 OPTIONS(
    description="Original value before validation clamping (if any). NULL if no clamping. (Opus P3)"
  ),

  value_range_valid BOOL OPTIONS(
    description="TRUE if feature_value within expected range. Detects calculation errors (negative percentages, >100% rates, etc.). (Opus P2)"
  ),

  validation_status STRING OPTIONS(
    description="Validation result: 'valid', 'clamped', 'defaulted', 'warning'. Tracks what validation did. (Opus P2)"
  ),

  -- SOURCE TRACKING
  source_type STRING OPTIONS(
    description="'phase4' (precompute), 'phase3' (analytics), 'calculated' (on-the-fly), 'default' (fallback)"
  ),

  upstream_table STRING OPTIONS(
    description="Source BigQuery table: 'player_daily_cache', 'player_composite_factors', etc."
  ),

  upstream_data_hash STRING OPTIONS(
    description="Hash from upstream source record (e.g., player_daily_cache.data_hash). Enables exact tracing to source record. (Opus P1)"
  ),

  last_updated TIMESTAMP OPTIONS(
    description="When source data was last updated. For freshness detection."
  ),

  -- QUALITY SCORING
  quality_score FLOAT64 OPTIONS(
    description="0-100 quality score for THIS specific feature. phase4=100, phase3=87, calculated=100, default=40, with freshness/sample penalties."
  ),

  feature_quality_tier STRING OPTIONS(
    description="Feature tier: 'gold' (phase4, fresh, valid), 'silver' (phase3/slightly stale), 'bronze' (calculated), 'poor' (default/stale). Matches Phase 3 pattern. (Opus P1)"
  ),

  confidence_pct FLOAT64 OPTIONS(
    description="Confidence in this feature value (0-100). Based on quality_score, sample_size, and source reliability."
  ),

  -- DEFAULT/FALLBACK TRACKING
  is_default BOOL OPTIONS(
    description="TRUE if using default/fallback value due to missing data"
  ),

  fallback_reason STRING OPTIONS(
    description="Why fallback used: 'composite_factors_missing', 'thin_sample', 'stale_data', 'calculation_failed', etc."
  ),

  -- SAMPLE TRACKING
  sample_size INT64 OPTIONS(
    description="Sample size for rolling-window features (e.g., 10 for last_10 averages, 5 for last_5). NULL if not applicable. (Opus P1)"
  ),

  contributing_game_ids ARRAY<STRING> OPTIONS(
    description="For rolling-window features: game_ids used in calculation. Enables cascade impact analysis. (Opus P3)"
  ),

  -- TRAINING QUALITY
  is_training_quality BOOL OPTIONS(
    description="TRUE if meets training bar: quality_score >= 85, source_type != 'default', sample_size >= 5 (if applicable), value_range_valid = TRUE. (Opus P1)"
  ),

  -- ALERTING
  triggered_alert STRING OPTIONS(
    description="Alert this feature triggered (if any): 'stale_data_48h', 'thin_sample', 'range_violation', 'default_used'. NULL if no alert. (Opus P2)"
  ),

  -- VERSIONING
  feature_definition_version STRING OPTIONS(
    description="Version of feature definition: 'v1' (original), 'v2' (Session 133). Tracks when feature calculation changed. (Opus P2)"
  ),

  -- PERFORMANCE PROFILING
  computation_duration_ms INT64 OPTIONS(
    description="Milliseconds to compute this feature. For profiling/optimization. (Opus P3)"
  )

>> OPTIONS(
  description="Per-feature quality detail. 33 structs, one per feature. Complete visibility into source, quality, validation, and metadata for each feature."
)
```

**Total per-feature fields:** 20 fields per feature × 33 features

---

## LEVEL 2: Category-Level Aggregates

### Category Quality Scores (Fast Filtering)

```sql
-- Category-level quality percentages
matchup_quality_pct FLOAT64 OPTIONS(
  description="Quality % for matchup features (5-8: composite, 13-14: opponent defense). 0=all defaults, 100=all high quality."
),

player_history_quality_pct FLOAT64 OPTIONS(
  description="Quality % for player history features (0-4, 29-32). Typically 90-100% (good Phase 3 coverage)."
),

team_context_quality_pct FLOAT64 OPTIONS(
  description="Quality % for team context features (22-24). Usually 95-100% (Phase 3 team stats reliable)."
),

vegas_quality_pct FLOAT64 OPTIONS(
  description="Quality % for vegas features (25-28). Expected 40-60% (not all players have lines - normal)."
),

-- Category-level flags
has_composite_factors BOOL OPTIONS(
  description="TRUE if composite factors (5-8) available from Phase 4. Session 132: All FALSE caused issue."
),

has_opponent_defense BOOL OPTIONS(
  description="TRUE if opponent defense (13-14) available. Required for matchup quality."
),

has_vegas_line BOOL OPTIONS(
  description="TRUE if vegas line available. FALSE is normal for low-volume props."
),

-- Source distribution by category
matchup_default_count INT64 OPTIONS(
  description="Count of matchup features (5-8, 13-14) using defaults. Session 132: 6/6 defaulted."
),

player_history_default_count INT64,
team_context_default_count INT64,
vegas_default_count INT64
```

---

## LEVEL 3: Record-Level Aggregates

### Overall Quality & Alerting

```sql
-- Aggregate quality
feature_quality_score FLOAT64 OPTIONS(
  description="Aggregate 0-100 quality (weighted average of per-feature quality_scores). Use for fast filtering. KEEP for backward compatibility."
),

quality_tier STRING OPTIONS(
  description="Record-level tier: 'gold' (>95), 'silver' (85-95), 'bronze' (70-85), 'poor' (50-70), 'critical' (<50). Lowercase to match Phase 3."
),

quality_alert_level STRING OPTIONS(
  description="Alert priority: 'green' (healthy), 'yellow' (degraded), 'red' (critical). For real-time monitoring."
),

quality_alerts ARRAY<STRING> OPTIONS(
  description="Specific alerts: ['all_matchup_features_defaulted', 'high_default_rate_20pct', 'critical_features_missing']. Matches Phase 3 quality_issues pattern."
),

-- Source distribution (aggregate)
default_feature_count INT64 OPTIONS(
  description="Total features using defaults. High count = data unavailability. Session 132: 4 defaults (all matchup)."
),

phase4_feature_count INT64,
phase3_feature_count INT64,
calculated_feature_count INT64
```

### Training Data Quality (Opus Enhanced)

```sql
-- Training readiness (record-level)
is_training_ready BOOL OPTIONS(
  description="TRUE if quality sufficient for ML training (stricter than production). Requires: quality_tier in ('gold','silver'), matchup >= 70, history >= 80, no critical features missing."
),

training_quality_feature_count INT64 OPTIONS(
  description="Count of features with is_training_quality = TRUE. Use for filtering: WHERE training_quality_feature_count >= 30. (Opus P1)"
),

critical_features_training_quality BOOL OPTIONS(
  description="TRUE if ALL critical features (matchup 5-8, defense 13-14) meet training bar. Strict gate for ML training. (Opus P1)"
),

critical_feature_count INT64 OPTIONS(
  description="Count of CRITICAL features present (high quality). Missing critical = low model confidence."
),

optional_feature_count INT64 OPTIONS(
  description="Count of optional features present. Missing optional = acceptable."
)
```

### Model Compatibility (Breakout Integration)

```sql
feature_schema_version STRING OPTIONS(
  description="Feature schema version: 'v2_33features', 'v3_37features'. Validates model/data compatibility. Prevents Session 133 mismatch. (Opus P0)"
),

available_feature_names ARRAY<STRING> OPTIONS(
  description="List of feature names in this record. Runtime validation before prediction. (Opus P0)"
),

breakout_model_compatible ARRAY<STRING> OPTIONS(
  description="Which breakout models this data supports: ['v2_14features', 'v3_13features']. Prevents train/eval mismatch."
),

breakout_v3_features_available BOOL OPTIONS(
  description="TRUE if V3 breakout features (star_teammate_out, fg_pct_last_game) populated. Required for V3 predictions."
),

feature_quality_detail_version STRING OPTIONS(
  description="Version of feature_quality_detail schema: 'v1' (Session 133), 'v2' (with Opus enhancements). (Opus migration rec)"
)
```

### Production Readiness

```sql
is_production_ready BOOL OPTIONS(
  description="TRUE if safe for production predictions: quality_tier in ('gold','silver','bronze'), score >= 85, matchup >= 50."
)
```

### Traceability & Debugging (Opus Enhanced)

```sql
upstream_pipeline_run_id STRING OPTIONS(
  description="Correlation ID from Phase 4 orchestrator. Links to nba_orchestration.pipeline_runs for full pipeline debugging. (Opus P3)"
),

predecessor_processors_completed ARRAY<STRING> OPTIONS(
  description="Phase 4 processors completed before this record: ['PlayerCompositeFactorsProcessor', 'MLFeatureStoreProcessor']. (Opus P3)"
),

upstream_processors_ran STRING OPTIONS(
  description="Comma-separated processors that ran. Session 132 debug: Missing 'PlayerCompositeFactorsProcessor'."
),

missing_processors STRING OPTIONS(
  description="Expected processors that DID NOT run. Session 132: 'PlayerCompositeFactorsProcessor' missing caused all matchup defaults."
)
```

### Freshness Tracking (Breakout Integration)

```sql
feature_store_age_hours FLOAT64 OPTIONS(
  description="Hours since feature store computed. Training filter: exclude > 48h."
),

upstream_data_freshness_hours FLOAT64 OPTIONS(
  description="Hours since upstream data (Phase 3/4) updated. Detect stale dependencies."
)
```

### Audit Trail

```sql
quality_computed_at TIMESTAMP OPTIONS(
  description="When quality fields computed. Detect stale data."
),

quality_schema_version STRING OPTIONS(
  description="Quality schema version (e.g., 'v2.1_opus_enhanced'). For handling quality field evolution."
)
```

### Legacy Fields (Keep During Migration)

```sql
-- DEPRECATED - Keep for backward compatibility
feature_sources STRING OPTIONS(
  description="DEPRECATED: Legacy JSON mapping. Use feature_quality_detail instead. Kept for 3-month migration period."
),

primary_data_source STRING OPTIONS(
  description="DEPRECATED: Use feature_schema_version instead. Kept for backward compatibility."
),

matchup_data_status STRING OPTIONS(
  description="DEPRECATED: Use matchup_quality_pct and has_composite_factors instead. Kept for backward compatibility."
)
```

---

## Complete Field Count Summary

| Level | Category | Field Count |
|-------|----------|-------------|
| **Per-Feature STRUCT** | Core identification | 3 |
| | Value & validation | 5 |
| | Source tracking | 4 |
| | Quality scoring | 3 |
| | Default/fallback | 2 |
| | Sample tracking | 2 |
| | Training quality | 1 |
| | Alerting | 1 |
| | Versioning | 1 |
| | Performance | 1 |
| | **Subtotal per feature** | **23 fields** |
| | **× 33 features** | **759 data points** |
| **Category Aggregates** | Quality %ages | 4 |
| | Flags | 3 |
| | Default counts | 4 |
| | **Subtotal** | **11 fields** |
| **Record Aggregates** | Overall quality | 5 |
| | Training quality | 5 |
| | Model compatibility | 5 |
| | Production readiness | 1 |
| | Traceability | 4 |
| | Freshness | 2 |
| | Audit trail | 2 |
| | Legacy (deprecated) | 3 |
| | **Subtotal** | **27 fields** |
| **TOTAL** | **Record-level fields** | **38 fields** |
| | **+ Per-feature STRUCT** | **23 fields × 33** |
| | **Grand Total** | **797 data points/record** |

---

## Storage Impact (Opus Validated)

### Per-Record Storage

**Per-feature STRUCT (23 fields):**
```
feature_index (INT64):              8 bytes
feature_name (STRING):             20 bytes
feature_category (STRING):         15 bytes
feature_value (FLOAT64):            8 bytes
expected_value (FLOAT64):           8 bytes
original_value (FLOAT64):           8 bytes (nullable)
value_range_valid (BOOL):           1 byte
validation_status (STRING):        10 bytes
source_type (STRING):              10 bytes
upstream_table (STRING):           25 bytes
upstream_data_hash (STRING):       16 bytes
last_updated (TIMESTAMP):           8 bytes
quality_score (FLOAT64):            8 bytes
feature_quality_tier (STRING):     10 bytes
confidence_pct (FLOAT64):           8 bytes
is_default (BOOL):                  1 byte
fallback_reason (STRING):          15 bytes (nullable)
sample_size (INT64):                8 bytes (nullable)
contributing_game_ids (ARRAY):     20 bytes (avg, nullable)
is_training_quality (BOOL):         1 byte
triggered_alert (STRING):          15 bytes (nullable)
feature_definition_version (STR):  10 bytes
computation_duration_ms (INT64):    8 bytes (nullable)
------------------------------------------------
Total per feature:                ~241 bytes
```

**33 features:** 33 × 241 bytes = **7,953 bytes (~8 KB)**

**Record-level fields:** ~500 bytes

**Total per record:** ~8.5 KB

### Annual Storage & Cost

```
200 players/day × 8.5 KB = 1.7 MB/day
1.7 MB × 365 days = 620 MB/year

BigQuery cost: 620 MB × $0.02/GB/month = $0.0124/month = $0.15/year
```

### Comparison

| Version | Storage/Record | Annual Storage | Annual Cost |
|---------|----------------|----------------|-------------|
| Original (JSON only) | 1.2 KB | 88 MB | $0.02 |
| Category quality only | 1.4 KB | 102 MB | $0.02 |
| Per-feature (basic) | 4.8 KB | 351 MB | $0.08 |
| **Per-feature (Opus enhanced)** | **8.5 KB** | **620 MB** | **$0.15** |

**Cost increase:** $0.13/year vs original

**User decision:** "I don't mind having extra fields" ✅

**Opus assessment:** Worth it for complete ML quality visibility ✅

---

## Implementation Priority (Opus Recommendations)

### Phase 1: Core Per-Feature (Immediate - Session 133)

**Duration:** 10-12 hours

**Fields to implement:**
```sql
-- Per-feature STRUCT (10 core fields)
feature_index, feature_name, feature_value, source_type,
quality_score, confidence_pct, is_default, fallback_reason,
upstream_table, last_updated

-- Record-level (15 fields)
feature_quality_score, quality_tier, quality_alert_level, quality_alerts,
matchup_quality_pct, player_history_quality_pct, team_context_quality_pct, vegas_quality_pct,
has_composite_factors, has_opponent_defense, has_vegas_line,
default_feature_count, phase4_feature_count, phase3_feature_count, calculated_feature_count
```

**Outcome:** Session 132 detection (<10 sec), basic per-feature visibility

---

### Phase 2: Enhanced Per-Feature (Follow-up - Session 134)

**Duration:** 4-6 hours

**Add to per-feature STRUCT:**
- `sample_size` (Opus P1)
- `expected_value` (Opus P1)
- `feature_category` (Opus P2)
- `feature_quality_tier` (Opus P1)
- `is_training_quality` (Opus P1)
- `value_range_valid` (Opus P2)

**Add to record-level:**
- `training_quality_feature_count` (Opus P1)
- `critical_features_training_quality` (Opus P1)
- `feature_schema_version` (Opus P0)
- `available_feature_names` (Opus P0)

**Outcome:** Training data quality filtering, better validation

---

### Phase 3: Advanced Tracing (Future - Session 135+)

**Duration:** 3-4 hours

**Add to per-feature STRUCT:**
- `upstream_data_hash` (Opus P1)
- `triggered_alert` (Opus P2)
- `validation_status` (Opus P2)
- `feature_definition_version` (Opus P2)

**Add to record-level:**
- `upstream_pipeline_run_id` (Opus P3)
- `predecessor_processors_completed` (Opus P3)

**Outcome:** Complete traceability, pipeline debugging

---

### Phase 4: Performance & Profiling (Optional - Future)

**Duration:** 2-3 hours

**Add to per-feature STRUCT:**
- `original_value` (Opus P3)
- `computation_duration_ms` (Opus P3)
- `contributing_game_ids` (Opus P3)

**Outcome:** Performance optimization insights

---

## Migration Strategy (Opus Recommendations)

### Step 1: Add Schema (Instant - Metadata Only)

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS feature_quality_detail ARRAY<STRUCT<...>>,
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS matchup_quality_pct FLOAT64,
-- ... all new fields
;

-- Keep legacy fields (user requirement: "give some time to transition")
-- Do NOT drop: feature_sources, primary_data_source, matchup_data_status
```

### Step 2: Deploy Code with Dual-Write

```python
# In ml_feature_store_processor.py
def _build_feature_store_record(self, ...):
    # NEW: Build per-feature detail
    feature_quality_detail = self.quality_scorer.build_feature_quality_detail(...)

    record = {
        # NEW fields
        'feature_quality_detail': feature_quality_detail,
        'quality_tier': quality_tier,
        # ...

        # LEGACY fields (keep writing for backward compat)
        'feature_sources': json.dumps(feature_sources),
        'primary_data_source': primary_data_source,
        'matchup_data_status': matchup_data_status,
    }
```

### Step 3: Backfill in Phases

```bash
# Phase A: Last 7 days (test)
python bin/backfill/backfill_feature_quality.py --start 2026-01-29 --end 2026-02-05

# Phase B: Last 30 days
python bin/backfill/backfill_feature_quality.py --start 2026-01-06 --end 2026-02-05

# Phase C: Full season (90 days)
python bin/backfill/backfill_feature_quality.py --start 2025-11-01 --end 2026-02-05
```

### Step 4: Update Consumers (3-month grace period)

**Month 1:** Dual-write both old and new fields
**Month 2:** Update all consumers to use new fields
**Month 3:** Verify no consumers using old fields

### Step 5: Drop Legacy Fields (After 3 months)

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
DROP COLUMN feature_sources,
DROP COLUMN primary_data_source,
DROP COLUMN matchup_data_status;
```

---

## Success Criteria

### Detection Speed
- [ ] Session 132-style issues detected in <10 seconds (vs 2+ hours)
- [ ] Per-feature quality query runs in <5 seconds
- [ ] Category-level filtering works without UNNEST

### Training Quality
- [ ] Can filter to only high-quality features per-feature
- [ ] `training_quality_feature_count` enables fast filtering
- [ ] Critical features training gate works correctly

### Debugging
- [ ] Can trace feature value to exact upstream source record
- [ ] Can identify which processor produced each feature
- [ ] Can detect validation actions (clamping, defaulting)

### Model Compatibility
- [ ] Worker detects incompatible models before prediction
- [ ] Feature schema versioning prevents train/eval mismatch
- [ ] Breakout classifier blocker cannot recur

### Backfill
- [ ] 90 days backfilled with per-feature detail
- [ ] Historical trend queries work correctly
- [ ] Storage cost within $0.20/year

---

## Documentation Generated

This comprehensive schema design is documented across:

1. `00-PROJECT-OVERVIEW.md` - Project goals and high-level approach
2. `01-SCHEMA-DESIGN.md` - Original flat fields design (Opus validated)
3. `02-SCHEMA-ANALYSIS-AND-RECOMMENDATION.md` - Analysis of existing patterns
4. `03-OPUS-VALIDATION-AND-FINAL-SCHEMA.md` - First Opus review (quality fields)
5. `04-BREAKOUT-INTEGRATION.md` - Breakout classifier integration
6. `05-PER-FEATURE-QUALITY-TRACKING.md` - Per-feature design (user requirement)
7. **`06-FINAL-COMPREHENSIVE-SCHEMA.md` (THIS FILE)** - Complete integrated design with Opus enhancements

---

**Document Version:** 1.0 (Final)
**Last Updated:** February 5, 2026 (Session 133)
**Reviewers:** Opus 4.5 (comprehensive review)
**Status:** ✅ APPROVED FOR IMPLEMENTATION
**Storage Cost:** $0.15/year (acceptable)
**Implementation Time:** 10-12 hours (Phase 1), 20-25 hours (all phases)
**User Priority:** "I really really need the ML Features to be top quality" ✅
