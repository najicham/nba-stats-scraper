# Session Handoff — 2026-08-22 (session 6) — the roster P0 root cause, and three silent-failure chains

**Opener: Tue 20 Oct 2026 (59 days). First realistic picks ~2026-11-15.**
Previous: `2026-08-22-SESSION-5-HANDOFF.md`.

---

## TL;DR

Session 5's three tasks are done: the quota casualties are redeployed and verified, the
roster-registry root cause is fixed at the source rather than at the scheduler, and the
untested hot paths now have 116 mutation-checked tests.

The headline is that the roster P0 was **three** independent silent failures stacked on
one pipeline, not one. Each was individually invisible; together they had BR roster data
dead for seven months while every dashboard stayed green.

> The scheduler asked for the **wrong season**. The processor it fed **could not write at
> all**. And the Cloud Run job image it invoked **could not be rebuilt**, because a dead
> symlink had been crashing `gcloud builds submit` since May.

Fixing any one of them alone would have restored a job that still failed.

---

## 1. Quota casualties — DONE, verified by BUILD_COMMIT

A full ~36-trigger fan-out from the session-5 push was already draining when this session
started, at only 2 concurrent builds. It completed. Verified on the **traffic-bearing**
revision with `./bin/verify-deploy.sh`:

| Service | State |
|---|---|
| `weekly-retrain` | **OK** `3522c49` rev `-00049-luf` — the governance-gate change has landed; Wave C precondition met |
| `nba-scrapers` | **OK** `3522c49` rev `-00378-hvh` — carries the `PlayerLinker` season fix |
| `prediction-coordinator` | OK `3522c49` |
| `decay-detection` | OK `3522c49` |
| `mlb-prediction-worker` | OK `3522c49` |
| `nba-grading-alerts` | was stale at `2b19078`; rebuild triggered, **re-verify** |

⚠️ `halt-state-writer`, `phase6-export` and `post-grading-export` are all behind on
**`9f665f90`** (the "decorator on the wrong function / fleet-wide block / disarmed bound"
commit, which touched `shared/`). These are *not* the false-STALE the previous handoff
warned about — the delta is real code. `halt-state-writer` has no build trigger, so use
`./bin/deploy-function.sh halt-state-writer`.

---

## 2. THE ROSTER P0 — root-caused, fixed, and the fix proven live

`nba_reference.nba_players_registry` still has no 2026-27 rows (max `2025-26`, 696 rows,
last processed 2026-02-04). The seed itself still cannot happen before Oct 1. What changed
is that the machinery it depends on now works.

### 2.1 The processor had never written a row

`BasketballRefRosterBatchProcessor` was schema-misaligned with `nba_raw.br_rosters_current`
in five separate ways at once — four columns that do not exist, four REQUIRED columns
omitted, a TIMESTAMP into a REQUIRED DATE, and `season_year = start_year + 1` against a
table keyed on the start year. The MERGE could not parse.

Timeline, confirmed against BigQuery rather than inferred:

- `129a5bf9` (2026-01-13) added the Firestore-lock branch routing roster files to this
  processor instead of the schema-correct per-file `BasketballRefRosterProcessor`.
- The last BR roster write is **2026-01-13**, 524 rows across 30 files, `source_file_path`
  populated — i.e. written by the per-file processor, on the day the routing changed.
- Three weeks *before* the July scheduler purge. The purge is not the cause.

Both entry points — the GCS object notification and the backfill job's batch-completion
message — converge on this processor, so "route files back to the per-file processor"
would not have fixed the Oct 1-6 seed path. Repaired in place instead.

**The subtle part, which a reviewer caught and is worth remembering.** The original MERGE
gated its UPDATE on `source.data_hash != target.data_hash`. That looks like a free DML
saving and is actually a change to what `last_scraped_date` means.
`BRRosterSource.get_roster_players` reads `WHERE last_scraped_date = @data_date` and treats
a non-empty result as a **full match**. Under a hash gate only players who changed that day
carry today's date — so the registry would have seeded itself from three players and
reported success. The MERGE is now unconditional on match, exactly like the per-file
writer, and a test asserts the gate cannot come back.

### 2.2 The scheduler asked for the wrong season

`br-rosters-batch-daily` is in no catalog, no snapshot, and 400 days of audit logs. Its
definition was recovered from the **commit message of `19eda492`**, which created it:

```
Schedule: 30 6 * * * (6:30 AM ET daily)
Job: br-rosters-backfill with args: --seasons=2025 --all-teams --group=prod
```

