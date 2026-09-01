# Session 9 — start here

**Today 2026-09-01. Opener Tue 2026-10-20 (49 days). Seed window Oct 1-19, drop-dead Oct 6
(35 days). BigDataBall check window is NOW. First predictions ~Nov 3-4.**

Previous: `2026-08-24-SESSION-8-START.md`. That document's §5 list is still the backlog; this one
records what session 8 executed, what it measured, and which of its claims turned out to be wrong.

---

## 0. First five minutes

**Repo is clean. HEAD `1aef6f68`. Two commits are unpushed and their fan-out is already measured
at 6 triggers (see §3).**

```bash
git log --oneline origin/main..HEAD          # expect 2
git push origin main                          # 6 triggers; deploy-post-grading-export MUST land
./bin/verify-deploy.sh post-grading-export phase6-export live-export prediction-worker
```

**Environment gotchas (unchanged, still true):**
- Local `gcloud` default project is **`urcwest`**. Always `--project=nba-props-platform`, and set
  `GCP_PROJECT_ID=nba-props-platform` for local Python.
- `bq` CLI and `gcloud scheduler jobs list` hang in WSL. Use the Python BQ client and per-job
  `describe`. Wrap `gcloud` in `timeout`.
- pytest **per directory** with `-p no:cacheprovider`.
- Never `git checkout --` to undo an experiment. `cp` to a backup and restore from that.

---

## 1. The one thing to carry forward

Session 7's finding was "7 of 11 defects reported success while failing." Session 8 did not
disprove it — it **found four more instances**, and the most expensive one had been live for
months in the metric that decides whether a model gets switched off.

The new lesson on top of that one is narrower and sharper:

> **Absence of an error is not evidence of success. Require a positive artifact.**

This session produced a clean demonstration. After deploying the fix that lets `phase6-export`
emit metrics, the logs showed no `monitoring_v3 not available` warning, and it was reported as
"emitter is live." That was **wrong** — the only post-deploy invocation was a startup probe, and
the warning only appears when an emit is *attempted*. The correct proof came later and looked
completely different: a new `phase_completion` time series with `output_type="daily"`, a label
only `phase6-export` writes, at a timestamp matching its own log line to the second.

Three separate times this session, a guard reached the right verdict for the wrong reason —
matching text inside a **comment** rather than code. Strip comments before asserting on source.

---

## 2. What session 8 shipped

Eleven commits, `9ce5bb32..1aef6f68`.

### The bug that matters most: an ungraded prediction counted as a LOSS

`2ec597c7`. `CASE WHEN prediction_correct THEN 1 ELSE 0 END` casts **NULL to 0** in BigQuery, and
`daily_results` in `ml/analysis/model_performance.py` was the one CTE in that query missing
`prediction_correct IS NOT NULL`.

| window (edge>=3) | ungraded | HR as computed | true HR |
|---|---|---|---|
| 2026-01-01..04-07 | 25.6% | **39.6%** | 53.2% |
| 2026-02-22..03-01 | 35.4% | **34.1%** | 52.8% |

Thresholds are BLOCKED < 52.4 / DEGRADING < 55 / WATCH < 58, and **`decay_detection`
auto-disables BLOCKED models**. Over the week to 2026-03-01, **2 of 12 models were BLOCKED purely
by this**, the worst being `ensemble_v1` at **8.3% when it was really 62.5%** — the best model in
the fleet, one auto-disable away from being turned off. It bites hardest when grading lags, i.e.
when the pipeline is already unwell.

`1aef6f68` fixes the same shape in three user-facing numbers: `historical_accuracy` in
`best_bets_exporter` (x2, 730-day window) and `win_rate` in `player_season_exporter` (numerator
graded, denominator not). MLB was always correct — NBA was the outlier.

⚠️ **Stored rows in `model_performance_daily` are still wrong.** Every historical row carries the
buggy HR. `--backfill` exists; not run, because it rewrites history. **Decide before the opener** —
that table feeds the decay state machine and `fleet_blocked`.

### Drift diagnostics that see what hit rate cannot

Same commit. Seven new columns, live in the table and in the schema file.
`pred_bias_uncond_7d/14d`, `_t_7d`, `_n_7d`, `cover_margin_7d`, `_t_7d`, `realization_beta_14d`.

