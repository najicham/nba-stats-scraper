# Session 341 Handoff — Trends V3 Polish and Bug Fixes

**Date:** 2026-02-25
**Focus:** Closed all open items from Session 340, fixed data quality bugs found during frontend review, added production safeguards.

---

## What Was Done

### 1. Detail line framing pass (all 7 types)

Consistent rule across all types: **interesting/new number first, season avg last as context.**

| Type | Detail format | Example |
|---|---|---|
| `scoring_streak` | Streak stat first | "Averaging 30.1 PPG in the streak, 29.0 season avg" |
| `cold_snap` | Drop first | "Down 5.9 pts per game, 12.7 season avg" |
| `breakout` | Jump first | "A 73% jump from his 8.7 season avg" |
| `double_double_machine` | Stat line (no season avg) | "Averaging 24.2 pts, 12.0 reb, 8.6 ast over last 10" |
| `shooting_hot` | Season baseline only | "Season avg is 46% from the field" |
| `shooting_cold` | Season baseline only | "Season avg is 44% from 3" |
| `bounce_back` | Game context first | "Played 32 min, bounces back 50%, 25.2 season avg" |

Shooting details simplified per frontend feedback — headline already has the recent number, detail just provides the baseline. No subtraction required.

### 2. Per-type cap of 5

Each of the 7 trend types is capped at 5 items max before the tonight/other split. Prevents any single detector from dominating (shooting_cold was 15/30 before). With 7 types × 5 = 35 candidates, intensity sort naturally surfaces the best across all types.

### 3. Round-robin type interleaving

After final selection, trends are reordered using round-robin across types. Groups by type, orders type groups by their top intensity, takes one from each type before any type repeats. First 7 positions are always 7 different types.

Replaced the initial greedy "avoid back-to-back" approach which still allowed scoring_streak to dominate positions 1,3,5,7.

### 4. Wider bounce-back window

Query expanded from 15 games / 45 days to 30 games / 120 days. The bounce-back detector now has ~4x the history to find the 3+ bad-game-followed-by-bounce events it needs (MIN_SAMPLE=3). Produced 1 result today (was 0 before). Other detectors unaffected — they use their own `games[:7]` windowing.

### 5. FG% NULL mismatch bug fix

**Root cause:** Older games (pre-January for some players) have `fg_attempts = NULL` while `fg_makes` is populated. SQL's `SUM()` skips NULLs independently per column, so `SUM(fg_makes)` summed all 26 games but `SUM(fg_attempts)` only summed 6 non-NULL games → impossible percentages (109%, 165%, 203%).

**Fix:** Conditional aggregation — only include `fg_makes` in `SUM` when `fg_attempts IS NOT NULL`. Same for 3PT stats.

### 6. Scoring streak threshold scaling

Fixed thresholds (35/30/25/20) now skip any threshold trivially below the player's season average (`threshold < season_ppg - 5`). Eliminates noise like "Scored 20+ in 30 straight" for a 31.5 PPG scorer (SGA/Embiid).

### 7. Post-production validation layer

`_validate_trends()` runs before returning from `build_trends()`. Checks:
- Required fields (type, headline, player.lookup)
- Valid type (7 known) and category (hot/cold/interesting)
- Intensity range 0-10
- Shooting percentages 0-100% (would have caught FG% bug)
- Headline length max 80 chars

Strips bad items with warning logs. Never fails the whole export for one bad trend.

### 8. Build commit in metadata

`tonight.json` metadata now includes `"build_commit"` — the git SHA from the `BUILD_COMMIT` env var when running in Cloud Functions, or `"local"` for manual exports. Allows the frontend to identify exactly which code version generated each file.

### 9. Frontend spec updated

`/home/naji/code/props-web/docs/backend-specs/trends-v3-spec.md` updated to match all detail template changes and the `bounce_back` type definition.

---

## Bugs Found and Fixed

| Bug | Root cause | Fix |
|---|---|---|
| Season FG% showing 109%, 165%, 203% | `fg_attempts` NULL in older games, `SUM()` skips NULLs independently | Conditional aggregation: `SUM(IF(fg_attempts IS NOT NULL, fg_makes, NULL))` |
| Interleaving not diverse enough | Greedy "avoid back-to-back" let same type alternate (A,B,A,B,A) | Round-robin across types |
| "Scored 20+ in 30 straight" for 31 PPG scorer | Fixed thresholds don't scale with player average | Skip threshold if `< season_ppg - 5` |

---

## Commits

| SHA | Message |
|---|---|
| `44fdfc3f` | feat: add Trends V3 feed with 7 trend detectors |
| `0cfc48a2` | feat: per-type caps, type interleaving, wider bounce-back window |
| `34efc4ac` | fix: shooting % NULL mismatch and round-robin type interleaving |
| `9bfe5ffe` | fix: add post-production validation for trend items |
| `b2a6f733` | fix: detail lines lead with change, season avg last |
| `7e6b08c6` | fix: scale scoring streak thresholds, simplify shooting details |
| `866c1c7c` | feat: add build_commit to tonight.json metadata |

---

## Files Changed

| File | Status |
|---|---|
| `data_processors/publishing/trends_v3_builder.py` | **NEW** — trend computation module (Session 340), heavily iterated this session |
| `data_processors/publishing/trends_tonight_exporter.py` | **MODIFIED** — added trends array, build_commit metadata |

---

## What's NOT Done

### No automated trigger for `trends-tonight`

No scheduler or orchestrator currently sends the `trends-tonight` export type. The trends array in `tonight.json` is only populated by manual exports or when explicitly triggered. To automate:
- Add `'trends-tonight'` to the `phase6-hourly-trends` scheduler payload, OR
- Add it to `TONIGHT_EXPORT_TYPES` in the phase5-to-phase6 orchestrator

### Shooting trend dominance (mitigated, not eliminated)

Per-type cap of 5 prevents the worst case (15/30 shooting_cold). Could further tune by raising attempt thresholds or adding minimum point-differential filters.

### Bounce-back still rare

Wider window helps (1 result today vs 0 before), but bounce-back trends will only appear 2-3 times a week. Frontend treats this as a feature — "Worth Watching" section feels more special when it's not always there.

---

## Key Decisions

- **Per-type cap over raised thresholds** — Frontend recommended capping at 5 per type rather than raising shooting thresholds. Cleaner fix, preserves detector sensitivity.
- **Round-robin over greedy interleaving** — Guarantees maximum type diversity in top positions.
- **Shooting detail = baseline only** — "Season avg is 44% from 3" instead of "Down 17 points from his 44% season avg". Headline has the recent number, no math required.
- **1-hour cache TTL unchanged** — File only changes once/day in production. Today's cache staleness was a one-time issue from repeated manual exports during iteration.
