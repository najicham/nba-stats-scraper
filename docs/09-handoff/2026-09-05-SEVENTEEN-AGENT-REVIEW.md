# Seventeen-agent review — 2026-09-05

Successor to `2026-09-01-FIVE-AGENT-REVIEW.md` (read its correction header first — this round
overturned several of its load-bearing claims). All findings measured against live BigQuery/GCP.
Items marked ✅ were independently re-verified in-session before being written down.

**Opener 2026-10-20 (45 days). First publishable pick ~2026-11-17.**

---

## 0. The one-paragraph version

The system is in better shape than the last review said, and the *evidence base under every
strategic decision* is in far worse shape. Nothing is destroyed; several "missing" pieces already
exist. But **63% of the published-pick record was manufactured after the outcomes were known**, the
highest-weighted UNDER signal cannot fire, the champion-model resolver silently falls back to a
model that stopped predicting in April, CI has never run a single unit test, and the two regression
guards written for this year's worst bugs have never executed. The work that matters before Oct 20
is not new capability — it is making the existing machinery *observable* and its numbers *true*.

---

## 1. Broken right now

### ⚠️ 1.0 — THE P0: the feature store has no writer, and do-nothing yields ZERO predictions

✅ Verified in-session. `phase3_to_phase4` publishes per-table messages → precompute `/process` →
`PRECOMPUTE_TRIGGERS` (`main_precompute_service.py:76`), which maps only `player_game_summary`,
`team_defense_game_summary`, `team_offense_game_summary`, `upcoming_player_game_context`,
`upcoming_team_game_context`.

**`MLFeatureStoreProcessor` and `PlayerCompositeFactorsProcessor` are not in it.** They appear only
in `CASCADE_PROCESSORS` (`:85`) — **referenced exactly once, at its own definition. Dead code.**
Their only live entry is the `/process-date` HTTP route, and **all 12 schedulers targeting it are
PAUSED** (`ml-feature-store-{7am,10am,1pm}-et`, `-daily`, `player-composite-factors-{daily,upcoming}`,
`player-daily-cache-daily`, `same-day-phase4{,-tomorrow}`, `overnight-phase4{,-7am-et}`,
`phase4-timeout-check-job`).

**This falsifies §4's "minimum viable Phase 1 restore is 2 jobs; everything downstream is
event-driven."** Phase 4's feature-store step is scheduler-driven and every scheduler is off.

Timeline under do-nothing: Oct 20 the halt correctly lifts; Oct 20–Nov 2 the `BOOTSTRAP_DAYS=14`
window hides the hole; **Nov 3 the coordinator finds an empty feature store and produces zero
predictions** — with **no alert**, because `[WARNING] NBA Stale Predictions` is the one DISABLED
policy and no "zero predictions on a game day" policy exists among the 37. Dec 1: nothing to grade,
so `model_performance_daily`, the decay states, `fleet_blocked` and the drawdown breaker all stay
empty — **all three money breakers inert, fail-open, for the whole season.**

✅ **Also verified: the only ENABLED NBA props scrapers are `nba-{rebounds,assists}-props-*` — the
two markets the system does not bet.** All four points-props scrapers are PAUSED. **Zero enabled
jobs currently produce a points line, box score, injury report, feature row, prediction, or graded
result.**

**Honest minimum restore:** `master-controller-hourly`, `execute-workflows`, the 4 `nba-props-*`
scrapers, `ml-feature-store-{7am,10am,1pm}-et`, `player-composite-factors-daily`, `same-day-phase4`,
`overnight-phase4`, Phase 5 dispatch, the grading trigger — **then one end-to-end rehearsal on a
historical date that ends in a row in `signal_best_bets_picks`, because every intermediate check in
this system returns success when it produces nothing.**