The existing `pred_bias_*` is measured only on edge>=3 rows — a subsample **the model selects for
itself**. Measured 2026-01-01..04-07 it reads **-2.236 against -0.978 unconditionally**; most of
the 2.3x gap is selection, not drift, because conditioning on `|predicted - line|` picks extreme
predictions and extreme predictions regress. **The "-2.23 in Nov 2025" figure quoted in the code
and in the anomaly docs is inflated the same way.**

Sensitivity: the unconditional version detects a **0.58 pt** shift in 3 days versus **1.04 pt** on
edge>=3 (360 vs 109 rows/day, residual sd 6.75).

### The safety net could not see its own terminal states

`d06f8a79`, `90dd713d`, `bf1f4bf0`. `gap_detector`'s `overdue_count` counts EXPECTED + DEGRADED
only, so a row hitting the attempt cap and flipping to FAILED **leaves the counted set and drives
the metric DOWN** — giving up looked like recovery. Measured live: `overdue_count` = 3 against a
threshold of 5 (reading healthy) while **74 rows sat FAILED**. Eight straight days of FAILED MLB
rows paged nobody.

New `failed_count` is uncapped and **sport-labelled** (MLB carries a permanent backlog that would
hold any NBA threshold tripped). `planning_horizon_days` measures planner liveness as a level, not
an absence — Cloud Monitoring caps `conditionAbsent` at 23h30m and the planner's cadence is 24h,
so every legal absence window would fire ~1h a day, every day.

### Half the metric-emitting Cloud Functions never emitted anything

`2b8d5a8f`. `emit_metric` fails open on a missing dependency: the function runs, reports success,
emits nothing, and the only symptom is absent data. **3 of 6 emitting CFs** lacked
`google-cloud-monitoring` — including `phase6_export`, home of **`halt_gate_overridden`**, the
emergency-override tattletale and the highest-priority unwired metric in the Phase B plan. Every
emission was dropped. Now verified live by positive artifact.

### The season flip: two boundaries that named different seasons

`faed1f44`, `8f6ebf6c`. Labels flipped at `month >= 10`; every season *window* was a hardcoded
`date(year, 11, 1)` chosen with `month >= 11`. From **2026-10-20 to 10-31** an exporter would have
stamped `season: '2026-27'` on a window starting **2025-11-01** — publishing last season's picks
and record, publicly, under the new season's name, during opening week.

Corrections to the session-8 handoff, both measured: **9 sites across 7 files, not 7** (two were
truncated out of the first grep by `head -20` and surfaced only from a residual sweep), and
**203 picks of exposure, not ~650** (650 is the 2025-26 graded record 415-235; the tables these
exporters read hold far fewer).

`team_context.py` had the same shape: three season-average CTEs on a hardcoded `'2025-10-22'`,
feeding star identification and `stars_out`. Both literals were **also already wrong** — the
2025-26 opener was 2025-10-21.

### Alerting

4 new policies (NBA `failed_count`, planner liveness, `halt_gate_overridden`,
`bq_streaming_insert_failed`); `[WARNING] NBA Stale Predictions` **disabled** with its post-mortem
in its own `documentation` field — it was dead twice over (its log string exists nowhere in the
repo, and an absence condition needs a series that has existed); `SLACK_WEBHOOK_URL` bound on both
phase orchestrators, un-deadening **35 call sites**.

---

## 3. Deploy discipline — now measured, not guessed

**Measure the fan-out before pushing.** Match `git diff --name-only origin/main..HEAD` against
every enabled trigger's `includedFiles` (glob: `**` crosses directories, `*` does not; **no
`includedFiles` = fires on every push**).

The 9-commit push fired **30 of 36 triggers**, and **`shared/config/nba_season_dates.py` alone
pulled in 24**. Any change under `shared/config/**` is a ~24-service rebuild — that is why this
repo keeps hitting the Cloud Run CPU quota. The 2 currently-unpushed commits fire **6**, because
they touch no shared config.

**A starved build is fail-SAFE**: no revision is created, so the service keeps serving its current
correct code. So the question is never "how many fire" but **"which MUST succeed."** On the
30-trigger push, 6 failed on quota and all 6 were verified harmless — none called the changed code.

