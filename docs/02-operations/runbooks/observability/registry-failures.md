# Registry Failures Runbook

**Created:** 2025-12-06
**Last Updated:** 2025-12-06
**Status:** Active

---

## Overview

The `registry_failures` table tracks players who couldn't be found in the registry during Phase 3 processing. This enables:

1. **Visibility**: See which players are missing and why
2. **Targeted Reprocessing**: After an alias is created, find exactly which dates need reprocessing
3. **Workflow Tracking**: Track the full lifecycle from failure → resolution → reprocessing

---

## Quick Status Check

### Overall Status

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'complete'
    WHEN resolved_at IS NOT NULL THEN 'ready_to_reprocess'
    ELSE 'pending_resolution'
  END as status,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as total_records
FROM \`nba-props-platform.nba_processing.registry_failures\`
GROUP BY status
ORDER BY status"
```

**Healthy output:**
```
+---------------------+---------+---------------+
| status              | players | total_records |
+---------------------+---------+---------------+
| complete            |      12 |           156 |
| pending_resolution  |       5 |            45 |
| ready_to_reprocess  |       8 |            89 |
+---------------------+---------+---------------+
```

### Interpretation

| Status | Meaning | Action |
|--------|---------|--------|
| `pending_resolution` | No alias exists yet | Run AI resolution |
| `ready_to_reprocess` | Alias created, dates pending | Run reprocess script |
| `complete` | Fully reprocessed | No action needed |

---

## The Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        REGISTRY FAILURE LIFECYCLE                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  1. PENDING              2. RESOLVED              3. COMPLETE                   │
│  ─────────────────       ─────────────────        ─────────────────             │
│  created_at: SET         resolved_at: SET         reprocessed_at: SET          │
│  resolved_at: NULL       reprocessed_at: NULL     ✅ Done                       │
│                                                                                  │
│  Action:                 Action:                  No action needed              │
│  Create alias via AI     Run reprocess script                                   │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Common Operations

### 1. Find Players Needing Aliases (Pending Resolution)

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as affected_dates,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  ANY_VALUE(team_abbr) as sample_team
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NULL
GROUP BY player_lookup
ORDER BY affected_dates DESC
LIMIT 20"
```

**Then run AI resolution:**
```bash
python tools/player_registry/resolve_unresolved_batch.py --dry-run
python tools/player_registry/resolve_unresolved_batch.py
```

### 2. Find Players Ready to Reprocess

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as dates_to_reprocess,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NOT NULL
  AND reprocessed_at IS NULL
GROUP BY player_lookup
ORDER BY dates_to_reprocess DESC"
```

**Then run reprocessing:**
```bash
python tools/player_registry/reprocess_resolved.py --dry-run
python tools/player_registry/reprocess_resolved.py
```

### 3. Check Stale Failures (Pending > 7 Days)

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as affected_dates,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MIN(created_at), DAY) as days_pending,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NULL
GROUP BY player_lookup
HAVING days_pending > 7
ORDER BY affected_dates DESC"
```

If players are stale, investigate why AI resolution isn't working for them.

### 4. Check Specific Player Status

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  processor_name,
  team_abbr,
  season,
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'complete'
    WHEN resolved_at IS NOT NULL THEN 'ready'
    ELSE 'pending'
  END as status,
  created_at,
  resolved_at,
  reprocessed_at
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE player_lookup = 'marcusmorris'
ORDER BY game_date"
```

---

## Daily Monitoring

### Morning Check Script

```bash
#!/bin/bash
# Save as: monitoring/check_registry_failures.sh

echo "=== Registry Failures Status ==="

# Overall counts
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN reprocessed_at IS NOT NULL THEN 'complete'
    WHEN resolved_at IS NOT NULL THEN 'ready_to_reprocess'
    ELSE 'pending_resolution'
  END as status,
  COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_processing.registry_failures\`
GROUP BY status"

# Alert if too many pending
PENDING=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(DISTINCT player_lookup)
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NULL" | tail -1)

if [ "$PENDING" -gt 10 ]; then
  echo "⚠️  WARNING: $PENDING players pending resolution"
fi

# Alert if ready to reprocess
READY=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(DISTINCT player_lookup)
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NOT NULL AND reprocessed_at IS NULL" | tail -1)

if [ "$READY" -gt 0 ]; then
  echo "🔄 ACTION NEEDED: $READY players ready to reprocess"
fi
```

