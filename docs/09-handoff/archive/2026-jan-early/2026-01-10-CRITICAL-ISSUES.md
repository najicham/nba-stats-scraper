# Critical Issues Identified - January 10, 2026

## Session 2 Status Update (11:30 AM ET)

### Fixes Applied:
1. ✅ **Master Controller Timezone Bug** - Added "too late" check to prevent `morning_operations` from running at 7 PM ET instead of 6-10 AM ET
2. ✅ **Roster Query Bug** - Changed from global MAX roster_date to per-team MAX roster_date
3. ✅ **Added SKIP_COMPLETENESS_CHECK env var** - For recovery situations

### Results After Fixes:
| Metric | Before | After |
|--------|--------|-------|
| Context Table Players | 79 | 211 |
| Teams Covered | 5 | 12 |
| Players with Props | 37 | 88 |

### Remaining Work:
- Feature store update (got stuck on missing Phase 4 data)
- Registry updates automation (separate session)
- ESPN scraper reliability investigation

---

## Summary

Investigation revealed **systemic failures** in the player data pipeline causing 42% prediction coverage instead of ~95%. Multiple interconnected issues need to be addressed.

---

## Issue #1: Registry Updates NOT Automated (CRITICAL)

**Status**: 🔴 Broken since October 2025

### Evidence
- `nba_players_registry` last updated: **October 5, 2025** (3+ months ago)
- 684 players in registry, but NOT refreshed from gamebook data
- AI resolution cache is EMPTY (0 records)
- 2,099 pending unresolved names, 717 resolved

### Root Cause
- `RosterRegistryProcessor` and `GamebookRegistryProcessor` exist but require **Pub/Sub triggers**
- **NO Cloud Scheduler job** publishes these triggers
- Master controller doesn't include registry update workflows
- Processors were manually run once in October, never again

### Original Design (Per User)
1. Put unresolved names in `unresolved_player_names` table (2,818 records)
2. Manual review via `tools/name_resolution_review.py`
3. OR use Claude API via `shared/utils/player_registry/ai_resolver.py` to auto-resolve

### Current State
- Unresolved names table IS being populated (last added today at 09:09)
- AI resolver EXISTS at `shared/utils/player_registry/ai_resolver.py`
- AI resolution cache is EMPTY - resolver not being called automatically
- 2,099 names stuck in "pending" status

### Fix Required
- [ ] Add Cloud Scheduler job for nightly registry update from gamebook
- [ ] Add Cloud Scheduler job for morning registry update from rosters
- [ ] Investigate why AI resolver is not being called
- [ ] Process the 2,099 pending unresolved names
- [ ] **NEEDS DEEP DIVE SESSION** - registry system is critical

---

## Issue #2: ESPN Roster Scraper Unreliable (HIGH)

**Status**: 🟠 Intermittently failing

### Evidence
| Date | Teams Scraped | Expected |
|------|---------------|----------|
| Jan 6 | 3 | 30 |
| Jan 8 | 30 | 30 |
| Jan 9 | 2 | 30 |

### Root Cause
- Rate limiting from ESPN API
- No exponential backoff in scraper
- No retry logic in workflow
- No alerting when scrape is incomplete

### Impact
- Context processor uses `espn_team_rosters` as primary roster source
- Incomplete roster → incomplete player context → incomplete predictions

### Fix Required
- [ ] Add retry logic with exponential backoff
- [ ] Add completeness validation (alert if <25 teams)
- [ ] Consider using `nba_players_registry` as primary source instead

---

## Issue #3: Schedule Scraper Completely Non-Functional (HIGH)

**Status**: 🔴 Was completely broken

### Evidence
- ALL schedule data (Jan 1-Apr 12) created at 2026-01-10 15:00:05 UTC
- Schedule was bulk-backfilled TODAY
- No schedule data existed before today

### Impact
- Context processor ran at 22:00 UTC on Jan 9 with NO schedule data
- Resulted in incomplete player context (79 players instead of ~180)

### Fix Required
- [ ] Investigate why schedule scraper stopped
- [ ] Add monitoring for schedule freshness
- [ ] Ensure schedule is scraped BEFORE context processor runs

---

## Issue #4: Context Processor Has No Fallbacks (HIGH)

**Status**: 🟠 Design flaw

### Evidence
Context processor (`upcoming_player_game_context_processor.py`) only uses:
- `nba_raw.nbac_schedule` - was EMPTY
- `nba_raw.espn_team_rosters` - only 2 teams

Does NOT use:
- `nba_reference.nba_schedule` - had ALL 6 games
- `nba_players_registry` - has 682 players, 30 teams
- `nbac_player_list_current` - has 615 players, 30 teams

### Impact
When primary sources fail, entire prediction pipeline fails.