`--seasons` takes **ending** years. In January 2026 the live season was 2025-26, which is
`--seasons=2026`. So the job re-scraped the **2024-25** rosters every morning for six
months. The 2026-02-01 audit recorded it as "JOB FAILING"; the response on 2026-02-02 was
a manual processor backfill — of the same wrong season. All 655 of those rows are in the
table, written in one shot, and nobody noticed the year.

Restored **PAUSED** (wave A) with `--current-season`, a new flag that resolves at run time
from `shared/utils/season_utils`, so no scheduler carries a year again.

### 2.3 The job image could not be rebuilt

`--current-season` would have exited 2 on an image built **2025-09-18**, and the scheduler
would have reported SUCCESS anyway, because the Admin API `:run` only creates the
execution. Two things blocked the rebuild:

- `1942a6b3` archived the whole `docker/` directory as "orphaned". Twelve scraper-backfill
  deploy scripts hard-fail without `docker/backfill.Dockerfile`. Restored.
- `54d08d56` (2026-05-11) deleted `shared/utils/bigquery_client.py` and left six vendored
  symlinks pointing at it. Nothing imported it, so nothing failed — but a dangling symlink
  makes gcloud's file enumeration **crash outright**, so `gcloud builds submit` from the
  repo root has not worked since May. Cloud Build *triggers* check out from git and were
  unaffected, which is exactly why it stayed invisible for three months.

Image rebuilt, job updated, and proven live rather than assumed — execution
`br-rosters-backfill-d8qbb` logged:

```
--current-season resolved to ending year 2026 (season 2025-26)
```

which is correct for today and becomes `2027` / `2026-27` on Oct 1.

### 2.4 Still to do — unchanged, and still gated on the calendar

Seed window **2026-10-01 → 10-19**, drop-dead ~2026-10-06. Steps 7-9 of the session-5 plan
are unchanged. ESPN remains the dominant registry source (589/696); BR contributes 20.

---

## 3. Tests for the untested hot paths — 116 added, every one mutation-checked

No test was accepted on a green run alone. For each, the thing it covers was disabled and
the test was confirmed to fail.

| Area | File | N |
|---|---|---|
| The three aggregator model-sanity guards | `tests/unit/signals/test_aggregator_model_sanity.py` | 19 |
| The fleet-wide floor, on the production path | `tests/unit/signals/test_fleet_sanity_floor.py` | 17 |
| `evaluate_halt_state` precedence chain | `tests/unit/publishing/test_halt_state_composition.py` | 29 |
| Halted re-add guard + governance-loosening gate | `tests/unit/publishing/test_halt_downstream_guards.py` | 25 |
| BR roster schema/writer/MERGE parity | `tests/unit/data_processors/test_br_roster_batch_processor.py` | 26 |

### 3.1 The fleet-wide floor was inert on the best-bets path

Writing the tests is what exposed this, and it is the most consequential finding in the
section. `aggregate()` carries a fleet-wide safety floor; `run_single_model_pipeline`
calls `aggregate()` **once per model with only that model's predictions**, so its
`n_models` is always 1 and `1 > max(1, int(1*0.5))` is False. From the guards shipping
until now, the floor could not fire on the path that picks money — and the first draft of
the tests happily certified those dead semantics.

(Scope, corrected after review: the aggregator's floor is not dead code in general.
`signal_annotator._bridge_signal_picks` is production — `subset-picks` is in
`TONIGHT_EXPORT_TYPES` — and passes a real multi-model list, so the floor is live for the
published "Signal Picks" subset. It was dead only for signal-best-bets.)

The failure it was supposed to prevent is specific: the enabled fleet is three near-clones
of one family (r ≥ 0.95), so a shared feature regression trips the same guard on all three
— one per pipeline run — producing an indefinite zero-pick drought with
`halt_active: false`, no halt reason and nothing to alert on. `pick_drought` is MLB-only,
`_predictions_inactive` sees predictions flowing, `fleet_blocked` reads
`model_performance_daily` (which grades predictions, not picks) and stays healthy, and
both canaries are paused.

The floor now lives in `_apply_fleet_sanity_floor` in `per_model_pipeline` — the only
caller that can see the fleet. When more than half of the models self-block it logs ERROR,
emits `model_sanity_fleet_wide_trip`, and **re-runs those pipelines with
`disable_model_sanity=True`** so the day surfaces as a halt/model-health event instead of
a silent empty slate. The in-aggregator floor stays for the default-mode callers
(signal_annotator, backtest, replay, dry-run), with a docstring saying plainly that it
cannot fire in `per_model` mode.

Detection is `filter_summary['rejected']['model_sanity_block'] > 0`, which is why the
counter mattered beyond observability. Legacy-blocklisted and errored pipelines are
excluded from BOTH the numerator and the **denominator** — counting them dilutes the
fraction toward not tripping, which is the dangerous direction. Concretely: two enabled
clones plus two legacy prediction sets gives `n=4`, both real models self-block,
`2 <= max(1, 2)` holds, no trip — the exact zero-pick day the floor exists to stop.

