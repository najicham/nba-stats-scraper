# Session Handoff — 2026-05-11 (Late Evening) — Sport-Leakage Findings + MLB Improvement Synthesis

**Status at end of session:** Two user-reported MLB frontend bugs surfaced (pts→Ks, Tonight calendar). First fixed and shipped. Second diagnosed (NBA-only calendar consumed by MLB page); fix queued. A 5-agent incident post-mortem revealed 14+ pending sport-leakage bugs from the same class, leading to a 4-phase elimination plan. Separately, a 23-agent MLB pitcher-Ks improvement investigation was synthesized and reviewed by 8 reviewers + 1 fresh-eyes reviewer. Both plans are written to `docs/08-projects/current/` for the next session.

**Predecessors (chronological):**
- `docs/09-handoff/2026-05-11-PIPELINE-STATE-FOLLOWUP-HANDOFF.md` (morning)
- `docs/09-handoff/2026-05-11-PIPELINE-STATE-AGENT-REVIEW-FOLLOWUP.md` (afternoon)
- `docs/09-handoff/2026-05-11-PIPELINE-STATE-MLB-FOLLOWUP.md` (early evening — Pipeline state drain + MLB improvement plan v1)
- **This doc** (late evening — Sport-leakage findings + MLB plan v2 with full review)

---

## What shipped this session

### Frontend (`/home/naji/code/props-web`)

| Commit | Subject |
|--------|---------|
| `9c253e4` | **`feat(best-bets): sport-aware stat labels (Ks for MLB, pts for NBA)`** — fixed user-reported "Over 4.5 pts" bug on MLB Best Bets. Adds `src/lib/stat-labels.ts` with `statLabel(stat, count?)` — K returns singular "K" when count===1, plural "Ks" otherwise. NBA abbreviations unchanged. Deletes duplicated local maps in 3 components. 8 vitest tests, pass. Vercel build pending verification at push time. |

### Backend (`/home/naji/code/nba-stats-scraper`)

No code changes this session. Two **plan documents** added for the next session:
- `docs/08-projects/current/sport-leakage-elimination/PLAN.md`
- `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md`

### Earlier in the day (per `2026-05-11-PIPELINE-STATE-MLB-FOLLOWUP.md`)

