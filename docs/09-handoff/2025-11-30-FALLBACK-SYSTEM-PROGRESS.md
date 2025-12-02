# Fallback System Implementation Progress

**Date:** 2025-11-30
**Status:** IN PROGRESS - Core infrastructure complete, processor updates pending

---

## What Was Done This Session

### 1. Research & Design (Complete)

- Inventoried all 39 scrapers across 7 data sources
- Mapped all 21 Phase 2 raw tables
- Documented current fallback implementations in all Phase 3 processors
- Identified hard fails that need fixing
- Researched player registry system (has its own fallback logic)
- Researched PBP reconstruction feasibility

### 2. Design Documents Created

| Document | Path | Purpose |
|----------|------|---------|
| System Design | `docs/08-projects/current/backfill/FALLBACK-SYSTEM-DESIGN.md` | Complete architecture |
| Data Catalog | `docs/08-projects/current/backfill/DATA-SOURCE-CATALOG.md` | All sources & fallbacks |

### 3. Implementation Files Created

| File | Path | Purpose |
|------|------|---------|
| Config YAML | `shared/config/data_sources/fallback_config.yaml` | Source definitions, chains, quality rules |
| Config Loader | `shared/config/data_sources/loader.py` | Python singleton to read config |
| Module Init | `shared/config/data_sources/__init__.py` | Public exports |
| Fallback Mixin | `shared/processors/patterns/fallback_source_mixin.py` | Mixin for processors |

---

## Approved Design Decisions

### Fallback Matrix

| Data Type | Primary | Fallback 1 | Fallback 2 | On All Fail |
|-----------|---------|------------|------------|-------------|
| Player Stats | nbac_gamebook (100) | bdl_boxscores (85) | espn_boxscores (80) | skip |
| Team Stats | nbac_team_boxscore (100) | reconstruct (85) | espn (80) | placeholder |
| Player Props | odds_api (100) | bettingpros (90) | - | skip |
| Schedule | nbac_schedule (100) | espn_scoreboard (90) | - | fail |
| Game Lines | odds_api (100) | - | - | continue (-10) |
| Shot Zones | bigdataball (100) | nbac_pbp (85) | - | continue (-15) |
| Injuries | nbac_injury (100) | bdl_injuries (85) | - | continue (-5) |
| Rosters | nbac_player_list (100) | bdl_players (90) | br_rosters (85) | fail |

### Quality Scoring

| Score Range | Tier | Confidence Cap | Prediction Eligible |
|-------------|------|----------------|---------------------|
| 95-100 | gold | 100% | Yes |
| 75-94 | silver | 95% | Yes |
| 50-74 | bronze | 80% | Yes |
| 25-49 | poor | 60% | Yes |
| 0-24 | unusable | 0% | No |

### PBP Reconstruction

- **NOT** automatic fallback (some stats unreliable)
- Manual remediation option with `requires_manual_decision: true`
- Documented which stats CAN be reconstructed at what accuracy

---

## What Remains To Do

### Phase 1: Fix Hard Fails (Priority: HIGH) - COMPLETED

1. **team_defense_game_summary_processor.py** ✅ DONE
   - Added `FallbackSourceMixin` and `QualityMixin` to class
   - Replaced `raise ValueError` with `try_fallback_chain('team_boxscores', ...)`
   - Added `_reconstruct_team_from_players()` method (200+ line SQL)

2. **team_offense_game_summary_processor.py** ✅ DONE
   - Added `FallbackSourceMixin` and `QualityMixin` to class
   - Replaced hard fail with fallback chain
   - Added reconstruction method
   - Converted `validate_extracted_data()` to graceful handling

### Phase 2: Integrate Mixin into Processors

Update each Phase 3 processor to:
1. Inherit from `FallbackSourceMixin`
2. Replace hard-coded fallback logic with `try_fallback_chain()`
3. Use `build_quality_columns_from_result()` for quality columns

