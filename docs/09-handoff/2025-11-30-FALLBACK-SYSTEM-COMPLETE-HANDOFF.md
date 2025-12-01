# Data Fallback & Quality Tracking System - Complete Handoff

**Date:** 2025-11-30
**Session Duration:** ~4 hours
**Status:** PARTIAL IMPLEMENTATION - Core infrastructure complete, integration ongoing

---

## Executive Summary

This session designed and partially implemented a comprehensive data fallback and quality tracking system for the NBA Props Platform. The system ensures graceful handling of missing data sources, tracks data quality throughout the pipeline, and logs all fallback events for audit purposes.

**Key Accomplishments:**
- Designed complete fallback architecture with YAML config
- Created Python config loader and FallbackSourceMixin
- Fixed both critical hard fails in team processors
- Added reconstruction methods for team stats from player stats

**Remaining Work:**
- Schema standardization across Phase 3+ tables
- Integration into remaining processors
- Activation of source_coverage_log
- Testing and documentation

---

## Part 1: What Was Built

### 1.1 Configuration System

**Files Created:**

```
shared/config/data_sources/
├── __init__.py                    # Module exports
├── fallback_config.yaml           # Main config (447 lines)
└── loader.py                      # Python config loader (340 lines)
```

**fallback_config.yaml** contains:
- 17 data source definitions with quality scores
- 8 fallback chains with on_all_fail behaviors
- 5 quality tier definitions with confidence ceilings
- Quality propagation rules
- Reconstruction method definitions
- Manual remediation options
- Future source placeholders

**Key Config Sections:**

```yaml
sources:
  nbac_gamebook_player_stats:    # gold, 100
  bdl_player_boxscores:          # silver, 85
  espn_boxscores:                # silver, 80
  reconstructed_team_from_players:  # silver, 85 (virtual)
  # ... 13 more sources

fallback_chains:
  player_boxscores:   # nbac → bdl → espn, on_fail: skip
  team_boxscores:     # nbac → reconstruct → espn, on_fail: placeholder
  player_props:       # odds_api → bettingpros, on_fail: skip
  game_schedule:      # nbac → espn, on_fail: FAIL (critical)
  game_lines:         # odds_api only, on_fail: continue_without
  shot_zones:         # bigdataball → nbac_pbp, on_fail: continue_without
  injury_reports:     # nbac → bdl, on_fail: continue_without
  player_roster:      # nbac → bdl → br, on_fail: FAIL (critical)

quality_tiers:
  gold:     95-100, ceiling 1.00, eligible
  silver:   75-94,  ceiling 0.95, eligible
  bronze:   50-74,  ceiling 0.80, eligible
  poor:     25-49,  ceiling 0.60, eligible (flagged)
  unusable: 0-24,   ceiling 0.00, NOT eligible
```

**loader.py** provides:
- `DataSourceConfig` singleton class
- Typed dataclasses: `SourceConfig`, `FallbackChainConfig`, `QualityTierConfig`
- Methods: `get_source()`, `get_fallback_chain()`, `get_tier_from_score()`
- Validation and error handling

### 1.2 FallbackSourceMixin

**File:** `shared/processors/patterns/fallback_source_mixin.py` (280 lines)

**Key Features:**
- `try_fallback_chain()` - Main method to execute fallback logic
- `FallbackResult` dataclass with success/skip/placeholder states
- Automatic logging to source_coverage_log via QualityMixin
- Quality column builder helper

**Usage Pattern:**
```python
class MyProcessor(FallbackSourceMixin, QualityMixin, BaseProcessor):
    def extract_data(self):
        result = self.try_fallback_chain(
            chain_name='team_boxscores',
            extractors={
                'nbac_team_boxscore': lambda: self._query_nbac(),
                'reconstructed_team_from_players': lambda: self._reconstruct(),
            },
            context={'game_id': game_id, 'game_date': game_date},
        )

        if result.should_skip:
            return None
        if result.is_placeholder:
            return self._create_placeholder()

        # Use result.data, result.quality_tier, result.quality_score
```

### 1.3 Fixed Processors

#### team_defense_game_summary_processor.py

