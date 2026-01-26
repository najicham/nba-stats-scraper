# Source-Block Tracking System Design

**Date:** 2026-01-26
**Status:** Design Proposal
**Purpose:** Track data availability issues at the resource level to distinguish between infrastructure failures and source-level unavailability

---

## Problem Statement

### Current State

We have `nba_orchestration.proxy_health_metrics` which tracks proxy request success/failure at the **host level**:
- ✅ Tracks: `cdn.nba.com` returned 403
- ❌ Doesn't track: **Which specific game** returned 403
- ❌ Doesn't distinguish: Infrastructure failure vs source unavailability

### The Gap

When validation tools check data completeness, they can't tell the difference between:
1. **Infrastructure failure** - Our scraper broke, needs fixing
2. **Source block** - Specific resource blocked/removed by source (NBA.com returned 403 for specific game)
3. **Source unavailable** - Data never existed at source (both BDB and NBA.com missing same games)

### Real Example (2026-01-25)

**Situation:**
- 8 games scheduled on 2026-01-25
- 6 games successfully scraped from both BDB and NBA.com
- 2 games missing from BOTH sources: 0022500651 (DEN @ MEM), 0022500652 (DAL @ MIL)

**Current behavior:**
- ❌ Validation flags 2026-01-25 as incomplete (25% data missing)
- ❌ Monitoring shows 75% success rate (looks like failure)
- ❌ No way to know if this is a scraper bug or source issue

**Desired behavior:**
- ✅ Validation knows these specific games are source-unavailable
- ✅ Monitoring shows 100% of available data collected
- ✅ Alerts fire only for infrastructure failures, not source issues

---

## Proposed Solution

### Approach: Two-Level Tracking

**Level 1: Host-Level Tracking** (existing)
- Table: `nba_orchestration.proxy_health_metrics`
- Tracks proxy request patterns across hosts
- Purpose: Monitor proxy health, detect rate limiting

**Level 2: Resource-Level Tracking** (new)
- Table: `nba_orchestration.source_blocked_resources`
- Tracks specific resources (games, files) unavailable at source
- Purpose: Inform validation tools of legitimate data gaps

---

## Schema Design

### New Table: `source_blocked_resources`

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.source_blocked_resources (
  -- Resource Identification
  resource_id STRING NOT NULL,              -- e.g., "0022500651", "player_12345"
  resource_type STRING NOT NULL,            -- e.g., "play_by_play", "boxscore", "player_stats"
  game_date DATE,                           -- Associated game date (nullable for non-game resources)

  -- Source Information
  source_system STRING NOT NULL,            -- e.g., "nba_com_cdn", "bdb", "bdl"
  source_url STRING,                        -- Full URL that returned error

  -- Block Status
  http_status_code INT64,                   -- e.g., 403, 404, 410
  block_type STRING NOT NULL,               -- "http_error", "not_found", "removed", "access_denied"

  -- Verification Tracking
  first_detected_at TIMESTAMP NOT NULL,     -- When we first detected the block
  last_verified_at TIMESTAMP NOT NULL,      -- Last time we checked (for periodic re-checks)
  verification_count INT64 DEFAULT 1,       -- How many times we've verified it's blocked

  -- Alternative Source Tracking
  available_from_alt_source BOOL,           -- Is this available from another source?
  alt_source_system STRING,                 -- Which alternative source has it (if any)
  alt_source_verified_at TIMESTAMP,         -- When we verified alt source has it

  -- Metadata
  notes STRING,                             -- Human-readable explanation
  created_by STRING,                        -- "scraper", "manual", "backfill"

  -- Resolution Tracking
  is_resolved BOOL DEFAULT FALSE,           -- Set to TRUE if source block lifted
  resolved_at TIMESTAMP,                    -- When block was lifted
  resolution_notes STRING                   -- How it was resolved
)
PARTITION BY game_date
CLUSTER BY resource_type, source_system, block_type;
```

### Example Data

```sql
-- 2026-01-25 incident games
INSERT INTO nba_orchestration.source_blocked_resources VALUES
(
  '0022500651',                                                     -- resource_id
  'play_by_play',                                                   -- resource_type
  '2026-01-25',                                                     -- game_date
  'nba_com_cdn',                                                    -- source_system
  'https://cdn.nba.com/.../playbyplay_0022500651.json',           -- source_url
  403,                                                              -- http_status_code
  'access_denied',                                                  -- block_type
  '2026-01-26 06:43:05',                                           -- first_detected_at
  '2026-01-26 15:39:57',                                           -- last_verified_at
  3,                                                                -- verification_count
  FALSE,                                                            -- available_from_alt_source
  NULL,                                                             -- alt_source_system
  NULL,                                                             -- alt_source_verified_at
  'DEN @ MEM - NBA.com CDN returning 403. Also missing from BDB.', -- notes
  'scraper',                                                        -- created_by
  FALSE,                                                            -- is_resolved
  NULL,                                                             -- resolved_at
  NULL                                                              -- resolution_notes
),
(
  '0022500652',
  'play_by_play',
  '2026-01-25',
  'nba_com_cdn',
  'https://cdn.nba.com/.../playbyplay_0022500652.json',
  403,
  'access_denied',
  '2026-01-26 06:43:10',
  '2026-01-26 15:40:02',
  3,
  FALSE,
  NULL,
  NULL,
  'DAL @ MIL - NBA.com CDN returning 403. Also missing from BDB.',
  'scraper',
  FALSE,
  NULL,
  NULL
);
```

---

## Integration Points

### 1. Scraper Integration

**When scraper encounters HTTP error:**

```python
# In http_handler_mixin.py or similar
def handle_http_error(self, response, url: str):
    """Handle HTTP errors and log to tracking systems."""

    # Existing: Log to proxy_health_metrics (host-level)
    from shared.utils.proxy_health_logger import log_proxy_result
    log_proxy_result(
        scraper_name=self.scraper_name,
        target_host=urlparse(url).netloc,
        http_status_code=response.status_code,
        success=False,
        error_type=classify_error(response.status_code)
    )

    # NEW: If specific resource blocked, log to source_blocked_resources
    if response.status_code in [403, 404, 410]:
        from shared.utils.source_block_tracker import record_source_block
        record_source_block(
            resource_id=self.extract_resource_id(url),  # e.g., game_id from URL
            resource_type=self.resource_type,            # e.g., "play_by_play"
            source_system=self.source_system,            # e.g., "nba_com_cdn"
            source_url=url,
            http_status_code=response.status_code,
            game_date=self.opts.get('game_date')
        )
