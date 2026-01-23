# Player Registry Auto-Resolution Pipeline

**Date Started:** 2026-01-22
**Last Updated:** 2026-01-22
**Status:** Planning
**Priority:** High
**Related Project:** [registry-system-fix](../registry-system-fix/) (2026-01-10)

## Executive Summary

Despite previous fixes in January 2026, the player registry has accumulated **2,835 unresolved players**. The root cause is that while the AI resolution infrastructure exists, it is not being triggered automatically at scale. This project designs and implements a fully automated resolution pipeline that eliminates manual intervention for the majority of cases.

## Problem Statement

### Current State (2026-01-22)

| Metric | Value | Impact |
|--------|-------|--------|
| Unresolved players | 2,835 | Predictions cannot be generated |
| Registry status | "pending" | Awaiting manual review |
| Auto-resolution rate | 0% | AI resolver exists but isn't triggered |
| Manual review required | 100% | Unsustainable at scale |

### Root Causes

1. **AI Resolution Not Auto-Triggered**: The `ai_resolver.py` module is fully implemented but never called automatically in the pipeline
2. **No Automatic Reprocessing**: After resolution, historical games aren't reprocessed
3. **Limited Game Tracking**: Only 10 example games tracked per unresolved player
4. **New Data Sources**: ESPN, BettingPros add name variations not in registry
5. **Encoding Variations**: Special characters, accents cause mismatches

## Project Goals

