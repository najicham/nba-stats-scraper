# Ten-agent review of the 2026-08-20 session — consolidated findings

**Scope:** 10 independent reviewers (fresh context, no inherited reasoning) over the work in
commits `2b190789`, `13cc1c3d`, `1e8fe7b7`, plus the season-prep plan. Every headline claim
below was re-verified in the main session before being recorded here.

---

## 1. Things that were WRONG in the session's own conclusions

| Claim made | Reality | Source |
|---|---|---|
| "Every service is verified serving the pushed code" | **False.** `transition-monitor` (`7b094e3`, 7 weeks stale) and `grading-gap-detector` (`2682e41`) had green builds and deployed nothing. **Fixed 2026-08-21, both now `1e8fe7b7`.** | red-team |
| "The serving-revision assertion is the check that would have caught it" | True for the six; **false in general.** When the nested source build EXPIRES, no revision is created, so `latestReady == latestCreated` on the OLD revision and the assertion passes. `gcloud functions deploy` printed a hard `ERROR:` and still **exited 0**. | red-team |
| "Retries only on quota; any other failure exits immediately" | Premise wrong — non-quota failures do **not** reliably surface as non-zero exit. | red-team |
| "93 services is the cause" of the quota failure | **Wrong.** Quota is 20,000 vCPU/min; the live fleet's worst-case ceiling is 820 (4%). Deleting dead services is a rounding error. | fan-out |
| "Four CFs have no build trigger" | **50 of 76** deployed CFs have no trigger. | docs |
| `nba-reference-service` is a dead stray | **Not dead** — Cloud Scheduler calls `/resolve-pending`, 25 hits/30d. | fan-out |
| `role_player_under_low_edge` removed for being "exactly break-even" | 52.44%, N=635, **p=0.98**, CI [48.6, 56.3]. The number justifies nothing. Removal still defensible on architecture + archetype-negation grounds. | stats |

**Also:** the removal bar used (52.4%, delete) is stricter than the system's own codified rule
(`CF_HR_THRESHOLD = 55.0`, N≥20, 7 consecutive days, **demote**). Unacknowledged inconsistency.

---

## 2. The auto-halt — two compounding defects

**(a) The metric tracks fleet composition, not the market.** Verified in-session:

| month | models/player-game | median edge | pct_e3 |
|---|---|---|---|
| 2025-12 | 5.4 | 2.4 | 36.2% |
| 2026-01 | 4.6 | 1.9 | 27.6% |
| 2026-02 | **12.4** | **1.3** | **10.2%** |

Holding the model set fixed (the 7 models present in both Jan and Feb), February reads
**1.5 / 16.6% → would NOT have halted.** March still halts (0.6 / 2.1%), so the breaker does
catch the real collapse — but **the single calibration episode is confounded with a fleet swap.**
Enabling or disabling a model now silently moves the circuit breaker.

**(b) Release is asymmetric and can trap.** Halt fires below 1.4; release requires ≥1.6 for 3
consecutive days. Replaying a hypothetical false halt on 2026-02-15: **no release for 63 days,
through season end.** A false positive is a lost season, not an outage.

Supporting measurements (145 evaluable clean-season days): **41.4% of days have median < 1.4.**
Only `pct_e3 ≥ 10%` keeps the system live, and its narrowest healthy-day buffer is **0.24pp
against a within-season SD of 8.70pp**. Estimated P(≥1 false-halt day in 2026-27) ≈ **25-40%**.

The AND conjunction is **confirmed load-bearing** — median-alone would have false-halted in
2023-24, 2024-25 *and* the clean 2025-26. Never simplify it.

**(c) Fail-open, still live.** `query_halt_state` returns `None` on error; `regime_context.py`
and `halt_state_writer` both leave `halt_active=False`. A transient BigQuery failure during a
real collapse publishes picks. Only `weekly_retrain` fails closed. This is the exact bug class
the module docstring says it exists to prevent.

**(d) `halt_state` may not gate picks.** The exporter's early return keys solely on
`bb_auto_halt_active`; `halt_envelope()` is consulted only *inside* that branch. A `manual` or
`fleet_blocked` row likely does not suppress publishing. **Needs confirmation.**

---

## 3. The "runs but affects nothing" class — worse than documented

The game plan names silent no-ops as a root cause of lost seasons. The review found more:

- **`decay-detection` has NO scheduler.** CLAUDE.md says daily 11 AM ET; it auto-disables
  BLOCKED models. **That safety net does not exist.** Same class as `weekly-retrain`.
- **`grading-gap-detector` has NO scheduler.**
- **Both pipeline canaries are PAUSED** (`nba-pipeline-canary-trigger` `*/15`,
  `nba-pipeline-canary-routine-trigger` hourly) — the documented 30-min pick-drought alerting
  does not run.
