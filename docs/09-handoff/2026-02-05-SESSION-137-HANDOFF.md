# Session 137 Handoff: Feature Quality Visibility - Implementation

**Date:** February 5, 2026
**Status:** Code complete, needs schema update + deploy + backfill
**Priority:** HIGH - prevents Session 132-style silent failures

---

## What We Did

Implemented the Feature Quality Visibility system — 121 new columns on `ml_feature_store_v2` that give per-feature, per-category, and aggregate quality tracking. This lets us detect when features silently default to fallback values (like Session 132, where all 6 matchup features used defaults for an entire day and nobody noticed).

### Problem Being Solved

In Session 132, the `PlayerCompositeFactorsProcessor` didn't run, so features 5-8 (fatigue, shot zone mismatch, pace, usage spike) and 13-14 (opponent defense) all got default values. The aggregate `feature_quality_score` showed 72 ("looks fine") because it averaged 37 features. With the new system, `matchup_quality_pct` would show 40% and `quality_alert_level` would be `red` — detectable in < 5 seconds.

### Files Changed (5 files, 514 insertions)

| File | What Changed |
|------|-------------|
| `quality_scorer.py` | Major enhancement: `build_quality_visibility_fields()` returns 120 fields (per-feature quality/source, category quality, alerts, training readiness). Added `get_feature_quality_tier()` with feature-store-specific thresholds. Extended `SOURCE_WEIGHTS` to handle all 9 source types. |
| `ml_feature_store_processor.py` | Calls `build_quality_visibility_fields()` after quality scoring, merges into record. Replaced shared tier function with local one. Added `is_quality_ready` field. Fixed stale "33" comments. |
| `batch_writer.py` | **Critical fix:** Refactored MERGE from hardcoded ~48-column UPDATE SET to dynamic column building from schema. Prevents "forgotten column" bugs forever. Streaming buffer handling unchanged. |
| `04_ml_feature_store_v2.sql` | Fixed stale field counts (114→122), fixed player_history description, added `is_quality_ready` column. |
| `08-IMPLEMENTATION-PLAN.md` | Fixed stale "128" references, updated Step 4 to reflect batch_writer refactor. |

### Key Design Decisions

1. **`is_production_ready` unchanged** — still means "completeness ≥ 70% AND upstreams ready." 20+ consumers depend on it.
2. **`is_quality_ready` is NEW** — TRUE if quality_tier in (gold/silver/bronze) AND score ≥ 70 AND matchup_quality_pct ≥ 50. Safe to adopt incrementally.
3. **Tier system is local** — `get_feature_quality_tier()` in quality_scorer.py, NOT the shared `QualityTier` enum. Different thresholds (silver=85 vs shared=75). Zero blast radius.
4. **`calculated` weight stays at 100** — deferred to separate deploy to avoid score discontinuity.
5. **Dynamic MERGE** — batch_writer builds UPDATE SET from schema. Proven pattern used by 3 other processors.

---

## What Needs to Happen Next

### Step 1: Commit the code

```bash
git add data_processors/precompute/ml_feature_store/quality_scorer.py \
        data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
        data_processors/precompute/ml_feature_store/batch_writer.py \
        schemas/bigquery/predictions/04_ml_feature_store_v2.sql \
        docs/08-projects/current/feature-quality-visibility/08-IMPLEMENTATION-PLAN.md \
        docs/09-handoff/2026-02-05-SESSION-137-HANDOFF.md

git commit -m "feat: Implement feature quality visibility (121 new columns, dynamic MERGE)

- quality_scorer.py: build_quality_visibility_fields() returns 120 fields
- ml_feature_store_processor.py: integrates quality fields into record
- batch_writer.py: dynamic UPDATE SET from schema (was hardcoded 48 cols)
- Added is_quality_ready field (separate from is_production_ready)
- Fixed stale field counts and comments

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

### Step 2: Apply BigQuery schema update

Run the ALTER TABLE statements from `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`. There are 6 ALTER TABLE blocks in Step 4 that add the quality visibility columns. All columns are NULLABLE so existing data is unaffected.

```bash
# Extract and run Step 4 ALTER TABLE blocks
# The blocks start at "-- Step 4: Add feature quality visibility columns"
# There are 6 ALTER TABLE statements:
# 1. Aggregate quality (9 fields + is_quality_ready)
# 2. Category quality (18 fields)
# 3. Per-feature quality scores (37 fields)
# 4. Per-feature sources (37 fields)
# 5. Per-feature details JSON (6 fields)
# 6. Model compatibility (4 fields) + Traceability (6 fields) + Legacy (3 fields)

