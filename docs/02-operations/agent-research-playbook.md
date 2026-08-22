# Agent Research & Review Playbook

**Status of the project this playbook serves (2026-08):** research is CONVERGED; the next
phase is LIVE EXECUTION for the 2026-27 season (opener 2026-10-20, first realistic picks
~2026-11-15). Agents here have repeatedly caught real deployed defects — but the review
angles were reinvented each session, and closed research questions have been re-run. This
document makes both durable.

**How to use it:** Section 0 first (or you lose the session to a hung `gcloud`). Section 1
when reviewing code or diagnosing an incident. Section 2 gives copy-pasteable standing
missions. Sections 3-4 gate any proposal to "go research X."

---

## 0. Day-one environment gotchas

- **`bq` CLI and `gcloud scheduler jobs list` HANG in this WSL environment.** Use
  `.venv/bin/python` with `google.cloud.bigquery`, and per-job
  `gcloud scheduler jobs describe`. Wrap every `gcloud` call in `timeout 60` (or 120);
  `run/sql describe`, IAM, and pubsub mutations hang on the response — the mutation often
  succeeded, so **verify before retrying**.
- **The local gcloud default project is WRONG** (has been `jett-prod`, `dmhr-platform`,
  `urcwest`). Always pass `--project=nba-props-platform --region=us-west2`.
- **Always filter partitioned tables on `game_date`** or you get a 400. Exception:
  `nba_predictions.ml_feature_store_v2` is **UNPARTITIONED** — every query full-scans it;
  keep queries narrow.
- **Schema traps:** `prediction_accuracy` has no `edge` / `hit` / `predicted_direction`
  columns; `player_prop_predictions`' line column is `current_points_line`;
  `player_game_summary.win_flag` is ALWAYS FALSE (use `plus_minus > 0`); best-bets JSON
  pct fields are 0-100, feature-store values are 0-1.
- **Prior-season rows in BOTH `prediction_accuracy` and `player_prop_predictions` are
  leak-contaminated.** Cross-season claims come from
  `nba_predictions.walkforward_sim_predictions` (leak-free) or they are not answerable.
- **Deploy verification is `./bin/verify-deploy.sh`** — `BUILD_COMMIT` on the
  *traffic-bearing* revision, never revision equality, never build status (class C).
- **The deploy gate runs `tests/unit/signals` on a deliberately thin dependency set.** A
  test placed there must import like a Cloud Function; one that imported
  `SignalBestBetsExporter` (pulls `google.cloud.storage`) turned three builds red
  (`682fb8c2`).
- **Pytest full runs cross-pollute.** Triage per-directory with `-p no:cacheprovider`; the
  "149 failures" of 2026-07-04 were pollution, not defects.
- **Ignore `.claude/worktrees/**`** in greps and file counts — agent worktrees are full
  repo copies (they bloated build contexts and re-triggered the symlink crash; now in
  `.gcloudignore`).
- Cloud Functions: `gcloud functions describe`, not `run services describe`, for env vars.
  Gen2 URLs are `FUNC-f7p3g7f6ya-wl.a.run.app`. Use `rsync -aL`, not `cp -r`, for `shared/`.

---

## 1. Defect-class taxonomy with detection recipes

Every class below has bitten this project at least twice. Frequency ranking from the
2026-08-21 meta-count: **silent no-ops ~16, single-episode calibration ~7, panic-tuning
~6, observation-mode debt ~5.**

### A. Silent no-op writer / dead pipeline
Every layer reports success while zero rows land.
- `br_roster_batch_processor` **never wrote a single row** — schema-misaligned five ways at
  once; routed to on `129a5bf9` (2026-01-13); last BR write is that same day. Dead seven
  months, all dashboards green. (SESSION-6 handoff §2.1)
- Two restored scheduler jobs had no-op bodies that would "run zero work and return
  success" (`156b3abd`).
- PBP loader: GCS data never reached BQ, Session 396 (`session-learnings.md`; memory:
  `pbp-loader-broken-since-nov.md`).
- Health-aware signal weighting: reads `signal_health_daily WHERE game_date = @target_date`,
  but **0 of 3,855** rows exist on their own game_date — fails open to 1.0 forever
  (`1e8fe7b7`).

