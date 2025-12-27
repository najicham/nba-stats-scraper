# Simplified Player Name Resolution Plan

**Date:** 2025-12-06
**Status:** Ready for Implementation
**Revision:** Simplified based on Opus feedback

---

## Executive Summary

The original design document identified 24 failure points and proposed a 5-phase, 33-52 hour implementation. After review, we're simplifying to focus on what actually matters:

- **719 pending names** → 599 are timing issues (auto-resolve), 8 need aliases, 2 need investigation
- **AI integration deferred** → 8 aliases don't need AI
- **3 new tables → 1** → Only `unresolved_occurrences` for future prevention
- **5 phases → 3** → Clear queue, enable reprocessing, prevent future issues

---

## Current State

```
Pending Queue: 719 records

Breakdown:
├── 599 timing issues (exact match now exists in registry) → AUTO-RESOLVE
├── 8 need aliases (suffix/encoding/nickname variations) → CREATE ALIASES
├── 2 season mismatches (ronholland, jeenathanwilliams) → INVESTIGATE
└── 0 truly unknown players
```

### The 8 Aliases Needed

| Unresolved | Registry Match | Type | Verified |
|------------|----------------|------|----------|
| `marcusmorris` | `marcusmorrissr` | suffix (Sr.) | ✓ |
| `robertwilliams` | `robertwilliamsiii` | suffix (III) | ✓ |
| `kevinknox` | `kevinknoxii` | suffix (II) | ✓ |
| `ggjacksonii` | `ggjackson` | suffix (remove II) | ✓ |
| `xaviertillmansr` | `xaviertillman` | suffix (remove Sr.) | ✓ |
| `filippetruaev` | `filippetrusev` | encoding (š→s) | ✓ |
| `matthewhurt` | `matthurt` | nickname (Matthew→Matt) | ✓ |
| `derrickwalton` | `derrickwaltonjr` | suffix (Jr.) | ✓ |

### The 2 Season Mismatches

| Unresolved | Issue | Action |
|------------|-------|--------|
| `ronholland` (DET 2024-25) | Registry has 2025-26 only | Wait for roster processor or mark ignored |
| `jeenathanwilliams` (HOU 2024-25) | Registry has 2022-23/2023-24 | Wait for roster processor or mark ignored |

---

## Simplified Implementation Plan

### Phase 1: Clear the Queue (30-60 minutes)

**Goal:** Reduce pending from 719 → 0

#### Step 1.1: Auto-resolve timing issues (599 names)

```sql
-- Preview first
SELECT COUNT(*) as will_resolve
FROM `nba-props-platform.nba_reference.unresolved_player_names` u
WHERE status = 'pending'
  AND EXISTS (
    SELECT 1 FROM `nba-props-platform.nba_reference.nba_players_registry` r
    WHERE u.normalized_lookup = r.player_lookup
      AND u.season = r.season
  );

-- Execute
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

#### Step 1.2: Create 8 aliases

```sql
-- Insert all 8 aliases
INSERT INTO `nba-props-platform.nba_reference.player_aliases`
(alias_lookup, nba_canonical_lookup, alias_display, nba_canonical_display, alias_type, alias_source, is_active, created_at)
VALUES
-- Suffix additions
('marcusmorris', 'marcusmorrissr', 'Marcus Morris', 'Marcus Morris Sr.', 'suffix_difference', 'manual_cleanup', TRUE, CURRENT_TIMESTAMP()),
('robertwilliams', 'robertwilliamsiii', 'Robert Williams', 'Robert Williams III', 'suffix_difference', 'manual_cleanup', TRUE, CURRENT_TIMESTAMP()),
('kevinknox', 'kevinknoxii', 'Kevin Knox', 'Kevin Knox II', 'suffix_difference', 'manual_cleanup', TRUE, CURRENT_TIMESTAMP()),
('derrickwalton', 'derrickwaltonjr', 'Derrick Walton', 'Derrick Walton Jr.', 'suffix_difference', 'manual_cleanup', TRUE, CURRENT_TIMESTAMP()),

-- Suffix removals
('ggjacksonii', 'ggjackson', 'GG Jackson II', 'GG Jackson', 'suffix_difference', 'manual_cleanup', TRUE, CURRENT_TIMESTAMP()),
('xaviertillmansr', 'xaviertillman', 'Xavier Tillman Sr.', 'Xavier Tillman', 'suffix_difference', 'manual_cleanup', TRUE, CURRENT_TIMESTAMP()),

