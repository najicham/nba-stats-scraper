# Session Handoff — 2026-08-22 — the batch is deployed and the schedulers are back

Previous: `2026-08-21-SESSION-4-AUTO-HALT-REBUILD.md`. **Opener: Tue 20 Oct 2026.**

---

## TL;DR

Seventeen reviewers over two rounds, then execution. The auto-halt work from Session 4
survived review; the reviews found one blocker and roughly twenty majors, all fixed.
Then the batch was **pushed and deployed**, and the **59 deleted Cloud Scheduler jobs
were re-created (paused)** — the item that had been the critical path since the backup
was destroyed, and which nobody had been on.

The headline correction still stands and is now doubly confirmed: **the edge metric was
never a market signal.** A purpose-built invariance check makes that measurable rather
than a matter of judgement.

---

## 1. What is now live

| Component | State |
|---|---|
| `halt-state-writer` | **DEPLOYED**, revision `-00010-woj`, `BUILD_COMMIT=9030f8e1`, Slack secret **mounted** |
| `halt-state-stale` alert policy | **UPDATED live** — Critical, threshold >30h OR series-absent-23h |
| Secret IAM | `halt-state-writer` SA granted `secretAccessor` on `slack-webhook-monitoring-warning` |
| Scheduler catalog | **59 jobs re-created, ALL PAUSED** |
| Everything else | pushed as `33ba93a7`; auto-deploy fan-out ran |

## 2. Three defects found *while deploying*, that reading could not have found

1. **The stale-alert could never fire, in either shape.** `halt_state_age_hours` was
   emitted only on a successful write, once a day. A threshold can't fire (a dead writer
   emits nothing, so there is no series); and `conditionAbsent` can't be configured
   either — Cloud Monitoring caps its duration at **23h30m** and a healthy once-daily
   emitter has a ~24h gap, so every valid duration false-fires daily. Fixed by having
   `phase-completion-reconciler` (every 30 min) emit the age from the table, giving the
   metric a continuous series whose *value* grows when the writer dies.
2. **`SLACK_WEBHOOK_URL_ALERTS` was present but EMPTY**, so `maybe_alert_on_change` — the
   only notification that a halt fired or released — was a silent no-op. The secret
   existed; the SA had no accessor binding.
3. **`bin/deploy-function.sh` had no secret support**, so binding the webhook out-of-band
   would have been silently dropped by the next redeploy. Added `FUNC_SECRETS`
   (`--update-secrets`, never `--set-secrets`).

## 3. What the ten round-2 reviewers changed

**Confirmed working** by running it, not reading it: the halt gate short-circuits before
the pipelines (call count 0), `manual` is excused while `unknown_state` falls through the
floors, all three `halt_envelope` tiers behave as documented against the real
2026-08-16..19 write gap, and the opening-night fix holds on the actual 2026-27 schedule.

**Fixed:**
- **No kill switch on the gate** — added `HALT_GATE_ENABLED`. The halt path is one-way by
  design, so the only way back from a false halt was pinning Cloud Run traffic.
- **The dormancy gate swallowed a COMPUTED halt** — same bug class already fixed once for
  fallbacks. A halt carried through a thin stretch (all-star-break shaped) was persisted
  as `halt_active=False` with `source='computed'`: a "healthy" row laundering a live halt.
- **Zero test coverage on the publishing half** — 17 tests added; "906 tests pass" had
  carried no signal about the gate at all.
- **The warm-up quarantine no longer protects against the February episode.** Family
  keying re-admits 29 experiment model-days; under the OLD thresholds the false halt would
  arrive **three days earlier than before the quarantine existed**. The loosened
  thresholds are now the sole protection — a second reason never to re-tighten. The
  shipped calibration floor is the family-keyed 0.800/4.47%, not 0.871/6.72%.

## 4. New capability

**`shared/config/drawdown_halt.py` — decision 4, done.** `unit_drawdown` (6u soft / 10u
hard below the season-scoped peak) and `volume_anomaly` (`>= max(10, 3x trailing-10-pick-day
median)`). Replayed at true 5 AM cadence over 2025-26:

    halt days 9 (one episode) · avoided +14.27u · forgone -2.45u · net +11.82u
    max drawdown 14.27u -> 3.64u

Two properties are load-bearing: the peak **resets** on release (or the frozen curve
re-halts forever), and the volume window is **3 days** (03-06 published 13 picks, 03-07
published 1, and the 03-08 slate lost 9.18u). Parameters came from a 36-cell grid and the
**plateau was taken, not the maximum**.

**Large-edge guards:** per-model median-edge cap 5.5 and prediction-spread floor 2.0 in
`aggregator.py`, plus a symmetric fleet bound at 4.5 in `edge_halt`. All 0 FP over five
seasons. A self-baseline change detector was tested and rejected — broken models here were
born broken or came back broken, never drifted.

**`bin/validation/validate_guard_invariance.py`** — run before changing ANY guard
threshold. Measure **churn**, not headcount (rho -0.582 vs -0.085; a 7x under-read). Its
uncomfortable finding: the shipped basis is **more** churn-coupled (-0.797) than the one it
replaced. Nothing decouples it — which is exactly why demoting the thresholds beat
recalibrating them. The script therefore gates on "is the bar out of reach of churn?",
not on coupling itself.

**Four season-boundary bugs** that would have failed silently on 2026-10-20:
`SEASON_CALENDARS` had no 2026 entry; `discover_active_models` fabricated a four-model
phantom fleet whenever the 30-day window was empty (i.e. every day until mid-November);
`PlayerLinker` defaulted to `'2025-26'` on a 15-minute scheduler; `season_game_counts`
hardcoded both the start date and the label.

## 5. Still open — ordered

1. **Resume the schedulers in waves** (they are all created, all paused). Wave A at T-14,
   B at T-7, C at T-3. `execute-workflows` must be resumed PAIRED with
   `master-controller-hourly`. The restore script only creates; resuming is manual.
2. **`br-rosters-batch-daily` does not exist anywhere** — not in the catalog, not in the
   snapshot. The BR-roster → `RosterRegistryProcessor` → `nba_players_registry` path is
   dead with no restore path, and **the registry still has no 2026-27 rows** (max season
   2025-26). Due ~2026-10-01. This is the top remaining P0.
3. **`nba-closing-lines-sweep`** is in no backup and no catalog — create via
   `bin/deploy/deploy_closing_lines_scheduler.sh --paused`.
4. **Enable both pipeline canaries** before opening night.
5. **`phase-completion-reconciler` needs a manual deploy** — it has no build trigger and
   now carries the `halt_state_age_hours` emitter the alert depends on.
6. Frontend check: the halt payload drops 14 top-level keys and introduces
   `model_health.status='halted'`. Run `halt-mode-frontend-impact.md` against props-web.
7. Export-time volume cap in `pipeline_merger` — the only mechanism that can catch a
   volume spike on day one rather than the morning after.

*Session 2026-08-22.*
