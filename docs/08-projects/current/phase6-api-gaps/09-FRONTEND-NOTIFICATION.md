# Frontend Team - Phase 6 API Updates Deployed 🎉

**Date:** February 12, 2026
**Status:** ✅ Deployed to production
**Your Review:** `/home/naji/code/props-web/docs/08-projects/current/backend-integration/API_ENDPOINT_REVIEW_2026-02-11.md`

---

## What's Available Now

### 🆕 New Fields (Tonight Endpoint)

All 192 lined players now have:

| Field | Type | Example | Usage |
|-------|------|---------|-------|
| `days_rest` | int/null | `2` | ContextBadge component |
| `minutes_avg` | float | `32.5` | Player card stats (alias for season_mpg) |
| `recent_form` | string | `"Hot"` / `"Cold"` / `"Neutral"` | Form indicator badge |
| `last_10_lines` | array | `[20.5, 18.5, null, ...]` | Accurate O/U sparkline |
| `prediction.factors` | array | `["Strong model edge...", ...]` | "Why this pick?" reasoning |

**In Picks Endpoint:**
- `player_lookup` - Link picks to player detail pages

### 🆕 New Endpoints

| Endpoint | Purpose | Cache |
|----------|---------|-------|
| `/tonight/{YYYY-MM-DD}.json` | Historical date browsing | 24h |
| `/calendar/game-counts.json` | Calendar widget (30 days + 7 forward) | 30min |

### ✅ Fixes Applied

**P0 (Data Quality):**
1. ✅ **31 players with all-dash O/U** - Fixed with `last_10_lines` array
2. ✅ **Bogus odds (199900)** - Filtered with validation
3. ✅ **game_time whitespace** - Removed leading space

**P1 (Missing Fields):**
4. ✅ **prediction.factors** - Your #1 request! Max 4 directional factors
5. ✅ **days_rest** - Now populated
6. ✅ **recent_form** - Calculated Hot/Cold/Neutral
7. ✅ **minutes_avg** - Alias added
8. ✅ **player_lookup** - Added to picks

**P2 (New Endpoints):**
9. ✅ **Date-specific tonight files** - Historical browsing enabled
10. ✅ **Calendar game counts** - Widget data available

---

## Breaking Changes

**None!** All changes are additive/backward-compatible.

**One change to note:**
- `confidence` still 0-100 scale (not 0.0-1.0) - your adapter handles this already

---

## Field Details

### `prediction.factors` (New!)

**Format:** Array of 1-4 strings, directionally supporting the recommendation

**Examples:**
```json
{
  "prediction": {
    "predicted": 23.5,
    "confidence": 72,
    "recommendation": "OVER",
    "factors": [
      "Solid model edge (3.5 points)",
      "Weak opposing defense favors scoring",
      "Hot over streak: 7-3 last 10",
      "Well-rested, favors performance"
    ]
  }
}
```

**Priority Order:** Edge > Matchup > Trend > Fatigue > Form

**Safety:** No contradictory factors possible (e.g., OVER will never show "Elite opposing defense")

**Edge Cases:**
- Empty array `[]` if no factors (low conviction picks)
- Always includes edge if >= 3 points
- Max 4 factors (UI-friendly)

### `last_10_lines` (New!)

**Format:** Array matching `last_10_points` length (same 10 games)

**Example:**
```json
{
  "last_10_points": [25, 18, null, 30, 19],
  "last_10_lines":  [20.5, 18.5, null, 21.5, 17.5],
  "last_10_results": ["O", "U", "DNP", "O", "O"]
}
```

**Usage:**
```typescript
const computeAccurateOU = (points: number[], lines: number[]) => {
  return points.map((pts, i) => {
    if (pts === null || lines[i] === null) return '-';
    return pts >= lines[i] ? 'O' : 'U';
  });
};
```

