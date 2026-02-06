# ML Feature Store V2 Processor - Quick Reference

**Last Updated**: 2025-11-25
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 4 - Precompute (ML Features) |
| **Schedule** | Nightly at 12:00 AM (runs LAST in Phase 4) |
| **Duration** | ~2 minutes (450 players) |
| **Priority** | **High** - Required for Phase 5 Week 1 |
| **Status** | ✅ Production Ready (158+ tests passing, quality gate active) |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | 1115 lines |
| **Schema** | `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | 30 fields |
| **Tests** | `tests/processors/precompute/ml_feature_store/` | **158+ total** |
| | - Unit tests | 57 tests |
| | - Integration tests | 30 tests |
| | - Integration enhanced | 30 tests |
| | - Performance tests | 16 tests |
| | - Feature extractor tests | 25 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 4 Precompute:
  ├─ player_daily_cache (CRITICAL) - Features 0-4, 18-20, 22-23
  ├─ player_composite_factors (CRITICAL) - Features 5-8
  ├─ player_shot_zone_analysis (CRITICAL) - Features 18-20
  └─ team_defense_zone_analysis (CRITICAL) - Features 13-14

Phase 3 Analytics (Fallback):
  ├─ player_game_summary (FALLBACK) - When Phase 4 incomplete
  ├─ upcoming_player_game_context (FALLBACK) - When Phase 4 incomplete
  └─ team_offense_game_summary (FALLBACK) - Team win %

Consumers (Phase 5):
  └─ All 5 prediction systems - XGBoost, moving avg, zone matchup, similarity, ensemble
```

---

## What It Does

1. **Primary Function**: Generates and caches 25 ML features for all active players nightly
2. **Key Output**: Array-based flexible feature storage (can evolve 25 → 47+ without schema changes)
3. **Value**: Combines 19 direct-copy features + 6 calculated features with quality scoring (0-100)

**Week 1-4 Strategy**: 25 baseline features. After 3 months, expand to 47 based on XGBoost feature importance.

---

## Feature Categories (25 Total)

### Features 0-4: Recent Performance Baseline
- 0: `points_avg_last_5` - Most recent form
- 1: `points_avg_last_10` - Recent trend
- 2: `points_avg_season` - Season baseline
- 3: `points_std_last_10` - Consistency/volatility
- 4: `games_in_last_7_days` - Recent workload
- **Source**: Phase 4 (player_daily_cache) → Phase 3 fallback → Defaults

### Features 5-8: Composite Adjustment Factors
- 5: `fatigue_score` - Physical freshness (0-100)
- 6: `shot_zone_mismatch_score` - Player zones vs opponent (-10 to +10)
- 7: `pace_score` - Game pace impact (-3 to +3)
- 8: `usage_spike_score` - Recent usage changes (-3 to +3)
- **Source**: Phase 4 ONLY (player_composite_factors) → Defaults (no Phase 3 fallback)

### Features 9-12: Derived Performance Factors (CALCULATED)
- 9: `rest_advantage` - Player rest minus opponent rest (-2 to +2)
- 10: `injury_risk` - Status mapped to numeric (0-3)
- 11: `recent_trend` - Performance trajectory (-2 to +2)
- 12: `minutes_change` - Playing time trend
- **Source**: CALCULATED fresh from Phase 3 data (always 100% quality)

### Features 13-17: Matchup and Game Context
- 13: `opponent_def_rating` - Opponent defensive efficiency
- 14: `opponent_pace` - Opponent pace
- 15: `home_away` - Home game flag (0/1)
- 16: `back_to_back` - Back-to-back flag (0/1)
- 17: `playoff_game` - Playoff flag (0/1)
- **Source**: Mixed (13-14 from Phase 4 team_defense, 15-17 from Phase 3)

### Features 18-21: Shot Zone Distribution
- 18: `pct_paint` - Paint shot rate (0-1)
- 19: `pct_mid_range` - Mid-range shot rate (0-1)
- 20: `pct_three` - Three-point shot rate (0-1)
- 21: `pct_free_throw` - Free throw contribution (CALCULATED)
- **Source**: 18-20 from Phase 4 (player_shot_zone), 21 calculated

### Features 22-24: Team Offensive Context
- 22: `team_pace` - Team's pace last 10 games
- 23: `team_off_rating` - Team's offensive rating
- 24: `team_win_pct` - Team's season win % (CALCULATED)
- **Source**: 22-23 from Phase 4 (player_daily_cache), 24 calculated

---

## Quality Score Calculation

```python
# Quality = weighted average of source quality across all 25 features
SOURCE_WEIGHTS = {
    'phase4': 100,      # Preferred (pre-computed)
    'phase3': 75,       # Fallback (calculated from raw)
    'calculated': 100,  # Always accurate (calculated fresh)
    'default': 40       # Last resort (hardcoded)
}

# Example: 20 from phase4, 3 calculated, 2 defaults
quality_score = ((20*100) + (3*100) + (2*40)) / 25 = 95.2
```

**Quality Tiers**:
- **95-100**: Excellent (all Phase 4 + calculated)
- **85-94**: Good (some Phase 3 fallback)
- **70-84**: Medium (significant Phase 3 reliance)
- **<70**: Low (many defaults, early season)

---

## Output Schema Summary

