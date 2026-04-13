# Session 528 Handoff — MLB Pitcher UI (Phase 1 Shipped)

**Date:** 2026-04-12
**Focus:** Design + ship new MLB pitcher leaderboard and profile pages
**Commits:**
  - `nba-stats-scraper`: `ed001240` → `8395f1d5` (1 commit)
  - `props-platform-web`: `3b5ab63` → `d6491f4` (1 commit)

---

## TL;DR

New `/pitchers` and `/pitchers/[slug]` pages are live on playerprops.io. Backed by a new GCS export (`v1/mlb/pitchers/leaderboard.json` + 298 per-pitcher profiles) regenerated twice daily by two new Cloud Schedulers. The page leads with the unique differentiator nobody else shows: **our model's HR + rank per pitcher** (e.g. "Logan Webb — 65.7%, #111 of 218 starters"). Phase 2 (pitch-by-pitch / Statcast forensics) deferred.

Before building, 10 agents (5 Opus + 5 Sonnet) reviewed competitive landscape, data feasibility, UX, betting integration, and strategy. Key converged findings: don't out-Savant Savant, lead with per-pitcher prediction track record, game-first UX (tonight's slate default, not a 187-pitcher ranked list), full page not modal.

---

## What Was Done (Chronological)

### 1. Data inventory + feasibility research (10 parallel agents)

Key findings that shaped the design:

- **Zero pitch-by-pitch data exists in BQ today.** `mlb_raw.mlb_game_feed` has the right pitch-level schema (`pitch_type`, `pitch_speed`, `spin_rate`, `is_swinging_strike`) but 0 rows. Scraper (`scrapers/mlb/mlbstatsapi/mlb_game_feed.py`) writes only GCS, never BQ — classified **MEDIUM fix** (needs `transform_data` rewrite to flatten `playEvents`, a new BQ exporter, a processor, and a scheduler).
- **`mlb_analytics.pitcher_game_summary`** has everything needed for Phase 1: 20K rows, per-start stats, rolling windows, splits, lines, O/U outcomes.
- **`mlb_predictions.pitcher_strikeouts`** has graded prediction history (is_correct, actual_strikeouts) going back to 2025-01 — this is the foundation of the "our track record" stat.
- **Baseball Savant CSV scrape via Cloud Run** is the right path for Phase 2 (free, ~700K rows/season, legally equivalent to every public baseball stats site — FanGraphs, Pitcher List, etc.). Alternative: fix `mlb_game_feed`. Prefer the fix (we already have the scraper skeleton).
- **Frontend is `/home/naji/code/props-web`** (separate repo from backend), Next.js 16 App Router on Vercel, data via `/api/proxy/[...path]` → GCS.

### 2. Backend — new pitcher exporter (`8395f1d5`)

`data_processors/publishing/mlb/mlb_pitcher_exporter.py` (new, ~450 lines). Extends `BaseExporter`. One dry-run builds everything:

- `_fetch_tonight_predictions()` — today's starters (deduped per pitcher via `QUALIFY ROW_NUMBER`, highest-edge system wins)
- `_fetch_best_bet_keys()` — BB flag lookup
- `_fetch_track_records()` — per-pitcher graded HR since 2025-01 (deduped same way)
- `_rank_track_records()` — population rank by HR%, min 5 picks
- `_fetch_season_aggregates()` — season K, ERA, WHIP, K/9 from `pitcher_game_summary`
- `_fetch_game_logs()` — last 20 starts per pitcher, joined with predictions + BB flag, `over_under_result` computed inline from `strikeouts > line` (the source column is unpopulated)

**Four leaderboards:** Hot Hands (current OVER streaks), Strikeout Kings, Model Trusts Him (rank by HR with population rank), Line Beaters (avg K minus line over last 10).

**Writes two products:**
1. `v1/mlb/pitchers/leaderboard.json` — tonight + 4 leaderboards
2. `v1/mlb/pitchers/{pitcher_lookup}.json` — one file per pitcher (~298 files)

`orchestration/cloud_functions/phase6_export/main.py` now dispatches `export_types=["pitchers"]` for MLB. Auto-deployed from main push (Cloud Build trigger `deploy-phase6-export`, SUCCESS at 2026-04-13 01:16 UTC, revision `phase6-export-00342-zum`).

### 3. Two new Cloud Schedulers

Created via `gcloud scheduler jobs create pubsub`:

| Job | Schedule | Purpose |
|-----|----------|---------|
| `mlb-pitcher-export-morning` | `45 10 * 3-10 *` (10:45 AM ET) | Post-grading refresh — updates track records after overnight grading completes |
| `mlb-pitcher-export-pregame` | `0 13 * 3-10 *` (1 PM ET) | Tonight's slate before first pitch |

