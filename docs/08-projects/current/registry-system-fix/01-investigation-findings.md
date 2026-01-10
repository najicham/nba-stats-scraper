# Investigation Findings: Player Name Registry System

**Date:** 2026-01-10
**Investigator:** Claude Code (Opus 4.5)
**Scope:** Complete analysis of name resolution lifecycle

## Executive Summary

A comprehensive investigation of the player name registry system revealed:

1. **Critical Bug (FIXED)**: `process_single_game()` method didn't exist, breaking all reprocessing
2. **Normalization Inconsistency**: 10+ scrapers use different name normalization implementations
3. **Automation Gap**: No automatic reprocessing after alias creation
4. **Data Recovery Path**: Now functional after implementing missing method

---

## 1. Phase 2 Scrapers Analysis

### Normalization Methods by Source

| Source | Scraper/Processor | Method | Diacritics | Periods | Status |
|--------|-------------------|--------|------------|---------|--------|
| NBA.com Gamebook | `nbac_gamebook_processor.py` | `normalize_name_for_lookup()` | ✅ | ✅ | **GOOD** |
| NBA.com Boxscore | `nbac_player_boxscore_processor.py` | Local `normalize_player_name()` | ❌ | ❌ | Needs fix |
| NBA.com PBP | `nbac_play_by_play_processor.py` | Local `normalize_player_name()` | ❌ | ❌ | Needs fix |
| NBA.com Injury | `nbac_injury_report_processor.py` | Local `_normalize_player_name()` | ❌ | ⚠️ | Needs fix |
| NBA.com Player List | `nbac_player_list_processor.py` | Local `_normalize_player_name()` | ✅ | ⚠️ | Partial |
| BDL Boxscores | `bdl_player_box_scores_processor.py` | Local `normalize_player_name()` | ❌ | ❌ | Needs fix |
| BDL Live | `bdl_live_boxscores_processor.py` | Local `normalize_player_name()` | ❌ | ❌ | Needs fix |
| BDL Active | `bdl_active_players_processor.py` | `normalize_name()` (legacy) | ✅ | ✅ | Legacy |
| ESPN Boxscore | `espn_boxscore_processor.py` | Local `normalize_player_name()` | ❌ | ❌ | Needs fix |
| ESPN Roster | `espn_team_roster_processor.py` | Local `_normalize_player_name()` | ❌ | ❌ | Needs fix |
| Odds API | `odds_api_props_processor.py` | `normalize_name()` (legacy) | ✅ | ✅ | Legacy |
| BettingPros | `bettingpros_player_props_processor.py` | Local `normalize_player_name()` | ❌ | ❌ | Needs fix |
| BigDataBall | `bigdataball_pbp_processor.py` | Local `normalize_player_name()` | ❌ | ❌ | Needs fix |

### Recommended Standard: `normalize_name_for_lookup()`

**File:** `shared/utils/player_name_normalizer.py`

```python
def normalize_name_for_lookup(name: str) -> str:
    # 1. Lowercase
    # 2. Remove diacritics (ā → a, é → e) via NFD normalization
    # 3. Remove: spaces, hyphens, apostrophes, periods, commas, underscores
    # 4. Remove remaining non-alphanumeric
    # Result: "LeBron James Jr." → "lebronjamesjr"
```

**Why this is correct:**
- Handles international names (José → jose)
- Handles periods (T.J. → tj)
- Handles suffixes consistently (Jr. → jr)
- Used by the reference player name resolver

---

## 2. Registry Population Analysis

### How Players Enter the Registry

```
Source              Timing              Authority           Creates When
─────────────────────────────────────────────────────────────────────────
RosterRegistryProcessor   Morning (pre-game)    Team only if games=0    Player on roster
GamebookRegistryProcessor Evening (post-game)   Full authority          Player in boxscore
```

### Critical Race Condition

```
Player signs day of game
    ↓
Boxscore processed (evening)
    ↓ Player not yet in roster sources
Name resolution FAILS
    ↓
registry_failures created
    ↓
[Next day] Roster sources update
    ↓
AI resolution creates alias
    ↓
[MANUAL] Reprocessing required ← Gap here
```

### Bootstrap Period

New players have a 14-day bootstrap period before predictions:
- `min_games_required: 3`
- `min_days_in_league: 14`
- During bootstrap: predictions skipped

---

## 3. Name Resolution Failure Scenarios

### Scenario 1: Suffix Variations

| Input | Registry | Normalized Input | Registry Normalized | Match? |
|-------|----------|------------------|---------------------|--------|
| Charlie Brown Jr. | Charlie Brown | charliebrownjr | charliebrown | ❌ |
| LeBron James | LeBron James Jr. | lebronjames | lebronjamesjr | ❌ |

**Recovery:** AI creates alias mapping

### Scenario 2: Period Handling

| Input | Normalized (old) | Normalized (new) | Issue |
|-------|------------------|------------------|-------|
| T.J. McConnell | t.j.mcconnell | tjmcconnell | Old scrapers keep periods |
| P.J. Tucker | p.j.tucker | pjtucker | Same issue |

**Recovery:** AI creates alias or fix normalization

### Scenario 3: Diacritics

| Input | Without NFD | With NFD | Issue |
|-------|-------------|----------|-------|
| José Alvarado | josalvarado | josealvarado | Accent stripped wrong |
| Dāvis Bertāns | dvisberts | davisbertans | Macron handling |

**Recovery:** Proper NFD normalization in all scrapers

### Scenario 4: New Players