A fleet-wide trip stamps `model_sanity_block_disarmed` and
`model_sanity_fleet_wide_trip` onto each re-run pipeline's filter summary, so the audit
trail survives the replacement. Without it, a fleet-wide trip would be the one day whose
`best_bets_filter_audit` shows nothing was ever blocked.

**And a new Critical alert policy ships with it.** The floor deliberately fails OPEN. That
is only defensible if someone finds out, and nothing was listening —
`monitoring/alert-policies/model-sanity-fleet-wide-trip.yaml` closes that. Without it the
fix would trade a silent drought for a silent *publication* of picks from models every
guard just condemned, which is worse: the drawdown and volume breakers evaluate at 5 AM on
yesterday's data and cannot stop the first slate.

Three things worth knowing:

- **The sanity guards had no counter.** A zero-pick day caused by a sanity block was
  indistinguishable from an empty slate in the filter summary. Added
  `filter_counts['model_sanity_block']`. It is write-only, so it does not appear on empty
  input and does not disturb the exact-key-set assertion in the existing suite.
- **The floor arithmetic is `> max(1, int(n * 0.5))`.** Half does not disarm; more than
  half does; a one-model fleet is NOT disarmed. All three are pinned in both files,
  because that expression flips silently under an innocuous edit.
- **Two guards were unreachable from a test** and were extracted:
  `post_grading_export.patch_best_bets_json` and `weekly_retrain.is_computed_edge_halt`.
  Both extractions are behaviour-preserving. While doing the first one I re-created this
  repo's own `9f665f90` bug — the `@functions_framework.cloud_event` decorator followed
  the extracted function instead of staying on `main`. Caught before commit. **When you
  splice a function in above `main`, check the decorator.**

---

## 4. New findings, ranked

1. **`gcloud builds submit` was broken repo-wide for three months** (§2.3). The symlink
   pre-commit hook only checked that a hardcoded list of links was *present*; it never
   checked that any link *resolves*. It now walks the repo and fails on any dangling
   symlink. `.claude/` is also now in `.gcloudignore` — agent worktrees are full repo
   copies carrying their own stale symlinks, and they both bloated every build context and
   re-triggered the same crash. Enumeration went from crashing at 1,279 files to
   completing at 4,785.

2. **Eight more live deploy scripts still reference archived Dockerfiles**
   (`docker/analytics-processor.Dockerfile`, `docker/precompute-processor.Dockerfile`,
   `docker/predictions-coordinator.Dockerfile`, `docker/freshness.Dockerfile`,
   `docker/mlb-*.Dockerfile`). Only `backfill.Dockerfile` was restored, because only the
   backfill jobs have no Cloud Build trigger and therefore no alternative path. The others
   are broken-but-not-load-bearing. Decide whether to restore or delete them.

3. **`gs://nba-scraped-data` deletes objects at 90 days** (NEARLINE at 30). This is the
   deliberate 2026-01 cost policy, but the consequence is worth stating plainly: **all NBA
   raw JSON older than 90 days is gone** — `basketball-ref/`, `espn/`, `odds-api/` and
   `big-data-ball/` no longer exist as prefixes at all. Any processor backfill that
   re-reads GCS is limited to a 90-day window. The Oct seed plan is unaffected because it
   re-scrapes. Encouraging side note: `nba-com/schedule/2026-27/` was written 2026-08-20,
   so the opener schedule is already in hand.

4. **`model_sanity_block` is now in `shared/registry/filters.yaml`** and in
   `NEVER_DEMOTE` in `filter_counterfactual_evaluator`. First attempt put it in
   `stream_block_class.class_a`, which is a *different* list — the C3 promotion-stream
   Tier-1 classification, not the non-demotable set — and wrong on its own terms, since
   that block's header names "sanity" as Class B and `default: B` already covers it.
   Two lists containing `legacy_block` is how they got conflated.

5. **27 pre-existing failures in `tests/cloud_functions/`** (mostly
   `test_phase5_to_phase6_handler.py`). Confirmed pre-existing by stashing — not caused by
   this session. Untriaged.

