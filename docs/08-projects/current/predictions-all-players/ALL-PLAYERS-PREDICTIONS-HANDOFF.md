# All-Player Predictions - Architectural Change Handoff

> **SUPERSEDED:** This document has been implemented. See `ALL-PLAYERS-PREDICTIONS-COMPLETE.md` for final implementation details and deployment instructions.

**Created:** 2025-12-01
**Completed:** 2025-12-01
**Status:** IMPLEMENTED
**Priority:** HIGH
**Estimated Effort:** Medium (2-4 hours)

---

## Executive Summary

Currently, the prediction system only generates predictions for players with betting prop lines (~22 players per game day). The user wants predictions for ALL players (~67 per game day) because:

1. Predictions for all players help with future dates
2. Historical predictions improve ML model learning
3. Business value extends beyond just prop-line betting

This document provides a complete handoff for implementing this change.

---

## Current State

### The Limitation

The `upcoming_player_game_context_processor.py` uses props tables as the "DRIVER" query:

```python
# File: data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
# Lines 322-334

def _extract_players_with_props(self) -> None:
    """
    Extract all players who have prop bets for target date.

    This is the DRIVER query - determines which players to process.
    """
    # Queries odds_api_player_points_props or bettingpros_player_points_props
```

### Data Flow (Current)

```
nbac_gamebook_player_stats (67 players)
       │
       ├──→ player_game_summary (67) ✓ All players
       │
       └──→ Props tables (22 with lines)
             │
             ├──→ upcoming_player_game_context (22) ← BOTTLENECK
             │
             ├──→ ml_feature_store_v2 (22)
             │
             └──→ player_prop_predictions (110 = 22 × 5 systems)
```

### Impact

- Only 33% of players get predictions
- No predictions for role players, bench players
- Can't learn from full roster data
- Can't predict for players before they have prop lines

---

## Desired State

### Data Flow (After Change)

```
nbac_gamebook_player_stats (67 players)
       │
       ├──→ player_game_summary (67)
       │
       ├──→ upcoming_player_game_context (67) ← ALL PLAYERS
       │         │
       │         └──→ has_prop_line = TRUE for 22
       │
       ├──→ ml_feature_store_v2 (67)
       │
       └──→ player_prop_predictions (335 = 67 × 5 systems)
                 │
                 └──→ 22 have prop line context for OVER/UNDER
```

### Key Changes

1. **All players flow through prediction pipeline**
2. **New flag tracks which players have prop lines**
3. **Predictions generated for everyone**
4. **OVER/UNDER recommendations only for prop-line players**

---

## Implementation Plan

### Step 1: Modify upcoming_player_game_context_processor.py

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Change:** Replace props-based DRIVER query with gamebook-based query.

**Before (lines 338-362):**
```python
query = """
WITH latest_props AS (
    SELECT player_lookup, game_id, ...
    FROM `{project}.nba_raw.odds_api_player_points_props`
    WHERE game_date = '{target_date}'
    ...
)
SELECT DISTINCT ... FROM latest_props
"""
```

**After:**
```python
query = """
WITH players_with_games AS (
    -- Get ALL players from gamebook who have games on target date
    SELECT DISTINCT
        g.player_lookup,
        g.game_id,
        g.team_abbr,
        g.home_team_abbr,
        g.away_team_abbr
    FROM `{project}.nba_raw.nbac_gamebook_player_stats` g
    WHERE g.game_date = '{target_date}'
      AND g.player_status = 'active'  -- Only active players
),
props AS (
    -- Check which players have prop lines
    SELECT DISTINCT player_lookup, points_line
    FROM `{project}.nba_raw.bettingpros_player_points_props`
    WHERE game_date = '{target_date}'
      AND is_active = TRUE
    UNION DISTINCT
    SELECT DISTINCT player_lookup, points_line
    FROM `{project}.nba_raw.odds_api_player_points_props`
    WHERE game_date = '{target_date}'
)
SELECT
    p.*,
    pr.points_line,
    pr.player_lookup IS NOT NULL as has_prop_line
FROM players_with_games p
LEFT JOIN props pr ON p.player_lookup = pr.player_lookup
"""
```

### Step 2: Add has_prop_line Column

**Schema change:** `schemas/bigquery/nba_analytics/upcoming_player_game_context.sql`

Add column:
```sql
has_prop_line BOOLEAN,  -- TRUE if player has betting prop line for this game
current_points_line FLOAT64,  -- The prop line if available, NULL otherwise
```