| # | Finding | Evidence | Fix |
|---|---|---|---|
| 1.1 | ✅ **No model is `is_production AND enabled`** (3 enabled, 1 production, zero overlap). `model_selection.py:19` `_DEFAULT_CHAMPION='catboost_v12'` is therefore the steady state, and the empty-result path returns **silently** (the warning is only in the `except` branch). That literal resolves to a system_id whose last game date is **2026-04-18**. 36 call sites, 17 public exporters. | live registry query; `v1/systems/model-health.json` last written 2026-04-19 | one registry row + make the empty path raise |
| 1.2 | ✅ **`UNDER_SIGNAL_WEIGHTS['quantile_ceiling_under'] = 3.0` — the highest UNDER weight — can never fire.** It reads `prediction['quantile_p75']`, written only in the worker's in-memory result. **Zero quantile columns exist in `player_prop_predictions`**; the value is discarded at the BQ write boundary. No MultiQuantile model is enabled. | `INFORMATION_SCHEMA.COLUMNS`; a real 103-key prod pred dict | delete the weight, or plumb p25/p50/p75 |
| 1.3 | ✅ **CI has never executed a unit test — and not for the reason previously reported.** `test.yml:47` passes `--timeout=60`; `pytest-timeout` is installed nowhere. pytest exits **4 (usage error)** before collection. 200/200 runs. Collection pollution is the *second* blocker. **Behind both sit 2,827 passing tests**, including the 7-test ungraded-as-loss guard and the 19-test season-flip guard — **written for this year's worst defects, never once run.** | `gh run view`; reproduced locally, exit 4 | `pip install pytest-timeout` (~15 min) |
| 1.4 | ✅ **`gs://nba-props-platform-api` grants `allUsers:objectViewer` bucket-wide.** `v1/admin/dashboard.json` returns **HTTP 200, 14,469 bytes** anonymously, carrying `champion_model_state`, `model_health`, `signal_health`, `subset_performance`, `picks`. Frontend Firebase auth on `/admin` is bypassed by the direct URL. Uniform bucket access cannot scope the public `v1/` grant away from `v1/admin/`. | anonymous curl | move `v1/admin/*` to a private bucket |
| 1.5 | **`pipeline-reconciliation` (6 AM ET, ENABLED) is 100% dead** — all 8 BigQuery checks error; `run_query` swallows to a warning and returns `[]`; callers substitute **zero**. Checks gated `&gt;0` can never fire; checks gated `==0` fire **falsely every day**. This is the monitor that would have caught the Oct 2025 opening-week gap. | 8 failures/day, ≥60 days | re-raise instead of `return []` |
| 1.6 | **Injuries fail open.** A structurally-valid PDF with 0 parsed records passes `should_save_data`; the injuries CTE is empty; `WHERE i.injury_status IS NULL OR ...` passes **every player as healthy**. OUT players get published picks, indistinguishable from a no-injury day. | code trace | fail closed when the table is empty on a game day |
| 1.7 | **`_fleet_in_transition` has never applied.** It selects `WHERE is_production = TRUE AND enabled = TRUE` → **zero rows** → returns None → the grace never fires. Meanwhile `BLOCK_THRESHOLD = 52.4%` sits on the fleet's true median 7d HR of **52.9%**, so **48.5% of model-days are legitimately BLOCKED**. At 3 clones with 57.8% conditional co-blocking: **~1-in-6 daily chance of a full-slate zero-pick halt**, with the designed safety valve inert. | 3,144 model-days recomputed | key on `enabled = TRUE`; raise the `INSUFFICIENT_DATA` floor from n7&lt;5 to n7&lt;30 |
| 1.8 | **`./bin/retrain.sh --all` crashes and exits 0.** `quick_retrain.py:491` formats a `None` (`AVG` over an empty set) → unhandled `TypeError`; `retrain.sh:330-346` swallows per family and **exits 0**. Nothing trains; it is indistinguishable from success. | reproduced against live BQ | guard `avg_q is None`; hard-return when `total == 0` |
| 1.9 | **`batch_staging_writer.py:298-310` never reads `validation['error']`.** Any exception in the schema check (transient BQ 5xx, IAM change) fails the batch with `SCHEMA MISMATCH: 0 fields ... []`, instructing the operator to ALTER TABLE while discarding the real cause. | test triage | surface `validation.get('error')` |
| 1.10 | **`bin/check-deployment-drift.sh` is structurally blind.** Maps three services to directories that do not exist (`data_processors/phase2\|phase3\|phase4`; real: `raw\|analytics\|precompute`), and `:257` loops over `$SERVICES`, **assigned nowhere** — no `set -u`, so `:269` unconditionally prints "All services routing to latest revisions". **2,317 references across 1,490 files.** | grep + live run | fix the map, `set -u`, iterate the real keys |

---

## 2. Corrections — including to the 09-01 review and to this session's own earlier reporting

Ordered by how much each has been steering decisions.