6. **The "16 picks exceeded the 15/day merger cap" claim was wrong**, and it was in
   `drawdown_halt.py`'s docstring where it would have sent someone hunting a cap bug.
   `pipeline_merger` and `MAX_MERGED_PICKS_PER_DAY` did not exist until `bfac51f2` on
   2026-03-08 itself; the March 4-8 picks carry `algorithm_version` v429 / v438 / v440,
   the pre-merger path, and 03-08 alone spans three versions between 12:03 and 21:01 UTC.
   Panic-deploy churn, not a breached cap. Corrected in place.

   While checking it: the volume guard counts `DISTINCT (player_lookup, recommendation,
   line_value)` from a table whose DELETE is scoped to refreshed players, so several
   export runs a day accumulate rows and line movement between runs *could* double-count
   a pick. Measured — **0 of 203 player-days in 2026 carry more than one `line_value`**,
   and no day's distinct-triple count differs from its distinct (player, direction) count.
   The basis is clean, and replay and the live guard call the same function, so any
   residual inflation is priced into the calibration. **Do not "fix" that query** without
   re-measuring the thresholds.

7. **`validation/configs/raw/br_rosters.yaml` targets `nba_raw.br_season_rosters`**, a
   table name that does not match the real `br_rosters_current`. Likely another silent
   no-op in the validation layer. Not investigated.

---

## 5. What is LIVE right now

| Component | State |
|---|---|
| `br-rosters-batch-daily` | **CREATED, PAUSED.** `30 6 * * *` America/New_York, OAuth, Run Admin API `:run` with `--current-season --all-teams --group=prod` |
| `br-rosters-backfill` job | image rebuilt 2026-08-21, job updated, flag verified in a live execution |
| Scheduler jobs | **169 → 170.** ENABLED unchanged at 74. Every restored job still PAUSED |
| Catalog | 60 entries (59 restored + `br-rosters-batch-daily`, which was never in the purge) |
| Today's `halt_state` | NBA `off_season`, `halt_active=true` |

---

## 6. Ordered plan to 2026-11-15 (revised)

**Now → Aug 29**
1. Re-verify `nba-grading-alerts`; deploy `halt-state-writer` with
   `./bin/deploy-function.sh` (no trigger) and confirm `phase6-export` /
   `post-grading-export` land `9f665f90`.
2. Decide `missing-prediction-check` — its CF source directory was deleted from the repo,
   so it works today but cannot be redeployed or fixed. **Unchanged from session 5.**
3. Create `nba-closing-lines-sweep` paused via `bin/deploy/deploy_closing_lines_scheduler.sh`.
   **Unchanged from session 5.**

**Sept**
4. REB/AST backfill (approved). Fleet diversity: get ≥1 non-clone model into the fleet.
5. Export-time volume cap in `pipeline_merger` — still the only thing that can catch a
   volume spike on day one instead of the morning after.
6. Triage the 27 `tests/cloud_functions` failures (§4.5).
7. Decide on the eight remaining archived Dockerfiles (§4.2).

**Oct 1-6 — the seed** (hard gate). Unchanged from session 5 §5 steps 7-9.

**Oct 6-17 — resume in waves.** Session-5 §6 gates all still apply, plus one new one:
**before resuming `br-rosters-batch-daily`, confirm `nba-phase2-raw-processors` is serving
the fixed `br_roster_batch_processor`.** Its first run should write ~600 rows with
`season_display='2026-27'` and `season_year=2026`; anything else means the routing or the
season convention moved again.

---

## 7. Durable lessons

- **Three green layers can hide one dead pipeline.** The scheduler reported success
  (`:run` only creates the execution), the processor failed inside a handler that logs and
  returns, and the image was too old to have the flag. Every layer was individually
  plausible. What broke the tie was reading the *data*: the last write date in BigQuery
  matched a routing commit to the day.
- **A commit message can be the last surviving copy of a config.** `br-rosters-batch-daily`
  existed in no backup, no catalog, no snapshot and no audit log — only in the body of
  `19eda492`. Write them like that.
- **"Orphaned" is a claim to verify, not a label to apply.** `1942a6b3` archived a
  directory twelve live scripts depended on.
- **A refactor for testability is still a refactor.** Extracting a block above `main`
  moved a decorator onto the wrong function — the exact bug this repo fixed nine commits
  earlier.
- **A mock that mocks nothing looks exactly like a mock.** `mock.patch.dict('sys.modules')`
  with no arguments snapshots and restores the module table and patches nothing. The tests
  passed, and executed the real `emit_metric` — harmless here only because
  google-cloud-monitoring is absent from this venv. On CI with the package and ADC it
  would have written real time series into the production project. Assert the mock was
  *called*, not just that the test is green.
- **Writing a test can reveal that the thing you are testing never ran.** The fleet-wide
  floor looked correct, read correctly, and was unreachable. The first draft of its tests
  passed, and would have entrenched dead semantics as verified behaviour. Ask what call
  site actually reaches the code before writing the assertion.
- **Mutation-check every new test.** Four of the tests written this session passed on the
  first run against code that already worked; only disabling the guard proved they were
  measuring anything.

*Session 2026-08-22.*
