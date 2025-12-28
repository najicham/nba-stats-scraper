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

---

## Frontend Update - December 28, 2025 (Session 201)

**Focus:** Connecting real data for Tonight page and Challenge grading

### Data Status Check (9:39 AM PST / 12:39 PM ET)

| Endpoint | Status | Notes |
|----------|--------|-------|
| `/tonight/all-players.json` | ⚠️ **Stale** | Shows Dec 27 (yesterday) |
| `/tonight/2025-12-28.json` | ❌ **404** | Today's dated file doesn't exist |
| `/tonight/player/lebronjames.json` | ❌ **Very Stale** | Shows `game_date: "2021-12-25"` |
| `/live/latest.json` | ✅ **Working** | Shows Dec 28, 9 games final |
| `/live-grading/latest.json` | ✅ **Working** | Shows Dec 28, empty (no games today) |
| `/live-grading/2025-12-27.json` | ✅ **Working** | Full grading data available |
| `/best-bets/latest.json` | ⚠️ **Empty** | Shows Dec 27, 0 picks |
| `/trends/whos-hot-v2.json` | ⚠️ **Empty** | 0 hot players, 0 cold players |
| `/results/latest.json` | ✅ **Working** | Shows Dec 27 (correct - yesterday's results) |
| `/players/lebronjames.json` | ⚠️ **Partial** | `season_stats` is null |

### Critical Issues for Tonight Page

#### Issue 1: `/tonight/all-players.json` Not Updating

**Current State:**
```json
{
  "game_date": "2025-12-27",
  "generated_at": "2025-12-27T23:16:21.938706+00:00",
  "total_players": 832,
  "total_with_lines": 275
}
```

**Expected:** Should show Dec 28 data after 1:30 PM ET scheduler runs.

**Question:** Is the Dec 28 scheduler expected to run? If there are no games today, should `all-players.json` show an empty games array?

---

#### Issue 2: Player Detail Endpoint Extremely Stale

**Endpoint:** `/tonight/player/{lookup}.json`

**Example:** `/tonight/player/lebronjames.json`
```json
{
  "player_lookup": "lebronjames",
  "player_full_name": "LeBron James",
  "game_date": "2021-12-25",  // <-- 4 YEARS OLD!
  "generated_at": "2025-12-12T15:40:33.429675+00:00",
  ...
}
```

**Impact:** Player modal "Tonight" tab shows ancient data.

**Question:** Is this endpoint still being maintained? Or was it deprecated?

---

#### Issue 3: Trends Endpoint Empty

**Endpoint:** `/trends/whos-hot-v2.json`

**Response:**
```json
{
  "period": null,
  "hot_count": 0,
  "cold_count": 0
}
```

**Question:** Is this endpoint being populated? The Trends page relies on this data.

---

#### Issue 4: Best Bets Empty

**Endpoint:** `/best-bets/latest.json`

**Response:**
```json
{
  "game_date": "2025-12-27",
  "total_picks": 0,
  "picks": []
}
```

**Question:** Are best bets being generated? Previous days may have had games but this shows 0 picks.

---

### Challenge Grading Data ✅

**Good news:** Challenge grading is ready to work with real data.

| Component | Status |
|-----------|--------|
| Player lookup matching | ✅ Same format (lowercase, no spaces) |
| Live grading endpoint | ✅ `/live-grading/latest.json` works |
| Historical grading | ✅ `/live-grading/{date}.json` works |
| Required fields | ✅ `actual`, `game_status`, `status`, `line` all present |
| Adapter layer | ✅ Transforms API → frontend types correctly |

**Test Result (2025-12-27):**
```json
{
  "player_lookup": "jeremiahfears",
  "actual": 18,
  "game_status": "final",
  "status": "correct",
  "period": 4,
  "time_remaining": "Final"
}
```

All required fields are present. Grading engine will work.

---

### Minor Type Mismatch (Non-Blocking)

**Issue:** API returns `home_team`/`away_team` but TypeScript expects `game_id` in `LiveGradingPrediction`.

**API Response:**
```json
{
  "player_lookup": "jeremiahfears",
  "home_team": "NOP",
  "away_team": "PHX"
  // No game_id field
}
```

**Impact:** None - grading engine only matches by `player_lookup`, not `game_id`.

**Recommendation:** Either:
- Add `game_id` to API response, OR
- We update frontend types to expect `home_team`/`away_team` instead

---

### Summary: What Frontend Needs to Work

| Priority | Item | Status |
|----------|------|--------|
| **High** | `/tonight/all-players.json` updated for current date | ⏳ Waiting |
| **High** | `/tonight/player/{lookup}.json` with current data | ❌ Broken |
| **Medium** | `/best-bets/latest.json` with picks | ⏳ Waiting |
| **Medium** | `/trends/whos-hot-v2.json` with data | ❌ Empty |
| **Low** | Player profile `season_stats` populated | ⚠️ Partial |

---

### Questions for Backend

1. **What's the scheduler status?** Are the daily jobs running (phase6-tonight-picks, etc.)?

2. **Are there games today (Dec 28)?** If no games, should `all-players.json` update to show empty?

3. **Is `/tonight/player/{lookup}.json` deprecated?** Data is 4 years old.

4. **What populates `/trends/whos-hot-v2.json`?** Currently returning empty.

5. **Are best bets being generated?** `/best-bets/latest.json` shows 0 picks.

---

### Next Steps (Frontend)

Once data is flowing:
1. Test challenge creation with real tonight data
2. Test challenge grading with live game data
3. Verify player modal shows correct tonight analysis
4. Test trends page with real hot/cold players

---

## Backend Response - December 28, 2025 (Session 180)

**From:** Backend Team
**Date:** 2025-12-28
**Time:** 12:55 PM ET

---

### Response to Session 201 Questions

#### Q1: What's the scheduler status?

**Status:** All schedulers are ENABLED and running normally.

| Scheduler | Schedule | Last Run | Status |
|-----------|----------|----------|--------|
| `same-day-phase3` | 12:30 PM ET | ✅ Ran today | Analytics prep |
| `same-day-phase4` | 1:00 PM ET | ⏳ Running in 5 mins | ML features |
| `same-day-predictions` | 1:30 PM ET | ⏳ 35 mins away | Phase 5 predictions |
| `phase6-tonight-picks` | 1:00 PM ET | ⏳ Running in 5 mins | Tonight API export |
| `phase6-player-profiles` | 6 AM ET Sundays | ✅ Ran today | Player detail files |

**Current Time:** 12:55 PM ET - You checked 30-40 minutes before the daily export runs.

---

#### Q2: Are there games today (Dec 28)?

**YES - 6 games scheduled today.**

Verified via NBA API:
```json
{ "games_scheduled": 6 }
```

The `/tonight/all-players.json` will update after:
1. Phase 4 completes (~1:00 PM ET)
2. Phase 5 predictions complete (~1:30 PM ET)
3. Phase 6 export runs (~1:35-1:45 PM ET)

**Expected availability:** ~1:45 PM ET today.

---

#### Q3: Is `/tonight/player/{lookup}.json` deprecated?

**NOT deprecated, but BROKEN.** This is a real bug.

**Investigation:**
- File `lebronjames.json` was created **Dec 12, 2025** (16 days ago)
- Contains `game_date: "2021-12-25"` (4 years old!)
- The weekly scheduler (`phase6-player-profiles`) ran TODAY at 6 AM ET
- BUT the files weren't updated

**Root Cause:** The scheduler passes `{"players": true, "min_games": 5}` but **no target date**. The exporter may be querying an empty or old dataset.

**Fix Required:** Yes - we need to investigate why the player detail exporter is producing stale data.

**Priority:** High - this affects player modal functionality.

**Workaround:** Use data from `/tonight/all-players.json` instead. Each player object in the `games[].players[]` array has the same core data (prediction, injury, fatigue, etc.).

---

#### Q4: What populates `/trends/whos-hot-v2.json`?

**Working correctly - just no players qualify.**

```json
{
  "generated_at": "2025-12-28T17:00:10",
  "min_games": 5,
  "total_qualifying_players": 0,
  "hot": [],
  "cold": []
}
```

**Why empty:**
- Requires players with 5+ games in last 30 days
- Requires consistent over/under performance vs their line
- Early in season + Christmas break = fewer qualifying players

**Suggestion:** Lower `min_games` threshold or adjust criteria. Will look into this.

---

#### Q5: Are best bets being generated?

**Working correctly - just no picks selected.**

```json
{
  "game_date": "2025-12-27",
  "methodology": "Ranked by composite score: confidence * edge_factor * historical_accuracy",
  "total_picks": 0,
  "picks": []
}
```

**Why 0 picks:**
- The algorithm is conservative
- Requires high confidence + significant edge + good historical accuracy
- Dec 27 may not have had any picks meeting all thresholds

**This is intentional** - showing 0 picks is better than showing bad picks.

---

### Summary: What's Actually Broken vs Working

| Endpoint | Status | Notes |
|----------|--------|-------|
| `/tonight/all-players.json` | ⏳ **Expected** | Will update ~1:45 PM ET today |
| `/tonight/player/{lookup}.json` | ❌ **BROKEN** | 2021 data! Needs investigation |
| `/live-grading/latest.json` | ⏳ **Expected** | Empty until games start tonight |
| `/trends/whos-hot-v2.json` | ✅ **Working** | Empty because no players qualify |
| `/best-bets/latest.json` | ✅ **Working** | Empty because no picks meet thresholds |
| `/live/latest.json` | ✅ **Working** | Confirmed working |
| `/results/latest.json` | ✅ **Working** | Shows Dec 27 correctly |

---

### Action Items (Backend)

| Item | Priority | Status |
|------|----------|--------|
| Fix `/tonight/player/{lookup}.json` stale data | **High** | 🔍 Investigating |
| Consider lowering trends `min_games` threshold | Low | 📋 Backlog |
| Add empty-state file for no-games days | Low | 📋 Backlog |

---

### Check Back After 2 PM ET

The tonight's data will be fully available after the schedulers run:
- **1:00 PM ET:** Phase 4 + Phase 6 tonight export starts
- **1:30 PM ET:** Phase 5 predictions complete
- **~1:45 PM ET:** All data should be fresh

Check `/tonight/all-players.json` after 2 PM ET - it should show Dec 28 with all 6 games.

---

## Update - December 28, 2025 (2:00 PM ET)

**Status:** ✅ ALL DATA NOW FRESH

After re-investigation at 1:55 PM ET, all endpoints are now working:

### Verified Working

| Endpoint | Status | Current Data |
|----------|--------|--------------|
| `/tonight/all-players.json` | ✅ Fresh | `game_date: "2025-12-28"`, `total_players: 211`, `generated_at: 2025-12-28T19:30:29` |
| `/tonight/player/lebronjames.json` | ✅ Fresh | `game_date: "2025-12-28"`, `generated_at: 2025-12-28T18:08:59` |
| `/live-grading/latest.json` | ✅ Ready | Waiting for games to start |

### Root Cause: Timing

The frontend team checked at **12:39 PM ET**. The scheduler runs at **1:00 PM ET**.

| Time | What Happened |
|------|---------------|
| 12:39 PM ET | Frontend checked → saw Dec 27 data (stale) |
| 1:00 PM ET | Scheduler triggered Phase 6 export |
| 1:08 PM ET | Player files updated (including lebronjames.json) |
| 1:30 PM ET | Predictions complete, all-players.json refreshed |

**The "2021-12-25" date in lebronjames.json was from Dec 12** when the file was first created. It was overwritten today at 1:08 PM ET with current data.

### Current LeBron Data

```json
{
  "player_lookup": "lebronjames",
  "game_date": "2025-12-28",
  "generated_at": "2025-12-28T18:08:59.525308+00:00",
  "game_context": {
    "game_id": "0022500446",
    "opponent": "SAC",
    "home_game": true,
    "team_abbr": "LAL",
    "days_rest": 3,
    "is_back_to_back": false
  }
}
```

### No Backend Issues Found

All systems working as designed:
- ✅ Schedulers running on time
- ✅ Tonight export updates daily at 1 PM ET
- ✅ Player detail files update for players with games that day
- ✅ Trends/best-bets empty because no players/picks meet thresholds (intentional)

### Recommendation for Frontend

For real-time data availability checks:
```javascript
// Check if tonight data is for today
const tonight = await fetch('/tonight/all-players.json').then(r => r.json());
const isStale = tonight.game_date !== new Date().toISOString().split('T')[0];

if (isStale) {
  // Show "Data updating..." message
  // Or use player index for selection
}
```

---

## Summary: No Backend Changes Needed

All originally reported issues are either:
1. ✅ Already fixed (period/time_remaining, days_rest)
2. ✅ Working correctly (trends, best-bets - just empty criteria)
3. ✅ Timing issue resolved (tonight data - check after 2 PM ET)

**Frontend integration can proceed with current API.**

