# Frontend Integration Feedback

**From:** Frontend Team
**Date:** 2025-12-27
**Re:** Review of `FRONTEND_API_REFERENCE.md`
**Status:** Awaiting Backend Review

---

## Summary

The API reference is comprehensive and well-documented. The frontend has already built an **adapter layer** (`src/lib/api-adapters.ts`) that handles most field naming differences between backend output and frontend types.

This document outlines:
1. Issues we can fix on the frontend (no backend changes needed)
2. Issues that require backend changes
3. Clarifying questions

---

## Issues We'll Fix on Frontend (No Backend Changes Needed)

### 1. `fatigue_level: "rested"` vs `"fresh"`

| Backend Returns | Frontend Expects |
|-----------------|------------------|
| `"rested"` | `"fresh"` |
| `"normal"` | `"normal"` |
| `"tired"` | `"tired"` |

**Our Fix:** We'll add a mapping in our adapter layer:
```typescript
fatigue_level: raw.fatigue_level === "rested" ? "fresh" : raw.fatigue_level
```

**Rationale:** "Rested" is actually more descriptive. We'll adapt to your terminology and map it for our existing UI components.

---

### 2. `injury_status: null` vs `"available"`

| Backend Returns | Frontend Expects |
|-----------------|------------------|
| `null` | `"available"` |
| `"questionable"` | `"questionable"` |
| etc. | etc. |

**Our Fix:** We'll map `null → "available"` in our adapter:
```typescript
injury_status: raw.injury_status ?? "available"
```

**Rationale:** Using `null` for "no injury" is semantically clean. We'll normalize it on our end.

---

### 3. `games_scheduled` Count

Frontend expected this at the top level of `/live-grading/`, but we can calculate it from:
```
games_scheduled = total_games - games_in_progress - games_final
```

**Our Fix:** We'll derive this value. No backend change needed.

---

## Issues That Need Backend Input

### 4. Missing `period` and `time_remaining` in Live Grading Predictions

**Current State:**
- `/live/latest.json` has `period` and `time_remaining` per game
- `/live-grading/latest.json` does NOT have these fields per prediction

**Frontend Need:**
We want to show "Q3 8:24" next to live scores on player cards. Currently we only know a game is `"in_progress"` but not WHERE in the game.

**Options:**

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A. Backend adds fields** | Add `period` and `time_remaining` to each prediction in `/live-grading/` | Single API call, simple frontend | Minor data duplication |
| **B. Frontend merges endpoints** | Frontend calls both `/live/` and `/live-grading/`, merges by `game_id` | Clean separation of concerns | 2x API calls every 30s |
| **C. Add game-level info** | Add a `games` array to `/live-grading/` with game state | Efficient, no per-prediction duplication | Schema change |

**Our Recommendation:** Option A is simplest. The duplication is minimal (2 small fields per prediction) and avoids doubling our polling load.

**Question:** Which option works best for your architecture?

---

### 5. Missing `days_rest` Field

**Current State:** Not provided in `/tonight/all-players.json`

**Frontend Need:** We have a `ContextBadge` component that shows:
- "B2B" (back-to-back)
- "2 Days Rest"
- "3+ Days Rest"

This provides valuable context for users evaluating predictions.

**Request:** Add `days_rest: number` to player objects:
```json
{
  "player_lookup": "lebronjames",
  "name": "LeBron James",
  "days_rest": 2,
  ...
}
```

**Rationale:** You likely already have this data since `fatigue_level` is derived from rest days.

**Priority:** Medium - UI works without it, but it's valuable context.

---

### 6. `line_source` Field Documentation

The example shows:
```json
{
  "line_source": "ESTIMATED_AVG"
}
```

**Questions:**
1. What are all possible values? (e.g., `"SPORTSBOOK"`, `"ESTIMATED_AVG"`, others?)
2. Should we display this to users? (e.g., show "Est." badge when line is estimated)

**Recommendation:** Document the possible values. We can show users when a line is estimated vs real sportsbook data.

---

## Clarifying Questions

