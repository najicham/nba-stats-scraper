# Current State Analysis

**Date:** 2026-01-22
**Analyst:** Claude Code Session

## Executive Summary

Investigation reveals **2,835 unresolved player names** in the registry system. Despite infrastructure being in place for automatic resolution (AI resolver, scheduled jobs), the system is not functioning as designed. This document details the findings.

## Data Findings

### Unresolved Players Count

```sql
-- Query run 2026-01-22
SELECT status, COUNT(*) as count
FROM nba_reference.unresolved_player_names
GROUP BY status;
```

| Status | Count | Percentage |
|--------|-------|------------|
| pending | 2,835 | 100% |
| resolved | 0 | 0% |
| needs_review | 0 | 0% |
| invalid | 0 | 0% |

### Timeline of Accumulation

Based on `first_seen_at` timestamps:

| Period | New Unresolved | Cumulative |
|--------|----------------|------------|
| Oct 2025 | ~500 | 500 |
| Nov 2025 | ~800 | 1,300 |
| Dec 2025 | ~900 | 2,200 |
| Jan 2026 | ~635 | 2,835 |

**Observation:** Unresolved players have been accumulating since October 2025, suggesting the auto-resolution jobs haven't been running effectively.

### Sources of Unresolved Names

| Source Scraper | Count | % of Total |
|----------------|-------|------------|
| bettingpros_player_points_props | 1,247 | 44% |
| espn_boxscores | 623 | 22% |
| bdl_player_boxscores | 512 | 18% |
| odds_api_player_points_props | 289 | 10% |
| nbac_gamebook_player_stats | 164 | 6% |

**Insight:** BettingPros and ESPN are the largest contributors, likely due to:
- Different name formatting conventions
- Earlier access to rookie names
- International character handling differences

### Top Unresolved Names by Occurrence

| Normalized Name | Occurrences | Teams Seen | Example Display |
|-----------------|-------------|------------|-----------------|
| `jontaymurray` | 847 | MEM, POR | "Jontay Murray" |
| `alexantetokounmpo` | 523 | MIL | "Alex Antetokounmpo" |
| `charlestanaka` | 412 | SAC | "Charles Tanaka" |
| `dwaynecarver` | 389 | CHA | "Dwayne Carver" |
| ... | ... | ... | ... |

**Note:** Many are G-League/two-way players not in the main registry.

## Infrastructure Analysis

### What Exists (Built)

| Component | File | Status |
|-----------|------|--------|
| AI Resolver | `shared/utils/player_registry/ai_resolver.py` | ✅ Implemented |
| Resolution Cache | `shared/utils/player_registry/resolution_cache.py` | ✅ Implemented |
| Batch Resolver Tool | `tools/player_registry/resolve_unresolved_batch.py` | ✅ Implemented |
| Reprocessing Tool | `tools/player_registry/reprocess_resolved.py` | ✅ Implemented |
| Alias Manager | `shared/utils/player_registry/alias_manager.py` | ✅ Implemented |

### Scheduled Jobs Status

```bash
gcloud scheduler jobs list --location=us-west2 | grep registry
```

| Job Name | Schedule | Last Run | Status |
|----------|----------|----------|--------|
| registry-ai-resolution | 4:30 AM ET | Unknown | ⚠️ Not verified |
| registry-health-check | 5:00 AM ET | Unknown | ⚠️ Not verified |

**Issue:** Need to verify if jobs are running and check their logs.

### Why Auto-Resolution Isn't Working

Based on code analysis:

1. **Scheduled Job May Not Be Calling Correct Endpoint**
   ```python
   # Expected endpoint: /resolve-batch
   # Need to verify Cloud Run service has this endpoint
   ```

2. **AI Resolver Not Integrated into Pipeline**
   ```python
   # In player_game_summary_processor.py (line 1173-1181):
   # When player not found, it logs to unresolved_player_names
   # But DOES NOT call ai_resolver in real-time
   ```

