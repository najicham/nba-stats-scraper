# Cross-Source Reconciliation

**Priority**: P2
**Effort**: 4-6 hours
**Status**: Investigation

---

## Problem Statement

We ingest data from multiple sources:
- NBA.com (official stats)
- Ball Don't Lie API (BDL)
- ESPN (rosters, schedules)
- Odds API (betting lines)

These sources can disagree on values. Currently we don't systematically compare them.

---

## Proposed Solution

Daily reconciliation query comparing key stats between sources.

### Comparison Query
```sql
-- Compare points between NBA.com and BDL
WITH nba_stats AS (
  SELECT game_id, player_id, pts
  FROM nba_raw.nbacom_boxscores
  WHERE game_date = CURRENT_DATE() - 1
),
bdl_stats AS (
  SELECT game_id, player_id, pts
  FROM nba_raw.bdl_player_boxscores
  WHERE game_date = CURRENT_DATE() - 1
)
SELECT
  n.game_id,
  n.player_id,
  n.pts as nba_pts,
  b.pts as bdl_pts,
  ABS(n.pts - b.pts) as difference
FROM nba_stats n
JOIN bdl_stats b USING (game_id, player_id)
WHERE ABS(n.pts - b.pts) > 2  -- Flag if >2 point difference
ORDER BY difference DESC;
```

---

## Implementation Plan

### Step 1: Create Reconciliation View
```sql
CREATE VIEW nba_monitoring.source_reconciliation AS
-- Compare all key stats: pts, reb, ast, etc.
```

### Step 2: Create Scheduled Query
Run hourly to check for discrepancies.

### Step 3: Add to /validate-daily
Report any significant discrepancies in daily validation.

---

## Investigation Questions

1. What tables contain BDL vs NBA.com data?
2. How do we match players between sources (player_id mapping)?
3. What's the expected discrepancy threshold? (0? 1? 2?)
4. Are there known cases where sources legitimately differ?
5. Should we prefer one source over another?

---

## Success Criteria

- [ ] Daily reconciliation runs automatically
- [ ] Discrepancies >2 points flagged
- [ ] Source preference decisions documented
