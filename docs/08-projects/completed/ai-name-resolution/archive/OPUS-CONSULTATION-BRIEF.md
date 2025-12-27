# Strategic Consultation: AI-Assisted Player Name Resolution System

**Purpose:** This document provides comprehensive context about our NBA stats pipeline's player name resolution system. We're seeking strategic recommendations for implementing AI-assisted name resolution during backfill operations.

**Request:** Please analyze this system, provide recommendations, challenge our assumptions, and ask clarifying questions. We want the best possible solution, not just validation of our current thinking.

---

## Table of Contents

1. [The Big Picture Problem](#1-the-big-picture-problem)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Detailed Data Flow](#3-detailed-data-flow)
4. [Current State Analysis](#4-current-state-analysis)
5. [Identified Gaps & Issues](#5-identified-gaps--issues)
6. [Our Current Recommendations](#6-our-current-recommendations)
7. [Open Questions](#7-open-questions)
8. [Request for Guidance](#8-request-for-guidance)

---

## 1. The Big Picture Problem

### What We're Building

An NBA statistics pipeline that:
- Scrapes data from 7+ sources (NBA.com, ESPN, Basketball-Reference, Ball Don't Lie API, etc.)
- Processes raw data through multiple phases (Raw → Analytics → Precompute → Predictions)
- Uses BigQuery for storage
- Runs on Google Cloud (Cloud Run, Pub/Sub orchestration)

### The Core Challenge

**Different data sources format player names differently:**

| Source | Name Format Example |
|--------|---------------------|
| NBA.com | "LeBron James" |
| Basketball-Reference | "L. James" or "LeBron James" |
| ESPN | "LeBron James" |
| Ball Don't Lie | "Lebron James" (lowercase) |
| Odds API | "L. James Jr." |

**To join data across sources, we need a universal player identity.**

### Why This Matters Now

We're running a historical backfill (processing 3+ years of data). During this backfill:
- Many player names fail to resolve
- When resolution fails, **player data is skipped entirely**
- 719 names are currently pending manual review
- Manual review is time-consuming (2-5 min per name)
- Skipped data means incomplete analytics

**Our Goal:** Use Claude API to automate name resolution during backfill, reducing manual effort while maintaining data quality.

---

## 2. System Architecture Overview

### Processing Phases

```
PHASE 1: SCRAPERS
├── 7+ data sources scraping NBA data
├── Raw player names vary by source
└── Output: nba_raw.* tables (game stats, rosters, etc.)

PHASE 2: REFERENCE PROCESSORS (Registry Building)
├── Roster Registry Processor (runs first)
│   └── Populates registry from roster sources
├── Gamebook Registry Processor (runs second)
│   └── Confirms players via game participation
└── Output: nba_reference.nba_players_registry

PHASE 3: ANALYTICS PROCESSORS
├── Uses RegistryReader to look up universal IDs
├── If lookup fails → record is SKIPPED
├── Unresolved names logged to queue
└── Output: nba_analytics.* tables

PHASE 4: PRECOMPUTE PROCESSORS
├── Aggregates analytics data
├── Affected by missing players from Phase 3
└── Output: nba_precompute.* tables

PHASE 5: PREDICTIONS
├── Uses precompute features
└── Output: predictions tables
```

### Key Database Tables

**`nba_reference.nba_players_registry`** - The authoritative player store
```sql
-- Key fields:
universal_player_id STRING,    -- e.g., "lebronjames_001" (immutable across name changes)
player_name STRING,            -- Display name: "LeBron James"
player_lookup STRING,          -- Normalized key: "lebronjames"
team_abbr STRING,              -- Current team
season STRING,                 -- "2024-25"
games_played INT64,            -- Confirmation via game participation
-- Plus: jersey_number, position, source tracking, timestamps
```

**`nba_reference.unresolved_player_names`** - Queue for manual review
```sql
-- Key fields:
source STRING,                 -- Which processor/source encountered this
original_name STRING,          -- Name as it appeared in source
normalized_lookup STRING,      -- Normalized version for matching
team_abbr STRING,
season STRING,
occurrences INT64,             -- How many times seen
example_games ARRAY<STRING>,   -- Game IDs where encountered (CURRENTLY EMPTY - bug)
status STRING,                 -- 'pending', 'resolved', 'invalid', 'ignored', 'snoozed'
resolution_type STRING,        -- 'create_alias', 'add_to_registry', 'typo'
```

**`nba_reference.player_aliases`** - Maps name variations to canonical names
```sql
-- Key fields:
alias_lookup STRING,           -- The variant: "marcusmorris"
nba_canonical_lookup STRING,   -- Maps to: "marcusmorrissr"
alias_type STRING,             -- 'suffix_difference', 'nickname', 'typo', 'source_variation'
is_active BOOLEAN,
```

---

## 3. Detailed Data Flow

### How a Player Name Gets Resolved

```
Step 1: NORMALIZATION
   Input:  "LeBron James Jr."
   Output: "lebronjamesjr"

   Process:
   - Lowercase
   - Remove diacritics (é → e)
   - Strip spaces, hyphens, apostrophes, periods
   - Remove all non-alphanumeric

Step 2: REGISTRY LOOKUP
   Query: SELECT universal_player_id
          FROM nba_players_registry
          WHERE player_lookup = 'lebronjamesjr'

   If found → Return universal_player_id ✓
   If not found → Continue to Step 3

Step 3: ALIAS LOOKUP
   Query: SELECT nba_canonical_lookup
          FROM player_aliases
          WHERE alias_lookup = 'lebronjamesjr'
          AND is_active = TRUE

   If found → Recursively resolve canonical name
   If not found → Continue to Step 4

Step 4: FAILURE HANDLING
   - Log to unresolved_player_names queue
   - Return None
   - CALLING CODE SKIPS THIS RECORD
```

### What Happens When Resolution Fails (Critical Issue)

In `player_game_summary_processor.py`:

```python
# Line 647: Batch lookup all players
uid_map = self.registry.get_universal_ids_batch(unique_players)

# Line 810-814: Process each row
universal_player_id = uid_map.get(player_lookup)
if universal_player_id is None:
    self.registry_stats['records_skipped'] += 1
    return None  # ← ENTIRE RECORD SKIPPED, DATA LOST
```

**Impact:** If "Marcus Morris" appears without "Sr." suffix:
- His game stats for that game are not written
- Downstream analytics/precompute affected
- No automatic recovery when name is later resolved

### How Names Get Into the Registry

**Path 1: Roster Processor (Primary)**
1. Scrapes rosters from NBA.com, ESPN, Basketball-Reference
2. Normalizes names
3. Creates registry entries with `universal_player_id`
4. Runs BEFORE game data processing

**Path 2: Gamebook Processor (Secondary)**
1. Processes official NBA gamebook PDFs
2. Confirms players via game participation
3. Updates registry with game counts
4. Runs AFTER roster processor

**Path 3: Manual Resolution (Current)**
1. CLI tool reviews unresolved names
2. Human decides: create alias, add to registry, or mark invalid
3. No automatic reprocessing of affected data

---

## 4. Current State Analysis

### Unresolved Names Statistics

```
Total Pending: 719 records (603 unique names)

By Season:
├── 2023-24: 657 (572 unique) ← Bulk of backfill issues
├── 2025-26: 44 (42 unique)
├── 2024-25: 6 (6 unique)
├── 2022-23: 5 (4 unique)
└── 2021-22: 7 (6 unique)

By Source:
├── basketball_reference: 675 (94%)
├── br: 25
├── espn: 17
└── nba_com: 2
```

**Key Insight:** Basketball-Reference is the primary problem source (94% of unresolved).

### Common Unresolved Patterns

| Pattern | Unresolved Name | Registry Name | Issue |
|---------|-----------------|---------------|-------|
| Missing Jr./Sr. | `marcusmorris` | `marcusmorrissr` | Suffix not included |
| Missing III/II | `robertwilliams` | `robertwilliamsiii` | Suffix not included |
| Accented chars | `filippetruaev` | `filippetrusev` | š encoded as 'a' vs 's' |
| Different suffix | `xaviertillmansr` | `xaviertillman` | Has suffix, registry doesn't |

### Timing Issue Discovery

Many "unresolved" names actually exist in registry now:
- Analytics processor ran before registry was updated
- Name logged as unresolved
- Registry processor later added the player
- Unresolved record never cleaned up

**Example:** `kevinknox` marked unresolved for GSW/2025-26, but exists in registry.

### Current Manual Resolution Workflow

```
1. Run CLI tool: python -m tools.player_registry.resolve_unresolved_names

2. For each pending name, tool shows:
   - Similar names in registry
   - Team roster for that season
   - Existing aliases for similar names

3. User chooses action:
   [a]lias   - Create alias to existing player
   [n]ew     - Create new registry entry
   [i]nvalid - Mark as typo/error
   [g]ignore - Mark as too minor
   [z]snooze - Delay 7 days

4. After resolution:
   - Alias/registry entry created
   - Unresolved marked as 'resolved'
   - NO automatic reprocessing of affected data
```

---

## 5. Identified Gaps & Issues

### GAP #1: Data Loss on Resolution Failure (CRITICAL)

**Problem:** When a name fails to resolve, the entire record is skipped.

**Current Behavior:**
```python
if universal_player_id is None:
    return None  # Skip this player's data
```

**Impact:**
- Player stats not written to analytics tables
- Downstream phases have incomplete data
- Manual re-run required after resolution

**Alternative Considered:** Write partial records with NULL universal_player_id
- Pro: Preserves data for later recovery
- Con: Complicates downstream queries, may break joins

---

### GAP #2: No Link Between Unresolved Names and Affected Records

**Problem:** When we resolve a name, we don't know which records need reprocessing.

**Current State:**
- `unresolved_player_names` tracks names
- `example_games` array exists but is ALWAYS EMPTY (context not passed in batch lookups)
- No table linking names to specific skipped records

**Impact:**
- After resolution, must re-run entire date range
- Can't measure business impact of each unresolved name
- No way to prioritize which names to resolve first

---

### GAP #3: No Automatic Reprocessing After Resolution

**Problem:** After resolving a name, nothing happens automatically.

**Current Flow:**
1. Name resolved → alias created
2. Unresolved record marked 'resolved'
3. **End.** No trigger to reprocess affected data.

**Desired Flow:**
1. Name resolved → alias created
2. System identifies affected date range/games
3. Triggers reprocessing for those specific dates
4. Tracks recovery success

---

### GAP #4: Race Condition in Universal ID Creation

**Problem:** Concurrent processors can create duplicate universal IDs.

**Scenario:**
```
Thread A: Checks if "newplayer_001" exists → No
Thread B: Checks if "newplayer_001" exists → No
Thread A: Creates "newplayer_001"
Thread B: Creates "newplayer_001" ← DUPLICATE!
```

**Current Mitigation:** None. No distributed lock or atomic operation.

**Impact:** Potential duplicate universal IDs causing join issues.

---

### GAP #5: No Skip Reason Tracking

**Problem:** Can't identify which processor runs had name resolution failures.

**Current State:**
- `processor_run_history` tracks runs
- `records_skipped` field exists
- No breakdown of WHY records were skipped

**Impact:**
- Can't query "show me all runs that skipped records due to unresolved names"
- Can't correlate unresolved names to specific runs

---

## 6. Our Current Recommendations

### Recommendation 1: Use Claude API for Batch Resolution

**Approach:**
1. Build context for each unresolved name (registry matches, roster, aliases)
2. Send to Claude with structured prompt
3. Get decision + confidence score
4. Auto-apply if confidence ≥ 0.95, else queue for human review

**Proposed Prompt Structure:**
```
Given an unresolved player name with context:
- Unresolved: "marcusmorris" (Team: PHI, Season: 2023-24)
- Similar in registry: ["marcusmorrissr" on PHI 2023-24, 45 games]
- Team roster: [list of PHI players]
- Existing aliases: [none for similar names]

Determine:
1. Resolution type: create_alias | create_registry | invalid | unknown
2. Target (if alias): which player_lookup to map to
3. Alias type: suffix_difference | nickname | typo | source_variation
4. Confidence: 0.0-1.0
5. Reasoning: brief explanation
```

**Confidence Thresholds:**
- ≥ 0.95: Auto-apply
- 0.90-0.94: Auto-apply with notification
- 0.70-0.89: Human review with AI suggestion
- < 0.70: Human review, no auto-action

**Cost Estimate:**
- ~600 names at ~$0.01 per 10 = ~$6-10 for backlog
- Daily: < $0.01/day

---

### Recommendation 2: Create New Tables for Full Tracking

**Table 1: `ai_resolution_log`**
```sql
decision_id STRING,
unresolved_lookup STRING,
model_name STRING,
confidence FLOAT64,
decision_type STRING,
target_lookup STRING,
reasoning STRING,
input_tokens INT64,
cost_usd FLOAT64,
decision_applied BOOLEAN,
human_reviewed BOOLEAN,
reprocess_triggered BOOLEAN
```

**Table 2: `unresolved_name_impacts`**
```sql
unresolved_lookup STRING,
affected_table STRING,
affected_game_id STRING,
affected_game_date DATE,
impact_type STRING,  -- record_skipped, incomplete_data
resolved BOOLEAN,
reprocessed BOOLEAN
```

**Table 3: `name_resolution_reprocess_queue`**
```sql
resolution_id STRING,
affected_table STRING,
game_dates ARRAY<DATE>,
status STRING,  -- pending, running, completed, failed
priority INT64,
records_recovered INT64
```

---

### Recommendation 3: Add Impact Tracking to Current Flow

**Modify `RegistryReader.get_universal_ids_batch()`:**
- Pass game context (game_id, date)
- Populate `example_games` array
- Calculate `affected_records_count`

**Add to `unresolved_player_names`:**
```sql
affected_records_count INT64,
affected_tables ARRAY<STRING>,
affected_game_dates ARRAY<DATE>,
priority_tier STRING  -- Based on impact
```

---

### Recommendation 4: Implement Post-Resolution Hooks

**When name is resolved:**
1. Query for affected records/dates
2. Create reprocessing queue entry
3. Trigger processor via Pub/Sub
4. Track recovery success

---

## 7. Open Questions

### Questions We're Uncertain About

1. **Should we prevent data loss at source?**
   - Option A: Keep skipping unresolved (current)
   - Option B: Write partial records with NULL universal_player_id
   - Option C: Write to separate "pending resolution" table
   - Trade-offs unclear

2. **Batch vs. Real-time AI Resolution?**
   - Batch: Process accumulated names periodically (e.g., after each season backfilled)
   - Real-time: Call Claude API inline during processing (adds latency)
   - Hybrid: Batch for backfill, real-time for daily ops?

3. **How to handle the race condition?**
   - Option A: Distributed lock (Redis?)
   - Option B: BigQuery MERGE with uniqueness constraint
   - Option C: Accept occasional duplicates, clean up later
   - Which is best for BigQuery environment?

4. **Confidence threshold tuning?**
   - 0.95 feels conservative but safe
   - Should we start higher (0.98) and lower based on accuracy data?
   - How do we measure AI accuracy post-deployment?

5. **What about the timing issue (names that now exist)?**
   - Should we auto-clean these before running AI?
   - Simple query: unresolved names that match registry
   - Reduces AI workload by ~10-20%?

6. **Reprocessing scope after resolution?**
   - Reprocess entire season where name appeared?
   - Reprocess only specific dates from `example_games`?
   - What's the cost/benefit of granular vs. broad reprocessing?

### Questions About Our Approach

1. Are we overcomplicating this? Is there a simpler solution?

2. Should we fix the "data loss" architecture first, before adding AI?

3. Is Claude API the right tool, or would fuzzy matching algorithms suffice?

4. How should we handle cases where AI is uncertain? Current plan is human review, but is there a better pattern?

5. What's the right level of audit trail? We've proposed extensive logging - is this overkill?

---

## 8. Request for Guidance

### What We Need From You

1. **Architecture Validation:** Is our proposed approach sound? Are we missing anything critical?

2. **Priority Ordering:** Given limited time, what should we implement first?

3. **Simplification Opportunities:** Where are we overengineering?

4. **Risk Assessment:** What could go wrong with AI-assisted resolution? How do we mitigate?

5. **Alternative Approaches:** Are there better solutions we haven't considered?

6. **Implementation Strategy:**
   - Should we do a quick "cleanup" pass (timing issues, auto-matchable patterns) before AI?
   - How should we phase the rollout?

### Please Challenge Our Assumptions

- We assume AI can reliably match player names with context. Is this true?
- We assume 0.95 confidence is a good auto-apply threshold. Is it?
- We assume we need extensive audit logging. Do we?
- We assume reprocessing is straightforward. Is it?

### Please Ask Your Own Questions

We may have missed important considerations. What else do you need to know to provide good recommendations?

---

## Appendix: File Locations (For Reference)

```
Registry System:
├── shared/utils/player_registry/reader.py      # Read-only access
├── shared/utils/player_registry/resolver.py   # Universal ID resolution
├── shared/utils/player_registry/exceptions.py # Custom exceptions
└── tools/player_registry/resolve_unresolved_names.py  # CLI tool

Schemas:
├── schemas/bigquery/nba_reference/nba_players_registry_table.sql
├── schemas/bigquery/nba_reference/unresolved_player_names_table.sql
├── schemas/bigquery/nba_reference/player_aliases_table.sql
└── schemas/bigquery/processing/processing_tables.sql

Key Processors:
├── data_processors/reference/player_reference/roster_registry_processor.py
├── data_processors/reference/player_reference/gamebook_registry_processor.py
└── data_processors/analytics/player_game_summary/player_game_summary_processor.py

Documentation:
├── docs/06-reference/player-registry.md
└── docs/08-projects/current/ai-name-resolution/
```

---

## End of Brief

Thank you for reviewing this. We're looking for strategic guidance to ensure we build the right solution, not just a solution. Please be critical and thorough in your analysis.
