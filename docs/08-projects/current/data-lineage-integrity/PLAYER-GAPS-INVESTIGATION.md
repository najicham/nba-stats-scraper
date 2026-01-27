# Player Gaps Investigation Findings

**Date**: 2026-01-26
**Status**: Root cause identified, fix pending

---

## Executive Summary

Investigation into ERROR_HAS_MINUTES gaps found a **systemic Phase 3 processor bug** that skips ~10-15 players per game day who actually played.

This is NOT the same as DNP filtering (which is intentional) - these are players with real playing time.

---

## Investigation Timeline

### Initial Finding
`/spot-check-gaps` identified 20 ERROR_HAS_MINUTES cases - players in boxscores with actual minutes but missing from `player_game_summary`.

### Deep Dive
Checked specific players:
- Jimmy Butler - 18 games missing
- Carlton Carrington - up to 40 minutes missing
- Hansen Yang - 14 games missing

### Systemic Pattern
Checked Jan 7, 2026:
- 419 players in boxscores
- 250 players in analytics
- **169 players missing (40%)**

### Root Cause
Breakdown by minutes:
| Minutes | Total | In Analytics | Missing |
|---------|-------|--------------|---------|
| 0 (DNP) | 159 | 0 | 159 | ← Intentional filter |
| 1-5 | 27 | 25 | 2 | ← Bug |
| 6-10 | 12 | 11 | 1 | ← Bug |
| 11-20 | 66 | 64 | 2 | ← Bug |
| 21+ | 155 | 150 | 5 | ← Bug |

**~10 players per day with real playing time are being skipped.**

---

## Affected Players (Jan 7 Sample)

| Player | Minutes | Points | Team | Status |
|--------|---------|--------|------|--------|
| carltoncarrington | 40 | 18 | WAS | **Major** |
| jimmybutler | 32 | 21 | GSW | Traded |
| alexandresarr | 27 | 15 | WAS | **Major** |
| nicolasclaxton | 23 | 7 | BKN | - |
| hugogonzlez | 21 | 3 | BOS | - |
| nolantraor | 20 | 6 | BKN | - |
| hansenyang | 17 | 3 | POR | - |
| airiousbailey | 10 | 2 | UTA | - |
| chrismaon | 1 | 0 | LAL | - |
| davidjones | 1 | 0 | SAS | - |

---

## Hypotheses for Root Cause

### 1. Primary Source Mismatch
- Phase 3 processor uses `nbac_gamebook_player_stats` as primary source
- If a player is in BDL but NOT in NBA.com gamebook, they might be skipped
- BDL fallback might not be working correctly

### 2. Registry Lookup Failures
- Processor may silently skip players it can't find in registry
- New players or name variations could cause lookup failures

### 3. Game ID Mismatch
- Player's game_id in boxscore might not match analytics game_id
- Join failing silently

### 4. Processing Order/Timing
- If player data arrives after initial processing
- Re-processing doesn't pick up all players

---

## Impact Assessment

### Data Quality Impact
- ~10 players × ~50 games = **~500 missing records this season**
- Includes star players (Jimmy Butler, Carlton Carrington)
- Rolling averages and ML features potentially affected

### Cascade Impact
- Missing records → incorrect rolling averages for games AFTER the gap
- L10 window: could affect 20+ future records per gap
- ML predictions could use incomplete features

---

## Recommended Actions

### Immediate (P1)
1. **Investigate Phase 3 processor** - Find where players are being filtered/skipped
2. **Check primary vs fallback source logic** - Is BDL fallback working?
3. **Add logging** - Log when players are skipped and why

### Short-term (P2)
4. **Backfill missing records** - Re-run processor for affected dates
5. **Run cascade remediation** - Recompute downstream records

### Long-term (P3)
6. **Add validation** - Daily check for boxscore vs analytics discrepancy
7. **Alert on gaps** - Slack alert if >5 players missing per day

---

## Root Cause Found (Jan 26 Investigation)

### The Actual Bug

Players without a `universal_player_id` in the registry are skipped entirely:

```python
# player_game_summary_processor.py line 1658-1678
if universal_player_id is None:
    self.registry_stats['records_skipped'] += 1
    continue  # ← SKIPS THE PLAYER ENTIRELY
```

### Name Normalization Mismatch

BDL API sends different name formats than the registry:

| Boxscore (BDL) | Registry | Issue |
|----------------|----------|-------|
| `hugogonzlez` | `hugogonzalez` | Missing 'a' |
| `nolantraor` | `nolantraore` | Missing 'e' |
| `hansenyang` | `yanghansen` | First/last swapped |
| `kasparasjakuionis` | `kasparasjakucionis` | Missing 'c' |

### Timeline

1. Players had mismatched names → skipped by processor
2. Unresolved player system detected them
3. Resolutions added (Jan 3-4, 2026) - aliases created
4. **New games (Jan 22+) now work** - resolutions in effect
5. **Historical games (pre-resolution) still missing** - need reprocessing

### Verification

Recent games DO have analytics:
```sql
SELECT game_date, player_lookup, points
FROM nba_analytics.player_game_summary
WHERE player_lookup IN ('hansenyang', 'hugogonzlez', 'nolantraor', 'kasparasjakuionis')
  AND game_date >= '2026-01-20'
-- Returns records for Jan 22-26
```

### Fix Required

**Reprocess Phase 3 for historical dates** to pick up the resolutions:

```bash
# Reprocess Jan 1-21 for affected players
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2026-01-01 \
  --end-date 2026-01-21
```

## Files to Investigate

```
data_processors/analytics/player_game_summary/
├── player_game_summary_processor.py  # Main processor - line 1658-1678 is the skip logic
├── source_selector.py                # Primary/fallback logic
├── player_registry.py               # Player lookup wrapper
└── quality_scorer.py                # Quality filtering
```

---

## Verification Queries

### Count missing players per day
```sql
SELECT
    b.game_date,
    COUNT(DISTINCT b.player_lookup) as boxscore_players,
    COUNT(DISTINCT pgs.player_lookup) as analytics_players,
    COUNT(DISTINCT b.player_lookup) - COUNT(DISTINCT pgs.player_lookup) as gap
FROM nba_raw.bdl_player_boxscores b
LEFT JOIN nba_analytics.player_game_summary pgs
    ON b.player_lookup = pgs.player_lookup AND b.game_date = pgs.game_date
WHERE b.game_date >= '2026-01-01'
  AND b.minutes NOT IN ('00', '0')
GROUP BY b.game_date
HAVING gap > 5
ORDER BY b.game_date
```

### Find specific missing players for a date
```sql
SELECT
    b.player_lookup, b.minutes, b.team_abbr, b.points
FROM nba_raw.bdl_player_boxscores b
LEFT JOIN nba_analytics.player_game_summary pgs
    ON b.player_lookup = pgs.player_lookup AND b.game_date = pgs.game_date
WHERE b.game_date = @date
  AND b.minutes NOT IN ('00', '0')
  AND SAFE_CAST(b.minutes AS INT64) > 0
  AND pgs.player_lookup IS NULL
ORDER BY SAFE_CAST(b.minutes AS INT64) DESC
```

---

## Related Documents

- [SPOT-CHECK-INTEGRATION.md](./SPOT-CHECK-INTEGRATION.md) - Spot check skills
- [DESIGN-DECISIONS.md](./DESIGN-DECISIONS.md) - Data lineage architecture
- Phase 3 processor: `data_processors/analytics/player_game_summary/`