```

### 2. Validation Integration

**Update completeness checks:**

```python
# In validation tools
def check_pbp_completeness(game_date: str) -> Dict[str, Any]:
    """Check PBP data completeness, accounting for source blocks."""

    # Get expected games for date
    expected_games = get_games_for_date(game_date)

    # Get source-blocked games for this date
    blocked_games = get_source_blocked_resources(
        game_date=game_date,
        resource_type='play_by_play'
    )

    # Get actual games in storage
    actual_games_bdb = get_bdb_pbp_games(game_date)
    actual_games_nba = get_nba_com_pbp_games(game_date)

    # Calculate expected = total - blocked
    blocked_ids = [g['resource_id'] for g in blocked_games]
    expected_available = len(expected_games) - len(blocked_ids)
    actual_count = len(actual_games_bdb)  # Use primary source

    return {
        'complete': actual_count >= expected_available,
        'total_games': len(expected_games),
        'blocked_games': len(blocked_ids),
        'blocked_game_ids': blocked_ids,
        'expected_available': expected_available,
        'actual_available': actual_count,
        'missing_games': max(0, expected_available - actual_count),
        'coverage_pct': (actual_count / expected_available * 100) if expected_available > 0 else 0
    }
```

### 3. Monitoring Integration

**Updated dashboard queries:**

```sql
-- Daily PBP Coverage Dashboard
WITH expected_games AS (
  SELECT game_date, COUNT(*) as total_games
  FROM schedule
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
),
blocked_games AS (
  SELECT game_date, COUNT(*) as blocked_count
  FROM nba_orchestration.source_blocked_resources
  WHERE resource_type = 'play_by_play'
    AND game_date >= CURRENT_DATE() - 7
    AND is_resolved = FALSE
  GROUP BY game_date
),
actual_games AS (
  SELECT game_date, COUNT(DISTINCT game_id) as actual_count
  FROM nba_raw.bigdataball_play_by_play
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
)
SELECT
  e.game_date,
  e.total_games,
  COALESCE(b.blocked_count, 0) as blocked_games,
  e.total_games - COALESCE(b.blocked_count, 0) as expected_available,
  COALESCE(a.actual_count, 0) as actual_collected,
  CASE
    WHEN e.total_games - COALESCE(b.blocked_count, 0) = 0 THEN 100.0
    ELSE ROUND(COALESCE(a.actual_count, 0) / (e.total_games - COALESCE(b.blocked_count, 0)) * 100, 1)
  END as coverage_pct,
  CASE
    WHEN COALESCE(a.actual_count, 0) >= (e.total_games - COALESCE(b.blocked_count, 0)) THEN '✅ Complete'
    ELSE '⚠️ Missing Data'
  END as status
