# Session Handoff — 2026-08-22 — auto-halt rebuilt, schedulers restored, batch deployed

**Opener: Tue 20 Oct 2026 (59 days). First realistic picks ~2026-11-15.**
Previous: `2026-08-21-SESSION-4-AUTO-HALT-REBUILD.md`.
Supersedes the draft `2026-08-22-SESSION-5-EXECUTION.md` (written mid-session; this is the final record).

---

## TL;DR

Owner decision 1 (rebuild the auto-halt) and decision 4 (drawdown halt) are both **done and
deployed**. The 59 deleted Cloud Scheduler jobs are **re-created, all paused** — the item
that had been the critical path since the backup was destroyed.

Twenty-two independent reviewers across three rounds found **2 blockers and ~35 majors**,
all fixed. The single most important result is not a fix, it is a measurement:

> **The edge-collapse metric never measured the market.** On any invariant basis the 2026
> "collapse" does not exist, and during the one real loss the metric was *anti-correlated*
> with the danger. It has been demoted from circuit breaker to degeneracy guard.

---

## 1. Read these first

| Doc | Why |
|---|---|
| `shared/config/edge_halt.py` docstring | The full evidence for the demotion. Read before touching any number. |
| `shared/config/drawdown_halt.py` docstring | The real circuit breaker + its honest limits, incl. a replay-methodology correction. |
| `docs/02-operations/runbooks/halt-mode-operations.md` | Rewritten. The old one described a fail-OPEN advisory label; it is now a fail-CLOSED gate. |
| `bin/validation/validate_guard_invariance.py` | Run before changing ANY guard threshold. |

## 2. What changed, and why it mattered

**The edge halt was demoted, not recalibrated.** Three careful, validated, owner-approved
attempts were all wrong. Evidence:

- Models spanning Jan→Feb 2026 read edge **UP** (2.04→2.70, 2.19→2.72, 1.94→2.75). February
  never collapsed — 42 new line-hugging `system_id`s appeared, 30 alive ≤5 days.
- On a fixed procedure (`wf_sim_v12noveg`, leak-free, 5 seasons) monthly median edge is
  0.728-0.999 with **Mar-2026 = 0.839, ABOVE 2022-03, 2023-01 and 2025-01**.
- Vegas MAE (model-free) 4.64-5.38 across five seasons; Feb/Mar/Apr 2026 = 5.05/5.04/5.39.
  **The market never compressed.**
- March was **over-publishing**: Mar 4-8 = 9/13/1/10/16 picks (season high), 03-08 went
  2-11, **13.3u lost in two days** against a prior season-max drawdown of 3.64u.

Now a degeneracy guard: 0.35 / 0.30% (**loosened**), family-keyed warm-up, symmetric
release, 14-day bounded lifetime, a symmetric **inflation** bound at 4.5, and a fail-closed
chain. `halt_state` now actually **gates** NBA picks — it never did; `halt_envelope()` was a
stamp in all three call sites.

**Decision 4 shipped.** `unit_drawdown` (6u soft / 10u hard) + `volume_anomaly`
(`>= max(10, 3x trailing-10-pick-day median)`, 3-day window). Counterfactual replay over
2025-26: **3 halt days, +13.27u avoided, 0.00u forgone, max drawdown 14.27u → 3.64u.**

## 3. What is LIVE right now

| Component | State |
|---|---|
| `halt-state-writer` | rev `-00010-woj`, `BUILD_COMMIT=9030f8e1`, Slack secret **mounted** |
| `phase6-export`, `post-grading-export` | `33ba93a` ✓ |
| `phase-completion-reconciler` | redeployed at HEAD (decorator fix) |
| `halt-state-stale` alert | **Critical**, threshold >30h OR absent-23h — applied live |
| Scheduler jobs | **110 → 169**; 59 created, ALL PAUSED; ENABLED unchanged at 74 |
| Today's `halt_state` | NBA `off_season`, `halt_active=true` ✓ |

⚠️ **STALE — must redeploy (quota killed 6 of ~36 triggers):**
- **`weekly-retrain`** (`2b19078`) — this batch changed its governance gate. Must land before Wave C.
- **`nba-scrapers`** (`2b19078`) — missing the `PlayerLinker` season fix; 15-min scheduler.
- `prediction-coordinator`, `decay-detection`, `nba-grading-alerts`, `mlb-prediction-worker` — stale but behaviourally harmless.

Retry off-peak, then `./bin/verify-deploy.sh`. They failed **loudly** — in August this same
quota exhaustion produced green builds serving old code.

## 4. THE TOP P0 — the roster registry, and it is not what we thought

`nba_reference.nba_players_registry` has **no 2026-27 rows** (max 2025-26, seeded
2025-10-04/05). `br-rosters-batch-daily` exists in no catalog and no snapshot.

