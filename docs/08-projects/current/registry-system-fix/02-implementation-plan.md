# Implementation Plan: Registry System Fixes

**Date:** 2026-01-10
**Status:** Active
**Owner:** Engineering Team

## Priority Matrix

| Priority | Criteria |
|----------|----------|
| P0 - Critical | Data loss, system broken, blocking production |
| P1 - High | Significant data gaps, manual workarounds needed |
| P2 - Medium | Quality issues, technical debt |
| P3 - Low | Nice to have, future improvement |

---

## Completed Work (P0)

### ✅ 1. Implement `process_single_game()` Method
**Priority:** P0 - Critical
**Status:** COMPLETE
**Commit:** `56cf1a7`

**Problem:** Reprocessing tool called non-existent method, all reprocessing failed silently.

**Solution:**
- Added `process_single_game(game_id, game_date, season)` to PlayerGameSummaryProcessor
- Added `_extract_single_game_data()` for parameterized queries
- Added `_save_single_game_records()` for atomic MERGE

**Files Changed:**
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` (+320 lines)
- `tools/player_registry/reprocess_resolved.py` (date conversion fix)

---

### ✅ 2. Add DATA_ERROR Cache Handling
**Priority:** P0 - Critical
**Status:** COMPLETE
**Commit:** `e5225b2`

**Problem:** Known bad names (typos) were re-added to unresolved queue on every encounter.

**Solution:**
- Check for DATA_ERROR cache hits before queuing
- Return None immediately for cached bad names
- Added warning log for alias creation failures

**Files Changed:**
- `shared/utils/player_name_resolver.py` (+15 lines)
- `shared/utils/tests/test_player_name_resolver.py` (rewritten, 11 tests)

---

## Planned Work

### 3. Auto-Trigger Reprocessing After AI Resolution
**Priority:** P1 - High
**Status:** PLANNED
**Effort:** Medium (4-8 hours)

**Problem:** After AI creates aliases, reprocessing requires manual CLI run. Data stays incomplete.

**Proposed Solution:**

Option A: **Extend AI Batch Resolution** (Recommended)
```python
# In resolve_unresolved_batch.py, after creating aliases:
def resolve_batch():
    # ... existing alias creation ...

    # NEW: Auto-trigger reprocessing for resolved games
    if aliases_created > 0:
        reprocessor = ReprocessingOrchestrator()
        reprocessor.reprocess_all(resolved_since=batch_start_time)
```

Option B: **Separate Scheduler Job**
- Add Cloud Scheduler job at 5:00 AM ET
- Runs after AI resolution (4:30 AM)
- Calls `/reprocess-resolved` endpoint

Option C: **Event-Driven via Pub/Sub**
- AI resolution publishes to `registry-aliases-created` topic
- Reprocessing service subscribes and triggers

**Recommendation:** Option A is simplest, keeps logic together. Option C is most scalable.

**Files to Modify:**
- `tools/player_registry/resolve_unresolved_batch.py`
- OR `data_processors/reference/main_reference_service.py`
- OR new Pub/Sub handler

---

### 4. Fix Manual Alias Creation Gap
**Priority:** P1 - High
**Status:** PLANNED
**Effort:** Small (1-2 hours)

**Problem:** `resolve_unresolved_names.py` creates aliases but doesn't update `registry_failures.resolved_at`.

**Solution:**
```python
# In resolve_unresolved_names.py, create_alias() method:
def create_alias(self, source_name, target_name):
    if self.alias_manager.create_alias(source_name, target_name):
        # Existing: mark unresolved_player_names as resolved
        self.mark_as_resolved(source_name)

        # NEW: Also update registry_failures
        self.mark_registry_failures_resolved(source_name)
```

**Files to Modify:**
- `tools/player_registry/resolve_unresolved_names.py`

---

### 5. Standardize Scraper Normalization
**Priority:** P2 - Medium
**Status:** PLANNED
**Effort:** Large (8-16 hours)

**Problem:** 10+ scrapers use different name normalization, causing potential mismatches.

**Solution:** Replace all local implementations with shared utility.

**Files to Modify:**

| File | Current Method | Change To |
|------|----------------|-----------|
| `nbac_player_boxscore_processor.py` | Local `normalize_player_name()` | `normalize_name_for_lookup()` |
| `nbac_play_by_play_processor.py` | Local `normalize_player_name()` | `normalize_name_for_lookup()` |
| `nbac_injury_report_processor.py` | Local `_normalize_player_name()` | `normalize_name_for_lookup()` |
| `bdl_player_box_scores_processor.py` | Local `normalize_player_name()` | `normalize_name_for_lookup()` |
| `bdl_boxscores_processor.py` | Local `normalize_player_name()` | `normalize_name_for_lookup()` |
| `bdl_live_boxscores_processor.py` | Local `normalize_player_name()` | `normalize_name_for_lookup()` |
| `espn_boxscore_processor.py` | Local `normalize_player_name()` | `normalize_name_for_lookup()` |
| `espn_team_roster_processor.py` | Local `_normalize_player_name()` | `normalize_name_for_lookup()` |
| `bettingpros_player_props_processor.py` | Local `normalize_player_name()` | `normalize_name_for_lookup()` |
| `bigdataball_pbp_processor.py` | Local `normalize_player_name()` | `normalize_name_for_lookup()` |

**Template Change:**
```python
# BEFORE
def normalize_player_name(self, name: str) -> str:
    normalized = name.lower().strip()
    normalized = re.sub(r'\s+(jr\.?|sr\.?|ii+|iv|v)$', '', normalized)
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    return normalized