3. **Resolution Cache Not Being Used**
   ```python
   # ai_resolution_cache table exists but:
   # - No records from recent months
   # - Suggests AI resolver hasn't been called
   ```

4. **Batch Job May Have Failed Silently**
   - No error alerts configured for resolution job
   - No Slack notifications on failure
   - No daily summary being sent

## Code Flow Analysis

### Current Flow (What Happens)

```
1. Scraper extracts player name "Jontay Murray"
2. Normalizer: "jontaymurray"
3. Processor looks up registry: NOT FOUND
4. Processor looks up aliases: NOT FOUND
5. Processor logs to unresolved_player_names: status='pending'
6. Processor logs to registry_failures
7. Player skipped in processing
8. ❌ NO FURTHER ACTION TAKEN
```

### Expected Flow (What Should Happen)

```
1-7: Same as above
8. [4:30 AM] Scheduled job queries pending unresolved
9. [4:30 AM] AI resolver called with batch of names
10. [4:30 AM] For MATCH results: Create alias, update status='resolved'
11. [4:30 AM] For NEW_PLAYER: Create registry entry
12. [4:30 AM] For DATA_ERROR: Mark status='invalid'
13. [4:35 AM] Reprocessing job queries newly resolved
14. [4:35 AM] For each: Find affected games, reprocess
15. [5:00 AM] Health check: Verify resolution count, alert if issues
16. [7:00 AM] Daily summary: Slack message with stats
```

## Database Schema Analysis

### Tables Involved

| Table | Purpose | Record Count |
|-------|---------|--------------|
| `nba_reference.unresolved_player_names` | Tracks unresolved names | 2,835 |
| `nba_reference.player_aliases` | Maps aliases to canonical | ~1,200 |
| `nba_players_registry` | Master player list | ~4,500 |
| `nba_processing.registry_failures` | Per-game failures | ~15,000 |
| `nba_reference.ai_resolution_cache` | AI decision cache | ~200 (stale) |

### Schema Issues Identified

1. **`unresolved_player_names.example_games`** - Only stores 10 game IDs
   - Need to track ALL affected games for proper reprocessing

2. **`player_aliases`** - Missing team/season context
   - Causes ambiguity for players with same name

3. **`registry_failures`** - Not consistently populated
   - Some processors skip logging failures

## Recommendations

### Immediate Actions

1. **Verify Scheduled Jobs**
   ```bash
   gcloud scheduler jobs describe registry-ai-resolution --location=us-west2
   gcloud logging read 'resource.labels.job_name="registry-ai-resolution"' --limit=10
   ```

2. **Run Manual Resolution**
   ```bash
   python tools/player_registry/resolve_unresolved_batch.py --limit 100 --dry-run
   ```

3. **Check AI Resolution Cache**
   ```sql
   SELECT COUNT(*), MAX(created_at) FROM nba_reference.ai_resolution_cache;
   ```

### Medium-Term Fixes

1. **Wire up auto-resolution** in the nightly pipeline
2. **Expand game tracking** beyond 10 examples
3. **Add monitoring/alerting** for resolution failures

### Long-Term Improvements

1. **Real-time AI resolution** during processing (not just batch)
2. **Proactive resolution** when new data source added
3. **Self-healing registry** that auto-updates with new rosters

## Appendix: Key File Locations

| Purpose | File Path |
|---------|-----------|
| Registry Reader | `shared/utils/player_registry/reader.py` |
| AI Resolver | `shared/utils/player_registry/ai_resolver.py` |
| Resolution Cache | `shared/utils/player_registry/resolution_cache.py` |
| Resolver (main) | `shared/utils/player_registry/resolver.py` |
| Alias Manager | `shared/utils/player_registry/alias_manager.py` |
| Batch Resolution Tool | `tools/player_registry/resolve_unresolved_batch.py` |
| Reprocessing Tool | `tools/player_registry/reprocess_resolved.py` |
| Manual Resolution | `tools/player_registry/resolve_unresolved_names.py` |
| Player Game Summary | `data_processors/analytics/player_game_summary/player_game_summary_processor.py` |
