# 2026-09-06 — P0 restore + first end-to-end rehearsal

Successor to `2026-09-05-SEVENTEEN-AGENT-REVIEW.md`. Read that, and the correction header of
`2026-09-01-FIVE-AGENT-REVIEW.md`, for the evidence base this session acted on.

**Opener 2026-10-20 (44 days). First publishable pick ~2026-11-17.**

Everything below was verified by a positive artifact — a row count that changed, a query that
appears in `region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT`, an HTTP status with a body.
No claim rests on the absence of an error.

---

## 0. One paragraph

The P0 is real and is now un-blocked: `CASCADE_PROCESSORS` is dead code, all 12 Phase-4
schedulers were paused, and driving `/process-date` by hand proved the write path still works
(`player_composite_factors` 0 → 486 rows). 18 schedulers are resumed. CI now runs unit tests for
the first time in the repo's history — and is red, honestly, with 90 pre-existing failures. The
champion-model resolver no longer falls back to a model that died in March. The rehearsal got
Phase 4 and Phase 6 proven and stopped at two walls worth more than the rehearsal itself: Phase 5
cannot be exercised on any historical date at all, and `model_bb_candidates` receives **zero**
rows, so the per-model provenance every promotion gate reads does not exist.

---

## 1. Done

### 1.1 CI executes unit tests (Tier-0 #1)
- `pytest-timeout>=2.3` added to `requirements-test.txt` and to `.github/workflows/test.yml`'s
  explicit install. Reproduced the original failure first: `unrecognized arguments: --timeout=60`,
  exit 4, before collection.
- Second blocker fixed: `tests/unit/prediction_tests/coordinator/test_batch_staging_writer_race_conditions.py`
  fabricated `predictions.coordinator` via `type(sys)(...)` and left it in `sys.modules`. A
  synthetic module has no `__path__`, so 4 later modules died with *"'predictions.coordinator' is
  not a package"*. `predictions/coordinator/__init__.py` exists — the file now imports the real
  package. Verified neutral for that file (30 failed / 13 passed before **and** after).
- **Before:** 0 tests ever executed. **After:** 2,940 collected, **2,827 passed / 90 failed /
  21 skipped / 2 errors**.
- The two regression guards written for this year's worst bugs —
  `tests/unit/ml/test_model_performance_grading_filter.py` (7) and
  `tests/unit/publishing/test_season_window_alignment.py` (19) — **run and pass, 26/26**, for the
  first time.

⚠️ **CI will now fail on every PR.** The 90 failures are real (they reproduce in isolation, so
this is not the `sys.modules` google-stub pollution): `test_batch_staging_writer_race_conditions`
30, `test_health_checker` 23, `test_execution_logger` 17, `test_firestore_arrayunion_limits` 13,
`test_run_history_mixin` 3, `test_dependency_tracking` 2, `test_circuit_breaker_mixin` 1,
`test_bigquery_client` 1. Fix or quarantine deliberately — do not silence.

### 1.2 Champion model resolves (Tier-0 #5)
`model_registry` had one `is_production` row (disabled v9) and three `enabled` rows, zero overlap.
`get_champion_model_id()` therefore returned the literal `catboost_v12` — whose **last prediction
is 2026-03-03**, not 2026-04-18 as previously reported. ~17 champion-filtered exporters were
querying a dead system_id.

- Demoted `catboost_v9_33f_train20260106-20260205_20260218_223530`.
- Promoted **`catboost_v12_noveg_train1205_0403`** (CatBoost, `v12_noveg`, trained through
  2026-04-03; all three enabled models predicted through 2026-04-18).
- Verified: the registry query returns it, and `get_champion_model_id()` resolves to it live.
- The zero-row path now logs **`CHAMPION_MODEL_UNRESOLVED` at ERROR** (not info — every
  `logger.info` in a Gen2 CF is discarded). Not made to raise: two exporters call it at module
  import, so raising would take down unrelated exports.
- This also revives `_fleet_in_transition` (`halt_state_writer/main.py:483`), which keyed on the
  same empty predicate and had never applied.

⚠️ `./bin/model-registry.sh sync` sets `is_production` from the GCS manifest and can silently
revert this. Fleet is still exactly **3** enabled models — do not add a 4th before the
`INSUFFICIENT_DATA` floor goes from n7<5 to n7>=30.