---

## Troubleshooting

### No Failures Being Recorded

**Check if processors are running the new code:**
```bash
# Look for registry failure logs
grep "registry failures" logs/player_game_summary*.log
```

**Verify table exists:**
```bash
bq show nba-props-platform:nba_processing.registry_failures
```

### Resolved But Not Reprocessing

**Check if resolved_at was set correctly:**
```sql
SELECT player_lookup, resolved_at
FROM `nba_processing.registry_failures`
WHERE resolved_at IS NOT NULL
LIMIT 10
```

**Verify alias exists:**
```sql
SELECT * FROM `nba_reference.player_aliases`
WHERE alias_lookup = 'marcusmorris'
```

### Duplicate Failures

The system deduplicates by `(player_lookup, game_date)` before inserting, so duplicates indicate re-runs. This is expected behavior - the `occurrence_count` field tracks this.

---

## Frequently Asked Questions (FAQ)

### 1. What if reprocessing fails partway through?

**Answer:** Only successfully reprocessed dates get marked with `reprocessed_at`. Failed dates remain in the "ready_to_reprocess" state (where `resolved_at IS NOT NULL` and `reprocessed_at IS NULL`). Simply re-run the reprocess script to pick up where you left off:

```bash
python tools/player_registry/reprocess_resolved.py
```

The script will automatically skip any dates that have already been successfully reprocessed.

---

### 2. What if an alias is later deleted or changed?

**Answer:** The `registry_failures` records remain unchanged. The `resolved_at` timestamp reflects when the alias was originally created. If the alias is deleted:

- Existing failure records keep their `resolved_at` timestamp (historical record)
- New failures will be recorded on future processor runs
- These new failures will have `resolved_at = NULL` until a new alias is created

This design preserves the audit trail while allowing the system to respond to registry changes.

---

### 3. How long should failures stay in 'pending' state?

**Answer:** Ideally:

- **Daily runs:** < 24 hours
- **Backfills:** < 7 days

Use the "stale failures" query to find long-pending items:

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as affected_dates,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MIN(created_at), DAY) as days_pending
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE resolved_at IS NULL
GROUP BY player_lookup
HAVING days_pending > 7
ORDER BY affected_dates DESC"
```

If players are stale for more than 7 days, investigate why AI resolution isn't working for them or if manual intervention is needed.

---

### 4. What if the same player fails on multiple dates?

**Answer:** Each `(player_lookup, game_date)` combination gets its own record in the `registry_failures` table. When an alias is created:

- All records for that player (across all dates) get `resolved_at` set to the same timestamp
- This allows you to see the full scope of dates that need reprocessing
- The reprocess script will handle all affected dates in batch

Example:
```sql
-- Before alias creation
player_lookup: 'marcusmorris', game_date: '2021-11-01', resolved_at: NULL
player_lookup: 'marcusmorris', game_date: '2021-11-05', resolved_at: NULL
player_lookup: 'marcusmorris', game_date: '2021-11-08', resolved_at: NULL

-- After alias creation (all get marked)
player_lookup: 'marcusmorris', game_date: '2021-11-01', resolved_at: '2025-12-06 10:30:00'
player_lookup: 'marcusmorris', game_date: '2021-11-05', resolved_at: '2025-12-06 10:30:00'
player_lookup: 'marcusmorris', game_date: '2021-11-08', resolved_at: '2025-12-06 10:30:00'
```

---

### 5. Do I need to manually mark failures as resolved?

**Answer:** No. The `resolve_unresolved_batch.py` script automatically updates `resolved_at` when it creates an alias. The workflow is:

1. Script creates alias in `player_aliases` table
2. Script immediately updates all `registry_failures` records for that player
3. You then run `reprocess_resolved.py` to handle the reprocessing

Manual intervention is only needed if you create an alias through some other method (e.g., directly in SQL or through a different tool). In that case, you can manually update:

```sql
UPDATE `nba_processing.registry_failures`
SET resolved_at = CURRENT_TIMESTAMP()
WHERE player_lookup = 'player_name'
  AND resolved_at IS NULL
