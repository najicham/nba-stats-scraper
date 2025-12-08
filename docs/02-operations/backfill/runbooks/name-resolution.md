# Player Name Resolution for Backfills

**Created:** 2025-12-06 13:00:00 PST
**Last Updated:** 2025-12-06 13:00:00 PST
**Status:** Active

---

## Overview

During backfills, player names from different sources (NBA.com, ESPN, Basketball Reference) may not match the canonical names in `nba_players_registry`. This guide explains how the name resolution system works and how to handle unresolved names during backfills.

---

## Resolution Pipeline

```
1. Direct Registry Lookup (99% of cases)
   └─ player_lookup matches nba_players_registry

2. Alias Lookup (known variations)
   └─ player_lookup matches player_aliases table
   └─ 8 aliases currently active

3. AI Resolution (edge cases)
   └─ Claude Haiku analyzes context
   └─ Creates aliases automatically
   └─ Requires ANTHROPIC_API_KEY
```

---

## Two-Pass Backfill (Recommended)

The **two-pass approach** prevents 83% of unresolved name issues by ensuring the registry is populated before analytics runs.

### Usage

```bash
./bin/backfill/run_two_pass_backfill.sh START_DATE END_DATE
```

**Example:**
```bash
./bin/backfill/run_two_pass_backfill.sh 2021-10-19 2025-06-22
```

### What It Does

| Pass | Purpose | Result |
|------|---------|--------|
| **Pass 1** | Populate registry (Phase 1) | All players exist in `nba_players_registry` |
| **Pass 2** | Run analytics (Phase 3) | ~99% of players resolve automatically |

---

## After Backfill: Handling Unresolved Names

### Step 1: Check Health

```bash
python monitoring/resolution_health_check.py
```

**Healthy output:**
```
Overall Status: OK
[OK] Stale Unresolved Names - Count: 0
[OK] Active Aliases: 8
```

### Step 2: If Pending > 0, Run AI Resolution

```bash
# Requires ANTHROPIC_API_KEY environment variable
export ANTHROPIC_API_KEY=sk-ant-api03-...

# Dry run first
python tools/player_registry/resolve_unresolved_batch.py --dry-run

# Actually resolve
python tools/player_registry/resolve_unresolved_batch.py
```

### Step 3: Reprocess Games with New Aliases

```bash
# See what would be reprocessed
python tools/player_registry/reprocess_resolved.py --resolved-since 2025-12-06 --dry-run

# Actually reprocess
python tools/player_registry/reprocess_resolved.py --resolved-since 2025-12-06
```

### Finding Dates to Reprocess (via Registry Failures)

The `registry_failures` table tracks all players who failed registry lookup. After an alias is created, you can find exactly which dates need reprocessing:

```sql
-- Find all dates where a specific player failed registry lookup
SELECT DISTINCT game_date
FROM `nba-props-platform.nba_processing.registry_failures`
WHERE player_lookup = 'marcusmorris'
  AND resolved_at IS NOT NULL      -- Alias has been created
  AND reprocessed_at IS NULL       -- Not yet reprocessed
ORDER BY game_date
```

Or use the reprocess script which queries this automatically:
```bash
python tools/player_registry/reprocess_resolved.py --dry-run
```

See the [Registry Failures Runbook](../observability/registry-failures.md) for full details on monitoring and managing registry failures.

---

## Current Aliases

| Alias | Canonical | Type |
|-------|-----------|------|
| `marcusmorris` | `marcusmorrissr` | suffix_difference |
| `robertwilliams` | `robertwilliamsiii` | suffix_difference |
| `xaviertillmansr` | `xaviertillman` | suffix_difference |
| `kevinknox` | `kevinknoxii` | suffix_difference |
| `filippetruaev` | `filippetrusev` | encoding_difference |
| `matthewhurt` | `matthurt` | name_variation |
| `derrickwalton` | `derrickwaltonjr` | suffix_difference |
| `ggjacksonii` | `ggjackson` | suffix_difference |

---

## Validation Queries

### Check Pending Unresolved Count
```sql
SELECT COUNT(*) as pending_count
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending'
```

### View Top Unresolved Names
```sql
SELECT
    normalized_lookup,
    raw_name,
    source_name,
    COUNT(*) as occurrences
FROM `nba-props-platform.nba_reference.unresolved_player_names`
WHERE status = 'pending'
GROUP BY normalized_lookup, raw_name, source_name
ORDER BY occurrences DESC
LIMIT 20
```

### Check Alias Coverage
```sql
SELECT alias_type, COUNT(*) as count, SUM(CASE WHEN is_active THEN 1 ELSE 0 END) as active
FROM `nba-props-platform.nba_reference.player_aliases`
GROUP BY alias_type
```

---

## Troubleshooting

### "Anthropic API key not found"
```bash
# Check if env var is set
echo $ANTHROPIC_API_KEY

# Set it
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

### High Unresolved Count After Backfill
1. **Check if it's timing issues**: Names exist in registry but analytics ran first
   - Solution: Use two-pass backfill

2. **Check if aliases needed**: Genuine name mismatches
   - Solution: Run AI resolution

### AI Resolution Not Working
1. Verify API key: `echo $ANTHROPIC_API_KEY`
2. Check anthropic package: `pip show anthropic`
3. Check Secret Manager (Cloud Run): `gcloud secrets describe anthropic-api-key`

---

## Cost Estimates

| Usage | Cost |
|-------|------|
| Per name resolution | ~$0.0001 |
| 100 names | ~$0.01 |
| Monthly (steady state) | ~$1-5 |

---

## Related Files

| File | Purpose |
|------|---------|
| `bin/backfill/run_two_pass_backfill.sh` | Two-pass backfill script |
| `tools/player_registry/resolve_unresolved_batch.py` | Batch AI resolution |
| `tools/player_registry/reprocess_resolved.py` | Reprocess after aliases |
| `monitoring/resolution_health_check.py` | Health monitoring |
| `shared/utils/player_registry/ai_resolver.py` | AI resolver implementation |
| `shared/utils/player_registry/alias_manager.py` | Alias CRUD operations |

---

## Related Documentation

- **Registry Failures Runbook:** `docs/02-operations/runbooks/observability/registry-failures.md` - Monitor and manage registry failures
- **Failure Tracking Design:** `docs/08-projects/current/observability/FAILURE-TRACKING-DESIGN.md` - Technical design
- **AI Name Resolution Design:** `docs/08-projects/current/ai-name-resolution/DESIGN-DOC-AI-NAME-RESOLUTION.md`

---

**Last Verified:** 2025-12-06
**Maintained By:** NBA Platform Team