### Fix Required
- [ ] Add fallback chain: `espn_rosters` → `nba_players_registry` → `nbac_player_list`
- [ ] Use `nba_reference.nba_schedule` as fallback for schedule
- [ ] Log which fallback was used

---

## Issue #5: NBA.com Player List Stale (MEDIUM)

**Status**: 🟠 Not maintained

### Evidence
- `nbac_player_list_current` last updated: October 1, 2025
- 615 players, 30 teams
- Could be used as roster fallback but isn't being refreshed

### Fix Required
- [ ] Add Cloud Scheduler job for regular NBA.com player list scraping
- [ ] Or deprecate if ESPN roster is reliable enough

---

## Issue #6: Jan 9 Grading Not Completed (MEDIUM)

**Status**: 🟠 Behind

### Evidence
- Last graded date: Jan 7
- Jan 8 and Jan 9 NOT graded

### Fix Required
- [ ] Run grading for Jan 8 and Jan 9
- [ ] Investigate why grading pipeline stopped

---

## Issue #7: Master Controller Timezone Bug (CRITICAL)

**Status**: ✅ Fixed

### Evidence
- `morning_operations` ran at **7:08 PM ET** on Jan 9
- Should have run between **6-10 AM ET**
- Caused by bug in `_evaluate_self_aware()` - only checked "too early", not "too late"

### Root Cause
```python
# BUGGY CODE:
if current_hour < ideal_start:
    return SKIP  # Only checked too early
# Falls through to RUN even at 7 PM!
```

At 7 PM ET (hour=19) with ideal_window 6-10:
- current_hour (19) < ideal_start (6)? NO → doesn't skip
- Falls through to RUN, just with alert_level=WARNING

### Impact
- `morning_operations` ran at 7 PM ET instead of 6-10 AM ET
- This was AFTER `same-day-phase3-tomorrow` ran at 12 PM ET
- Context processor used stale roster data (only 2 teams from ESPN)

### Fix Applied
Added "too late" check in `orchestration/master_controller.py`:
```python
if current_hour > ideal_end:
    # Too late - schedule for tomorrow morning
    tomorrow = current_time + timedelta(days=1)
    return WorkflowDecision(
        action=DecisionAction.SKIP,
        reason=f"Too late (ideal window: {ideal_start}-{ideal_end} ET)",
        ...
    )
```

### Verification
With this fix:
- morning_operations will now ONLY run between 6-10 AM ET
- Context processor (12 PM ET) will use fresh roster data from morning run

---

## Issue #8: Circuit Breaker Lockout Too Long (LOW)

**Status**: 🟢 Quick fix available

### Current Setting
7 days lockout after failures

### Recommendation
Reduce to 24 hours (documented in robustness session handoff)

---

## Available But Unused Data Sources

| Source | Records | Last Updated | Could Be Used For |
|--------|---------|--------------|-------------------|
| `nba_reference.nba_schedule` | 6 games Jan 10 | Unknown | Schedule fallback |
| `nba_players_registry` | 682 players | Oct 5 2025 | Roster fallback |
| `nbac_player_list_current` | 615 players | Oct 1 2025 | Roster fallback |
| `nbac_gamebook_player_stats` | Active | Jan 9 2026 | Registry updates |

---

## Immediate Actions Required

### Today (Fix Jan 10 Predictions)
1. Re-run `upcoming_player_game_context` processor for Jan 10
2. Re-run `ml_feature_store` processor for Jan 10
3. Re-run predictions for Jan 10

### This Week
1. **Deep dive on registry system** (separate session)
   - Understand why AI resolver isn't being called
   - Process 2,099 pending unresolved names
   - Set up automated registry updates
2. Fix ESPN scraper reliability
3. Add fallback chain to context processor

### Long-term
1. Make registry the authoritative player source
2. Add comprehensive monitoring/alerting
3. Document the player data architecture

---

## Files to Review for Registry Deep Dive

```
# Core registry processors
data_processors/reference/player_reference/roster_registry_processor.py
data_processors/reference/player_reference/gamebook_registry_processor.py
data_processors/reference/main_reference_service.py

# AI resolution system
shared/utils/player_registry/ai_resolver.py
shared/utils/player_registry/resolution_cache.py
shared/utils/player_name_resolver.py

# Manual review tool
tools/name_resolution_review.py

# Fallback configuration
shared/config/data_sources/fallback_config.yaml

# Orchestration (missing registry workflows)
orchestration/master_controller.py
```

---

## Related Handoff Documents

- `docs/09-handoff/2026-01-10-INVESTIGATION-HANDOFF.md` - Original investigation queries
- `docs/09-handoff/2026-01-10-ROBUSTNESS-SESSION-HANDOFF.md` - Robustness improvements backlog