- Queue cleanup: 371 destructive Phase 6 rows marked `EMPTY_OK` (matches that handoff's open follow-up item)
- Phase 6 NBA `FAILED` count dropped 402 → 31

---

## User-reported bug #1 — pts → Ks on MLB Best Bets (SHIPPED)

**Bug:** MLB Best Bets page rendered prop lines as `"Over 4.5 pts"` instead of `"Over 4.5 Ks"`. Also `"5 pts"` for graded actuals.

**Root cause:** Three frontend code sites — `BetCard.tsx:23`, `TodayPicksTable.tsx:14`, `WeeklyHistory.tsx:127-128,157` — each had a duplicated `statLabel` map mapping `K → "k"` (lowercase). `WeeklyHistory.tsx:157` was a flat hardcoded `${pick.actual} pts`. Backend already provides correct `stat: "K"` per-pick (`BestBetsPick.stat` in `best-bets-types.ts:18`); the bug was purely frontend pluralization + casing.

**Fix:** Centralized `src/lib/stat-labels.ts` keyed on `pick.stat` with count-aware singular/plural. Three components updated. Build + tests + lint clean. Committed `9c253e4`, pushed.

---

## User-reported bug #2 — MLB Tonight calendar shows May 3 (DIAGNOSED, FIX QUEUED)

**Bug:** MLB Tonight page (`/mlb/`) shows "No leaderboard for this date" with date picker defaulting to Sunday May 3 2026 (today is Monday May 11). Going to previous dates shows nothing either.

**Root cause (5-agent investigation):**

1. **Calendar leakage:** MLB Tonight page calls `useGameCounts()` which fetches NBA-only `gs://nba-props-platform-api/v1/schedule/game-counts.json`. That JSON says `last_game_date: 2026-05-03` (NBA's last playoff game; `next_game_date: 2026-06-03` for Finals — 30-day gap). `useEffectiveDate` sees "today has no NBA games" → snaps MLB page to NBA's `lastGameDate` = May 3.
2. **History gap:** MLB pitcher history endpoint expects `mlb/pitchers/history/{date}.json`. Commit `950daaf2` (2026-05-05) introduced the history sidecar — files exist only for May 6-11 (6 days). Plus the calendar bug landing user on May 3 → 404 → "No leaderboard."
3. **Compounded:** Even if calendar were correct, manually navigating to May 1-5 still 404s because history files don't exist for that range. **Both must be fixed.**

**Why this happened (forensic):**
- Commit `577756e` (props-web, 2026-04-13 19:20) replaced "MLB Coming Soon" placeholder with real `MlbTonightPanel`. Hooks `useGameCounts`/`useEffectiveDate` were inherited from Feb 13 NBA-only era. Latent bug until NBA games stopped (~May 3).
- Commit `44f05dc` (props-web, 2026-05-04) **explicitly diagnosed the date-snap bug in its commit body** and deferred: *"Past-date navigation on MLB is a separate, deeper architectural gap... Tracked separately."* User reported it 7 days later.
- Same-day Feb 13 commits `68d8b42` (frontend `fetchGameCounts`) + `f5b17094` (backend `season_game_counts_exporter.py`) landed 12 minutes apart; the path contract `schedule/game-counts.json` had no sport segment, baking NBA-implicit into the contract.

**Why no alert fired:** 14 monitors exist; **zero would have caught this**. Same monitoring-gap pattern as the May 8-11 Vercel 3-day-stale build incident. `stuck-loading-watchdog.ts:37` IS firing Sentry warnings tagged `stuck_loading: tonight:mlb` for every affected user — **nobody routes Sentry to Slack**. Highest-information-density telemetry, zero output. `e2e/sport-render.spec.ts:25,60` accepts `/no leaderboard/i` as a passing render state — bug **passes its own test**. `props-web` has no `.github/` directory: zero CI gates exist.

**Fix queued in Phase 1 of `docs/08-projects/current/sport-leakage-elimination/PLAN.md`:**

1. Sport-gate `useGameCounts({ sport })` AND short-circuit `useEffectiveDate` when `sport !== "nba"` (1h)
2. Backfill MLB pitcher history Mar 27/28 → May 5 (~90 min) — extract `_write_history_only(game_date)` helper on `mlb_pitcher_exporter.py:106-110`
3. Sentry alert rule → Slack `#nba-alerts` filter `tag.stuck_loading CONTAINS ":mlb"` (NOT `STARTS_WITH "mlb-"` — fresh reviewer caught this tag schema mismatch)
4. One-line spec fix removing `/no leaderboard/i` from `e2e/sport-render.spec.ts:25,60`
5. GitHub Actions CI gate (moved forward from Phase 4) — without this every Phase 2 PR re-introduces the leak
6. 10-line `gsutil stat` freshness check in `daily_health_check/main.py`

---

## The bigger problem — sport-leakage as a class

**14+ confirmed bugs of the same root cause class.** Predicted next user-visible bugs:

| Route | Bug | Reviewer evidence |
|-------|-----|-------------------|
| `/mlb/results` | **4 compounded leaks:** `useGameCounts` (date snap), `fetchResultsByDate` (NBA picks/grading), `fetchSystemPerformance` (NBA stats), `fetchYesterdayBestBets` (NBA recap) | High — fully broken when MLB results JSON ships |
| `/mlb/*` Header SearchBar | `fetchPlayerIndex` returns NBA players only. "judge" → no results; "lebron" → opens NBA modal from MLB context | High — affects every MLB page |
| `/mlb/players?player=X` | `fetchPlayerProfile` 404s on every MLB player | High |
| `/mlb/` Tonight | `useNewsIndicators` (literal `player-news/nba/`), `useLiveUpdates` (wasted NBA polls), `useChallengeGrading` (MLB challenges graded with NBA scores) | Silent bugs |

**Structural diagnosis (architecture audit):** Three missing abstractions —
1. No sport-aware fetch layer (every `fetchX()` in `src/lib/api.ts` hardcodes NBA paths; only `fetchBestBetsAll(sport)` in `best-bets-api.ts:14` is correct — and that's an accident of file split when MLB Best Bets shipped, not an intentional pattern)
2. `SPORT_META` is anemic (display fields only — no `apiPathPrefix`, capability flags, dateLockBehavior)
3. No GCS-path symmetry contract (NBA bare paths `v1/schedule/`, `v1/players/` etc. vs MLB `v1/mlb/*` — nothing enforces symmetry)

**Sport-Routing Rules in `props-web/CLAUDE.md` lines 44-92 already existed and were ignored.** Rules advisory, no enforcement. That's the root process gap.

**Full plan:** `docs/08-projects/current/sport-leakage-elimination/PLAN.md` (4 phases, 3-4 weeks active dev time).

---

## MLB improvement plan v2 (synthesis of 23 + 8 + 1 = 32 agents)

Yesterday's 3-agent investigation produced a tiered plan; today's deeper 15-agent investigation + 8 reviewers + 1 fresh-eyes review **corrected 8 specific claims in v1** and re-prioritized aggressively. Headline finding: **the MLB system is operationally underbuilt, not algorithmically deficient** — 7 of 15 agents independently surfaced fully-built-but-never-deployed plumbing.

**Critical corrections to v1 plan:**

| v1 claim | Reviewer finding |
|----------|------------------|
| "Wire 11 dead features (~1 day)" | 5 of 11 are **abandoned by design** (retired BDL sources); the others decompose into 30min-4h fixes |
| "Add `book_disagree_over`" | **Direction REVERSED in MLB.** UNDER works (71.4% HR), OVER fails (45.7%) |
| "LightGBM unlocks cross-model signals" | **Myth.** `combo_3way` + `book_disagreement` are single-model. MLB has zero cross-model infra |
| "Bottom-up K from batter props" | **Dead end.** Odds API `batter_strikeouts` market extinct since Sep 2024 |
| Tier 1 #1 mid-archetype filter "N=7, 14.3% HR" | Numbers **unreproducible** (`f05_season_k_per_9` is 100% NULL in production). OOS effect is 3-5pp not 36pp |
| Tier 1 #2 f28 umpire "30 min" | **Real fix is ~1 day** — SELECT references columns that don't exist on target table |
| `ballpark_k_factor` "verify in vector" | Already verified in 36-feature contract at `catboost_v2_regressor_predictor.py:34` — drop from plan |
| `chase_rate_over` "demote to shadow" | Already shadow at `registry.py:172` — only `high_csw_over` needs demotion |

**Critical missing item the v1 plan didn't include:**
- **MLB edge-based auto-halt** — port `regime_context.py` to MLB. Without this, every new pick-volume-increasing signal is uncovered risk. NBA paid for this lesson with 25.6% of season profit in March (Sessions 514-515).

**Statistical reality check:** Family-wise error rate from 15 parallel hypothesis families at α=0.05 ≈ **54%** — at least one finding is statistically expected to be a false positive. Hard rule from Reviewer 1: **No new MLB filter ships at N<100. No new MLB signal graduates from shadow at Wilson lower bound <55%.**

**Full plan:** `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md` (6-PR sequence, plumbing first, structural retrains last).

---

## Where to pick up (next session, in order)

### Today (Phase 1 of sport-leakage plan, ~1.5-2 days)

1. **Verify Vercel build for `9c253e4`** (props-web pts→Ks commit) actually deployed. `gh api repos/najicham/props-platform-web/commits/9c253e4/status` was `pending` at push time
2. Backfill verification: `SELECT MIN(game_date) FROM mlb_predictions.pitcher_strikeouts` (sets real backfill start, plan guessed Mar 28)
3. Sport-gate `useGameCounts({ sport })` + `useEffectiveDate` (BOTH layers)
4. One-line `e2e/sport-render.spec.ts:25,60` regex fix
5. GitHub Actions CI gate `.github/workflows/e2e.yml`
6. MLB pitcher history backfill (`_write_history_only` helper)
7. Sentry alert rule wired to Slack `#nba-alerts` — filter `tag.stuck_loading CONTAINS ":mlb"` (NOT `STARTS_WITH "mlb-"`)
8. `gsutil stat` freshness check in `daily_health_check/main.py`
9. Smoke check `/mlb`, `/mlb/results`, `/mlb/picks`

### This week (continue Phase 2 of sport-leakage plan)

- Expand `SPORT_META` with capability flags + `apiPathPrefix`
- Gate `[sport]/*` pages with capability checks
- **Split `api.ts` → `nba-api.ts` + `mlb-api.ts`** (reviewer-corrected approach — file split, not in-place mutation)
- Synthetic HTML check in `daily_health_check`

### Next week (Phase 3 backend symmetry, MLB plan PR 1)

- MLB calendar/schedule exporter (`mlb_season_game_counts_exporter.py`)
- MLB plan PR 1: training anchor (`train_regressor_v2.py:141`) + `high_csw_over` demotion + weekly-retrain CF (with TWO training caps) + **MLB edge-based auto-halt** + `is_home` silent bug fix

---

## Triage carry-forwards from earlier today

From `2026-05-11-PIPELINE-STATE-MLB-FOLLOWUP.md`:
- **~49 Phase 1 NBA preseason `FAILED` rows** (2025-10-21 → 2025-11-02). Need explicit sign-off before BQ DML. Tracked, not addressed this session
- **184 Phase 2 + 14 Phase 4 + 15 Phase 5 NBA `FAILED`** (real mid-season gaps Oct-Jan). Need cascading backfill, deferred

---

## Things NOT changed this session (intentionally)

- **The MLB Tonight calendar bug itself.** Diagnosed; fix queued in Phase 1 of sport-leakage plan. Wanted explicit sign-off before pushing a hook signature change that affects 3 pages
- **The MLB pitcher history backfill.** Diagnosed; fix queued (extract `_write_history_only`, run loop)
- **The MLB improvement plan.** Synthesis ready as a doc; no code changes pending user direction on PR sequence
- **The 5 incident-review agent outputs** (forensic, architecture, retention, monitoring, prevention). Findings captured in the two plan docs; raw outputs at `/tmp/claude-1001/-home-naji-code-nba-stats-scraper/.../tasks/` (transient)

---

## Open questions for next session

1. **Should the calendar fix (Phase 1.2) + pts→Ks fix bundle in one PR?** Pts→Ks already shipped (commit `9c253e4`). Next props-web PR can be the hook change alone.
2. **MLB history backfill range?** First MLB game date in `mlb_predictions.pitcher_strikeouts` determines actual count. Reviewer flagged "39 days Mar 28 → May 5" as suspect.
3. **MLB plan PR sequencing — start with PR 1 (anchor + demote + retrain CF + auto-halt) or with something smaller?** Reviewer 3 ranks training anchor #1 by EV/cost.
4. **Approval to wire Sentry → Slack alert** (zero code, Sentry console only)? Highest-leverage 30-minute fix in the entire plan per Reviewer 4.

---

## Files touched this session

**Frontend (`/home/naji/code/props-web`):**
- `src/lib/stat-labels.ts` (NEW, committed)
- `src/lib/stat-labels.test.ts` (NEW, committed)
- `src/components/best-bets/BetCard.tsx` (committed)
- `src/components/best-bets/TodayPicksTable.tsx` (committed)
- `src/components/best-bets/WeeklyHistory.tsx` (committed)

**Backend (`/home/naji/code/nba-stats-scraper`):**
- `docs/08-projects/current/sport-leakage-elimination/PLAN.md` (NEW)
- `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md` (NEW)
- `docs/09-handoff/2026-05-11-EVENING-SPORT-LEAKAGE-MLB-IMPROVEMENT.md` (NEW — this doc)
