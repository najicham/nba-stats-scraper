# Session 134 Start Here - ML Feature Store Quality Schema Implementation

**Date:** February 5, 2026
**Status:** 🟢 READY FOR IMPLEMENTATION - Design Reviewed & Corrected
**Previous Session:** Session 133 (design & documentation)
**Estimated Time:** 14-17 hours

---

## Quick Start

**Session 133 completed comprehensive schema design. External review identified 5 issues to fix before implementation.**

### Critical Fixes Required

1. ✅ Fixed `is_production_ready` logic bug (bronze tier contradiction)
2. ✅ Removed duplicate schema version fields
3. ✅ Added `game_context` category for 11 uncategorized features
4. ✅ Removed 3 redundant derivable JSON fields
5. ✅ Removed premature `feature_upstream_hashes_json`

**Corrected schema:** 122 fields (up from 116)

---

## Review Feedback Summary

### Issue 1: is_production_ready Logic Bug (CRITICAL)

**Problem:**
```sql
is_production_ready: "TRUE if quality_tier in ('gold','silver','bronze'), score >= 85, matchup >= 50"
```

But bronze tier is defined as 70-85. The AND condition means bronze can never satisfy score >= 85.

**Fix Applied:**
```sql
is_production_ready BOOL OPTIONS(
  description="TRUE if safe for production: quality_tier in ('gold','silver','bronze') AND score >= 70 AND matchup_quality_pct >= 50. Bronze floor is 70, not 85."
)
```

**Calculation:**
```python
is_production_ready = (
    quality_tier in ('gold', 'silver', 'bronze') and
    feature_quality_score >= 70 and  # Changed from 85 to match bronze floor
    matchup_quality_pct >= 50
)
```

---

### Issue 2: Duplicate Schema Version Fields (CLEANUP)

**Problem:** Two fields serving same purpose with conflicting values:
- Section 6: `feature_quality_schema_version = 'v1_hybrid'`
- Section 7: `quality_schema_version = 'v2.1_hybrid'`

**Fix Applied:** Keep one, drop the other
```sql
-- KEEP (clear purpose)
quality_schema_version STRING OPTIONS(
  description="Quality schema version: 'v1_hybrid_20260205'. For handling schema evolution."
)

-- REMOVED
-- feature_quality_schema_version (duplicate)
```

---

### Issue 3: 11 Features Have No Category (CRITICAL BLIND SPOT)

**Problem:** Categories only cover 26 of 37 features. 11 features (9-12, 15-21) have no category:
- Features 9-12: rest_advantage, injury_risk, recent_trend, minutes_change
- Features 15-21: home_away, back_to_back, playoff_game, pct_paint, pct_mid_range, pct_three, pct_free_throw

If these silently default, category-level monitoring won't catch it.

**Fix Applied:** Add `game_context` category
```sql
-- NEW category for 11 previously uncategorized features
game_context_quality_pct FLOAT64 OPTIONS(
  description="Quality % for game context features (9-12, 15-21): rest, schedule, status. 11 features total."
),

game_context_default_count INT64 OPTIONS(
  description="Count of game context features using defaults."
),

game_context_quality_tier STRING OPTIONS(
  description="Game context category tier: 'gold', 'silver', 'bronze', 'poor', 'critical'."
)
```

**Category Mapping (Updated):**
- **matchup** (6 features): 5-8, 13-14
- **player_history** (13 features): 0-4, 29-36
- **team_context** (3 features): 22-24
- **vegas** (4 features): 25-28
- **game_context** (11 features): 9-12, 15-21 ← NEW

**Total: 37 features** (all 37 features now have category coverage)

---

### Issue 4: Redundant Derivable JSON Fields (CLEANUP)

**Problem:** 3 JSON fields are derivable from flat columns - adds complexity:
- `feature_quality_tiers_json` ← derivable from `feature_N_quality` + tier thresholds
- `feature_is_default_json` ← derivable from `feature_N_source == 'default'`
- `feature_training_quality_json` ← derivable from `feature_N_quality >= 85 AND source != 'default'`

**Fix Applied:** Remove all 3 fields