**Processor change:** Populate `has_prop_line` and `current_points_line` from the query result.

### Step 3: Update ml_feature_store_processor.py

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Change:** Ensure it processes ALL players from `upcoming_player_game_context`, not filtered.

The processor should already do this since it reads from `upcoming_player_game_context`. Verify no additional filtering.

### Step 4: Update Phase 5 Coordinator

**File:** `predictions/coordinator/player_loader.py`

**Change:** The coordinator queries `upcoming_player_game_context`. It may have filters like:
```python
AND (player_status IS NULL OR player_status NOT IN ('OUT', 'DOUBTFUL'))
```

These are fine to keep (don't predict for injured players). Just ensure no prop-line filtering.

### Step 5: Update Prediction Output

**File:** `predictions/worker/worker.py`

**Change:** For players WITHOUT prop lines:
- Still generate `predicted_points` and `confidence_score`
- Set `recommendation` to `'NO_LINE'` instead of `'OVER'`/`'UNDER'`/`'PASS'`
- Set `current_points_line` to `NULL`
- Set `line_margin` to `NULL`

```python
if not has_prop_line:
    prediction['recommendation'] = 'NO_LINE'
    prediction['current_points_line'] = None
    prediction['line_margin'] = None
```

### Step 6: Add has_prop_line to Predictions Table

**Schema change:** `schemas/bigquery/nba_predictions/01_player_prop_predictions.sql`

Add column:
```sql
has_prop_line BOOLEAN,  -- TRUE if player had betting line when prediction was made
```

---

## Testing Plan

### Unit Tests

1. **Test all players extracted:** Verify gamebook query returns all active players
2. **Test prop line detection:** Verify `has_prop_line` correctly set
3. **Test feature generation:** Verify ml_feature_store has all players
4. **Test prediction output:** Verify 5 systems × all players

### Integration Test

Run for a historical date with known data:
```bash
# Date: 2021-10-19 (season opener, 2 games, ~67 players)
python3 bin/validate_pipeline.py 2021-10-19 --verbose
```

Expected:
- Phase 3: 67 players in upcoming_player_game_context
- Phase 4: 67 players in ml_feature_store_v2
- Phase 5: 335 prediction rows (67 × 5)
- 22 with `has_prop_line = TRUE`
- 45 with `has_prop_line = FALSE`

### Backfill Considerations

After implementation:
1. Reprocess Phase 3 for historical dates
2. Reprocess Phase 4 for historical dates
3. Reprocess Phase 5 for historical dates

This is significant work - may want to only backfill recent dates initially.

---

## Files to Modify

| File | Change |
|------|--------|
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | Change DRIVER query, add has_prop_line |
| `schemas/bigquery/nba_analytics/upcoming_player_game_context.sql` | Add has_prop_line, current_points_line columns |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Verify no prop filtering |
| `predictions/coordinator/player_loader.py` | Verify no prop filtering |
| `predictions/worker/worker.py` | Handle NO_LINE recommendation |
| `schemas/bigquery/nba_predictions/01_player_prop_predictions.sql` | Add has_prop_line column |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Increased processing time | ~3x more players; monitor Cloud Run scaling |
| Increased storage costs | ~3x more prediction rows; acceptable |
| Recommendation confusion | Clear `NO_LINE` status; UI should handle |
| Backfill effort | Prioritize recent dates; optional for historical |

---

## Success Criteria

1. ✅ All active players have predictions (not just prop-line)
2. ✅ `has_prop_line` correctly identifies players with betting lines
3. ✅ OVER/UNDER recommendations only for prop-line players
4. ✅ Validation script shows "67/67 players" instead of "22/67"
5. ✅ No increase in error rate

---

## Questions for Implementer

1. **DNP/Inactive players:** Should we predict for players listed as DNP or inactive in gamebook? Current recommendation: NO (they didn't play).

2. **Historical backfill scope:** How far back should we reprocess? Recommendation: Start with current season (2024-25), expand if needed.

3. **Prop line timing:** Props may not be available until game day. For "upcoming" context (next day's games), how do we handle missing props? Recommendation: Set `has_prop_line = FALSE`, still generate prediction.

---

## Related Documents

- **Validation Script Design:** `docs/08-projects/current/validation/VALIDATION-SCRIPT-DESIGN.md`
- **Phase 5 Architecture:** `predictions/worker/ARCHITECTURE.md`
- **Quality Tracking:** `docs/05-development/guides/quality-tracking-system.md`

---

*Handoff prepared by: Claude + User collaboration*
*Date: 2025-12-01*
