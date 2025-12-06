# AI-Assisted Player Name Resolution

**Project Status:** Planning
**Created:** 2025-12-05
**Last Updated:** 2025-12-05

## Problem Statement

During backfill operations, the player registry system accumulates many unresolved player names that require manual review. The current CLI tool (`tools/player_registry/resolve_unresolved_names.py`) provides excellent context but requires human judgment for each name, which is time-consuming during large backfills.

**Goal:** Automate player name resolution using Claude API to reduce manual review workload while maintaining data quality.

---

## Current System Overview

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Player Registry System                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────┐    ┌──────────────────┐    ┌────────────────┐ │
│  │   Data Sources   │───▶│  Registry Reader │───▶│  Downstream    │ │
│  │  (gamebook, etc) │    │   (read-only)    │    │  Processors    │ │
│  └──────────────────┘    └────────┬─────────┘    └────────────────┘ │
│                                   │                                  │
│                          Player Not Found?                           │
│                                   │                                  │
│                                   ▼                                  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              unresolved_player_names (BigQuery)               │   │
│  │  - source, original_name, normalized_lookup                   │   │
│  │  - team_abbr, season, occurrences                             │   │
│  │  - status: pending → resolved/invalid/ignored                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                   │                                  │
│                          MANUAL REVIEW (Current)                     │
│                                   │                                  │
│                                   ▼                                  │
│  ┌──────────────────┐    ┌──────────────────┐                       │
│  │  player_aliases  │◀───│   CLI Tool       │                       │
│  │  (mappings)      │    │   (interactive)  │                       │
│  └──────────────────┘    └──────────────────┘                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `nba_players_registry` | Authoritative player records | `universal_player_id`, `player_lookup`, `player_name`, `team_abbr`, `season` |
| `unresolved_player_names` | Queue for manual review | `normalized_lookup`, `original_name`, `team_abbr`, `season`, `status` |
| `player_aliases` | Name variation mappings | `alias_lookup` → `nba_canonical_lookup`, `alias_type` |

### Current Resolution Options

1. **Create Alias** - Map unresolved name to existing canonical player
2. **Create Registry Entry** - Add as new player to registry
3. **Mark Invalid** - Typo or data error
4. **Mark Ignored** - Too minor to track
5. **Snooze** - Delay for later review

### CLI Context Provided

The current CLI tool provides rich context for each unresolved name:
- Similar names in registry (fuzzy search)
- Team roster for the season
- Existing aliases for similar names
- Occurrence count and game examples

---

## Proposed Solution: Claude API Integration

### High-Level Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                    AI-Assisted Resolution Flow                        │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────┐                                                  │
│  │ Unresolved Name │                                                  │
│  │ (pending queue) │                                                  │
│  └────────┬────────┘                                                  │
│           │                                                           │
│           ▼                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    Context Builder                               │ │
│  │  - Search registry for similar names                             │ │
│  │  - Get team roster for season                                    │ │
│  │  - Check existing aliases                                        │ │
│  │  - Get historical data (traded players, etc.)                    │ │
│  └────────┬────────────────────────────────────────────────────────┘ │
│           │                                                           │
│           ▼                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    Claude API Call                               │ │
│  │  Prompt with:                                                    │ │
│  │  - Unresolved name + context                                     │ │
│  │  - Registry matches                                              │ │
│  │  - Team roster                                                   │ │
│  │  - Request: Decision + Confidence                                │ │
│  └────────┬────────────────────────────────────────────────────────┘ │
│           │                                                           │
│           ▼                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    Decision Router                               │ │
│  │                                                                  │ │
│  │   High Confidence (≥0.90)     │    Low Confidence (<0.90)       │ │
│  │   ─────────────────────       │    ───────────────────────       │ │
│  │   Auto-apply resolution       │    Queue for human review        │ │
│  │   Log to audit table          │    Include AI suggestion         │ │
│  │                               │                                   │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Claude Prompt Design

