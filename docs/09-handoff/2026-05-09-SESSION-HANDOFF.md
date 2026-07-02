# Session Handoff — 2026-05-09

**Status at start of next session:** NBA halted (correct). MLB healthy. Major infra cleanup landed today (IAM, MLB schedule lookahead, drift tooling, frontend memory layer). **3 user-reported frontend bugs surfaced at end of session — diagnosed but not fixed.** Best Bets page reportedly stuck on loading graphic; Season-concluded banner won't stay dismissed; Top Scorers grid spacing off.

---

## What shipped this session

### Backend (commits 5125108f, 1e572ec7, both pushed; 8 services auto-redeployed clean)

**Critical infra (production-affecting):**
- **MLB schedule lookahead fixed** — `MlbScheduleScraper` defaults to a 7-day window when no dates provided. Verified: 8 days / 107 games now in `mlb_raw.mlb_schedule`. Tomorrow's MLB predictions unblocked. (`scrapers/mlb/mlbstatsapi/mlb_schedule.py`, manually deployed via `./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`.)
- **IAM cleanup** — added compute SA invoker bindings to `scraper-gap-backfiller` (was zero, silently failing despite ENABLED scheduler), `weekly-retrain` (pre-Oct landmine), all 3 MLB processors. Removed `allUsers` from `mlb-phase3-analytics-processors`, `mlb-phase4-precompute-processors`, `slack-reminder`.
- **TONIGHT_GUARD_ENABLED=true** set explicitly on `live-export` + `post-grading-export` (was relying on code default).
- **Orphan model deactivated** — `xgb_v12_noveg_train0103_0228` was enabled but generating zero predictions; cascaded via `bin/deactivate_model.py`.

**Drift / monitoring tooling (all in 1e572ec7):**
- `bin/check-deployment-drift.sh` — narrowed `validation-runner` watched paths from `shared` → `shared/validation` to match the actual Cloud Build trigger. Eliminates the recurring false-positive.
- `bin/monitoring/verify-env-vars-preserved.sh` — added `--gen2` flag and `.serviceConfig.environmentVariables` jq path so Gen2 Cloud Functions stop returning false-positive CRITICAL.
- `.pre-commit-hooks/validate_auto_deploy_consistency.py` — treat any `shared/...` subpath as supplementary (not just bare `shared`); needed to support the drift-script narrowing above.
- `.claude/skills/validate-daily/SKILL.md` Phase 0.675 detector — code-2 (UNKNOWN) + recent successful attempt now classified as PASS.
- `.claude/skills/best-bets-config/SKILL.md` — dropped `familiar_matchup` (removed Session 494), marked `bench_under` as observation (Session 419).
- `ml/signals/pipeline_merger.py` — `ALGORITHM_VERSION` bumped to `v522_over_floor_6_regime_adaptive`.
- `ml/signals/aggregator.py` — OVER edge floor log message corrected ("5.0 base" → "6.0 base"; the actual code already uses 6.0).

### Frontend (props-web commit 7027c33)

- **`props-web/CLAUDE.md`** (new, ~160 lines) — first frontend memory file. Sections: Mission, Backend Contract, **Halt-Mode Behavior**, **Sport-Routing Rules**, Common Pitfalls. Promotes content from `.claude/claude_project_instructions.md` and adds the cross-repo cognitive link that the April 2026 /mlb regression exposed.
- **`props-web/e2e/sport-render.spec.ts`** (new, F1) — Playwright spec asserting per-sport render within 10s, plus a halt-regime mock (empty gameCounts) that reproduces the April incident. **Runs only against localhost today** — see Task #24 to wire to prod.

### Backend docs

- `docs/02-operations/runbooks/halt-mode-frontend-impact.md` (new, F3 backend half) — operator checklist for backend changes that publish empty/halt-mode JSON. Cross-links to `props-web/CLAUDE.md`.

---

## Live production issues — user-reported, diagnosed today, NOT yet fixed

### Issue A — Best Bets page stuck on loading graphic (Task #22, #23)

**User report:** Click Best Bets, never finishes loading. User suspected our cost-cutting changes hurt it.