-- Encoding/nickname
('filippetruaev', 'filippetrusev', 'Filip Petruŝev', 'Filip Petrusev', 'source_variation', 'manual_cleanup', TRUE, CURRENT_TIMESTAMP()),
('matthewhurt', 'matthurt', 'Matthew Hurt', 'Matt Hurt', 'nickname', 'manual_cleanup', TRUE, CURRENT_TIMESTAMP());
```

#### Step 1.3: Mark aliased names as resolved

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

#### Step 1.4: Handle season mismatches

```sql
-- Mark as snoozed (will auto-resolve when roster processor runs for 2024-25)
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

#### Step 1.5: Verify queue is clear

```sql
SELECT status, COUNT(*) as count
FROM `nba-props-platform.nba_reference.unresolved_player_names`
GROUP BY status
ORDER BY count DESC;
```

**Expected Result:**
- `resolved`: ~607+ (599 timing + 8 aliased)
- `snoozed`: 2 (season mismatches)
- `pending`: 0

---

### Phase 2: Enable Future Context Capture (2-4 hours)

**Goal:** When new unresolved names occur, capture full game context for later reprocessing

#### Step 2.1: Create unresolved_occurrences table

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_reference.unresolved_occurrences` (
    occurrence_id STRING NOT NULL,
    normalized_lookup STRING NOT NULL,

    -- Game context
    game_id STRING NOT NULL,
    game_date DATE NOT NULL,
    season STRING NOT NULL,
    team_abbr STRING,

    -- Processor context
    processor_name STRING NOT NULL,
    processor_run_id STRING NOT NULL,
    source_table STRING,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY normalized_lookup, processor_name
OPTIONS (
    description = 'Tracks every occurrence of unresolved player names with full context for reprocessing'
);
```

#### Step 2.2: Modify RegistryReader to capture context

**File:** `shared/utils/player_registry/reader.py`

**Change:** Modify `flush_unresolved_players()` to also write to `unresolved_occurrences`

```python
# In flush_unresolved_players(), after inserting/updating unresolved_player_names:

# NEW: Also log each occurrence with full context
if self._unresolved_contexts:
    occurrences = []
    for lookup, contexts in self._unresolved_contexts.items():
        for ctx in contexts:
            occurrences.append({
                'occurrence_id': str(uuid.uuid4()),
                'normalized_lookup': lookup,
                'game_id': ctx.get('game_id'),
                'game_date': ctx.get('game_date'),
                'season': ctx.get('season'),
                'team_abbr': ctx.get('team'),
                'processor_name': ctx.get('processor_name', self._processor_name),
                'processor_run_id': ctx.get('run_id', self._run_id),
                'source_table': ctx.get('source_table'),
            })

    if occurrences:
        # Write to unresolved_occurrences table
        self._write_occurrences(occurrences)
```

#### Step 2.3: Pass game context in batch lookups

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Change:** Pass game_id when looking up players

```python
# Current (line ~647):
uid_map = self.registry.get_universal_ids_batch(unique_players)

# Change to pass context per player:
uid_map = self.registry.get_universal_ids_batch(
    unique_players,
    contexts={
        player: {'game_id': game_id, 'game_date': game_date}
        for player, game_id, game_date in player_game_mapping
    }
)
```

---

### Phase 3: Two-Pass Backfill Script (1-2 hours)

**Goal:** Prevent timing issues in future backfills by ensuring registry is populated first

#### Step 3.1: Create two-pass backfill script

**File:** `bin/backfill/run_two_pass_backfill.sh`

