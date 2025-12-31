# Session 50 Handoff: AI-Assisted Player Name Resolution

**Date:** 2025-12-05
**Status:** Deep Analysis Complete - Awaiting Opus Strategic Review
**Priority:** High - Blocking efficient backfill operations

---

## Executive Summary

This session conducted a comprehensive analysis of the player name resolution system to design an AI-assisted resolution feature. Three parallel investigation agents analyzed: (1) code flow, (2) backfill/reprocessing capabilities, and (3) schema completeness.

**Key Outcome:** Created a detailed consultation brief for Opus review before implementation.

---

## What Was Accomplished

### 1. System Analysis Complete

- Mapped complete data flow from scrapers → normalization → registry → analytics
- Identified 5 critical architectural gaps
- Analyzed 719 pending unresolved names (603 unique)
- Found that 94% of issues come from basketball_reference source

### 2. Gap Identification

| Gap | Risk | Description |
|-----|------|-------------|
| Data loss on failure | HIGH | Records skipped entirely, not flagged |
| No impact tracking | HIGH | Can't link unresolved names to affected records |
| No auto-reprocessing | HIGH | After resolution, nothing triggers data recovery |
| Race condition | MEDIUM | Concurrent ID creation can cause duplicates |
| No game context | MEDIUM | `example_games` array always empty |

### 3. Schema Analysis Complete

**New tables needed:**
1. `ai_resolution_log` - AI decision audit trail
2. `unresolved_name_impacts` - Link names to affected records
3. `name_resolution_reprocess_queue` - Automated reprocessing
4. `ai_resolution_metrics` - Daily monitoring

**Existing tables need additions:**
- `unresolved_player_names` - AI suggestion fields, impact tracking
- `player_aliases` - AI origin tracking, verification
- `processor_run_history` - AI integration fields

### 4. Documents Created

All in `docs/08-projects/current/ai-name-resolution/`:

| File | Purpose |
|------|---------|
| `README.md` | Original project overview and initial findings |
| `COMPREHENSIVE-ANALYSIS.md` | Full deep analysis with all agent findings |
| `OPUS-CONSULTATION-BRIEF.md` | Self-contained brief for Opus strategic review |

---

## Files to Read (Priority Order)

### Essential - Read These First

1. **`docs/08-projects/current/ai-name-resolution/OPUS-CONSULTATION-BRIEF.md`**
   - Complete context for the problem
   - All our recommendations
   - Open questions needing answers
   - This is the document to share with Opus

2. **`docs/08-projects/current/ai-name-resolution/COMPREHENSIVE-ANALYSIS.md`**
   - Detailed technical analysis
   - All gaps with code locations
   - Schema recommendations
   - Implementation roadmap

3. **`docs/06-reference/player-registry.md`**
   - Official reference doc for the registry system
   - API usage patterns
   - Common patterns and best practices

### Code - Understand the System

4. **`tools/player_registry/resolve_unresolved_names.py`**
   - CLI tool for manual resolution
   - Shows current workflow
   - Good starting point for AI integration

5. **`shared/utils/player_registry/reader.py`**
   - RegistryReader class (read-only access)
   - `get_universal_ids_batch()` - where batch lookups happen
   - `flush_unresolved_players()` - how unresolved get logged
   - Lines 855-954 critical for understanding unresolved tracking

6. **`shared/utils/player_registry/resolver.py`**
   - UniversalPlayerIDResolver class
   - Creates/resolves universal IDs
   - Race condition is here (lines 260-277)

7. **`data_processors/analytics/player_game_summary/player_game_summary_processor.py`**
   - Lines 647, 810-814 show data loss behavior
   - Where records get skipped

### Schemas - Understand the Data Model

8. **`schemas/bigquery/nba_reference/nba_players_registry_table.sql`**
9. **`schemas/bigquery/nba_reference/unresolved_player_names_table.sql`**
10. **`schemas/bigquery/nba_reference/player_aliases_table.sql`**
11. **`schemas/bigquery/nba_reference/unresolved_resolution_log_table.sql`**
12. **`schemas/bigquery/processing/processing_tables.sql`**