**Diagnosis (read-only):**
- Backend payload `gs://nba-props-platform-api/v1/best-bets/all.json` is STALE — last modified `2026-04-18T21:01:07Z` (21 days ago). Payload is well-formed (`weeks: 14`, `today: 0`, `total_picks: 190`).
- Public proxy `https://playerprops.io/api/proxy/best-bets/all.json` returns HTTP 200 in 226ms with that same valid-but-stale payload.
- `https://playerprops.io/nba/best-bets` direct GET returns SSR'd skeleton with 8 `animate-pulse` containers — expected for a `"use client"` page before hydration.
- Page logic at `props-web/src/app/[sport]/best-bets/page.tsx:46-75` cleanly resolves loading: `setLoading(false)` is in `finally`. With empty `today`, branch at lines 302-321 renders the "Today's picks aren't out yet" message rather than a perpetual skeleton.
- **NOT the same bug class as the April /mlb incident** — Best Bets page contains no cross-sport state. `useSport` derives from URL only.
- None of today's IAM/cost-cutting changes touched `phase6-export` permissions on the GCS bucket nor the proxy route.

**Most likely cause:** Stale Vercel edge cache or stale Service Worker bundle on the user's browser. Stuck on hydration before it can complete.

**Underlying root cause:** Phase 6 publisher stops rewriting `best-bets/all.json` during halt because picks=[]. The 21-day-old payload's `data.date = "2026-04-18"` triggers a misleading "Today's picks aren't out yet — check back around 2 PM ET" copy instead of an explicit "Off-season" / "Halt active" treatment.

