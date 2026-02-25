# Session 340 Handoff — Trends V3 Feed Implementation

**Date:** 2026-02-24
**Focus:** Built and deployed the V3 trends array for the frontend trends page redesign.

---

## What Was Done

### New: `data_processors/publishing/trends_v3_builder.py`

Standalone module that computes player performance trends from BigQuery game data. One SQL query fetches last 15 games + season averages + position for all qualifying players (~370), then 7 Python-side detectors produce trend items.

**7 Tier 1 detectors:**

| Detector | Category | Trigger |
|---|---|---|
| `scoring_streak` | hot | 4+ consecutive games above 20/25/30/35 threshold |
| `cold_snap` | cold | Below season avg in 5+ of last 7, 15%+ drop |
| `breakout` | hot | Role player (< 20 PPG) last-7 avg 40%+ above season avg |
| `double_double_machine` | hot | 5+ DDs in last 7 or 7+ in last 10 |
| `shooting_hot` | hot | 3PT% up 12+ pts (28+ attempts) or FG% up 8+ pts |
| `shooting_cold` | cold | 3PT% down 12+ pts or FG% down 8+ pts |
| `bounce_back` | interesting | Last game 10+ pts below avg, 20+ min played, has history |

**Pipeline:** Deduplicates (one per player, highest intensity wins), applies 70/30 tonight/other split, caps at 30, sorted by intensity descending.

### Modified: `data_processors/publishing/trends_tonight_exporter.py`

- Imports and calls `build_trends()` from the new module
- Adds `trends` array to `tonight.json` output alongside existing `players`, `matchups`, `insights`
- Version bumped from `'2'` to `'3'`
- Added `_extract_tonight_teams()` and `_build_trends_section()` helper methods

### Output format (V3 spec)

```json
{
  "id": "scoring-streak-kawhileonard",
  "type": "scoring_streak",
  "category": "hot",
  "player": { "lookup": "kawhileonard", "name": "Kawhi Leonard", "team": "LAC", "position": "F" },
  "headline": "Scored 20+ in 15 straight",
  "detail": "28.1 season avg, averaging 27.6 in the streak",
  "stats": { "primary_value": 15, "primary_label": "straight games", "secondary_value": 27.6, "secondary_label": "PPG in streak" },
  "intensity": 9.0
}
```

### Formatting rules enforced

1. No player names in headlines (frontend shows name separately)
2. No em dashes — commas only
3. No redundancy between headline and detail (each adds new info)
4. Stat lines spelled out: "24.2 pts, 12.0 reb, 8.6 ast"
5. PPG unit included in scoring headlines
6. Details under ~60 chars for mobile grid cards

### Data pushed to GCS

Live at `gs://nba-props-platform-api/v1/trends/tonight.json` — pushed manually. **Code is NOT deployed yet** (not committed/pushed to main).

---

## What's NOT Done

### Code not committed or deployed
The new `trends_v3_builder.py` and modified `trends_tonight_exporter.py` are local changes only. Need to:
1. Commit and push to main (auto-deploys phase6-export Cloud Function)
2. Verify the daily export includes the trends array

### Detail line framing needs a per-type pass
The current detail lines follow one pattern (lead with season avg), but each trend type reads better with different framing. The detail should complement the headline, not repeat it, and the most impactful number should come first.

**Proposed rewrites per type:**

| Type | Current detail | Proposed detail |
|---|---|---|
| `scoring_streak` | "28.1 season avg, averaging 27.6 in the streak" | "Averaging 27.6 PPG in the streak, 28.1 season avg" (lead with the streak stat, season avg as context at the end) |
| `shooting_cold` | "Season avg 47%, down 20 percentage points" | "Down 20 points from his 47% season avg" (lead with the drop — that's the story) |
| `shooting_hot` | "Season avg 36%, up 15 percentage points" | "Up 15 points from his 36% season avg" (same — lead with the jump) |
| `cold_snap` | "24.8 season avg, down 8.5 pts per game" | Fine as-is (season avg leads because headline already has the low number) |
| `breakout` | "Up from his 8.7 season avg, a 73% jump" | Fine as-is |
| `double_double_machine` | "Averaging 24.2 pts, 12.0 reb, 8.6 ast..." | Fine as-is |
| `bounce_back` | "24.3 season avg, played 34 min, bounces back 78%" | Fine as-is |

**File to edit:** `data_processors/publishing/trends_v3_builder.py` — update the `detail=` strings in `_detect_scoring_streaks`, `_detect_shooting_hot`, and `_detect_shooting_cold`.

Also update the spec at `/home/naji/code/props-web/docs/backend-specs/trends-v3-spec.md` detail templates table to match, then re-export to GCS.

### Bounce-back detector: limited by 15-game window
The bounce-back detector computes historical bounce-back rate from the same 15-game window used by all detectors. This is a small sample for counting bad-game-followed-by-bounce-back events. It may produce 0 results on many days. Consider either:
- Expanding the query window for bounce-back specifically
- Querying bounce-back history separately (like the existing `BounceBackExporter` does with full season + multi-season data)

### Frontend spec location
The spec lives at `/home/naji/code/props-web/docs/backend-specs/trends-v3-spec.md` and was updated throughout the session with formatting rules, headline templates, and the bounce_back type definition.

### Shooting trends still dominate
15 of 30 trends are shooting_cold on today's data. Thresholds are tighter than v1 (28+ 3PA, 20+ MPG, 12+ point diff) but shooting variance naturally produces more candidates. Could consider:
- Capping shooting trends to max 8-10 per export
- Further raising attempt/minute thresholds

---

## Files Changed

| File | Status |
|---|---|
| `data_processors/publishing/trends_v3_builder.py` | **NEW** — trend computation module |
| `data_processors/publishing/trends_tonight_exporter.py` | **MODIFIED** — imports builder, adds trends to output |

---

## Key Decisions

- **Separate module** for trend computation (not inline in exporter) — keeps the 900-line exporter manageable
- **Single SQL query** for all detectors — one round-trip, ~370 players, 15 games each
- **Python-side detection** — more flexible than SQL for streak counting, conditional logic
- **70/30 tonight/other split** — prioritize players playing tonight but include notable streaks from others
- **One trend per player** — dedup keeps only the highest-intensity trend per player
- **Intensity capped at 8.0-8.5 for shooting** — prevents shooting trends from dominating over scoring streaks and DDs
