# Session 7 — start here

**Today 2026-08-22. Opener Tue 2026-10-20 (59 days). Seed window Oct 1-19, drop-dead Oct 6.
First predictions ~Nov 3-4. First realistic picks ~Nov 15.**

Previous: `2026-08-22-SESSION-6-HANDOFF.md` (what was built), then a six-agent review whose
findings are carried in §6 of this document — they exist nowhere else.

---

## 1. The thing to understand before you plan anything

Two facts, each fine alone, jointly dangerous:

1. **Opening night through ~Nov 4 will look exactly like an outage, by design.** Zero-tolerance
   blocks every player while the feature store writes placeholders for ~14 days. Verified
   empirically by the October audit: last season's first `player_prop_predictions` row is
   2025-11-04, opener+14. Expect zero picks on Oct 20, a CRITICAL `expected-output-overdue`
   alert, futile backfill triggers, and then a `predictions_inactive` halt from Oct 21 to
   ~Nov 4.
2. **If predictions genuinely stop, effectively nothing pages you.** The one dedicated alert
   policy (`[WARNING] NBA Stale Predictions`) matches the log string
   `"Prediction saved successfully"`, which **appears nowhere in the repo** — its metric can
   never be written again, so its absence condition has no series to go absent. Both canaries
   are PAUSED. Both phase orchestrators have their Slack webhook env vars unset — 35 alert
   call sites that log a warning and drop.

**So there is a two-week window where broken and healthy are indistinguishable and nothing is
watching.** That is where a real failure will hide, and it opens on the highest-attention day
of the year. Closing that window is worth more than any single bug on the list below.

The corollary for Oct 20: **the success test is "data flowing and feature rows accumulating",
not "picks published."** Anyone measuring the system by picks that day will misdiagnose it —
and this project's documented worst failure mode is panic-deploying at a scary-but-expected
reading.

---

## 2. State right now

### ⚠️ Four commits are COMMITTED BUT NOT PUSHED

```
e50e5878  docs: session-7 start (this document)
dd67633d  fix: a second, independent blocker on the roster registry
631e5139  fix: keys/ was uploadable into every manual build context
53265cf4  docs: an agent research playbook
```

Left unpushed deliberately. Pushing and verifying belong together — splitting
them across sessions is how "a green build is not a deployment" happens. Do both
as step A1, not one now and one later.

Nothing in them is deployed. Push, then `./bin/verify-deploy.sh`. Remember: a push touching
only `tests/` or `docs/` triggers nothing, and the four trigger-less CFs
(`halt-state-writer`, `expected-outputs-planner`, `phase-completion-reconciler`,
`gap-detector`) need `./bin/deploy-function.sh`.

### ⚠️ OPEN QUESTION — does the registry fix have a deploy path at all?

`dd67633d` edits `data_processors/reference/player_reference/roster_registry_processor.py`.
Measured: **no shell script, YAML or Dockerfile in the repo references that file.** The live
Cloud Run job `nba-players-registry-processor-backfill` was created 2025-09-21 and its image
was last built **2025-09-26 — eleven months ago**, with no in-repo build config (the same
Sept-2025 vintage as `br-rosters-backfill`, whose image this session had to rebuild).

Two candidate execution paths for Oct 1-6 step 9, with very different consequences:

- **Run locally from the repo** (`PYTHONPATH=. python ... --season-year 2026`) — the fix is
  live the moment it is pushed, nothing further needed. The session-5 plan's phrasing reads
  this way.
- **Executed as that Cloud Run job** — the fix does not reach production until the image is
  rebuilt, and there is no committed config to rebuild it with.

**Establish which, before Oct 1.** If it is the job, budget the same treatment
`br-rosters-backfill` got. Do not assume.

### Deployed and verified at `d8360a97`

Twelve services verified by `BUILD_COMMIT` on the traffic-bearing revision at the end of
session 6, including the manually-deployed `halt-state-writer`. The
`model-sanity-fleet-wide-trip` alert policy is live, enabled, with a channel attached
(policy `7557628960555333168`); its metric descriptor had to be POSTed by hand first, because
Cloud Monitoring refuses to create a policy for a metric that has never been emitted.

---

## 3. Two decisions waiting on the owner