Processors to update:
- [ ] `player_game_summary_processor.py`
- [ ] `team_defense_game_summary_processor.py`
- [ ] `team_offense_game_summary_processor.py`
- [ ] `upcoming_player_game_context_processor.py`
- [ ] `upcoming_team_game_context_processor.py`

### Phase 3: Schema Standardization

Add missing columns to Phase 3 tables:
- [ ] `quality_tier` (standardize from `data_quality_tier`)
- [ ] `quality_score`
- [ ] `quality_issues` (ARRAY)
- [ ] `data_sources` (ARRAY)
- [ ] `is_production_ready`
- [ ] Completeness fields where missing
- [ ] Circuit breaker fields where missing

### Phase 4: Activate source_coverage_log

- [ ] Verify `QualityMixin` is inherited by all processors
- [ ] Add context manager pattern (`with self:`) for auto-flush
- [ ] Test events are being logged
- [ ] Verify alert deduplication

### Phase 5: Testing

- [ ] Test with missing data scenarios
- [ ] Verify fallback chains work correctly
- [ ] Verify quality propagates through pipeline
- [ ] End-to-end test with backfill

---

## How to Continue

### Option 1: Continue in Same Session
If context allows, continue with fixing the hard fails:

```python
# In team_defense_game_summary_processor.py, replace line 192 with:
result = self.try_fallback_chain(
    chain_name='team_boxscores',
    extractors={
        'nbac_team_boxscore': lambda: self._extract_opponent_offense(game_id),
        'reconstructed_team_from_players': lambda: self._reconstruct_team_from_players(game_id),
    },
    context={'game_id': game_id, 'game_date': game_date},
)

if result.should_skip or result.is_placeholder:
    return self._create_placeholder_record(game_id, game_date, result.quality_issues)

opponent_offense_df = result.data
```

### Option 2: New Session
Start new session with this prompt:

```
Continue implementing the data fallback system. Core infrastructure is complete:
- Config: shared/config/data_sources/fallback_config.yaml
- Loader: shared/config/data_sources/loader.py
- Mixin: shared/processors/patterns/fallback_source_mixin.py

Next steps:
1. Fix hard fail in team_defense_game_summary_processor.py line 192
2. Fix hard fail in team_offense_game_summary_processor.py line 397
3. Integrate FallbackSourceMixin into all Phase 3 processors
4. Standardize quality columns across schemas

Read docs/09-handoff/2025-11-30-FALLBACK-SYSTEM-PROGRESS.md for full context.
```

---

## File Locations Summary

```
shared/config/data_sources/
├── __init__.py              # Module exports
├── fallback_config.yaml     # Main config (sources, chains, quality)
└── loader.py                # DataSourceConfig singleton

shared/processors/patterns/
├── fallback_source_mixin.py # FallbackSourceMixin (NEW)
├── quality_mixin.py         # QualityMixin (existing)
└── ...

docs/08-projects/current/backfill/
├── FALLBACK-SYSTEM-DESIGN.md    # Architecture doc
├── DATA-SOURCE-CATALOG.md       # All sources & fallbacks
└── DATA-FALLBACK-COMPLETENESS-TASK.md  # Original task
```

---

## Key Classes & Usage

### DataSourceConfig

```python
from shared.config.data_sources import DataSourceConfig

config = DataSourceConfig()
source = config.get_source('nbac_team_boxscore')
chain = config.get_fallback_chain('team_boxscores')
tier = config.get_tier_from_score(85)  # 'silver'
```

### FallbackSourceMixin

```python
from shared.processors.patterns.fallback_source_mixin import FallbackSourceMixin

class MyProcessor(FallbackSourceMixin, QualityMixin, BaseProcessor):
    def extract_data(self):
        result = self.try_fallback_chain(
            chain_name='team_boxscores',
            extractors={...},
            context={...},
        )
        # Handle result.success, result.should_skip, result.is_placeholder
```

---

*Session ended with ~54% context used. Good progress on infrastructure, processor updates remain.*
