# Player Name Resolution System - Implementation Plan v2

**Created:** 2025-12-06 11:30 PST (Session 52)
**Last Updated:** 2025-12-06 11:45 PST
**Status:** Ready for Implementation
**Author:** Human + Claude
**Version:** 2.1 (AI-First with Caching)

---

## Executive Summary

After comprehensive analysis of the data flow, gaps, and options, here is the recommended implementation plan.

### Key Insight
The 83% "timing issues" are a **backfill-specific problem** caused by not respecting phase order. In daily ops, Phase 1 (registry) runs before Phase 3 (analytics), so timing issues don't occur. The solution is **two-pass backfill** that enforces registry-first ordering.

### Recommendation
- **For Backfill:** Two-pass approach (Registry THEN Analytics) + batch resolution AFTER
- **For Daily Ops:** Post-Phase 3 resolution hook (should rarely trigger)
- **For All:** Fix RegistryReader to check aliases

---

## 1. Root Cause Analysis

### Why Timing Issues Happen (83% of queue)

```
CURRENT BACKFILL (Wrong Order):
┌─────────────────┐     ┌─────────────────┐
│   Analytics     │     │    Registry     │
│   Processor     │ ──▶ │   Processor     │  (may run in parallel or wrong order)
│                 │     │                 │
│ Queries registry│     │ Populates       │
│ BEFORE it's     │     │ registry        │
│ populated!      │     │                 │
└─────────────────┘     └─────────────────┘
         │
         ▼
    UNRESOLVED! (but player exists, just not yet)
```

```
DAILY OPS (Correct Order):
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    Phase 1      │     │    Phase 2      │     │    Phase 3      │
│   Registry      │ ──▶ │   Raw Data      │ ──▶ │   Analytics     │
│   (populated)   │     │                 │     │   (queries)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
                                                   FOUND! ✓
```

### Why True Mismatches Happen (10 unique names)

Different data sources normalize names differently:

| Source | Name | Normalized |
|--------|------|------------|
| Basketball-Reference | "Marcus Morris" | `marcusmorris` |
| NBA.com Registry | "Marcus Morris Sr." | `marcusmorrissr` |

These require **aliases** to bridge the gap.

---

## 2. Recommended Approach: Two-Pass + Batch Resolution

### For Backfill (4 Seasons)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        BACKFILL EXECUTION PLAN                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PASS 1: REGISTRY (Eliminates timing issues)                               │
│  ═══════════════════════════════════════════                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ python backfill_jobs/reference/gamebook_registry/                    │   │
│  │        gamebook_registry_reference_backfill.py                       │   │
│  │        --start-date 2021-10-19 --end-date 2025-06-22                │   │
│  │        --strategy merge                                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  Result: nba_players_registry fully populated                              │
│  Time: ~2-4 hours                                                          │
│                                                                             │
│  PASS 2: ANALYTICS (Most will resolve now)                                 │
│  ═══════════════════════════════════════════                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ python backfill_jobs/analytics/player_game_summary/                  │   │
│  │        player_game_summary_analytics_backfill.py                     │   │
│  │        --start-date 2021-10-19 --end-date 2025-06-22                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  Result: ~99% of players resolved, only true mismatches remain             │
│  Time: ~4-8 hours                                                          │
│                                                                             │
│  PASS 3: RESOLUTION (Handle true mismatches)                               │
│  ═══════════════════════════════════════════                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ python tools/player_registry/resolve_unresolved_batch.py             │   │
│  │        --use-fuzzy --use-ai --auto-create-aliases                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  Result: Aliases created for all resolvable names                          │
│  Time: ~30 minutes                                                         │
│                                                                             │
│  PASS 4: REPROCESS (Fix affected games)                                    │
│  ═══════════════════════════════════════════                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ python tools/player_registry/reprocess_resolved.py                   │   │
│  │        --resolved-since "2025-12-06"                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  Result: 100% player resolution                                            │
│  Time: Depends on affected dates                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why "After" Instead of "During"?

