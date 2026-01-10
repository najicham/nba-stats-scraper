# Data Flow: Player Name Resolution System

**Date:** 2026-01-10
**Purpose:** Document how player names flow through the system

---

## Overview Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 2: RAW DATA                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  NBA.com     │  │ BallDontLie  │  │    ESPN      │  │  Odds API    │   │
│  │  Gamebook    │  │    API       │  │   Boxscore   │  │   Props      │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                 │                 │            │
│         │ normalize_name_for_lookup()       │ local method    │ legacy     │
│         │ ✅                                │ ❌              │ ✅         │
│         │                 │                 │                 │            │
│         ▼                 ▼                 ▼                 ▼            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   player_lookup field created                        │   │
│  │           (e.g., "lebronjames", "tjmcconnell", "josealvarado")       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
└────────────────────────────────────┼────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PHASE 3: ANALYTICS                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PlayerGameSummaryProcessor.calculate_analytics()                           │
│                          │                                                  │
│                          ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                  RegistryReader.get_universal_ids_batch()            │   │
│  │                              │                                       │   │
│  │              ┌───────────────┼───────────────┐                       │   │
│  │              ▼               ▼               ▼                       │   │
│  │   ┌────────────────┐ ┌────────────────┐ ┌────────────────┐          │   │
│  │   │ player_aliases │ │ nba_players_   │ │ ai_resolution_ │          │   │
│  │   │     table      │ │   registry     │ │     cache      │          │   │
│  │   └───────┬────────┘ └───────┬────────┘ └───────┬────────┘          │   │
│  │           │                  │                  │                    │   │
│  │           ▼                  ▼                  ▼                    │   │
│  │      Found alias?      Valid player?      Cached MATCH?              │   │
│  │           │                  │                  │                    │   │
│  │     YES ──┼──────────► Return universal_player_id                    │   │
│  │           │                  │                  │                    │   │
│  │      NO ──┼───────► NO ─────┼───────► NO ─────┼──────────┐          │   │
│  │           │                  │                  │          │          │   │
│  └───────────┴──────────────────┴──────────────────┴──────────┼──────────┘   │
│                                                               │              │
│                                                               ▼              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    RESOLUTION FAILED                                 │   │
│  │                          │                                           │   │
│  │     ┌────────────────────┼────────────────────┐                     │   │
│  │     ▼                    ▼                    ▼                     │   │
│  │ unresolved_         registry_            Player data               │   │
│  │ player_names        failures             SKIPPED in                │   │
│  │ (pending)           (created_at)         output table              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Resolution Chain Detail

```
handle_player_name(input_name, source, game_context)
│
├─► Step 1: Empty/None Check
│   └─► Return None if empty
│
├─► Step 2: Alias Resolution
│   │   resolve_to_nba_name(input_name)
│   │       │
│   │       ├─► normalize_name_for_lookup(input_name)
│   │       │   └─► "T.J. McConnell" → "tjmcconnell"
│   │       │
│   │       └─► Query player_aliases table
│   │           SELECT nba_canonical_display
│   │           WHERE alias_lookup = 'tjmcconnell'
│   │
│   ├─► FOUND: Return canonical name ("T.J. McConnell")
│   └─► NOT FOUND: Continue
│
├─► Step 3: Registry Validation
│   │   is_valid_nba_player(resolved_name, season, team)
│   │       │
│   │       └─► Query nba_players_registry
│   │           WHERE player_lookup = 'tjmcconnell'
│   │           AND season = '2024-25'
│   │
│   ├─► VALID: Return resolved_name
│   └─► INVALID: Continue
│
├─► Step 4: AI Resolution Cache Lookup
│   │   if _use_resolution_cache and _resolution_cache:
│   │       cached = _resolution_cache.get_cached(normalized_lookup)
│   │       │
│   │       ├─► MATCH cached:
│   │       │   │   canonical = _get_canonical_display_name(cached.canonical_lookup)
│   │       │   │   create_alias_mapping(input_name → canonical)
│   │       │   └─► Return canonical name
│   │       │
│   │       ├─► DATA_ERROR cached:
│   │       │   └─► Return None (don't re-queue known bad name)
│   │       │
│   │       └─► NEW_PLAYER or None:
│   │           └─► Continue to Step 5
│   │
│   └─► Cache exception: Continue to Step 5
│
└─► Step 5: Add to Unresolved Queue
    │   add_to_unresolved_queue(source, input_name, game_context)
    │       │
    │       ├─► Insert/Update unresolved_player_names
    │       │   └─► status = 'pending', increment occurrences
    │       │
    │       └─► Return None (signals failure to caller)
    │
    └─► Caller (processor) adds to registry_failures table
```

---