⚠️ **Two enabled triggers produced NO BUILD AT ALL** (`deploy-phase6-export`, `deploy-live-export`).
Not failed — absent. **Third occurrence** (session 8's handoff recorded two on 08-23). Assume
~1 in 10 matching triggers silently does not fire, and **verify by name**, never by counting.

**Remediation — never re-push to fix a straggler:**
```bash
gcloud builds triggers run deploy-phase6-export --region=us-west2 --project=nba-props-platform --branch=main
```
Zero fan-out, uses the trigger's own config. Strictly better than registering the function in
`bin/deploy-function.sh`, which would mean hand-reproducing the config of the service that carries
the halt gate.

---

## 4. Where performance actually stands (measured 2026-09-01)

Do not read the raw-model number as the product's number.

| layer | 2025-26 |
|---|---|
| raw model, edge < 3 | **51.7%** (n=20,659) — *below* the 52.4% breakeven; this is why the edge floor exists |
| raw model, edge 3-5 | 56.7% (n=6,986) |
| raw model, edge 6+ | 60.0% (n=3,055) |
| **published best bets** | **60.0%** (105-70, surviving rows) |
| season record as booked | **415-235 = 63.8%** |

⚠️ **2025-26 was anomalous.** Grading the clean walk-forward cache directly: **edge-6+ OVER hit
92.6% last season against a documented 38.9% across the four prior seasons.** Do not plan on 63.8%
recurring. UNDER is the durable engine; the OVER floor at 6.0 is the response.

**The model is not the bottleneck.** Held-out residual R² for added features is **+0.004** — three
independent confirmations that adding model features cannot help. Selection (signals/filters)
already lifts ~57.8% to 60-64%. The identified next lever is **CLV** (UNDER HR +14pp on the true
close; drop a pick when the close moves >=0.5 against it).

---

## 5. Open items, ranked by deadline

### Now — September
1. **BigDataBall NBA play-by-play season pass.** Not yet on sale as of 2026-09-01. **Email them.**
   Ask: will 2026-27 NBA PBP be offered, when does it go on sale, any schema/format/delivery change
   vs 2025-26, and what is the earliest delivery date. Needs to be purchased AND delivery-proven by
   Oct 1.

   ⚠️ **But the "blocks every player" framing needs verification before it drives decisions.**
   Measured 2026-09-01: `nba_raw.nbac_play_by_play` carries **`shot_x`, `shot_y`, `shot_distance`,
   `shot_made`, `shot_type`** — the same shot-location fields BigDataBall provides — with
   comparable coverage (**1,007 games vs BDB's 998** in 2025-26). `player_shot_zone_analysis`
   *declares* both PBP sources as dependencies but hardcodes BDB in its availability check
   (`:535`). And shot-zone fields in `player_game_summary` are only **27.3% populated** for
   paint/mid-range already, with `shot_zones_estimated` and `has_complete_shot_zones` flags
   implying a degraded mode exists. **Establish what feature 6 actually does when shot zones are
   missing before treating BDB as existential.** A fallback to NBA.com PBP looks feasible.

2. **Re-create `weekly-retrain-trigger` and the Wave C schedulers.** Forgetting weekly retraining
   is the documented root cause of the 2025-26 collapse. The function is current; it fires never.
   59 jobs are paused/deleted (`ops/scheduler-catalog-2026.yaml`).

3. **Decide the `model_performance_daily` backfill** (§2). Stored HRs are wrong.

### Before October
4. **The remaining monitoring CFs that ACK their own crashes** — the rest of the return-200 family.
5. **`fleet_blocked` reachability** — unreachable only by denominator pollution; fires 7 of 19 days
   when replayed on the actually-enabled fleet. Decide before season week 2.
6. **Export-time volume cap in `pipeline_merger`** — still the only thing that could catch a
   one-slate blowup; both breakers evaluate at 5 AM on yesterday's data.
7. **Roster seed** (Oct 1-6). Rehearsal passes end-to-end; it is a data question now, not a
   machinery question. Recipe in the session-8 handoff §6.

### Recorded, unverified
8. **The AI name resolver fails silently and daily** — 590 rows in
   `nba_reference.unresolved_player_names` whose `notes` begin `"AI call failed: ... 'Your cred…'"`.
   Session 8 initially called this "coupled to the Oct 6 seed drop-dead"; that **overstated it** —
   the seed rehearsal passed at 522 players while the resolver was failing. It degrades the
   unresolved-name tail, not the seed. Credential rotation was owner-deferred to September.
9. **`whole_line_precision` may be starved.** Whole-number lines are **1.22% of 2025-26 rows, down
   from 3.74% in 2024-25** — and **0%** in `player_game_summary` (that table is all half-points,
   so the two tables' "line" are different objects). Its N>=30 promotion gate will take far longer
   than assumed.
10. **24 test files still stub the `google` namespace** (`grep -rn "sys.modules\['google" tests/`).
11. **Two byte-identical duplicate alert policies** (`[WARNING] NBA Environment Variable Changes`,
    ids `12842169831579599906` / `1771264843392742585`). Both left unwired so neither double-pages.
    Delete one, wire the other, or leave.

---

## 6. Product direction: the margin views (6-agent review, 2026-08-30)

Owner proposed (A) a list showing how much each player beat their line by, and (B) a per-player
LINE / AVERAGE / RESULT chart.

**Most of it already exists.** `player_game_summary` has a physical **`margin`** column ("actual
points minus line"), populated for 7,696 of 8,280 lined rows. Five exporters compute margin
inline. `player_profile_exporter:335` recomputes it instead of reading the stored column. So (A)
is **a ranking and a page, not a pipeline**. For (B), LINE and RESULT already ship as per-game
series in four exporters; only an aligned **rolling AVERAGE** series is missing, and
`player_game_report_exporter._query_moving_averages` is an exact in-repo precedent.

**The number that should shape (A): only 19.3% of player-game rows have a line** (8,280 of
42,841). The "no line → use their average" fallback is not an edge case, it is **four-fifths of the
view**. A single mixed column would be ~80% self-relative numbers, and worse, it **inverts the
ranking**: a 4.8-PPG bench player scoring 19 in garbage time posts +14 against his average, while a
star with a sharp 28.5 line rarely clears ±10 — because the line already prices form and matchup.
The grading pipeline already made this split deliberately (`line_source` ∈
`ACTUAL_PROP` / `NO_PROP_LINE` / `ESTIMATED_AVG`, with NO_PROP_LINE excluded from accuracy). Reuse
that enum; do not invent a third baseline.

**Do NOT build:** any streak or "beat his line N straight" leaderboard — player over/under rates
are **not** stable cross-season (r=0.143) while **variance is** (r=0.642), and `over_trend_over`
already sits in SHADOW at **44.4% HR**. It was tried; it loses.

**The genuinely new thing worth building: rolling absolute margin** — `|actual - line|` per player,
"how badly does the market price this guy." Nothing in the repo computes it, it is the r=0.642
quantity that persists, and it is the right y-axis for the chart. Note that `over_rate_last_10`
(f55) is already wired into two signals while `margin_vs_line_avg_last_5` (f56) — the **signed**
one — is used by no signal at all. The half that doesn't persist is the half nobody wired up.

---

## 7. Working discipline that earned its keep

- **Require a positive artifact.** A missing error message is not proof. See §1.
- **Measure before building.** The case for the drift columns rested on a selection effect; one
  query showed it was 2.3x and reframed the whole change.
- **Mutation-check every assertion, and make the mutation assert it applied.** Several mutations
  this session would have been vacuous.
- **Strip comments before asserting on source.** Three guards matched prose before code.
- **Re-sweep after a bulk fix.** `head -20` hid two of the nine season-flip sites; only a residual
  grep after fixing the first seven found them.
- **Compare failure *sets*, not counts**, and establish the baseline by restoring the old file.
- **Verify a claim's population.** "203 not 650" and "9 sites not 7" both came from re-measuring a
  handoff claim rather than inheriting it.

*Session 8 closed 2026-09-01. HEAD `1aef6f68`, tree clean, 2 commits unpushed (fan-out measured at
6 triggers). Everything else is deployed and verified by BUILD_COMMIT.*
