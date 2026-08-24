# Session 8 — start here

**Today 2026-08-24. Opener Tue 2026-10-20 (57 days). Seed window Oct 1-19, drop-dead Oct 6.
First predictions ~Nov 3-4. First realistic picks ~Nov 15.**

Previous: `2026-08-22-SESSION-7-START.md` — still the live plan document. Read its §1, §4 and
§6; this document records what session 7 executed and what it learned, and does not repeat them.

---

## 1. The one thing to carry forward

Session 7 set out to fix a signal alias and ended up finding **eleven defects**, of which
**seven reported success while failing**. That ratio is the finding, not any individual bug.

The pattern has a shape, and it recurred at every layer:

| Layer | How it lied |
|---|---|
| A processor | returned `status: 'success'` with `records_processed: 0` after the write failed |
| A CLI | exited `0` on `status: failed` |
| Four Cloud Functions | returned HTTP 200 on total failure, one of them commented "so scheduler doesn't retry" |
| Grading | turned BigQuery `NotFound` into `[]`, which the caller renders as "nothing to grade" |
| `ErrorContext` | replaced every exception with `TypeError`, so `except <SpecificError>` could never match |
| A test fixture | assigned an attribute the constructor never created, so 12 tests passed against an object production could not build |
| Nine tests | called methods deleted 209 days earlier, and were simply left red |
| `--test-mode` | isolated three of four tables and wrote the other two to production |

**When something on this system reports success, that is weak evidence.** Session 7's most
productive move, every single time, was to run the thing and read the data rather than read the
code. Second most productive: mutation-test every assertion, because three of session 7's own
tests and two of its own mutations were silently vacuous until checked.

---

## 2. State right now

### Everything is committed and pushed. HEAD `bc57ecbc`.

Working tree clean. Nothing is waiting to be committed.

### ⚠️ Deploy state is PARTIAL — finish this first

`bc57ecbc` touches `shared/utils/error_context.py`, which fires **26 Cloud Build triggers**.
That is a bigger fan-out than the 8-commit batch that exhausted the Cloud Run CPU quota on
2026-08-20 and left six functions green-but-stale.

**Step A1 for session 8:**

```bash
./bin/verify-deploy.sh                      # defaults to the halt-gate set
# and widen it — this commit reaches far more than the default four:
./bin/verify-deploy.sh phase6-export post-grading-export live-export \
    prediction-worker prediction-coordinator nba-grading-service weekly-retrain \
    nba-scrapers nba-phase2-raw-processors nba-phase3-analytics-processors \
    nba-phase4-precompute-processors
```

A green build is not a deployment. Compare `BUILD_COMMIT` on the traffic-bearing revision
against `bc57ecb`.

**Two of the five Phase B fixes cannot deploy from a push at all** — `halt-state-writer` and
`expected-outputs-planner` have no Cloud Build trigger:

```bash
./bin/deploy-function.sh halt-state-writer
./bin/deploy-function.sh expected-outputs-planner
```

Until those run, three of five fixes are live and two are not.

---

## 3. What session 7 shipped

Eleven commits, `53265cf4..bc57ecbc`. Grouped by what they protect.

### The money path