- **Health multipliers are inert** — 10,580 rows, 0 visible on their own game_date, min lag
  **40 hours**. `_get_health_multiplier` (aggregator.py:2324) is dead code with no callers.
  Lag-1 test says a fix would likely *hurt*: HOT **46.2%** (N=286) vs NORMAL 51.3% vs COLD
  **53.2%** — inverted against the 1.2×/0.5× weights.
- **`master-controller-hourly` is ENABLED while `execute-workflows` is deleted** — writing
  decisions nothing executes.
- **`deploy-monthly-retrain`** targets a deleted directory; permanently red since 2026-06-05.

---

## 4. Season-open blockers not in any plan

- **Player registry has no 2026-27 rows.** `nba_reference.nba_players_registry` max season
  `2025-26`, seeded 2025-10-02. Fallback silently serves **last season's rosters**.
  Equivalent due date: **~2026-10-01.**
- **`br-rosters-batch-daily`** is `critical: true` in `config/workflows.yaml` but is in
  **neither the restore catalog nor the live snapshot** — the restore will not bring it back.
- **Enabled fleet is 3 models, all trained to 2026-04-02/03** — inside the collapse window.
- `team_context.py:771,877,983` hardcode `game_date >= '2025-10-22'` → blends 2025-26 into
  2026-27 season averages.
- `SEASON_CALENDARS` has only 2024/2025 → trade-deadline/ASB toxic-window protection silently
  off for 2026-27.
- `discover_active_models` falls back to 4 legacy phantom IDs when the 30-day window is empty
  (i.e. every day until mid-November).
- Nov-1 season boundary hardcoded in **7 files / 9 sites**.
- **There is no historical case of this system publishing picks in the first two weeks of any
  season.** First real picks realistically ~**Nov 15**, from an April model on last season's
  rosters. Oct 20 is the wrong deadline to plan against.

---

## 5. Deploy integrity — what to actually do

The assertion was the valuable half. The retry is under-engineered and partly counterproductive:

- **No jitter** — `BACKOFF=ATTEMPT*90` is deterministic, so a lockstep herd reconverges exactly
  at t+90 and t+270.
- **It sleeps inside a build slot.** Cloud Build "Concurrent Build CPUs" = **4** (never raised).
  Holding a slot for up to 270s starves the queue — two builds EXPIRED this way on 2026-08-20.
- **Real constraints:** 5,672 retained revisions; 4 concurrent build CPUs; 26 of 36 triggers
  match `shared/**`. Not service count.
- **Timeout budget:** 3 attempts + 270s backoff + 120s assertion can exceed the configured
  `timeout:` in all three configs, converting a recoverable failure into an opaque TIMEOUT.
- **Coverage gap:** `mlb-phase2-raw-processors` and both MLB configs got the test gate but
  neither retry nor assertion.

**Correct assertion:** compare deployed `BUILD_COMMIT` to `SHORT_SHA` (and/or source generation),
and grep deploy output for `ERROR:` regardless of exit code. Revision-name equality is blind to
the failure that actually occurred.

---

## 6. Test gate

Verdict: **too narrow but well-calibrated.** Pins verified — no drift vs the worker lock. Three
deps genuinely sufficient (295 pass). Highest-value addition: import `predictions/worker/worker.py`
(needs only `Flask` + `google-cloud-storage`, does **not** pull catboost/lightgbm) — **+2.5s**.

The feared `931a7e2a` NameError **did not occur** — pyflakes shows zero undefined names on both
sides. But an import check would not have caught it anyway; static undefined-name analysis is the
right tool.

The "17 pre-existing failures" is really **60 failed / 3 collection errors**, and **none are
production bugs** — stale mocks, a moved symbol, and a live-Firestore test. Do **not** add that
directory to the gate.

**Two genuine latent crashes found** (confirmed in-session): `live_grading_exporter.py:39` and
`live_scores_exporter.py:30` use `logger` inside `except ImportError:` before it is assigned.

---

## 7. Scheduler restore — 17 blocking confirmations reduced to 1

All 16 others were derived from the code that *consumes* each message; for
`missing-prediction-check` the deployed function's own source zip contained the creating script.

**Landmine caught:** `run_mode` is not a coordinator key — `coordinator.py:953` reads
`prediction_run_mode` and defaults to `OVERNIGHT`→`RETRY`. Restoring the catalog as written would
silently downgrade `FIRST` / `FINAL_RETRY` / `LAST_CALL` to `RETRY`. Three other bodies would
hard-400; three would silently run zero processors. Also: `ShotZoneAnalyticsProcessor` does not
exist (it is `PlayerShotZoneAnalysisProcessor`) and unknown names are **silently dropped** with a
200 OK — so omitting the `processors` key is strictly safer than listing it.

**The one open question:** should the coordinator retry chain carry `"force": true`? It bypasses
the duplicate-batch block; `same-day-predictions` provably had it, but the doc showing it on all
four is a plan, not a deployment record.

*Compiled 2026-08-20/21.*
