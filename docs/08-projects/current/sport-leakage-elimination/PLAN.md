# Sport-Leakage Elimination Plan

**Date:** 2026-05-11 (evening session)
**Status:** Approved scope, awaiting execution
**Approved by:** User (all four phases, Option A on NBA legacy paths)

---

## Why this plan exists

- 2 user-reported bugs in 1 session (pts→Ks on MLB Best Bets, MLB Tonight calendar showing May 3), 3 in 3 weeks
- 14+ confirmed sport-leakage bugs identified by 4-agent architecture audit (see references)
- A May 4 commit (`44f05dc` in props-web) **explicitly diagnosed** the calendar bug and deferred ("Tracked separately"). User found it 7 days later
- `props-web/CLAUDE.md` lines 44-92 already document "Sport-Routing Rules" — they were ignored. Rules advisory, no enforcement
- Existing `e2e/sport-render.spec.ts` regex `/no leaderboard/i` matches the broken state — bug passes its own test
- `props-web` has no `.github/` directory: zero CI gates exist
- 14 backend monitors exist; zero would have caught this bug. `stuck-loading-watchdog` Sentry events fire for every affected user — nobody routes them to Slack

## The bug (single-paragraph context)

The MLB Tonight page (`/mlb/`) calls `useGameCounts()` which fetches NBA-only `gs://nba-props-platform-api/v1/schedule/game-counts.json`. That JSON says `last_game_date: 2026-05-03` (NBA's last playoff game). `useEffectiveDate` sees "today has no NBA games" → snaps MLB date back to May 3 → MLB pitcher history endpoint 404s for that date → "No leaderboard for this date." Same class as the pts→Ks bug fixed in commit `9c253e4`.

## Goals

1. Restore MLB Tonight page (calendar + history)
2. Eliminate the 14+ pending leaks at structural level (not one-by-one)
3. Wire monitoring so user stops being the canary
4. Make recurrence either type-impossible or CI-impossible

---

## Phase 1 — Stop the Bleeding (1.5-2 days)

**Apply reviewer amendments before execution.** Items in execution order:

| # | Item | Effort | Repo | Notes |
|---|------|--------|------|-------|
| 1.0 | **Backfill verification** — query `mlb_predictions.pitcher_strikeouts` for `MIN(game_date)` to set the real backfill start (plan claimed Mar 28, reviewer flagged late-March uncertainty) | 10 min | BQ | Eliminates date-math off-by-N |
| 1.1 | ✅ **DONE** — commit `pts → Ks` fix to props-web. Commit `9c253e4`, pushed 2026-05-11 | — | props-web | Already shipped this session |
| 1.2 | Sport-aware `useGameCounts({ sport })` AND short-circuit `useEffectiveDate` when `sport !== "nba"`. **Fix BOTH layers** per `props-web/CLAUDE.md` rule #2 | 1h | props-web | Options bag (not positional). Keep backward-compat shim 1 week |
| 1.3 | **One-line spec fix:** remove `/no leaderboard/i` from accepted regex in `e2e/sport-render.spec.ts:25,60`. Bug currently passes its own test | 5 min | props-web | Don't wait for Phase 4.2 rewrite |
| 1.4 | Backfill MLB pitcher history. Extract `_write_history_only(game_date)` helper on `mlb_pitcher_exporter.py:106-110` to avoid clobbering live `leaderboard.json`. Run loop for verified backfill range | ~90 min | nba-stats-scraper | Reviewer: 35+ BQ queries via `_build_bundle(game_date)` per date — time on one date first |
| 1.5 | **GitHub Actions PR gate** — `.github/workflows/e2e.yml` in props-web. Runs Playwright on every PR, blocks merge on fail. **Reviewer moved this forward from Phase 4** | 2-3h | props-web | **Without this, every Phase 2 PR can re-introduce the leak** |
| 1.6 | 10-line `gsutil stat` freshness check on `gs://...mlb/pitchers/history/{today}.json` in `daily_health_check/main.py`. Catches today's class of bug immediately | 20 min | nba-stats-scraper | Don't wait for Phase 2.4 HTML synthetic |
| 1.7 | Wire `stuck-loading-watchdog` Sentry events → Slack `#nba-alerts`. **Filter: `tag.stuck_loading CONTAINS ":mlb"`** (NOT `STARTS_WITH "mlb-"` — reviewer caught this; tag is `tonight:mlb` / `best-bets:mlb`) | 30 min | Sentry console | Existing telemetry, zero code |
| 1.8 | Smoke check on `/mlb`, `/mlb/results`, `/mlb/picks` — all three call `useGameCounts`. Note: results/picks will show empty content until 2.2's capability gates ship; that's expected behavior | 15 min | manual QA | Verifies the hook fix didn't break NBA |

**Phase 1 commit gotchas:**
- `git push` auto-deploys both repos. Verify nothing in flight: `gcloud builds list --limit=5` before pushing
- `regularSeasonEndDate` for MLB is `undefined` in `sport-config.ts:34`. When MLB season ends Sept, same bug recurs in reverse. **Add TODO**.
- Pass `{ sport }` options bag to `fetchGameCounts`, not positional — fetcher signature already takes options

---

## Phase 2 — Kill the 14+ Predicted Bugs Structurally (5-6 days)

**Reviewer correction:** Phase 2.3 should be a **file split**, not in-place mutations. `fetchBestBetsAll(sport)` in `best-bets-api.ts:14` got sport-awareness right because it was carved off from `api.ts` when MLB Best Bets shipped — file split forced sport-awareness at carve time. Repeat that intervention.

### 2.1 Expand `SPORT_META` (2h)

```typescript
// src/lib/sport-config.ts
export interface SportMeta {
  emoji: string;
  displayName: string;
  offseasonMessage: string;
  regularSeasonEndDate?: string;
  // NEW:
  apiPathPrefix: "" | "mlb/";
  capabilities: {
    calendar: boolean;
    gameCounts: boolean;
    resultsPage: boolean;
    picksPage: boolean;
    trendsPage: boolean;
    playerSearch: boolean;
    playerProfile: boolean;
    liveGrading: boolean;
    challengeGrading: boolean;
    news: boolean;
  };
  dateLockBehavior: "snap-to-last-game" | "today";
}
```

Initial MLB capabilities all `false` except `bestBets`, `pitcherProfile`. Flip to `true` as backend endpoints ship in Phase 3.

**Reviewer note:** capability flag shape may ossify around 2 sports. Consider `enabledFeatures: Set<Feature>` if a third sport is on the roadmap. For now, the boolean record is fine.

### 2.2 Gate `/[sport]/*` pages with capability checks (4h)

Each page early-returns `<NotAvailableForSport sport={sport} feature="results" />` when capability is false. Eliminates:
- `/mlb/results` — 4 compounded leaks (NBA picks + grading + system + yesterday's best bets)
- `/mlb/picks` — NBA picks/subsets leakage
- `/mlb/players?player=X` — 404s
- `/mlb/trends` — brief NBA render before redirect

### 2.3 Split `api.ts` → `nba-api.ts` + `mlb-api.ts` (2-3 days)

**Reviewer's strongest contribution.** Treat this as a refactor, not mutation:

1. Create `src/lib/nba-api.ts`. Move all current NBA-implicit fetchers from `api.ts`. Each takes no sport arg (NBA-only by file location). Keep names but file-prefix them.
2. Create `src/lib/mlb-api.ts`. Add MLB equivalents that hit `mlb/`-prefixed paths. Use existing `mlb-pitchers-api.ts` as model.
3. Re-export shared types from `api.ts` for back-compat (1 week deprecation).
4. Update callers: NBA pages import from `nba-api`, MLB pages from `mlb-api`. Compile errors guide the migration.
5. Hooks that wrap fetchers become sport-parametrized at the same time: `useGameCounts(sport)`, `useNewsIndicators(sport)`, `useLiveUpdates(sport)`, `useChallengeGrading(sport)`.

Fetchers affected (12): `fetchGameCounts`, `fetchPlayerIndex`, `fetchPlayerProfile`, `fetchResultsByDate`, `fetchSystemPerformance`, `fetchYesterdayBestBets`, `fetchTrendsTonight`, `fetchTonightNewsSummary`, `fetchLiveGrading`, `fetchLiveScores`, `fetchDailyPicks`, `fetchSeasonData`.

### 2.4 Synthetic HTML check — F2 from May 4 handoff (3h)

Extend `orchestration/cloud_functions/daily_health_check/main.py` with `RENDERED_PAGE_CHECKS` dict. GET `https://playerprops.io/mlb`, regex-assert `Tonight's Starters` present AND `data-game-date` within 1 day of today. Reuse existing Slack webhook.

---

## Phase 3 — Backend GCS Symmetry (1-2 weeks, incremental)

### 3.1 MLB calendar/schedule exporter (1 day)

Build `data_processors/publishing/mlb/mlb_season_game_counts_exporter.py` analogous to `season_game_counts_exporter.py` but querying `mlb_raw.mlb_schedule`. Output: `v1/mlb/schedule/game-counts.json`.

Flip `SPORT_META.mlb.capabilities.gameCounts = true` once verified in production.

### 3.2 Remaining MLB endpoints, build-to-demand

Per the audit, these MLB equivalents are missing. Build only when a feature actually needs them:
- `v1/mlb/players/index.json` — search index (unlocks SearchBar on MLB pages)
- `v1/mlb/players/{lookup}.json` — pitcher profiles
- `v1/mlb/streaks/today.json`
- `v1/mlb/live/{date}.json` + `v1/mlb/live-grading/{date}.json` (only if live MLB scoring needed)
- `v1/mlb/best-bets/yesterday.json` + `/performance.json` + `/record.json` + `/history.json`

Each unlocks a capability flag in `SPORT_META`.

### 3.3 GCS path contract documentation (1h)

`docs/01-architecture/gcs-path-contract.md`: "Bare paths under `v1/` (e.g., `v1/schedule/`, `v1/players/`) are NBA-only legacy by convention. **New resources MUST be sport-prefixed (`v1/{sport}/...`).** Symmetry check enforced in CI (Phase 4.5)."

---

## Phase 4 — Prevention Infrastructure (2 weeks, parallel)

**Reordered per reviewer: 4.3 → Phase 1 (CI gate), 4.2 spec assertion → Phase 1 (one-line fix). Remaining items below.**

### 4.4 Branded `SportPath<S>` types (0.5-1 day)

```ts
// src/lib/api-paths.ts
declare const sportTag: unique symbol;
export type SportPath<S extends "nba" | "mlb" | "shared" = "nba" | "mlb" | "shared"> =
  string & { readonly [sportTag]: S };

export const nbaPath = (p: `/${string}`): SportPath<"nba"> => p as SportPath<"nba">;
export const mlbPath = (p: `mlb/${string}` | `/mlb/${string}`): SportPath<"mlb"> =>
  p as SportPath<"mlb">;
export const sharedPath = (p: `/${string}`): SportPath<"shared"> => p as SportPath<"shared">;
```

**Reviewer caveat:** branded paths catch *static* misuse only — not runtime hook chains. Don't oversell as "type-impossible." This is incremental polish atop the file split (2.3) which does the load-bearing work.

### 4.5 GCS symmetry check (2h)

CI script: for each new `v1/X/` path in backend publishers, require either `v1/mlb/X/` exists OR explicit `unsupported` marker in `data_processors/publishing/PATH_REGISTRY.py`. Fail PR otherwise.

### 4.6 ESLint `no-restricted-imports` (1-2h)

In `src/components/mlb/**`, `src/components/pitchers/**`, ban imports of NBA-only fetchers from `nba-api.ts`. Belt-and-suspenders alongside Phase 2.3 file split.

### 4.7 F6 Vercel deploy SHA drift alert (1.5h)

GitHub Action or Cloud Function: compare `gh api repos/.../commits/main` SHA against Vercel deployments API latest READY. Alert `#nba-alerts` if HEAD is >24h ahead. **What would have caught the May 8-11 Vercel 3-day-stale build.**

### 4.8 PR template + process (30 min)

`.github/pull_request_template.md`:
- [ ] Touched a fetcher in `src/lib/nba-api.ts` or `src/lib/mlb-api.ts`? Updated `e2e/sport-render.spec.ts`?
- [ ] Touched a hook in `src/hooks/` consumed by `/[sport]/*`? Sport-parametrized?
- [ ] Tested locally on both `/nba` and `/mlb`?

### 4.9 Convert "tracked separately" deferrals → real tickets (process)

Any commit body containing "tracked separately" / "follow-up" / "deeper architectural gap" gets a mandatory linked GitHub issue. The May 4 commit's deferral is exactly the recurrence pattern.

---

## Explicitly NOT doing (reviewer-validated over-engineering)

- **Per-sport route groups** `(nba)/nba/` `(mlb)/mlb/` with sport-scoped data providers. 1-2 week refactor, breaks deep links. Skip.
- **Runtime sport-context middleware wrapping every fetch.** Duplicates type-level guarantees with weaker (runtime) guarantees + adds latency. Skip.
- **NBA bare-path migration to `v1/nba/...`** (Option B from earlier). User approved Option A: leave NBA bare, document the contract.

---

## Effort summary (reviewer-corrected)

| Phase | Original | Corrected |
|-------|----------|-----------|
| Phase 1 | ~1 day | **1.5-2 days** |
| Phase 2 | 3-4 days | **5-6 days** |
| Phase 3 | 1-2 weeks | 1-2 weeks (unchanged) |
| Phase 4 | 2-3 weeks | 2 weeks (some items moved to Phase 1) |
| **Total active dev** | ~3 weeks | **~3-4 weeks** |

---

## Success criteria

1. MLB Tonight page shows today's date by default with leaderboard data (Phase 1)
2. MLB history navigable back to opener (Phase 1)
3. All 14+ predicted leakage bugs fixed by structural change (Phase 2+3)
4. `npm run build && npm test` blocks any PR that introduces a new leak (Phase 1.5 + Phase 4 specs)
5. User stops being the canary: next regression discovered by monitoring, not user (Phase 1.7 + 2.4)
6. Zero "tracked separately" deferrals in commit bodies without linked issues (Phase 4.9)

---

## References

### Agent investigations (this session, 2026-05-11)
- 5 incident reviewers (forensic timeline, sport-leakage architecture audit, MLB Tonight retention investigation, monitoring gap, prevention plan)
- 1 fresh plan reviewer (independent verification of load-bearing claims, reviewer amendments)
- Earlier same day: 23-agent MLB improvement investigation (separate plan)

### Key files

**Frontend (`/home/naji/code/props-web`):**
- `src/lib/sport-config.ts` (Phase 2.1 — expand SPORT_META)
- `src/lib/api.ts` (Phase 2.3 — split into nba-api.ts + mlb-api.ts)
- `src/lib/api-paths.ts` (Phase 4.4 — NEW for branded types)
- `src/hooks/useGameCounts.ts` (Phase 1.2 — sport-required)
- `src/hooks/useEffectiveDate.ts` (Phase 1.2 — short-circuit non-NBA)
- `src/app/[sport]/*/page.tsx` (Phase 2.2 — capability gates)
- `src/lib/stuck-loading-watchdog.ts:37` (Phase 1.7 — Sentry tag schema reference)
- `e2e/sport-render.spec.ts` (Phase 1.3 — spec assertion fix; Phase 4 — full rewrite)
- `.github/workflows/e2e.yml` (Phase 1.5 — NEW CI gate)
- `.github/pull_request_template.md` (Phase 4.8 — NEW)
- `CLAUDE.md` (Phase 4.8 — update Sport-Routing Rules)

**Backend (`/home/naji/code/nba-stats-scraper`):**
- `data_processors/publishing/mlb/mlb_pitcher_exporter.py:106-110` (Phase 1.4 — extract `_write_history_only`)
- `data_processors/publishing/mlb/mlb_season_game_counts_exporter.py` (Phase 3.1 — NEW)
- `orchestration/cloud_functions/daily_health_check/main.py` (Phase 1.6 — gsutil stat; Phase 2.4 — RENDERED_PAGE_CHECKS)
- `data_processors/publishing/PATH_REGISTRY.py` (Phase 4.5 — NEW)
- `docs/01-architecture/gcs-path-contract.md` (Phase 3.3 — NEW)

### External
- Sentry props-web project — Alerts (Phase 1.7)
- Vercel deployment API (Phase 4.7)
- Slack `#nba-alerts` channel
