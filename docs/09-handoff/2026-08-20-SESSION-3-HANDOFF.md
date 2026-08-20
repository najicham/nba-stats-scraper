# Session Handoff — 2026-08-20 — plan, todo list, and what landed

**Branch:** `main`, **pushed and deployed.** **Opener: Tue 20 Oct 2026 (61 days).**

Previous: `2026-08-19-SESSION-2-HANDOFF.md`. Game plan:
`docs/08-projects/current/2026-27-season-prep/00-GAMEPLAN.md`.

---

## TL;DR

The 8-commit batch is pushed and every service is verified serving it. Deploying it
exposed a deploy-integrity bug that mattered more than the batch: **six Cloud Functions
reported green builds while silently serving old code.** That is fixed, tested, and
proven in live CI.

`halt-state-writer` — the one caller of the rewritten auto-halt that has no build
trigger — was confirmed to still be running the OLD always-firing logic, and is now
deployed and verified.

The last open P0 (health multipliers) was **measured, not fixed**: it is provably inert,
0 of 3,855 rows, never applied once.

---

## 1. What landed this session

| Commit | What |
|---|---|
| `2b190789` (pushed) | The 8-commit off-season batch — auto-halt rewrite, worker filters, test gate, break-even, scheduler catalog |
| `13cc1c3d` | Deploy integrity: serving-revision assertion, quota-aware retry, MLB test gates, pipeline-state CFs registered |
| *(manual)* | `halt-state-writer` deployed with the new `shared/config/edge_halt.py` |

### 1.1 The push itself

Verified before pushing rather than trusting the prior handoff: the test gate reproduced
in a clean venv on exactly its three pins (295 tests, 2.5s), no dangling references to
the four removed worker filters, no `NameError` from the deleted `season_avg`/`l5_avg`
(both survive only in other functions), all 20 changed `.py` compile, 28/28 pre-commit
hooks pass.

**The gate worked.** It ran and passed in every build, including ones that later failed
at the deploy step. It has never yet gone red for an unrelated reason.

### 1.2 The real finding — a green build is not a deployment

A push touching `shared/config/**` matches the `includedFiles` of ~20 of the 36 triggers.
They all build and create Cloud Run revisions at once, against **93 services already in
us-west2**, and the region's `total allowable CPU` ceiling is hit partway through. Eight
deploys failed.

Two failed loudly (`nba-grading-service`, `nba-phase2-raw-processors`) and were retried
by hand. **Six did not:** `bias-decay-monitor`, `daily-health-check`, `live-export`,
`phase6-export`, `pipeline-health-summary`, `self-heal-predictions`. Each reported a
SUCCESSFUL build — `gcloud functions deploy` exited 0 — while the revision it created
died with `HealthCheckContainerError: Quota exceeded`. All six kept serving old code.

They were caught by comparing `latestReadyRevisionName` to `latestCreatedRevisionName`,
then redeployed two at a time. All recovered.

Fixes in `13cc1c3d`, all verified in live CI:
- **Serving-revision assertion** after traffic routing on both build paths. Confirmed in
  a real build: `OK: nba-grading-service serving nba-grading-service-00109-bnb`.
- **Quota-aware retry**, 3 attempts / 90s / 180s. Retries **only** on `Quota exceeded`;
  any other failure exits immediately rather than burning attempts on a code error.
  Verified against four stubbed scenarios.
- **Test gate added to both MLB configs** — they watch `ml/**` and had none.

### 1.3 halt-state-writer — the fix was only two-thirds live

The rewritten auto-halt has three callers. `halt_state_writer` has **no Cloud Build
trigger** (verified against all 36) and was **not** in `bin/deploy-function.sh`, so
nothing deployed it. Its deployed source zip was downloaded and confirmed to still carry
the old inlined `avg_edge < 5.0 AND pct_5plus < 50.0` logic — the rule that fires on
865/865 days.

Deploying it during off-season is safe and was reasoned through before acting:
`evaluate_halt_state` checks `off_season` **first** and short-circuits, so
`_nba_edge_collapse` never runs until games return. Confirmed live — invoked it and got
`halt_active=true, reason=off_season`, byte-identical behavior, HTTP 200.

All four pipeline-state CFs (`halt-state-writer`, `expected-outputs-planner`,
`phase-completion-reconciler`, `gap-detector`) are now registered in
`bin/deploy-function.sh`, which also gained per-function service-account support — they
each run under their own SA and would otherwise have silently deployed under
`processor-sa`.

### 1.4 Health multipliers — MEASURED (this is a result, not a fix)

`get_signal_health_summary` queries `signal_health_daily WHERE game_date = @target_date`.
Over 2025-10-01 → 2026-05-01:

```
rows available ON the game date (lag <= 0):     0
rows written AFTER the game date (lag >= 1): 3855
minimum lag observed:                        1 day
```

