# Session 128: Phase 6 Polish - Fatigue, Edge Cases, vs_line_pct

**Date:** 2025-12-12
**Status:** Complete
**Previous Session:** Session 127 (Tonight exporters schema fixes)

---

## Summary

Added polish features to Phase 6 exporters:
1. Fatigue fields to BestBetsExporter
2. `limited_data` edge case flag
3. `vs_line_pct` to TonightPlayerExporter splits

---

## Changes Made

### 1. BestBetsExporter - Fatigue Fields

**File:** `data_processors/publishing/best_bets_exporter.py`

Added:
- `fatigue_score` - numeric fatigue score (0-100)
- `fatigue_level` - categorical: 'fresh' (95+), 'normal' (75-94), 'tired' (<75)
- Fatigue in rationale: "Well-rested (fatigue: 95)" or "Elevated fatigue (fatigue: 60)"

```json
{
  "rank": 1,
  "player_full_name": "Royce O'Neale",
  "fatigue_score": 95.0,
  "fatigue_level": "fresh",
  "rationale": ["High confidence (91%)", "Well-rested (fatigue: 95)"]
}
```

### 2. Edge Case Flags - `limited_data`

**Files:**
- `data_processors/publishing/tonight_all_players_exporter.py`
- `data_processors/publishing/tonight_player_exporter.py`

Added:
- `games_played` - number of games this season
- `limited_data: true` - when `games_played < 10`

This helps the frontend show warnings for players with insufficient sample size.

### 3. TonightPlayerExporter - `vs_line_pct` in Splits

**File:** `data_processors/publishing/tonight_player_exporter.py`

Added `vs_line_pct` to:
- Home/Away splits
- B2B (back-to-back) splits
- Rested splits
- vs Opponent splits

Example tonight's factor with vs_line_pct:
```json
{
  "factor": "location",
  "direction": "neutral",
  "vs_line_pct": 0.615,
  "description": "Averages 28.1 on the home (13 games), 62% OVER"
}
```

---

## Test Results

### BestBetsExporter
```
1. Royce O'Neale (UNDER)
   Fatigue: fresh (95.0)
   Rationale: ['High confidence (91%)', 'Well-rested (fatigue: 95)']

2. Romeo Langford (UNDER)
   Fatigue: fresh (100.0)
   Rationale: ['High confidence (91%)', 'Well-rested (fatigue: 100)']
```

### TonightAllPlayersExporter
```
Player: Clint Capela
  games_played: 30
  limited_data: False
```

### TonightPlayerExporter
```
Player: LeBron James
limited_data: False
Tonight's factors:
  - location: Averages 28.1 on the home (13 games)
```

---

## Files Modified

| File | Changes |
|------|---------|
| `data_processors/publishing/best_bets_exporter.py` | Added fatigue query, output fields, rationale |
| `data_processors/publishing/tonight_all_players_exporter.py` | Added `games_played`, `limited_data` |
| `data_processors/publishing/tonight_player_exporter.py` | Added `limited_data`, `vs_line_pct` to splits/factors |
| `docs/08-projects/current/website-ui/TODO.md` | Marked items complete |

---

## Phase 6 Backend Status

### Complete ✅
- TonightAllPlayersExporter
- TonightPlayerExporter
- PlayerProfileExporter (enhanced)
- BestBetsExporter (with fatigue)
- CLI integration
- Edge case flags (`limited_data`)
- `vs_line_pct` in splits

### Remaining (Low Priority)
- [ ] StreaksExporter - for players on OVER/UNDER streaks
- [ ] Defense tier ranking - precompute daily team defense tier

---

## What's Next

Phase 6 backend is **production-ready**. Next steps:
1. **Frontend development** - Create `nba-props-website` repo
2. **Daily scheduler** - Ensure tonight exports run daily
3. **Monitoring** - Alert on export failures

---

**End of Handoff**