# AFTER
from shared.utils.player_name_normalizer import normalize_name_for_lookup

# In processing method:
player_lookup = normalize_name_for_lookup(player_name)
```

**Risk:** Changing normalization may create mismatches with existing aliases. Need migration plan.

---

### 6. Add Health Check Alerts
**Priority:** P2 - Medium
**Status:** PLANNED
**Effort:** Medium (4-8 hours)

**Problem:** No automatic alerts when:
- Names stuck in "pending" for >24 hours
- Names stuck in "resolved" but not "reprocessed" for >24 hours
- AI resolution error rate spikes

**Solution:**

```python
# In monitoring/resolution_health_check.py

def check_stale_pending(hours_threshold=24):
    """Alert if pending names older than threshold."""
    query = """
    SELECT COUNT(*) as count
    FROM nba_reference.unresolved_player_names
    WHERE status = 'pending'
    AND created_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
    """
    if count > 0:
        notify_warning(f"{count} names pending for >{hours_threshold}h")

def check_stale_resolved(hours_threshold=24):
    """Alert if resolved but not reprocessed for too long."""
    query = """
    SELECT COUNT(DISTINCT player_lookup) as count
    FROM nba_processing.registry_failures
    WHERE resolved_at IS NOT NULL
    AND reprocessed_at IS NULL
    AND resolved_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
    """
    if count > 0:
        notify_warning(f"{count} players resolved but not reprocessed for >{hours_threshold}h")
```

**Files to Modify:**
- `monitoring/resolution_health_check.py`
- `bin/orchestration/add_registry_scheduler_jobs.sh` (add health check job)

---

### 7. Add AI Cache TTL/Invalidation
**Priority:** P3 - Low
**Status:** PLANNED
**Effort:** Medium (4-8 hours)

**Problem:** Bad AI decisions cached forever with no way to invalidate.

**Solution Options:**

Option A: **Add TTL to Cache Table**
```sql
ALTER TABLE nba_reference.ai_resolution_cache
ADD COLUMN expires_at TIMESTAMP;

-- Set 90-day TTL
UPDATE nba_reference.ai_resolution_cache
SET expires_at = TIMESTAMP_ADD(created_at, INTERVAL 90 DAY);
```

Option B: **Manual Invalidation CLI**
```bash
python tools/player_registry/invalidate_cache.py --lookup "badname"
```

Option C: **Confidence-Based Refresh**
- Re-resolve names with confidence < 0.8 after 30 days
- Higher confidence entries persist longer

**Recommendation:** Option A for simplicity, add Option B for manual overrides.

---

### 8. Process Older Season Failures
**Priority:** P3 - Low
**Status:** PLANNED
**Effort:** Small (2-4 hours)

**Problem:** 911 failures from 2021-2024 seasons need resolution.

**Solution:**
```bash
# One-time backfill
python tools/player_registry/resolve_unresolved_batch.py --limit 1000 --include-historical

# Then reprocess
python tools/player_registry/reprocess_resolved.py --resolved-since 2021-01-01
```

**Consideration:** Historical data may have different name formats, need to verify aliases work.

---

## Implementation Order

```
Phase 1 (Immediate - Next Deploy)
├─ ✅ process_single_game() - DONE
├─ ✅ DATA_ERROR handling - DONE
├─ Deploy reference service
└─ Run scheduler setup

Phase 2 (This Week)
├─ Auto-trigger reprocessing (#3)
├─ Fix manual alias gap (#4)
└─ Add health check alerts (#6)

Phase 3 (Next Sprint)
├─ Standardize scraper normalization (#5)
└─ Process older seasons (#8)

Phase 4 (Future)
└─ Add AI cache TTL (#7)
```

---

## Testing Plan

### Unit Tests
- ✅ `test_player_name_resolver.py` - 11 tests for cache handling
- TODO: Tests for auto-reprocessing trigger
- TODO: Tests for health check thresholds

### Integration Tests
```bash
# Test full flow
1. Insert fake failure to registry_failures
2. Run AI resolution
3. Verify alias created
4. Run reprocessing
5. Verify data in player_game_summary
6. Verify registry_failures.reprocessed_at set
```

### Dry Run Validation
```bash
# Always dry-run first
python tools/player_registry/resolve_unresolved_batch.py --dry-run --limit 10
python tools/player_registry/reprocess_resolved.py --dry-run --resolved-since 2025-01-01
```

---

## Rollback Plan

### If process_single_game() causes issues:
```bash
git revert 56cf1a7
# Reprocessing will fail again but won't cause new problems
```

### If normalization changes cause mismatches:
1. Keep old normalization methods as fallbacks
2. Check both old and new normalized forms in alias lookup
3. Gradually migrate aliases to new format

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Pending names >24h old | Unknown | 0 |
| Resolved but not reprocessed >24h | Unknown | 0 |
| AI resolution success rate | ~95% | >98% |
| Data completeness (player_game_summary) | ~95% | >99% |
| Manual intervention required | Daily | Weekly or less |