```

---

### 6. What happens if I re-run a processor for a date that already has failures?

**Answer:** New failures are inserted (deduplicated within the same run). Old failure records remain. This is by design - we don't delete history.

The `occurrence_count` field tracks how many times the same failure was encountered. This helps identify:

- Persistent issues (high occurrence count)
- One-off transient failures (occurrence_count = 1)

Example scenario:
```
Day 1: Run processor → "marcusmorris" fails → Record created (occurrence_count: 1)
Day 2: Re-run processor → "marcusmorris" fails again → New record created (occurrence_count: 1)
Day 3: Create alias → Both records get resolved_at set
Day 4: Reprocess both dates → Both records get reprocessed_at set
```

This ensures complete historical tracking.

---

### 7. How do I know if all failures for a player have been reprocessed?

**Answer:** Query for that player and check if any records have `reprocessed_at = NULL` with `resolved_at != NULL`:

```bash
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  COUNT(*) as total_records,
  COUNTIF(resolved_at IS NOT NULL) as resolved_records,
  COUNTIF(reprocessed_at IS NOT NULL) as reprocessed_records,
  COUNTIF(resolved_at IS NOT NULL AND reprocessed_at IS NULL) as pending_reprocess
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE player_lookup = 'marcusmorris'
GROUP BY player_lookup"
```

If `pending_reprocess` = 0, all failures for that player have been fully handled.

You can also check specific dates:
```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  processor_name,
  CASE
    WHEN reprocessed_at IS NOT NULL THEN '✅ Complete'
    WHEN resolved_at IS NOT NULL THEN '⏳ Ready to Reprocess'
    ELSE '❌ Pending Resolution'
  END as status
FROM \`nba-props-platform.nba_processing.registry_failures\`
WHERE player_lookup = 'marcusmorris'
ORDER BY game_date"
```

---

## Schema Reference

```sql
CREATE TABLE `nba_processing.registry_failures` (
  -- Identity
  player_lookup STRING NOT NULL,        -- Raw name that failed lookup
  game_date DATE NOT NULL,              -- When the player played
  processor_name STRING NOT NULL,       -- Which processor encountered it

  -- Context
  team_abbr STRING,                     -- Team context
  season STRING,                        -- Season (e.g., "2021-22")
  game_id STRING,                       -- Specific game

  -- Lifecycle timestamps
  created_at TIMESTAMP,                 -- When failure was first recorded
  resolved_at TIMESTAMP,                -- When alias was created
  reprocessed_at TIMESTAMP,             -- When date was reprocessed

  -- Metadata
  occurrence_count INT64,               -- How many times seen
  run_id STRING                         -- Processing run ID
)
PARTITION BY game_date
CLUSTER BY player_lookup, processor_name
```

---

## Related Documentation

- **Name Resolution Runbook:** `docs/02-operations/runbooks/backfill/name-resolution.md`
- **Design Doc:** `docs/08-projects/current/observability/FAILURE-TRACKING-DESIGN.md`
- **AI Name Resolution:** `docs/08-projects/current/ai-name-resolution/DESIGN-DOC-AI-NAME-RESOLUTION.md`

---

## Related Scripts

| Script | Purpose |
|--------|---------|
| `tools/player_registry/resolve_unresolved_batch.py` | Create aliases via AI (sets `resolved_at`) |
| `tools/player_registry/reprocess_resolved.py` | Reprocess dates (sets `reprocessed_at`) |
| `monitoring/resolution_health_check.py` | Overall health check |

---

**Last Verified:** 2025-12-06
**Maintained By:** NBA Platform Team