```python
RESOLUTION_PROMPT = """
You are an NBA player name resolution assistant. Your task is to determine the correct identity of an unresolved player name.

## Unresolved Name
- **Original Name:** {original_name}
- **Normalized Lookup:** {normalized_lookup}
- **Team:** {team_abbr}
- **Season:** {season}
- **Occurrences:** {occurrences}
- **Source:** {source}

## Similar Names in Registry
{registry_matches}

## Team Roster ({team_abbr}, {season})
{team_roster}

## Existing Aliases for Similar Names
{existing_aliases}

## Your Task
Analyze the unresolved name and determine:

1. **Resolution Type**: One of:
   - `create_alias` - This is a variation of an existing player
   - `create_registry` - This is a new player not in the registry
   - `invalid` - This appears to be a typo or data error
   - `unknown` - Not enough information to decide

2. **Canonical Match** (if create_alias): The `player_lookup` to map to

3. **Alias Type** (if create_alias): One of:
   - `suffix_difference` - Jr/Sr/III difference
   - `nickname` - Known nickname
   - `typo` - Source typo
   - `source_variation` - Different data source format

4. **Confidence**: 0.0-1.0 score

5. **Reasoning**: Brief explanation

## Response Format (JSON)
```json
{
  "resolution_type": "create_alias|create_registry|invalid|unknown",
  "canonical_match": "player_lookup or null",
  "alias_type": "suffix_difference|nickname|typo|source_variation or null",
  "confidence": 0.95,
  "reasoning": "Brief explanation"
}
```

Common patterns to consider:
- Name suffixes (Jr., Sr., III, II)
- First name variations (Mike/Michael, Chris/Christopher)
- Hyphenated name variations
- Accented characters
- Middle name inclusion/exclusion
"""
```

### Output Schema

```python
from pydantic import BaseModel
from typing import Optional, Literal

class ResolutionDecision(BaseModel):
    resolution_type: Literal["create_alias", "create_registry", "invalid", "unknown"]
    canonical_match: Optional[str] = None
    alias_type: Optional[Literal["suffix_difference", "nickname", "typo", "source_variation"]] = None
    confidence: float  # 0.0-1.0
    reasoning: str
```

### Confidence Thresholds

| Confidence | Action |
|------------|--------|
| ≥ 0.95 | Auto-apply, log to audit |
| 0.90-0.94 | Auto-apply with notification |
| 0.70-0.89 | Queue for human review with suggestion |
| < 0.70 | Queue for human review, no auto-action |

---

## Implementation Plan

### Phase 1: Core Infrastructure

1. **Create AI Resolution Module** (`shared/utils/player_registry/ai_resolver.py`)
   - Claude API client wrapper
   - Context builder (gather registry data, roster, aliases)
   - Prompt template management
   - Response parsing and validation

2. **Create Audit Table** (`nba_reference.ai_resolution_log`)
   - Track all AI decisions for review
   - Store prompt, response, confidence, outcome

3. **Add Configuration**
   - API key management
   - Confidence thresholds
   - Batch size limits
   - Rate limiting

### Phase 2: Batch Processing

1. **Batch Resolution Script** (`tools/player_registry/ai_batch_resolve.py`)
   - Process pending unresolved names in batches
   - Apply confidence-based routing
   - Generate human review queue

2. **Integration with CLI Tool**
   - Add "AI assist" option to interactive mode
   - Show AI suggestions during manual review

### Phase 3: Real-time Integration

1. **Hook into RegistryReader**
   - Optional AI resolution for real-time processing
   - Configurable per-processor

2. **Monitoring & Alerts**
   - Dashboard for AI resolution accuracy
   - Alert on high unresolved counts
   - Track confidence distribution

---

## Technical Considerations

### API Usage

- **Model:** Claude 3.5 Sonnet (haiku for cost-sensitive batch)
- **Estimated tokens:** ~1000 input, ~200 output per resolution
- **Cost estimate:** ~$0.01 per 10 resolutions (Sonnet)

### Batch Processing Strategy

```python
async def process_batch(unresolved_names: List[Dict], batch_size: int = 10):
    """Process unresolved names in batches with rate limiting."""
    results = []

    for i in range(0, len(unresolved_names), batch_size):
        batch = unresolved_names[i:i + batch_size]

        # Build context for each name (can be parallelized)
        contexts = await asyncio.gather(*[
            build_context(name) for name in batch
        ])

        # Call Claude API (sequentially to respect rate limits)
        for name, context in zip(batch, contexts):
            result = await resolve_with_claude(name, context)
            results.append(result)

            # Rate limiting
            await asyncio.sleep(0.1)

    return results
```

### Error Handling

- API failures → retry with exponential backoff
- Parse failures → queue for human review
- Low confidence → queue for human review
- All decisions logged for audit

### Security

- API key stored in Secret Manager
- Audit trail for all AI decisions
- Human review for automated actions

---

## Files Reference

### Existing Files

| File | Purpose |
|------|---------|
| `tools/player_registry/resolve_unresolved_names.py` | CLI tool for manual resolution |
| `shared/utils/player_registry/reader.py` | Registry read-only access |
| `shared/utils/player_registry/resolver.py` | Universal ID resolution |
| `schemas/bigquery/nba_reference/unresolved_player_names_table.sql` | Unresolved queue schema |
| `schemas/bigquery/nba_reference/player_aliases_table.sql` | Alias mappings schema |

