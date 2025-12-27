# Robust Player Name Resolution System Design

**Document Version:** 1.0
**Date:** 2025-12-06
**Status:** Design Review
**Author:** Claude Code (Session 51)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current System Architecture](#2-current-system-architecture)
3. [Data Flow Analysis](#3-data-flow-analysis)
4. [Identified Issues & Failure Points](#4-identified-issues--failure-points)
5. [Current State Analysis](#5-current-state-analysis)
6. [Proposed Solutions](#6-proposed-solutions)
7. [AI Integration Design](#7-ai-integration-design)
8. [Error Handling & Recovery](#8-error-handling--recovery)
9. [Schema Changes](#9-schema-changes)
10. [Implementation Roadmap](#10-implementation-roadmap)
11. [Monitoring & Alerting](#11-monitoring--alerting)
12. [Open Questions & Decisions](#12-open-questions--decisions)

---

## 1. Executive Summary

### The Problem

The NBA stats pipeline ingests data from 7+ sources (NBA.com, ESPN, Basketball-Reference, etc.) that format player names differently. To join data across sources, we need a universal player identity. When name resolution fails, player data is lost.

### Current Impact

- **719 pending unresolved names** in queue
- **599 are "timing issues"** - players now exist in registry but were logged as unresolved earlier
- **10 unique names** actually need resolution (suffix/encoding issues)
- **~5,000 affected records** across 4 seasons
- **95% of issues** from 2023-24 season (backfill-related)
- **94% from Basketball-Reference** source

### Proposed Solution

A multi-layer resolution system that:
1. **Prevents** issues through suffix/fuzzy matching before failing
2. **Captures** full context when issues occur (game IDs, dates, processors)
3. **Automates** resolution for obvious cases (timing, suffix, encoding)
4. **Uses AI** for disambiguation and research tasks
5. **Caches** AI decisions for reuse without API calls
6. **Reprocesses** affected data automatically after resolution
7. **Monitors** for new patterns and anomalies

---

## 2. Current System Architecture

### 2.1 Key Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PLAYER REGISTRY SYSTEM                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────┐     ┌─────────────────────┐                   │
│  │ nba_players_registry│     │   player_aliases    │                   │
│  ├─────────────────────┤     ├─────────────────────┤                   │
│  │ universal_player_id │     │ alias_lookup        │                   │
│  │ player_name         │     │ nba_canonical_lookup│                   │
│  │ player_lookup       │◄────│ alias_type          │                   │
│  │ team_abbr           │     │ is_active           │                   │
│  │ season              │     └─────────────────────┘                   │
│  │ games_played        │                                               │
│  └─────────────────────┘                                               │
│            ▲                                                            │
│            │ lookup                                                     │
│  ┌─────────────────────┐     ┌─────────────────────┐                   │
│  │   RegistryReader    │     │ unresolved_player_  │                   │
│  ├─────────────────────┤     │      names          │                   │
│  │ get_universal_ids_  │────►├─────────────────────┤                   │
│  │   batch()           │     │ normalized_lookup   │                   │
│  │ flush_unresolved_   │     │ original_name       │                   │
│  │   players()         │     │ status              │                   │
│  └─────────────────────┘     │ occurrences         │                   │
│                              │ example_games (!)   │                   │
│                              └─────────────────────┘                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Key Files

| File | Purpose |
|------|---------|
| `shared/utils/player_registry/reader.py` | RegistryReader class - read-only access, batch lookups |
| `shared/utils/player_registry/resolver.py` | UniversalPlayerIDResolver - creates/resolves IDs |
| `tools/player_registry/resolve_unresolved_names.py` | CLI tool for manual resolution |
| `data_processors/analytics/player_game_summary/player_game_summary_processor.py` | Main analytics processor that uses registry |

### 2.3 Registry Design

The registry stores **one record per player per season per team**:

```
dennisschroder_001:
  2021-22 | BOS | 51 games
  2021-22 | HOU | 15 games   (traded mid-season)
  2022-23 | LAL | 84 games
  2023-24 | BKN | 29 games
  2023-24 | TOR | 54 games   (traded mid-season)
  ...
```

The `universal_player_id` is:
- **Unique per PLAYER** (one ID across career)
- **NOT unique per ROW** (multiple rows share same ID)

This is **by design** - allows tracking players across seasons/teams.

---

## 3. Data Flow Analysis

### 3.1 Processing Pipeline

```
PHASE 1: SCRAPERS
├── 7+ data sources scrape NBA data
├── Output: GCS files + nba_raw.* tables
└── Trigger: Cloud Scheduler → Master Controller

PHASE 2: RAW PROCESSORS (21 processors)
├── Process raw data, normalize, validate
├── Registry processors populate nba_players_registry
├── Output: Processed raw tables
└── Trigger: Pub/Sub nba-phase1-scrapers-complete

    ↓ Orchestrator waits for 21/21 complete

PHASE 3: ANALYTICS PROCESSORS (5 processors)
├── Transform raw → analytics tables
├── Uses RegistryReader for player lookups
├── If lookup fails → record SKIPPED
├── Output: nba_analytics.* tables
└── Trigger: Pub/Sub nba-phase3-trigger

    ↓ Orchestrator waits for 5/5 complete

PHASE 4: PRECOMPUTE PROCESSORS (5 processors)
├── Aggregate analytics → feature tables
├── Dependency ordering (#1,#2 parallel, then #3,#4,#5)
├── Output: nba_precompute.* tables
└── Trigger: Pub/Sub nba-phase4-trigger

    ↓ Orchestrator waits for 5/5 complete

PHASE 5: PREDICTIONS
├── Load features, run ML models
├── Output: Predictions tables
└── Trigger: Pub/Sub + HTTP call
```

### 3.2 Name Resolution Flow (Current)

```
Processor encounters player name "Marcus Morris"
    │
    ▼
normalize(name) → "marcusmorris"
    │
    ▼
Query registry: WHERE player_lookup = 'marcusmorris' AND season = '2023-24'
    │
    ├─► FOUND: Return universal_player_id
    │
    └─► NOT FOUND:
            │
            ▼
        Query aliases: WHERE alias_lookup = 'marcusmorris'
            │
            ├─► FOUND: Resolve canonical name → retry registry
            │
            └─► NOT FOUND:
                    │
                    ▼
                Log to unresolved_player_names
                Return None
                    │
                    ▼
                RECORD SKIPPED (data loss)
```

---

## 4. Identified Issues & Failure Points

### 4.1 Complete Failure Point Matrix

| ID | Phase | Failure Point | Severity | Current Handling | Status |
|----|-------|---------------|----------|------------------|--------|
| **F1.1** | Scrape | Source encoding varies (UTF-8 vs Latin-1) | Medium | None | Unaddressed |
| **F1.2** | Scrape | Name format differs by source | Medium | None | Unaddressed |
| **F1.3** | Scrape | Special characters lost (š → s or a) | High | None | Unaddressed |
| **F1.4** | Scrape | Suffix included/excluded inconsistently | High | None | Unaddressed |
| **F2.1** | Raw | Registry not ready before analytics | **Critical** | None | **Unaddressed** |
| **F2.2** | Raw | New player not in any source | Medium | Log unresolved | Partial |
| **F2.3** | Raw | Player traded mid-season | Low | Multiple entries | Working |
| **F2.4** | Raw | Name variation doesn't match registry | High | Log unresolved | Partial |
| **F2.5** | Raw | Race condition in ID creation | Low | None | Verified OK |
| **F3.1** | Analytics | Lookup fails → skip record | **Critical** | Skip + log | **Partial** |
| **F3.2** | Analytics | No game context captured | **Critical** | Empty array | **Unaddressed** |
| **F3.3** | Analytics | No skip details (which players) | High | Count only | Partial |
| **F3.4** | Analytics | No alert on high skip rate | Medium | None | Unaddressed |
| **F3.5** | Analytics | Incomplete data propagates | Medium | Silent | Unaddressed |
| **F3.6** | Analytics | No retry with variations | High | None | Unaddressed |
| **F4.1** | Precompute | Missing upstream data | Medium | Silent | Unaddressed |
| **F4.2** | Precompute | Aggregations incomplete | Medium | Silent | Unaddressed |
| **F6.1** | Resolution | No reprocessing after resolve | **Critical** | None | **Unaddressed** |
| **F6.2** | Resolution | Don't know affected dates | **Critical** | Empty example_games | **Unaddressed** |
| **F6.3** | Resolution | Wrong resolution made | High | None | Unaddressed |
| **F6.4** | Resolution | No rollback mechanism | High | None | Unaddressed |
| **F6.5** | Resolution | AI decisions not cached | High | N/A | Not implemented |
| **F6.6** | Resolution | No validation after reprocess | Medium | None | Unaddressed |
| **F7.1** | Backfill | Processor ordering issues | **Critical** | Manual | **Partial** |
| **F7.2** | Backfill | Previous failures block | High | Manual | Partial |

### 4.2 Root Cause Analysis

**Why do names end up unresolved?**

| Issue Type | Count | Root Cause | Example |
|------------|-------|------------|---------|
| **Timing Issues** | 599 | Analytics runs before registry populated | traeyoung logged as unresolved, but exists now |
| **Suffix Mismatch** | ~5 | Source omits Jr/Sr/II/III | marcusmorris vs marcusmorrissr |
| **Encoding Issues** | ~2 | Unicode handling differs | filippetruaev vs filippetrusev |
| **Season Mismatch** | ~2 | Player exists but not for that season | ronholland in 2025-26 not 2024-25 |
| **Unknown Player** | ~1 | Player not in any source | matthewhurt |

**Why is example_games always empty?**

```python
# In reader.py, flush_unresolved_players():
'example_games': game_ids[:10]  # Would be populated IF context had game_ids

# But get_universal_ids_batch() is called like:
uid_map = self.registry.get_universal_ids_batch(unique_players)  # No context!

# Context is set globally, not per-player:
registry.set_default_context(season=season_str)  # No game_id
```

**Why no reprocessing after resolution?**

The CLI tool `resolve_unresolved_names.py` was designed for manual review only:
1. Creates alias/registry entry ✓
2. Marks unresolved as resolved ✓
3. Logs to resolution_log ✓
4. **STOPS** - No Pub/Sub message, no reprocess trigger

---

## 5. Current State Analysis

### 5.1 Unresolved Queue Statistics

```
Total Pending: 719 records (603 unique names)

By Category:
├── Timing Issues: 698 records (599 unique)  ─── 97% auto-resolvable
└── Real Unresolved: 21 records (10 unique)  ─── Need resolution

By Season:
├── 2023-24: 4,858 occurrences (95.8%)
├── 2025-26: 141 occurrences
├── 2024-25: 46 occurrences
├── 2021-22: 14 occurrences
└── 2022-23: 10 occurrences

By Source:
├── basketball_reference: 94%
├── br: 3%
├── espn: 2%
└── nba_com: <1%
```

### 5.2 The 10 Real Unresolved Names

| Name | Original | Team | Season | Issue | Resolution |
|------|----------|------|--------|-------|------------|
| `marcusmorris` | Marcus Morris | PHI/CLE/LAC | Multiple | Registry has `marcusmorrissr` | Create alias |
| `robertwilliams` | Robert Williams | BOS/POR | Multiple | Registry has `robertwilliamsiii` | Create alias |
| `kevinknox` | Kevin Knox | Multiple | Multiple | Registry has `kevinknoxii` | Create alias |
| `ggjacksonii` | GG Jackson II | MEM | 2023-24 | Registry has `ggjackson` (no II) | Create alias |
| `xaviertillmansr` | Xavier Tillman Sr. | MEM | Multiple | Registry has `xaviertillman` | Create alias |
| `filippetruaev` | Filip Petruŝev | PHI/SAC | 2023-24 | Registry has `filippetrusev` | Create alias |
| `ronholland` | Ron Holland | DET | 2024-25 | Registry has 2025-26 only | Wait/add entry |
| `jeenathanwilliams` | Jeenathan Williams | HOU | 2024-25 | Registry has 2022-23/2023-24 | Wait/add entry |
| `matthewhurt` | Matthew Hurt | MEM | 2023-24 | No match found | Research needed |
| `derrickwalton` | Derrick Walton | DET | 2021-22 | No match found | Research needed |

### 5.3 Registry Statistics

```
Total Records: 3,908
Unique Player IDs: 1,293
Unique Lookups: 1,300

Players with most records (across seasons/teams):
├── mosesbrown_001: 9 records (5 seasons, 8 teams)
├── dennisschroder_001: 9 records (5 seasons, 8 teams)
├── pjtucker_001: 9 records (5 seasons, 6 teams)
└── ...

No TRUE duplicates found (same player+season+team appearing twice)
```

### 5.4 Alias Statistics

```
Current aliases: TBD (query showed no results for test names)
By type: TBD
```

---

## 6. Proposed Solutions

### 6.1 Multi-Layer Resolution Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PROPOSED RESOLUTION PIPELINE                              │
└─────────────────────────────────────────────────────────────────────────────┘

Input: Player name + team + season + game_context
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: EXACT MATCH                                                        │
│ ─────────────────────                                                       │
│ normalize(name) → lookup in registry                                        │
│ If found → return universal_player_id                                       │
│ Time: <1ms | Success rate: ~90%                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                    │ Not found
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: ALIAS LOOKUP                                                       │
│ ─────────────────────                                                       │
│ lookup in player_aliases → resolve canonical → retry registry               │
│ Time: <1ms | Success rate: ~5%                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                    │ Not found
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: SUFFIX VARIATIONS (NEW)                                            │
│ ───────────────────────────────                                             │
│ Try: name+jr, name+sr, name+ii, name+iii, name+iv                           │
│ Try: name-jr, name-sr, name-ii, name-iii, name-iv                           │
│ If match found → auto-create alias → return ID                              │
│ Time: <5ms | Expected success rate: ~3%                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                    │ Not found
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 4: FUZZY MATCH (NEW)                                                  │
│ ─────────────────────────                                                   │
│ Search registry for similar names (Levenshtein distance)                    │
│ Filter by: same team OR same season                                         │
│ If score > 0.92 → auto-create alias → return ID                             │
│ If score 0.85-0.92 → store as suggestion for later                          │
│ Time: <50ms | Expected success rate: ~1%                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                    │ Not found OR low confidence
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 5: LOG TO UNRESOLVED (ENHANCED)                                       │
│ ─────────────────────────────────────                                       │
│ Store with FULL context:                                                    │
│ - game_id, game_date, processor_name, run_id                                │
│ - issue_category (auto-classified)                                          │
│ - fuzzy_candidates (for later AI/manual review)                             │
│ - suggested_resolution                                                      │
│ Return None                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Auto-Resolution Tiers

| Tier | Risk | Conditions | Action | Review |
|------|------|------------|--------|--------|
| **1** | Zero | Timing issue: exact match now exists | Mark resolved | None |
| **2** | Low | Suffix match: same team+season | Create alias | Spot-check |
| **3** | Low | Fuzzy match: score > 0.92 | Create alias | Spot-check |
| **4** | Medium | Fuzzy match: score 0.85-0.92 | AI validation | Auto if AI confident |
| **5** | Medium | Multiple candidates | AI disambiguation | Auto if AI confident |
| **6** | High | No match found | AI research | Human review |

### 6.3 Two-Pass Backfill

**Current Problem:** Registry and analytics run in same phase, order not guaranteed.

**Solution:** Separate backfill into two explicit passes.

```bash
#!/bin/bash
# bin/backfill/run_two_pass_backfill.sh

# PASS 1: Registry Only
echo "=== PASS 1: Building Registry ==="
for season in 2021-22 2022-23 2023-24 2024-25; do
    # Run roster registry processor
    python -m data_processors.reference.player_reference.roster_registry_processor \
        --season $season --allow-backfill --skip-downstream-trigger

    # Run gamebook registry processor
    python -m data_processors.reference.player_reference.gamebook_registry_processor \
        --season $season --allow-backfill --skip-downstream-trigger
done

echo "=== Registry complete. Verifying... ==="
# Verify registry has expected player count

# PASS 2: Analytics + Precompute
echo "=== PASS 2: Processing Analytics ==="
for season in 2021-22 2022-23 2023-24 2024-25; do
    # Now safe to run analytics - registry is populated
    ./bin/backfill/run_phase3_backfill.sh --season $season
    ./bin/backfill/run_phase4_backfill.sh --season $season
done
```

### 6.4 Post-Resolution Reprocessing

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     POST-RESOLUTION FLOW                                     │
└─────────────────────────────────────────────────────────────────────────────┘

1. Name resolved (alias or registry entry created)
           │
           ▼
2. Query unresolved_occurrences for affected dates
   SELECT DISTINCT game_date
   FROM unresolved_occurrences
   WHERE normalized_lookup = @lookup
           │
           ▼
3. Create reprocessing job
   INSERT INTO resolution_reprocess_queue
   (affected_dates, priority, status='pending')
           │
           ▼
4. Reprocessing worker picks up job
   FOR each affected_date:
       - Trigger Phase 3 analytics
       - Trigger Phase 4 precompute
           │
           ▼
5. Verify data was recovered
   COUNT records where player_lookup = @lookup
   Log records_recovered
           │
           ▼
6. Mark job complete
```

---

## 7. AI Integration Design

### 7.1 When to Use AI vs Rules

| Scenario | Solution | Why |
|----------|----------|-----|
| Timing cleanup | SQL query | Zero ambiguity |
| Suffix variation | Rule-based | Deterministic pattern |
| High fuzzy match (>0.92) | Auto-alias | Algorithm sufficient |
| Encoding issue | Character mapping | Deterministic |
| **Disambiguation** | **Claude API** | Needs context understanding |
| **Research** | **Claude API** | Needs external knowledge |
| **Bulk triage** | **Claude API** | Efficiency at scale |

### 7.2 AI Prompt Design

```
You are resolving NBA player name mismatches for a statistics database.

TASK: Determine how to resolve unresolved player names.

For each name, analyze the context and provide:
1. resolution_type: "create_alias" | "add_registry" | "invalid" | "needs_human"
2. target_lookup: The canonical player_lookup to map to (if alias)
3. confidence: 0.0 to 1.0
4. reasoning: Brief explanation

CONTEXT FORMAT:
- unresolved_name: The name that couldn't be found
- normalized_lookup: The normalized version used for matching
- team: Team abbreviation where player appeared
- season: Season (e.g., "2023-24")
- source: Data source (e.g., "basketball_reference")
- similar_names: Names in registry with similarity scores
- team_roster: Other players on this team this season

GUIDELINES:
- Marcus Morris (no suffix) with PHI 2023-24 → likely Marcus Morris Sr.
- If jersey numbers available, use them for disambiguation
- If multiple candidates with similar confidence, choose "needs_human"
- For unknown players, search your knowledge for NBA players with that name

NAMES TO RESOLVE:
{context_json}

Respond with JSON array of resolutions.
```

### 7.3 AI Decision Caching

```sql
CREATE TABLE ai_resolution_cache (
    cache_id STRING NOT NULL,

    -- Input fingerprint
    input_hash STRING NOT NULL,        -- Hash of normalized_lookup + team + season
    normalized_lookup STRING NOT NULL,
    team_context STRING,
    season STRING,

    -- What AI saw
    context_snapshot JSON,             -- Full context sent to AI

    -- AI decision
    resolution_type STRING,            -- create_alias, add_registry, invalid, needs_human
    target_lookup STRING,              -- If alias, what it maps to
    confidence FLOAT64,
    reasoning STRING,

    -- API tracking
    model_version STRING,              -- claude-3-5-sonnet-20241022
    prompt_version STRING,             -- v1.0, v1.1, etc.
    tokens_used INT64,
    cost_usd FLOAT64,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

    -- Reuse tracking
    times_reused INT64 DEFAULT 0,
    last_reused_at TIMESTAMP,

    -- Human feedback
    human_reviewed BOOLEAN DEFAULT FALSE,
    human_approved BOOLEAN,
    human_override JSON,               -- If human changed decision
    override_reason STRING
)
CLUSTER BY input_hash, normalized_lookup;
```

**Cache Lookup Flow:**

```python
def resolve_with_ai(name, team, season, context):
    # Generate cache key
    input_hash = hash(f"{normalize(name)}|{team}|{season}")

    # Check cache
    cached = query_cache(input_hash)
    if cached and cached.confidence >= 0.85:
        # Reuse cached decision
        update_reuse_count(cached.cache_id)
        return cached

    # Call Claude API
    response = call_claude_api(build_prompt(context))

    # Cache the decision
    save_to_cache(input_hash, context, response)

    return response
```

---

## 8. Error Handling & Recovery

### 8.1 Error Scenario: Wrong AI Resolution

**Example:** AI incorrectly aliases "Marcus Morris" → "Marcus Morris Jr." (should be Sr.)

**Immediate Effect:**
- Alias created: marcusmorris → marcusmorrisjr
- Sr.'s games attributed to Jr.
- Both players' stats become wrong

**Discovery Mechanisms:**
1. Human spot-check of AI decisions
2. User reports incorrect stats
3. Anomaly detection (sudden stat jumps)
4. Validation: player on two teams same game

**Rollback Procedure:**

```sql
-- 1. Deactivate wrong alias
UPDATE player_aliases
SET is_active = FALSE,
    deactivated_at = CURRENT_TIMESTAMP(),
    deactivation_reason = 'Incorrect AI resolution'
WHERE alias_lookup = 'marcusmorris'
  AND nba_canonical_lookup = 'marcusmorrisjr';

-- 2. Create correct alias
INSERT INTO player_aliases (alias_lookup, nba_canonical_lookup, alias_type, ...)
VALUES ('marcusmorris', 'marcusmorrissr', 'suffix_difference', ...);

-- 3. Log correction
INSERT INTO unresolved_resolution_log (action, ...)
VALUES ('CORRECTION', ...);

-- 4. Update AI cache
UPDATE ai_resolution_cache
SET human_reviewed = TRUE,
    human_approved = FALSE,
    human_override = '{"correct_target": "marcusmorrissr"}',
    override_reason = 'Confused Jr. with Sr.'
WHERE normalized_lookup = 'marcusmorris';

-- 5. Re-trigger reprocessing
INSERT INTO resolution_reprocess_queue (...)
SELECT ... FROM unresolved_occurrences WHERE normalized_lookup = 'marcusmorris';
```

**Time to Fix:** ~30 minutes manual, ~5 minutes if automated

**Data Impact:** Fully reversible, no permanent damage

### 8.2 Prevention Strategies

1. **Include disambiguation context in AI prompt:**
   - Jersey numbers
   - Position
   - Age/draft year
   - Career stats range

2. **Validation rules before applying:**
   - If alias changes player identity significantly, flag for review
   - Check for conflicts (player on two teams same game)

3. **Confidence thresholds:**
   - Auto-apply: >= 0.95
   - Auto-apply with notification: 0.90-0.94
   - Human review: < 0.90

---

## 9. Schema Changes

### 9.1 New Table: unresolved_occurrences

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.unresolved_occurrences` (
    occurrence_id STRING NOT NULL,
    normalized_lookup STRING NOT NULL,    -- Links to unresolved_player_names

    -- Context
    game_id STRING NOT NULL,
    game_date DATE NOT NULL,
    season STRING NOT NULL,
    team_abbr STRING,

    -- Processor info
    processor_name STRING NOT NULL,
    processor_run_id STRING NOT NULL,
    source_table STRING,
    raw_record_key STRING,                -- Reference to source record

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY normalized_lookup, processor_name
OPTIONS (
    description = "Tracks every occurrence of unresolved player names with full context"
);
```

### 9.2 New Table: resolution_reprocess_queue

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.resolution_reprocess_queue` (
    job_id STRING NOT NULL,
    resolution_id STRING,                  -- From unresolved_resolution_log
    normalized_lookup STRING NOT NULL,
    resolution_type STRING,
    resolved_to STRING,

    -- Scope
    affected_dates ARRAY<DATE>,
    affected_processors ARRAY<STRING>,
    total_records_affected INT64,

    -- Execution
    priority INT64,                        -- Higher = process sooner
    status STRING,                         -- pending, queued, running, completed, failed
    batch_id STRING,                       -- Group multiple resolutions

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    queued_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Results
    records_reprocessed INT64,
    records_recovered INT64,
    error_message STRING
)
PARTITION BY DATE(created_at)
OPTIONS (
    description = "Queue for reprocessing data after name resolution"
);
```

### 9.3 New Table: ai_resolution_cache

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.ai_resolution_cache` (
    cache_id STRING NOT NULL,
    input_hash STRING NOT NULL,
    normalized_lookup STRING NOT NULL,
    team_context STRING,
    season STRING,

    context_snapshot JSON,

    resolution_type STRING,
    target_lookup STRING,
    confidence FLOAT64,
    reasoning STRING,

    model_version STRING,
    prompt_version STRING,
    tokens_used INT64,
    cost_usd FLOAT64,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    times_reused INT64 DEFAULT 0,
    last_reused_at TIMESTAMP,

    human_reviewed BOOLEAN DEFAULT FALSE,
    human_approved BOOLEAN,
    human_override JSON,
    override_reason STRING
)
CLUSTER BY input_hash, normalized_lookup
OPTIONS (
    description = "Cache for AI resolution decisions to avoid duplicate API calls"
);
```

### 9.4 Alterations to unresolved_player_names

```sql
ALTER TABLE `nba-props-platform.nba_reference.unresolved_player_names`
ADD COLUMN IF NOT EXISTS issue_category STRING,
ADD COLUMN IF NOT EXISTS auto_resolvable BOOLEAN,
ADD COLUMN IF NOT EXISTS fuzzy_candidates JSON,
ADD COLUMN IF NOT EXISTS suggested_resolution JSON,
ADD COLUMN IF NOT EXISTS priority_score FLOAT64,
ADD COLUMN IF NOT EXISTS affected_game_count INT64,
ADD COLUMN IF NOT EXISTS affected_date_range STRUCT<start_date DATE, end_date DATE>,
ADD COLUMN IF NOT EXISTS ai_decision_id STRING;
```

---

## 10. Implementation Roadmap

### Phase 0: Immediate Cleanup (1-2 hours)

**Goal:** Clear current queue, establish baseline

- [ ] Mark 599 timing issues as resolved
- [ ] Create 6 obvious aliases (suffix/encoding)
- [ ] Document resolution patterns
- [ ] Verify no data impact

**Deliverables:**
- Pending queue: 719 → ~4
- 6 new aliases in player_aliases
- Resolution log entries

### Phase 1: Critical Infrastructure (4-8 hours)

**Goal:** Enable safe backfill, capture context

- [ ] Create `unresolved_occurrences` table
- [ ] Modify `flush_unresolved_players()` to populate context
- [ ] Create two-pass backfill script
- [ ] Test on small date range

**Deliverables:**
- New table schema deployed
- Modified reader.py
- Working two-pass backfill script

### Phase 2: Prevention Layer (8-12 hours)

**Goal:** Reduce new unresolved names

- [ ] Build suffix variation handler
- [ ] Integrate fuzzy matching (use existing name_utils.py)
- [ ] Add auto-alias creation for high-confidence matches
- [ ] Add issue_category classification

**Deliverables:**
- Enhanced resolve_player_name() function
- Auto-alias logging
- Category classification

### Phase 3: AI Integration (8-12 hours)

**Goal:** Handle complex cases efficiently

- [ ] Design prompt template
- [ ] Create ai_resolution_cache table
- [ ] Build AINameResolver class
- [ ] Integrate with CLI tool
- [ ] Test on historical unresolved names

**Deliverables:**
- Working AI resolution pipeline
- Cache with reuse capability
- Enhanced CLI tool

### Phase 4: Reprocessing (8-12 hours)

**Goal:** Automatically fix historical data

- [ ] Create resolution_reprocess_queue table
- [ ] Build reprocessing worker
- [ ] Integrate with resolution flow
- [ ] Add verification step

**Deliverables:**
- Automated reprocessing after resolution
- Verification logging
- Integration with existing backfill

### Phase 5: Monitoring (4-8 hours)

**Goal:** Catch issues early

- [ ] Daily alert for new unresolved count
- [ ] Skip rate monitoring
- [ ] Anomaly detection for stat changes
- [ ] Dashboard metrics

**Deliverables:**
- Alert configuration
- Monitoring queries
- Dashboard (if applicable)

---

## 11. Monitoring & Alerting

### 11.1 Daily Alerts

| Alert | Condition | Action |
|-------|-----------|--------|
| New unresolved spike | Count > 10 in 24h | Investigate source |
| High skip rate | > 5% for any processor | Check registry |
| Reprocess queue backup | > 100 dates pending | Scale up worker |
| AI low confidence | > 5 names with conf < 0.8 | Manual review |

### 11.2 Weekly Reports

- Resolution rate by category (auto vs AI vs manual)
- AI accuracy (based on human reviews)
- Reprocessing completion status
- Data completeness by season

### 11.3 Anomaly Detection

- Player stats change > 50% after reprocess → investigate
- Player on multiple teams same game → data error
- Games played > games in season → duplicate data
- Career stats decrease → something was removed

---

## 12. Open Questions & Decisions

### 12.1 Confirmed Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Skip vs NULL player ID | Skip records | Prevents duplicates, cleaner data |
| Error tolerance | 5% acceptable | Fully reversible, low impact |
| AI cost | Acceptable ($0.01-0.05/name) | Time savings worth it |
| Cache AI decisions | Yes | Reuse without API calls |
| Implementation order | Phases 0-5 as outlined | Builds on each phase |

### 12.2 Open Questions

1. **Backfill timing:** When is the 4-season backfill planned to start?
2. **Daily orchestration:** Is this already running, or also to be set up?
3. **Notification preferences:** Slack? Email? Both?
4. **Dashboard:** Is there an existing monitoring dashboard to add to?

---

## Appendix A: Existing Fuzzy Matching Utilities

The codebase already has fuzzy matching infrastructure:

**Location:** `data_processors/raw/utils/name_utils.py`

```python
def levenshtein_distance(s1: str, s2: str) -> int:
    """Pure Python Levenshtein distance implementation"""

def calculate_similarity(name1: str, name2: str) -> float:
    """Returns similarity score 0.0 to 1.0"""
    # Formula: (longer - distance) / longer

def normalize_name(name: str) -> str:
    """Removes accents, punctuation, spaces"""
```

**Also available:**
- FuzzyWuzzy library (installed, used for team matching)
- python-Levenshtein C extension (for performance)
- BigQuery LEVENSHTEIN() function

---

## Appendix B: Sample Queries

### Count unresolved by category

```sql
SELECT
    CASE
        WHEN EXISTS (
            SELECT 1 FROM nba_reference.nba_players_registry r
            WHERE u.normalized_lookup = r.player_lookup
              AND u.season = r.season
        ) THEN 'timing_issue'
        ELSE 'real_unresolved'
    END as category,
    COUNT(*) as count
FROM nba_reference.unresolved_player_names u
WHERE status = 'pending'
GROUP BY 1;
```

### Find suffix match candidates

```sql
WITH pending AS (
    SELECT normalized_lookup, team_abbr, season
    FROM nba_reference.unresolved_player_names
    WHERE status = 'pending'
),
registry AS (
    SELECT player_lookup, team_abbr, season
    FROM nba_reference.nba_players_registry
)
SELECT
    p.normalized_lookup as unresolved,
    r.player_lookup as registry_match,
    CASE
        WHEN r.player_lookup = CONCAT(p.normalized_lookup, 'jr') THEN 'add_jr'
        WHEN r.player_lookup = CONCAT(p.normalized_lookup, 'sr') THEN 'add_sr'
        WHEN r.player_lookup = CONCAT(p.normalized_lookup, 'ii') THEN 'add_ii'
        WHEN r.player_lookup = CONCAT(p.normalized_lookup, 'iii') THEN 'add_iii'
    END as suffix_type
FROM pending p
JOIN registry r ON p.season = r.season
WHERE r.player_lookup LIKE CONCAT(p.normalized_lookup, '%')
  AND LENGTH(r.player_lookup) <= LENGTH(p.normalized_lookup) + 4;
```

### Auto-resolve timing issues

```sql
UPDATE nba_reference.unresolved_player_names u
SET
    status = 'resolved',
    resolution_type = 'timing_auto',
    reviewed_by = 'automated_cleanup',
    reviewed_at = CURRENT_TIMESTAMP(),
    notes = 'Auto-resolved: exact match exists in registry'
WHERE status = 'pending'
  AND EXISTS (
    SELECT 1 FROM nba_reference.nba_players_registry r
    WHERE u.normalized_lookup = r.player_lookup
      AND u.season = r.season
  );
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-06 | Claude Code | Initial document |
