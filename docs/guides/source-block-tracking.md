# Source-Block Tracking System - User Guide

**Version:** 1.0
**Status:** Production Ready
**Last Updated:** 2026-01-26

---

## Overview

The source-block tracking system distinguishes between:
- **Infrastructure failures** - Your scrapers are broken (needs fixing)
- **Source blocks** - Specific resources blocked by source (expected)
- **Source unavailable** - Data doesn't exist anywhere (acceptable)

**Before:** Validation shows "6/8 games = 75% (FAIL)"
**After:** Validation shows "6/6 available games = 100% (PASS), 2 source-blocked"

---

## Quick Start

### Query Blocked Resources

```python
from shared.utils.source_block_tracker import get_source_blocked_resources

# Get all blocked games for a date
blocks = get_source_blocked_resources(
    game_date="2026-01-25",
    resource_type="play_by_play"
)

for block in blocks:
    print(f"{block['resource_id']}: {block['notes']}")
```

### Record a Block (Automatic)

Scrapers automatically record blocks when encountering 403/404/410:

```python
# Happens automatically in http_handler_mixin.py
# When scraper gets 403, it calls:
record_source_block(
    resource_id=game_id,
    resource_type="play_by_play",
    source_system="cdn_nba_com",
    http_status_code=403,
    source_url=url,
    game_date=game_date
)
```

### Manual Recording

```python
from shared.utils.source_block_tracker import record_source_block

# Record a block manually
record_source_block(
    resource_id="0022500651",
    resource_type="play_by_play",
    source_system="nba_com_cdn",
    source_url="https://cdn.nba.com/.../playbyplay_0022500651.json",
    http_status_code=403,
    game_date="2026-01-25",
    notes="DEN @ MEM - Blocked by NBA.com CDN",
    created_by="manual"
)
```

### Mark Block Resolved

```python
from shared.utils.source_block_tracker import mark_block_resolved

# If a previously blocked resource becomes available
mark_block_resolved(
    resource_id="0022500651",
    resource_type="play_by_play",
    source_system="nba_com_cdn",
    resolution_notes="Block lifted, data now available"
)
```

---

## How It Works

### Data Flow

```
1. Scraper encounters HTTP 403 from cdn.nba.com
   ↓
2. Logs to proxy_health_metrics (host-level: cdn.nba.com)
   ↓
3. Records to source_blocked_resources (resource-level: game 0022500651)
   ↓
4. Validation script queries blocked resources
   ↓
5. Adjusts expected counts (total - blocked = expected available)
   ↓
6. Shows: "6/6 available games (100%), 2 source-blocked"
```

### Storage

**Table:** `nba_orchestration.source_blocked_resources`

**Key Fields:**
- `resource_id` - Game ID, player ID, etc.
- `resource_type` - "play_by_play", "boxscore", etc.
- `source_system` - "nba_com_cdn", "bdb", etc.
- `http_status_code` - 403, 404, 410
- `block_type` - "access_denied", "not_found", "removed"
- `is_resolved` - TRUE if block lifted
- `verification_count` - How many times verified blocked

---

## Common Use Cases

### 1. Check Why Validation Shows Missing Data

```python
# Validation shows: "2 games missing"
# Check if they're source-blocked:

from shared.utils.source_block_tracker import get_source_blocked_resources

blocks = get_source_blocked_resources(game_date="2026-01-25")
if blocks:
    print("These games are source-blocked (not failures):")
    for b in blocks:
        print(f"  - {b['resource_id']}: {b['notes']}")
else:
    print("Not source-blocked - investigate scraper issues")
```

### 2. Monitor Active Blocks

```sql
-- Run this query to see what's currently blocked
SELECT * FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
WHERE is_resolved = FALSE
  AND game_date >= CURRENT_DATE() - 7
ORDER BY game_date DESC;
```

Or use the pre-made query:
```bash
bq query --use_legacy_sql=false < sql/queries/source_blocks_active.sql
```

### 3. Calculate Accurate Coverage %

```bash
# Shows coverage % accounting for source blocks
bq query --use_legacy_sql=false < sql/queries/source_blocks_coverage.sql
```

Example output:
```
game_date  | total | blocked | expected | actual | coverage | status
2026-01-25 |   8   |    2    |    6     |   6    |  100.0%  | ✅ Complete
```

### 4. Identify Problematic Sources

```bash
# See which sources block most frequently
bq query --use_legacy_sql=false < sql/queries/source_blocks_patterns.sql
```

---

## Validation Script Integration

The validation script (`scripts/validate_tonight_data.py`) automatically:

1. Queries source-blocked resources for the target date
2. Subtracts blocked count from expected count
3. Only flags real failures (missing non-blocked games)
4. Shows blocked games separately in output

### Example Output

**Before source-block tracking:**
```
✗ Game Context: 6/8 games found (25% missing)
Issues: 2 failures
```

**After source-block tracking:**
```
✓ Game Context: 6/6 available games, 211 total players
  ℹ️  2 games source-blocked (not counted as failures)
Issues: 0
```

---

## Monitoring Queries

### Active Blocks by Date
```bash
bq query < sql/queries/source_blocks_active.sql
```

Shows: Current date, which resources blocked, from which sources

### Coverage Percentage
```bash
bq query < sql/queries/source_blocks_coverage.sql
```

Shows: Actual coverage % accounting for blocked resources

### Block Patterns
```bash
bq query < sql/queries/source_blocks_patterns.sql
```

