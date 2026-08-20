# Session Handoff — 2026-08-19 (evening) — entry point for the next session

**Branch:** `main`, 8 commits ahead of origin, **NOT PUSHED.** **Opener: Tue 20 Oct 2026 (62 days).**

Read this, then `docs/08-projects/current/2026-27-season-prep/00-GAMEPLAN.md` (now has a
STATUS block at the top).

---

## TL;DR

Four of the five owner decisions were taken and executed. Both P0 items that were
actionable are done. One new P0 was discovered and is **not fully fixable**: the GCS
backup the entire scheduler-restore plan depended on was silently deleted by a bucket
lifecycle rule.

**Nothing is pushed.** Pushing auto-deploys to ~20 services. That is the first decision
for the next session.

---

## 1. Owner decisions taken

| # | Decision | Chosen |
|---|---|---|
| 1 | Auto-halt variant | Median-per-player-game + hysteresis |
| 2 | Where you bet | **Four majors → break-even 52.4%** |
| 3 | REB/AST backfill | **GO** — code change not yet made |
| 5 | Backend deploy gate | Test gate in Cloud Build (not branch protection) |
| 4 | Drawdown tolerance | still open |

---

## 2. What shipped (8 commits, unpushed)

| Commit | What |
|---|---|
| `1dbf4a21` | **Auto-halt rewritten.** Fired on 865/865 days, never released |
| `5c18f3af` | Records that the halt's margin rests on contaminated prior seasons |
| `931a7e2a` | **Four panic-era worker filters removed** |
| `783516f1` | **Pre-deploy test gate** on all four NBA build configs + build timeout raise |
| `b6ae7924` | **One break-even**, wired to `shared/config/breakeven.py` |
| `8e7cdab3` | Scheduler snapshots in git + `bin/scheduler/backup_scheduler_jobs.sh` |
| `62477300` | Restore script + 59-job reconstructed catalog |
| *(docs)* | Manifest + game plan corrected |

### 2.1 Auto-halt — worse than reported, now fixed

Replayed against `player_prop_predictions`: the Session 515 halt fires on **865 of 865**
evaluable prediction-days across all five seasons — not 136/148 (91.9%). Every season
would have published zero picks. Release required exceeding values above the all-time
maximum, so a halt was permanent.

The same broken test was copied in **three** places. The third, in `weekly_retrain`,
gates whether **model governance is loosened** for a "season restart" — so every retrain
would have run with relaxed governance gates on a healthy market. It has not bitten only
because `weekly-retrain-trigger` is deleted.

New rule (`shared/config/edge_halt.py`, shared by all three callers):
`HALT median-per-player-game edge < 1.4 AND edge-3+ share < 10%`, release at `>= 1.6`
for 3 consecutive days. Replay: **0 FP / 931 healthy days, 57/57 anomaly days, exactly
one transition in five seasons.**

⚠️ **The conjunction is load-bearing.** In 2023-24 and 2024-25 the median alone dipped
below 1.4 on healthy days (1.367, 1.300); only the edge-3+ share kept the system live.
Never simplify this to the median.

⚠️ **The margin is thinner than it looks.** "0 of 843 prior-season days within 25% of
both thresholds, closest 28.8% clear" comes from backfilled rows that are leak-contaminated
(graded there, UNDER edge 5+ shows 72-86% vs a clean walk-forward 50-66%). On the one
clean live season the binding margin is **2.4%**. Do not tighten these thresholds.

### 2.2 Worker filters — one premise refuted

All four were added 3-11 Feb 2026 (commits dated 02-03, 02-04, 02-04, 02-11), inside the
panic week. Zero blocked rows exist before 2026-02-01. Realized blocked-pool HR, deduped:
`role_player_under_low_edge` 52.4% (N=635, exactly break-even), `hot_streak_under_risk`
50.3% (N=338), `star_under_bias_suspect` 43.7% (N=126), `stale_model_under_dampening`
66.7% (N=18, and dead code — gated on `catboost_v9`, not in the fleet).