Both publish `{"sport":"mlb","export_types":["pitchers"],"target_date":"today"}` to `nba-phase6-export-trigger`. March-October (matches other MLB schedulers — don't use `4-10`, that broke Opening Day twice in 2025).

### 4. Frontend — `/pitchers` + `/pitchers/[slug]` (`d6491f4`)

All in `props-platform-web`:

- `src/lib/pitchers-types.ts` — full type surface for both endpoints
- `src/lib/pitchers-api.ts` — `fetchPitcherLeaderboard()`, `fetchPitcherProfile(id)`
- `src/app/pitchers/page.tsx` — leaderboard page with 5 angle chips
- `src/app/pitchers/[slug]/page.tsx` — detail page (uses React 19 `use()` hook for params promise)
- `src/app/api/proxy/[...path]/route.ts` — added `mlb/pitchers` 5-min cache rule
- `src/components/layout/Header.tsx` — added "Pitchers" to `NAV_ITEMS`

**Detail page sections (in order):**
1. Name + team
2. Tonight hero card (only if has_start)
3. **"Our Track Record" panel** — the killer stat (HR%, record, rank #X of Y, OVER/UNDER splits)
4. Last-10 strip — green/red/gray bars, K count below each
5. Season stats grid
6. Full 20-start game log

Typecheck passed, build passed, lint clean. Existing test failures in `BottomNav.test.tsx`/`ThemeToggle.test.tsx`/`SettingsDropdown.test.tsx`/`GameReportTab.test.tsx` are pre-existing (traced to commit `4571811 Remove player search from header and bottom nav`), not related to this work.

### 5. End-to-end verification

- Manual `python mlb_pitcher_exporter.py --date 2026-04-12` wrote 1 leaderboard + 298 profiles successfully (first upload, populated GCS before CF deploy finished)
- Scheduler manual-triggered at 01:17:23 UTC → `leaderboard.json` updated 01:17:33, `logan_webb.json` updated 01:17:37 — full CF dispatch path works
- `curl https://playerprops.io/pitchers` → 200, page renders with "MLB Pitchers" + "Tonight" text
- `curl https://playerprops.io/api/proxy/mlb/pitchers/logan_webb.json` → full profile JSON (65.7% HR, rank #111 of 218, 20 game_log entries)

---

## System State

### GCS API surface (new)
- `gs://nba-props-platform-api/v1/mlb/pitchers/leaderboard.json`
- `gs://nba-props-platform-api/v1/mlb/pitchers/{pitcher_lookup}.json` × ~298

### Cloud Function
- `phase6-export` revision `00342-zum` on commit `8395f1d`. Dispatches `pitchers` export type.

### Cloud Scheduler (us-west2)
- `mlb-pitcher-export-morning` — ENABLED, 10:45 AM ET, March-October
- `mlb-pitcher-export-pregame` — ENABLED, 1:00 PM ET, March-October

### Frontend
- `/pitchers`, `/pitchers/[slug]` live on playerprops.io
- "Pitchers" nav visible in Header (appears in both NBA and MLB modes — the page itself is MLB-only)

### Known small issues
- Pre-existing test failures in props-web (unrelated to this session): `BottomNav.test.tsx` (4), `ThemeToggle.test.tsx` (1), `SettingsDropdown.test.tsx` (3), `GameReportTab.test.tsx` (1). Someone should fix these — they're from the `Remove player search` commit.
- `phase6-export` logs are very sparse — only the `fuzzywuzzy not available` warning shows, not the `logger.info(...)` calls inside the MLB branch. Function works end-to-end (GCS files update), but log verbosity during MLB dispatch is low. Worth investigating if we need to debug a future failure.

---

## What To Work On Next — Phase 2

Primary goal: unlock pitch-by-pitch stats for the profile page. **Use Sonnet for this work** — the heavy architecture decisions are already made and documented here. Sonnet is plenty for the implementation.

### Priority 1: Populate `mlb_raw.mlb_game_feed` (Task #7, MEDIUM)

Table has the right schema, scraper exists, but nothing writes pitch-level rows to BQ. Three paths, pick one:

**Path A (recommended): Fix existing `mlb_game_feed` scraper.**
- Rewrite `scrapers/mlb/mlbstatsapi/mlb_game_feed.py::transform_data` to flatten `playEvents` into one row per pitch per at-bat (not just strikeout summaries)
- Add a `bigquery` exporter entry targeting `mlb_raw.mlb_game_feed`
- Add `data_processors/raw/mlb/mlb_game_feed_processor.py` to load GCS→BQ
- Add Cloud Scheduler job (daily post-game, e.g. 3 AM ET for yesterday's games, 3-10 season months)
- Raw MLB Stats API endpoint: `https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live` — already returns every `playEvent` with `pitchData.startSpeed`, `pitchData.spinRate`, `details.type`, `details.description`

**Path B: New Baseball Savant scraper.** Agent O2's analysis: `https://baseballsavant.mlb.com/statcast_search/csv?...`, chunk by day, ~700K rows/season, ~50-80 MB in BQ. Cheaper per-row than `mlb_game_feed` (more fields, better normalized) but duplicates existing work.

**Path C: Do nothing.** Leave pitch-type stats out of the UI. Profile page still has strong content — track record is the moat, not pitch mix. Valid option if we're velocity-constrained.

Pick A if we want the data for both UI and future ML features. Pick B if Savant's extra fields (exit velo, spin axis, movement) will be valuable. Pick C if we want to ship another feature instead.

### Priority 2: Pitch arsenal analytics (blocked on 1)

Build `mlb_analytics.pitcher_pitch_arsenal_daily` materialized view aggregating per (pitcher_lookup, pitch_type, date): usage %, whiff rate, K rate, HR allowed, avg velo. Top 5 stats to surface (from agent S2 brainstorm):

1. **K Pitch Effectiveness L3** — rolling 3-start whiff rate on primary K pitch vs season average
2. **HR Pitch Fingerprint** — pitch type + location on every HR allowed
3. **3rd Time Through Drift** — pitch-type whiff rate by times-through-order
4. **Inning Velo Fade** — FB velo by inning, 1-7
5. **Arsenal Concentration Score** — HHI of pitch-type usage, trend over last 10

### Priority 3: Pitch arsenal UI panel (blocked on 2)

Add an "Arsenal" section to `/pitchers/[slug]` between Last-10 strip and Season stats. Pitch-type cards with velocity, usage %, whiff %. Tonight card should weave in: "Cole's slider whiff% 38% vs LHB; opponent is 65% LHB lineup."

### Priority 4 (lower): Clean up pre-existing props-web test failures

9 failing tests from a prior commit, unrelated to this session. Quick win if someone wants a small task.

---

## Files Changed

### Backend (`nba-stats-scraper`)

| File | Change |
|------|--------|
| `data_processors/publishing/mlb/mlb_pitcher_exporter.py` | **New** (~450 lines) — leaderboard + profile exporter |
| `orchestration/cloud_functions/phase6_export/main.py` | Added `pitchers` export type to MLB dispatch branch |
| **gcloud (no commit)** | Created `mlb-pitcher-export-morning` + `mlb-pitcher-export-pregame` schedulers |

### Frontend (`props-platform-web`)

| File | Change |
|------|--------|
| `src/lib/pitchers-types.ts` | **New** — full type surface |
| `src/lib/pitchers-api.ts` | **New** — fetch helpers |
| `src/app/pitchers/page.tsx` | **New** — leaderboard page |
| `src/app/pitchers/[slug]/page.tsx` | **New** — detail page |
| `src/app/api/proxy/[...path]/route.ts` | Added `mlb/pitchers` → 300s cache |
| `src/components/layout/Header.tsx` | Added "Pitchers" to `NAV_ITEMS` |

---

## Lessons / Guardrails

- **`pitcher_game_summary.game_status`** has two different values depending on season: `'F'` for 2025 data, `'Final'` for 2026 data. Any filter must use `IN ('Final', 'F')`. Probably worth normalizing upstream in Phase 3 analytics, but for now every query needs the IN clause.
- **`pitcher_game_summary.over_under_result`** is always NULL — don't use it. Compute inline from `strikeouts > strikeouts_line`. Same for `win_flag` which is globally broken (use `plus_minus > 0` as proxy — actually we don't even need it for pitchers).
- **Multiple system_ids per (pitcher_lookup, game_date)** in `pitcher_strikeouts`. Three active (`v1_baseline`, `v1_6_rolling`, `catboost_v2_regressor`). Always dedupe with `QUALIFY ROW_NUMBER() OVER (PARTITION BY pitcher_lookup, game_date ORDER BY ABS(IFNULL(edge, 0)) DESC, processed_at DESC) = 1` before aggregating, otherwise track record counts are 2-3× inflated.
- **`pitcher_game_summary` requires partition filter on `game_date`** — BQ rejects unfiltered queries. Always add `WHERE game_date >= DATE('YYYY-01-01')` even when you also have `season_year = YYYY`.
- **React 19 `use()` hook** is how you unwrap `params: Promise<...>` in App Router dynamic routes. Don't await; use `use(params)`.
- **Vercel doesn't need a route config change** for new pages — just drop `src/app/<route>/page.tsx` and push. SPORT_PAGES in Header only gates sport switcher visibility, not routing.
- **Exporting 298 per-pitcher files** takes ~30-60s of GCS uploads. Fine for a scheduled run, but don't put it inline in any synchronous user-facing path.

---

## Memory Updates

No MEMORY.md updates this session. Key facts worth storing if this stays in production:

- `mlb_raw.mlb_game_feed` schema exists but table is empty — scraper is a GCS-only stub. Future Phase 2 work.
- Pre-existing props-web test failures (4 files, 9 tests) from `Remove player search` commit — not a priority but useful to know.
- `game_status IN ('Final', 'F')` is required for MLB queries until upstream normalization lands.

If this session starts getting referenced in future work, create `session-528.md` with the pitch-type priorities and agent findings.

---

## Model Recommendation for Next Chat

**Use Sonnet.** Phase 2 is well-scoped implementation work: rewrite a scraper's transform method, add a new BQ exporter entry, build a processor, create a scheduler, roll up an analytics view, add UI components. The architecture decisions are already made and captured above. No novel trade-offs left to evaluate.

Reach for Opus if you hit:
- Fundamental rethink on UX (e.g., "the leaderboard isn't sticky, should it be a dashboard instead?")
- A data quality crisis that requires debating multiple root causes
- A new competitive threat or market repositioning question
