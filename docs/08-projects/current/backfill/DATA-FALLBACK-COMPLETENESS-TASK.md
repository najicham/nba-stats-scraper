# Data Fallback & Completeness System - Design Task

**Created:** 2025-11-30
**Status:** Ready for Implementation
**Priority:** HIGH - Required before production backfill

---

## Executive Summary

We need a comprehensive system that handles every possible data source failure gracefully, tracks data quality in the database, and makes intelligent decisions about when to:
1. **Continue with degraded quality** (low-confidence prediction)
2. **Skip and flag for remediation** (error state, needs fixing)
3. **Mark data as incomplete** for future lookbacks to make informed decisions

---

## The Problem

Currently, some processors **fail hard** when data is missing:
```python
# team_defense_game_summary_processor.py:192
raise ValueError("Missing opponent offensive data from nbac_team_boxscore")
```

This is problematic because:
- System stops instead of gracefully degrading
- No record in DB that data was attempted but missing
- Future lookbacks don't know this date has issues
- No visibility into what's missing or why

---

## Desired End State

### 1. Every Data Source Has a Fallback Chain
```
PRIMARY: nbac_team_boxscore
    ↓ if missing
FALLBACK 1: Aggregate from nbac_gamebook_player_stats (reconstructed)
    ↓ if missing
FALLBACK 2: Aggregate from bdl_player_boxscores (reconstructed, lower quality)
    ↓ if all missing
GRACEFUL SKIP: Create placeholder record with quality_tier='unusable'
```

### 2. Quality Tracked in Database
Every record should have:
- `quality_tier`: gold/silver/bronze/poor/unusable
- `quality_score`: 0-100 numeric
- `quality_issues`: Array of specific problems
- `is_production_ready`: Boolean for prediction eligibility
- `data_completeness_pct`: What % of expected data is present
- `missing_sources`: Which sources were unavailable

### 3. Decision Thresholds Defined
| Quality Score | Tier | Action | Prediction? |
|---------------|------|--------|-------------|
| 95-100 | gold | Full confidence | Yes, 100% confidence cap |
| 75-94 | silver | Slight penalty | Yes, 95% confidence cap |
| 50-74 | bronze | Moderate penalty | Yes, 80% confidence cap |
| 25-49 | poor | Strong warning | Yes, 60% confidence cap, flagged |
| 0-24 | unusable | Skip prediction | No, placeholder only |

### 4. Future Lookbacks Informed
When Phase 4 calculates rolling averages and encounters a low-quality historical record:
- Option A: Exclude from average (reduces sample size)
- Option B: Include with quality-weighted contribution
- Option C: Flag the aggregate as degraded quality

---

## Files to Study

### Core Architecture Documents
```
docs/01-architecture/source-coverage/01-core-design.md
docs/01-architecture/source-coverage/02-schema-reference.md
docs/01-architecture/source-coverage/03-implementation-guide.md
docs/06-reference/data-sources/02-fallback-strategies.md
docs/06-reference/data-sources/01-coverage-matrix.md
```

### Phase 3 Processors (Where Fallbacks Are Implemented)
```
data_processors/analytics/player_game_summary/player_game_summary_processor.py
  - Lines 264-396: Multi-source extraction with fallback
  - Lines 713-722: Quality tier assignment

data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py
  - Line 192: HARD FAIL - needs fixing
  - Lines 367-420: Defensive actions fallback (gamebook → BDL)
  - Lines 592-596: data_quality_tier assignment

data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py
  - Similar structure to team_defense, check for hard fails

data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
  - Lines 366-370: BettingPros fallback implementation
  - Lines 677-754: Prop lines fallback

data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py
  - Check for game lines fallback
```

### Phase 4 Processors (Quality Propagation)
```
data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
  - How quality flows from Phase 3 → Phase 4
  - Early season placeholder creation
  - is_production_ready logic

data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py
```

### Phase 5 Predictions (Quality Consumption)
```
predictions/worker/worker.py
  - Lines 442-481: Feature validation and quality checks
  - min_quality_score threshold (currently 70.0)
  - is_production_ready checks
```

### Base Classes (Shared Logic)
```
data_processors/analytics/analytics_base.py
  - check_dependencies() method
  - Source tracking logic

data_processors/raw/processor_base.py
  - Base dependency checking
```

