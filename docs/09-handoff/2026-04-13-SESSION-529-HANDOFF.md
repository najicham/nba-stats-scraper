# Session 529 Handoff — MLB Pitcher UI (Phase 2 Complete)

**Date:** 2026-04-13
**Focus:** Pitch arsenal panel — Statcast pipeline fix, BQ view, exporter update, frontend component, test fixes
**Commits:**
  - `nba-stats-scraper`: `8395f1d5` → `836062b8` (3 commits)
  - `props-platform-web`: `d6491f4` → `a1eaf8f` (2 commits)

---

## TL;DR

Phase 2 of the pitcher UI is live. Every pitcher profile on playerprops.io now shows a **Pitch Arsenal** panel — pitch type breakdown (FF 34%, SL 23%, CH 19% …) with usage bars, whiff%, and velocity — powered by Statcast data. Also fixed a silent pipeline bug: the Statcast daily scraper had been writing to GCS every morning but the processor was never wired into the dispatcher, so no 2026 data ever reached BigQuery. Fixed with 2 lines. Backfilled Apr 4–11 (959 rows). Also cleared 9 pre-existing test failures in props-web.

**Known limitation:** `whiff_rate` and `avg_velocity` in the arsenal panel are pitcher-level stats (overall, not per pitch type). `statcast_pitcher_daily` has pitch counts per type but no per-type velocity or whiff rate. Usage % is correct and per-type. See "What To Work On Next" if you want true per-pitch-type stats.

---

## What Was Done

### 1. Statcast processor wiring fix (2 lines, `c5174c60`)

**Root cause:** `mlb_statcast_daily` scraper ran every morning at 8:05 AM ET, successfully writing Statcast pitch data to GCS. But `MlbStatcastDailyProcessor` was exported from `data_processors/raw/mlb/__init__.py` yet never imported in `main_processor_service.py` and never added to `PROCESSOR_REGISTRY`. Every daily GCS file was silently dropped.

**Fix:** `data_processors/raw/main_processor_service.py`:
- Added `MlbStatcastDailyProcessor` to the MLB import block
- Added `'mlb-statcast/daily-pitcher-summary': MlbStatcastDailyProcessor` to `PROCESSOR_REGISTRY`

**Backfill:** GCS files existed for Mar 28 – Apr 11. Mar 28–Apr 3 had empty `pitcher_summaries` arrays (Statcast data not yet indexed when scraper ran). Apr 4–11: 959 rows written using the processor CLI with `SPORT=mlb --force` to bypass dedup.

Also fixed: wrong default `--bucket` value in processor CLI (`mlb-scraped-data` → `nba-scraped-data`) and added `--force` flag to bypass dedup check for backfills.

### 2. `pitcher_pitch_arsenal_latest` BQ view (`50cdc8e3`)

New view: `mlb_analytics.pitcher_pitch_arsenal_latest`

**Source:** `mlb_raw.statcast_pitcher_daily.pitch_types` — JSON string like `{"FF": 42, "SL": 28, "CH": 18}`

**Method:** `REGEXP_EXTRACT(pitch_types, CONCAT(r'"', code, r'":\s*(\d+)'))` cross-joined with a known pitch code list. BigQuery `JSON_EXTRACT_SCALAR` requires a literal JSONPath constant — it cannot accept a computed expression. `REGEXP_EXTRACT` accepts dynamic patterns.

**Output:** One row per `(pitcher_lookup, pitch_type_code)`, aggregated over last 5 starts:
- `usage_pct` — pitch count as % of total pitches across those 5 starts ✓ (per pitch type)
- `whiff_rate` — weighted avg of pitcher's overall whiff_rate ✗ (pitcher-level, not per pitch type)
- `avg_velocity` — weighted avg of pitcher's overall avg_velocity ✗ (pitcher-level, not per pitch type)
- Filters to pitch types ≥ 5% of arsenal

Deployed directly: `bq query --nouse_legacy_sql < schemas/bigquery/mlb_analytics/pitcher_pitch_arsenal_tables.sql`

### 3. Exporter update (`836062b8`)

`data_processors/publishing/mlb/mlb_pitcher_exporter.py`:
- New `_fetch_pitch_arsenal(pitcher_lookups)` method
- Wired into `_build_bundle()` and `_build_profile()`
- `pitch_arsenal` array added to all per-pitcher profile JSONs

**Critical lookup format mismatch:** `pitcher_game_summary.player_lookup` uses underscores (`sean_manaea`). `statcast_pitcher_daily.player_lookup` uses no underscores (`seanmanaea`). The fix: build a `{stripped: original}` map before querying, translate back after.

