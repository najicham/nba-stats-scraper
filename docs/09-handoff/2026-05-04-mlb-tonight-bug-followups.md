# Session Handoff — MLB Tonight Page Bug + Followup Plan

**Date:** 2026-05-04
**Trigger:** User reported `/mlb` tonight page rendered nothing for ~5 days during NBA halt.
**Outcome:** Root cause found + 9-line fix shipped + 3-agent review produced a prioritized followup list.

---

## TL;DR

The `/mlb` page on playerprops.io was stuck on a NBA loading skeleton because the master loading guard at `src/app/[sport]/page.tsx:351` returned for any sport whenever `loading === true`. `loading` only flipped to `false` inside NBA's `loadData()`, which was gated on `dateSettled` — a guard that never resolved when NBA was halted (gameCounts feed empty). Bug shipped April 16-17 in a URL-routing refactor; surfaced ~April 28 when NBA halted.

**Fix shipped this session:** props-web commit `44f05dc` — skip NBA `loadData()` and the master loading guard when `sport === "mlb"`. Vercel auto-deployed (`dpl_2bqF4XzqydPf9wiv1fYcp5uFJjeU`). Verified `/mlb` HTML now contains "Tonight's Starters" + "All pitchers →" markers.

**Two architectural gaps remain:**
1. MLB leaderboard fetch ignores `selectedDate` — date selector doesn't change the panel.
2. Backend `mlb_pitcher_exporter.py:98-110` writes only a single latest pointer, no date-keyed history. So even if the frontend asked for yesterday, GCS would 404.

---

## What's done

| # | Item | Where |
|---|------|-------|
| 1 | Diagnosed the NBA loading-guard bug | This session, summary above |
| 2 | Shipped the 9-line fix | props-web `44f05dc`, deployed |
| 3 | Verified production HTML | `curl https://playerprops.io/mlb` returns "Tonight's Starters" |
| 4 | Three-agent review of recurrence prevention | Synthesized into followup table below |

---

## Followups — 3-agent synthesized recommendations

### P0 — ship in next session (~7h total)

| # | Item | Effort | Notes |
|---|------|--------|-------|
| **F1** | **Playwright sport-render spec** at `props-web/e2e/sport-render.spec.ts`. For each `["nba","mlb"]`, assert heading visible within 10s + no skeleton present. Mock empty gameCounts in one test to reproduce halt regime. Gate on PRs. | 30m–1h | Single most valuable item. Would have caught the bug on commit `e7b6923` two weeks ago. |
| **F2** | **Synthetic HTML check in `daily_health_check` CF.** Add `RENDERED_PAGE_CHECKS` map to `orchestration/cloud_functions/daily_health_check/main.py`. URL → required substrings (e.g. `https://playerprops.io/mlb` → `["Tonight's Starters", "All pitchers"]`). Same Slack route as existing GCS-freshness checks. | 3h | The only mechanism that would have detected this in production. HTTP 200 was always being returned. |
| **F3** | **Frontend CLAUDE.md + halt runbook.** Promote `props-web/.claude/claude_project_instructions.md` → `props-web/CLAUDE.md` with sections: BACKEND CONTRACT, HALT-MODE BEHAVIOR, sport-routing rules. Cross-link to new backend runbook `nba-stats-scraper/docs/02-operations/runbooks/halt-mode-frontend-impact.md` (4-line operator checklist). | 3h | Adds the missing cross-repo memory layer. Frontend repo currently has no CLAUDE.md / memory. |

### P1 — within the month (~7h total)

| # | Item | Effort | Notes |
|---|------|--------|-------|
| **F4** | **Sport-scoped loading state machine** in `src/app/[sport]/page.tsx:37`. Replace `useState(true)` with `"idle" \| "fetching" \| "ready" \| "error"` starting `idle`. Master skeleton only when `status === "fetching"`. Kills two bug classes: this incident + future "guard never resolves" bombs. | 4h | |
| **F5** | **Deadline on `useGameCounts` and `dateSettled`.** Add 8-second timeout in `src/hooks/useGameCounts.ts` that resolves with `degraded: true`. Page treats degraded as settled. No remote-data guard should wait forever on a user-facing route. | 1h | Pairs with F4. |
| **F6** | **Vercel deploy freshness alert.** GitHub Action daily: compare `git rev-parse HEAD` (props-web main) vs Vercel API deployed sha. Slack `#nba-alerts` if different and HEAD is >24h ahead. The 16-day stale build was its own signal. | 1.5h | Alert, NOT auto-redeploy — auto-redeploy hides the underlying "we forgot to deploy" issue. |
| **F7** | **Backend commit "Frontend impact:" trailer.** Pre-commit hook in `nba-stats-scraper/.pre-commit-hooks/`: when commit touches `regime_context.py`, `signal_best_bets_exporter.py`, or `data_processors/publishing/`, require a `Frontend impact:` line in the message. | 30m | Forces cross-repo cognitive link before change ships. |