| Claim | Verdict | Correction |
|---|---|---|
| "The 2025-26 publish record was destroyed — 95 of 198 JSONs overwritten to empty" | ✅ **WRONG** | GCS versioning has been **on since bucket creation**, no lifecycle rule, 1,530 retained generations. The "overwritten" objects have **exactly one generation each**, stamped `generated_at` 2026-02-15/22 — **created** empty by a backfill. `2025-12-15.json` has **zero** generations. The published-pick record genuinely **begins 2026-01-09**. |
| "Absent-build rate is 37.9%" | ✅ **WRONG — instrument artifact** | `gcloud builds list` paginates server-side against a 60 req/min quota (429 reproduced). Against Cloud Build's **audit log**, the glob-computed expectation matched **exactly, 5/5, at fan-outs of 26-30**. On 08-30 all 30 fired; **9 FAILED** — those 9 are the components still stale. Do not use the build ledger as an oracle. |
| "The snapshots were truncated (110 of 169)" | ✅ **WRONG** | The estate really was 110 jobs; the 08-22 restore added 59 (0 removed). CLAUDE.md's "`weekly-retrain-trigger` was deleted" was **accurate when written** and went stale on 08-22. Conclusion survives, reasoning did not. |
| "Cross-model signals can't fire with a 3-clone fleet" | ✅ **WRONG** | `combo_3way` gates on *this model's* edge + minutes surge + confidence band — no cross-model reference. `book_disagreement` is cross-**sportsbook**. What *is* cross-model (`consensus_bonus`, `feature_set_diversity`, `quantile_consensus_under`) is explicitly unused for ranking. **Fleet diversity currently buys zero scoring signal.** |
| "`bq` and `gcloud scheduler jobs list` hang in WSL" | ✅ **WRONG** | Both return in **~2.1s** with an explicit `--project`/`--project_id`. The symptom was almost certainly `bq`'s interactive setup prompt under the wrong default project (`urcwest`). |
| "5 active signals have never fired" | **3 of 5 wrong** | `sharp_line_drop_under` fired **23×**, `cold_3pt_over` **29×**, `book_disagree_over` **3×**. Only `quantile_ceiling_under` (0 anywhere) and `elite_line_under` (0 live) hold. |
| "Zero-fire signals are a raw-vs-0-1 threshold-scale bug" | **The hypothesis is FALSE** | All `feature_N_value` columns are **raw-scale** (f1 max 40.8 pts, f4 max 8 games, f25 0.5-35.5). **CLAUDE.md's "feature store values are normalized 0-1" is wrong and actively misleads debugging.** |
| "`roi_simulation`/`roi_summary` have 0 rows" | **WRONG** | 4,252 and 95 rows respectively. |
| "Book attribution is missing" | **Misdiagnosed** | `player_prop_predictions.sportsbook` is **89.5% populated**. `prediction_accuracy_processor.py:853` maps it, but the source SELECT never selects the column — a two-line omission, live since Jan 2026. |
| "No append-only publish log exists" | **WRONG** | `best_bets_export_audit`: 922 rows, 156 dates, `picks_snapshot` 100% non-null. Written by the wrong exporter (doesn't bracket the DELETE) and lossy, but the machinery exists. |
| "Line coverage regressed 55.1% → 19.3%" | **Two tables conflated** | In `prediction_accuracy` coverage **improved** every season, 59.3% → **89.4%**. The drop is in `player_game_summary.points_line`, an **unfinished backfill** — Feb-Apr run 53-62%, *better* than 2024-25. |
| "First graded rows ~Dec 1" | **WRONG** | Steady-state grading lag is **1 day** (Mar/Apr measured); the Nov-Jan lags were backfill artifacts. N≥40 clears ~2 game days after grading starts. **The real risk is different: in 2025-26 the pipeline emitted zero prop lines until 2025-11-19 — four weeks post-opener.** |
| "Signal rescue went 29-35 (45.3%), below breakeven" | **Does not reproduce, and the conclusion inverts** | True record **11-13 (45.8%, N=24)**. All 25 rescues fall on **four consecutive March-collapse days**, where rescued picks **outperformed the same-day control by 17pp** (45.8% vs 16.7% OVER / 38.5% UNDER). **13 of 25 came from lanes since closed.** |
| "The Sep 20 roster deadline" | **Does not exist as stated** | The **Oct-1 code boundary** means NBA.com and ESPN *cannot* produce `season_year=2026` rows before October. **BR is the only source that can be populated pre-Oct-1**, and it serves 2026-27 data today. |
| "`br-rosters-batch-daily` was never created" | **WRONG** | Exists, PAUSED, `30 6 * * *`. **`nba-closing-lines-sweep` is the only genuinely missing job.** |
| "24 test files stub `google`" / "920 tests pass per-dir" | **23 files; ~6,051 pass** | The memory figure is wrong by **~6.5×**. |
| "`decay-detection` is double-off" | **WRONG** | `AUTO_DISABLE_ENABLED=true` on the deployed CF. Two *data* guards hold today (`max_to_disable=0`, all `INSUFFICIENT_DATA`) — both evaporate at a 4th model + graded rows. |
| "`model_performance_daily`'s 604 BLOCKED rows are a NULL-bug artifact" | **Overstated** | **396 of 604 (65.6%) are real.** The bug inflated BLOCKED by ~52%; it did not manufacture it. |
| "`moving_average_baseline_v1` at 71.4% beats every ML model" | **ARTIFACT** | It predicts **8.72** where the actual is **14.26** (LeBron 6.5 vs a 20.3 line). "Edge ≥6" is a proxy for feature-extraction failure. The honest version of the angle hits **48.3%**. |

---

## 3. The strategic question, settled

**63% of `signal_best_bets_picks` was generated retrospectively.** ✅ `ml/experiments/signal_backfill.py`
(`614072e6`, 2026-02-14) re-runs the aggregator over **already-graded** `prediction_accuracy`:

| month | picks | created AFTER the game | mean lag |
|---|---|---|---|
| 2026-01 | 69 | **69 / 69** | **36.5 d** |
| 2026-02 | 55 | 41 | 9.1 d |
| 2026-03 | 73 | 16 | 0.2 d |
| 2026-04 | 6 | 0 | 0 |

| split | graded | HR |
|---|---|---|
| **LIVE** (`created_at <= game_date`) | **70** | **45.7%** |
| RETRO (in-sample re-scoring) | 119 | 66.4% |

**The entire published OVER case is retro.** "62.1% at edge 5-6" and "72.3% at edge 6+" live in
manufactured rows; genuinely live OVER at edge≥5 is **5/10**. Excluding January (100% retro),
published OVER edge3+ = 50.7% (n=71) vs UNDER 51.0% (n=51) — identical, both losing.

**The properly-powered replacement for the n=18 argument** (logistic `win ~ edge`, leak-free
walk-forward, 5 seasons): the `edge × is2025_26` interaction is **OVER β=+0.539, z=5.35, p=4×10⁻⁸**
versus **UNDER β=+0.109, p=0.193**. **UNDER's edge→HR relationship is statistically
indistinguishable across all five seasons; OVER's 2025-26 is a massive departure from its own
four-season history.** On prior-4 data the **OVER CI upper bound is below 52.4% at every edge from
3 to 8**.

**But the OVER floor is not the consequential setting it is called.** It governs ~4.5 picks/season
at 6.0 (9.5 at 5.0) against a ~187-pick UNDER book — **total leverage ±2u/season**. 5.0 vs 6.0 vs
7.0 needs n≥360; every population has n≤47.

**Decision: hold 6.0. Do not lower to 3.0** (that IS well-powered — OVER edge 3-5 prior-4 = 49.0%,
n=584, costs 12-14u/season). Stop spending sessions on the level. ⚠️ Session 522's stated
justification is **false on clean data**: "edge 6-8 = 61.4% consistent all 5 seasons" is OVER-only
prior-4 = **4/12 = 33.3%**. Right floor, wrong reason — fix the comment so it is not re-cited.

**100% of the OVER selection layer was fitted in-season:** `ml/signals/` has zero commits before
2025-10-21; `aggregator.py` created 2026-02-14; `OVER_SIGNAL_WEIGHTS` created 2026-03-08 from that
season's own live HRs; no OVER-blocking filter existed before 2026-02-28 (39-day live window); the
floor moved **7 times in 41 days** and today's 6.0 was set **3 days after the last live pick**.
`fast_pace_over` (weight 2.5) aliased `feature_18_value` (pct_paint) as pace all season.

**Nuance that cuts the other way:** the 2025-26 OVER boom is present in the **pre-selection,
leak-free** data too (edge≥3 = 71.7%). The layer did not create it — **the season did** — and the
layer arguably destroyed value Feb-Apr.

**CLV is not the #1 lever.** Honestly sized: **+2 to +4.5u/season** (~+0.3-0.7% ROI), CI lower
bound barely above zero at any cadence short of per-game. The live filter
`clv_diverge_under_block` is **measured backwards** — it blocks the line-dropped bucket at **59.6%**
(the best one) and leaves the line-rose bucket at 54.7% alone. The effect **reverses inside its own
single season** (+6pp Nov-Dec, −20 to −30pp Jan-Apr, and Jan-Apr is the collapse window).
Cross-season validation is **impossible**: 25 qualifying snapshot rows exist before 2025. At
best-bets level the rule would have touched **7 picks** all season.

---

## 4. Season readiness

**The real opening-night blocker is `espn_team_rosters`, not the registry.**
`upcoming_player_game_context` builds its player universe from a **90-day window** on that table
(`shared_ctes.py:96-131`), currently **132 days stale** (max `roster_date` 2026-04-26). Empty
window → zero rows → **zero predictions**. The registry is enrichment: its write path died
2026-02-04 and Feb-Apr produced predictions normally at the (inflated) season HR.

**All three roster scrapers work today** — verified by *running* them: BR returns 19 players for
BOS 2026-27; NBA.com returns 582; ESPN returns 16 including a 2026 draftee.

⚠️ **ESPN's 30-team fan-out hit all 30 on only 18 of 108 dates last season.** Diagnosing that needs
weeks of daily samples. **This, not the Oct-1 boundary, is the argument for resuming now.**
Marginal cost measured at **~$0.15 for the whole 45 days**.

**Minimum viable Phase 1 = 2 paused jobs**, resumed together (`/evaluate` writes decisions that
`/execute-workflows` honours for only 60 minutes): `master-controller-hourly` + `execute-workflows`.

**BigDataBall: NBA.com PBP is the *better* source, not a fallback.** Against the official box score
NBA.com reproduces 3PA and total FGA with **zero error**; BDB undercounts threes by 0.676 per
player-game (its 2025-26 feed lost the `3pt` markers). Paint agrees exactly (r=1.000, 100% exact,
N=4,279). Coverage is **complementary** — union 97.3%, neither-source 2.7%.
⚠️ **But it is five bugs, not two.** `shot_distance` is percentage-of-court arithmetic mislabelled
as feet (2PT median **52.1**), `player_1_lookup` is last-name-only with 99 collisions, and ~45% of
`game_id`s carry reversed team order. **The "two-line fix" would return rows with ~0 paint and ~0
mid-range and log success.**
⚠️ **And the blocking chain in every prior doc is wrong:** feature 6 never defaults on shot-zone
absence (it silently reads a fabricated 0.0 with `is_production_ready=TRUE`). **Features 18-20 are
the actual blocker** — 10,561 of 14,042 blocked rows, and 100% of rows with a missing shot-zone
rate are blocked.

**Two calendar facts that will repeat:**
- **35 of the first 41 games of 2025-26 are missing from `player_game_summary`** (Oct 21-26);
  `nbac_gamebook_player_stats` has no rows until 2025-11-01. The gamebook scraper did not run for
  the first **eleven days** of last season. **This recurs on 2026-10-20 unless Phase 1 is verified.**
- **The pipeline emitted zero prop lines until 2025-11-19**, four weeks post-opener.

---

## 5. Alerting — 15 of 37 policies cannot fire; 4 fire constantly

**One notification channel exists project-wide** (`#alerts`), and it is **none of the ~13 channels
the code writes to**. `"Sent Slack alert"` appears **zero times in 30 days**; `"No Slack webhook URL
configured"` appears 81 times.

**All 84 deployed functions are Gen2**, so their logs carry `resource.type="cloud_run_revision"`.
Four policies filter `cloud_function` — and **two of the underlying log-metric definitions carry
the same mistake**, so those metrics never increment at all.

✅ **A third, independent reason nothing paged: every `logger.info` in every Gen2 CF is discarded.**
`logging.basicConfig(level=INFO)` is a no-op once functions-framework installs a root handler; the
root level stays at WARNING. Verified across 5 CFs — **zero stdout entries, zero INFO app lines**.
Any log-based metric keyed on an INFO-level string can never match.

**Worst single policy:** a substring match on `"401"`/`"403"` across all Cloud Run text logs —
**78,624 matches in 30 days**, and a 300-row sample found **zero** were auth errors. Estimated
in-season load **200-350 Slack messages/week at ~0.3-1% actionable**.

**All 170 scheduler jobs have `retryConfig.retryCount` unset (= 0 retries).** The
"return 200 so the scheduler doesn't retry" convention rests on a **false premise** — a 500 costs
one red log line, which is the thing you want. And **the DLQs cannot be reached**: `nba-backfill-trigger`
has `maxDeliveryAttempts: 5` but its consumer always ACKs.

---

## 6. Ranked actions

### Tier 0 — hours, do first
1. `pip install pytest-timeout` + add to `requirements-test.txt`. **15 minutes; unblocks 2,827 tests.**
2. Promote `validate_cloud_function_symlinks.py` into `pre-commit-checks.yml` (one line, into the one green workflow).
3. Fix `check-cloud-function-drift.sh` (`--project`) and `check-deployment-drift.sh` (the map + `$SERVICES` + `set -u`).
4. Two-line grading fix: add `sportsbook`, `line_source_api` to the `predictions_raw` SELECT.
5. Set `is_production = TRUE` on one enabled model — revives `_fleet_in_transition` **and** fixes the champion fallback.
6. Add `google-cloud-monitoring` to 5 lock files (coordinator, phase3, phase4, nba-scrapers, nba-grading-service). Phases 3 and 4 have **never** emitted a datapoint.

### Tier 1 — before Oct 20
7. **§1.0 first: un-pause the Phase 4 feature-store schedulers and the 4 points-props scrapers**, then `master-controller-hourly` + `execute-workflows`, and watch ESPN's 30-team rate daily.
8. Run BR 2026-27 rosters by hand (`--seasons=2027`, **never `--current-season` before Oct 1**).
9. Raise the `INSUFFICIENT_DATA` floor to n7≥30 **before** adding a 4th model (adding one arms auto-disable).
10. Fix the `pipeline_reconciliation` swallow; fix the injury fail-open.
11. Delete the 13 unfireable alert policies and the `"401"/"403"` noise generator; wire the 9-policy minimum set.
12. `quantile_ceiling_under`: delete the 3.0 weight, or plumb quantiles.
13. Move `v1/admin/*` off the public bucket.
14. Create `nba-closing-lines-sweep` **paused**; demote `clv_diverge_under_block` (it blocks the best bucket).

### Tier 2 — measurement, before the first published pick (~Nov 17)
15. `bet_key` (excluding `system_id`) + an `is_backfilled` flag on `signal_best_bets_picks`. **Every HR query on that table is wrong until the flag exists.**
16. Publish log written *before* the DELETE; price/book/stake persisted at pick time.
17. Fix the `model_bb_candidates` writer (Task #39) → thousands of rows/season, which is the only way any promotion gate becomes reachable.

### Do NOT
- Do not backfill `model_performance_daily` (negative EV; `if rows:` skips the worst dates).
- Do not delete signal rescue — the case against it inverts on inspection.
- Do not lower the OVER floor to 3.0.
- Do not ship the BDB "two-line fix".
- Do not add a 4th model before the n7≥30 floor.
- Do not use `gcloud builds list` as a deploy oracle.
- Do not fix `nba_monitoring_alerts`' model id without also fixing its NULL cast at `:278` — that converts a dead monitor into an actively wrong one.

---

## 7. Open decisions for the owner

1. **Propagate the record correction?** `415-235 (63.8%)` is wrong three ways (unscoped join 3.7×, 63% retro, and it drives strategy). The defensible live number is **32-38 (45.7%, n=70)** — and even that sits inside the collapse window, so the honest statement is that **the published table supports no conclusion about OVER vs UNDER in either direction.**
2. **Do you actually place these bets, at how many books?** `DEFAULT_BREAKEVEN_HR = 52.4` assumes best-of-four-majors; single-book is 53.5%, which makes every gate 1.1pp too loose.
3. **`v1/admin/*` public** — separate bucket, or accept?
4. **`quantile_ceiling_under`** — delete, or plumb quantiles as the non-clone fleet member?
5. **Retrain before the opener?** The fleet trains through Apr 2-3, i.e. it already carries the late-season contamination the CF cap exists to prevent. A `--train-end 2026-02-28` retrain is strictly better as an opener fleet.
6. **Is "features are done" still established?** The residual test predicts error *from the same features the model consumed* — near-tautological, and at residual sd 6.75 the effect that would matter is R²≈0.002, smaller than the +0.004 being called zero.

---

*Seventeen agents, all read-only. Every ✅ item was re-verified in-session before being written
down. Nothing in the system was changed by this review.*