Re-exported all 298 pitcher profiles manually after deploy: `SPORT=mlb PYTHONPATH=. .venv/bin/python3 data_processors/publishing/mlb/mlb_pitcher_exporter.py --date 2026-04-12`

### 4. Frontend arsenal panel (`props-platform-web: 1be0a90`)

New `PitchArsenal` component in `src/app/pitchers/[slug]/page.tsx`:
- Positioned between Last-10 strip and Season stats
- Pitch name + code, usage % bar (fills proportionally to usage), whiff%, avg velocity
- Tonight context line ("Pitching vs/@ opponent tonight")
- Up to 5 pitch types sorted by usage DESC
- Footer note: "Last N starts · Velo = avg all pitches" (honest about the limitation)
- Renders nothing if `pitch_arsenal` is empty (early season, off-season, pre-2025 pitchers)

New type: `PitcherPitchType` in `src/lib/pitchers-types.ts`. `pitch_arsenal: PitcherPitchType[]` added to `PitcherProfileResponse`.

TypeScript: clean. All tests: passing.

### 5. Test fixes (`props-platform-web: a1eaf8f`)

9 pre-existing failures from commit `4571811` (Remove player search) fixed in 4 files:

| File | Root cause | Fix |
|------|-----------|-----|
| `BottomNav.test.tsx` (4) | "Picks"/"/picks" → "Bets"/"/best-bets" in nav | Updated labels and hrefs |
| `ThemeToggle.test.tsx` (1) | Expected dark default; system theme → light when `matchMedia.matches=false` | Fixed assertion direction |
| `SettingsDropdown.test.tsx` (3) | "Default Page" section doesn't exist; "Show Betting Odds" → "Show All Players"; `detectTimezone()` non-deterministic | Removed dead assertions, added `Intl.DateTimeFormat` mock to force ET |
| `GameReportTab.test.tsx` (1) | "No game tonight" → "No game data for this date" | Updated string |

56/56 tests passing.

---

## System State

### GCS API
- `v1/mlb/pitchers/leaderboard.json` — unchanged schema
- `v1/mlb/pitchers/{pitcher_lookup}.json` — now includes `pitch_arsenal` array (298 files re-uploaded)

### BigQuery
- `mlb_analytics.pitcher_pitch_arsenal_latest` — new view, live, ~2K rows (2025 + 2026)
- `mlb_raw.statcast_pitcher_daily` — 18K rows (2025 full season) + 959 rows (Apr 4–11 2026)

### Cloud Run
- `nba-phase2-raw-processors` — deployed `c5174c60`, now dispatches statcast processor
- `phase6-export` — unchanged (pitchers export type already supported)

### Daily pipeline (now working)
- 8:05 AM ET: `mlb-statcast-daily` scheduler → scraper writes to GCS
- Scraper publishes to `mlb-phase1-scrapers-complete` Pub/Sub
- `nba-phase2-raw-processors` picks up message → `MlbStatcastDailyProcessor` → `mlb_raw.statcast_pitcher_daily`
- 10:45 AM ET + 1 PM ET: pitcher export schedulers re-export profiles with fresh arsenal data

---

## What To Work On Next

### Option A: True per-pitch-type stats (half-day)

Upgrade the arsenal panel from "pitch counts" to full pitch quality metrics (velocity per pitch type, whiff rate per pitch type). Requires real per-pitch data, not just daily aggregates.

**Path: Fix `mlb_game_feed.py` scraper**

The scraper fetches `https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live` which returns every `playEvent` with `pitchData.startSpeed`, `pitchData.spinRate`, `details.type.code`, `details.description`. Currently `transform_data` only extracts strikeout plays. Rewrite to emit one row per pitch:

```
game_pk, game_date, pitcher_lookup, pitcher_id, pitch_type_code,
velocity, spin_rate, is_swinging_strike, is_called_strike, is_foul,
count_balls, count_strikes, inning, at_bat_index, pitch_number
```

Also: scraper currently takes `game_pk` as required param. Make it accept `game_date` instead, look up game_pks from schedule, iterate.

Then:
1. New BQ schema: `schemas/bigquery/mlb_raw/mlb_game_feed_tables.sql` (partitioned by game_date, clustered by pitcher_lookup + pitch_type_code)
2. New processor: `data_processors/raw/mlb/mlb_game_feed_processor.py` (following `mlb_pitcher_stats_processor.py` pattern)
3. Wire into `PROCESSOR_REGISTRY`: `'mlb-stats-api/game-feed': MlbGameFeedProcessor`
4. New scheduler: 3 AM ET daily, Mar–Oct
5. Update `pitcher_pitch_arsenal_latest` view to source from `mlb_game_feed` instead of (or in addition to) `statcast_pitcher_daily`