### 1.3 Schedulers resumed (Tier-1 #7) — 18 jobs
Phase 4 (12): `ml-feature-store-{7am,10am,1pm}-et`, `ml-feature-store-daily`,
`player-composite-factors-{daily,upcoming}`, `player-daily-cache-daily`,
`same-day-phase4{,-tomorrow}`, `overnight-phase4{,-7am-et}`, `phase4-timeout-check-job`.
Phase 1 (6): `nba-props-{morning,midday,pregame,evening-closing}` (all four run workflow
`betting_lines`, i.e. points), plus `master-controller-hourly` + `execute-workflows` resumed
together. All verified ENABLED.

Cost measured before resuming, not assumed: one date's Phase-4 chain = 566 SELECT + 2 MERGE jobs,
**5.6 GB billed ≈ $0.035**; a no-game day bills **0 bytes**.

### 1.4 Admin JSON exposure (owner decision: move to a private bucket)
Confirmed independently: anonymous `GET` of `v1/admin/dashboard.json` returns **HTTP 200,
14,469 bytes**.
- Created **`gs://nba-props-platform-admin`** — uniform bucket-level access, **no public
  bindings**, `objectAdmin` granted to the phase6 runtime SA.
- `AdminDashboardExporter` now honours **`ADMIN_BUCKET_NAME`**, defaulting to the current public
  bucket **so deploying this change alone breaks nothing**.
- **Cutover, still to do:** (1) point the frontend `/admin` at an authenticated read of the
  private bucket, (2) `gcloud run services update phase6-export --update-env-vars=ADMIN_BUCKET_NAME=nba-props-platform-admin`
  (**never** `--set-env-vars`), (3) delete the public copy.

### 1.5 Code freeze on `ml/signals/` (owner decision)
Recorded at the top of CLAUDE.md's Signal System section. No threshold/weight/filter/floor/rescue
change until **100 graded 2026-27 picks exist**. Bug fixes and observability still allowed.

### 1.6 Breakeven
Owner confirmed 4+ books. `DEFAULT_BREAKEVEN_HR = 52.4` stands; no gate changes.

---

## 2. The rehearsal

Owner chose *additive date, then clean up*. Snapshots taken first; everything restored after.

| stage | result |
|---|---|
| **Phase 4** | ✅ **PROVEN.** `/process-date` for 2025-12-23 → `player_composite_factors` **0 → 486 rows**, 488/490 feature rows rewritten (`updated_at` 2026-09-06 20:52:53). |
| **Phase 5** | ❌ **Structurally unreachable** — see §3.1. |
| **Phase 6** | ⚠️ **Executes and writes, but yields no picks** — see §3.2. |

**Final integrity check:** `signal_best_bets_picks` = 203 rows, **0 created today**;
`player_prop_predictions` **0 created today**. Feature store for 2025-12-23 restored exactly
(490 rows, 163 clean, `max(updated_at)` back to 2026-03-01). Three GCS JSONs restored by
generation. Fleet back to exactly 3 enabled models.

**Left in place deliberately:** the 486 `player_composite_factors` rows for 2025-12-23 (a gap
fill, not contamination). Note that recomputing the feature store *with* them present dropped the
clean-row count **163 → 149** — worth a look, it means composite-factor presence makes more rows
fail zero-tolerance.

**Snapshots kept:** `nba_predictions_backups.rehearsal_fs_20251223_pre`,
`nba_predictions_backups.rehearsal_registry_pre_20260906`. Safe to drop.

---

## 3. New findings