### P2 — explicitly skipped / deferred

| # | Item | Verdict |
|---|------|---------|
| F8 | Sport-split route groups (`(nba)/page.tsx` + `(mlb)/page.tsx`) | DEFER until F4 lands and shape stabilizes. ~4h. |
| F9 | Sentry "stuck loading" custom transaction + replay sampling boost | DEFER. Mostly redundant with F2 synthetic check. Revisit if real-user reports come in. |
| F10 | Mixpanel `tonight_page_data_loaded` funnel | SKIP. Funnel = product analytics, not 30-min incident detection. Redundant with F2. |
| F11 | Cross-repo monorepo migration / shared schema package | SKIP. Too heavy for this failure mode. |
| F12 | Vercel daily forced rebuild cron | SKIP. Hides the underlying "code shipped but never deployed" problem. Alert (F6), don't auto-fix. |

### Recommended sequence
1. **Next session** — ship F1 + F3 (~3.5h). Prevention + docs in place.
2. **This week** — ship F2. Production detection.
3. **Next week** — F4 + F5 + F7. Code-path hardening.
4. **Within month** — F6.

If picking ONE: **F1 (Playwright sport-render spec)**. 30 minutes, runs on every PR.

---

## Architectural gap: yesterday navigation on MLB

Separate from the followup list. The MLB tonight panel ignores `selectedDate` (`src/app/[sport]/page.tsx:158-167` deps array `[sport]` only). Backend `mlb_pitcher_exporter.py:98-110` writes only `gs://nba-props-platform-api/v1/mlb/pitchers/leaderboard.json` — no date-keyed history.

**Fix is two-repo:**
- Backend: extend exporter to also write `mlb/pitchers/leaderboard/{date}.json` daily. ~2h.
- Frontend: in `[sport]/page.tsx` MLB effect, when `selectedDate !== today`, fetch the date-keyed file. Show "data not available" banner if 404. ~2h.

**Recommendation:** ship pre-NBA-resume in September alongside the broader off-season cleanup. Not urgent during NBA halt.

---

## Other in-flight items (carried from prior session 2026-05-03)

From `2026-05-03-mlb-tonight-bug-followups.md` predecessor + `2026-05-02-tonight-content-guard.md`:

- **Tonight content guard ARMED** — kill-switch removed from `live-export` + `post-grading-export`. Sentinel write verified end-to-end.
- **`same-day-phase3` scheduler RESUMED** — was the root cause of NBA tonight outage Apr 28+. Other Phase 3 schedulers (`evening-analytics-10pm-et`, `overnight-analytics-6am-et`, `same-day-phase3-tomorrow`, `evening-analytics-6pm-et`) remain PAUSED. **Decision needed pre-season.**
- **Generalize `validate_content`** to 5 other systemic exporters (`results_exporter`, `live_grading_exporter`, `system_performance_exporter`, `player_profile_exporter`, `tonight_trend_plays_exporter`, `whos_hot_cold_exporter`).
- **Frontend banner PR for `status: "degraded"`** — props-web tonight page falls through to empty state on degraded payloads. Add explicit banner.
- **MLB Tonight exporter** — still doesn't exist. Architectural decision pending.

---

## Where to start if you're a new session

1. Read this file.
2. Read `2026-05-02-tonight-content-guard.md` for the broader content-guard context.
3. Read `2026-05-02-SESSION-HANDOFF.md` for the cross-system audit.
4. Verify `/mlb` still renders: `curl -sS https://playerprops.io/mlb | grep -oE "Tonight.s Starters"`.
5. Pick F1 (~30m) — the Playwright sport-render spec — to land cheap prevention immediately.

---

## Files touched this session

- `props-web/src/app/[sport]/page.tsx` — 9-line fix, commit `44f05dc`, deployed
- `nba-stats-scraper/.claude/projects/-home-naji-code-nba-stats-scraper/memory/tonight-content-guard.md` — earlier in this conversation
- `nba-stats-scraper/.claude/projects/-home-naji-code-nba-stats-scraper/memory/MEMORY.md` — earlier in this conversation
- `nba-stats-scraper/docs/09-handoff/2026-05-04-mlb-tonight-bug-followups.md` — this file

## Production state at end of session

- `/mlb` renders correctly (verified curl)
- Backend MLB pitcher data: 15 starters in `leaderboard.json`, fresh
- Tonight content guard: ARMED, no degraded sentinel
- Phase 3 morning scheduler: ENABLED
- NBA: still halted (auto-halt active per `regime_context.py`)
- All other backend monitoring: nominal