FROM expected_games e
LEFT JOIN blocked_games b ON e.game_date = b.game_date
LEFT JOIN actual_games a ON e.game_date = a.game_date
ORDER BY e.game_date DESC;
```

---

## Helper Functions

### Python Module: `shared/utils/source_block_tracker.py`

```python
"""
Source Block Tracker - Record and query resource-level source blocks.

Usage:
    from shared.utils.source_block_tracker import record_source_block, get_source_blocked_resources

    # Record a block
    record_source_block(
        resource_id="0022500651",
        resource_type="play_by_play",
        source_system="nba_com_cdn",
        source_url="https://...",
        http_status_code=403,
        game_date="2026-01-25"
    )

    # Query blocks
    blocked = get_source_blocked_resources(
        game_date="2026-01-25",
        resource_type="play_by_play"
    )
```

```python
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

def record_source_block(
    resource_id: str,
    resource_type: str,
    source_system: str,
    http_status_code: int,
    source_url: Optional[str] = None,
    game_date: Optional[str] = None,
    notes: Optional[str] = None,
    block_type: Optional[str] = None
) -> bool:
    """
    Record a source block in BigQuery.

    Uses MERGE to update if already exists (increments verification_count),
    or inserts new record if first time seeing this block.
    """
    try:
        from shared.utils.bigquery_utils import get_bigquery_client

        client = get_bigquery_client()
        now = datetime.now(timezone.utc)

        # Classify block type from HTTP status
        if block_type is None:
            block_type = classify_block_type(http_status_code)

        # MERGE query: update if exists, insert if new
        query = f"""
        MERGE nba_orchestration.source_blocked_resources AS target
        USING (
          SELECT
            '{resource_id}' AS resource_id,
            '{resource_type}' AS resource_type,
            '{source_system}' AS source_system
        ) AS source
        ON target.resource_id = source.resource_id
          AND target.resource_type = source.resource_type
          AND target.source_system = source.source_system
          AND target.is_resolved = FALSE
        WHEN MATCHED THEN
          UPDATE SET
            last_verified_at = '{now.isoformat()}',
            verification_count = verification_count + 1,
            http_status_code = {http_status_code}
        WHEN NOT MATCHED THEN
          INSERT (
            resource_id, resource_type, game_date, source_system, source_url,
            http_status_code, block_type, first_detected_at, last_verified_at,
            verification_count, available_from_alt_source, notes, created_by,
            is_resolved
          )
          VALUES (
            '{resource_id}',
            '{resource_type}',
            {'NULL' if game_date is None else f"'{game_date}'"},
            '{source_system}',
            {'NULL' if source_url is None else f"'{source_url}'"},
            {http_status_code},
            '{block_type}',
            '{now.isoformat()}',
            '{now.isoformat()}',
            1,
            FALSE,
            {'NULL' if notes is None else f"'{notes[:500]}'"},
            'scraper',
            FALSE
          )
        """

        query_job = client.query(query)
        query_job.result()  # Wait for completion

        logger.info(f"Recorded source block: {resource_id} ({resource_type}) from {source_system}")
        return True

    except Exception as e:
        logger.warning(f"Failed to record source block: {e}")
        return False


def get_source_blocked_resources(
    game_date: Optional[str] = None,
    resource_type: Optional[str] = None,
    source_system: Optional[str] = None,
    include_resolved: bool = False
) -> List[Dict[str, Any]]:
    """
    Query source-blocked resources.

    Returns list of blocked resources matching filters.
    """
    try:
        from shared.utils.bigquery_utils import get_bigquery_client

        client = get_bigquery_client()

        where_clauses = []
        if game_date:
            where_clauses.append(f"game_date = '{game_date}'")
        if resource_type:
            where_clauses.append(f"resource_type = '{resource_type}'")
        if source_system:
            where_clauses.append(f"source_system = '{source_system}'")
        if not include_resolved:
            where_clauses.append("is_resolved = FALSE")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        query = f"""
        SELECT
          resource_id,
          resource_type,
          game_date,
          source_system,
          source_url,
          http_status_code,
          block_type,
          first_detected_at,
          last_verified_at,
          verification_count,
          available_from_alt_source,
          alt_source_system,
          notes
        FROM nba_orchestration.source_blocked_resources
        WHERE {where_sql}
        ORDER BY game_date DESC, resource_id
        """

        query_job = client.query(query)
        results = query_job.result()

        return [dict(row) for row in results]

    except Exception as e:
        logger.warning(f"Failed to query source blocks: {e}")
        return []


def classify_block_type(http_status_code: int) -> str:
    """Classify block type from HTTP status code."""
    if http_status_code == 403:
        return "access_denied"
    elif http_status_code == 404:
        return "not_found"
    elif http_status_code == 410:
        return "removed"
    elif http_status_code >= 500:
        return "server_error"
    else:
        return "http_error"


def mark_block_resolved(
    resource_id: str,
    resource_type: str,
    source_system: str,
    resolution_notes: Optional[str] = None
) -> bool:
    """Mark a source block as resolved."""
    try:
        from shared.utils.bigquery_utils import get_bigquery_client

        client = get_bigquery_client()
        now = datetime.now(timezone.utc)

        query = f"""
        UPDATE nba_orchestration.source_blocked_resources
        SET
          is_resolved = TRUE,
          resolved_at = '{now.isoformat()}',
          resolution_notes = {'NULL' if resolution_notes is None else f"'{resolution_notes}'"}
        WHERE resource_id = '{resource_id}'
          AND resource_type = '{resource_type}'
          AND source_system = '{source_system}'
          AND is_resolved = FALSE
        """

        query_job = client.query(query)
        query_job.result()

        logger.info(f"Marked source block as resolved: {resource_id}")
        return True

    except Exception as e:
        logger.warning(f"Failed to mark block as resolved: {e}")
        return False
```

---

## Rollout Plan

### Phase 1: Setup (30 minutes)
1. Create `source_blocked_resources` table
2. Create `shared/utils/source_block_tracker.py` module
3. Insert 2026-01-25 blocked games manually
4. Test queries

### Phase 2: Integration (1 hour)
1. Update PBP scraper to call `record_source_block()` on 403/404
2. Update validation functions to check `source_blocked_resources`
3. Update monitoring dashboards with new queries
4. Test with 2026-01-25 data

### Phase 3: Validation (30 minutes)
1. Run validation on 2026-01-25 - should show 100% complete
2. Check monitoring dashboard - should show correct coverage
3. Verify proxy_health_metrics still being populated
4. Document usage in runbooks

### Phase 4: Historical Audit (1-2 hours)
1. Run audit query to find historical missing data
2. Investigate patterns
3. Backfill `source_blocked_resources` if needed
4. Document findings

---

## Success Metrics

### Before Implementation
- ❌ 2026-01-25 validation: FAIL (6/8 games = 75%)
- ❌ Monitoring: Shows failures for missing games
- ❌ No way to distinguish infrastructure vs source issues

### After Implementation
- ✅ 2026-01-25 validation: PASS (6/6 available games = 100%)
- ✅ Monitoring: Shows 100% of available data collected
- ✅ Clear visibility: 2 games source-blocked, rest complete
- ✅ Future incidents: Automatic tracking and validation

---

## FAQ

### Q: Why not just add fields to proxy_health_metrics?

**A:** proxy_health_metrics tracks **host-level** patterns (useful for proxy health monitoring). We need **resource-level** tracking (specific games) for validation purposes. These serve different purposes and should remain separate.

### Q: Should we automatically record source blocks in scrapers?

**A:** Yes, but with care:
- ✅ Auto-record for 403 (access denied)
- ✅ Auto-record for 404 (not found) after retry
- ✅ Auto-record for 410 (gone)
- ⚠️ Consider threshold: only record after N consecutive failures
- ❌ Don't auto-record for 500s (server errors) - these are transient

### Q: How do we handle periodic re-checks?

**A:** Add a periodic job (weekly) that:
1. Queries unresolved blocks from `source_blocked_resources`
2. Re-attempts to fetch each resource
3. If HTTP 200: marks as resolved
4. If still blocked: increments verification_count
5. Alerts on newly resolved blocks

### Q: What if a game is available from alternative source?

**A:** Update the record:
```python
update_alt_source_availability(
    resource_id="0022500651",
    resource_type="play_by_play",
    source_system="nba_com_cdn",
    alt_source_system="pbpstats",
    alt_source_verified_at=datetime.now()
)
```

---

## Next Steps

1. **Get approval** on schema design
2. **Create table** and helper functions
3. **Insert 2026-01-25 data** manually
4. **Test integration** with one scraper (PBP)
5. **Roll out** to all scrapers gradually
6. **Run historical audit** and backfill if needed

---

## Related Documentation

- `proxy_health_logger.py` - Existing host-level tracking
- `validation_system.md` - Validation framework
- `SOURCE-BLOCKED-GAMES-ANALYSIS.md` - 2026-01-25 incident analysis