### Q1: Data Availability Timing

The doc says `/tonight/all-players.json` updates at ~6 PM ET.

**Question:** When is this file FIRST populated each day?

**Context:** Users may want to create challenges earlier in the day. For challenge creation, we need:
- Tonight's players list
- At minimum, player names and teams
- Lines can come later

**Ideal scenario:**
- Preliminary data (players, teams, game times) available by noon ET
- Lines added when available from sportsbooks (~6 PM ET)

**Current workaround:** We can use the player index for selection if tonight's data isn't ready, but that's a worse UX.

---

### Q2: Empty State Handling

When there are no games on a given day, what does `/tonight/all-players.json` return?

**Expected:**
```json
{
  "game_date": "2025-12-30",
  "generated_at": "...",
  "total_players": 0,
  "total_with_lines": 0,
  "games": []
}
```

**Or does the file not exist?** (Returns 404)

We need to handle both cases in the UI.

---

### Q3: Historical Live Grading

The doc shows:
```
GET /live-grading/{date}.json
```

**Question:** How long are historical files retained?

**Use case:** If a user loads the Results page for a past date, we might want to show the final grading for that day.

---

## Nice-to-Have (Low Priority)

### 7. `last_10_points` Array

**Current:** `last_10_results: ["O", "U", "-", ...]`

**Request:** Add actual point totals:
```json
{
  "last_10_points": [28, 15, null, 32, 22, 19, 25, 31, 27, 20]
}
```

**Priority:** Low - O/U indicators are sufficient for core use case. This would enable richer visualizations (sparklines, etc.) in the future.

---

## Summary of Requested Changes

| Item | Priority | Type |
|------|----------|------|
| Add `period`/`time_remaining` to live-grading predictions | **High** | Schema addition |
| Add `days_rest` to tonight players | **Medium** | Schema addition |
| Document `line_source` values | **Medium** | Documentation |
| Clarify data availability timing | **Medium** | Documentation |
| Document empty state behavior | **Low** | Documentation |
| Add `last_10_points` array | **Low** | Schema addition (future) |

---

## Our Adapter Layer

For reference, the frontend has an adapter layer at `props-web/src/lib/api-adapters.ts` that handles:

- `name` → `player_full_name`
- `team` → `team_abbr`
- `props[0].line` → `current_points_line`
- `prediction.predicted` → `predicted_points`
- `prediction.confidence` → `confidence_score`
- `last_10_results: "-"` → `last_10_results: "DNP"`
- (Will add) `fatigue_level: "rested"` → `"fresh"`
- (Will add) `injury_status: null` → `"available"`

This means the backend doesn't need to change field names - we transform on our end.

---

## Contact

Questions? Ping the frontend chat or leave comments below.

---

## Backend Response Section

**From:** Backend Team
**Date:** 2025-12-28

---

### Response to Q1 (Data Timing):

**Scheduler Configuration:**
- `same-day-predictions`: **1:30 PM ET** - Predictions generated
- `phase6-tonight-picks`: **1:00 PM ET** - Tonight's API exported

**Current Reality:**
The `/tonight/all-players.json` is generated at ~1 PM ET, but requires predictions to be ready. The full pipeline is:
1. Phase 3 analytics runs at 12:30 PM ET
2. Phase 4 ML features at 1:00 PM ET
3. Phase 5 predictions at 1:30 PM ET
4. Phase 6 export triggered after predictions complete

**Recommendation for Earlier Data:**
We can add a **preliminary endpoint** that's available earlier:
- `/tonight/players-preview.json` - Available by 10 AM ET
- Contains: player names, teams, game times (no predictions/lines)
- You could use this for challenge creation, then hydrate with full data later

**Want us to implement this?** Let us know.

---

### Response to Q2 (Empty States):

**Confirmed behavior:** On days with no games, the file **does not exist** (returns 404).

**Example:** Dec 24, 2025 had no NBA games → no `/tonight/2025-12-24.json` file.

