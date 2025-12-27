# AI-Powered Player Name Resolution System

## Design Document v1.0

**Created:** 2025-12-06 (Session 52)
**Status:** Design Complete, Ready for Implementation
**Authors:** Human + Claude

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Current Architecture Analysis](#3-current-architecture-analysis)
4. [Root Cause Analysis](#4-root-cause-analysis)
5. [Solution Design](#5-solution-design)
6. [Scenario Handling](#6-scenario-handling)
7. [Implementation Plan](#7-implementation-plan)
8. [Data Structures](#8-data-structures)
9. [API Design](#9-api-design)
10. [Integration Points](#10-integration-points)
11. [Monitoring & Alerting](#11-monitoring--alerting)
12. [Future Enhancements](#12-future-enhancements)
13. [Decision Log](#13-decision-log)
14. [Appendix](#appendix)

---

## 1. Executive Summary

### 1.1 The Problem
Player names from different data sources don't always match the canonical names in our registry. This causes players to be marked as "unresolved," resulting in incomplete analytics data.

### 1.2 The Solution
A multi-layer name resolution system that:
1. **Fixes an architectural gap** - Add alias lookup to RegistryReader
2. **Implements intelligent matching** - Use Claude API for ambiguous cases
3. **Auto-creates aliases** - Build the alias table automatically over time
4. **Enables reprocessing** - Fix historical data when new aliases are created

### 1.3 Key Metrics
| Metric | Before | After (Target) |
|--------|--------|----------------|
| Unresolved rate | ~1% of players | <0.1% |
| Manual review required | All unresolved | Only truly unknown |
| Time to resolution | Days (manual) | Minutes (automated) |

---

## 2. Problem Statement

### 2.1 Current Situation
When processing game data, we encounter player names that don't match our registry:

```
Source Data: "Marcus Morris" (LAC, 2021-22)
Registry Has: "Marcus Morris Sr." → player_lookup: "marcusmorrissr"
Result: Player marked as UNRESOLVED, stats lost
```

### 2.2 Impact
- **Data Completeness:** Missing player stats in analytics tables
- **Prop Betting:** Can't calculate results for unresolved players
- **ML Features:** Incomplete training data
- **User Experience:** Gaps in player dashboards

### 2.3 Scale (Current Backfill)
```
Total Pending: 719 records

Breakdown:
├── 599 (83%) timing issues → Exist in registry, just not found at query time
├── 10 (1.4%) true mismatches → Need aliases
├── 2 (0.3%) season gaps → Player not in registry for that season
└── 108 (15%) duplicates → Same player logged multiple times
```

---

## 3. Current Architecture Analysis

### 3.1 Component Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PLAYER REGISTRY SYSTEM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐         ┌─────────────────────┐                   │
│  │  Registry Writers   │         │   Registry Readers   │                   │
│  │  (Phase 1 Processors)│         │  (Analytics Processors)│                │
│  └──────────┬──────────┘         └──────────┬──────────┘                   │
│             │                               │                               │
│             ▼                               ▼                               │
│  ┌─────────────────────┐         ┌─────────────────────┐                   │
│  │ UniversalPlayerID   │         │   RegistryReader    │                   │
│  │ Resolver            │         │                     │                   │
│  │                     │         │  - Direct lookup    │                   │
│  │ - Direct lookup     │         │  - NO alias lookup! │ ◄── GAP!         │
│  │ - Alias lookup ✓    │         │  - Log unresolved   │                   │
│  │ - Create new IDs    │         │                     │                   │
│  └──────────┬──────────┘         └──────────┬──────────┘                   │
│             │                               │                               │
│             ▼                               ▼                               │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     BigQuery Tables                                   │  │
│  │  ┌────────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │  │
│  │  │ nba_players_registry│  │  player_aliases  │  │unresolved_player │  │  │
│  │  │                    │  │                  │  │    _names        │  │  │
│  │  │ player_lookup (PK) │  │ alias_lookup(PK) │  │ normalized_lookup│  │  │
│  │  │ universal_player_id│  │ canonical_lookup │  │ status           │  │  │
│  │  │ player_name        │  │ is_active        │  │ resolution_type  │  │  │
│  │  │ team_abbr          │  │ alias_type       │  │ resolved_to_name │  │  │
│  │  │ season             │  │                  │  │                  │  │  │
│  │  └────────────────────┘  └──────────────────┘  └──────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Key Files

| File | Purpose | Used By |
|------|---------|---------|
| `shared/utils/player_registry/reader.py` | Read-only registry access | Analytics processors |
| `shared/utils/player_registry/resolver.py` | Create/resolve universal IDs | Registry processors |
| `shared/utils/player_registry/exceptions.py` | Custom exceptions | Both |

### 3.3 The Architectural Gap

**Problem:** `RegistryReader.get_universal_ids_batch()` does NOT check aliases.

```python
# Current flow in RegistryReader (reader.py:474-555)
def get_universal_ids_batch(self, player_lookups, context=None):
    # Step 1: Check cache - OK
    # Step 2: Query registry directly - OK
    # Step 3: Log missing as unresolved - OK
    #
    # MISSING: Step 2.5 - Check alias table for missing players!
```

**Why this matters:**
- Even if we create aliases, analytics processors won't use them
- Only registry processors (which create IDs) check aliases
- This defeats the purpose of the alias system

---

## 4. Root Cause Analysis

### 4.1 Categories of Unresolved Names

| Category | Example | Root Cause | Resolution |
|----------|---------|------------|------------|
| **Timing Issues** | `treymurphy` not found | Registry not populated when analytics ran | Auto-resolves on reprocess |
| **Suffix Mismatch** | `marcusmorris` vs `marcusmorrissr` | Source omits Jr/Sr/II/III | Create alias |
| **Reverse Suffix** | `xaviertillmansr` vs `xaviertillman` | Source includes suffix, registry doesn't | Create alias |
| **Nickname** | `matthewhurt` vs `matthurt` | Matthew vs Matt | Create alias |
| **Encoding** | `filippetruaev` vs `filippetrusev` | Unicode handling (š → s) | Create alias |
| **Season Gap** | `ronholland` in 2024-25 | Player not in registry for season | Add to registry or wait |
| **Truly Unknown** | Never seen name | Data error or new player | Manual review |

### 4.2 Registry Data Quality Issue

The registry itself has inconsistencies - same players appear with multiple `player_lookup` values:

```
Ronald Holland II: ['ronaldhollandii', 'ronaldholland']
Dennis Smith Jr.: ['dennissmithjr', 'dennissmith']
Kevin Knox II: ['kevinknoxii', 'kevinknox']
... (15+ players affected)
```

**Impact:** Creates confusion about which is "canonical"
**Recommendation:** Standardize on WITH-suffix versions, create aliases from without-suffix

### 4.3 The 10 True Mismatches (from 2021 backfill)

| Unresolved | Canonical | Type | Seasons Affected |
|------------|-----------|------|------------------|
| `marcusmorris` | `marcusmorrissr` | suffix | 2021-22, 2022-23, 2023-24 |
| `robertwilliams` | `robertwilliamsiii` | suffix | 2021-22, 2022-23, 2024-25 |
| `kevinknox` | `kevinknoxii` | suffix | 2021-22, 2022-23, 2024-25 |
| `derrickwalton` | `derrickwaltonjr` | suffix | 2021-22 |
| `xaviertillmansr` | `xaviertillman` | reverse_suffix | 2021-22, 2022-23 |
| `ggjacksonii` | `ggjackson` | reverse_suffix | 2023-24 |
| `filippetruaev` | `filippetrusev` | encoding | 2023-24 |
| `matthewhurt` | `matthurt` | nickname | 2023-24 |

---

## 5. Solution Design

### 5.1 Multi-Layer Resolution Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RESOLUTION PIPELINE (Priority Order)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Input: player_lookup = "marcusmorris"                                      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 1: DIRECT LOOKUP (instant)                                    │   │
│  │ Query: SELECT * FROM registry WHERE player_lookup = 'marcusmorris'  │   │
│  │ Result: NOT FOUND → continue                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 2: ALIAS LOOKUP (instant)                                     │   │
│  │ Query: SELECT canonical FROM aliases WHERE alias = 'marcusmorris'   │   │
│  │ Result: Found 'marcusmorrissr' → RESOLVED                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼ (if not found)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 3: FUZZY MATCHING (fast, no API)                              │   │
│  │ - Try adding common suffixes (jr, sr, ii, iii)                      │   │
│  │ - Try removing suffixes                                             │   │
│  │ - Try common nickname mappings                                      │   │
│  │ Result: If confident match → auto-create alias → RESOLVED           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼ (if still not found)                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 4: AI RESOLUTION (Claude API - batched)                       │   │
│  │ - Provide context: team, season, similar names in registry          │   │
│  │ - Ask Claude to identify most likely match                          │   │
│  │ - If confidence > 90%: auto-create alias                            │   │
│  │ - If confidence 70-90%: create alias, flag for review               │   │
│  │ - If confidence < 70%: flag for manual review                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼ (if still not found)                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 5: MANUAL REVIEW QUEUE                                        │   │
│  │ - Add to unresolved_player_names with status='needs_review'         │   │
│  │ - Alert if count exceeds threshold                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Component Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NEW COMPONENTS                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  shared/utils/player_registry/                                              │
│  ├── reader.py              # MODIFY: Add alias lookup                      │
│  ├── resolver.py            # EXISTING: No changes needed                   │
│  ├── ai_resolver.py         # NEW: Claude API integration                   │
│  ├── fuzzy_matcher.py       # NEW: Rule-based fuzzy matching                │
│  └── alias_manager.py       # NEW: Alias CRUD operations                    │
│                                                                             │
│  tools/player_registry/                                                     │
│  ├── resolve_unresolved_names.py  # EXISTING: Manual CLI tool               │
│  └── batch_ai_resolve.py          # NEW: Batch AI resolution                │
│                                                                             │
│  orchestration/                                                             │
│  └── daily_orchestrator.py  # MODIFY: Add post-processing step              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Decision: When to Use AI vs Rules

| Scenario | Use Rules | Use AI |
|----------|-----------|--------|
| Missing suffix (Jr/Sr/II/III) | ✓ | |
| Extra suffix | ✓ | |
| Common nickname (Matt/Matthew) | ✓ | |
| Unicode normalization | ✓ | |
| Multiple possible matches | | ✓ |
| Name completely different | | ✓ |
| Low confidence from rules | | ✓ |

**Rationale:** Rules are fast, free, and predictable. Use AI only when rules can't decide.

---

## 6. Scenario Handling

### 6.1 Scenario: Backfill Processing

**Context:** Running analytics on historical data (e.g., 2021-22 season)

```
Timeline:
1. Phase 1 processors run → Registry populated with 2021-22 players
2. Phase 2 raw data collected → Game stats from 2021-22
3. Analytics processors run → Some players unresolved (different name formats)
4. AI Resolution runs → Creates aliases for mismatches
5. Reprocessing triggered → Analytics re-run for affected games
```

**Flow:**

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Analytics        │───▶│ Unresolved       │───▶│ AI Resolution    │
│ Processing       │    │ Queue            │    │ (batch mode)     │
│                  │    │                  │    │                  │
│ 50 players/game  │    │ 10 unresolved    │    │ 8 auto-resolved  │
│ 48 found         │    │ accumulated      │    │ 2 flagged review │
│ 2 not found      │    │                  │    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
                                                        │
                                                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Reprocessing     │◀───│ Affected Games   │◀───│ Alias Created    │
│ Complete         │    │ Identified       │    │                  │
│                  │    │                  │    │ marcusmorris →   │
│ 100% players     │    │ 47 games need    │    │ marcusmorrissr   │
│ resolved         │    │ reprocess        │    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

### 6.2 Scenario: Daily Orchestration

**Context:** Processing today's games as part of daily pipeline

```
Timeline:
1. 10:00 AM - Raw data collected (overnight games)
2. 10:05 AM - Registry updated with any new players
3. 10:10 AM - Analytics processors run
4. 10:15 AM - Post-process: Check for unresolved players
5. 10:16 AM - If unresolved > 0: Run AI resolution
6. 10:17 AM - If aliases created: Trigger targeted reprocess
7. 10:20 AM - Pipeline complete
```

**Key Difference from Backfill:**
- Smaller batches (usually 0-5 unresolved per day)
- Real-time resolution matters more
- Should alert if unusual volume

### 6.3 Scenario: New Player (Rookie Debut)

**Context:** A new player debuts mid-season

```
Game Data: "Bronny James" plays first game
Registry: Does not have Bronny James yet (roster not updated)
Result: Player marked unresolved

Resolution Path:
1. Fuzzy match fails (no similar name)
2. AI says "likely new player, not an alias"
3. Marked as 'new_player' in unresolved queue
4. Alert sent: "Potential new player: Bronny James (LAL)"
5. Roster processor runs next day → adds to registry
6. Reprocessing fills in stats
```

### 6.4 Scenario: Trade Mid-Season

**Context:** Player traded, name format differs between sources

```
Source A: "James Harden" (LAC)
Source B: "James E. Harden" (LAC)
Registry: "jamesharden" (LAC)

Resolution Path:
1. "jamesharden" found directly → OK
2. "jameseharden" not found
3. Fuzzy match: Remove middle initial → "jamesharden" → MATCH
4. Auto-create alias: jameseharden → jamesharden
```

### 6.5 Scenario: Encoding/Unicode Issues

**Context:** International player names with special characters

```
Source: "Filip Petruŝev" → normalized to "filippetruaev" (š → a???)
Registry: "filippetrusev" (š → s)

Resolution Path:
1. Direct lookup fails
2. Alias lookup fails
3. Fuzzy: Unicode normalization tries multiple forms
4. AI: Given candidates, identifies "filippetrusev" as match
5. Creates alias with type='encoding'
```

### 6.6 Scenario: Multiple Candidates

**Context:** Ambiguous name could match multiple players

```
Source: "Marcus Morris" (team unknown)
Registry:
  - "marcusmorrissr" (Marcus Morris Sr.)
  - "marcusmorrisjr" (Marcus Morris Jr. - if existed)

Resolution Path:
1. Direct/Alias fail
2. Fuzzy finds multiple candidates
3. AI considers context (team, season)
4. If team=LAC: Marcus Morris Sr. played for LAC → high confidence
5. If no team context: Low confidence → flag for review
```

### 6.7 Scenario: Data Error in Source

**Context:** Source has completely wrong player name

```
Source: "Michael Jordan" plays for LAL in 2024
Registry: Michael Jordan retired in 2003

Resolution Path:
1. All layers fail
2. AI: "Michael Jordan is retired, this is likely a data error"
3. Mark as 'data_error' with note
4. Alert: "Suspicious data: Michael Jordan playing in 2024"
5. Manual review confirms error, mark as 'ignored'
```

---

## 7. Implementation Plan

### 7.1 Phase 1: Fix the Gap (1-2 hours)

**Goal:** Add alias lookup to RegistryReader

**Changes:**
```python
# reader.py - Modify get_universal_ids_batch()
def get_universal_ids_batch(self, player_lookups, context=None):
    # Step 1: Check cache (existing)
    # Step 2: Query registry directly (existing)

    # Step 2.5: NEW - Check aliases for missing players
    missing_from_registry = [p for p in player_lookups if p not in result]
    if missing_from_registry:
        alias_mappings = self._bulk_resolve_via_aliases(missing_from_registry)
        result.update(alias_mappings)

    # Step 3: Log remaining as unresolved (existing)
```

**Testing:**
1. Create test alias manually
2. Verify RegistryReader finds player via alias
3. Run analytics processor, confirm alias used

### 7.2 Phase 2: Fuzzy Matcher (2-3 hours)

**Goal:** Rule-based matching for common patterns

**New File:** `shared/utils/player_registry/fuzzy_matcher.py`

```python
class FuzzyMatcher:
    SUFFIXES = ['jr', 'sr', 'ii', 'iii', 'iv']
    NICKNAMES = {
        'matthew': 'matt', 'michael': 'mike',
        'william': 'will', 'robert': 'rob', ...
    }

    def find_candidates(self, lookup: str, registry_lookups: List[str]) -> List[Match]:
        """Return ranked list of potential matches."""
        candidates = []

        # Try adding suffixes
        for suffix in self.SUFFIXES:
            if f"{lookup}{suffix}" in registry_lookups:
                candidates.append(Match(f"{lookup}{suffix}", 'suffix_added', 0.95))

        # Try removing suffixes
        for suffix in self.SUFFIXES:
            if lookup.endswith(suffix):
                base = lookup[:-len(suffix)]
                if base in registry_lookups:
                    candidates.append(Match(base, 'suffix_removed', 0.95))

        # Try nickname substitution
        # ... etc

        return sorted(candidates, key=lambda x: x.confidence, reverse=True)
```

### 7.3 Phase 3: AI Resolver (3-4 hours)

**Goal:** Claude API integration for complex cases

**New File:** `shared/utils/player_registry/ai_resolver.py`

```python
class AINameResolver:
    def __init__(self, api_key: str = None):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ['ANTHROPIC_API_KEY'])
        self.model = "claude-3-haiku-20240307"  # Fast, cheap for this use case

    def resolve_batch(self, unresolved: List[UnresolvedPlayer]) -> List[Resolution]:
        """Resolve multiple unresolved players in one API call."""

        # Build prompt with all unresolved names and candidates
        prompt = self._build_prompt(unresolved)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        return self._parse_response(response)

    def _build_prompt(self, unresolved: List[UnresolvedPlayer]) -> str:
        return f"""You are helping resolve NBA player names. For each unresolved name,
identify the most likely canonical match from the candidates provided.

Return JSON with format:
{{"resolutions": [
  {{"unresolved": "marcusmorris", "canonical": "marcusmorrissr", "confidence": 0.98, "reason": "Missing Sr. suffix"}},
  ...
]}}

Unresolved players:
{self._format_unresolved(unresolved)}

Registry candidates:
{self._format_candidates(unresolved)}
"""
```

### 7.4 Phase 4: Alias Manager (1-2 hours)

**Goal:** Clean interface for alias CRUD

**New File:** `shared/utils/player_registry/alias_manager.py`

```python
class AliasManager:
    def create_alias(self, alias_lookup: str, canonical_lookup: str,
                     alias_type: str, source: str, confidence: float) -> bool:
        """Create new alias in BigQuery."""

    def bulk_create_aliases(self, aliases: List[AliasRecord]) -> int:
        """Create multiple aliases efficiently."""

    def deactivate_alias(self, alias_lookup: str) -> bool:
        """Soft-delete an alias."""

    def get_alias_stats(self) -> Dict:
        """Get statistics about alias usage."""
```

### 7.5 Phase 5: Integration (2-3 hours)

**Goal:** Wire everything together

**Changes:**

1. **Daily Orchestrator:**
```python
# After all processors complete:
async def post_process_resolution(self):
    unresolved = get_pending_unresolved()
    if not unresolved:
        return

    # Layer 3: Fuzzy matching
    fuzzy = FuzzyMatcher()
    resolved, remaining = fuzzy.resolve_batch(unresolved)

    # Layer 4: AI resolution (if needed)
    if remaining:
        ai = AINameResolver()
        ai_resolved = ai.resolve_batch(remaining)
        resolved.extend(ai_resolved)

    # Create aliases and trigger reprocessing
    alias_manager.bulk_create_aliases(resolved)
    trigger_reprocessing(get_affected_games(resolved))
```

2. **Backfill Script:**
```python
# bin/backfill/resolve_and_reprocess.py
def main():
    # Get all pending unresolved
    unresolved = get_all_pending_unresolved()

    # Run resolution pipeline
    resolved = resolution_pipeline.process(unresolved)

    # Create aliases
    alias_manager.bulk_create_aliases(resolved)

    # Get affected games
    affected_games = get_affected_games(resolved)

    # Trigger reprocessing
    for game in affected_games:
        reprocess_game(game)
```

### 7.6 Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Fix Gap | 1-2 hours | None |
| Phase 2: Fuzzy Matcher | 2-3 hours | None |
| Phase 3: AI Resolver | 3-4 hours | Anthropic API key |
| Phase 4: Alias Manager | 1-2 hours | None |
| Phase 5: Integration | 2-3 hours | Phases 1-4 |

**Total:** 9-14 hours

---

## 8. Data Structures

### 8.1 Existing Tables

#### nba_players_registry
```sql
CREATE TABLE nba_reference.nba_players_registry (
  universal_player_id STRING NOT NULL,
  player_name STRING NOT NULL,
  player_lookup STRING NOT NULL,  -- Normalized: "lebronjames"
  team_abbr STRING NOT NULL,
  season STRING NOT NULL,
  -- ... other fields
  PRIMARY KEY (player_lookup, team_abbr, season)
);
```

#### player_aliases
```sql
CREATE TABLE nba_reference.player_aliases (
  alias_lookup STRING NOT NULL,      -- The variant: "marcusmorris"
  nba_canonical_lookup STRING NOT NULL,  -- The canonical: "marcusmorrissr"
  alias_display STRING NOT NULL,     -- Display: "Marcus Morris"
  nba_canonical_display STRING NOT NULL, -- Display: "Marcus Morris Sr."
  alias_type STRING,                 -- 'suffix', 'nickname', 'encoding', etc.
  alias_source STRING,               -- 'manual', 'ai_resolved', 'fuzzy_match'
  is_active BOOL NOT NULL DEFAULT TRUE,
  notes STRING,
  confidence FLOAT64,                -- AI confidence score
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL,
  PRIMARY KEY (alias_lookup)
);
```

#### unresolved_player_names
```sql
CREATE TABLE nba_reference.unresolved_player_names (
  source STRING NOT NULL,
  original_name STRING NOT NULL,
  normalized_lookup STRING NOT NULL,
  first_seen_date DATE,
  last_seen_date DATE,
  team_abbr STRING,
  season STRING,
  occurrences INT64,
  example_games ARRAY<STRING>,
  status STRING NOT NULL,  -- 'pending', 'resolved', 'snoozed', 'ignored'
  resolution_type STRING,  -- 'alias_created', 'timing_auto', 'manual', etc.
  resolved_to_name STRING,
  notes STRING,
  reviewed_by STRING,
  reviewed_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
);
```

### 8.2 New Table: ai_resolution_log

```sql
CREATE TABLE nba_reference.ai_resolution_log (
  resolution_id STRING NOT NULL,
  unresolved_lookup STRING NOT NULL,
  resolved_to STRING,
  confidence FLOAT64,
  resolution_type STRING,  -- 'auto_accepted', 'flagged_review', 'no_match'
  ai_model STRING,
  ai_response JSON,
  candidates_provided ARRAY<STRING>,
  context JSON,  -- team, season, etc.
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (resolution_id)
);
```

**Purpose:** Audit trail for AI decisions, enables analysis and improvement.

---

## 9. API Design

### 9.1 FuzzyMatcher API

```python
class FuzzyMatcher:
    def find_candidates(
        self,
        lookup: str,
        registry_lookups: List[str],
        context: Optional[Dict] = None
    ) -> List[Match]:
        """
        Find potential matches for an unresolved lookup.

        Args:
            lookup: The unresolved player_lookup
            registry_lookups: All valid lookups from registry
            context: Optional context (team, season)

        Returns:
            List of Match objects sorted by confidence
        """

    def resolve_batch(
        self,
        unresolved: List[UnresolvedPlayer]
    ) -> Tuple[List[Resolution], List[UnresolvedPlayer]]:
        """
        Attempt to resolve a batch of unresolved players.

        Returns:
            Tuple of (resolved, still_unresolved)
        """

@dataclass
class Match:
    canonical_lookup: str
    match_type: str  # 'suffix_added', 'suffix_removed', 'nickname', 'encoding'
    confidence: float  # 0.0 to 1.0
```

### 9.2 AINameResolver API

```python
class AINameResolver:
    def resolve_single(
        self,
        unresolved: UnresolvedPlayer,
        candidates: List[str]
    ) -> Resolution:
        """Resolve a single unresolved player using AI."""

    def resolve_batch(
        self,
        unresolved: List[UnresolvedPlayer],
        max_batch_size: int = 20
    ) -> List[Resolution]:
        """
        Resolve multiple unresolved players efficiently.

        Batches API calls for efficiency.
        """

    def get_resolution_stats(self) -> Dict:
        """Get statistics about AI resolution performance."""

@dataclass
class Resolution:
    unresolved_lookup: str
    canonical_lookup: Optional[str]
    confidence: float
    resolution_type: str  # 'match_found', 'no_match', 'needs_review'
    reason: str
    ai_model: Optional[str]
```

### 9.3 AliasManager API

```python
class AliasManager:
    def create_alias(
        self,
        alias_lookup: str,
        canonical_lookup: str,
        alias_type: str,
        source: str,
        confidence: float = 1.0,
        notes: str = None
    ) -> bool:
        """Create a new alias."""

    def bulk_create_aliases(
        self,
        aliases: List[AliasRecord]
    ) -> Tuple[int, List[str]]:
        """
        Create multiple aliases.

        Returns:
            Tuple of (success_count, error_messages)
        """

    def get_alias(self, alias_lookup: str) -> Optional[AliasRecord]:
        """Get alias by lookup."""

    def deactivate_alias(self, alias_lookup: str, reason: str) -> bool:
        """Soft-delete an alias."""

    def get_usage_stats(self) -> Dict:
        """Get alias usage statistics."""
```

---

## 10. Integration Points

### 10.1 Analytics Processors

**File:** `data_processors/analytics/*/processor.py`

**Current Flow:**
```python
# In process() method:
uid_map = self.registry.get_universal_ids_batch(unique_players)
# Missing players logged to unresolved queue
```

**After Phase 1 (No Code Change Needed in Processors):**
- `RegistryReader.get_universal_ids_batch()` now checks aliases
- Processors automatically benefit

### 10.2 Daily Orchestrator

**File:** `orchestration/daily_orchestrator.py`

**Add Post-Processing Step:**
```python
async def run_daily_pipeline(self):
    # Existing steps...
    await self.run_phase1_processors()
    await self.run_phase2_processors()
    await self.run_analytics_processors()

    # NEW: Post-processing resolution
    await self.resolve_unresolved_players()

async def resolve_unresolved_players(self):
    """Resolve any unresolved players from today's processing."""

    # Get pending from today
    unresolved = self.get_todays_unresolved()
    if not unresolved:
        logger.info("No unresolved players to process")
        return

    logger.info(f"Processing {len(unresolved)} unresolved players")

    # Run resolution pipeline
    resolver = ResolutionPipeline()
    results = resolver.process(unresolved)

    # Log results
    logger.info(f"Resolved: {results.resolved_count}, "
                f"Flagged: {results.flagged_count}, "
                f"Failed: {results.failed_count}")

    # Trigger reprocessing if needed
    if results.aliases_created:
        affected_games = self.get_affected_games(results.aliases_created)
        await self.queue_reprocessing(affected_games)
```

### 10.3 Backfill Scripts

**New File:** `bin/backfill/resolve_backfill_unresolved.py`

```python
#!/usr/bin/env python3
"""
Resolve all pending unresolved players from a backfill run.

Usage:
    python resolve_backfill_unresolved.py --season 2021-22
    python resolve_backfill_unresolved.py --all-pending
"""

def main():
    args = parse_args()

    # Get unresolved players
    if args.season:
        unresolved = get_unresolved_for_season(args.season)
    else:
        unresolved = get_all_pending_unresolved()

    print(f"Found {len(unresolved)} unresolved players")

    # Run resolution pipeline
    pipeline = ResolutionPipeline(
        use_fuzzy=True,
        use_ai=True,
        auto_create_aliases=args.auto_alias,
        confidence_threshold=args.confidence
    )

    results = pipeline.process(unresolved)

    # Report results
    print_results(results)

    # Optionally trigger reprocessing
    if args.reprocess and results.aliases_created:
        trigger_reprocessing(results.affected_games)

if __name__ == '__main__':
    main()
```

### 10.4 CLI Tool Enhancement

**File:** `tools/player_registry/resolve_unresolved_names.py`

**Add AI Resolution Option:**
```python
@click.command()
@click.option('--use-ai', is_flag=True, help='Use AI for resolution')
@click.option('--auto-alias', is_flag=True, help='Auto-create aliases for high confidence')
@click.option('--confidence', default=0.9, help='Minimum confidence for auto-alias')
def resolve(use_ai, auto_alias, confidence):
    """Resolve unresolved player names."""
    # ... existing logic ...

    if use_ai:
        ai_resolver = AINameResolver()
        # ... AI resolution logic ...
```

---

## 11. Monitoring & Alerting

### 11.1 Metrics to Track

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `unresolved_daily_count` | New unresolved per day | > 20 |
| `resolution_success_rate` | % resolved by pipeline | < 90% |
| `ai_resolution_rate` | % requiring AI | > 50% |
| `alias_creation_rate` | New aliases per day | Info only |
| `reprocess_queue_size` | Games awaiting reprocess | > 100 |

### 11.2 Alert Configuration

```python
# In notification_system config
ALERTS = {
    'high_unresolved_count': {
        'threshold': 20,
        'level': 'WARNING',
        'message': 'Unusually high unresolved player count: {count}'
    },
    'ai_resolution_failure': {
        'threshold': 5,  # consecutive failures
        'level': 'ERROR',
        'message': 'AI resolution failing consistently'
    },
    'new_player_detected': {
        'level': 'INFO',
        'message': 'Potential new player: {player_name} ({team})'
    }
}
```

### 11.3 Dashboard Queries

```sql
-- Daily resolution stats
SELECT
  DATE(created_at) as date,
  COUNT(*) as total,
  COUNTIF(status = 'resolved') as resolved,
  COUNTIF(status = 'pending') as pending,
  COUNTIF(resolution_type = 'ai_resolved') as ai_resolved
FROM nba_reference.unresolved_player_names
WHERE created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY date
ORDER BY date DESC;

-- Alias effectiveness
SELECT
  alias_type,
  alias_source,
  COUNT(*) as count,
  AVG(confidence) as avg_confidence
FROM nba_reference.player_aliases
WHERE is_active = TRUE
GROUP BY alias_type, alias_source;
```

---

## 12. Future Enhancements

### 12.1 Short-Term (Next 1-2 months)

1. **Learning Loop:** Track which AI resolutions are later corrected by humans, use to improve prompts
2. **Caching:** Cache AI responses for identical inputs to reduce API costs
3. **Batch Optimization:** Optimal batch sizes for AI calls based on response quality

### 12.2 Medium-Term (3-6 months)

1. **Cross-Season Learning:** Use aliases from one season to pre-populate for next
2. **Source-Specific Rules:** Different sources have different patterns, learn them
3. **Confidence Calibration:** Tune thresholds based on actual accuracy

### 12.3 Long-Term (6+ months)

1. **Fine-Tuned Model:** Train a small model specifically for NBA name matching
2. **Predictive Aliases:** Pre-create aliases for expected variations before they occur
3. **Data Quality Feedback:** Use resolution data to improve source data quality

### 12.4 Registry Cleanup (Parallel Work)

The registry has duplicate entries (with/without suffixes). Consider:
1. Standardize on canonical form (with suffix)
2. Create aliases for all variants
3. Update historical data

---

## 13. Decision Log

### D1: AI Model Choice
**Decision:** Use Claude 3 Haiku for name resolution
**Rationale:** Fast, cheap, sufficient accuracy for this task
**Alternatives Considered:** Claude Sonnet (overkill), GPT-4 (more expensive)

### D2: Confidence Thresholds
**Decision:**
- ≥90%: Auto-create alias
- 70-89%: Create alias + flag for review
- <70%: Manual review only

**Rationale:** Balance automation with safety. Most cases should be clear.

### D3: Layer Order
**Decision:** Direct → Alias → Fuzzy → AI → Manual
**Rationale:** Cheapest/fastest first. Only escalate when needed.

### D4: Alias Immutability
**Decision:** Aliases are soft-deleted, never modified
**Rationale:** Audit trail, reproducibility, debugging

### D5: Reprocessing Trigger
**Decision:** Queue-based, not immediate
**Rationale:** Batch reprocessing more efficient, avoids thundering herd

### D6: Phase 1 Priority
**Decision:** Fix RegistryReader gap first
**Rationale:** Enables existing aliases, immediate value

---

## Appendix

### A1: Example AI Prompt

```
You are an NBA player name matching assistant. Your task is to identify which
canonical player name, if any, matches each unresolved name.

Context:
- Unresolved names come from game data (box scores, play-by-play)
- Canonical names are from our verified player registry
- Common issues: missing suffixes (Jr/Sr/II/III), nicknames, encoding

For each unresolved name, return:
- canonical: The matching canonical name (or null if no match)
- confidence: 0.0 to 1.0
- reason: Brief explanation

Return valid JSON only.

Unresolved players to match:
1. "marcusmorris" - Team: LAC, Season: 2021-22
2. "matthewhurt" - Team: MEM, Season: 2023-24

Candidates from registry (same team/season):
- LAC 2021-22: marcusmorrissr, paulgeorge, reggiejackson, ...
- MEM 2023-24: matthurt, jajackson, jakemorant, ...

Response format:
{
  "resolutions": [
    {"unresolved": "marcusmorris", "canonical": "marcusmorrissr", "confidence": 0.98, "reason": "Missing Sr. suffix, same team/season"},
    {"unresolved": "matthewhurt", "canonical": "matthurt", "confidence": 0.95, "reason": "Matthew→Matt nickname variation"}
  ]
}
```

### A2: Test Cases

```python
# test_fuzzy_matcher.py
def test_suffix_addition():
    matcher = FuzzyMatcher()
    result = matcher.find_candidates('marcusmorris', ['marcusmorrissr', 'otherplayer'])
    assert result[0].canonical_lookup == 'marcusmorrissr'
    assert result[0].match_type == 'suffix_added'
    assert result[0].confidence >= 0.9

def test_suffix_removal():
    matcher = FuzzyMatcher()
    result = matcher.find_candidates('xaviertillmansr', ['xaviertillman', 'otherplayer'])
    assert result[0].canonical_lookup == 'xaviertillman'
    assert result[0].match_type == 'suffix_removed'

def test_nickname():
    matcher = FuzzyMatcher()
    result = matcher.find_candidates('matthewhurt', ['matthurt', 'otherplayer'])
    assert result[0].canonical_lookup == 'matthurt'
    assert result[0].match_type == 'nickname'
```

### A3: Cost Estimation

| Component | Cost Driver | Estimated Monthly Cost |
|-----------|-------------|------------------------|
| Claude API | ~$0.25/1M input tokens | $5-10 (batch processing) |
| BigQuery | Storage + queries | Already included |
| Reprocessing | Compute | Minimal (incremental) |

**Total incremental cost:** ~$10-20/month

### A4: File Locations Summary

```
shared/utils/player_registry/
├── __init__.py
├── reader.py           # MODIFY: Add alias lookup
├── resolver.py         # EXISTING: No changes
├── exceptions.py       # EXISTING: No changes
├── fuzzy_matcher.py    # NEW
├── ai_resolver.py      # NEW
└── alias_manager.py    # NEW

tools/player_registry/
├── resolve_unresolved_names.py  # MODIFY: Add AI option
└── batch_ai_resolve.py          # NEW

bin/backfill/
└── resolve_backfill_unresolved.py  # NEW

tests/player_registry/
├── test_fuzzy_matcher.py    # NEW
├── test_ai_resolver.py      # NEW
└── test_alias_manager.py    # NEW
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-06 | Session 52 | Initial design document |
