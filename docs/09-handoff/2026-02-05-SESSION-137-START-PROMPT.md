# Session 137: Feature Quality Visibility - Final Review & Implementation

## Copy-paste this into a new Claude Code session:

---

## Context: Why We're Doing This

In Session 132, all 6 matchup features (fatigue_score, shot_zone_mismatch_score, pace_score, usage_spike_score, opponent_def_rating, opponent_pace) silently defaulted to fallback values because the PlayerCompositeFactorsProcessor didn't run. The aggregate `feature_quality_score` showed 72 ("looks fine") while the matchup-specific quality was 0 ("completely broken"). This went undetected for an entire day, causing bad predictions.

**The root problem:** We have no per-feature quality visibility. The aggregate score masks component failures. We can't tell which features are real data vs defaults, which processor failed, or which category degraded.

**The solution:** Add 122 quality visibility columns to `ml_feature_store_v2` — per-feature quality scores, per-feature source tracking, category-level quality percentages, alert levels, and production/training readiness gates. This lets us detect Session 132-style issues in <5 seconds instead of 2+ hours.

Sessions 133-134c spent ~4 hours designing the schema, fixing feature name mismatches (the original design had 12 wrong feature names and was missing 4 features), creating the implementation plan, and documenting everything. All design work is done. No Python code has been changed yet.

## Your Task

**Before we implement anything, do a final review of the complete design to make sure everything is correct and consistent.** Previous sessions had multiple rounds of fixes (33→37 features, wrong feature names at indices 10-21, wrong field counts). I want fresh eyes on this before we write any code.

### Step 1: Review these files (in order)

1. **The implementation plan** (most important — this is your roadmap):
   `docs/08-projects/current/feature-quality-visibility/08-IMPLEMENTATION-PLAN.md`

2. **The SQL schema** (source of truth for what gets deployed):
   `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`

3. **The Python processor** (source of truth for feature names/indices):
   `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

4. **The quality scorer** (file that needs the most changes):
   `data_processors/precompute/ml_feature_store/quality_scorer.py`

5. **The file map guide** (which files to touch):
   `docs/05-development/feature-store-complete-file-map.md`

6. **The hybrid schema design** (full design rationale):
   `docs/08-projects/current/feature-quality-visibility/07-FINAL-HYBRID-SCHEMA.md`

### Step 2: Cross-check for consistency

Verify:
- [ ] SQL schema feature names at ALL 37 indices match `FEATURE_NAMES` in the processor
- [ ] Category assignments are correct (matchup=6, player_history=13, team_context=3, vegas=4, game_context=11 = 37)
- [ ] Field counts are consistent across all docs (122 quality fields, 74 per-feature columns)
- [ ] ALTER TABLE statements match the CREATE TABLE columns exactly
- [ ] Unpivot view covers all 37 features with correct names
- [ ] Implementation plan's 3 audit findings (source type mapping, tier rename, feature_sources reuse) are still accurate
- [ ] No references to "33 features" or "114 fields" remain anywhere

### Step 3: Review the Python code that will be modified

Read the actual code and check:
- [ ] `quality_scorer.py` — What does it currently do? What needs to change?
- [ ] `ml_feature_store_processor.py` — Where does quality scoring happen? Where do we inject the new fields?
- [ ] `shared/validation/feature_store_validator.py` — What validations exist?
- [ ] `shared/utils/bigquery_batch_writer.py` — Will it auto-handle new nullable columns?

### Step 4: Report findings

Tell me:
1. Any remaining inconsistencies or errors
2. Any concerns about the implementation approach
3. Whether the 10-step implementation plan is correct and complete
4. If you'd change the order of operations
5. Any risks I should know about

**Only after you've reviewed everything and I've approved your findings, proceed to implement starting with Step 1 of the plan (quality_scorer.py).**

### Key References

- **Handoff:** `docs/09-handoff/2026-02-05-SESSION-134c-HANDOFF.md`
- **Feature name source of truth:** `FEATURE_NAMES` list in `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- **CLAUDE.md quality section** has the updated category definitions
- **3 audit findings** are in the implementation plan (source types, tier names, feature_sources dict)

---