- **`02511358`** — two signal queries selected a feature other than the one they named.
  `feature_18_value AS opponent_pace` (f18 is `pct_paint`, 0-1; pace is f14) and
  `feature_53_value AS prop_over_streak` (f53 is `line_vs_season_avg`; streak is f51), in both
  live best-bets query paths.

  `slow_pace_under` disqualifies when `opp_pace > 99.0`, which a 0-1 variable can never exceed,
  so it tagged **every** UNDER at a pinned 0.90 confidence and its recorded 56.6% HR was the
  all-UNDER base rate. `fast_pace_over` was really asking "are ≥75% of this player's shots in
  the paint"; Session 387 saw it never firing and *refitted the threshold* (102 → 0.75) to the
  wrong column instead of questioning the alias.

  Neither touches money today — both are in `SHADOW_SIGNALS`, and `_score_candidate`
  (`aggregator.py:1764`) filters shadow tags out before weights apply, so `fast_pace_over`'s 2.5
  in `OVER_SIGNAL_WEIGHTS` is unreachable. The reason to fix now was the **promotion pathway**:
  both carry live `N>=30 in 2026-27` gates, and promoting `slow_pace_under` would add +1
  `real_sc` to every UNDER pick, recreating through a bug the exact SC inflation `real_sc`
  exists to prevent. DATA CUTOVER recorded in `signals.yaml` `promotion_gate` for both.

  Prevention: `tests/unit/signals/test_feature_alias_contract.py`. The hard rule carries **no
  allowlist** — *an alias must never be the canonical name of a different feature index*. That
  isolates the dangerous class with zero false positives where exact matching drowns in
  legitimate shorthand (`avg_pts_vs_opp`). Five near-misses outside the money path are frozen in
  `QUARANTINED_NEAR_MISSES` as **unverified** — see §5.

### The Oct 1-19 roster seed

Session 6 found two blockers here and said assume a third. **There were four more**, all found
by running the rehearsal 5 weeks early rather than reading code.

- **`6c712fde`** — `RosterRegistryProcessor.__init__` never created `source_dates_used`, but
  `get_current_roster_data()` calls `.update()` on it unconditionally at `:183`. **Every real
  run crashed there before writing a row**, and exited 0. The test suite could not see it: the
  `processor` fixture assigned `proc.source_dates_used = {}`, creating what the constructor
  never created. Proven by mutation — 12 of that module's tests still passed with the fix
  reverted.
- **`19d731d6`** — a failed write reported `success` and exited 0. `status` now derives from
  what reached BigQuery; the CLI exits 1 on non-success. Verified live: rehearsal run 2
  correctly reported `failed — 0 reached BigQuery` where it would previously have said
  `success, Records processed: 0`.
- **`df868509`** — `unresolved_player_names` was never written. The date converter was an
  *optional* parameter: `normalizer.py:579` passed it, `registry_ops.py:144` did not, so raw
  `date` objects hit `load_table_from_json`, failed, and were swallowed.
- **`3fe0cfe8`** — **`--test-mode` wrote two tables to production.** The base class computes all
  four table names test-aware; `roster_registry_processor.py:130` passed `self.table_name`
  (correct) alongside hardcoded `"nba_reference.player_aliases"` and
  `"nba_reference.unresolved_player_names"`. This session put 62 rows into the live table before
  it was noticed. **Deliberate asymmetry retained and pinned by a test:**
  `GamebookPrecedenceValidator` still reads production `processor_run_history` under test mode —
  it only reads, the check is meaningless against an empty table, and the test-suffixed table is
  never created, so pointing it at `self.run_history_table` would trip its fail-closed path and
  block every rehearsal. **Rule: reads may cross into production, writes may not.**
- **`9e115dc1`** — real coverage for the three source handlers (see §4).

**The rehearsal passed.** `Status: success, Records processed: 522`, 522 players / 29 teams.
The Oct 1-6 path is proven end-to-end; Oct 1 is now a data question, not a machinery question.

### Failure reporting

- **`bc57ecbc`** — Phase B code half. All four §6 claims verified before touching anything, per
  §7; all four confirmed, one worse than reported. `weekly_retrain` → 500 (and a broken alert
  channel now logs instead of `except Exception: pass`), `expected_outputs_planner` → 500 on any
  planning error, `halt_state_writer` → 500 when a sport fails (its docstring had promised
  exactly that for years while the function had one return, a 200), and `prediction_accuracy`
  now propagates infra errors instead of rendering them as "nothing to grade".

  **Then removing that swallow exposed the fifth defect, and it is the important one.**
  `ErrorContext.__exit__` raised
  `TypeError: log_error() got multiple values for keyword argument 'error_type'` — from
  `__exit__`, so it **replaced the exception being handled**. Every error passing through an
  `ErrorContext` reached its caller as a `TypeError`. Structured error logging never ran, and
  **`except <SpecificError>` downstream of an `ErrorContext` could never match.** That silently
  disabled Session 478's `BadRequest` re-raise — the fix added after a six-day silent grading
  outage — because the query runs inside an `ErrorContext`. **35 production files use it.**

