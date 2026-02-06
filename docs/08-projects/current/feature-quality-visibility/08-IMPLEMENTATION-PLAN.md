# Feature Quality Visibility - Implementation Plan

**Date:** February 5, 2026 (Session 134)
**Status:** Ready for implementation
**Estimated effort:** 8-10 hours (code changes + testing + deploy)

---

## Pre-Implementation Audit Findings

### Finding 1: Source type mapping needed
The processor writes 9 source types but the quality schema expects 4.

**Mapping:**
```python
SOURCE_TYPE_CANONICAL = {
    'phase4': 'phase4',
    'phase3': 'phase3',
    'calculated': 'calculated',
    'default': 'default',
    'vegas': 'phase4',              # Vegas data sourced via Phase 4 pipeline
    'opponent_history': 'phase4',   # Opponent history from Phase 4
    'minutes_ppm': 'phase4',        # Minutes/PPM from Phase 4 daily cache
    'fallback': 'default',          # Fallback = using default value
    'missing': 'default',           # Missing = using default value
}
```

### Finding 2: Quality tier rename
Current: `high`, `medium`, `low` (quality_scorer.py)
New: `gold` (>95), `silver` (85-95), `bronze` (70-85), `poor` (50-70), `critical` (<50)

The rename happens in quality_scorer.py. The existing `quality_tier` column value will change — consumers should be updated.

### Finding 3: feature_sources already exists
The processor already writes `feature_sources` as a Python dict. The batch_writer serializes it as a JSON string to BigQuery. This dict is the input for computing the new per-feature columns.

---

## Implementation Steps (in order)

### Step 1: Enhance quality_scorer.py

**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py`

**Changes:**
- Add `SOURCE_TYPE_CANONICAL` mapping (9 types → 4)
- Add `FEATURE_CATEGORIES` dict (5 categories, all 37 features — player_history includes features 33-36 for total 13 features)
- Add `QUALITY_TIER_THRESHOLDS` (gold/silver/bronze/poor/critical)
- Add `calculate_per_feature_quality()` — returns dict of feature_N_quality scores
- Add `calculate_category_quality()` — returns pct and default_count per category
- Add `calculate_production_ready()` — score >= 70 AND matchup >= 50
- Add `calculate_training_ready()` — stricter tier check
- Add `calculate_alert_level()` — green/yellow/red
- Add `calculate_alerts()` — list of specific alert strings
- Add `build_quality_visibility_fields()` — master function returning all 120 new fields (122 total) (37 per-feature columns)
- Update existing `calculate_quality_score()` to use new tier names
- Keep backward compatibility: still return `quality_score`, `quality_tier`, `data_source`

**Source weight updates:**
```python
SOURCE_WEIGHTS = {
    'phase4': 100,
    'phase3': 87,
    'calculated': 95,     # Was 100, slightly less than phase4
    'default': 40,
    'vegas': 100,          # High quality when available
    'opponent_history': 90,
    'minutes_ppm': 95,
    'fallback': 40,
    'missing': 0,
}
```

### Step 2: Update ml_feature_store_processor.py

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Changes in `_generate_player_features()`:**
After existing quality scoring, call new function:

```python
# Existing code produces: features (list), feature_sources (dict)
# Existing quality scoring produces: quality_score, quality_tier, data_source

# NEW: Build quality visibility fields
from .quality_scorer import build_quality_visibility_fields
quality_fields = build_quality_visibility_fields(
    feature_sources=feature_sources,
    feature_values=features,
    feature_names=FEATURE_NAMES,
    quality_score=quality_score,
    processors_ran=self._processors_ran,    # Track which processors contributed
    upstream_metadata=source_tracking_data,  # Freshness info
)

# Merge into record
record.update(quality_fields)
```

**No changes needed to:**
- `FEATURE_NAMES`, `FEATURE_COUNT`, `FEATURE_VERSION` (unchanged)
- Feature extraction logic (unchanged)
- Feature calculation logic (unchanged)

### Step 3: Apply BigQuery schema update

**Run the ALTER TABLE statements from `04_ml_feature_store_v2.sql`:**
```bash
# Step 4 ALTER TABLE blocks add 121 new columns (120 quality + is_quality_ready)
bq query --use_legacy_sql=false < schemas/bigquery/predictions/04_ml_feature_store_v2_quality_alter.sql
```

Or extract Step 4 ALTER TABLE blocks and run them. The columns are all nullable so existing data is unaffected.

### Step 4: Refactor batch_writer.py MERGE (REQUIRED)

**Session 137 finding:** The MERGE query had a hardcoded UPDATE SET with ~48 explicit columns. New quality columns would NOT be updated on reprocessing. This was refactored to a dynamic UPDATE SET built from the target table schema, excluding only merge keys (`player_lookup`, `game_date`) and special columns (`created_at`, `updated_at`). The `updated_at` is set explicitly to `CURRENT_TIMESTAMP()`. This proven pattern is already used by 3 other processors in the codebase.

### Step 5: Create the unpivot view

```bash
bq query --use_legacy_sql=false "
CREATE OR REPLACE VIEW nba-props-platform.nba_predictions.v_feature_quality_unpivot AS
..."
# (from 04_ml_feature_store_v2.sql)
```

### Step 6: Update feature_store_validator.py

**File:** `shared/validation/feature_store_validator.py`

**Changes:**
- Add validation for new quality fields (quality_tier must be one of gold/silver/bronze/poor/critical)
- Add validation that per-feature quality scores are 0-100
- Add validation that per-feature sources are one of 4 canonical types

### Step 7: Update audit_feature_store.py

**File:** `bin/audit_feature_store.py`

**Changes:**
- Add quality visibility field checks to audit
- Verify all 37 features have quality/source columns populated (including features 33-36 trajectory features)
- Check category quality percentages sum correctly

### Step 8: Deploy Phase 4 processors

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

### Step 9: Verify with live data

After next pipeline run (~6 AM ET), verify:
```sql
SELECT
    player_lookup,
    quality_tier,
    quality_alert_level,
    matchup_quality_pct,
    game_context_quality_pct,
    feature_5_quality,
    feature_5_source,
    default_feature_count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