`star_under_bias_suspect` moved to the aggregator as **observation**, not active: on the
leak-free walk-forward cache its exact slice (UNDER, edge ≥5, season avg ≥25) hit
**60.0 / 50.0 / 62.9 / 83.3 / 65.6%** — profitable in 4 of 5 seasons and better than
non-star UNDER in 3 of 5. Pre-registered gate in `shared/registry/filters.yaml`.

---

## 3. NEW P0 — the scheduler backup is gone

`gs://nba-bigquery-backups/scheduler-jobs-backup/scheduler_jobs_backup_2026-07-03.json`
**does not exist.** The bucket has a lifecycle rule deleting at age 30 days; the file aged
out ~2026-08-02. Oldest surviving object: 2026-07-21. No copy anywhere.

Audit-log recovery was attempted: admin logs reach 2025-07-21 (400d) and carry
schedule/timeZone/retryConfig, but **GCP redacts every target** — 315 payloads across 110
job names, zero with `httpTarget`/`pubsubTarget`. URI, headers, body, OIDC unrecoverable.

**Mitigation shipped:**
- `ops/scheduler-catalog-2026.yaml` — 59 jobs reconstructed, each tagged with provenance
  (`repo_script` 17 / `live_pattern` 11 / `manifest` 28 / `needs_input` 3). 42 verified.
- `scripts/nba_offseason_restore_jobs.py` — dry-run default, waves, idempotent, creates
  everything PAUSED, **refuses `needs_input` jobs** unless `--allow-unverified`.
- `bin/scheduler/backup_scheduler_jobs.sh` + `ops/scheduler-snapshots/` — snapshots in git,
  which has no TTL. Current state captured: 110 jobs, 75 ENABLED, 35 PAUSED.

**Count correction:** the manifest says 58 (A=19, B=18, C=21); its Wave B table has 19
rows. The real number is **59**.

**Still needs a human before resume:** 3 `needs_input` jobs (the phase3/phase4
"5 processors" bodies the manifest never named) and 14 `verified: false` jobs (mostly
coordinator `/start` body keys and the `nba-props-*` workflow body key).

---

## 4. What to do first

1. **Decide whether to push.** 8 commits, auto-deploys ~20 services. The system is
   off-season and halted, so blast radius is low, and the new test gate runs first.
2. **Confirm the 17 unverified job definitions**, then
   `./scripts/nba_offseason_restore_jobs.py --wave A --apply` (creates paused).
3. **REB/AST backfill** — approved, code change not yet made. ~15-25 lines in
   `backfill_jobs/scrapers/bp_props/bp_props_scraper_backfill.py`; ~12-14h, ~37k calls.
4. **Health multipliers** (game plan §2.2) — the last untouched P0. They have never applied
   in production. Measure before fixing: independent analysis suggests HOT may be
   *anti*-predictive on a lag-1 basis.
5. **props-web PR #4** — verify CI green, merge.
6. **Drawdown tolerance** — decision 4, still open.

---

## 5. Notes for whoever is next

- `bq` CLI hangs here; `gcloud scheduler jobs list` and `gcloud logging read` work but
  `logging read` over a wide window needs a background run (it times out at 2 min).
- Full-repo `pytest` is unusable — cross-suite pollution. Triage per-directory with
  `-p no:cacheprovider`. `tests/unit/signals` is green (295). `tests/unit/prediction_tests`
  has **17 pre-existing failures and 3 collection errors** that predate this session.
- The `check-date-comparisons` hook only accepts its suppression marker **on the same
  line** as the `<=`, not on a preceding comment line.
- Prior-season rows in `player_prop_predictions` are leak-contaminated too, not just
  `prediction_accuracy`. For any cross-season claim use `walkforward_sim_predictions`.

*Session 2026-08-19 evening. Previous: `2026-08-19-SESSION-HANDOFF.md`.*
