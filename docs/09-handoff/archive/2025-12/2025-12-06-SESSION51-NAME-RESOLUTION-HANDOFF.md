# Session 51 Handoff: Player Name Resolution System

**Date:** 2025-12-06
**Status:** Ready for Phase 1 Execution (Pending Your Approval)
**Context Usage:** 86% - recommend new session for implementation

---

## Executive Summary

This session completed a comprehensive analysis of the player name resolution system and created a simplified implementation plan based on Opus review feedback.

**Key Outcome:**
- Original 5-phase plan (33-52 hours) simplified to 3-phase plan (4-7 hours)
- All verification checks passed
- Ready to execute Phase 1 (queue cleanup)

---

## Documents Created This Session

| File | Purpose |
|------|---------|
| `docs/08-projects/current/ai-name-resolution/ROBUST-SYSTEM-DESIGN.md` | Comprehensive system design (24 failure points, full architecture) |
| `docs/08-projects/current/ai-name-resolution/SIMPLIFIED-IMPLEMENTATION-PLAN.md` | Pragmatic 3-phase plan based on Opus feedback |
| `docs/09-handoff/2025-12-06-SESSION51-NAME-RESOLUTION-HANDOFF.md` | This handoff document |

---

## Current State of Unresolved Queue

```
Total Pending: 719 records

Breakdown:
├── 599 timing issues → AUTO-RESOLVE (exact match exists in registry)
├── 8 need aliases → CREATE ALIASES (verified targets exist)
├── 2 season mismatches → SNOOZE or IGNORE
└── 0 truly unknown players

After Phase 1: 719 → 0 pending
```

---

## The 8 Verified Aliases to Create

All targets verified to exist in `nba_players_registry`:

| Alias (unresolved) | Target (canonical) | Type | Verified |
|--------------------|-------------------|------|----------|
| `marcusmorris` | `marcusmorrissr` | suffix (Sr.) | ✅ |
| `robertwilliams` | `robertwilliamsiii` | suffix (III) | ✅ |
| `kevinknox` | `kevinknoxii` | suffix (II) | ✅ |
| `derrickwalton` | `derrickwaltonjr` | suffix (Jr.) | ✅ |
| `ggjacksonii` | `ggjackson` | suffix (remove II) | ✅ |
| `xaviertillmansr` | `xaviertillman` | suffix (remove Sr.) | ✅ |
| `filippetruaev` | `filippetrusev` | encoding (š→s) | ✅ |
| `matthewhurt` | `matthurt` | nickname (Matthew→Matt) | ✅ |

---

## Verified Schema Information

### player_aliases table columns:
```
alias_lookup              STRING (NOT NULL)
nba_canonical_lookup      STRING (NOT NULL)
alias_display             STRING (NOT NULL)
nba_canonical_display     STRING (NOT NULL)
alias_type                STRING (nullable)
alias_source              STRING (nullable)
is_active                 BOOL (NOT NULL)
notes                     STRING (nullable)
created_by                STRING (NOT NULL)  ← Was missing from original INSERT
created_at                TIMESTAMP (NOT NULL)
processed_at              TIMESTAMP (NOT NULL) ← Was missing from original INSERT
```

### Backfill scripts that exist:
- `bin/backfill/run_phase4_backfill.sh` ✅
- `bin/backfill/run_phase3_backfill.sh` ❌ (does NOT exist - needs creation)

---

## Simplified Implementation Plan

### Phase 1: Clear the Queue (30-60 min) ← READY TO EXECUTE

**Step 1.1: Auto-resolve 599 timing issues**
```sql
UPDATE `nba-props-platform.nba_reference.unresolved_player_names` u
SET
    status = 'resolved',
    resolution_type = 'timing_auto',
    reviewed_by = 'automated_cleanup',
    reviewed_at = CURRENT_TIMESTAMP(),
    notes = 'Auto-resolved: exact match exists in registry for same season'
WHERE status = 'pending'
  AND EXISTS (
    SELECT 1 FROM `nba-props-platform.nba_reference.nba_players_registry` r
    WHERE u.normalized_lookup = r.player_lookup
      AND u.season = r.season
  );
```