| Factor | During (per batch) | After (batch at end) |
|--------|-------------------|---------------------|
| **Efficiency** | Resolves same alias multiple times | Resolves each alias once |
| **Complexity** | Complex orchestration | Simple linear passes |
| **Data Consistency** | Clean as you go | Inconsistent until end |
| **Debugging** | Harder to trace issues | Clear separation of concerns |
| **Risk** | Higher (more moving parts) | Lower (simpler) |

**My Recommendation: "After"** because:
1. True mismatches are only ~10 unique names
2. Same player appears in many games (resolve once, fix many)
3. Simpler to implement and debug
4. The two-pass approach eliminates 83% of issues before resolution even runs

### For Daily Ops

Daily ops should NOT have timing issues (Phase 1 runs before Phase 3). But as a safety net:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DAILY PIPELINE WITH RESOLUTION                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Phase 1 (Reference)    Phase 2 (Raw)    Phase 3 (Analytics)               │
│  ═══════════════════    ═════════════    ══════════════════                │
│        │                      │                  │                          │
│        ▼                      ▼                  ▼                          │
│  ┌──────────┐          ┌──────────┐       ┌──────────┐                     │
│  │ Registry │   ──▶    │   Raw    │  ──▶  │ Analytics│                     │
│  │ Processor│          │Processors│       │Processors│                     │
│  └──────────┘          └──────────┘       └──────────┘                     │
│                                                  │                          │
│                                                  ▼                          │
│                                           ┌──────────────┐                  │
│                                           │ Post-Phase 3 │  ◄── NEW        │
│                                           │ Resolution   │                  │
│                                           │ Hook         │                  │
│                                           └──────────────┘                  │
│                                                  │                          │
│                                                  ▼                          │
│                                    ┌─────────────────────────┐              │
│                                    │ Unresolved count > 0?   │              │
│                                    └─────────────────────────┘              │
│                                          │           │                      │
│                                         YES          NO                     │
│                                          │           │                      │
│                                          ▼           ▼                      │
│                                    ┌──────────┐ ┌──────────┐               │
│                                    │Run Fuzzy │ │Continue  │               │
│                                    │+ AI      │ │to Phase 4│               │
│                                    │Resolution│ │          │               │
│                                    └──────────┘ └──────────┘               │
│                                          │                                  │
│                                          ▼                                  │
│                                    ┌──────────┐                             │
│                                    │Reprocess │                             │
│                                    │Today's   │                             │
│                                    │Games     │                             │
│                                    └──────────┘                             │
│                                          │                                  │
│                                          ▼                                  │
│                                     Continue to Phase 4                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Implementation Phases

### Phase 1: Fix RegistryReader Gap (Priority: CRITICAL)
**Time:** 1-2 hours
**Impact:** Makes existing aliases work

```python
# In shared/utils/player_registry/reader.py
# Modify get_universal_ids_batch() to check aliases

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

### Phase 2: Two-Pass Backfill Script (Priority: HIGH)
**Time:** 1-2 hours
**Impact:** Eliminates 83% of timing issues

New file: `bin/backfill/run_two_pass_backfill.sh`

```bash
#!/bin/bash
# Two-Pass Backfill: Registry THEN Analytics
# Eliminates timing issues by ensuring registry is populated first

# Pass 1: Registry
echo "=== PASS 1: Populating Registry ==="
python backfill_jobs/reference/gamebook_registry/gamebook_registry_reference_backfill.py \
    --start-date $START_DATE --end-date $END_DATE --strategy merge

# Pass 2: Analytics
echo "=== PASS 2: Running Analytics ==="
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
    --start-date $START_DATE --end-date $END_DATE