### 3.1 Phase 5 cannot be rehearsed or backfilled on any 2025-26 date
`POST /start` for 2025-12-23 returned **HTTP 404 `{"message":"No players found"}`** while the
same body reported `total_players: 486`, `production_ready_count: 775`, `with_prop_line: 377`,
`total_games: 21`. The logs give the real reason:
`Game date 2025-12-23 is too far in the past (>90 days)` → `Invalid game date`
(`predictions/coordinator/player_loader.py:2114`, comment: *"TEMPORARY: Increased from 30 to 90
days"*).

From the off-season every 2025-26 date is out of range, so **the first proof that Phase 5 works
will be a live game night** unless this is parameterised. It has also silently capped every
historical prediction backfill since the constant was set.

**Fix before Oct 20:** `int(os.environ.get('COORDINATOR_MAX_PAST_DAYS', '90'))`, and make the 404
say `invalid_game_date: >90d in past` instead of `No players found` — the current message sends
you to the feature store.

### 3.2 `enabled = TRUE` is necessary but not sufficient — a hardcoded model allowlist gates best bets
Read off the query the running exporter actually issued. The per-model prediction fetch ends with
a ~30-clause `AND (p.system_id = 'catboost_v9' OR p.system_id LIKE 'lgbm_v12_noveg_%' OR ...)`,
generated by `build_system_id_sql_filter()` in `shared/config/cross_model_subsets.py`. The
registry only feeds the *exclusion* CTE; it never adds a model in.

Proved it: a registry row for `catboost_v8` with `enabled = TRUE` (315 real predictions, 215 with
lines on the target date) produced `total_predictions: 0`. Models whose ids match the patterns
produced 17, then 77, candidates on the same code path.

**Consequence:** ship a model family with a new id prefix and it will be enabled, generate
predictions, appear in model-health exports, and contribute **nothing** to best bets — silently.

### 3.3 `model_bb_candidates` receives ZERO rows
Across three runs, with 77 candidates flowing through 7 per-model pipelines,
`model_bb_candidates` got **0 rows**. Task #39 is not "the writer emits 30 of 47 columns" — the
writer emits nothing. Every promotion gate that reads per-model provenance is **unreachable**,
not merely under-powered. `best_bets_filtered_picks` (125) and `best_bets_filter_audit` (2) were
written on the same runs, so the export is not failing wholesale.

### 3.4 The filter stack rejected 100% of candidates
| date | models | candidates | edge≥3 | edge≥5 | max edge | picks |
|---|---|---|---|---|---|---|
| 2026-04-10 | 1 | 17 | 17 | 4 | 9.2 | 0 |
| 2026-03-12 | 1 | 24 | 24 | 7 | 9.4 | 0 |
| 2026-03-12 | 7 | 77 | 77 | 17 | 9.4 | 0 |

Top blockers across the 77: `line_jumped_under_obs` 15, `bench_under` 14, `under_star_away` 10,
`regime_over_floor` 9, `signal_stack_2plus_obs` 9, `clv_diverge_under_block` 7,
`regime_rescue_blocked` 7. Three `_obs` (observation-mode) filters appear in the rejection
counts — confirm they are counted but not blocking.

This **reproduces** the live outcome for both dates (0 picks on the day), so it is consistent
behaviour, not breakage. But it means the `signal_best_bets_picks` write path is **still the one
unproven link in the chain**, and both dates sit inside the TIGHT-market / March-collapse regime,
so it is not evidence about November either.

### 3.5 The bootstrap window reports success while writing nothing
`/process-date` for 2025-11-03 returned `HTTP 200 {"status":"success","stats":{}}` for all three
processors and wrote **zero rows**. The logs:
`⏭️ Skipping 2025-11-03: early season period (day 0-13 of season 2025). Regular processing starts
day 14.` So for the **first 14 days of every season** these processors deliberately no-op *and
report success* — the same window that hides the missing feature store until Nov 3.

### 3.6 Confirmed live, previously only asserted
- `WARNING:shared.observability.metrics:monitoring_v3 not available, metrics will be no-op` on
  every Phase-4 request. Tier-0 #6 (add `google-cloud-monitoring` to 5 lock files) is real.
- `phase6-export` logs show **only** WARNING+ lines — the Gen2 `logger.info` discard is real.
- `best_bets_filtered_picks` had **no rows at all** for 2026-03-12 or 2026-04-10 before this
  session, despite the live export running those days. The writer appears to post-date them.

---

## 4. Next, in order

1. **Parameterise the 90-day guard** (§3.1) and fix the misleading 404. Without it there is no
   Phase 5 rehearsal before opening night.
2. **Fix the `model_bb_candidates` writer** (§3.3). Nothing downstream of it can be evaluated
   until rows exist.
3. **Add `google-cloud-monitoring`** to the coordinator, phase3, phase4, nba-scrapers and
   nba-grading-service lock files (Tier-0 #6).
4. **Complete the admin-bucket cutover** (§1.4 steps 1-3).
5. **Decide on the 90 CI failures** — fix or quarantine, explicitly.
6. **`is_backfilled` + `bet_key` on `signal_best_bets_picks`** (Tier-2 #15). Every HR query on
   that table is wrong until the flag exists.
7. Remaining Tier-0/Tier-1 from the 09-05 review: symlink validator into `pre-commit-checks.yml`;
   `check-deployment-drift.sh` map + `set -u` + `$SERVICES`; the two-line grading `sportsbook` /
   `line_source_api` SELECT fix; `pipeline_reconciliation` swallow; injury fail-open;
   `INSUFFICIENT_DATA` floor to n7≥30 **before** any 4th model.

---

## 5. Pushed and verified

`1e44991f` (the fixes above) and `a3f3466f` (`pytz` + `functions-framework`, see below).

**CI.** The first run got **past exit 4** — `collected 2825 items` — but died at exit 2 on 5
collection errors that do not reproduce locally: `No module named 'pytz'` (3 orchestration
tests) and `No module named 'functions_framework'` (2 publishing/halt tests). Neither is in
`requirements.txt`; both happened to be present in `.venv`. `pip install -r requirements.txt ||
true` did **not** mask a failure — that install succeeded. Added both to `requirements-test.txt`.

**Second run — the suite executes end to end for the first time: `171 failed, 2704 passed,
43 skipped, 22 errors`.**

⚠️ CI has ~81 more failures than local (171 vs 90), and the gap is not flakiness:
`google.auth.exceptions.DefaultCredentialsError`, **358 occurrences**. A large share of
`tests/unit/` is **not hermetic** — it constructs real GCP clients and passes only where ADC
exists. Corroborated independently: during the local run,
`INFORMATION_SCHEMA.JOBS_BY_PROJECT` showed precompute-processor queries issued under
`nchammas@gmail.com`, i.e. the "unit" suite was hitting live BigQuery. **The next step is not
"fix 171 tests" — it is to make the suite hermetic, then judge what is genuinely broken.**

**Deploy.** Fan-out measured before pushing: **29 triggers**. Wave outcome: 17 SUCCESS,
7 FAILURE, 8 EXPIRED, 4 CANCELLED. The 7 CF failures were contention, not code — each one's
*inner* function build was CANCELLED. Re-running the failed triggers in **batches of 3 after the
wave drained** made all 9 succeed with no code change (`gcloud builds triggers run <name>
--branch=main`; never re-push).

⚠️ **Correction to the standing "verify by BUILD_COMMIT" rule.**
`services describe --format="value(spec.template.spec.containers[0].env)"` returns the *latest
created* revision — it read `1e44991` on three services that were still serving **`b81937e`
from 2026-08-30**. `nba-scrapers`, `nba-phase3-analytics-processors` and `nba-grading-service`
each had a revision stuck at `HealthCheckContainerError: Quota exceeded for total allowable CPU
per project per region`. Read the **serving** revision instead:

```bash
ready=$(gcloud run services describe $S --region=us-west2 --format="value(status.latestReadyRevisionName)")
gcloud run revisions describe $ready --region=us-west2 --format="value(spec.containers[0].env)" | grep BUILD_COMMIT
```

Fixed without a rebuild: `gcloud run services update $S --update-env-vars="BUILD_COMMIT=<same>"`
once the wave drained. All three now serve `1e44991` with `latestReady == latestCreated`.
**Final sweep: the only remaining mismatches are the three known permanent strays**
(`analytics-processor`, `nba-reference-service`, `prediction-coordinator-dev`).

Working tree clean.

## Do NOT
Unchanged from the 09-05 review: no `model_performance_daily` backfill; do not delete signal
rescue; do not lower the OVER floor to 3.0; do not ship the BDB "two-line fix"; no 4th model
before the n7≥30 floor; do not use `gcloud builds list` as a deploy oracle. Plus, new:
**do not trust `/process-date` or `/start` status text** — check row counts and
`INFORMATION_SCHEMA.JOBS_BY_PROJECT`.