### Documentation and infrastructure

- `53265cf4` agent research playbook · `631e5139` `keys/` no longer uploadable into build
  contexts · `dd67633d` registry `processor_run_history` dataset fix · plus handoff updates.

---

## 4. The test suite lies too — and the fix generalises

`tests/processors/reference/` went **16 failed / 48 passed → 4 failed / 91 passed** with **no
production code changed**. Three independent defeats, all in one directory:

1. **Nine tests dead for 209 days**, calling `_get_espn_roster_players_strict` and two siblings.
   `45953cb6` (2026-01-25) moved that logic into `sources/*.py` and never updated them. The
   three handlers that decide whether the seed finds 600 rows or 113 had **zero executing
   coverage for seven months**, including `test_fallback_within_7_days`.
2. **Stubbing the `google` namespace in `sys.modules`.** Makes `except GoogleAPIError` raise
   `TypeError: catching classes that do not inherit from BaseException`, so error paths are
   structurally untestable — and it **leaks session-wide**, whether set in `pytest_configure`
   (a session hook) or at test-module scope. Removing the two instances here took a combined
   `reference + unit/signals` run from **7 failed / 528 passed to 4 failed / 531 passed**, and
   the two tests that unbroke were in `unit/signals`, unrelated to reference processors.

   **This is a concrete, measured mechanism for the repo-wide "cross-suite pollution" the
   per-directory triage habit exists to dodge.** `tests/processors/reference/README.md` had
   documented the stub as recommended practice, which is how it reached 26 files.
3. **The fixture repaired the object under test.**

New tests key to the **public contract** —
`get_roster_players(season_year, data_date, allow_fallback) -> (players, actual_date, matched)` —
so a rename cannot silently delete the coverage again. Shared behaviour is parametrized across
all three handlers; per-source specifics are asserted individually because those are what differ:

| Handler | Table | Date column | Window |
|---|---|---|---|
| NBA | `nbac_player_list_current` | `source_file_date` | **7d** + `is_active` |
| ESPN | `espn_team_rosters` | `roster_date` | 30d |
| BR | `br_rosters_current` | `last_scraped_date` | 30d |

Two load-bearing behaviours are now pinned: the fallback must never select data recorded **after**
the requested date (a point-in-time seed borrowing future rosters is leakage), and **NBA.com's
7-day window must stay stricter than the other two** — tidying all three into one shared constant
would let a three-week-old official player list count as current.

---

## 5. Open items, ranked

### Do first (finishes work already started)
1. **Verify the 26-build fan-out and run the two manual deploys** — §2.
2. **Phase B, alerting half.** Rebuild the `[WARNING] NBA Stale Predictions` policy on a metric
   that exists (it matches the log string `"Prediction saved successfully"`, which appears
   nowhere in the repo). Wire the orphaned metrics, `halt_gate_overridden` above all — it is the
   emergency-override tattletale and nobody watches it. Fix the two phase orchestrators' unset
   Slack webhooks (35 dead call sites). Add an absence alert on `expected_outputs` production
   itself. Resume the two paused canaries. Needs GCP writes and notification-channel decisions;
   **exactly one channel exists** (Slack "#alerts") and four policies have zero channels.
3. **The four remaining monitoring CFs that ACK their own crashes** — the rest of the return-200
   family, not yet touched.

### Do before October
4. **The Nov-1 season-flip family (7 exporters).** Labels flip in October, windows flip Nov 1, so
   **Oct 20-31 the public record blends ~650 stale 2025-26 picks under a `2026-27` label.**