**Mechanism:** the failure is swallowed inside a handler that logs-and-returns, or the
success is reported by a layer that only *enqueued* the work (Scheduler `:run` only creates
the execution).
**Recipe:** *Read the data, not the logs.* For every table a component claims to write:
`SELECT MAX(<write-timestamp or partition date>)` and compare against the invoker's cadence.
When something is dead, bisect by matching the last-write date against `git log` — the
SESSION-6 tiebreaker was a BigQuery last-write matching a routing commit **to the day**. For
a lookup, also check the *read* side: run the consuming query for a real date and confirm
non-empty.

### B. Deployed-but-never-invoked
Code is live, current, billed — and fires never.
- `decay-detection` (so BLOCKED-model auto-disable does not exist), `grading-gap-detector`,
  `validation-runner`, `grading-readiness-monitor`: HTTP-only, no scheduler, no event
  trigger, no in-repo caller.
- `weekly-retrain`: current code, deleted trigger — fires never.
- The full sweep found **29 components with no invoker**
  (`docs/02-operations/cf-scheduler-pairing-audit-2026-08.md`), including one FALSE positive
  (`news-fetcher`, alive via a Gen1 alias) — so verify both directions.

**Recipe:** For each deployed CF/service: find its scheduler (per-job `describe` — the list
command hangs), its `eventTrigger`, or an in-repo caller
(`grep -r "<function-url-or-name>"`). Then confirm with request logs: last invocation
timestamp within the expected cadence. Cross-check the pairing audit doc and
`ops/scheduler-catalog-2026.yaml` rather than rebuilding from scratch.

### C. Green build != deployment
- When a nested source build EXPIRES, **no revision is created**,
  `latestReady == latestCreated` passes on the OLD revision, and `gcloud functions deploy`
  prints `ERROR:` yet **exits 0**. `transition-monitor` and `grading-gap-detector` had green
  builds and deployed nothing.
- 2026-08-20: six functions "deployed" green and kept serving old code after Cloud Run CPU
  quota killed the revisions.
- A push whose only diff is under `tests/` triggers **nothing** — no trigger watches that
  path (SESSION-6 §1).

**Recipe:** `./bin/verify-deploy.sh` — assert `BUILD_COMMIT` on the traffic-bearing revision
equals HEAD's short SHA. Grep deploy output for `ERROR:` regardless of exit code.

### D. Guards that cannot fire
The protection exists, reads correctly, and is unreachable.
- The fleet-wide sanity floor: `run_single_model_pipeline` calls `aggregate()` once per
  model, so `n_models` is always 1 and the floor could never fire on the path that picks
  money (SESSION-6 §3.1; fixed by moving it to `_apply_fleet_sanity_floor`).
- `halt-state-stale` alert: a GT-36h threshold on a metric that only exists when the write
  *succeeds* — could never fire; rewritten absence-based (`33ba93a7`).
- `halt_envelope()` was a **stamp, not a gate** in all three NBA exporter call sites until
  2026-08-21 — a `manual` halt row published a full slate under `halt_active: true`.