### New Files (Proposed)

| File | Purpose |
|------|---------|
| `shared/utils/player_registry/ai_resolver.py` | Claude API integration |
| `tools/player_registry/ai_batch_resolve.py` | Batch processing script |
| `schemas/bigquery/nba_reference/ai_resolution_log_table.sql` | Audit table |

---

## Success Metrics

1. **Resolution Rate:** % of unresolved names auto-resolved
2. **Accuracy:** % of AI decisions confirmed correct (via audit)
3. **Time Savings:** Hours saved vs. manual review
4. **Human Review Reduction:** % decrease in manual reviews needed

---

## Open Questions

1. **Confidence threshold tuning:** Start conservative (0.95) and adjust based on accuracy data?
2. **Batch vs. real-time:** Process during backfill only, or integrate into daily processing?
3. **Human-in-the-loop:** Should high-confidence decisions still require periodic spot-checks?
4. **Cost budget:** Maximum monthly spend on Claude API for this feature?

---

## Next Steps

1. [ ] Review and approve this design
2. [ ] Set up Claude API credentials
3. [ ] Implement Phase 1 core infrastructure
4. [ ] Test with sample of historical unresolved names
5. [ ] Tune confidence thresholds based on results
6. [ ] Deploy for backfill processing

---

---

## Investigation Findings (2025-12-05)

### Current Unresolved Volume

| Season | Total | Unique Names |
|--------|-------|--------------|
| 2025-26 | 44 | 42 |
| 2024-25 | 6 | 6 |
| 2023-24 | 657 | 572 |
| 2022-23 | 5 | 4 |
| 2021-22 | 7 | 6 |
| **Total** | **719** | **603** |

**Source Breakdown:**
- `basketball_reference`: 675 (94%)
- `br`: 25
- `espn`: 17
- `nba_com`: 2

### Critical Finding: Skipped Records = Lost Data

When a player lookup fails, the record is **skipped entirely**:

```python
# From player_game_summary_processor.py:810-814
universal_player_id = uid_map.get(player_lookup)
if universal_player_id is None:
    self.registry_stats['records_skipped'] += 1
    return None  # Data lost!
```

**Impact:** Unresolved names during backfill means player game data is not written. To recover, you must:
1. Resolve the name (create alias or registry entry)
2. Re-run the processor for affected dates

### Common Patterns Found

| Pattern Type | Example Unresolved | Registry Match | Resolution |
|--------------|-------------------|----------------|------------|
| Missing Jr./Sr. suffix | `marcusmorris` | `marcusmorrissr` | Create alias |
| Missing III/II suffix | `robertwilliams` | `robertwilliamsiii` | Create alias |
| Accented chars | `filippetruaev` (š→a) | `filippetrusev` | Create alias |
| Different suffix | `xaviertillmansr` | `xaviertillman` | Create alias |
| Timing issue | `kevinknox` | `kevinknox` (exists!) | Auto-cleanup |

### Timing Issue Discovery

Many "unresolved" names actually exist in the registry now:
- `kevinknox` marked unresolved for GSW/2025-26 but exists in registry
- `treymurphy` marked unresolved for NOP/2025-26 but exists in registry

This happens when:
1. Analytics processor runs before registry processor
2. Name logged as unresolved
3. Registry processor adds the player
4. Unresolved record not cleaned up

**Recommendation:** Add a cleanup job to auto-resolve names that now exist in registry.

### Cost Estimate

| Scenario | Volume | Est. Cost |
|----------|--------|-----------|
| Clear current backlog | ~600 unique names | ~$6-10 |
| Per-season backfill | ~50-100 new names | ~$0.50-1.00 |
| Daily operations | ~1-5 new names | < $0.01/day |

### Batch vs Real-time Decision

**Recommendation: Hybrid Approach**

1. **Batch (Primary):** Run AI resolution after each season/month during backfill
   - Process accumulated unresolved names
   - No impact on backfill speed
   - Can review high-volume patterns

2. **Optional Real-time:** For daily operations only
   - Lower volume, less impact
   - Could add latency (100-500ms per API call)
   - Consider caching frequent resolutions

### Prerequisites

- [ ] Install `anthropic` SDK: `pip install anthropic`
- [ ] Add `ANTHROPIC_API_KEY` to environment/Secret Manager
- [ ] Create audit table for AI decisions

---

## Session Log

| Date | Session | Notes |
|------|---------|-------|
| 2025-12-05 | Initial | Created project doc, analyzed existing system, investigated current data |