5. **`team_context.py:771,877,983`** — three hardcoded `'2025-10-22'` season windows, live daily
   in Phase 3, feeding stars-out context into predictions.
6. **`fleet_blocked` reachability.** Verified: it has never fired (0 all-BLOCKED days in 106),
   because `model_performance_daily` is populated from `prediction_accuracy` over a trailing 30
   days — every experiment run, not the enabled fleet — so the denominator was 24-58 models.
   Replayed on the three actually-enabled clones it **fires 7 of 19 covered days**, including a
   7-day consecutive run. Unreachable today only by accident of denominator pollution, and flips
   to firing once the fleet is the intended three. **Decide before season week 2.**
7. **The export-time volume cap in `pipeline_merger`** — still the only thing that could catch a
   one-slate blowup on day one; both breakers evaluate at 5 AM on yesterday's data.
8. **BigDataBall NBA play-by-play season pass.** Not listed on the store as of 2026-08-22 (NFL,
   WNBA, MLB are) — almost certainly a calendar artifact. **Check mid-September; purchased AND
   delivery-proven by Oct 1.** It is a supply dependency on the critical path:
   `nba_raw.bigdataball_play_by_play` feeds `ml_feature_store_processor` and
   `player_game_summary`, and without it feature 6 `shot_zone_mismatch_score` defaults, which
   under `HARD_FLOOR_MAX_DEFAULTS = 0` blocks **every player**. A lapsed pass produces zero picks
   on exactly the schedule §1 of the session-7 doc says zero picks are expected.

### Recorded, unverified, unowned
9. **Five quarantined feature-alias near-misses**, frozen in `QUARANTINED_NEAR_MISSES`: four in
   `bin/backfill_experiment_features.py` (f44 as `minutes_load`, f6 as `pace`, f42 as
   `spread_mag`, f4 as `pts_std`) and one in `ml_feature_store_validator.py` (f13 as `opp_pace`).
   Each may be a real bug or deliberate shorthand. None is on the money path; none was verified.
10. **The AI name resolver is failing continuously and silently.**
    `nba_reference.unresolved_player_names` holds **590 rows** whose `notes` begin
    `"AI call failed: Error code: 400 … invalid_request_error … 'Your cred…'"`, plus 8 with
    `529 overloaded`. Ongoing daily — 7 on 08-23, 22 on 08-22, 19 on 08-21. **The failure is
    written into a data column instead of raised**, which is the §1 pathology in a place Phase B
    does not list. Not in `ops/scheduler-catalog-2026.yaml`; no model id under
    `tools/player_registry/`. What invokes it, and with what credentials, is unidentified.
11. **24 test files still stub the `google` namespace** (`grep -rn "sys.modules\['google" tests/`).
    Each needs its own before/after measurement. Doing them all would likely let the full suite
    run green, which makes every future change cheaper to verify.
12. **The registry Cloud Run job is a trap.** `nba-players-registry-processor-backfill` serves a
    2025-09-26 image and **cannot be rebuilt from the repo** — `deploy_reference_processor_backfill.sh`
    names `roster_registry` in its usage, but the `job-config.env` it discovers has never existed
    in any commit. `704b28b8` (2025-09-27) deleted the pre-split `deploy.sh` and created
    gamebook's replacement without a roster equivalent. Anyone who runs that job gets code
    predating all four registry fixes. **Write the config or delete the job.**
13. **Four gamebook-registry test failures** — different processor, genuinely different causes
    (date-vs-string assertions, empty enhancement maps, temporal ordering).
14. **§6 of the session-7 doc is still largely un-red-teamed.** Several headline claims have
    failed verification (§2's "nothing references the processor", decision B's framing), and
    several were confirmed exactly. The true hit rate is unknown and it is driving the plan.