## Nightly AI Resolution Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    4:30 AM ET - Cloud Scheduler Trigger                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  POST /resolve-pending → resolve_unresolved_batch.py                        │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Query: SELECT * FROM unresolved_player_names                        │   │
│  │         WHERE status = 'pending'                                     │   │
│  │         ORDER BY occurrences DESC                                    │   │
│  │         LIMIT @batch_size                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  For each pending name:                                              │   │
│  │      │                                                               │   │
│  │      ├─► Check ai_resolution_cache first                             │   │
│  │      │       │                                                       │   │
│  │      │       ├─► CACHED: Use cached decision (no API call)           │   │
│  │      │       └─► NOT CACHED: Continue                                │   │
│  │      │                                                               │   │
│  │      ├─► Build context:                                              │   │
│  │      │       - team_roster from nba_players_registry                 │   │
│  │      │       - similar_names (fuzzy match)                           │   │
│  │      │       - source, team_abbr, season                             │   │
│  │      │                                                               │   │
│  │      ├─► Call AINameResolver.resolve_single(context)                 │   │
│  │      │       │                                                       │   │
│  │      │       └─► Claude Haiku API call                               │   │
│  │      │           Returns: resolution_type, canonical_lookup,         │   │
│  │      │                    confidence, reasoning                      │   │
│  │      │                                                               │   │
│  │      └─► Process result:                                             │   │
│  │              │                                                       │   │
│  │              ├─► MATCH:                                              │   │
│  │              │       - Create alias in player_aliases                │   │
│  │              │       - Cache decision                                │   │
│  │              │       - Update registry_failures.resolved_at          │   │
│  │              │       - Update unresolved_player_names.status         │   │
│  │              │                                                       │   │
│  │              ├─► NEW_PLAYER:                                         │   │
│  │              │       - Cache decision                                │   │
│  │              │       - Mark as resolved (type=new_player_detected)   │   │
│  │              │                                                       │   │
│  │              └─► DATA_ERROR:                                         │   │
│  │                      - Cache decision                                │   │
│  │                      - Mark as resolved (type=data_error)            │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Summary: X names processed, Y aliases created, $Z.ZZ cost           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Reprocessing Flow (Now Working!)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Manual Trigger (or future: automated)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  python reprocess_resolved.py --resolved-since 2025-01-01                   │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Query: SELECT player_lookup, game_id, game_date, season             │   │
│  │         FROM registry_failures                                       │   │
│  │         WHERE resolved_at IS NOT NULL                                │   │
│  │           AND reprocessed_at IS NULL                                 │   │
│  │           AND resolved_at >= @since_date                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  For each affected game:                                             │   │
│  │      │                                                               │   │
│  │      ├─► PlayerGameSummaryProcessor.process_single_game()            │   │
│  │      │       │                                                       │   │
│  │      │       ├─► _extract_single_game_data(game_id)                  │   │
│  │      │       │       - Query Phase 2 data for this game only         │   │
│  │      │       │       - Parameterized query (safe)                    │   │
│  │      │       │                                                       │   │
│  │      │       ├─► _extract_player_shot_zones()                        │   │
│  │      │       │       - Get shot zone data for this game              │   │
│  │      │       │                                                       │   │
│  │      │       ├─► registry.get_universal_ids_batch()                  │   │
│  │      │       │       - NOW FINDS ALIAS (created by AI resolution)    │   │
│  │      │       │       - Returns universal_player_id                   │   │
│  │      │       │                                                       │   │
│  │      │       ├─► _process_single_player_game() for each player       │   │
│  │      │       │       - Calculate analytics                           │   │
│  │      │       │       - Build record with all fields                  │   │
│  │      │       │                                                       │   │
│  │      │       └─► _save_single_game_records()                         │   │
│  │      │               - MERGE to player_game_summary                  │   │
│  │      │               - Atomic upsert (no duplicates)                 │   │
│  │      │                                                               │   │
│  │      └─► On success:                                                 │   │
│  │              - Update registry_failures.reprocessed_at               │   │
│  │              - Log completion                                        │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Result: Player data now in player_game_summary!                     │   │
│  │          Downstream Phase 4/5 will pick it up on next run            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Table Relationships