```

### Phase 3: Fuzzy Matcher (Priority: MEDIUM)
**Time:** 2-3 hours
**Impact:** Auto-resolves suffix/encoding issues without AI

New file: `shared/utils/player_registry/fuzzy_matcher.py`

```python
class FuzzyMatcher:
    """Rule-based name resolution for common patterns."""

    SUFFIXES = ['jr', 'sr', 'ii', 'iii', 'iv', 'v']

    def find_match(self, unresolved: str, candidates: List[str]) -> Optional[Match]:
        # Try adding suffixes
        for suffix in self.SUFFIXES:
            if f"{unresolved}{suffix}" in candidates:
                return Match(f"{unresolved}{suffix}", 'suffix_added', 0.95)

        # Try removing suffixes
        for suffix in self.SUFFIXES:
            if unresolved.endswith(suffix):
                base = unresolved[:-len(suffix)]
                if base in candidates:
                    return Match(base, 'suffix_removed', 0.95)

        # Try Levenshtein distance for encoding issues
        for candidate in candidates:
            if levenshtein(unresolved, candidate) <= 2:
                return Match(candidate, 'encoding', 0.85)

        return None
```

### Phase 4: AI Resolver (Priority: MEDIUM)
**Time:** 3-4 hours
**Impact:** Handles uncertain cases without manual review

New file: `shared/utils/player_registry/ai_resolver.py`

```python
class AINameResolver:
    """Claude API integration for uncertain name matches."""

    def __init__(self):
        self.client = anthropic.Anthropic()
        self.model = "claude-3-haiku-20240307"  # Fast and cheap

    def resolve_batch(self, unresolved: List[UnresolvedName]) -> List[Resolution]:
        # Build prompt with context
        # Call Claude API
        # Parse response
        # Return resolutions with confidence scores
```

### Phase 5: Reprocessing Component (Priority: HIGH)
**Time:** 2-3 hours
**Impact:** Fixes historical data when aliases are created

New file: `tools/player_registry/reprocess_resolved.py`

```python
def reprocess_for_resolved_aliases(resolved_since: date):
    """Re-run analytics for games affected by newly created aliases."""

    # Get newly resolved names
    resolved = get_recently_resolved(resolved_since)

    # Get affected dates from unresolved records
    # (This requires fixing example_games - see Phase 6)
    affected_dates = get_affected_dates(resolved)

    # Re-run analytics for those dates
    for date in affected_dates:
        run_analytics_for_date(date)
```

### Phase 6: Fix Context Capture (Priority: HIGH)
**Time:** 1 hour
**Impact:** Enables identifying which games need reprocessing

```python
# In player_game_summary_processor.py
# When logging unresolved, include game context

# Current (broken):
uid_map = self.registry.get_universal_ids_batch(unique_players)

# Fixed:
uid_map = self.registry.get_universal_ids_batch(
    unique_players,
    context={
        'game_id': current_game_id,
        'game_date': current_game_date,
        'season': season
    }
)
```

---

## 4. Implementation Timeline

```
Week 1: Foundation
├── Day 1-2: Phase 1 (Fix RegistryReader) + Phase 6 (Fix context capture)
├── Day 3-4: Phase 2 (Two-pass backfill script)
└── Day 5: Test on small date range

Week 2: Resolution System
├── Day 1-2: Phase 3 (Fuzzy matcher)
├── Day 3-4: Phase 4 (AI resolver)
├── Day 5: Phase 5 (Reprocessing component)

Week 3: Integration & Backfill
├── Day 1: Integration testing
├── Day 2-5: Run 4-season backfill with new system
```

---

## 5. Immediate Actions (Before Full Build)

For the current 719 pending records:

### Step 1: Auto-resolve timing issues (599 records)
```sql
UPDATE `nba-props-platform.nba_reference.unresolved_player_names` u
SET
    status = 'resolved',
    resolution_type = 'timing_auto',
    reviewed_by = 'session52_cleanup',
    reviewed_at = CURRENT_TIMESTAMP(),
    notes = 'Auto-resolved: exact match exists in registry for same season'
WHERE status = 'pending'
  AND EXISTS (
    SELECT 1 FROM `nba-props-platform.nba_reference.nba_players_registry` r
    WHERE u.normalized_lookup = r.player_lookup
      AND u.season = r.season
  );
```

### Step 2: Create aliases for true mismatches (8 aliases)
```sql
INSERT INTO `nba-props-platform.nba_reference.player_aliases`
(alias_lookup, nba_canonical_lookup, alias_display, nba_canonical_display,
 alias_type, alias_source, is_active, created_by, created_at, processed_at)