### Database Schemas
```
schemas/bigquery/nba_analytics/player_game_summary.sql
schemas/bigquery/nba_analytics/team_defense_game_summary.sql
schemas/bigquery/nba_analytics/team_offense_game_summary.sql
schemas/bigquery/nba_precompute/ml_feature_store_v2.sql
schemas/bigquery/nba_reference/source_coverage_log.sql
```

---

## Data Sources to Map

### Phase 2 Raw Tables (Sources)
| Table | Primary Use | Coverage | Has Fallback? |
|-------|-------------|----------|---------------|
| `nbac_gamebook_player_stats` | Player stats | ~100% | Yes → bdl_player_boxscores |
| `nbac_team_boxscore` | Team stats | ~100% | **NO - NEEDS FALLBACK** |
| `bdl_player_boxscores` | Player fallback | ~94% | Is the fallback |
| `odds_api_player_points_props` | Current props | ~40% | Yes → bettingpros |
| `bettingpros_player_points_props` | Historical props | ~99.7% | Is the fallback |
| `bigdataball_play_by_play` | Shot zones | ~94% | Partial → nbac_play_by_play |
| `nbac_schedule` | Game schedule | ~100% | Yes → ESPN |
| `odds_api_game_lines` | Spreads/totals | ~99% | No (99% coverage OK) |

### Phase 3 Analytics Tables (Outputs)
| Table | Key Sources | Failure Behavior |
|-------|-------------|------------------|
| `player_game_summary` | gamebook, bdl, props | Graceful fallback ✅ |
| `team_defense_game_summary` | team_boxscore, gamebook | **HARD FAIL** ❌ |
| `team_offense_game_summary` | team_boxscore, pbp | **CHECK - likely hard fail** |
| `upcoming_player_game_context` | props, schedule | Graceful fallback ✅ |
| `upcoming_team_game_context` | game_lines, schedule | Check fallback |

---

## Deliverables Required

### 1. Complete Fallback Matrix
Create a comprehensive matrix showing:
- Every data source
- Its fallback chain (1st, 2nd, 3rd fallback)
- What happens at each level (quality tier assigned)
- Final fallback behavior (placeholder or skip)

### 2. Database Column Standardization
Ensure ALL Phase 3+ tables have:
```sql
-- Quality tracking (REQUIRED)
quality_tier STRING,              -- 'gold', 'silver', 'bronze', 'poor', 'unusable'
quality_score FLOAT64,            -- 0-100
quality_issues ARRAY<STRING>,     -- ['missing_team_boxscore', 'reconstructed']
data_sources ARRAY<STRING>,       -- ['nbac_gamebook', 'bdl_fallback']

-- Production readiness (REQUIRED)
is_production_ready BOOL,         -- Can this be used for predictions?
data_completeness_pct FLOAT64,    -- What % of expected data present?

-- Remediation tracking (NEW)
requires_remediation BOOL,        -- Should this be backfilled/fixed?
remediation_priority STRING,      -- 'critical', 'high', 'medium', 'low'
missing_sources ARRAY<STRING>,    -- Which sources were unavailable?
```