# Run each ALTER TABLE block via bq CLI or BigQuery console
bq query --use_legacy_sql=false "ALTER TABLE \`nba-props-platform.nba_predictions.ml_feature_store_v2\` ..."
```

**IMPORTANT:** The `is_quality_ready` column was added to the first ALTER TABLE block (aggregate quality). Make sure it's included.

### Step 3: Deploy Phase 4 processors

This is the only service that needs deploying — it runs the ML feature store processor.

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

### Step 4: Verify with next pipeline run

After the next pipeline run (~6 AM ET), verify:

```sql
SELECT
    player_lookup,
    quality_tier,
    quality_alert_level,
    matchup_quality_pct,
    game_context_quality_pct,
    feature_5_quality,
    feature_5_source,
    default_feature_count,
    is_quality_ready
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
LIMIT 10;
```

### Step 5: Create unpivot view

```bash
# Run the CREATE OR REPLACE VIEW statement from 04_ml_feature_store_v2.sql
# (the v_feature_quality_unpivot view near the bottom of the file)
```

### Step 6: Backfill historical data

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

## Tests

All 36 existing tests pass:
- `tests/unit/data_processors/test_ml_feature_store.py` — 21 passed
- `tests/processors/precompute/ml_feature_store/test_unit.py::TestQualityScorer` — 15 passed
- `identify_data_tier()` kept as deprecated for backward compatibility

### Manual verification scenarios tested:

| Scenario | Result |
|----------|--------|
| All phase4 sources | score=100, tier=gold, alert=green, quality_ready=True |
| Session 132 (matchup defaults) | score=90.27, tier=silver, alert=**red**, quality_ready=**False**, alerts=all_matchup_features_defaulted |
| `identify_data_tier()` backward compat | high/medium/low — unchanged |

---

## What NOT to Change

- **Do NOT change `is_production_ready`** — 20+ production consumers depend on its current completeness-based semantics
- **Do NOT change `calculated` source weight** — defer to separate deploy with before/after analysis
- **Do NOT change shared `QualityTier` enum** — the feature store uses its own `get_feature_quality_tier()`
- **Do NOT change `feature_quality_score` computation** — `SOURCE_WEIGHTS` now correctly handles all 9 source types (vegas, opponent_history, minutes_ppm were previously defaulting to 40)

---

## Architecture Quick Reference

```
quality_scorer.py (enhanced)
├── SOURCE_WEIGHTS: 9 source types → quality scores (0-100)
├── SOURCE_TYPE_CANONICAL: 9 types → 4 canonical (phase4/phase3/calculated/default)
├── FEATURE_CATEGORIES: 5 categories × feature indices = 37 total
├── get_feature_quality_tier(): gold/silver/bronze/poor/critical
├── QualityScorer.calculate_quality_score(): aggregate score (unchanged)
├── QualityScorer.build_quality_visibility_fields(): 120 fields
│   ├── Section 1: Aggregate (9 fields) + is_quality_ready
│   ├── Section 2: Category quality (18 fields)
│   ├── Section 3: Per-feature quality (37 fields)
│   ├── Section 4: Per-feature source (37 fields)
│   ├── Section 5: JSON details (6 fields)
│   ├── Section 6: Model compat (4 fields)
│   ├── Section 7: Traceability (6 fields)
│   └── Section 8: Legacy (3 fields)
└── QualityScorer.identify_data_tier(): DEPRECATED, kept for tests

ml_feature_store_processor.py
├── Calls build_quality_visibility_fields() after quality scoring
├── record.update(quality_fields) before return
├── is_production_ready: UNCHANGED (completeness-based)
└── quality_tier: now uses get_feature_quality_tier() (local)

batch_writer.py
├── _merge_to_target(): dynamic UPDATE SET from target_schema
├── Excludes: player_lookup, game_date, created_at, updated_at
├── Appends: updated_at = CURRENT_TIMESTAMP()
└── Streaming buffer handling: UNCHANGED
```