- A Cloud Monitoring alert policy **cannot be created** for a metric never emitted; a
  rare-event guard needs the descriptor POSTed first (SESSION-6 §4.7 — "a plausible reason
  other documented alerts were never actually created").

**Recipe:** For each guard, answer in writing: *which call site reaches this code with
inputs that can trip it?* Then mutation-test it: force the condition (or disable the guard)
and confirm the alert/halt fires end-to-end. For alert policies: `GET metricDescriptors`,
confirm the type exists, then confirm the policy exists, is enabled, and has a channel.

### E. Self-referential calibration
The threshold was validated on data the system itself generated, so it measures our
configuration, not the world.
- The edge-collapse halt, wrong **three consecutive times** despite increasingly careful
  validation: Session 515 fired 865/865 days; the 2026-08-19 rewrite was calibrated on a
  fleet-swap artifact (42 line-hugging experiment `system_id`s moved the breaker); demoted
  2026-08-21 (`029b1d84`; full evidence in the `shared/config/edge_halt.py` docstring — the
  repo's best-written finding, read it as a model).
- Churn coupling of the metric: Spearman **-0.849** against the share of rows from
  <7-day-old `system_id`s. Measuring model *count* instead read -0.129 — a 7x under-read.
- Same shape, still unaudited: `MIN_EDGE=3.0` / OVER floor 6.0, `vegas_mae_7d < 4.5`
  (calibrated on ONE day), the paused canary's `avg_abs_diff < 1.2/1.4`.

**Recipe:** `PYTHONPATH=. python bin/validation/validate_guard_invariance.py` before
changing ANY guard threshold. Anchor on quantities the system did not generate: Vegas MAE
(model-free), `walkforward_sim_predictions` (fixed procedure). Coupling alone is not the
defect — a threshold close enough for churn to cross is.

### F. Convention collisions
Two encodings of the same concept meet without a converter.
- **Season start-vs-end year:** `br_roster_batch_processor` computed
  `season_year = start_year + 1` against a start-year-keyed table; separately, `--seasons`
  takes ENDING years, so `br-rosters-batch-daily` carried `--seasons=2025` and re-scraped
  the **2024-25** rosters every morning for six months — 655 wrong-season rows written and
  nobody noticed the year (SESSION-6 §2.2). Fix pattern: `--current-season` resolved at run
  time; **no scheduler carries a year again**.
- **0-1 vs 0-100 vs raw scales:** feature-store values are normalized 0-1 and signals died
  on raw-scale thresholds; JSON pct fields are 0-100.
- **game_id forms:** `nbac_schedule.game_id` is the 10-digit official ID, NOT
  `YYYYMMDD_AWAY_HOME` — a join silently lost seasons.

**Recipe:** grep the diff for `season_year`, `start_year`, `+ 1`, `pct`, `game_id`; for any
new threshold, `SELECT APPROX_QUANTILES(feature_N_value, 4)` first and confirm the scale;
for any season literal in a scheduler/config body, reject it — resolve at run time via
`shared/utils/season_utils`.

### G. Schema/writer drift
- `model_bb_candidates`: 47 schema columns, writer emits 30 — 15 silently NULL (Task #39).
- The br_rosters five-way misalignment (class A) is also this class.
- `validation/configs/raw/br_rosters.yaml` targets `nba_raw.br_season_rosters`, a table that
  does not exist — likely another silent no-op in the validation layer, flagged and NOT yet
  investigated (SESSION-6 §4.8).

**Recipe:** `python .pre-commit-hooks/validate_schema_fields.py`; for any writer, diff its
emitted field list against `INFORMATION_SCHEMA.COLUMNS`; for any table,
`SELECT COUNTIF(col IS NULL)/COUNT(*)` per column over recent write-days — 100%-NULL
columns are drift. For validation configs: assert every referenced table exists.

### H. Documented-but-not-real
The docs describe a system that does not exist; the code is the truth.
- Signal/filter counts in CLAUDE.md **and** MEMORY.md were both wrong until checked against
  `shared/registry/{signals,filters}.yaml` (33/50 and 48/20, not 28/32/25).
- `signals.yaml` marks six `_over` signals `active` that `aggregator.SHADOW_SIGNALS`
  excludes — the registry contradicts the executing code; the code wins.
- The best-bets algorithm version in CLAUDE.md was **65 versions stale**; "10 layers of
  cross-model monitoring" — at least three do not execute; `drawdown_halt.py`'s own
  docstring carried the false "16 exceeded the 15/day cap" claim (`pipeline_merger` didn't
  exist until `bfac51f2`, on 2026-03-08 itself).

**Recipe:** for any doc claim that gates a decision, read the constant / the live resource,
not the sentence. Session-5 rule: **"validate bodies against the code that CONSUMES them,
not the catalog they came from."** When you correct a doc, leave the correction inline with
the evidence (the `edge_halt.py` / `drawdown_halt.py` docstrings are the house style).

### I. Fail-open where fail-closed was intended (and vice versa)
- The halt gate (class D's stamp) was fail-open for the system's most important control.
- `_health_multiplier()` fails open to 1.0 on an always-empty lookup — inert forever.
- `dict.get(key, default)` returns `None` when the key EXISTS with value `None`.
- Deliberate fail-closed done right: `resolve_halt_state`'s chain (compute → carry forward
  <=3d → halt). Deliberate fail-open done right: the fleet floor fails open **with a
  Critical alert attached** (SESSION-6: "failing open is only defensible if someone finds
  out").

**Recipe:** enumerate every `except`, every default, every empty-result path in guard/gate
code and label each OPEN or CLOSED with a one-line justification. Any fail-open without an
alert is a finding. Test both directions: the guard firing, and its data source being
empty/stale.

### J. Refactor and entry-point traps
- `@functions_framework.cloud_event` ended up on the wrong function after splicing code
  above `main` — shipped once (`9f665f90`), then **re-created during SESSION-6's own
  testability refactor** and caught before commit. When you splice above `main`, check the
  decorator.
- Gen2 entry point is immutable — the `main = actual_func` alias pattern.

**Recipe:** after any edit to a CF `main.py`, confirm the decorator/alias sits on the
registered entry point: `grep -n "functions_framework\|^main" main.py` and eyeball adjacency.

### K. Orphaned-but-load-bearing / retention destroying state
- `1942a6b3` archived `docker/` as "orphaned" — twelve live deploy scripts hard-fail without
  it; eight still reference archived Dockerfiles (SESSION-6 §4.2).
- `54d08d56` deleted `shared/utils/bigquery_client.py` leaving six dangling symlinks;
  nothing imported it so nothing failed — but `gcloud builds submit` **crashed repo-wide for
  three months** (triggers check out from git and were unaffected, which is why it stayed
  invisible).
- The scheduler backup was **destroyed by a 30-day GCS lifecycle rule**;
  `gs://nba-scraped-data` deletes at 90 days — all older raw JSON is *gone*;
  `br-rosters-batch-daily`'s only surviving definition was the **commit message of
  `19eda492`**; `missing-prediction-check`'s CF source dir is deleted — it runs but cannot
  be redeployed.

**Recipe:** "orphaned" is a claim to verify: `grep -r` for the path in `bin/`,
`deployment/`, cloudbuild YAMLs before archiving. `find . -xtype l` for dangling symlinks
(now also a pre-commit hook). `gsutil lifecycle get` on ANY bucket used as a backup.
Configs and job definitions live in git, and commit messages should be written as the last
surviving copy — because one was.

### L. Tests that prove nothing
- `mock.patch.dict('sys.modules')` with no arguments patches nothing — the tests passed
  while executing the real `emit_metric`; on CI with ADC it would have written production
  time series.
- The first draft of the fleet-floor tests **certified dead semantics as verified
  behaviour** — the code under test was unreachable (class D).

**Recipe:** **mutation-check every new test**: disable the guard / break the behaviour and
confirm the test fails. Four of SESSION-6's tests passed first-run against working code;
only mutation proved they measured anything. Assert mocks were *called*. Ask what call site
reaches the code before writing the assertion.

### M. Leak-contaminated evaluation & single-episode calibration
- The "85% HR" was data leakage (Session 458); true raw HR is 53.4% at edge 3+. Both
  prediction tables' prior seasons are contaminated (Section 0).
- Window functions in derived features must use `1 PRECEDING`, never `CURRENT ROW` — one
  leak became 16 in the repo-wide sweep (memory: `nba-feature-leak-audit.md`).
- Single-episode/panic tuning: `high_spread_over_would_block` flipped 3x in 19 days on tiny
  samples; `b2b_under` and `downtrend_under` were both killed on N<=6 and both turned out
  ~58-63% over 5 seasons; drawdown thresholds are honestly N=1 and say so.

**Recipe:** any raw-model HR >60% cross-season is presumed leaked until reproduced on
`walkforward_sim_predictions`. `grep -rn "CURRENT ROW"` in feature SQL. Never demote an
UNDER signal on N<30; never tune a guard on a bad week; pre-register thresholds before
looking.

---

## 2. Standing agent missions

Paste these into a fresh session (each assumes Section 0). Missions 1-4 are mechanical;
5-8 are judgment missions.

### Mission 1 — Deploy-integrity check
**When:** end of every session that pushed; after any quota incident.
**Prompt:** "For every service/CF the session's pushes could have touched (triggers watch
`shared/` too), verify deployment: run `./bin/verify-deploy.sh`; independently assert
`BUILD_COMMIT` on the *traffic-bearing* revision equals HEAD's short SHA; grep the
build/deploy logs for `ERROR:` regardless of exit code. Remember the four trigger-less CFs
(`halt-state-writer`, `expected-outputs-planner`, `phase-completion-reconciler`,
`gap-detector`) deploy only via `./bin/deploy-function.sh`, and that a tests-only push
triggers nothing."
**Evidence:** table `service | BUILD_COMMIT | HEAD | verdict`. **Clean:** every row matches,
or a named stale service with the redeploy command. Known permanent strays:
`analytics-processor`, `nba-reference-service`, `prediction-coordinator-dev`.

### Mission 2 — Invoker-pairing sweep
**When:** pre-season (before each resume wave); after any scheduler or CF change; quarterly
off-season.
**Prompt:** "Rebuild the CF-to-invoker pairing: for every deployed function and Cloud Run
service, identify its scheduler (per-job `describe` — the list command hangs), event
trigger, or in-repo caller, and its last actual invocation from request logs. Diff against
`docs/02-operations/cf-scheduler-pairing-audit-2026-08.md` and
`ops/scheduler-catalog-2026.yaml`. Check both directions — `news-fetcher` was a false
positive alive via a Gen1 alias. Also flag ENABLED jobs whose *partner* is paused or
deleted (the `master-controller-hourly` / `execute-workflows` split)."
**Evidence:** component → invoker → last-invocation table; deltas vs the audit doc.
**Clean:** zero uncovered components outside the documented-exceptions list, zero orphaned
ENABLED jobs.

### Mission 3 — Data-liveness audit (the silent no-op hunt)
**When:** weekly in-season; monthly off-season; ALWAYS post-incident.
**Prompt:** "For each production table with an expected write cadence (start from CLAUDE.md
Key Tables + `nba_raw` sources + the `expected_outputs` phase grid), query the max write
timestamp with the Python BQ client and compare to cadence. For anything stale: bisect
against `git log` — match the last-write date to a commit (the br_rosters kill was dated to
`129a5bf9` this way). Then check the *consumers*: run each stale table's main consuming
query for a live date and record whether it silently returns empty. Do not trust logs or
scheduler success states at any step."
**Evidence:** table → last write → expected cadence → verdict, plus a suspect commit for
each stale one. **Clean:** everything within cadence or explained by `off_season` / PAUSED
state.

### Mission 4 — Guard reachability & mutation audit
**When:** pre-season; after ANY change to a guard, gate, alert, or threshold.
**Prompt:** "Enumerate every guard/gate/alert in the halt-and-safety surface
(`shared/config/edge_halt.py`, `shared/config/drawdown_halt.py`, `halt_state_writer`, the
aggregator sanity guards, `_apply_fleet_sanity_floor`, `monitoring/alert-policies/*`). For
each: (a) name the call site that reaches it with trip-capable inputs — 'unreachable' is a
Critical finding (the fleet floor was unreachable on the money path with n_models always 1);
(b) mutation-test: force the condition and confirm the halt/alert fires end-to-end; (c) for
alert policies, confirm the metric descriptor exists, the policy is enabled, and a channel
is attached; (d) label every failure path fail-open or fail-closed and flag any fail-open
without an alert; (e) if any threshold changed, run
`bin/validation/validate_guard_invariance.py` first and refuse the change if lived
behaviour crosses the bar."
**Evidence:** per-guard call-site proof, mutation transcript, open/closed labels.
**Clean:** every guard demonstrably fires; every fail-open has a listener.

### Mission 5 — Docs-vs-code truth reconciliation
**When:** monthly, and before any decision that leans on a doc claim.
**Prompt:** "Reconcile the load-bearing claims in CLAUDE.md and MEMORY.md against the code
and live state: signal/filter counts vs `shared/registry/{signals,filters}.yaml`; registry
`active` entries vs `aggregator.SHADOW_SIGNALS`; the algorithm version constant in
`ml/signals/pipeline_merger.py` vs the doc; the deploy/trigger lists vs live Cloud Build
triggers; scheduler claims vs per-job describes; 'documented' alerts vs actually-created
policies. Where doc and code disagree, the code is the truth — correct the doc *in place,
with the evidence*, in the style of the `edge_halt.py` docstring. History says the counts,
the auto-deploy claim, and the algorithm version have ALL been wrong before."
**Evidence:** contradiction list with the code-side truth for each. **Clean:** zero
contradictions, or corrections committed.

### Mission 6 — Pre-season readiness sweep
**When:** Sept 1, Oct 1, and T-3 before each resume wave.
**Prompt:** "Verify season-rollover readiness: `nba_players_registry` has current-season
rows (blast radius of a miss is in the 2026-08-22 SESSION-5 handoff §4 — everything stays
green while exporters serve last season); `SEASON_CALENDARS` covers the new season; grep for
hardcoded season dates; no scheduler/config body carries a literal year (class F); the
enabled fleet is not entirely models trained into the prior collapse window; both pipeline
canaries UNPAUSED before Wave C; the wave gates from the session-5 §6 runbook (paired jobs,
`BUILD_COMMIT` checks, drives-not-0.0 on `nba-tracking-stats-daily`, both grading backstops,
the three `America/Los_Angeles` jobs left un-normalized). The first `br-rosters-batch-daily`
run must write ~600 rows with `season_display='2026-27'` AND `season_year=2026` — anything
else means the season convention moved again."
**Evidence:** checklist with query outputs. **Clean:** all gates green with numbers
attached, not assertions.

### Mission 7 — Threshold provenance review
**When:** before ANY numeric threshold change; post-incident before any "tune the guard"
response.
**Prompt:** "For the proposed threshold change: identify the calibration episode (which
days, what N); state whether the calibration data was generated by the system under test
(class E); run `validate_guard_invariance.py`; check git history for how often this number
has moved (`high_spread_over_would_block` flipped 3x in 19 days — that pattern is
disqualifying); and check the module docstring for standing do-not-tighten warnings
(`edge_halt.py` and `drawdown_halt.py` both carry them, and `drawdown_halt.py` documents why
chasing the 03-08 slate by lowering the bar is the wrong trade). If the calibration is a
single episode, the default answer is NO."
**Evidence:** provenance paragraph + invariance output. **Clean:** either the change clears
all four checks or it is refused with the reason on record.

### Mission 8 — Red-team the reviewers
**When:** after any multi-agent review session, before its conclusions enter MEMORY.md or a
handoff.
**Prompt:** "Take the previous review round's headline claims and re-verify each against
primary data (BigQuery, live GCP state, the code) — not against the review's own artifacts.
Deliver a per-claim verdict: CONFIRMED / OVERTURNED / NARROWED, with the query or file that
decides it. The record justifying this: the 2026-08-20 ten-agent review's own
fleet-composition finding was directionally right but measured model *count* instead of
churn and under-read the coupling 7x; the 2026-07-21 35-agent audit shipped 2 wrong findings
(grading dedup, zero-tolerance severity); SESSION-6's reviewer caught a `data_hash` MERGE
gate that would have seeded the registry from three players and reported success; and three
rounds of review in one session each found things the previous round missed. Also verify the
review's *statistics* support its conclusions — `role_player_under_low_edge` was removed
citing 'exactly break-even' at p=0.98."
**Evidence:** claim-by-claim verdict table. **Clean:** all CONFIRMED — but a clean round on
the first pass is itself suspicious; say so if the round found nothing.

---

## 3. The "do not re-test" list

Closed questions. Re-opening any of these requires *new data the prior test could not see*,
not a new analysis of the same data. Where sources disagree, both are shown.

### Model & features — CLOSED
| Question | Answer | Evidence |
|---|---|---|
| Can adding model features help? | **NO — 3rd independent confirmation.** Held-out residual R² = **+0.004 (~0)**. The edge is in selection/signals. | memory `frame-breaking-features-done-2026-06.md`; `docs/09-handoff/2026-06-23-SESSION-4-frame-breaking-RESULT.md` |
| 80+ training/loss/feature/config variants | All negative or neutral — that list is authoritative. | `docs/06-reference/model-dead-ends.md` |
| Is V12_NOVEG the strongest feature set? | ⚠️ **SOURCES DISAGREE.** CLAUDE.md [MODEL] still says "strongest, adding features hurts"; MEMORY.md marks that SUPERSEDED — leak-contaminated runs; clean re-run shows v12_noveg–v19 **within noise**. Practical upshot is identical: don't run feature-set experiments. |
| GBDT fleet diversity via feature sets or algos? | **DEAD.** CatBoost/LGBM/XGB converge to r~0.93-0.99 regardless of features; MQ quantile heads are clones too (r=0.932) — do not retry quantile heads. | memory `fleet-diversity-and-cadence.md` |
| Retrain cadence grids (7/14/21/28d) | Done. <=28d ~ weekly on HR; 14d adopt-eligible on COST only; only a true freeze degrades. **Do not re-run the grids.** | memory `fleet-diversity-and-cadence.md`, `staleness-arm-2026-06.md` |
| Did staleness cause the March collapse? | **NO** — no cadence arm reproduces it. ⚠️ Nuance: `cap_to_pre_late_season` is REFUTED as a *profit lever* but stays as inert insurance — "don't relax" and "don't promote as lever" are both true. | memory `staleness-arm-2026-06.md` |

### Markets & expansion — CLOSED
| Question | Answer | Evidence |
|---|---|---|
| MLB pitcher strikeouts | **No edge, confirmed 5x, externally corroborated. Stay halted; info product only.** | memory `mlb-strikeout-project.md` |
| 28 sport x market expansion candidates | ALL SKIP (52-agent, unanimous across 3 lenses). Pipeline is structurally points-locked. | memory `expand-vs-improve-2026-06.md` |
| Naive MLB batter-prop bias | All 13 markets failed the naive scan (-0.6 to -7.1pp both seasons). Only a *conditional* edge remains open, gated behind backtest-first. | memory `next-market-opportunity-2026-06.md` |
| Kalshi threes / player props | Spreads (30-39c) absorb the edge in every direction; pricing dead since 2026-03-13. | memory `kalshi-player-props-structure.md` |
| Reddit/social sentiment | Team-level, already priced, near-zero for props. | `model-dead-ends.md` |

### Signals, angles, OVER/UNDER structure — CLOSED
| Question | Answer | Evidence |
|---|---|---|
| Is high-edge OVER a money zone? | **NO — CORE CORRECTION.** Edge>=6 OVER = 38.9% in the 4 prior seasons; 2025-26 was an anomaly. UNDER edge>=6 IS durable (~61%). | `docs/09-handoff/2026-06-23-edge-calibration-RESULT.md` |
| A forward-detectable OVER regime gate? | REFUTED — keep the static edge-6 floor. | memory `over-gate-refuted-highline-additive-2026-06.md` |
| Cross-book OVER signals | 2025-26-only artifacts. | `docs/09-handoff/2026-06-23-crossbook-OVER-multiseason-RESULT.md` |
| 7 structural angles | Star-RETURN, opposing-star-OUT, minutes-trending-up (inverts), day-after-blowout, rim-protector-OUT, outlier-corrective, long-gap-return: all negative. | memory `nba-angles-tested-2026-05-23.md` |
| Research Wave 1 (6 pre-registered tests) | 0 clean passes. The one actionable output is an INVERSION: low-sigma low-edge UNDER is the WORST, staged as a shadow block. ⚠️ Wave 1 "vindicated" the edge auto-halt — **SUPERSEDED** by the 2026-08-21 demotion. | memory `research-wave1-results-2026-06-27.md` |
| Narrative/news proxies | 5 FAIL, 1 inconclusive; **do NOT build a news scraper**. Survivor wired SHADOW: `national_tv_under`. | memory `narrative-proxies-discovery-2026-06-28.md` |
| Confidence surfaces | Roster zero-sum DEAD; fleet-disagreement "trust" DEAD. Survivor: `line_converging_under` CLV gate. | memory `confidence-surface-exploration-2026-06-27.md` |
| `combo_3way` at 95.5%? | ⚠️ **SOURCES DISAGREE.** CLAUDE.md still shows 95.5% all-time; the gate-check found 38 fires/season at **60.5%** (33% in March) — and the current all-clone fleet cannot fire it at all. Trust the gate-check. | memory `fleet-diversity-and-cadence.md` vs CLAUDE.md [SIGNALS] |
| bench_under 76.5% | Look-ahead bias (post-game `starter_flag`); pre-game proxy = 51.8%. | CLAUDE.md BB-simulator section |

### Infra & eval — CLOSED
- **The 2026 "edge collapse" never existed.** Do not re-investigate, do not re-adopt
  1.4/10%, do not tighten 0.35/0.30% — the case is the `shared/config/edge_halt.py`
  docstring (`029b1d84`).
- **Do not tune drawdown/volume thresholds on a bad week** — N=1 episode; the peak reset and
  the 3-day volume window are load-bearing. Do not "fix" the distinct-triple volume query
  without re-measuring thresholds (measured clean: 0/203 player-days multi-line).
- **NBA training-leakage claims are FALSE post-`60279b20`**; the leak audit is DROPPED. The
  *evaluation-data* contamination (Section 0) is a separate, still-true fact.
- Grading is aligned with book practice; 63.85% BB HR is real. Two of the 35-agent GCP
  audit's findings were WRONG (grading dedup, zero-tolerance severity) — don't resurrect
  them.

---

## 4. Open questions worth an agent's time, ranked

Ranked by "changes what we do before ~Nov 15." The honest frame: **most remaining questions
are execution and instrumentation, not discovery.**

1. **Invariance-audit the unaudited thresholds:** `MIN_EDGE=3.0`, OVER floor 6.0,
   `vegas_mae_7d < 4.5`, canary `avg_abs_diff < 1.2/1.4`. The exact failure shape that broke
   the auto-halt three times; the tool exists and it is one query per metric. A fail on
   `vegas_mae<4.5` (calibrated on ONE day; healthy lows reach 4.48) would change a live gate
   before the opener. Prior: a spot check of `MIN_EDGE` found the mechanism real but no
   drought risk today — expect narrowings, not bombshells.
2. **Design the export-time volume cap in `pipeline_merger`.** Named in both August handoffs
   as *the only thing* that can catch a one-slate blowup on day one (9.2u of March's 14.3u
   died on a single slate the 5 AM guards cannot see). The open question is the trim rule
   (graceful top-N vs zero) and its threshold — answerable from `signal_best_bets_picks`
   2026 distributions now, and it must pass Mission 7.
3. **Ship the large-edge degeneracy guards** — the symmetric fleet bound at 4.5 in
   `edge_halt.py`. The five-season measurement is already done in that docstring: every
   median-edge >=5.0 day belongs to four known pathology episodes; calibrated fleets top out
   at 4.52. Implementation + Mission-4 mutation proof, not research. (The per-model cap 5.5
   and spread floor 2.0 shipped 2026-08-21.)
4. **Settle the health-multiplier fork: is HOT/COLD predictive at lag-1?** The documented
   weighting has never applied once (class A); fixing the read might make things worse.
   Answerable now from `signal_health_daily` (lag-1) joined to graded picks. Either way, dead
   code documented as live behaviour should not survive into the season.
5. **Sweep the validation layer for silent no-ops**, starting from
   `validation/configs/raw/br_rosters.yaml` → nonexistent `nba_raw.br_season_rosters`. One
   confirmed dead config in a layer whose whole job is catching dead pipelines predicts more.
6. **Data-readiness check for the approved Sept REB/AST backfill:** confirm reb/ast line
   volume and label coverage are sufficient given the data clock started 2026-04-06 — before
   anyone spends a week building against thin, playoff-biased data.
7. **Task #39: the 15 silently-NULL `model_bb_candidates` columns** — write or drop. Cheap;
   matters because that table is the provenance record the post-incident missions rely on.

**Explicitly not worth running now:** any model-feature experiment (closed 3x — needs *new
data*); fleet-diversity model research (the 90-day lever is enabling one existing non-clone,
a task not a question); true-CLV cross-season confirmation and the >=0.5-against drop rule
(**pre-registered, needs live 2026-27 closes — no backtest can advance it**); all
shadow-signal promotions (every one is live-N-gated at N>=30; the only pre-season work is
verifying the graded-N tracking will accrue); the same-game co-directional Kelly haircut
(data-blocked until mid-season); the MLB batter conditional-edge backtest (violates the
improve-the-core decision; the line scraper has been dormant since 2025-09-28).

---

**Left out deliberately:** MLB-specific defect instances (same classes, separate `mlb-*`
memory files); the GCP cost-audit material (closed —
`docs/09-handoff/2026-07-27-SESSION-7-CLOSEOUT-HANDOFF.md`); the 59-job scheduler restore
detail (`ops/scheduler-catalog-2026.yaml` + the two August handoffs); per-signal weight
history (`SIGNAL-INVENTORY.md` is the registry-validated source). This playbook indexes them
rather than repeating them.

*Created 2026-08-22. Every SHA and path cited here was verified against `git log` and the
filesystem at creation time.*