### 3. Processor Updates
Fix processors that hard-fail to instead:
1. Try fallback sources
2. If all fail, create placeholder with quality_tier='unusable'
3. Log to source_coverage_log
4. Continue processing (don't raise exception)

### 4. Quality Propagation Rules
Document how quality flows through phases:
```
Phase 3 → Phase 4:
  - Aggregate takes WORST quality of inputs
  - 9 gold + 1 bronze = bronze aggregate
  - Track: aggregated_from_count, min_input_quality

Phase 4 → Phase 5:
  - Confidence capped by quality tier
  - is_production_ready must be TRUE
  - quality_score must be >= threshold (currently 70)
```

### 5. Future Lookback Handling
Define behavior when rolling averages encounter low-quality historical data:
```python
# Option A: Exclude (reduces sample)
games_for_avg = [g for g in last_10 if g.quality_tier != 'unusable']

# Option B: Quality-weighted
weighted_avg = sum(g.points * g.quality_score for g in last_10) / sum(g.quality_score)

# Option C: Flag aggregate
if any(g.quality_tier in ['poor', 'unusable'] for g in last_10):
    aggregate.quality_issues.append('includes_low_quality_data')
```

### 6. Source Coverage Log Integration
Ensure every fallback/failure is logged:
```python
log_source_coverage_event(
    event_type='fallback_used',
    severity='warning',
    primary_source='nbac_team_boxscore',
    fallback_sources_tried=['reconstructed_from_players'],
    resolution='reconstructed',
    quality_tier_before='gold',
    quality_tier_after='silver',
    game_id=game_id,
    game_date=game_date
)
```

---

## Key Questions to Answer

1. **Threshold for predictions:** What's the minimum quality_score to generate a prediction?
   - Current: 70.0 in worker.py
   - Should this vary by prediction type?

2. **Reconstructed data quality:** If we aggregate player stats → team stats, is that:
   - silver (backup source used)?
   - bronze (reconstructed)?

3. **Missing props handling:** If a player has stats but no prop line:
   - Skip prediction entirely?
   - Make prediction with NULL prop context?

4. **Historical lookback rules:** When Phase 4 calculates 10-game average and game 5 is 'poor' quality:
   - Use only 9 games?
   - Use all 10 with quality weighting?
   - Flag the result?

5. **Error recovery priority:** When we detect missing data, how do we prioritize fixing it?
   - By recency (fix recent first)?
   - By impact (fix most-used data first)?
   - By source (fix primary sources first)?

---

## Current Gaps Found

### Critical (Blocks Processing)
1. `team_defense_game_summary` raises ValueError if team_boxscore missing
2. `team_offense_game_summary` - needs verification, likely same issue

### Medium (Quality Not Tracked)
1. Some processors use `data_quality_tier` instead of standard `quality_tier`
2. `source_coverage_log` may not be actively receiving events
3. `missing_sources` column doesn't exist yet

### Low (Documentation Gaps)
1. No single matrix showing all sources and fallbacks
2. Quality propagation rules not fully documented
3. Remediation workflow not defined

---

## Success Criteria

When this task is complete:
1. [ ] Every processor handles missing data gracefully (no hard fails)
2. [ ] Every record has quality_tier, quality_score, quality_issues populated
3. [ ] source_coverage_log receives events for every fallback/failure
4. [ ] Future lookbacks can detect and handle low-quality historical data
5. [ ] Comprehensive fallback matrix document exists
6. [ ] All Phase 3+ tables have standardized quality columns
7. [ ] Remediation workflow defined (how to fix low-quality data)

---

## Recommended Approach

### Phase 1: Audit (1-2 hours)
- Read all listed files
- Document current fallback behavior for each processor
- Identify all hard-fail points
- Check which quality columns actually exist

### Phase 2: Design (1-2 hours)
- Create complete fallback matrix
- Define quality tier thresholds
- Define propagation rules
- Design remediation workflow

### Phase 3: Implement (3-4 hours)
- Add missing fallbacks to team processors
- Standardize quality columns across tables
- Add source_coverage_log integration
- Add missing_sources and remediation columns

### Phase 4: Test (1-2 hours)
- Test with missing data scenarios
- Verify quality flows correctly
- Verify source_coverage_log receives events
- Verify future lookbacks handle low-quality data

---

## Context From Previous Session

### Verified Data Coverage (Oct 19, 2021 - Regular Season Start)
All primary sources have data:
- nbac_gamebook_player_stats: 67 records ✅
- nbac_team_boxscore: 8 records ✅
- bettingpros_player_points_props: 1,666 records ✅
- bigdataball_play_by_play: 983 records ✅
- bdl_player_boxscores: 51 records ✅

### Key Discovery
Player boxscores aggregate EXACTLY to team totals:
- GSW: Player sum = 121, Team boxscore = 121 ✓
- LAL: Player sum = 114, Team boxscore = 114 ✓

This proves we CAN create team stats from player stats as a fallback.

### Bootstrap Period
- Oct 19-25, 2021 (Days 0-6): Fill Phase 2+3, Phase 4 auto-skips
- Oct 26, 2021 onwards: Full processing

---

*This document prepared for handoff to new chat session focused on data fallback completeness.*