**A. Credential rotation.** A build I ran at 02:40 UTC on 2026-08-22 uploaded
`keys/bigdataball-service-account.json` — the private key for
`bigdataball-puller@nba-props-platform.iam.gserviceaccount.com` — into
`gs://nba-props-platform_cloudbuild/source/1787366364.010176-d96b9ad5d0ac4767b0f3e21bd07085e4.tgz`,
where it was readable by every step of that build. Verified by listing the tarball. The two
`service-account-dev.json` entries (symlinks to the owner's live ADC) were stored as
**symlinks, 0 bytes** — the refresh token content was NOT uploaded.

Config is fixed in `631e5139`. Outstanding: rotate the key? delete the staging object? Neither
was done — the first is a risk judgement, the second destroys evidence before the owner has
looked.

Latent, not new: root `gcloud builds submit` had been *crashing* since 2026-05-11 on a dangling
symlink, which masked the exposure. Repairing that (`a5992db7`) un-masked it.

**B. `opponent_pace` — accept the loss of accumulated shadow stats?** Verified directly:
`ml/signals/supplemental_data.py:437` and `ml/signals/per_model_pipeline.py:402` both alias
`feature_18_value AS opponent_pace`. The feature map is unambiguous —
`14: (90, 115, 'opponent_pace')`, `18: (0, 1, 'pct_paint')` — and live March data confirms it
(f14 ranges 92.05-107.86, f18 ranges 0.0-1.0). `slow_pace_under` disqualifies only when
`opp_pace > 99.0`, which on a 0-1 variable can never happen, so it has fired on **every**
UNDER at pinned 0.90 confidence — 28,443 tag events since March 2026, and its "56.6% HR" is
just the all-UNDER base rate. `fast_pace_over` gates on `>= 0.75` and is really asking
"are 75% of shots in the paint".

Fixing it invalidates both signals' accumulated shadow statistics. That is a call about
promotion timelines, not a code question. Same latent class:
`feature_53_value AS prop_over_streak` (the real streak is f51).

---

## 4. The plan

Framing: ~50 known defects, one hard calendar gate that cannot be retried, and almost no
working alerting. The goal is **not** to fix everything. It is to (a) make the Oct 1-6 seed
succeed first time, (b) make failures loud enough that the rest surface during the ramp
instead of in production, (c) fix the few things that corrupt the money path or the public
record, and (d) leave the remainder documented and ranked.

### Phase A — now → Aug 29: land and decide
1. Push the four commits; verify by `BUILD_COMMIT`. `dd67633d` is the only one
   touching runtime code.
2. Resolve the registry deploy question (§2). This gates everything in Phase C/D.
3. Owner decisions A and B (§3).
4. Red-team the unverified findings — see §7. Do this **before** fixing, not after.

### Phase B — early Sept: make failures loud (highest leverage)
Nothing else on this list is verifiable while the system cannot report its own failures.
- The "return 200" family: `weekly_retrain/main.py:1204`, `expected_outputs_planner`
  (:347-357), `halt_state_writer` (:1073-1109, whose docstring already promises a 500 the
  code never returns), and the four monitoring CFs that ACK their own crashes.
- Grading converting BigQuery infra failures into "nothing to grade" → `EMPTY_OK`
  (`prediction_accuracy_processor.py:597-604, 643-650, 1070-1077`).
- The two phase orchestrators' Slack webhooks (35 dead call sites).
- Rebuild the Stale Predictions policy around a metric that actually exists.
- Wire the orphaned metrics — `halt_gate_overridden` most of all. That is the emergency-override
  tattletale, and nobody is watching the tattletale.
- Add an absence alert on `expected_outputs` production itself: if the planner stops, the
  reconciler has nothing to flip and the Critical overdue alert can never fire.

### Phase C — mid/late Sept: rehearse the seed, then the money path
**Rehearse the roster seed end-to-end.** Two independent silent blockers have already been
found on this path, weeks apart. Assume a third until proven otherwise, and do not go hunting
for it by reading code — *run the thing*. Suggested: build the registry for `--season-year 2025`
(a season with data) against a scratch target and confirm it writes ~696 rows. If it does, the
machinery works and Oct 1 becomes a pure data question. This is the highest-value September
task and it is cheap.

Also in Phase C:
- The Nov-1 season-flip family (7 exporters): labels flip in October, windows flip Nov 1, so
  **Oct 20-31 the public record blends ~650 stale 2025-26 picks under a `2026-27` label.**
- `team_context.py:771,877,983` — three hardcoded `'2025-10-22'` season windows, live daily in
  Phase 3, feeding stars-out context into predictions.
- `opponent_pace`, pending decision B.
- `fleet_blocked` reachability (§6) — decide before it becomes reachable in season week 2.
- The export-time volume cap in `pipeline_merger` — still the only thing that can catch a
  one-slate blowup on day one; both breakers evaluate at 5 AM on yesterday's data.

### Phase D — Oct 1-6: the seed (hard gate, no retry)
Session-5 plan steps 7-9, unchanged and code-verified by the October audit. Two additions:
- **The NBA.com source fallback window is only 7 days** (ESPN's is 30). Run the registry
  processor within 7 days of the `nbac_player_list` scrape, or re-scrape first.
- **BR partial-failure acceptance is unfixed**: three stacked warn-only layers mean a 7-of-30
  team scrape still MERGEs, seeds the registry and reports success. Check team count before
  trusting the seed.
- Verify 600-750 rows for `season='2026-27'`; the first `br-rosters-batch-daily` run must
  write ~600 rows with `season_display='2026-27'` AND `season_year=2026`.

### Phase E — Oct 6-20: waves, and define "healthy" for the blind window
Session-5 §6 gates all still apply. Add one deliverable: **write down what healthy looks like
during Oct 20 → Nov 4** — box scores landing, `player_game_summary` growing, feature-store rows
accumulating — and have something watch those specific quantities. Otherwise §1's blind window
stays blind. Also: `weekly-retrain-trigger` fires Mondays only, so its sole pre-opener run is
Mon Oct 19 — resume by Fri Oct 16 or the first retrain is Oct 26.

### Explicitly NOT in this plan
Everything in §6 marked P2/P3, all shadow-signal promotions (live-N-gated at N>=30), any model
or feature research (closed — see `docs/02-operations/agent-research-playbook.md` §3), the
remaining eight archived Dockerfiles, and `ml_feature_store_v2` partitioning (cost, not
correctness). Doing a good job on Phases A-C beats a poor job on all fifty.

---

## 5. My own loose ends from session 6

Listed separately because they are mine, not inherited:

- **The fleet floor's denominator is still dilutable.** `1a9ae03e` excluded legacy and errored
  pipelines, but a model with 1-19 predictions can never self-block (all three guards need
  >=20) and still counts. 2 clones + 2 small unregistered experiment sets → `2 <= max(1,2)` →
  no trip. Same shape in the aggregator's own copy.
- **The disarm seam has no test that executes it.** Deleting the
  `_apply_fleet_sanity_floor(results, _run_one)` call, or the `disable_model_sanity`
  pass-through, leaves all tests green — the latter silently recreates the drought.
- **The alert runbook I wrote contains a query that errors.**
  `monitoring/alert-policies/model-sanity-fleet-wide-trip.yaml:70-75` selects `system_id` from
  `best_bets_filter_audit`, which has no such column — failing at exactly the moment the policy
  fires.
- `model_sanity_block_disarmed` lands in the `rejected_json` namespace with no `filters.yaml`
  entry, though `f766d3bc`'s own rationale for registering `model_sanity_block` applies.

---

## 6. Findings from the six-agent review

**These exist nowhere else.** Verification status is marked per item and matters: three of six
agents produced a headline that did not survive checking.

### VERIFIED directly (BigQuery / live GCP / code read)

| Finding | Status |
|---|---|
| Registry queries `nba_raw.processor_run_history`; table does not exist (real one is `nba_reference`, 2.3M rows, identical schema). The validator's deliberate fail-CLOSED except returns `(True, "check_failed")`, so `build_registry_for_season` exits 'blocked' as a normal non-error result | **FIXED** `dd67633d` (unpushed) |
| `opponent_pace` aliased to `feature_18_value` (pct_paint, 0-1) instead of `feature_14_value` (pace, 92-108) | Verified, NOT fixed — decision B |
| `keys/` in every manual build context; the bigdataball key reached the staging bucket; ADC stored as symlink so NOT exposed | Config **FIXED** `631e5139`; rotation pending |
| `_fleet_blocked` has **never fired**: 0 all-BLOCKED days in 106, max blocked share 0.75. MPD is populated from `prediction_accuracy` over a trailing 30 days — every experiment run, not the enabled fleet — so the denominator was 24-58 models | Verified |
| Replayed on the three actually-enabled clones, `_fleet_blocked` **fires 7 of 19 covered days (36.8%)**, including a 7-day consecutive run; analogue triples 13-26%. It is unreachable today only by accident of denominator pollution, and flips to firing in multi-day runs once the fleet is the intended three. Opening night is safe (three independent layers) | Verified; **decide before season week 2** |

### AGENT-REPORTED, not independently verified — P0/P1

Ranked as the reporting agent ranked them. Each is claimed to be a <=5-line fix.

- `weekly_retrain/main.py:1204` returns 200 on total failure by design ("so scheduler doesn't
  retry"); per-family crashes looped past; the Slack alert is itself inside `except: pass`.
  Nothing else watches model age.
- Grading converts NotFound/ServiceUnavailable/DeadlineExceeded into `return []` → `skipped` →
  `EMPTY_OK` → ACK. Someone already fixed this for `BadRequest` and stopped.
- `expected_outputs_planner` failure returns 200 — blinds the entire safety net.
- **UTC vs ET day boundary**: `phase6_export/main.py:257` (`utcnow()`), `nba_grading_alerts:641`,
  `data_quality_alerts:799`, `prediction_health_alert:299`. Evening ET runs export or check
  the wrong day; the 19:00 ET jobs sit exactly on the EST midnight boundary.
- `player_lookup` normalizer split: the `nba_tracking_stats` join is **0-for-307,135** (missing
  the `REPLACE(...,'-','')` its two siblings have), so `drive_volume_under` accumulates nothing
  while logging success. Separately ~26 suffix players ("Jr") never match projection sources.
- `quantile_ceiling_under` — ACTIVE, top UNDER weight 3.0 — reads `prediction['quantile_p75']`,
  which the batch query never selects. Double-dead (no MQ model enabled either).
- Rescue health gate has never executed: second consumer of the same `signal_health` same-day
  lookup bug that makes health-aware weighting inert.
- Ultra tier is structurally impossible for 2 of 3 enabled models (`startswith('v12')` vs
  `lgbm_v12_noveg_mae`). BQ since Jan: lgbm 0/43, xgb 0/11, catboost 37/53.
- Phase 3→4 "BLOCKING" boundary validation has never executed (AttributeError caught as
  non-blocking). **Half-fixing it would block Phase 4 daily** — fix both layers or delete.
- Kalshi table is 92% duplicates (498,465 rows, 39,819 distinct) — dedup keys on a column the
  table does not have.
- Filter auto-demote is write-only for `bench_over_block`, `role_over_block`,
  `mae_gap_over_block` — their block sites never consult `_runtime_demoted`.
- `post_grading_export`: 12 independently swallowed steps, unconditional ACK, including the
  actuals backfills that feed CF-HR and auto-demote. No watchdog.
- Phase 1→2 and 2→3 publishes "never fail the caller" — and Phase 2→3 IS the critical path.
  `live_export` publishes without awaiting the future, then writes a marker that permanently
  prevents re-attempt.
- `ref_crew_under_tendency` is triple-dead (scale, NULL source column, feed dead since
  2025-06-19). Its in-code plan "data will accumulate from 2026-27" is false three ways.
- Two "trigger predictions" paths publish to topics with **zero subscribers** (admin dashboard
  button; BDB retry processor).
- `grading-gap-detector` CF's remediation path is dead twice (stale host, wrong param names) —
  and it is half the justification for excluding the three `grading-*` jobs from the restore.

### AGENT-REPORTED — the alerting map (Part 2 of the docs audit)

- **Exactly one notification channel exists**: Slack "#alerts". The per-topic channels
  (#canary-alerts, #deployment-alerts) exist only as code-level webhooks.
- **Four policies have zero channels** — the entire env-var-drift layer notifies nobody.
- Unconsumed metrics (emitted, no policy watches): `halt_active`, `halt_gate_overridden`,
  `exporter_halt_suppressed`, `zero_pick_reexport`, `clv_retraction`,
  `bq_streaming_insert_failed`.
- Mute-but-running on ENABLED schedules: `gcs-freshness-monitor` (which also always returns
  200), `live-freshness-monitor`, `daily-health-summary`, `data-source-health-canary`,
  `signal-decay-monitor`, and both phase orchestrators.
- `news-fetcher` is degraded yet its scheduler is **ENABLED every 15 minutes** — the one enabled
  job pointed at a broken function. `scraper-gap-backfiller` has two ENABLED duplicates.

### AGENT-REPORTED — CLAUDE.md is wrong in 18 places

Highest-impact: governance gate is **N>=40**, not 15 (`quick_retrain.py:4350`); the TIGHT-market
OVER floor is 6.0→7.0, not 5→6 (the same file says it correctly elsewhere);
`UNDER_SIGNAL_WEIGHTS` has 10 entries, not 11 (9 execute); `bb_enriched_simulator.py` and two
discovery tools **do not exist**; "code imports via `shared.registry.is_known_signal`" is false —
the only importer is the pre-commit hook, and the YAML `weight`/`rescue_priority` fields have
**zero runtime consumers**. Several "no scheduler" claims are now stale (the jobs exist, PAUSED —
they need a resume, not a create).

### AGENT-REPORTED — registry vs executing code

`signals.yaml` marks three signals active that are unregistered in code (`blowout_recovery`,
`prop_line_drop_over`, `rest_advantage_2d`); three filters active that code removed; ~12 weight
mismatches where code executes a different number than the YAML documents;
`book_disagree_under` holds weight 1.5 and goes live the instant it leaves `SHADOW_SIGNALS`;
five `ELIGIBLE` auto-demote entries can never match a row; `book_disagreement` is a *signal*
sitting in the *filter* demote list.

### P2/P3 — recorded, not scheduled

`validation/configs/**` is entirely dead with 11 phantom target tables; `shot_profile`
classifies every player `interior` (0.50 threshold against 0-100 data); DFF projections collect
nothing usable; PGS registry-failure observability writes to a nonexistent table;
`signal_combo_registry` is annotation-only with 6 of 11 rows referencing dead tags;
`PRIMARY_ALERT_MODEL` keyed to a system_id dead since 2026-03-03; `feature_store_validator` can
never PASS; `BigQueryBatchWriter` destroys batches on failure with a WARNING; two analytics
processors are complete no-ops; assorted team-code and season-convention islands.

---

## 7. Working discipline for this session

**Verify before acting.** Three of six agents produced a headline that did not survive contact
with primary data — the threshold agent's own retraction is the model to follow: *"I measured
one population and reasoned about another, inside the audit built to catch that."* An efficient
policy:

- Cheap to verify **and** cheap to fix (doc corrections, string fixes): verify inline while
  fixing.
- Changes money-path behaviour: verify hard and independently **before** touching.
- "This is dead code": verify by checking whether it ever produced output, not by reading it.

**Start by red-teaming the list, not by fixing it.** Run playbook Mission 8 over §6's
agent-reported items — CONFIRMED / OVERTURNED / NARROWED, each decided by a query or a file.
That parallelises the verification tax and is a better first move than picking off items.

**The playbook is at `docs/02-operations/agent-research-playbook.md`** — 13 defect classes with
detection recipes, 8 standing missions, a do-not-re-test list, and the day-one environment
gotchas (`bq` and `gcloud scheduler jobs list` hang here; the local gcloud default project is
wrong; the deploy gate runs `tests/unit/signals` on a thin dependency set).

**Mutation-check every new test.** Four of session 6's tests passed first-run against working
code; only disabling the thing they covered proved they measured anything.

---

## 8. Durable lessons from session 6

- **Three green layers can hide one dead pipeline.** The scheduler reported success (`:run` only
  creates the execution), the processor failed inside a handler that logs and returns, and the
  image was too old to have the flag. What broke the tie was reading the *data*: the last write
  date in BigQuery matched a routing commit to the day.
- **A commit message can be the last surviving copy of a config.** `br-rosters-batch-daily`
  existed in no backup, no catalog, no snapshot and no audit log — only in the body of
  `19eda492`.
- **Fixing one blocker on a path is not evidence the path works.** The BR processor repair was
  necessary and not sufficient; a second independent fail-closed blocker sat one layer above it,
  and a third question (the deploy path) is still open.
- **"Orphaned" is a claim to verify.** `1942a6b3` archived a directory twelve live scripts
  depended on.
- **Repairing something can un-mask an exposure.** Fixing the build-path crash is what put
  credentials into a build context; neither commit is wrong alone.
- **Writing a test can reveal that the thing you are testing never ran.**

*Session 6 closed 2026-08-22. HEAD `e50e5878` (4 commits unpushed).*