VALUES
('marcusmorris', 'marcusmorrissr', 'Marcus Morris', 'Marcus Morris Sr.',
 'suffix_difference', 'session52_cleanup', TRUE, 'session52', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
-- ... (other 7 aliases)
```

### Step 3: Mark aliased names as resolved
```sql
UPDATE `nba-props-platform.nba_reference.unresolved_player_names`
SET status = 'resolved', resolution_type = 'alias_created', ...
WHERE normalized_lookup IN ('marcusmorris', 'robertwilliams', ...);
```

### Step 4: Handle season mismatches (2 records)
```sql
UPDATE `nba-props-platform.nba_reference.unresolved_player_names`
SET status = 'snoozed', snooze_until = DATE_ADD(CURRENT_DATE(), INTERVAL 30 DAY), ...
WHERE normalized_lookup IN ('ronholland', 'jeenathanwilliams');
```

---

## 6. Resolution Pipeline Architecture (AI-First)

**Philosophy:** Use AI for ALL uncertain cases. No fuzzy guessing. AI decisions are cached to avoid repeat API calls.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RESOLUTION PIPELINE (AI-First, No Manual Review)         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Input: unresolved_lookup = "marcusmorris"                                  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 1: DIRECT LOOKUP                                              │   │
│  │ Query: SELECT * FROM registry WHERE player_lookup = 'marcusmorris'  │   │
│  │ Result: NOT FOUND → continue                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 2: ALIAS LOOKUP                                               │   │
│  │ Query: SELECT canonical FROM aliases WHERE alias = 'marcusmorris'   │   │
│  │ Result: Found 'marcusmorrissr' → RESOLVED ✓                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼ (if not found)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 3: AI RESOLUTION CACHE CHECK                                  │   │
│  │ Query: SELECT * FROM ai_resolution_cache                            │   │
│  │        WHERE unresolved_lookup = 'marcusmorris'                     │   │
│  │ If cached: Use cached decision → RESOLVED ✓ (no API call!)          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼ (if not cached)                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 4: AI RESOLUTION (Claude API)                                 │   │
│  │ Provide: unresolved name, team, season, ALL candidates from registry│   │
│  │ AI returns: canonical match + confidence + reasoning                │   │
│  │                                                                     │   │
│  │ ALWAYS:                                                             │   │
│  │ 1. Cache the decision in ai_resolution_cache                        │   │
│  │ 2. Create alias if match found                                      │   │
│  │ 3. Log full response for audit                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼ (if AI says no match)                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 5: MARK AS AI_UNRESOLVABLE                                    │   │
│  │ Status: 'ai_no_match'                                               │   │
│  │ Cache: Store "no_match" decision (avoid re-asking AI)               │   │
│  │ Note: "AI determined no valid match in registry"                    │   │
│  │ Alert if count exceeds threshold                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### AI Resolution Cache Table

```sql
CREATE TABLE nba_reference.ai_resolution_cache (
  unresolved_lookup STRING NOT NULL,      -- The name we couldn't find
  resolved_to STRING,                      -- The canonical match (NULL if no match)
  resolution_type STRING NOT NULL,         -- 'match_found' or 'no_match'
  confidence FLOAT64,                      -- AI's confidence score
  reasoning STRING,                        -- AI's explanation
  candidates_provided ARRAY<STRING>,       -- What candidates AI was given
  context JSON,                            -- team, season, etc.
  ai_model STRING NOT NULL,                -- e.g., 'claude-3-haiku-20240307'
  api_call_id STRING,                      -- For tracing
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (unresolved_lookup)
);
```

### Cache Benefits
1. **Cost Savings:** Same unresolved name across 50 games = 1 API call, not 50
2. **Speed:** Cache lookup is instant vs API call
3. **Consistency:** Same name always resolves the same way
4. **Audit Trail:** Full record of all AI decisions

---

## 7. Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `shared/utils/player_registry/reader.py` | MODIFY | Add alias lookup to `get_universal_ids_batch()` |
| `shared/utils/player_registry/fuzzy_matcher.py` | CREATE | Rule-based suffix/encoding resolution |
| `shared/utils/player_registry/ai_resolver.py` | CREATE | Claude API integration |
| `shared/utils/player_registry/alias_manager.py` | CREATE | Alias CRUD operations |
| `bin/backfill/run_two_pass_backfill.sh` | CREATE | Registry-then-analytics backfill |
| `tools/player_registry/resolve_unresolved_batch.py` | CREATE | Batch resolution CLI |
| `tools/player_registry/reprocess_resolved.py` | CREATE | Reprocess after aliases created |
| `requirements.txt` | MODIFY | Add `anthropic` SDK |

---

## 8. Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| During vs After resolution | After | More efficient, same alias used across many games |
| AI model | Claude Haiku | Fast, cheap, sufficient for name matching |
| Manual review | None | AI decides all uncertain cases, no human queue |
| Timing issue fix | Two-pass backfill | Root cause fix, not symptom treatment |
| Daily ops resolution | Post-Phase 3 hook | Safety net, should rarely trigger |

---

## 9. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Pending unresolved count | 719 | 0 |
| Resolution rate (automatic) | 0% | 100% |
| Time to resolve new name | Never | < 1 hour |
| Manual review required | All | None |

---

## 10. Next Steps

1. **Immediate:** Run cleanup SQL to clear current queue (30 min)
2. **This week:** Implement Phase 1 (RegistryReader fix) + Phase 2 (Two-pass script)
3. **Next week:** Implement Phases 3-6 (Resolution system)
4. **Then:** Run 4-season backfill with new system

---

---

## 11. Instructions for Backfill Chat

**Share this section with the chat handling the backfill.**

### What the Backfill Chat Needs to Know

1. **Use Two-Pass Approach:**
   - Run registry processor FIRST for the date range
   - Then run analytics processor
   - This eliminates 83% of "unresolved" names (timing issues)

2. **Don't Worry About Unresolved During Backfill:**
   - Some names won't resolve (true mismatches like "Marcus Morris" vs "Marcus Morris Sr.")
   - This is expected and will be handled AFTER the backfill

3. **After Analytics Pass Completes:**
   - A separate resolution pass will run
   - AI will resolve remaining names
   - Aliases will be created automatically
   - Affected games will be reprocessed

4. **Current Backfill Order:**
```
PASS 1: Registry (run this FIRST)
bin/backfill/reference/gamebook_registry/...
--start-date 2021-10-19 --end-date [current end date]

PASS 2: Analytics (run this AFTER registry)
bin/backfill/analytics/player_game_summary/...
--start-date 2021-10-19 --end-date [current end date]

PASS 3: Resolution (we'll handle this in a separate session)
- Will use AI to resolve remaining names
- Will create aliases
- Will reprocess affected games
```

5. **Key Tables to Check:**
```sql
-- Check unresolved count after analytics
SELECT status, COUNT(*)
FROM `nba-props-platform.nba_reference.unresolved_player_names`
GROUP BY status;

-- Check which names are truly unresolved (not timing issues)
SELECT DISTINCT u.normalized_lookup, u.team_abbr, u.season
FROM `nba-props-platform.nba_reference.unresolved_player_names` u
LEFT JOIN `nba-props-platform.nba_reference.nba_players_registry` r
  ON u.normalized_lookup = r.player_lookup AND u.season = r.season
WHERE u.status = 'pending' AND r.player_lookup IS NULL;
```

6. **Don't Block on Unresolved:**
   - The backfill can continue even with unresolved names
   - We'll fix them in the resolution pass
   - Phase 4 and Phase 5 can proceed

### Summary for Backfill Chat

> **TL;DR:** Run registry backfill first, then analytics. Expect ~10 truly unresolved names (not 700) - these are real mismatches that will be fixed by AI resolution after the backfill completes. Don't block on them.

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-06 11:00 PST | Session 52 | Initial comprehensive design |
| 2.0 | 2025-12-06 11:30 PST | Session 52 | Simplified to two-pass + batch, added "After" recommendation |
| 2.1 | 2025-12-06 11:45 PST | Session 52 | AI-first approach with caching, added backfill chat instructions |