```bash
#!/bin/bash
set -e

# Usage: ./run_two_pass_backfill.sh --start-season 2021-22 --end-season 2024-25

START_SEASON="${1:-2021-22}"
END_SEASON="${2:-2024-25}"

echo "=========================================="
echo "TWO-PASS BACKFILL: $START_SEASON to $END_SEASON"
echo "=========================================="

# PASS 1: Registry Population
echo ""
echo "=== PASS 1: REGISTRY POPULATION ==="
echo "Building player registry for all seasons first..."

for SEASON in "2021-22" "2022-23" "2023-24" "2024-25"; do
    echo ""
    echo "--- Registry: $SEASON ---"

    # Roster registry processor
    python -m data_processors.reference.player_reference.roster_registry_processor \
        --season "$SEASON" \
        --allow-backfill \
        --skip-downstream-trigger

    # Gamebook registry processor
    python -m data_processors.reference.player_reference.gamebook_registry_processor \
        --season "$SEASON" \
        --allow-backfill \
        --skip-downstream-trigger
done

echo ""
echo "=== PASS 1 COMPLETE ==="
echo "Registry populated. Verifying..."

# Verify registry has expected entries
python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT season, COUNT(*) as players, SUM(games_played) as total_games
FROM \`nba-props-platform.nba_reference.nba_players_registry\`
GROUP BY season
ORDER BY season
'''
print('Registry status:')
for row in client.query(query):
    print(f'  {row.season}: {row.players} players, {row.total_games} total games')
"

# PASS 2: Analytics + Precompute
echo ""
echo "=== PASS 2: ANALYTICS + PRECOMPUTE ==="
echo "Now safe to run analytics - registry is populated."

for SEASON in "2021-22" "2022-23" "2023-24" "2024-25"; do
    echo ""
    echo "--- Analytics: $SEASON ---"

    # Run Phase 3 backfill for this season
    ./bin/backfill/run_phase3_backfill.sh --season "$SEASON"

    # Run Phase 4 backfill for this season
    ./bin/backfill/run_phase4_backfill.sh --season "$SEASON"
done

echo ""
echo "=== PASS 2 COMPLETE ==="
echo "Backfill finished. Checking for unresolved names..."

# Check for any new unresolved names
python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT status, COUNT(*) as count
FROM \`nba-props-platform.nba_reference.unresolved_player_names\`
GROUP BY status
'''
print('Unresolved names status:')
for row in client.query(query):
    print(f'  {row.status}: {row.count}')
"

echo ""
echo "=========================================="
echo "TWO-PASS BACKFILL COMPLETE"
echo "=========================================="
```

---

## What We're NOT Doing (Deferred)

| Item | Reason | When to Reconsider |
|------|--------|-------------------|
| AI integration | 8 names don't need AI | If future volume > 50 names |
| ai_resolution_cache table | No AI = no cache needed | When AI is added |
| resolution_reprocess_queue table | Manual triggers fine at this scale | If queue > 100 dates |
| Complex monitoring/alerting | Only 2 snoozed names remain | If daily ops show issues |
| Multi-layer fuzzy matching | Current 2-layer (exact + alias) works | If suffix issues recur |

---

## Reprocessing Affected Data

After Phase 1 (aliases created), existing data is NOT automatically fixed. Options:

### Option A: Wait for next backfill
- Pros: Simple, no extra work
- Cons: Data stays incomplete until backfill
- Best if: Full backfill is coming soon anyway

### Option B: Targeted reprocessing
- Identify affected dates from unresolved records
- Re-run Phase 3/4 for those specific dates
- Best if: Need data fixed before next full backfill

### Affected Date Ranges (from unresolved records)

```sql
-- Find affected dates for aliased names
SELECT
    normalized_lookup,
    MIN(first_seen_date) as earliest,
    MAX(last_seen_date) as latest,
    SUM(occurrences) as total_occurrences
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE normalized_lookup IN (
    'marcusmorris', 'robertwilliams', 'kevinknox', 'derrickwalton',
    'ggjacksonii', 'xaviertillmansr', 'filippetruaev', 'matthewhurt'
)
GROUP BY normalized_lookup
ORDER BY total_occurrences DESC;
```

**Recommendation:** If you're about to run the 4-season backfill, skip targeted reprocessing - the backfill will pick up the new aliases automatically.

---

## Summary

| Phase | Time | Outcome |
|-------|------|---------|
| **Phase 1** | 30-60 min | Queue cleared: 719 → 0 |
| **Phase 2** | 2-4 hours | Future unresolved names capture game context |
| **Phase 3** | 1-2 hours | Two-pass backfill prevents timing issues |

**Total: 4-7 hours** (down from 33-52 hours)

---

## Verification Checklist

After Phase 1:
- [ ] `SELECT COUNT(*) FROM unresolved_player_names WHERE status = 'pending'` = 0
- [ ] `SELECT COUNT(*) FROM player_aliases WHERE alias_source = 'manual_cleanup'` = 8
- [ ] Test lookup: `marcusmorris` resolves to `marcusmorrissr`

After Phase 2:
- [ ] `unresolved_occurrences` table exists
- [ ] New unresolved names populate with game_id, game_date

After Phase 3:
- [ ] `run_two_pass_backfill.sh` executes without errors
- [ ] Registry populated before analytics runs

---

## Questions for You

1. **Ready for Phase 1?** I can execute the cleanup queries now.

2. **Reprocessing strategy:** Is a full 4-season backfill coming soon? If yes, skip targeted reprocessing.

3. **Phase 2 timing:** Do this before or after the backfill? (Before = capture context during backfill; After = simpler but less visibility)