| Goal | Success Metric |
|------|----------------|
| Reduce manual review to <5% of cases | Auto-resolve >95% of new unresolved names |
| Automatic backfill after resolution | 100% of affected games reprocessed within 24h |
| Real-time visibility | Daily Slack summary of resolution activity |
| Zero prediction gaps due to registry | All players with prop lines have predictions |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUTOMATED PLAYER RESOLUTION PIPELINE                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 2: Raw Data Ingestion                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Scrapers (ESPN, BDL, BettingPros, NBA.com)                         │   │
│  │  → Extract player names                                              │   │
│  │  → Normalize names (lowercase, remove special chars)                 │   │
│  │  → Write to raw tables                                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                         │
│  PHASE 3: Analytics Processing                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  PlayerGameSummaryProcessor                                          │   │
│  │  ┌─────────────────────────────────────────────────────────────┐    │   │
│  │  │  1. Registry Lookup (nba_players_registry)                   │    │   │
│  │  │     └─ FOUND → universal_player_id → continue processing     │    │   │
│  │  │     └─ NOT FOUND → Step 2                                    │    │   │
│  │  │                                                               │    │   │
│  │  │  2. Alias Resolution (player_aliases)                         │    │   │
│  │  │     └─ FOUND → canonical_lookup → universal_player_id        │    │   │
│  │  │     └─ NOT FOUND → Step 3                                    │    │   │
│  │  │                                                               │    │   │
│  │  │  3. AI Cache Lookup (ai_resolution_cache)                     │    │   │
│  │  │     └─ HIT (MATCH) → create alias → continue                 │    │   │
│  │  │     └─ HIT (DATA_ERROR) → skip, log as invalid               │    │   │
│  │  │     └─ MISS → Step 4                                         │    │   │
│  │  │                                                               │    │   │
│  │  │  4. Log as Unresolved                                         │    │   │
│  │  │     └─ Write to unresolved_player_names                      │    │   │
│  │  │     └─ Track example_games (up to 10)                        │    │   │
│  │  │     └─ Write to registry_failures                            │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                         │
│  NIGHTLY AUTO-RESOLUTION (3:00 AM ET) - NEW                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  AutoResolutionPipeline                                              │   │
│  │                                                                       │   │
│  │  Stage 1: HIGH CONFIDENCE (Fuzzy Match ≥95%)                        │   │
│  │  ┌───────────────────────────────────────────────────────────────┐  │   │
│  │  │  • Query unresolved with status='pending'                      │  │   │
│  │  │  • For each: fuzzy match against registry                      │  │   │
│  │  │  • If score ≥95% AND same team/season:                        │  │   │
│  │  │    └─ Auto-create alias                                        │  │   │
│  │  │    └─ Mark status='resolved', resolution_method='fuzzy_auto'   │  │   │
│  │  │    └─ Log to resolution_audit_log                              │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  │                                                                       │   │
│  │  Stage 2: MEDIUM CONFIDENCE (AI Resolution)                          │   │
│  │  ┌───────────────────────────────────────────────────────────────┐  │   │
│  │  │  • Remaining unresolved from Stage 1                           │  │   │
│  │  │  • Call ai_resolver.resolve_batch() with context:              │  │   │
│  │  │    - unresolved_lookup                                         │  │   │
│  │  │    - team_roster for that season                               │  │   │
│  │  │    - similar_names from registry                               │  │   │
│  │  │  • If AI confidence ≥80%:                                      │  │   │
│  │  │    └─ MATCH: Create alias, mark resolved                       │  │   │
│  │  │    └─ NEW_PLAYER: Create registry entry                        │  │   │
│  │  │    └─ DATA_ERROR: Mark as 'invalid'                            │  │   │
│  │  │  • Cache all decisions in ai_resolution_cache                  │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  │                                                                       │   │
│  │  Stage 3: LOW CONFIDENCE (Queue for Review)                          │   │
│  │  ┌───────────────────────────────────────────────────────────────┐  │   │
│  │  │  • AI confidence <80% or conflicting signals                   │  │   │
│  │  │  • Mark status='needs_review'                                  │  │   │
│  │  │  • Add to daily Slack summary                                  │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                         │
│  AUTO-REPROCESSING (3:30 AM ET) - NEW                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ReprocessingOrchestrator                                            │   │
│  │                                                                       │   │
│  │  1. Query newly resolved players (resolved_at > last_run)            │   │
│  │                                                                       │   │
│  │  2. For each resolved player:                                        │   │
│  │     ├─ Find ALL affected games (not just 10 examples)                │   │
│  │     │  Query: registry_failures WHERE player_lookup = X              │   │
│  │     │  Query: raw tables for historical occurrences                  │   │
│  │     │                                                                 │   │
│  │     ├─ Sort games by date DESCENDING (newest first)                  │   │
│  │     │  Rationale: Recent games more important for predictions        │   │
│  │     │                                                                 │   │
│  │     └─ Reprocess each game:                                          │   │
│  │        PlayerGameSummaryProcessor.process_single_game(game_id)       │   │
│  │                                                                       │   │
│  │  3. Update registry_failures:                                        │   │
│  │     SET reprocessed_at = CURRENT_TIMESTAMP()                         │   │
│  │                                                                       │   │
│  │  4. Trigger downstream cascade:                                      │   │
│  │     → Phase 4 precompute for affected players                        │   │
│  │     → Phase 5 predictions regenerated                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                         │
│  DAILY SUMMARY (7:00 AM ET)                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  • Slack: Resolution summary (auto-resolved, AI-resolved, pending)   │   │
│  │  • Slack: Reprocessing summary (games updated, players affected)     │   │
│  │  • Email: Players needing manual review (if any)                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Documentation

| Document | Description |
|----------|-------------|
| [01-current-state-analysis.md](./01-current-state-analysis.md) | Investigation of 2835 unresolved players |
| [02-corner-cases.md](./02-corner-cases.md) | Edge cases and how we handle them |
| [03-implementation-plan.md](./03-implementation-plan.md) | Step-by-step implementation |
| [04-database-schema.md](./04-database-schema.md) | New tables and columns needed |

## Quick Links

- **Previous Project:** [registry-system-fix](../registry-system-fix/) - Foundation work from 2026-01-10
- **AI Resolver Code:** `shared/utils/player_registry/ai_resolver.py`
- **Resolution Tools:** `tools/player_registry/`
- **Scheduled Jobs:** Cloud Scheduler `registry-ai-resolution`, `registry-health-check`

## Implementation Status

| Phase | Status | ETA |
|-------|--------|-----|
| Phase 1: Documentation | ✅ Complete | 2026-01-22 |
| Phase 2: Auto-Resolution Job | 📋 Planned | TBD |
| Phase 3: Expanded Game Tracking | 📋 Planned | TBD |
| Phase 4: Auto-Reprocessing | 📋 Planned | TBD |
| Phase 5: Monitoring & Alerts | 📋 Planned | TBD |