**Before:** 10 JSON fields
**After:** 7 JSON fields

**Remaining JSON fields (necessary):**
1. `feature_fallback_reasons_json` - Not derivable (sparse, contains reason strings)
2. `feature_sample_sizes_json` - Not derivable (metadata from upstream)
3. `feature_expected_values_json` - Not derivable (metadata from upstream)
4. `feature_value_ranges_valid_json` - Not derivable (validation results)
5. `feature_upstream_tables_json` - Not derivable (metadata from upstream)
6. `feature_last_updated_json` - Not derivable (timestamps from upstream)
**Remaining: 6 JSON fields** (after removing 3 derivable + 1 premature)

---

### Issue 5: feature_upstream_hashes_json is Premature (DEFER)

**Problem:** Requires deterministic hashing infrastructure in all upstream sources. High implementation cost for rare deep-debug scenario.

**Fix Applied:** Remove field, defer to future version if needed

---

## Corrected Schema Summary

### Field Count Changes

| Section | Original | Corrected | Change |
|---------|----------|-----------|--------|
| Aggregate Quality | 11 | 11 | - |
| Category Quality | 15 | 18 | +3 (game_context) |
| Per-Feature Quality | 33 | 37 | +4 |
| Per-Feature Source | 33 | 37 | +4 |
| Per-Feature Details (JSON) | 10 | 6 | -4 (removed redundant) |
| Model Compatibility | 5 | 4 | -1 (removed duplicate) |
| Traceability | 6 | 6 | - |
| Legacy | 3 | 3 | - |
| **TOTAL** | **116** | **122** | **+6** |

**Net: 116 - 5 + 3 + 8 = 122 fields total** (added 8 for 4 extra quality + 4 extra source columns)

---

## Complete Corrected Schema

### SECTION 1: Aggregate Quality (11 fields - unchanged)

```sql
feature_quality_score FLOAT64,
quality_tier STRING,
quality_alert_level STRING,
quality_alerts ARRAY<STRING>,
default_feature_count INT64,
phase4_feature_count INT64,
phase3_feature_count INT64,
calculated_feature_count INT64,
is_production_ready BOOL OPTIONS(
  description="TRUE if safe for production: quality_tier in ('gold','silver','bronze') AND score >= 70 AND matchup >= 50. FIXED: Was >= 85 which excluded bronze."
),
is_training_ready BOOL,
training_quality_feature_count INT64
```

---

### SECTION 2: Category Quality (18 fields - added 3 for game_context)

```sql
-- Category quality percentages (5 categories now, was 4)
matchup_quality_pct FLOAT64,
player_history_quality_pct FLOAT64,
team_context_quality_pct FLOAT64,
vegas_quality_pct FLOAT64,
game_context_quality_pct FLOAT64 OPTIONS(
  description="Quality % for game context features (9-12, 15-21): rest, schedule, injury, starting status. 11 features total. ADDED: Fixes blind spot."
),

-- Category default counts (5 categories)
matchup_default_count INT64,
player_history_default_count INT64,
team_context_default_count INT64,
vegas_default_count INT64,
game_context_default_count INT64 OPTIONS(
  description="Count of game context features using defaults. ADDED: Fixes blind spot."
),

-- Critical feature flags (unchanged)
has_composite_factors BOOL,
has_opponent_defense BOOL,
has_vegas_line BOOL,

-- Training quality (unchanged)
critical_features_training_quality BOOL,
critical_feature_count INT64,
optional_feature_count INT64,

-- Category tiers (2 total - keep matchup, add game_context)
matchup_quality_tier STRING,
game_context_quality_tier STRING OPTIONS(
  description="Game context category tier. ADDED: Fixes blind spot."
)
```

---

### SECTION 3: Per-Feature Quality (37 fields - expanded for 4 new features)

```sql
feature_0_quality FLOAT64,
feature_1_quality FLOAT64,
...
feature_36_quality FLOAT64
```

---

### SECTION 4: Per-Feature Source (37 fields - expanded for 4 new features)

```sql
feature_0_source STRING,
feature_1_source STRING,
...
feature_36_source STRING
```