---

## Current State

### Unresolved Names Statistics

```
Total Pending: 719 (603 unique)
By Season: 2023-24 has 657 (bulk from backfill)
By Source: basketball_reference is 94%

Common Patterns:
- Missing Jr./Sr./III suffixes
- Accented character encoding differences
- Timing issues (name now exists in registry)
```

### What Hasn't Been Done Yet

1. **Opus consultation** - Brief created but not yet reviewed
2. **Schema creation** - New tables designed but not created
3. **Code implementation** - No AI integration code written
4. **API setup** - Anthropic SDK not installed, no credentials configured

---

## Next Steps (Recommended Order)

### Immediate: Opus Consultation

1. Copy contents of `OPUS-CONSULTATION-BRIEF.md`
2. Paste into Opus chat for strategic review
3. Get answers to open questions
4. Validate or revise approach

### After Opus Review

1. **Quick wins first:**
   - Auto-cleanup timing issue names (exist in registry now)
   - Fix `example_games` not being populated

2. **Schema changes:**
   - Create `ai_resolution_log` table
   - Add fields to existing tables

3. **Code implementation:**
   - Install anthropic SDK
   - Create `shared/utils/player_registry/ai_resolver.py`
   - Create batch processing script

4. **Testing:**
   - Test on sample of historical unresolved names
   - Tune confidence thresholds

---

## Key Decisions Pending

1. **Should we prevent data loss at source?**
   - Current: Skip unresolved records
   - Alternative: Write partial records with NULL universal_player_id
   - Opus should weigh in

2. **Batch vs real-time AI resolution?**
   - Batch during backfill seems right
   - Real-time for daily ops?
   - Need Opus guidance

3. **Confidence thresholds?**
   - Proposed 0.95 for auto-apply
   - May need adjustment

4. **Race condition fix?**
   - BigQuery MERGE vs distributed lock
   - Need architecture decision

---

## Technical Context

### Project Structure

```
/home/naji/code/nba-stats-scraper/
├── shared/utils/player_registry/     # Registry utilities
├── tools/player_registry/            # CLI tools
├── data_processors/
│   ├── reference/player_reference/   # Registry builders
│   └── analytics/                    # Uses registry
├── schemas/bigquery/
│   ├── nba_reference/                # Registry schemas
│   └── processing/                   # Run tracking schemas
└── docs/08-projects/current/ai-name-resolution/  # This project
```

### Key BigQuery Tables

```
nba_reference.nba_players_registry    # Authoritative player store
nba_reference.unresolved_player_names # Manual review queue
nba_reference.player_aliases          # Name variation mappings
nba_processing.analytics_processor_runs # Processor run history
```

### Environment

- Python 3.x with venv at `.venv/`
- Google Cloud (BigQuery, Cloud Run, Pub/Sub)
- No Anthropic SDK installed yet

---

## Commands to Get Started

```bash
# Activate virtual environment
source .venv/bin/activate

# Check current unresolved stats
python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT status, COUNT(*) as count
FROM \`nba-props-platform.nba_reference.unresolved_player_names\`
GROUP BY status
'''
for row in client.query(query):
    print(f'{row.status}: {row.count}')
"

# Run the CLI tool to see workflow
python -m tools.player_registry.resolve_unresolved_names stats
```

---

## Questions for New Session

If resuming this work:

1. Has Opus review been completed? If so, what were the recommendations?
2. Any decisions made on the pending questions?
3. Should we start with quick wins (cleanup timing issues) or full implementation?

---

## Session Log

| Session | Date | Focus |
|---------|------|-------|
| 50 | 2025-12-05 | Deep analysis, 3 agents, Opus brief created |

---

## Contact/Context

This is part of the NBA stats pipeline project. The player registry is critical infrastructure - all analytics depend on correct player identification. The AI resolution feature will significantly reduce manual work during backfill operations.