### Closed
- Decision B (`opponent_pace`) — fixed, and the trade-off it posed did not exist.
- Decision A (credential rotation) — **owner deferred 2026-08-23.** Config is fixed in
  `631e5139`; revisit with the September BigDataBall work, where rotate-and-prove-delivery is one
  job rather than two.
- The 62 production rows — **deleted 2026-08-23** with owner approval. Table 9,567 → 9,505.
- The registry deploy path — **resolved: run it locally.** No trigger watches
  `data_processors/reference/**` (confirmed empirically: `dd67633d` fired zero builds).

---

## 6. Running the seed rehearsal

This is the highest-value diagnostic in the repo and it now works. It found four defects.

```bash
GCP_PROJECT_ID=nba-props-platform PYTHONPATH=. .venv/bin/python \
  data_processors/reference/player_reference/roster_registry_processor.py \
  --season-year 2025 --date 2025-10-20 --allow-backfill --allow-source-fallback --test-mode
```

- **`GCP_PROJECT_ID` is mandatory.** `registry_processor_base.py:160` calls `bigquery.Client()`
  with no project and falls back to the ADC default, which on this machine is **`urcwest`**. The
  Cloud Run job injects the var; the local path — which is the chosen path for Oct 1-6 — does not.
- **The processor does not create its target tables.** `--test-mode` writes to
  `nba_reference.*_test_FIXED2` (the suffix is hardcoded despite being named `timestamp_suffix`,
  so runs share one table set and accumulate). If they are missing, recreate from production:
  `CREATE TABLE IF NOT EXISTS …_test_FIXED2 LIKE …`. They had drifted 8 columns behind
  production and silently failed every MERGE.
- Takes ~10-15 minutes. Expect `Status: success`, ~522 rows for that date.
- **Do not read 522 as the Oct-2026 number.** At 2025-10-20 only ESPN contributed: NBA.com had
  one scrape in the whole Sep 25 – Nov 15 window (2025-10-01, 113 rows) so its 7-day fallback
  caught nothing, and BR's season-2025 rows carry `last_scraped_date` 2026-01-13, *after* the
  target. That is an artifact of replaying a point-in-time process against `_current` snapshot
  tables — **but it is a useful artifact: a single-source seed still reported success with 29 of
  30 teams.** Check per-source contribution and team count on the real run.

---

## 7. Working discipline that earned its keep

- **Run the thing; read the data.** Every seed-path defect was found by executing, none by
  reading. Session 6's lesson repeated: what broke the tie was the last write date in BigQuery.
- **Mutation-check every assertion.** Two of session 7's own tests were vacuous until checked
  (both SQL bounds appear *twice* per fallback query — outer `WHERE` plus `MAX()` subquery — so
  asserting presence passed under partial removal). And **two of its own mutations were vacuous**:
  one matched the word "raise" inside a comment, another dropped one of two clauses. A mutation
  that fails to fail proves nothing.
- **Give every new gate a negative test.** An empty day must still return `[]`; a clean run must
  still return 200. Gates that fire on healthy input are how alerting gets ignored.
- **Never `git checkout --` to undo a mutation test.** It silently discarded uncommitted work
  twice in session 7. Use `cp` to a backup and restore from that.
- **Compare failure *sets*, not counts.** "16 before, 16 after" hid a changed failure reason once.
- **`get_table().num_rows` is cached metadata.** Use `COUNT(*)` when it matters.
- **Verify a claim's *population*.** The threshold agent's retraction from session 6 —
  *"I measured one population and reasoned about another, inside the audit built to catch that"* —
  recurred twice in session 7, and both times the fix was to check which table was actually
  written.

**Playbook:** `docs/02-operations/agent-research-playbook.md` — 13 defect classes, 8 standing
missions, a do-not-re-test list, and the day-one environment gotchas.

*Session 7 closed 2026-08-24. HEAD `bc57ecbc`, pushed. Deploy verification outstanding — §2.*