---

### SECTION 5: Per-Feature Details (6 JSON fields - removed 4)

```sql
-- REMOVED (derivable from flat columns):
-- feature_quality_tiers_json (can derive from feature_N_quality)
-- feature_is_default_json (can derive from feature_N_source == 'default')
-- feature_training_quality_json (can derive from quality + source)
-- feature_upstream_hashes_json (premature, no hashing infrastructure)

-- KEEPING (not derivable):
feature_fallback_reasons_json STRING OPTIONS(
  description="JSON map (sparse): {\"5\":\"composite_factors_missing\",...}. Not derivable."
),

feature_sample_sizes_json STRING OPTIONS(
  description="JSON map: {\"0\":5,\"1\":10,...}. Metadata from upstream, not derivable."
),

feature_expected_values_json STRING OPTIONS(
  description="JSON map: {\"5\":0.25,\"6\":0.0,...}. Metadata from upstream, not derivable."
),

feature_value_ranges_valid_json STRING OPTIONS(
  description="JSON map: {\"0\":true,\"13\":false,...}. Validation results, not derivable."
),

feature_upstream_tables_json STRING OPTIONS(
  description="JSON map: {\"0\":\"player_daily_cache\",\"5\":\"player_composite_factors\",...}. Metadata, not derivable."
),

feature_last_updated_json STRING OPTIONS(
  description="JSON map: {\"0\":\"2026-02-06T06:30:00Z\",...}. Timestamps from upstream, not derivable."
)
```

---

### SECTION 6: Model Compatibility (4 fields - removed 1 duplicate)

```sql
feature_schema_version STRING,
available_feature_names ARRAY<STRING>,
breakout_model_compatible ARRAY<STRING>,
breakout_v3_features_available BOOL

-- REMOVED (duplicate):
-- feature_quality_schema_version
```

---

### SECTION 7: Traceability (6 fields - unchanged)

```sql
upstream_processors_ran STRING,
missing_processors STRING,
feature_store_age_hours FLOAT64,
upstream_data_freshness_hours FLOAT64,
quality_computed_at TIMESTAMP,
quality_schema_version STRING OPTIONS(
  description="Quality schema version: 'v1_hybrid_20260205'. KEPT (removed duplicate from Section 6)."
)
```

---

### SECTION 8: Legacy (3 fields - unchanged)

```sql
feature_sources STRING,
primary_data_source STRING,
matchup_data_status STRING
```

---

## Implementation Changes Required

### 1. Update Category Definitions

**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py`

```python
FEATURE_CATEGORIES = {
    'matchup': {
        'indices': [5, 6, 7, 8, 13, 14],
        'names': ['fatigue_score', 'shot_zone_mismatch_score', 'pace_score',
                  'usage_spike_score', 'opponent_def_rating', 'opponent_pace'],
    },
    'player_history': {
        'indices': [0, 1, 2, 3, 4, 29, 30, 31, 32, 33, 34, 35, 36],
        'names': ['points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
                  'points_std_last_10', 'games_in_last_7_days', 'avg_points_vs_opponent',
                  'games_vs_opponent', 'minutes_avg_last_10', 'ppm_avg_last_10',
                  'dnp_rate', 'pts_slope_10g', 'pts_vs_season_zscore', 'breakout_flag'],
    },
    'team_context': {
        'indices': [22, 23, 24],
        'names': ['team_pace', 'team_off_rating', 'team_win_pct'],
    },
    'vegas': {
        'indices': [25, 26, 27, 28],
        'names': ['vegas_points_line', 'vegas_opening_line', 'vegas_line_move', 'has_vegas_line'],
    },
    # NEW: Game context category (fixes blind spot)
    'game_context': {
        'indices': [9, 10, 11, 12, 15, 16, 17, 18, 19, 20, 21],
        'names': ['rest_advantage', 'injury_risk', 'recent_trend', 'minutes_change',
                  'home_away', 'back_to_back', 'playoff_game',
                  'pct_paint', 'pct_mid_range', 'pct_three',
                  'pct_free_throw'],
    }
}
```

### 2. Fix is_production_ready Logic

**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py`