| Scenario | Detection | Action |
|----------|-----------|--------|
| Draft pick | Not in registry | AI marks as NEW_PLAYER |
| Mid-season trade | Not in registry | Same |
| G-League callup | Not in registry | Same |

**Recovery:** Wait for roster update, then alias if needed

### Scenario 5: Typos in Source Data

| Input | AI Decision | Action |
|-------|-------------|--------|
| Leborn James | DATA_ERROR | Cached, won't re-queue |
| Stephne Curry | DATA_ERROR | Same |

**Recovery:** Fix source data, clear cache entry

---

## 4. Tables Involved in Resolution

### `nba_reference.nba_players_registry`
- Canonical player list
- Source of truth for valid players
- Updated by Roster and Gamebook processors

### `nba_reference.player_aliases`
- Maps variant names to canonical names
- Created by AI resolution or manual entry
- Used first in resolution chain

### `nba_reference.unresolved_player_names`
- Manual review queue
- Status: pending, resolved, invalid, ignored
- Contains `example_games` array for reprocessing

### `nba_reference.ai_resolution_cache`
- Caches AI decisions
- Types: MATCH, NEW_PLAYER, DATA_ERROR
- Prevents repeated API calls

### `nba_processing.registry_failures`
- Per-game, per-player failures
- Tracks: created_at, resolved_at, reprocessed_at
- Lifecycle: PENDING → RESOLVED → REPROCESSED

---

## 5. Recovery Flow Analysis

### Current Flow (After Fixes)

```
Day 1: Name fails during processing
├─ registry_failures created (resolved_at=NULL)
├─ unresolved_player_names created (status='pending')
└─ Player data SKIPPED in player_game_summary

Night: AI resolution runs (4:30 AM scheduler)
├─ Checks ai_resolution_cache first
├─ If not cached: calls Claude Haiku
├─ Creates alias in player_aliases
├─ Caches decision in ai_resolution_cache
├─ Marks registry_failures.resolved_at
└─ Marks unresolved_player_names.status='resolved'

Day 2+: Manual reprocessing (NOW WORKS!)
├─ python reprocess_resolved.py --resolved-since <date>
├─ Finds games from registry_failures WHERE resolved_at IS NOT NULL
├─ Calls process_single_game() for each game
├─ Re-extracts Phase 2 data for that game
├─ Registry lookup NOW SUCCEEDS (alias exists)
├─ Writes to player_game_summary via MERGE
└─ Marks registry_failures.reprocessed_at
```

### What Was Broken

```python
# reprocess_resolved.py line 189 (BEFORE FIX)
result = processor.process_single_game(game_id, game_date, season)
# ↑ This method DID NOT EXIST
# Always threw AttributeError, caught silently at line 196-198

# NOW (AFTER FIX)
# Method exists, ~320 lines of implementation added
```

---

## 6. Automation Status

| Component | Automated? | Trigger | Notes |
|-----------|------------|---------|-------|
| Phase 2 scraping | ✅ Yes | Cloud Scheduler | Multiple jobs |
| Phase 3 processing | ✅ Yes | Pub/Sub | After Phase 2 |
| AI resolution | ✅ Yes | Cloud Scheduler 4:30 AM | Needs deployment |
| Reprocessing | ❌ **NO** | Manual CLI | **Gap** |
| Health monitoring | ❌ **NO** | Manual CLI | **Gap** |

---

## 7. Key Findings Summary

### Fixed This Session
1. **`process_single_game()` implemented** - Reprocessing now works
2. **Date conversion bug fixed** - `reprocess_game()` passes string not date object
3. **DATA_ERROR handling added** - Known bad names don't re-queue

### Still Needs Work
1. **Auto-reprocessing** - Should trigger after AI creates alias
2. **Scraper standardization** - 10+ files need to use `normalize_name_for_lookup()`
3. **Health alerts** - No automatic alerting for stale records
4. **Manual alias gap** - `resolve_unresolved_names.py` doesn't update registry_failures

### Risks
1. **Name mismatches** - Different normalization across sources
2. **Silent failures** - No alerts when reprocessing doesn't happen
3. **Cache poisoning** - Bad AI decisions persist forever
4. **Orphaned records** - Can get stuck in resolved-not-reprocessed state

---

## 8. Files Analyzed

### Core Resolution
- `shared/utils/player_name_resolver.py` (312 lines)
- `shared/utils/player_name_normalizer.py` (240 lines)
- `shared/utils/player_registry/reader.py` (800+ lines)
- `shared/utils/player_registry/resolver.py` (400+ lines)
- `shared/utils/player_registry/resolution_cache.py` (200+ lines)

### Registry Processors
- `data_processors/reference/player_reference/roster_registry_processor.py` (1000+ lines)
- `data_processors/reference/player_reference/gamebook_registry_processor.py` (1000+ lines)

### Analytics Processor
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` (1800+ lines)

### Tools
- `tools/player_registry/resolve_unresolved_batch.py` (400+ lines)
- `tools/player_registry/resolve_unresolved_names.py` (900+ lines)
- `tools/player_registry/reprocess_resolved.py` (400+ lines)

### Phase 2 Scrapers (13 files analyzed)
- Various in `data_processors/raw/nbacom/`
- Various in `data_processors/raw/balldontlie/`
- Various in `data_processors/raw/espn/`
- Various in `data_processors/raw/oddsapi/`
- Various in `data_processors/raw/bettingpros/`
- Various in `data_processors/raw/bigdataball/`