**Changes Made:**
1. Added imports for `FallbackSourceMixin` and `QualityMixin`
2. Added mixins to class inheritance (lines 55-56)
3. Replaced `raise ValueError` at line 192 with `try_fallback_chain()` (lines 193-233)
4. Added `_reconstruct_team_from_players()` method (lines 406-615, ~210 lines)

**Reconstruction Method:**
- Aggregates player stats from `nbac_gamebook_player_stats` + `bdl_player_boxscores`
- Creates defensive perspective (opponent's offense = team's defense)
- Calculates derived metrics (defensive rating, opponent pace, TS%)
- Verified 100% accurate (GSW 121=121, LAL 114=114)

#### team_offense_game_summary_processor.py

**Changes Made:**
1. Added imports for `FallbackSourceMixin` and `QualityMixin`
2. Added mixins to class inheritance (lines 55-56)
3. Refactored `extract_raw_data()` to use fallback chain (lines 203-244)
4. Split extraction into `_extract_from_nbac_team_boxscore()` method
5. Added `_reconstruct_team_from_players()` method (lines 312-427, ~115 lines)
6. Modified `validate_extracted_data()` to handle gracefully instead of raising (lines 386-411)

---

## Part 2: Design Documents Created

### 2.1 Main Design Document

**File:** `docs/08-projects/current/backfill/FALLBACK-SYSTEM-DESIGN.md`

Contains:
- Complete YAML config structure
- Schema standardization plan
- Python implementation details
- Processor change patterns
- Source coverage log integration
- Implementation timeline
- Verification queries

### 2.2 Data Source Catalog

**File:** `docs/08-projects/current/backfill/DATA-SOURCE-CATALOG.md`

Contains:
- All 39 scrapers inventoried
- All 21 Phase 2 raw tables documented
- Complete fallback matrix
- Scraper → table mapping
- Coverage percentages
- Resolved design questions

### 2.3 Original Task Document

**File:** `docs/08-projects/current/backfill/DATA-FALLBACK-COMPLETENESS-TASK.md`

The original task specification that drove this work.

---

## Part 3: What Remains To Do

### 3.1 Schema Standardization (Priority: HIGH)

**Goal:** Add standard quality columns to ALL Phase 3+ tables

**Standard Columns to Add:**
```sql
-- Core Quality Tracking
quality_tier STRING,                  -- 'gold', 'silver', 'bronze', 'poor', 'unusable'
quality_score FLOAT64,                -- 0-100
quality_issues ARRAY<STRING>,         -- ['backup_source_used', 'reconstructed']
data_sources ARRAY<STRING>,           -- ['nbac_gamebook', 'bdl_fallback']
is_production_ready BOOL,             -- Can be used for predictions?

-- Completeness Tracking (where applicable)
expected_games_count INT64,
actual_games_count INT64,
completeness_percentage FLOAT64,
missing_games_count INT64,
```

**Tables Needing Updates:**

| Table | Current State | Action Needed |
|-------|---------------|---------------|
| player_game_summary | Has BOTH `data_quality_tier` and `quality_tier` | Remove `data_quality_tier`, keep `quality_tier` |
| team_defense_game_summary | Has `data_quality_tier` only | Add new standard columns |
| team_offense_game_summary | Has `data_quality_tier` only | Add new standard columns |
| upcoming_player_game_context | Has `data_quality_tier` + completeness | Rename to `quality_tier` |
| upcoming_team_game_context | Missing quality tier entirely | Add `quality_tier`, `quality_score` |
| ml_feature_store_v2 | Has `feature_quality_score` | Add `quality_tier` |
| player_daily_cache | Has completeness only | Add `quality_tier`, `quality_score` |
| team_defense_zone_analysis | Has `data_quality_tier` + completeness | Rename to `quality_tier` |