```
┌─────────────────────────────┐
│  nba_players_registry       │ ◄─────────────────────────────────────────┐
│  (source of truth)          │                                           │
├─────────────────────────────┤                                           │
│  player_lookup (PK)         │                                           │
│  universal_player_id        │──────────────────────────────────────────┐│
│  full_name                  │                                          ││
│  team_abbr                  │                                          ││
│  games_played               │                                          ││
│  season                     │                                          ││
└─────────────────────────────┘                                          ││
         ▲                                                               ││
         │ validates against                                             ││
         │                                                               ││
┌─────────────────────────────┐      ┌─────────────────────────────┐    ││
│  player_aliases             │      │  ai_resolution_cache        │    ││
│  (name mappings)            │      │  (AI decisions)             │    ││
├─────────────────────────────┤      ├─────────────────────────────┤    ││
│  alias_lookup (PK)          │◄─────│  unresolved_lookup (PK)     │    ││
│  nba_canonical_lookup       │      │  resolved_to                │────┘│
│  nba_canonical_display      │      │  resolution_type            │     │
│  alias_type                 │      │  confidence                 │     │
│  created_by                 │      │  reasoning                  │     │
│  created_at                 │      │  used_count                 │     │
└─────────────────────────────┘      └─────────────────────────────┘     │
         ▲                                    ▲                          │
         │ creates alias                      │ caches decision          │
         │                                    │                          │
┌─────────────────────────────────────────────┴──────────────────────────┤
│                      AI Batch Resolution                                │
│                  (resolve_unresolved_batch.py)                         │
└─────────────────────────────────────────────────────────────────────────┘
         ▲
         │ reads pending
         │
┌─────────────────────────────┐      ┌─────────────────────────────┐
│  unresolved_player_names    │      │  registry_failures          │
│  (review queue)             │      │  (per-game failures)        │
├─────────────────────────────┤      ├─────────────────────────────┤
│  normalized_lookup (PK)     │◄────►│  player_lookup              │
│  original_name              │      │  game_id                    │
│  source                     │      │  game_date                  │
│  occurrences                │      │  team_abbr                  │
│  example_games[]            │      │  season                     │
│  status                     │      │  processor_name             │
│  resolution_type            │      │  created_at                 │
│  resolved_to_name           │      │  resolved_at ◄──────────────┤───┐
│  reviewed_at                │      │  reprocessed_at ◄───────────┤───┼─┐
└─────────────────────────────┘      └─────────────────────────────┘   │ │
         ▲                                    ▲                        │ │
         │ writes failures                    │ writes failures        │ │
         │                                    │                        │ │
┌────────┴────────────────────────────────────┴────────────────────────┤ │
│                    Phase 3 Analytics Processors                       │ │
│            (player_game_summary_processor.py, etc.)                  │ │
└─────────────────────────────────────────────────────────────────────┘ │ │
                                                                        │ │
┌───────────────────────────────────────────────────────────────────────┘ │
│                      AI Resolution marks resolved_at                    │
└─────────────────────────────────────────────────────────────────────────┘
                                                                          │
┌─────────────────────────────────────────────────────────────────────────┘
│                      Reprocessing marks reprocessed_at
└──────────────────────────────────────────────────────────────────────────
```

---

## State Machine: Registry Failure Lifecycle

```
                          ┌──────────────────┐
                          │                  │
                          │   Phase 3        │
                          │   Processing     │
                          │                  │
                          └────────┬─────────┘
                                   │
                                   │ Name resolution fails
                                   ▼
                    ┌──────────────────────────────┐
                    │                              │
                    │   PENDING                    │
                    │   created_at = NOW()         │
                    │   resolved_at = NULL         │
                    │   reprocessed_at = NULL      │
                    │                              │
                    └──────────────┬───────────────┘
                                   │
                                   │ AI resolution creates alias
                                   │ (4:30 AM batch or manual)
                                   ▼
                    ┌──────────────────────────────┐
                    │                              │
                    │   RESOLVED                   │
                    │   created_at = (unchanged)   │
                    │   resolved_at = NOW()        │
                    │   reprocessed_at = NULL      │
                    │                              │
                    └──────────────┬───────────────┘
                                   │
                                   │ reprocess_resolved.py runs
                                   │ (manual trigger)
                                   ▼
                    ┌──────────────────────────────┐
                    │                              │
                    │   REPROCESSED                │
                    │   created_at = (unchanged)   │
                    │   resolved_at = (unchanged)  │
                    │   reprocessed_at = NOW()     │
                    │                              │
                    └──────────────────────────────┘
                                   │
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │                              │
                    │   Data now in                │
                    │   player_game_summary        │
                    │                              │
                    └──────────────────────────────┘
```

---

## Files Reference

| Component | File Path | Purpose |
|-----------|-----------|---------|
| Name Resolver | `shared/utils/player_name_resolver.py` | Main resolution logic |
| Normalizer | `shared/utils/player_name_normalizer.py` | Standard normalization |
| Registry Reader | `shared/utils/player_registry/reader.py` | Batch ID lookups |
| Resolution Cache | `shared/utils/player_registry/resolution_cache.py` | Cache AI decisions |
| AI Resolver | `shared/utils/player_registry/ai_resolver.py` | Claude Haiku integration |
| Batch Resolution | `tools/player_registry/resolve_unresolved_batch.py` | Nightly batch job |
| Reprocessing | `tools/player_registry/reprocess_resolved.py` | Game reprocessing |
| PGS Processor | `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | Phase 3 analytics |
