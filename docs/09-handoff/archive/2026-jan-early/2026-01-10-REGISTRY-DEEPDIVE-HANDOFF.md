# Registry System Deep Dive - Handoff Document

**Priority**: CRITICAL
**Estimated Time**: 2-4 hours
**Scope**: Understand and fix the player name registry system

---

## Problem Statement

The player name registry system is critical for matching players across different data sources (ESPN, BettingPros, NBA.com, etc.). It's currently broken:

1. **Registry not being updated** - Last update was October 5, 2025
2. **AI resolver not being called** - 2,099 names stuck in "pending" status
3. **No automated triggers** - Processors exist but aren't scheduled

---

## Original Design Intent

Per user:
> "The original plan was to have it put names in a not found table and then I would manually review, then we switched to calling Claude API to have it look up the names and fix it."

### Flow Should Be:
```
Player name encountered
        ↓
Lookup in registry
        ↓
    ┌───┴───┐
 Found    Not Found
    ↓         ↓
 Return   Check aliases
    ↓         ↓
         ┌────┴────┐
      Found    Not Found
         ↓         ↓
      Return   AI Resolver (Claude)
         ↓         ↓
              ┌────┴────┐
           Resolved   Uncertain
              ↓           ↓
           Cache      Add to unresolved
           & Use      for manual review
```

---

## Current State

### Tables Involved
| Table | Purpose | Count | Status |
|-------|---------|-------|--------|
| `nba_reference.nba_players_registry` | Canonical player list | 684 | Stale (Oct 5) |
| `nba_reference.unresolved_player_names` | Names needing resolution | 2,818 | Active |
| `nba_reference.ai_resolution_cache` | Cached AI decisions | 0 | **EMPTY** |
| `nba_reference.player_aliases` | Alternate names | ? | Unknown |

### Unresolved Names Status
```
pending:  2,099  ← These need resolution!
resolved:   717
snoozed:      2
```

### Latest Unresolved (Added Today)
- `nikoladurisic` (ATL) - from player_game_summary
- `jahmaimashack` (MEM) - from player_game_summary
- `nolantraor` (BKN) - from player_game_summary
- `ronharper` (BOS) - from espn_roster_batch_processor

---

## Key Files to Investigate

### Core Registry Processors
```python
# Updates registry from roster scrapes (morning)
data_processors/reference/player_reference/roster_registry_processor.py

# Updates registry from gamebook after games (nightly)
data_processors/reference/player_reference/gamebook_registry_processor.py

# Entry points for both processors
data_processors/reference/main_reference_service.py
```

### AI Resolution System
```python
# The AI resolver using Claude API
shared/utils/player_registry/ai_resolver.py

# Caches AI decisions to avoid repeated API calls
shared/utils/player_registry/resolution_cache.py

# High-level name resolution (should call AI resolver)
shared/utils/player_name_resolver.py

# Alias management
shared/utils/player_registry/alias_manager.py
```

### Manual Review Tool
```python
# CLI tool for manual name review
tools/name_resolution_review.py

# Usage:
# python tools/name_resolution_review.py review
# python tools/name_resolution_review.py list --limit 20
```

### Configuration
```yaml
# Fallback chains for data sources
shared/config/data_sources/fallback_config.yaml
```

---

## Investigation Questions

### Q1: Why isn't the AI resolver being called?
Check:
- Is it hooked up in `player_name_resolver.py`?
- Is the Anthropic API key configured?
- Is there a feature flag disabling it?

### Q2: Why is the AI resolution cache empty?
Check:
- Was it cleared/reset at some point?
- Is the cache write logic working?
- Are there errors in logs?

### Q3: Why did registry updates stop in October?
Check:
- Were there scheduled jobs that got deleted?
- Did a Pub/Sub subscription break?
- Is there a manual cron that stopped?

### Q4: How should registry updates be automated?
Options:
1. Cloud Scheduler → HTTP endpoint on reference service
2. Pub/Sub trigger from gamebook processor completion
3. Add workflow to master controller

---

## Sample Queries for Investigation

```sql
-- Check unresolved by source
SELECT source, COUNT(*) as count
FROM nba_reference.unresolved_player_names
GROUP BY source
ORDER BY count DESC;

-- Check resolution types used
SELECT resolution_type, COUNT(*) as count
FROM nba_reference.unresolved_player_names
WHERE status = 'resolved'
GROUP BY resolution_type;

-- Check alias table
SELECT COUNT(*) as total_aliases
FROM nba_reference.player_aliases;

-- Check if any AI resolutions exist elsewhere
SELECT * FROM nba_reference.ai_resolution_cache LIMIT 10;
```

---

## Expected Outcomes from Deep Dive

1. **Understand the full resolution flow** - Document how names should flow through the system
2. **Fix AI resolver integration** - Get Claude API resolving names automatically
3. **Set up automation** - Cloud Scheduler jobs for registry updates
4. **Process pending names** - Clear the 2,099 pending backlog
5. **Add monitoring** - Alert when unresolved names pile up

---

## Related Documentation

- `/docs/09-handoff/2026-01-10-CRITICAL-ISSUES.md` - Full issues list
- `/shared/utils/player_registry/README.md` - Registry system docs (if exists)