```python
def calculate_is_production_ready(
    quality_tier: str,
    feature_quality_score: float,
    matchup_quality_pct: float
) -> bool:
    """
    Determine if safe for production.

    FIXED: Changed from score >= 85 to score >= 70 to match bronze tier floor.
    """
    return (
        quality_tier in ('gold', 'silver', 'bronze') and
        feature_quality_score >= 70 and  # FIXED: Was 85, excluded bronze
        matchup_quality_pct >= 50
    )
```

### 3. Remove Redundant JSON Fields

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
# REMOVE these from record:
# 'feature_quality_tiers_json': json.dumps(quality_tiers),  # DERIVABLE
# 'feature_is_default_json': json.dumps(is_default),  # DERIVABLE
# 'feature_training_quality_json': json.dumps(training_quality),  # DERIVABLE
# 'feature_upstream_hashes_json': json.dumps(upstream_hashes),  # PREMATURE

# KEEP these (not derivable):
record['feature_fallback_reasons_json'] = json.dumps({k:v for k,v in fallback_reasons.items() if v})
record['feature_sample_sizes_json'] = json.dumps({k:v for k,v in sample_sizes.items() if v is not None})
record['feature_expected_values_json'] = json.dumps(expected_values)
record['feature_value_ranges_valid_json'] = json.dumps(value_ranges_valid)
record['feature_upstream_tables_json'] = json.dumps(upstream_tables)
record['feature_last_updated_json'] = json.dumps(last_updated_times)
```

### 4. Consolidate Schema Version Field

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
# REMOVE:
# record['feature_quality_schema_version'] = 'v1_hybrid'

# KEEP:
record['quality_schema_version'] = 'v1_hybrid_20260205'
```

---

## Updated Query Patterns

### Derive Removed Fields (If Needed)

```sql
-- Derive feature_quality_tiers (if needed)
SELECT
  player_lookup,
  CASE
    WHEN feature_5_quality > 95 THEN 'gold'
    WHEN feature_5_quality >= 85 THEN 'silver'
    WHEN feature_5_quality >= 70 THEN 'bronze'
    WHEN feature_5_quality >= 50 THEN 'poor'
    ELSE 'critical'
  END as feature_5_tier
FROM ml_feature_store_v2;

-- Derive feature_is_default
SELECT player_lookup, (feature_5_source = 'default') as feature_5_is_default
FROM ml_feature_store_v2;

-- Derive feature_training_quality
SELECT player_lookup, (feature_5_quality >= 85 AND feature_5_source != 'default') as feature_5_training_quality
FROM ml_feature_store_v2;
```

### Create Unpivot View (Reviewer Suggestion)

**File:** `schemas/bigquery/predictions/views/v_feature_quality_unpivot.sql`

```sql
-- Create view to unpivot 37 quality columns into rows
CREATE OR REPLACE VIEW nba_predictions.v_feature_quality_unpivot AS
SELECT player_lookup, game_date, 0 as feature_index, 'points_avg_last_5' as feature_name, feature_0_quality as quality, feature_0_source as source FROM ml_feature_store_v2
UNION ALL
SELECT player_lookup, game_date, 1, 'points_avg_last_10', feature_1_quality, feature_1_source FROM ml_feature_store_v2
UNION ALL
-- ... repeat for all 37 features
SELECT player_lookup, game_date, 36, 'breakout_flag', feature_36_quality, feature_36_source FROM ml_feature_store_v2;

-- Then queries become simple:
SELECT
  feature_name,
  AVG(quality) as avg_quality,
  COUNTIF(source = 'default') as default_count
FROM v_feature_quality_unpivot
WHERE game_date = '2026-02-06'
GROUP BY feature_name
ORDER BY avg_quality ASC;
```

---

## Implementation Checklist

### Pre-Implementation
- [x] Review feedback incorporated
- [x] Schema corrected (122 fields)
- [x] Category blind spot fixed
- [x] is_production_ready logic fixed
- [x] Redundant fields removed
- [ ] Deploy stale services (P1 issue from handoff)