**Step 1.2: Create 8 aliases (corrected SQL)**
```sql
INSERT INTO `nba-props-platform.nba_reference.player_aliases`
(alias_lookup, nba_canonical_lookup, alias_display, nba_canonical_display,
 alias_type, alias_source, is_active, created_by, created_at, processed_at)
VALUES
('marcusmorris', 'marcusmorrissr', 'Marcus Morris', 'Marcus Morris Sr.',
 'suffix_difference', 'manual_cleanup', TRUE, 'session51_cleanup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('robertwilliams', 'robertwilliamsiii', 'Robert Williams', 'Robert Williams III',
 'suffix_difference', 'manual_cleanup', TRUE, 'session51_cleanup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('kevinknox', 'kevinknoxii', 'Kevin Knox', 'Kevin Knox II',
 'suffix_difference', 'manual_cleanup', TRUE, 'session51_cleanup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('derrickwalton', 'derrickwaltonjr', 'Derrick Walton', 'Derrick Walton Jr.',
 'suffix_difference', 'manual_cleanup', TRUE, 'session51_cleanup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('ggjacksonii', 'ggjackson', 'GG Jackson II', 'GG Jackson',
 'suffix_difference', 'manual_cleanup', TRUE, 'session51_cleanup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('xaviertillmansr', 'xaviertillman', 'Xavier Tillman Sr.', 'Xavier Tillman',
 'suffix_difference', 'manual_cleanup', TRUE, 'session51_cleanup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('filippetruaev', 'filippetrusev', 'Filip Petruŝev', 'Filip Petrusev',
 'source_variation', 'manual_cleanup', TRUE, 'session51_cleanup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('matthewhurt', 'matthurt', 'Matthew Hurt', 'Matt Hurt',
 'nickname', 'manual_cleanup', TRUE, 'session51_cleanup', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP());
```

**Step 1.3: Mark aliased names as resolved**
```sql
UPDATE `nba-props-platform.nba_reference.unresolved_player_names`
SET
    status = 'resolved',
    resolution_type = 'create_alias',
    reviewed_by = 'manual_cleanup',
    reviewed_at = CURRENT_TIMESTAMP(),
    notes = 'Alias created to canonical name'
WHERE status = 'pending'
  AND normalized_lookup IN (
    'marcusmorris', 'robertwilliams', 'kevinknox', 'derrickwalton',
    'ggjacksonii', 'xaviertillmansr', 'filippetruaev', 'matthewhurt'
  );
```

**Step 1.4: Handle season mismatches**
```sql
UPDATE `nba-props-platform.nba_reference.unresolved_player_names`
SET
    status = 'snoozed',
    snooze_until = DATE_ADD(CURRENT_DATE(), INTERVAL 30 DAY),
    reviewed_by = 'manual_cleanup',
    reviewed_at = CURRENT_TIMESTAMP(),
    notes = 'Player exists in registry but for different season. Will resolve when roster processor runs.'
WHERE status = 'pending'
  AND normalized_lookup IN ('ronholland', 'jeenathanwilliams');
```

**Step 1.5: Verify aliases work**
```sql
SELECT
  a.alias_lookup,
  a.nba_canonical_lookup,
  r.universal_player_id,
  r.player_name
FROM `nba-props-platform.nba_reference.player_aliases` a
LEFT JOIN `nba-props-platform.nba_reference.nba_players_registry` r
  ON a.nba_canonical_lookup = r.player_lookup
WHERE a.alias_source = 'manual_cleanup';
```

**Step 1.6: Verify queue is clear**
```sql
SELECT status, COUNT(*) as count
FROM `nba-props-platform.nba_reference.unresolved_player_names`
GROUP BY status
ORDER BY count DESC;
```

### Phase 2: Future Context Capture (2-4 hours) ← AFTER PHASE 1

- Create `unresolved_occurrences` table
- Modify `flush_unresolved_players()` to capture game context
- Enables reprocessing after future resolutions

### Phase 3: Two-Pass Backfill Script (1-2 hours) ← BEFORE MAJOR BACKFILL

- Create script that runs registry FIRST, then analytics
- Prevents timing issues in future backfills
- Note: `run_phase3_backfill.sh` needs to be created

---

## Decisions Needed Before Proceeding

### 1. Execute Phase 1 Now?
**Decision:** Yes/No
**Impact:** Clears queue from 719 → 0