**Frontend Handling:**
```javascript
try {
  const data = await fetch(url).then(r => {
    if (r.status === 404) return { games: [], total_players: 0 };
    return r.json();
  });
} catch (e) {
  // Handle as no-games day
}
```

**Alternative:** We can create empty-state files if you prefer a consistent 200 response. Let us know.

---

### Response to Q3 (Historical Retention):

**Current State:** Files are retained indefinitely (no cleanup policy yet).

**Available History:**
- `/live-grading/`: 4 files (recent only, just deployed)
- `/results/`: Goes back to early December
- `/tonight/`: Goes back to late November

**Note:** Live grading was just fixed today (Dec 27). Historical live-grading files before today may have issues.

---

### Decision on Period/Time in Live Grading:

**Decision: Option A - Add fields to each prediction** ✅

We'll add `period` and `time_remaining` to each prediction object in `/live-grading/`:

```json
{
  "player_lookup": "lebronjames",
  "game_status": "in_progress",
  "period": 3,
  "time_remaining": "Q3 8:24",
  "predicted": 27.5,
  "actual": 18,
  ...
}
```

**Implementation:** Will be deployed in next update.

---

### Decision on days_rest:

**Decision: Yes, we'll add it** ✅

The data is already available in our analytics layer (`upcoming_player_game_context.days_rest`).

We'll add to `/tonight/all-players.json`:
```json
{
  "player_lookup": "lebronjames",
  "days_rest": 2,
  "fatigue_level": "normal",
  ...
}
```

**Values:**
- `0` = Back-to-back (B2B)
- `1` = 1 day rest
- `2` = 2 days rest
- `3+` = Well rested

**Implementation:** Will be deployed in next update.

---

### line_source Values:

**All possible values:**

| Value | Description | Display Suggestion |
|-------|-------------|-------------------|
| `ACTUAL_PROP` | Real sportsbook line from Odds API or BettingPros | Show as-is |
| `ESTIMATED_AVG` | Estimated from player's season average | Show "Est." badge |

**Current distribution:**
- `ESTIMATED_AVG`: 9,000 predictions (99.9%)
- `ACTUAL_PROP`: 5 predictions (0.1%)

**Note:** Most predictions use estimated lines because:
1. Prop lines aren't always available until close to game time
2. Sportsbooks don't publish lines for all players

**Recommendation:** Yes, show an "Est." indicator when `line_source === "ESTIMATED_AVG"` so users know it's not a real Vegas line.

---

### Nice-to-Have Response (last_10_points):

**Status:** Logged for future consideration.

The data is available in our `player_game_summary` table. We can add it when priorities allow:
```json
{
  "last_10_points": [28, 15, null, 32, 22, 19, 25, 31, 27, 20]
}
```

Where `null` = DNP (Did Not Play).

---

## Action Items (Backend)

| Item | Priority | Status |
|------|----------|--------|
| Add `period`/`time_remaining` to live-grading | High | ✅ **Deployed** (2025-12-28) |
| Add `days_rest` to tonight | Medium | ✅ **Deployed** (2025-12-28) |
| Document `line_source` values | Medium | ✅ Done (above) |
| Consider preliminary players endpoint | Low | 📋 Backlog |
| Add `last_10_points` array | Low | 📋 Backlog |

---

## Deployment Verification

### Live Grading - `period` and `time_remaining` ✅

**Verified in production:**
```json
{
  "player_lookup": "jeremiahfears",
  "game_status": "final",
  "period": 4,
  "time_remaining": "Final",
  "predicted": 12.0,
  "actual": 18,
  ...
}
```

During live games, you'll see:
```json
{
  "period": 3,
  "time_remaining": "Q3 8:24"
}
```

### Tonight - `days_rest` ✅

**Deployed and ready.** Will appear in next tonight's export (Dec 28 ~1:30 PM ET):
```json
{
  "player_lookup": "lebronjames",
  "days_rest": 2,
  "fatigue_level": "normal",
  ...
}
```

**Values:**
- `0` = Back-to-back
- `1` = 1 day rest
- `2` = 2 days rest
- `3+` = Well rested
- `null` = Data not available