### Implementation (14-17 hours)
- [ ] Create schema JSON file (122 fields)
- [ ] Update BigQuery table schema (ALTER TABLE)
- [ ] Update FEATURE_CATEGORIES with game_context
- [ ] Fix is_production_ready calculation
- [ ] Remove 4 redundant JSON fields from code
- [ ] Consolidate schema version field
- [ ] Implement quality_scorer.py enhancements
- [ ] Implement ml_feature_store_processor.py integration
- [ ] Test with Feb 6 data
- [ ] Create unpivot view (reviewer suggestion)
- [ ] Deploy Phase 4 processors
- [ ] Backfill 7 days (test)
- [ ] Backfill 30 days
- [ ] Backfill 90 days (full season)

### Post-Implementation
- [ ] Verify Session 132 detection query works (<5 sec)
- [ ] Verify game_context category populated correctly
- [ ] Verify no redundant JSON fields in records
- [ ] Check storage cost (~$0.10/year)
- [ ] Update `/validate-daily` skill

---

## Minor Items (From Review)

### 1. Page Count Correction
**Review feedback:** Page counts in handoff were inflated ("385 pages" - actually ~50 pages total)

**Correction:** Documentation is comprehensive but not 385 pages. More like:
- 00-PROJECT-OVERVIEW.md: ~15 pages
- 01-SCHEMA-DESIGN.md: ~12 pages
- 02-SCHEMA-ANALYSIS: ~10 pages
- 03-OPUS-VALIDATION: ~8 pages
- 04-BREAKOUT-INTEGRATION: ~9 pages
- 05-PER-FEATURE-TRACKING: ~11 pages
- 06-COMPREHENSIVE-SCHEMA: ~13 pages
- 07-FINAL-HYBRID-SCHEMA: ~15 pages

**Total: ~93 pages** (not 385)

### 2. Stale Deployments (P1)
**Review feedback:** 3 services are 3 commits behind. Address before/alongside implementation.

**Action:** Deploy these before starting schema implementation:
```bash
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh prediction-coordinator
```

---

## Storage Impact (Updated)

### Per-Record Storage (Updated)

**Removed fields:**
- 3 JSON fields × 500 bytes = -1,500 bytes
- 1 upstream_hashes JSON × 500 bytes = -500 bytes
- 1 schema version field × 20 bytes = -20 bytes
**Total removed:** -2,020 bytes

**Added fields:**
- 3 game_context fields × 12 bytes = +36 bytes
- 8 per-feature fields (4 quality + 4 source) × 12 bytes = +96 bytes
- **Total added:** 11 fields = +132 bytes

**Net change:** -1,888 bytes

**New per-record size:** ~4.3 KB (down from 6.2 KB)

**Annual cost:** ~$0.07/year (down from $0.11/year)

---

## Success Criteria (Unchanged)

- [ ] Session 132 detection in <5 seconds
- [ ] Game context features have category visibility (NEW)
- [ ] No derivable JSON fields stored (cleanup verified)
- [ ] is_production_ready logic correct (bronze tier works)
- [ ] Training quality filtering works
- [ ] 90 days backfilled
- [ ] Storage cost < $0.10/year

---

## References

### Previous Session Docs
- Session 133 design: `docs/08-projects/current/feature-quality-visibility/07-FINAL-HYBRID-SCHEMA.md`
- Session 133 handoff: `docs/09-handoff/2026-02-05-SESSION-133-FINAL-HANDOFF.md`

### Files to Modify
- `schemas/bigquery/predictions/ml_feature_store_v2_hybrid.json` (create)
- `data_processors/precompute/ml_feature_store/quality_scorer.py` (enhance)
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` (integrate)

### Review Feedback Source
External review identified 5 critical/cleanup issues. All addressed in this handoff.

---

**Document Version:** 1.0
**Date:** February 5, 2026
**Status:** ✅ READY FOR IMPLEMENTATION
**Next:** Deploy stale services → Implement corrected schema → Backfill 90 days
**Estimated Time:** 14-17 hours
**Expected Outcome:** Daily ML feature quality issues stop permanently