**Action plan (Task #22 + #23):**
1. **First:** ask user to hard-refresh (Cmd-Shift-R). 80% likely this fixes it for them.
2. If reproducible across browsers/users, fix the Phase 6 publisher to regenerate `best-bets/all.json` daily even when picks=[], and add `halt_active: true` + `halt_reason` fields. Update the page to render an explicit halt treatment when those fields are present.

### Issue B — Season-concluded banner reappears after dismiss (Task #28)

**User report:** Banner shows on NBA. Click X to dismiss. Change date. Banner returns. Annoying. Want it dismissed-and-stay-dismissed (per session, or until refresh).

**Diagnosis:**
- File: `props-web/src/components/ui/BackendStatusIndicator.tsx`, lines 643–675 (state + effect), 689–692 (dismiss handler).
- `isDismissed` is plain `useState` — local to one mount, no persistence.
- The reappearance is NOT caused by re-mounting (page wrapper is stable).
- Real culprit: `bannerKey` recomputes in **Mode 3** (the stale-`gameDate` fallback). When user picks a different date → `tonightData?.game_date` changes → `gameDate` prop changes → `bannerKey = ${sport}-fallback-${gameDate}` changes → `useEffect` at line 671 fires `setIsDismissed(false)`.

**Recommended fix (Task #28, ~30min):**
1. Init `isDismissed` from `sessionStorage.getItem(`bb-dismiss:${bannerKey}`) === "1"` (lazy useState initializer, SSR-guarded).
2. On dismiss click, also `sessionStorage.setItem(`bb-dismiss:${bannerKey}`, "1")`.
3. Drop the `dismissedKey` state machine entirely — sessionStorage is now the source of truth.
4. Result: survives in-tab navigation (including date changes), resets on tab close/refresh, per-banner-content (so a genuine new break still surfaces).

### Issue C — NBA Top Scorers grid spacing off (Task #29)

**User report:** Click Top Scorers tab on NBA → grid spacing looks wrong.

**Diagnosis:**
- File: `props-web/src/app/[sport]/page.tsx:626-649` (Top Scorers + Favorites — uses `VirtualizedGrid`); compare to lines 601-616 (By-Game — uses Tailwind grid).
- **Inconsistency between two grid renderers:**
  - **By-Game:** `grid grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-2` — flips to multi-column at the `sm:` breakpoint (640px).
  - **Top Scorers:** `VirtualizedGrid` with `minItemWidth=340, gap=8` — uses `Math.floor((width + gap) / (minItemWidth + gap))`. At viewports 640-679px, math yields 1 column while By-Game shows 2.
- Additionally: when item count >50, `VirtualizedGrid` adds inline `overflow: auto` + `height: min(calc(100vh - 200px), ...)` which introduces an internal scrollbar (~15px) that further shrinks the measured width.

**Recommended fix (Task #29, ~30min):**
- Smallest CSS-only change: `props-web/src/components/ui/VirtualizedGrid.tsx:77` — change `minmax(${minItemWidth}px, 1fr)` to `minmax(min(100%, ${minItemWidth}px), 1fr)` so single-card rows fill the row instead of leaving trailing whitespace.
- Or (cleaner): replace `VirtualizedGrid` here with the same Tailwind grid By-Game uses; lists rarely exceed a few hundred items, so no need to virtualize.

### Issue D — Monitoring/visibility gap (the meta-question)

**User asked:** "Do we have monitoring in place so we get a proactive alert if this ever happens again? Do we have good visibility tools so we can see if there are any issues easily?"

**Honest answer: NO, not for this class of bug.** Backend health checks pass (services up, GCS payloads exist) → don't catch frontend rendering failures. The April /mlb regression slipped through for 5 days the same way.

**What exists today:**
- `daily_health_check` CF (8 AM ET) — checks Cloud Run `/health`, GCS payload freshness, Phase completion. **Does NOT fetch any rendered page.**
- Vercel cron `/api/cron/health-check` (daily 2:30 PM ET) — `checkSiteHealth()` fetches `https://playerprops.io` root for HTTP 200 only. **Does not look at the response body. Does not check Best Bets, Tonight, or any per-sport route.**
- Sentry — `Failed to fetch` and `ChunkLoadError` are explicitly suppressed in `ignoreErrors`. **Exactly the silent-failure modes that produce a stuck spinner.**
- F1 Playwright spec — runs against `localhost:3000` only. **Not executed against production URLs.**

**Top 5 monitoring additions (in priority order — see Tasks #9, #25, #26, #27, #28):**

| Pri | Item | Effort | Why |
|---|---|---|---|
| 1 | **F2: Synthetic HTML check** in `daily_health_check` CF (already pending as Task #9) — `RENDERED_PAGE_CHECKS` map: URL → required + forbidden substrings. | ~3h | Only mechanism that catches "200 OK + broken page." Designed in 2026-05-04 doc. Single deploy. |
| 2 | **Extend `checkSiteHealth`** to per-route + body assertion. (Task #24) | ~1h | Cheapest 2nd layer. Lives in same repo as the routes so it stays in sync. Cuts MTTD from 24h → 30min via Vercel cron. |
| 3 | **Run F1 Playwright spec in CI vs prod URL.** (Task #25) | ~2h | F1 work shipped today is currently dormant against prod. Activates it; catches at deploy time. |
| 4 | **Fix Sentry** — un-suppress fetch failures, add stuck-loading custom event. (Task #26) | ~1.5h | Real-user telemetry: catches regressions that only manifest in specific browsers/regions/edge caches. |
| 5 | **GCP uptime check** on `/nba/best-bets` and `/mlb` with content-match. (Task #27) | ~30min | Independent belt-and-suspenders; survives Vercel/own-code outages. |

**If picking ONE:** F2 (Task #9). Closes the exact failure mode of both the April /mlb outage AND today's Best Bets outage.

---

## Daily steering snapshot — 2026-05-09 09:34 PT

```
NBA: HALTED (playoffs, day ~42 of dormancy)
  All 7 NBA models: INSUFFICIENT_DATA (last data 2026-05-08, 0 picks/0 graded)
  Days since training: 35-36
  Edge-based auto-halt: still ACTIVE

MLB: HEALTHY, regime LOOSE today (was NORMAL yesterday)
  League macro 7d: vegas MAE 2.02, model MAE 1.73 (model AHEAD by 0.29)
                   model HR 53.5%, BB HR 66.7%, regime LOOSE
  Best bets:
    Last 7d:    14-7   (66.7%)  N=21
    Days 8-14:   8-8   (50.0%)  N=16
    Days 15-30: 10-8   (55.6%)  N=18
  Signal health: HOT — projection_agrees_over (100%, 3/3),
                       k_trending_over (83.3%, 5/6),
                       elite_peripherals_over (75%, 6/8),
                       pitcher_on_roll_over (75%, 12/16),
                       recent_k_above_line (68.4%, 13/19)
  WATCH/COLD: pitch_efficiency_depth_over RECOVERED to 50% 7d (was 25%)
  Yesterday's MLB BB: 3-1 (75% HR), 1 ungraded (kumar_rocker — see Task #10)

DEPLOYMENT DRIFT: 16 services checked, no real drift
  ✓ 14 services up to date
  ⚠️ validation-runner: false-positive (alerter bug fixed today)
  ⚠️ nba-phase2-raw-processors, nba-admin-dashboard: probe issue (timestamp unreadable)
  Model registry: ✓ matches manifest. Traffic: ✓ all on latest revisions.

Status: ALL CLEAR for MLB betting today.
```

---

## What the next session should do — explicit checklist

### 1. Address user-facing frontend bugs (urgent — they're staring at a broken page)
- [ ] **Task #22** — First: confirm Best Bets stuck-loading reproduces. If yes after hard-refresh, do **Task #23** (regenerate `best-bets/all.json` daily during halt + add `halt_active` field).
- [ ] **Task #28** — Banner sessionStorage persistence (~30min, smallest fix; biggest UX win).
- [ ] **Task #29** — Top Scorers grid: 1-line CSS change in `VirtualizedGrid.tsx:77` (~5min) OR full replacement with Tailwind grid (~30min).

### 2. Stand up real frontend monitoring (so this doesn't recur)
- [ ] **Task #9 (F2)** — Synthetic HTML check in `daily_health_check`. Single highest-leverage fix.
- [ ] **Task #24** — Per-route body assertion in `checkSiteHealth` (~1h).
- [ ] **Task #25** — Wire F1 Playwright to prod (~2h).
- [ ] **Task #26** — Sentry un-suppress + stuck-loading event (~1.5h).
- [ ] **Task #27** — GCP uptime checks (~30min).

### 3. Carry-forwards
- [ ] **Task #4** — Browser-test /mlb date picker (now testable cross-date with 4 history files).
- [ ] **Task #10** — Confirm kumar_rocker grading resolves on next cycle.

### 4. Phase 3 scheduler decision (carried from 2026-05-03)
- 4 Phase 3 schedulers remain PAUSED. Decision needed pre-NBA-resume in October.

---

## Files touched this session

**Backend:**
- `scrapers/mlb/mlbstatsapi/mlb_schedule.py` — 7-day lookahead default, range-first URL precedence
- `bin/check-deployment-drift.sh` — narrowed validation-runner watched paths
- `bin/monitoring/verify-env-vars-preserved.sh` — Gen2 CF support
- `.pre-commit-hooks/validate_auto_deploy_consistency.py` — `shared/...` subpath classification
- `.claude/skills/best-bets-config/SKILL.md` — filter inventory refresh
- `.claude/skills/validate-daily/SKILL.md` — Phase 0.675 detector logic
- `ml/signals/aggregator.py` — OVER edge floor log message
- `ml/signals/pipeline_merger.py` — ALGORITHM_VERSION bump
- `docs/02-operations/runbooks/halt-mode-frontend-impact.md` — new
- `docs/09-handoff/2026-05-09-SESSION-HANDOFF.md` — this file

**Frontend:**
- `props-web/CLAUDE.md` — new
- `props-web/e2e/sport-render.spec.ts` — new

---

## Production state at end of session

- Backend: 2 commits pushed, 8 services redeployed cleanly (all SUCCESS)
- Frontend: 1 commit pushed (Vercel auto-deployed)
- IAM: 0 `allUsers` on shared infra (was 3); 0 silent-fail Cloud Run services (was 1)
- All 3 documented drift false-positives now produce correct verdicts
- Tonight content guard: ARMED with explicit env var (was relying on code default)
- MLB schedule: 8 days deep (was 1)
- **3 user-facing frontend bugs open — see Issues A/B/C above**
- **Frontend monitoring is inadequate — see Issue D**