LIMIT 5;
```

### Step 10: Backfill historical data

```bash
# Test with 7 days first
PYTHONPATH=. python bin/backfill_ml_feature_store.py \
    --start-date 2026-01-29 \
    --end-date 2026-02-05

# Then full season
PYTHONPATH=. python bin/backfill_ml_feature_store.py \
    --start-date 2025-11-01 \
    --end-date 2026-02-05
```

---

## Skill Updates

### validate-daily skill

**File:** `.claude/skills/validate-daily/SKILL.md`

**Add new validation checks:**
```
Phase 0.6: Feature Quality Visibility
- Check quality_tier distribution (should be mostly gold/silver)
- Check for red alert_level (quality_alert_level = 'red')
- Check matchup_quality_pct > 0 (Session 132 detection)
- Check default_feature_count < 6 (healthy threshold)
- Check is_production_ready = TRUE for most players
- Verify feature_5_quality through feature_8_quality > 50 (composite factors)
```

**Example query to add:**
```sql
-- Feature quality health check
SELECT
    quality_tier,
    COUNT(*) as players,
    ROUND(AVG(feature_quality_score), 1) as avg_quality,
    SUM(default_feature_count) as total_defaults,
    COUNTIF(quality_alert_level = 'red') as red_alerts
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = @game_date
GROUP BY 1
ORDER BY 2 DESC;
```

### spot-check-features skill

**File:** `.claude/skills/spot-check-features/SKILL.md`

**Enhance existing checks with direct column access:**
- Replace JSON parsing of `feature_sources` with `feature_N_source` columns
- Add category quality checks using `matchup_quality_pct`, `vegas_quality_pct`, etc.
- Add per-feature quality distribution using `v_feature_quality_unpivot` view
- Add training readiness check using `is_training_ready` flag

**New check to add:**
```sql
-- Per-feature quality distribution (uses unpivot view)
SELECT
    feature_name,
    ROUND(AVG(quality), 1) as avg_quality,
    COUNTIF(source = 'default') as default_count,
    COUNTIF(source = 'phase4') as phase4_count
FROM nba_predictions.v_feature_quality_unpivot
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY avg_quality ASC
LIMIT 10;
```

---

## Files Changed Summary

| File | Change Type | Effort |
|------|------------|--------|
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Major enhancement | 3-4 hours |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Add quality fields to record | 1 hour |
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | Already done (Session 134) | Done |
| `shared/validation/feature_store_validator.py` | Add quality field validation | 30 min |
| `bin/audit_feature_store.py` | Add quality audit checks | 30 min |
| `.claude/skills/validate-daily/SKILL.md` | Add quality checks | 30 min |
| `.claude/skills/spot-check-features/SKILL.md` | Enhance with direct columns | 30 min |
| `tests/unit/data_processors/test_ml_feature_store.py` | Add quality scorer tests | 1-2 hours |

**Not changed:**
- `feature_extractor.py` — no changes needed
- `feature_calculator.py` — no changes needed
- `batch_writer.py` — auto-adapts to new schema columns
- `data_loaders.py` — reads features array, not quality columns
- `predictions/worker/*` — quality columns are for monitoring, not prediction

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| New fields cause MERGE failure | Low | High | All columns nullable, batch_writer handles NULL |
| Quality tier rename breaks consumers | Medium | Low | Only monitoring queries use tier values |
| Backfill takes too long | Low | Low | Batch by week, off-peak hours |
| Source type mapping incorrect | Low | Medium | Validate against existing feature_sources JSON |

---

## Release Checklist

```
Pre-deploy:
- [ ] quality_scorer.py enhanced with all quality visibility functions
- [ ] ml_feature_store_processor.py integrates quality fields (121 new fields (122 total), all 37 features)
- [ ] Unit tests pass for new quality scoring (all 37 features covered)
- [ ] ALTER TABLE statements applied to BigQuery (121 new columns (120 quality + is_quality_ready))
- [ ] Unpivot view created

Deploy:
- [ ] Deploy nba-phase4-precompute-processors
- [ ] Verify next pipeline run populates quality fields for all 37 features
- [ ] Run Session 132 detection query (< 5 seconds)

Post-deploy:
- [ ] Backfill 7 days (test)
- [ ] Backfill full season (90 days)
- [ ] Update validate-daily skill
- [ ] Update spot-check-features skill
- [ ] Update feature_store_validator.py
- [ ] Update audit_feature_store.py
- [ ] Monitor for 1 week
```

---

## Success Criteria

- [ ] `quality_tier` populated for all players (gold/silver/bronze/poor/critical)
- [ ] `feature_5_quality` through `feature_8_quality` populated (composite factors)
- [ ] `feature_33_quality` through `feature_36_quality` populated (trajectory features)
- [ ] `matchup_quality_pct` detects Session 132-style issues in < 5 seconds
- [ ] `is_production_ready` correctly gates low-quality records
- [ ] `v_feature_quality_unpivot` view works for per-feature analysis (all 37 features)
- [ ] No increase in pipeline processing time (< 10% overhead)
- [ ] `/validate-daily` includes quality visibility checks
- [ ] `/spot-check-features` uses direct columns instead of JSON
