# Injury Data Integration

**Date:** 2026-01-10
**Status:** Implemented
**Component:** `upcoming_player_game_context_processor.py`

---

## Background

The `_extract_injuries()` method was previously a TODO stub, leaving `player_status` and `injury_report` fields as NULL in the player context table. This made it impossible to know a player's injury status when generating predictions.

---

## Implementation

### Method: `_extract_injuries()`

Queries `nba_raw.nbac_injury_report` for the latest injury status for each player on the target game date.

```python
def _extract_injuries(self) -> None:
    # Gets latest injury report for each player
    # Stores in self.injuries as {player_lookup: {'status': ..., 'report': ...}}
```

### Query Logic

Uses parameterized queries for security and filters by both `game_date` and `game_id` for precision:

```sql
WITH latest_report AS (
    SELECT
        player_lookup,
        injury_status,
        reason,
        reason_category,
        ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY report_date DESC, processed_at DESC
        ) as rn
    FROM nbac_injury_report
    WHERE player_lookup IN UNNEST(@player_lookups)
      AND game_date = @target_date
      AND game_id IN UNNEST(@game_ids)
)
SELECT player_lookup, injury_status, reason, reason_category
FROM latest_report
WHERE rn = 1
```

### Injury Statuses

| Status | Meaning | Play Probability |
|--------|---------|-----------------|
| `out` | Definitely not playing | 0% |
| `doubtful` | Unlikely to play | ~25% |
| `questionable` | Uncertain | ~50% |
| `probable` | Likely to play | ~75% |
| `available` | Was on report but cleared | 100% |

---

## Data Flow

1. `_extract_injuries()` called during data extraction (Step 6)
2. Queries BigQuery for injury report data
3. Stores results in `self.injuries` dict
4. Transform uses `self.injuries.get(player_lookup, {}).get('status')` to populate fields

---

## Fields Populated

| Field | Source | Example |
|-------|--------|---------|
| `player_status` | `injury_status` | "out", "questionable", "probable" |
| `injury_report` | `reason` or `reason_category` | "Left Ankle Sprain", "injury" |

---

## Testing

```python
# Test results for Jan 9, 2026:
jamalmurray: status=out, report=unknown
kristapsporzingis: status=out, report=unknown
zaccharierisacher: status=out, report=Injury/Illness - Left Knee; Inflammation
lebronJames: (not on injury report - None/None)
```

---

## Source Tracking

Injury extraction populates `source_tracking['injuries']` for observability:

```python
{
    'last_updated': datetime,     # Latest processed_at from injury report
    'rows_found': int,            # Number of injury records found
    'players_with_status': int,   # Players with injury status populated
    'status_breakdown': dict,     # Count by status: {'out': 3, 'questionable': 2}
    'error': str                  # If extraction failed
}
```

---

## Integration with Coverage Check

With injury data now populated in player context:

1. **Pre-game predictions** can skip `out`/`doubtful` players
2. **Coverage check** can identify players who were marked as out
3. **Risk flagging** can warn about `questionable` players

---

## Files Changed

| File | Change |
|------|--------|
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | Implemented `_extract_injuries()` method |

---

**Author:** Claude Code (Opus 4.5)
**Session:** 7
