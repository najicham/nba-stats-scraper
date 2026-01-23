# Data Cascade Solution Implementation - Handoff
**Date:** January 22, 2026
**Purpose:** Implement the 3-phase solution to prevent predictions with incomplete historical data
**Priority:** HIGH - Architectural Fix

---

## Your Mission

Implement the data dependency validation system to prevent predictions from being made with incomplete/stale historical data. This is a **code implementation task** - the analysis and design are complete.

---

## Context Summary

### The Problem (Already Diagnosed)

When historical data is missing (e.g., team boxscore gap Dec 27 - Jan 21), downstream processing continues but produces **biased results**:

1. Completeness checks only validate TODAY's data
2. Rolling averages (`last_10_games`) silently return fewer games
3. No validation that the 10-game window is actually complete
4. Predictions made with stale/biased features - no warning

### The Gap in Current Code

```python
# Current behavior in feature_extractor.py:
query = "SELECT * FROM games ORDER BY date DESC LIMIT 10"
# Returns 10 rows - NO ERROR
# But those 10 rows might span 6 weeks due to gap (should be 3 weeks)
# Nobody validates the window is healthy
```

---

## What to Implement

### Phase 1: Historical Window Validation (THIS WEEK)

**Create:** `shared/validation/historical_window_validator.py`

Key functions needed:
1. `validate_player_window(player_lookup, target_date, window_size=10)`
   - Check if player's 10-game window is complete
   - Return: games_found, completeness_pct, window_span_days, is_stale

2. `validate_date_historical_completeness(target_date, lookback_days=7)`
   - Check if critical tables have data for recent days
   - Return: missing dates by table

**Integrate into:**
- `ml_feature_store_processor.py` - Add warning logging when window incomplete
- `bin/validate_pipeline.py` - Add pre-flight historical check

### Phase 2: Feature Quality Metadata (NEXT 2 WEEKS)

**Schema change:** Add to `ml_feature_store_v2`:
```sql
historical_completeness STRUCT<
    games_found INT64,
    games_expected INT64,
    completeness_pct FLOAT64,
    is_reliable BOOL
>
```

**Code changes:**
- Populate metadata during feature generation
- Add `is_reliable` filtering option in prediction coordinator

### Phase 3: Cascade Dependency Graph (NEXT MONTH)

**New table:** `nba_precompute.feature_lineage`
- Track which games contributed to each feature calculation
- Enable automated cascade detection after backfills

---

## Reference Documents

**Read these FIRST:**

1. `/docs/08-projects/current/team-boxscore-data-gap-incident/SOLUTION-PROPOSAL-DATA-DEPENDENCY-VALIDATION.md`
   - Complete implementation spec with code examples
   - Configuration recommendations
   - Monitoring/alerting additions

2. `/docs/08-projects/current/team-boxscore-data-gap-incident/ARCHITECTURAL-ANALYSIS-DATA-DEPENDENCIES.md`
   - Why the current architecture fails
   - The rolling window problem explained
   - Dependency chain visualization

3. `/docs/09-handoff/2026-01-22-DATA-CASCADE-PROBLEM-HANDOFF.md`
   - Earlier session's analysis (similar findings)
   - Additional SQL patterns

---

## Key Files to Modify

| File | Change |
|------|--------|
| `shared/validation/historical_window_validator.py` | **CREATE** - New validation module |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Add window validation calls |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Log when window degraded |
| `bin/validate_pipeline.py` | Add historical completeness check |
| `shared/config/validation_config.yaml` | **CREATE** - Configuration for thresholds |

---

## Success Criteria

**Phase 1 Complete When:**
- [ ] `historical_window_validator.py` exists and tested
- [ ] Warning logged when player has <80% window completeness
- [ ] Warning logged when window spans >21 days
- [ ] `validate_pipeline.py` checks historical tables before Phase 4
- [ ] Documentation updated

**Phase 2 Complete When:**
- [ ] `historical_completeness` column added to feature store
- [ ] Metadata populated during feature generation
- [ ] Can query for unreliable features
- [ ] Dashboard shows feature reliability metrics

---

## Quick Start

```bash
cd /home/naji/code/nba-stats-scraper

# Read the solution spec
cat docs/08-projects/current/team-boxscore-data-gap-incident/SOLUTION-PROPOSAL-DATA-DEPENDENCY-VALIDATION.md

# Look at existing validation patterns
ls shared/validation/
cat shared/validation/phase_boundary_validator.py

# Look at feature extractor (where rolling windows are calculated)
cat data_processors/precompute/ml_feature_store/feature_extractor.py | head -100
```

---

## Questions to Consider

1. **Performance:** How expensive is checking historical completeness per-player?
2. **Behavior:** Should we WARN, FLAG, or BLOCK when incomplete?
3. **Thresholds:** Is 80% completeness the right minimum?
4. **Scope:** Should we validate ALL players or sample?

---

**Document Status:** Ready for Implementation
**Estimated Effort:** Phase 1: 4-6 hours, Phase 2: 8-12 hours, Phase 3: 20+ hours
