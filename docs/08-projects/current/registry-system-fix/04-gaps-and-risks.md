# Known Gaps and Risks: Registry System

**Date:** 2026-01-10
**Status:** Active Monitoring Required
**Last Review:** 2026-01-10

---

## Risk Matrix

| Risk Level | Description |
|------------|-------------|
| CRITICAL | Data loss, system failure, production impact |
| HIGH | Significant data gaps, requires manual intervention |
| MEDIUM | Quality degradation, technical debt |
| LOW | Minor issues, nice-to-have fixes |

---

## Gap 1: No Automatic Reprocessing

**Risk Level:** HIGH
**Status:** Open
**Impact:** Data remains incomplete until manual intervention

### Description
After AI creates aliases (4:30 AM nightly), reprocessing requires manual CLI run:
```bash
python tools/player_registry/reprocess_resolved.py --resolved-since <date>
```

### Symptoms
- `registry_failures.resolved_at IS NOT NULL AND reprocessed_at IS NULL`
- Player data missing from `player_game_summary` despite alias existing
- Downstream predictions incomplete

### Current Workaround
Daily manual run of reprocessing script.

### Proposed Fix
Auto-trigger reprocessing after AI resolution completes. See [Implementation Plan](./02-implementation-plan.md#3-auto-trigger-reprocessing).

### Monitoring Query
```sql
SELECT
    player_lookup,
    COUNT(*) as games_affected,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(resolved_at), HOUR) as hours_since_resolved
FROM nba_processing.registry_failures
WHERE resolved_at IS NOT NULL
  AND reprocessed_at IS NULL
GROUP BY player_lookup
ORDER BY hours_since_resolved DESC;
```

---

## Gap 2: Manual Alias Creation Doesn't Update registry_failures

**Risk Level:** HIGH
**Status:** Open
**Impact:** Orphaned records, broken tracking

### Description
When using the interactive tool `resolve_unresolved_names.py` to manually create aliases, the `registry_failures` table is not updated with `resolved_at`.

### Code Location
`tools/player_registry/resolve_unresolved_names.py` line ~850

### Symptoms
- Alias exists in `player_aliases`
- `unresolved_player_names.status = 'resolved'`
- But `registry_failures.resolved_at = NULL` (orphaned)

### Current Workaround
After manual alias creation, run:
```sql
UPDATE nba_processing.registry_failures
SET resolved_at = CURRENT_TIMESTAMP()
WHERE player_lookup = '<the_player>'
  AND resolved_at IS NULL;
```

### Proposed Fix
Add `mark_registry_failures_resolved()` call to manual alias creation path.

### Monitoring Query
```sql
-- Find aliases without corresponding registry_failures updates
SELECT a.alias_lookup, a.created_at, a.created_by
FROM nba_reference.player_aliases a
LEFT JOIN (
    SELECT DISTINCT player_lookup
    FROM nba_processing.registry_failures
    WHERE resolved_at IS NOT NULL
) r ON a.alias_lookup = r.player_lookup
WHERE r.player_lookup IS NULL
  AND a.created_by = 'manual'
ORDER BY a.created_at DESC;
```

---

## Gap 3: Inconsistent Name Normalization Across Scrapers

**Risk Level:** MEDIUM
**Status:** Documented
**Impact:** Potential name mismatches, extra aliases needed

### Description
10+ Phase 2 scrapers use different name normalization implementations:
- Some handle diacritics, some don't
- Some remove periods, some don't
- Some remove suffixes, some don't

### Affected Files
| Scraper | Issue |
|---------|-------|
| `nbac_player_boxscore_processor.py` | No diacritic handling |
| `bdl_player_box_scores_processor.py` | No diacritic handling |
| `espn_boxscore_processor.py` | No diacritic handling |
| `bettingpros_player_props_processor.py` | No diacritic handling |
| (10+ more) | Various issues |

### Symptoms
- Same player appears with different `player_lookup` values from different sources
- Extra aliases needed to bridge the gap
- AI resolution cost increases

### Current Workaround
AI creates aliases to bridge normalization differences.

### Proposed Fix
Standardize all scrapers to use `normalize_name_for_lookup()` from shared utility.

### Risk of Fix
Changing normalization may create mismatches with existing aliases. Need migration plan:
1. Keep old method as fallback
2. Check both normalizations in alias lookup
3. Gradually migrate aliases to new format

---

## Gap 4: No AI Cache TTL or Invalidation

**Risk Level:** LOW
**Status:** Documented
**Impact:** Bad decisions persist forever

### Description
Entries in `ai_resolution_cache` have no expiration. A bad AI decision (wrong match, wrong DATA_ERROR classification) persists indefinitely.

### Symptoms
- Player consistently fails to resolve despite alias being possible
- Cache shows old decision preventing fresh resolution

### Current Workaround
Manual cache invalidation:
```sql
DELETE FROM nba_reference.ai_resolution_cache
WHERE unresolved_lookup = '<the_name>';
```

### Proposed Fix
Option A: Add 90-day TTL to cache entries
Option B: Add manual invalidation CLI tool
Option C: Confidence-based refresh (re-resolve low-confidence after 30 days)

---

## Gap 5: No Automatic Health Alerts

**Risk Level:** MEDIUM
**Status:** Documented
**Impact:** Silent failures go unnoticed

### Description
No automatic alerting when:
- Names stuck in "pending" for >24 hours
- Names stuck in "resolved" but not "reprocessed" for >24 hours
- AI resolution error rate spikes
- Reprocessing fails

### Current Workaround
Manual monitoring queries.

### Proposed Fix
Add scheduled health checks with alerts:
```python
# monitoring/resolution_health_check.py
def run_health_checks():
    check_stale_pending(hours=24)
    check_stale_resolved_not_reprocessed(hours=24)
    check_ai_error_rate(threshold=0.1)
    check_reprocessing_failures()
```

---

## Gap 6: Race Condition with New Players

**Risk Level:** LOW
**Status:** Accepted Risk
**Impact:** Occasional 1-day delay for new player data

### Description
When a player plays their first game:
1. Boxscore processed → Name resolution attempted
2. If roster sources haven't updated yet → Resolution fails
3. Next day: Roster updates, AI creates alias, reprocessing catches up

### Symptoms
- New player's first game data delayed by 1-2 days
- `registry_failures` entry exists for first game

### Current Workaround
Accept the delay. AI resolution + reprocessing catches up within 48 hours.

### Potential Fix
Proactive roster scraping before game tip-off, but complex and may not be worth it.

---

## Gap 7: example_games Array May Be Incomplete

**Risk Level:** LOW
**Status:** Documented
**Impact:** Some games might not reprocess

### Description
The `example_games` array in `unresolved_player_names` may not contain all game_ids where a player appeared.

### Code Location
`shared/utils/player_name_resolver.py` - limited array size for storage efficiency

### Symptoms
- Reprocessing finds fewer games than expected
- Some player-game records remain missing

### Current Workaround
Fallback query by date range in reprocessing tool:
```python
# reprocess_resolved.py line 259-262
games = self.get_games_by_date_range(start_date, end_date, [alias_lookup])
```

---

## Monitoring Dashboard Queries

### 1. Overall Health Status
```sql
SELECT
    (SELECT COUNT(*) FROM nba_reference.unresolved_player_names WHERE status = 'pending') as pending_count,
    (SELECT COUNT(DISTINCT player_lookup) FROM nba_processing.registry_failures
     WHERE resolved_at IS NOT NULL AND reprocessed_at IS NULL) as resolved_not_reprocessed,
    (SELECT COUNT(*) FROM nba_reference.ai_resolution_cache
     WHERE resolution_type = 'DATA_ERROR') as data_errors_cached,
    (SELECT COUNT(*) FROM nba_reference.player_aliases
     WHERE DATE(created_at) = CURRENT_DATE()) as aliases_created_today;
```

### 2. Pending Names by Age
```sql
SELECT
    CASE
        WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR) < 24 THEN '<24h'
        WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR) < 48 THEN '24-48h'
        WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR) < 168 THEN '2-7d'
        ELSE '>7d'
    END as age_bucket,
    COUNT(*) as count
FROM nba_reference.unresolved_player_names
WHERE status = 'pending'
GROUP BY age_bucket
ORDER BY age_bucket;
```

### 3. Resolution Rate by Day
```sql
SELECT
    DATE(created_at) as date,
    COUNT(*) as total_failures,
    COUNTIF(resolved_at IS NOT NULL) as resolved,
    COUNTIF(reprocessed_at IS NOT NULL) as reprocessed,
    ROUND(COUNTIF(reprocessed_at IS NOT NULL) / COUNT(*) * 100, 1) as completion_rate
FROM nba_processing.registry_failures
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date
ORDER BY date DESC;
```

### 4. AI Resolution Performance
```sql
SELECT
    resolution_type,
    COUNT(*) as count,
    ROUND(AVG(confidence), 3) as avg_confidence,
    COUNT(DISTINCT unresolved_lookup) as unique_names
FROM nba_reference.ai_resolution_cache
GROUP BY resolution_type;
```

---

## Incident Response Playbook

### Scenario: Large Number of Pending Names
1. Check if AI resolution job ran: `SELECT MAX(created_at) FROM ai_resolution_cache`
2. If not recent, manually trigger: `POST /resolve-pending`
3. Monitor progress: `SELECT COUNT(*) FROM unresolved_player_names WHERE status='pending'`

### Scenario: Resolved But Not Reprocessed >24h
1. Run reprocessing: `python reprocess_resolved.py --resolved-since <yesterday>`
2. Monitor: `SELECT COUNT(*) FROM registry_failures WHERE resolved_at IS NOT NULL AND reprocessed_at IS NULL`

### Scenario: Bad AI Decision Cached
1. Delete cache entry: `DELETE FROM ai_resolution_cache WHERE unresolved_lookup = '<name>'`
2. Reset unresolved status: `UPDATE unresolved_player_names SET status='pending' WHERE normalized_lookup='<name>'`
3. Wait for next AI resolution batch, or trigger manually

### Scenario: Player Data Missing Despite Alias Existing
1. Check `registry_failures` for the player
2. If `reprocessed_at IS NULL`, run reprocessing
3. If `resolved_at IS NULL`, run AI resolution first
4. Verify alias exists in `player_aliases`

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-01-10 | Initial document created | Claude Code |
| 2026-01-10 | Added process_single_game fix | Claude Code |