Shows: Which sources/resources block most frequently

### Resolution Tracking
```bash
bq query < sql/queries/source_blocks_resolution.sql
```

Shows: Blocks that were resolved, how long they lasted

---

## API Reference

### record_source_block()

```python
def record_source_block(
    resource_id: str,              # Required: Resource ID (e.g., game_id)
    resource_type: str,            # Required: "play_by_play", "boxscore", etc.
    source_system: str,            # Required: "nba_com_cdn", "bdb", etc.
    http_status_code: int,         # Required: 403, 404, 410, etc.
    source_url: str = None,        # Optional: Full URL that failed
    game_date: str = None,         # Optional: YYYY-MM-DD format
    notes: str = None,             # Optional: Human-readable explanation
    block_type: str = None,        # Optional: Override auto-classification
    created_by: str = "scraper"    # Optional: "scraper", "manual", etc.
) -> bool
```

**Returns:** `True` if successful, `False` otherwise

**Behavior:** Uses MERGE - if block already exists, increments `verification_count`

### get_source_blocked_resources()

```python
def get_source_blocked_resources(
    game_date: str = None,         # Optional: Filter by date (YYYY-MM-DD)
    resource_type: str = None,     # Optional: Filter by type
    source_system: str = None,     # Optional: Filter by source
    include_resolved: bool = False # Optional: Include resolved blocks
) -> List[Dict[str, Any]]
```

**Returns:** List of blocked resources as dictionaries

**Fields in result:**
- resource_id, resource_type, game_date
- source_system, source_url, http_status_code, block_type
- first_detected_at, last_verified_at, verification_count
- is_resolved, resolved_at, resolution_notes
- notes, available_from_alt_source, alt_source_system

### mark_block_resolved()

```python
def mark_block_resolved(
    resource_id: str,              # Required: Resource ID
    resource_type: str,            # Required: Resource type
    source_system: str,            # Required: Source system
    resolution_notes: str = None   # Optional: How it was resolved
) -> bool
```

**Returns:** `True` if successful, `False` otherwise

**Behavior:** Sets `is_resolved = TRUE`, records `resolved_at` timestamp

### classify_block_type()

```python
def classify_block_type(
    http_status_code: int          # Required: HTTP status code
) -> str
```

**Returns:** Block type classification:
- 403 → "access_denied"
- 404 → "not_found"
- 410 → "removed"
- 500+ → "server_error"
- Other → "http_error"

---

## Troubleshooting

### Q: Validation still shows failures for source-blocked games

**A:** Verify the validation script is querying blocks:
```python
# Check if get_source_blocked_resources() is being called
# Should see this in validate_tonight_data.py check_game_context()
blocked_games = get_source_blocked_resources(...)
```

### Q: Blocks not being recorded automatically

**A:** Check scraper is using `http_handler_mixin.py`:
```python
# Verify scraper inherits from ScraperBase (which uses HttpHandlerMixin)
class MyScraperHere(ScraperBase, ...):
    proxy_enabled = True  # Must be True to use http_handler_mixin
```

### Q: How do I check if a specific game is blocked?

**A:**
```python
from shared.utils.source_block_tracker import get_source_blocked_resources

blocks = get_source_blocked_resources()
game_ids = {b['resource_id'] for b in blocks}

if "0022500651" in game_ids:
    print("Game is source-blocked")
else:
    print("Game not blocked - investigate scraper")
```

### Q: Can I delete or update a block?

**A:** Use `mark_block_resolved()` to mark it resolved. Don't delete - we want historical record.

---

## Best Practices

### 1. Don't Count Blocks as Failures

```python
# BAD: Count total games
expected = 8
actual = 6
if actual < expected:
    raise Error("Missing games!")  # False alarm!

# GOOD: Subtract source-blocked
expected = 8
blocked = 2
expected_available = expected - blocked  # = 6
actual = 6
if actual < expected_available:
    raise Error("Missing games!")  # Real failure
```

### 2. Record Blocks with Useful Notes

```python
# BAD
notes = "Blocked"

# GOOD
notes = "DEN @ MEM - Blocked by NBA.com CDN (HTTP 403). Also checked BDB, unavailable there too."
```

### 3. Check Blocks Before Alerting

```python
# Before alerting on missing data, check if source-blocked
blocks = get_source_blocked_resources(game_date=date, resource_type="play_by_play")
if missing_game_id in {b['resource_id'] for b in blocks}:
    # Expected - source blocked
    pass
else:
    # Unexpected - alert!
    send_alert("Missing game data")
```

### 4. Use Pre-Made Queries

```bash
# Don't write custom queries - use the optimized ones
bq query < sql/queries/source_blocks_coverage.sql
```

---

## Related Documentation

- **API Reference:** `docs/api/source_block_tracker.md` (function signatures)
- **Design Document:** `docs/08-projects/current/2026-01-25-incident-remediation/SOURCE-BLOCK-TRACKING-DESIGN.md`
- **Implementation TODO:** `docs/08-projects/current/source-block-tracking-implementation/TODO.md`
- **Schema:** See `sql/create_source_blocked_resources.sql`
- **Tests:** `tests/test_source_block_tracking.py`

---

## Support

For questions or issues:
1. Check the troubleshooting section above
2. Review the design document
3. Run the test suite: `python tests/test_source_block_tracking.py`
4. Check logs in `nba_orchestration.source_blocked_resources` table

---

**Last Updated:** 2026-01-26
**Version:** 1.0
**Status:** Production Ready