This also unlocks the advanced arsenal stats from the Session 528 handoff: K Pitch Effectiveness L3, Inning Velo Fade, Arsenal Concentration Score, etc.

### Option B: Keep the panel as-is, do NBA off-season work

Usage % is genuinely useful and unique on a betting site. The velocity/whiff caveat is clearly labeled. Perfectly shippable as-is. Could instead focus on NBA off-season items or assists/rebounds market development (schedulers already running since Apr 6).

### Option C: Assists/rebounds prediction models

Data clock started Apr 6 (`nba-assists-props-morning/pregame` schedulers active). Points model captures zero signal for assists/rebounds — dedicated models needed. 4+ weeks of data required minimum; could start designing feature sets and model architecture now. `bettingpros_player_points_props` table already has `market_type` column with assists/rebounds data.

---

## Files Changed

### `nba-stats-scraper`

| File | Change |
|------|--------|
| `data_processors/raw/main_processor_service.py` | Added `MlbStatcastDailyProcessor` import + PROCESSOR_REGISTRY entry |
| `data_processors/raw/mlb/mlb_statcast_daily_processor.py` | Fixed CLI default bucket; added `--force` flag |
| `schemas/bigquery/mlb_analytics/pitcher_pitch_arsenal_tables.sql` | **New** — `pitcher_pitch_arsenal_latest` view |
| `data_processors/publishing/mlb/mlb_pitcher_exporter.py` | Added `_fetch_pitch_arsenal()`, updated `_build_bundle()` + `_build_profile()` |

### `props-platform-web`

| File | Change |
|------|--------|
| `src/lib/pitchers-types.ts` | Added `PitcherPitchType` interface; `pitch_arsenal` field on `PitcherProfileResponse` |
| `src/app/pitchers/[slug]/page.tsx` | Added `PitchArsenal` component + `usageBarWidth()` helper |
| `src/components/layout/BottomNav.test.tsx` | Fixed 4 stale assertions |
| `src/components/ui/ThemeToggle.test.tsx` | Fixed 1 stale assertion |
| `src/components/ui/SettingsDropdown.test.tsx` | Fixed 3 stale assertions + added Intl mock |
| `src/components/modal/GameReportTab.test.tsx` | Fixed 1 stale assertion |

---

## Lessons / Guardrails

- **`PROCESSOR_REGISTRY` is the source of truth for GCS → BQ routing.** When a new processor is created, it must be added there or it silently drops every message. Check with `grep -n "mlb-" data_processors/raw/main_processor_service.py` to audit coverage.
- **BigQuery `JSON_EXTRACT_SCALAR` requires a literal JSONPath.** Cannot use `CONCAT('$.', col)`. Use `REGEXP_EXTRACT(json_col, CONCAT(r'"', code, r'":\s*(\d+)'))` for dynamic key lookup.
- **`statcast_pitcher_daily` pitch data is pitcher-level, not pitch-type-level.** `pitch_types` JSON has counts only. For true per-pitch-type velocity/whiff, need `mlb_game_feed` (MLB Stats API) or Baseball Savant.
- **Lookup format split: `pitcher_game_summary` uses underscores, `statcast_pitcher_daily` does not.** Any JOIN or lookup between these tables needs normalization on one side. In Python: `pl.replace('_', '')` maps `sean_manaea` → `seanmanaea`.
- **Processor dedup blocks CLI backfills.** Add `processor.SKIP_DEDUPLICATION = True` before calling `processor.run()`, or use a `--force` CLI flag. Without it, re-runs return `rows_processed: 0` silently.
- **`game_status IN ('Final', 'F')` required for MLB queries.** 2025 data uses `'F'`, 2026 uses `'Final'`. Always use the IN clause.

---

## Memory Updates

Key facts worth storing:
- `mlb_raw.statcast_pitcher_daily` now populates daily from the statcast pipeline (was broken since scraper launch — fixed this session)
- `mlb_analytics.pitcher_pitch_arsenal_latest` view exists and is live
- Lookup format mismatch between `pitcher_game_summary` (underscores) and `statcast_pitcher_daily` (no underscores) — normalize with `.replace('_', '')`

---

## Model Recommendation for Next Session

**Sonnet.** If continuing pitcher arsenal work (Path A: fix `mlb_game_feed` scraper), all the decisions are made and documented here. If pivoting to assists/rebounds models, that's architecture work that might benefit from Opus — but start with Sonnet to explore data availability first.