**But the missing scheduler is not the root break.** The Phase 2 batch processor it fed
(`data_processors/raw/basketball_ref/br_roster_batch_processor.py`, Jan-2026 refactor) is
schema-misaligned with the real table and **has never successfully written**: it references
columns that don't exist, omits REQUIRED ones, puts a TIMESTAMP into a REQUIRED DATE, and
computes `season_year = start_year + 1` while the table, the path extractor and the
registry reader all use start-year (confirmed: `br_rosters_current` has `season_year=2025`
paired with `season_display='2025-26'`). **Restoring the scheduler without the code fix
restores a failing job.** BR data has been stale since ~2026-01-13 — three weeks *before*
the purge.

Also: **ESPN is the dominant registry source** (589/696 of 2025-26 rows; BR only 20), and
nothing publishes the `roster_scraped` trigger — the registry seed has always been a manual
act.

**Cannot be done now** — every processor tags season by `month >= 10`, so a scrape today
lands as 2025. **Seed window 2026-10-01 → 10-19, drop-dead ~2026-10-06.**

Blast radius on a miss: the prediction pipeline is **safe** (season-agnostic ID lookup), but
`streaks_exporter` goes empty league-wide, news linking goes silently empty, and several
exporters serve last season's team for traded players. **No existing monitor detects it —
everything stays green.**

## 5. Ordered plan to 2026-11-15

**Now → Aug 29**
1. Redeploy the 6 quota-failed services off-peak; verify by `BUILD_COMMIT`.
2. **Fix `br_roster_batch_processor`** (drop the `+1`, align the MERGE — or simply route
   `season-rosters` back to the schema-correct `BasketballRefRosterProcessor`).
3. Add `br-rosters-batch-daily` to the catalog (YAML + command derived in the review) and
   create it **paused**. Create `nba-closing-lines-sweep` paused.
4. Decide `missing-prediction-check` — its CF source directory was **deleted from the
   repo**, so it works today but cannot be redeployed or fixed.

**Sept**
5. REB/AST backfill (approved). Fleet diversity: get ≥1 non-clone model in the fleet.
6. Add tests for the untested hot paths (§7).

**Oct 1-6 — the seed** (hard gate)
7. Run `espn_roster` + `nbac_player_list` once on/after Oct 1 (they self-tag 2026).
8. Execute `br-rosters-backfill` once for `--seasons=2027`.
9. `roster_registry_processor.py --season-year 2026 --allow-source-fallback`; verify
   600-750 rows for `season='2026-27'`, spot-check traded players and rookies.

**Oct 6-17 — resume in waves.** Follow the runbook in §6. **Wave A T-14, B T-7, C T-3.**
Enable both pipeline canaries. Run the `halt-mode-frontend-impact.md` checklist.

## 6. Resume runbook — the pre-resume gates

Full ordering is in the review; the gates that must not be skipped:

- **`execute-workflows` must resume PAIRED with `master-controller-hourly`** (both PAUSED now).
- **Verify `nba-scrapers` is serving ≥ `7d1a3f9b`** before resuming `nba-tracking-stats-daily`
  (the drives-are-0.0 fix), and check the first run's drive values are not 0.0.
- **Verify `weekly-retrain`'s `BUILD_COMMIT` is current** before resuming its trigger.
- Wave B's same-day prediction pair only after one clean phase4 day.
- Resume **both** grading backstops (`grading-readiness-check`, `nba-grading-gap-detector`) —
  they are why the three `grading-*` jobs are correctly excluded (double-grading races).
- Three jobs are `America/Los_Angeles` — do **not** normalize.

## 7. Known-untested hot paths (ranked by cost if wrong)

1. **The two aggregator sanity guards** — they silently delete picks in the hot path. A
   fleet-wide floor was added after review; still no unit tests.
2. **`halt_state_writer.evaluate_halt_state` composition** — the precedence chain
   (edge → volume → drawdown → fleet → inactive → override) has no tests.
3. `post_grading_export`'s halted re-add guard; `weekly_retrain`'s `halt_source=='computed'`
   gate. Both one-line conditions guarding known past incidents.

## 8. Open items that are decisions, not bugs

- **`HALT_GATE_ENABLED=false` blinds the drawdown guard.** Picks published through an
  override are skipped forever by the replay, so the breaker cannot see losses booked while
  it was overridden. Runbook should say so.
- **No alert on `halt_active`**, and `dd_escalated` is consumed by nothing.
- **Nine restored CF targets accept unauthenticated requests** (IAM hygiene, pre-existing).
- **Export-time volume cap in `pipeline_merger`** — the only thing that can catch a volume
  spike on day one rather than the morning after.

## 9. Durable lessons

- **A green build is not a deployment.** Verify `BUILD_COMMIT` on the *traffic-bearing*
  revision — `latestReady == latestCreated` passes when a nested build EXPIRES and no
  revision is created. `./bin/verify-deploy.sh` does this.
- **Self-referential calibration is the recurring failure.** Validate against data the
  system did not generate. `validate_guard_invariance.py` measures **churn**, not headcount —
  the difference is 7x.
- **Validate bodies against the code that CONSUMES them, not the catalog they came from.**
  Two restored jobs would have run zero work and returned success.
- **Silent no-ops remain the most common defect class here** — ~16 found and counting. This
  session alone: an alert that could not fire, an empty Slack webhook, a decorator on the
  wrong function, and two no-op scheduler bodies.

*Session 2026-08-22.*