### 2. Snoozed Names: 30 days or mark ignored?
**Context:** `ronholland` and `jeenathanwilliams` exist in registry for different seasons (2025-26 and 2022-23) but are unresolved for 2024-25.
**Options:**
- A) Snooze 30 days (assumes roster processor will run for 2024-25)
- B) Mark as `ignored` (if roster processor won't run soon)
**Opus opinion helpful:** Yes - depends on your backfill timeline

### 3. Reprocessing After Aliases Created?
**Context:** Creating aliases doesn't fix historical data - need to reprocess.
**Options:**
- A) Wait for 4-season backfill (simple, data stays incomplete until then)
- B) Targeted reprocess for affected dates (immediate fix)
**Opus opinion helpful:** Yes - depends on when backfill is planned

### 4. When is 4-season backfill planned?
**Impact on decisions 2 and 3 above.**

### 5. Create run_phase3_backfill.sh?
**Context:** Two-pass script assumes this exists but it doesn't.
**Options:**
- A) Create it (better abstraction)
- B) Have two-pass script call processors directly (simpler)
**Opus opinion helpful:** Optional - either works

---

## What Was Deferred (Per Opus Feedback)

| Item | Reason | Reconsider When |
|------|--------|-----------------|
| AI integration | 8 names don't need AI | Future volume > 50 names |
| ai_resolution_cache table | No AI = no cache | When AI is added |
| resolution_reprocess_queue table | Manual triggers fine | Queue > 100 dates |
| Complex monitoring | Only 2 snoozed remain | Daily ops show issues |
| Multi-layer fuzzy pipeline | Current 2-layer works | Suffix issues recur |

---

## Key Findings This Session

### Root Causes Identified

1. **Timing Issues (599 names):** Analytics runs before registry populated during backfill
2. **Suffix Mismatches:** Basketball-Reference omits Jr/Sr/II/III
3. **Encoding Issues:** Unicode handling differs (š vs s)
4. **Season Mismatches:** Player exists but not for that specific season

### Why example_games is Always Empty

`get_universal_ids_batch()` is called without game context:
```python
uid_map = self.registry.get_universal_ids_batch(unique_players)  # No context!
```

Context is set globally, not per-player. Phase 2 fixes this.

### Multiple Records Per universal_player_id is BY DESIGN

Registry stores one record per player+season+team. Dennis Schroder has 9 records because he played for 8 teams across 5 seasons. This is NOT a bug.

---

## Files to Read (Priority Order)

### For Context
1. `docs/08-projects/current/ai-name-resolution/SIMPLIFIED-IMPLEMENTATION-PLAN.md` - The plan to execute
2. `docs/08-projects/current/ai-name-resolution/ROBUST-SYSTEM-DESIGN.md` - Full analysis (if needed)

### For Implementation
3. `shared/utils/player_registry/reader.py` - RegistryReader class
4. `tools/player_registry/resolve_unresolved_names.py` - CLI tool (reference)

---

## Verification Queries for Next Session

### Before Phase 1:
```sql
-- Count pending
SELECT COUNT(*) FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending';
-- Expected: 719
```

### After Phase 1:
```sql
-- Count by status
SELECT status, COUNT(*) as count
FROM `nba-props-platform.nba_reference.unresolved_player_names`
GROUP BY status;
-- Expected: pending = 0, resolved = ~607, snoozed = 2

-- Verify aliases created
SELECT COUNT(*) FROM `nba-props-platform.nba_reference.player_aliases`
WHERE alias_source = 'manual_cleanup';
-- Expected: 8

-- Test alias resolution works
SELECT a.alias_lookup, r.universal_player_id
FROM `nba-props-platform.nba_reference.player_aliases` a
JOIN `nba-props-platform.nba_reference.nba_players_registry` r
  ON a.nba_canonical_lookup = r.player_lookup
WHERE a.alias_source = 'manual_cleanup';
-- Expected: 8 rows with non-null universal_player_id
```

---

## Session Log

| Session | Date | Focus | Outcome |
|---------|------|-------|---------|
| 50 | 2025-12-05 | Deep analysis, Opus brief created | Analysis complete |
| 51 | 2025-12-06 | Opus review, simplified plan, verification | Ready for execution |

---

## Quick Start for Next Session

```
1. Read this handoff
2. Get answers to the 5 decisions above (Opus can help with 2, 3)
3. Execute Phase 1 SQL queries
4. Verify with queries above
5. Plan Phase 2/3 based on backfill timeline
```

---

## Contact/Context

This is part of the NBA stats pipeline project. The player registry is critical infrastructure - all analytics depend on correct player identification. The immediate goal is clearing the 719-item queue before the 4-season backfill.