**Total Fields**: 30

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 4 | player_lookup, universal_player_id, game_date, game_id |
| Flexible Features | 4 | features (array), feature_names (array), feature_count, feature_version |
| Feature Metadata | 2 | feature_generation_time_ms, feature_quality_score |
| Player Context | 3 | opponent_team_abbr, is_home, days_rest |
| Data Source | 1 | data_source ('phase4', 'phase3', 'mixed', 'early_season') |
| Source Tracking (v4.0) | 12 | 4 sources × 3 fields |
| Early Season | 2 | early_season_flag, insufficient_data_reason |
| Processing Metadata | 2 | created_at, updated_at |

---

## Health Check Query

```sql
-- Run this to verify feature store health
SELECT
  COUNT(DISTINCT player_lookup) >= 100 as enough_players,
  AVG(feature_quality_score) >= 85 as good_quality,
  COUNT(CASE WHEN early_season_flag THEN 1 END) as early_season_count,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(),
      source_daily_cache_last_updated, HOUR)) as max_source_age_hrs
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();

-- Expected Results:
-- enough_players: TRUE (100+)
-- good_quality: TRUE (85%+)
-- early_season_count: < 50 (after week 3)
-- max_source_age_hrs: < 24
```

---

## Common Issues & Quick Fixes

### Issue 1: Low Average Quality Score (<85)
**Symptom**: Many features using Phase 3 fallback or defaults
**Diagnosis**:
```sql
-- Check which sources causing low quality
SELECT
  AVG(source_daily_cache_completeness_pct) as cache_pct,
  AVG(source_composite_completeness_pct) as composite_pct,
  AVG(source_shot_zones_completeness_pct) as shot_zones_pct,
  AVG(source_team_defense_completeness_pct) as defense_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```
**Fix**:
1. Check which Phase 4 source has low completeness
2. Verify Phase 4 processors ran successfully
3. May need to run Phase 4 processors manually

### Issue 2: Feature Extraction Taking >100ms Per Player
**Symptom**: High `feature_generation_time_ms` values
**Diagnosis**:
```sql
-- Check generation time distribution
SELECT
  APPROX_QUANTILES(feature_generation_time_ms, 100)[OFFSET(50)] as p50_ms,
  APPROX_QUANTILES(feature_generation_time_ms, 100)[OFFSET(95)] as p95_ms,
  MAX(feature_generation_time_ms) as max_ms
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
```
**Fix**:
1. Expected: p50 ~50ms, p95 ~150ms
2. If > 200ms: Check Phase 4 cache availability (fallback to Phase 3 is slower)
3. Ensure Phase 4 dependencies completed before this runs

### Issue 3: No Features on Game Day
**Symptom**: Empty table on game day
**Fix**:
1. Check if games scheduled (may be off-day, normal to be empty)
2. Verify all 4 Phase 4 dependencies completed
3. Check processor logs for early season handling

---

## Processing Flow

```
player_daily_cache ──────┐
player_composite_factors ┤
player_shot_zone ────────┼─→ ML FEATURE STORE ─┬─→ XGBoost predictions
team_defense_zone ───────┘     (450 players)    ├─→ Moving avg predictions
                               25 features each  ├─→ Zone matchup predictions
                                                 ├─→ Similarity predictions
                                                 └─→ Ensemble predictions
```

**Timing**:
- Runs: 12:00 AM nightly (LAST in Phase 4 - waits for all others)
- Waits for: All 4 Phase 4 processors
- Cross-dataset write: `nba_predictions` (not `nba_precompute`)
- Phase 5 usage: Load features for all players, pass to ML models

---

## Success Criteria (Updated Session 139)

| Criterion | Threshold | Notes |
|-----------|-----------|-------|
| Player rows | >= 200 | Game day minimum |
| Avg quality score | >= 75 | Phase 5 requirement |
| `is_quality_ready` rate | >= 90% | Quality gate pass rate |
| All 4 dependencies | Present | player_daily_cache, composite_factors, shot_zone, team_defense |
| `prediction_made_before_game` | Populated | Enables accurate grading |

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Players processed | < 100 (game day) | Critical |
| Avg quality score | < 85 | Warning |
| Avg quality score | < 70 | Critical |
| Processing time | > 5 min | Warning |
| Any source age | > 24 hrs | Critical |
| Early season rate | > 20% (after week 3) | Warning |
| Quality gate fail rate | > 10% | Warning (Session 139) |
| `PREDICTIONS_SKIPPED` alert | Any | Warning (Session 139) |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - ML Feature Store V2 Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`
- 🧪 **Test Suite**: `tests/processors/precompute/ml_feature_store/`
- 📊 **Related Processors**:
  - ↑ Upstream: All 4 Phase 4 processors (must complete first)
  - → Consumers: All 5 Phase 5 prediction systems

---

## Notes

- **Array-Based Design**: Flexible for feature evolution (25 → 47+ without schema changes)
- **Feature Versioning**: `feature_version` field tracks which features present
- **Phase 4 → Phase 3 Fallback**: Ensures robustness when Phase 4 incomplete
- **Quality Scoring**: Enables Phase 5 to adjust confidence based on data quality
- **Quality Gate (Session 139)**: `is_quality_ready` field enforces hard floor rules before predictions; BACKFILL mode recovers skipped predictions
- **Cross-Dataset**: Writes to `nba_predictions` (not `nba_precompute`) for Phase 5 access
- **Most Complex**: 4 Phase 4 sources + 3 Phase 3 fallbacks = 7 total dependencies
- **158+ Tests**: Most thoroughly tested processor (includes performance tests)

---

**Card Version**: 1.1
**Created**: 2025-11-15
**Last Updated**: 2026-02-06 (Session 139 - quality gate, success criteria)
**Verified Against**: Code commit 71f4bde