**Migration Approach:**
1. Add new columns (don't remove old yet)
2. Update processors to populate both old and new
3. Verify data flows correctly
4. Deprecate old columns later

### 3.2 Remaining Processor Integration (Priority: MEDIUM)

**Processors Already Updated:**
- ✅ team_defense_game_summary_processor.py
- ✅ team_offense_game_summary_processor.py

**Processors Needing Updates:**

| Processor | Current Fallback | Action |
|-----------|------------------|--------|
| player_game_summary | Has manual fallback (good) | Add mixin, use standard pattern |
| upcoming_player_game_context | Has BettingPros fallback | Add mixin, standardize |
| upcoming_team_game_context | Has ESPN schedule fallback | Add mixin, standardize |

**For Each Processor:**
1. Add `FallbackSourceMixin` and `QualityMixin` to imports
2. Add mixins to class inheritance (BEFORE other mixins)
3. Replace manual fallback logic with `try_fallback_chain()`
4. Use `build_quality_columns_from_result()` for output

### 3.3 Source Coverage Log Activation (Priority: MEDIUM)

**Current State:**
- Schema exists: `nba_reference.source_coverage_log`
- QualityMixin exists with `log_quality_event()` method
- Only 1 event in table (basically unused)

**To Activate:**
1. Verify FallbackSourceMixin calls `log_quality_event()` correctly
2. Add context manager pattern to processors (`with self:`)
3. Test that events are being logged
4. Verify alert deduplication works

**Testing Queries:**
```sql
-- Check events are being logged
SELECT
  DATE(event_timestamp) as date,
  event_type,
  COUNT(*) as count
FROM `nba-props-platform.nba_reference.source_coverage_log`
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC;
```

### 3.4 Testing (Priority: HIGH before production)

**Test Scenarios:**
1. **Missing nbac_team_boxscore** - Verify reconstruction from players works
2. **Missing player props** - Verify skip behavior
3. **Missing schedule** - Verify hard fail (critical)
4. **Partial data** - Verify quality degradation tracked
5. **End-to-end** - Verify quality flows Phase 3 → 4 → 5

**Test Approach:**
- Create test fixtures with missing data
- Run processors and verify behavior
- Check source_coverage_log for events
- Verify quality columns populated correctly

---

## Part 4: Design Decisions Made

### 4.1 Approved Fallback Matrix

| Data Type | Primary | Fallback 1 | Fallback 2 | On All Fail |
|-----------|---------|------------|------------|-------------|
| Player Stats | nbac_gamebook (100) | bdl_boxscores (85) | espn (80) | skip |
| Team Stats | nbac_team_boxscore (100) | reconstruct (85) | espn (80) | placeholder |
| Player Props | odds_api (100) | bettingpros (90) | - | skip |
| Schedule | nbac_schedule (100) | espn_scoreboard (90) | - | **fail** |
| Game Lines | odds_api (100) | - | - | continue (-10) |
| Shot Zones | bigdataball (100) | nbac_pbp (85) | - | continue (-15) |
| Injuries | nbac_injury (100) | bdl_injuries (85) | - | continue (-5) |
| Rosters | nbac_player_list (100) | bdl_players (90) | br_rosters (85) | **fail** |

### 4.2 Quality Score Logic

```
Score = 100 - sum(penalties)

Penalties:
├── -15: First fallback source used
├── -20: Second fallback source used
├── -15: Reconstructed data
├── -15: Optional enhancement missing (shot zones)
├── -5:  Minor optional data missing (injuries)
└── -15: Thin sample size
```

### 4.3 on_all_fail Actions

| Action | Behavior | Use Case |
|--------|----------|----------|
| `skip` | Don't process entity, continue | Player without props |
| `placeholder` | Create record with unusable tier | Track that we tried |
| `fail` | Raise exception | Critical data (schedule) |
| `continue_without` | Process with degraded quality | Optional data (shot zones) |

### 4.4 PBP Reconstruction Decision

**Decision:** NOT automatic fallback

**Rationale:**
- Some stats unreliable (rebounds 85%, assists 80%)
- Better suited for manual remediation
- Config includes `remediation_options` for manual triggers
- Current approach: PBP for enhancement (shot zones), not replacement

---

## Part 5: Research Findings

### 5.1 Data Sources Inventoried

- **39 scrapers** across 7 data sources
- **21 Phase 2 raw tables** documented
- **5 Phase 3 analytics processors** analyzed
- **6 Phase 4 precompute processors** analyzed

### 5.2 Player Registry System

The player registry already has its own fallback logic:
- ESPN: 30-day fallback window
- NBA.com: 7-day fallback window
- Basketball Reference: Similar pattern

This is **complementary** to our data source fallback system.

### 5.3 Unused Data Sources

Three data types are collected but not consumed:
- **Referee assignments** - Placeholders exist, marked "deferred"
- **Standings** - Explicit "No dependencies yet" comment
- **Player movement** - No future plans documented

---

## Part 6: File Inventory

### 6.1 New Files Created

```
shared/config/data_sources/
├── __init__.py                    # 45 lines - Module exports
├── fallback_config.yaml           # 447 lines - Main config
└── loader.py                      # 340 lines - Python config loader

shared/processors/patterns/
└── fallback_source_mixin.py       # 280 lines - Fallback mixin

docs/08-projects/current/backfill/
├── FALLBACK-SYSTEM-DESIGN.md      # Architecture doc
└── DATA-SOURCE-CATALOG.md         # All sources & fallbacks

docs/09-handoff/
└── 2025-11-30-FALLBACK-SYSTEM-COMPLETE-HANDOFF.md  # This file
```

### 6.2 Files Modified

```
data_processors/analytics/team_defense_game_summary/
└── team_defense_game_summary_processor.py
    - Added imports (lines 47-49)
    - Added mixins to class (lines 55-56)
    - Replaced hard fail with fallback chain (lines 193-233)
    - Added _reconstruct_team_from_players() (lines 406-615)

data_processors/analytics/team_offense_game_summary/
└── team_offense_game_summary_processor.py
    - Added imports (lines 47-49)
    - Added mixins to class (lines 55-56)
    - Refactored extract_raw_data() (lines 203-244)
    - Added _extract_from_nbac_team_boxscore() (lines 246-310)
    - Added _reconstruct_team_from_players() (lines 312-427)
    - Modified validate_extracted_data() (lines 386-411)
```

### 6.3 Existing Files Referenced (Not Modified)

```
shared/processors/patterns/quality_mixin.py     # Existing - provides log_quality_event()
shared/config/source_coverage/__init__.py       # Existing - quality tier enums
schemas/bigquery/nba_reference/source_coverage_log.sql  # Existing - event log schema
```

---

## Part 7: How to Continue

### Option 1: Schema Standardization Session

**Prompt for new session:**
```
Continue implementing the data fallback system. Focus on schema standardization.

Context:
- Config created: shared/config/data_sources/fallback_config.yaml
- Mixin created: shared/processors/patterns/fallback_source_mixin.py
- Two processors fixed: team_defense, team_offense

Task: Standardize quality columns across all Phase 3+ BigQuery schemas.

Read docs/09-handoff/2025-11-30-FALLBACK-SYSTEM-COMPLETE-HANDOFF.md for full context.

Tables to update:
1. nba_analytics.team_defense_game_summary - add quality_tier, quality_score, quality_issues
2. nba_analytics.team_offense_game_summary - add quality_tier, quality_score, quality_issues
3. nba_analytics.upcoming_team_game_context - add quality_tier, quality_score
4. Rename data_quality_tier → quality_tier where applicable
```

### Option 2: Processor Integration Session

**Prompt for new session:**
```
Continue implementing the data fallback system. Focus on processor integration.

Context:
- Config created: shared/config/data_sources/fallback_config.yaml
- Mixin created: shared/processors/patterns/fallback_source_mixin.py
- Two processors fixed: team_defense, team_offense

Task: Integrate FallbackSourceMixin into remaining Phase 3 processors.

Read docs/09-handoff/2025-11-30-FALLBACK-SYSTEM-COMPLETE-HANDOFF.md for full context.

Processors to update:
1. player_game_summary_processor.py
2. upcoming_player_game_context_processor.py
3. upcoming_team_game_context_processor.py
```

### Option 3: Testing Session

**Prompt for new session:**
```
Continue implementing the data fallback system. Focus on testing.

Context:
- Config created: shared/config/data_sources/fallback_config.yaml
- Mixin created: shared/processors/patterns/fallback_source_mixin.py
- Two processors fixed: team_defense, team_offense

Task: Test the fallback system with missing data scenarios.

Read docs/09-handoff/2025-11-30-FALLBACK-SYSTEM-COMPLETE-HANDOFF.md for full context.

Test scenarios:
1. Run team_defense with missing nbac_team_boxscore data
2. Verify reconstruction method produces correct output
3. Verify source_coverage_log receives events
4. Verify quality columns are populated
```

---

## Part 8: Documentation Updates Needed

### 8.1 New Documentation to Create

| Document | Location | Purpose |
|----------|----------|---------|
| Fallback System Guide | `docs/05-development/guides/fallback-system.md` | Developer guide for using fallback mixin |
| Quality Column Reference | `docs/06-reference/quality-columns.md` | Standard quality columns reference |

### 8.2 Existing Documentation to Update

| Document | Update Needed |
|----------|---------------|
| `docs/06-reference/data-sources/02-fallback-strategies.md` | Add reference to new config system |
| `docs/01-architecture/source-coverage/01-core-design.md` | Add implementation status |
| `docs/05-development/guides/processor-development.md` | Add FallbackSourceMixin usage |

### 8.3 Suggested Fallback System Guide Outline

```markdown
# Fallback System Developer Guide

## Overview
- Purpose of the fallback system
- When to use fallbacks vs fail

## Configuration
- fallback_config.yaml structure
- How to add new sources
- How to add new fallback chains

## Using FallbackSourceMixin
- Adding to processor
- try_fallback_chain() usage
- Handling FallbackResult
- Building quality columns

## Quality Tracking
- Quality tiers explained
- Quality score calculation
- is_production_ready logic

## Source Coverage Log
- When events are logged
- How to query events
- Alert deduplication

## Testing
- Test fixtures for missing data
- Verification queries
```

---

## Part 9: Open Questions

### 9.1 Questions for Future Sessions

1. **ESPN team boxscore extraction**: The config includes `espn_team_boxscore` as a fallback, but there's no extraction method implemented yet. Need to add `_extract_from_espn()` to both team processors.

2. **Quality column migration**: Should we run a migration to backfill quality columns for existing data? Or only apply to new data going forward?

3. **Confidence ceiling enforcement**: The config defines confidence ceilings by tier, but Phase 5 worker may not be reading from config yet. Need to verify integration.

4. **Circuit breaker interaction**: The fallback system and circuit breaker both handle failures. Need to ensure they don't conflict.

### 9.2 Potential Future Enhancements

1. **Admin dashboard**: Visualize quality distribution across tables
2. **Automatic remediation**: Trigger backfills for low-quality data
3. **Quality alerts**: Slack notifications when quality degrades
4. **Trend analysis**: Track quality over time

---

## Part 10: Quick Reference

### Key Commands

```python
# Load config
from shared.config.data_sources import DataSourceConfig
config = DataSourceConfig()

# Get source info
source = config.get_source('nbac_team_boxscore')
print(f"{source.quality_tier}: {source.quality_score}")

# Get fallback chain
chain = config.get_fallback_chain('team_boxscores')
print(f"Sources: {chain.sources}")

# Convert score to tier
tier = config.get_tier_from_score(85)  # 'silver'

# Check prediction eligibility
eligible = config.is_prediction_eligible('bronze')  # True
```

### Key File Paths

```
# Config
shared/config/data_sources/fallback_config.yaml

# Mixin
shared/processors/patterns/fallback_source_mixin.py

# Fixed processors
data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py
data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py

# Design docs
docs/08-projects/current/backfill/FALLBACK-SYSTEM-DESIGN.md
docs/08-projects/current/backfill/DATA-SOURCE-CATALOG.md
```

### Verification Query

```sql
-- Check if fallback system is working
SELECT
  event_type,
  severity,
  primary_source,
  resolution,
  COUNT(*) as count
FROM `nba-props-platform.nba_reference.source_coverage_log`
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1, 2, 3, 4
ORDER BY count DESC;
```

---

*End of handoff document. Session completed 2025-11-30.*