**Zero of 3,855.** The lookup returns empty every single time, so `_health_multiplier()`
fails open to `1.0` for every signal on every pick. The documented behavior — COLD
behavioral → 0.5x, COLD model-dependent → 0.0x, HOT → 1.2x — **has never applied once in
production.** CLAUDE.md and the memory index both describe it as active; both are wrong.

This does **not** decide the fork. The game plan's caution stands: independent analysis
suggests HOT may be *anti*-predictive on a leak-free lag-1 basis, so fixing the read
could make things worse. What changed is that the premise is now measured.

### 1.5 Corrections to standing docs

Verified against all 36 live triggers:
- **`weekly-retrain` DOES auto-deploy.** `deploy-weekly-retrain` watches
  `orchestration/cloud_functions/weekly_retrain/**,shared/**`; today's push deployed it
  (`BUILD_COMMIT=2b19078`). CLAUDE.md claimed the opposite. Its scheduler is still
  deleted (absent from all 110 snapshot jobs), so it remains current-but-never-fired.
- **`cloudbuild-precompute.yaml` is orphaned** — no trigger uses it, so the test gate
  added there is dead weight.

---

## 2. TODO — ordered

### P0 — before opening night

- [ ] **1. Confirm the 17 unverified scheduler jobs, then run Wave A.**
  Still the critical path and still needs a human: 3 `needs_input` (the phase3/phase4
  "5 processors" bodies) and 14 `verified: false` (mostly coordinator `/start` body keys
  and the `nba-props-*` workflow body key). Then
  `./scripts/nba_offseason_restore_jobs.py --wave A --apply` (creates paused).
  *Next session can reduce this list by deriving bodies from the CF code that parses
  them — worth doing before asking.*

- [ ] **2. Health multipliers: decide the fork.** The read bug is now measured (§1.4).
  Remaining work is the lag-1 predictiveness test — does HOT actually outperform on the
  *next* day? Then either fix the read to use the most recent available row, or delete
  the mechanism. Do not leave it documented-as-active and inert.

- [ ] **3. Restore `weekly-retrain-trigger`.** The function is current and correct; only
  the scheduler is missing. This was the 2025-26 root cause.

- [ ] **4. Drawdown tolerance** — owner decision 4, still open.

### P1 — high value, not blocking

- [ ] **5. REB/AST backfill.** Approved (decision 3); code change not yet made.
  ~15-25 lines in `backfill_jobs/scrapers/bp_props/bp_props_scraper_backfill.py`;
  ~12-14h, ~37k calls.
- [ ] **6. props-web PR #4** — verify CI green, merge.
- [ ] **7. Purge the observation-filter backlog.** Six have zero rows ever;
  `opponent_under_block` looks *wrongly* demoted (CF 37.5% = correctly blocking losers)
  and is a re-promotion candidate.
- [ ] **8. Filter auto-demote rule** — replace the 7-consecutive-day requirement with a
  cumulative Wilson lower-bound rule (~20 lines).

### P2 — hygiene

- [ ] **9. Reduce the deploy fan-out.** The retry treats the symptom. 93 services in one
  region is the cause, and several are dead: `analytics-processor` (image gone since
  2026-01-27), `nba-reference-service`, `prediction-coordinator-dev` (both Retired
  2026-04-04). Deleting dead services frees quota. **Needs owner sign-off — deletion.**
- [ ] **10. Delete or wire up `cloudbuild-precompute.yaml`** (orphaned).
- [ ] **11. Watch `halt_state` continuity.** No rows exist for 2026-08-16..19 — four
  consecutive days — and the scheduler showed `status.code: 13` (INTERNAL) on 08-19. It
  self-resolved (08-20 wrote normally; live job reports a clean last attempt). Harmless
  off-season, but in-season a missing `halt_state` row affects what Phase 6 publishes.
  First real test of the newly deployed code is the 09:00 UTC run on 2026-08-21.

---

## 3. Notes for whoever is next

- **Verify deploys by serving revision, not build status.** This is the session's main
  lesson:
  ```
  gcloud run services list --project=nba-props-platform --region=us-west2 \
    --format="value(metadata.name,status.latestReadyRevisionName,status.latestCreatedRevisionName)" \
    | awk -F'\t' '$2!=$3 {print "STALE: "$0}'
  ```
  Known permanent strays: `analytics-processor`, `nba-reference-service`,
  `prediction-coordinator-dev`.
- `SHORT_SHA` and `TRIGGER_NAME` come back **blank for completed builds**. Filter by
  `createTime`, not by SHA, or you will misattribute a build to the wrong commit — this
  cost a wrong diagnosis mid-session (an old commit's 600s timeouts were briefly read as
  belonging to this push).
- `signal_health_daily` **requires a partition filter** on `game_date`.
- `halt_state` columns are `written_at` / `source` / `actor` — there is no `updated_at`.
- `bq` CLI hangs here; use the Python BQ client. Per-job `gcloud scheduler jobs describe`
  works even though `list` hangs.
- When stubbing a shell retry loop for tests, remember `OUT=$(cmd)` runs in a subshell —
  a counter incremented inside the stub will not persist. Use a file.

*Session 2026-08-20.*