**Benefit:** Accurate O/U calculation (not using today's line for historical games)

### `recent_form` (New!)

**Format:** String - `"Hot"` / `"Cold"` / `"Neutral"` / `null`

**Logic:**
- Hot: Last 5 PPG >= Season PPG + 3.0
- Cold: Last 5 PPG <= Season PPG - 3.0
- Neutral: Difference < 3.0
- null: Insufficient data

### Calendar Endpoint (New!)

**URL:** `https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json`

**Format:**
```json
{
  "2026-02-11": 14,
  "2026-02-10": 4,
  "2026-02-09": 12,
  "2026-02-08": 0,
  ...
}
```

**Coverage:** 30 days back + 7 days forward (~37 dates)

---

## Workarounds You Can Remove

**From `api-adapters.ts`:**

1. ✅ **Lines 135-150** - O/U computation workaround (now have accurate `last_10_lines`)
2. ✅ **Line 169** - `days_rest: null` default (now populated)
3. ✅ **Line 192** - `game_time` whitespace trim (now trimmed server-side)

**Keep these** (still needed):
- Line 153: `fatigue_level` "rested" → "fresh" mapping (we send "rested")
- Line 156: `injury_status` null → "available" mapping (we send null)
- Line 165: `confidence / 100` division (we send 0-100)

---

## Testing

### Quick Smoke Test

```bash
# 1. Check new fields exist
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[0].players[0] | {days_rest, minutes_avg, recent_form, factors: .prediction.factors}'

# 2. Verify arrays match length
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[0].players[0] | {
    points_len: (.last_10_points | length),
    lines_len: (.last_10_lines | length)
  }'

# 3. Calendar widget
curl https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json | jq 'keys | length'
# Should be ~37 dates
```

### Integration Checklist

**Tonight Page:**
- [ ] `days_rest` badge displays
- [ ] `recent_form` badge displays (Hot/Cold/Neutral)
- [ ] O/U sparkline uses `last_10_lines` for accurate calculations
- [ ] "Why this pick?" section shows `prediction.factors`
- [ ] No contradictory factors (OVER picks never show "Elite defense")

**Picks Page:**
- [ ] `player_lookup` links to player detail

**Calendar:**
- [ ] Date picker shows game counts
- [ ] Clicking date navigates to `/tonight/{date}.json`
- [ ] Historical dates load correctly

---

## Expected Behavior

### `prediction.factors` Examples

**High Edge OVER (should see edge + supporting factors):**
```json
{
  "recommendation": "OVER",
  "factors": [
    "Strong model conviction (5.2 point edge)",  // Always first if edge >= 5
    "Weak opposing defense favors scoring",       // Only if def rating > 115
    "Hot over streak: 8-2 last 10"               // Only if 7+ overs
  ]
}
```

**UNDER with Fatigue (should see edge + fatigue):**
```json
{
  "recommendation": "UNDER",
  "factors": [
    "Solid model edge (3.5 points)",
    "Back-to-back fatigue risk"  // Only appears for UNDER recs
  ]
}
```

**Low Conviction (may have empty factors):**
```json
{
  "recommendation": "OVER",
  "edge": 2.1,
  "factors": []  // Edge < 3, no other supporting factors
}
```

### Array Alignment

**All three arrays MUST match in length:**
```json
{
  "last_10_points": [25, 18, null, 30, 19, 24, 17, 23, 20, 22],  // 10 elements
  "last_10_lines":  [20.5, 18.5, null, 21.5, null, 20.5, null, 19.5, 18.5, 19.5],  // 10 elements
  "last_10_results": ["O", "U", "DNP", "O", "-", "O", "-", "O", "O", "O"]  // 10 elements
}
```

**Nulls mean:**
- `points: null` - DNP (did not play)
- `lines: null` - No line that game (played but no prop)
- Both null - DNP
- `results: "-"` - No line available (can't compute O/U)

---

## Known Issues

**None expected!** All changes were Opus-reviewed and validated.

If you encounter issues:
1. Check browser console for API errors
2. Verify endpoint URLs (new calendar endpoint)
3. Test with multiple players (some may have empty factors if low edge)

**Contact:** Slack or create issue with:
- Endpoint URL
- Player lookup
- Expected vs actual behavior

---

## Timeline

**Deployed:** February 12, 2026 ~12:30 AM UTC
**Build:** 785bd5fa (Cloud Build)
**Commit:** 6033075b

**Ready for integration immediately!**

---

## Questions?

**Common Questions:**

**Q: Why do some players have empty `factors` array?**
A: Low edge (<3 points) and no other supporting factors. This is correct - we only show factors that support the recommendation.

**Q: Why do some players have nulls in `last_10_lines`?**
A: No prop line was available for that game. This is honest data - we don't fabricate lines.

**Q: Will all OVER picks show "Weak opposing defense"?**
A: No, only if opponent def rating > 115 (weak defense). Factors are selective, not generic.

**Q: What if a player has OVER recommendation but 7+ unders in last 10?**
A: The trend factor won't appear (contradicts OVER). Only edge and other supporting factors will show.

**Q: Are the calendar game counts real-time?**
A: Updated every 30 minutes. Schedule changes may take up to 30 min to reflect.

---

**Happy integrating!** 🚀

Let us know if you see any issues or have questions.
