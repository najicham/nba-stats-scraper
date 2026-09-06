# Five-agent review — 2026-09-01

> ⚠️ **CORRECTIONS APPLIED 2026-09-05** (second review round, verified in-session):
> 1. **The 08-20/08-21 scheduler snapshots were NOT truncated.** They hold 110 jobs because the
>    estate genuinely was 110 then; the 08-22 restore added exactly 59 (0 removed). CLAUDE.md's
>    "`weekly-retrain-trigger` was deleted" was **accurate when written** and went stale on
>    2026-08-22. The actionable conclusion (it exists PAUSED, `resume` it) stands; §2's stated
>    mechanism does not.
> 2. **`br-rosters-batch-daily` EXISTS, PAUSED** (created 02:12Z, 54 min after the last snapshot).
>    The only job that genuinely does not exist is **`nba-closing-lines-sweep`**.
> 3. **`bq` and `gcloud scheduler jobs list` do NOT hang** — measured 2.1s each. The long-standing
>    "hangs in WSL" note is wrong; the symptom was almost certainly `bq`'s interactive setup prompt
>    triggered by the wrong default project (`urcwest`). Always pass `--project_id=`/`--project=`.
> 4. **`AUTO_DISABLE_ENABLED=true`** on the deployed `decay-detection` CF — not "double-off".
> 5. **All 170 scheduler jobs have `retryCount` unset (0 retries)** — the "return 200 so the
>    scheduler doesn't retry" convention rests on a false premise.
> 6. **Every `logger.info` in every Gen2 CF is discarded** (`basicConfig` is a no-op once
>    functions-framework installs a root handler; root stays at WARNING). Verified across 5 CFs.

Five independent reviewers (season-readiness, verification/trust, profitability, infrastructure,
red team), all read-only, all measuring against live BigQuery/GCP rather than reading docs.

**The headline: the system cannot currently produce a prediction, grading has not run since
2026-08-24, and four separate tools report that everything is fine.**

Where two agents measured the same thing independently, that is marked ✓✓. Where they disagree,
that is marked ⚠ and left unresolved — those are owner decisions, not synthesis failures.

---

## 0. Broken right now (verified, not inferred)

### 0.1 `prediction-request-prod` has no subscription — Phase 5 publishes into the void

`predictions/coordinator/coordinator.py:186` → `publish_prediction_requests` (`:3550`) is the
**only** dispatch path; no HTTP fallback. The worker consumes via a Pub/Sub *push* subscription.

```
gcloud pubsub topics list-subscriptions prediction-request-prod  →  Listed 0 items.
subscriptions matching "predict"                                 →  prediction-request-dlq-sub only
```
(Verified directly in-session, not only by the agent.)

Pub/Sub **accepts and discards** messages published to a topic with no subscription, so
`published_count` is non-zero and the coordinator logs success.

**The mechanism is worse than the instance.** Every surviving subscription carries
`expirationPolicy.ttl = 2678400s` — **31 days**. MEMORY records this exact subscription created
2026-07-23 and "behavior-verified"; predictions then stopped for the off-season and GCP
garbage-collected it ~31 days later. **The off-season deletes the plumbing.** Any NBA subscription
idle 31 days is on the same timer. 15 of 21 subs also have `deadLetterPolicy = NONE`.

Fix: recreate the push subscription → worker `/predict` with a DLQ, and set
`--expiration-period=never` on **all** production subscriptions.

### 0.2 `phase5b-grading` has been 403-ing for 3 days — grading is not running

Pub/Sub push from `nba-grading-trigger` returning **403 continuously since 2026-08-30T05:37:24Z**,
>1,000 rejections, retry loop still live. Last successful invocation **2026-08-24T17:00:23Z**.

Nothing paged: the four alert policies naming this function all filter
`resource.type="cloud_function"` and cannot see a Cloud Run–backed Gen2 function.

Downstream: `model_performance_daily`, decay states, `fleet_blocked`, and the published record all
freeze silently.

### 0.3 Three commits unpushed, including the fix for the metric that auto-disables models

`2ec597c7` + `1aef6f68` + `89b7c690` (docs). All nine key services serve `BUILD_COMMIT=b81937e` —
current with `origin/main`, and **missing both fixes**. Fan-out measured at 6 triggers by two
agents independently ✓✓. `deploy-post-grading-export` is the one that must succeed.

Note: the seven new drift columns are **already live in BigQuery** while the code that writes them
is unpushed — the table currently has columns nothing populates.

---

## 1. The pattern, stated precisely

The verification agent's closing formulation, which the other four independently illustrate:

> **Every check in this system asserts the absence of a negative signal, and negative signals are
> exactly what a silent failure withholds.**

This is not a collection of bugs. Every layer that *could* report failure has been independently
configured to report success:

| Layer | How it reports success while failing |
|---|---|
| Pub/Sub | publish to a subscription-less topic returns a message id |
| CI | `test` workflow: **878/878 failures**, aborts at collection, deploy fires anyway |
| GH drift check | `check-cloud-function-drift.sh` omits `--project` → hits `urcwest` → checks **0 of 42** functions → prints `All functions up to date!` → exit 0 |
| GH drift check | both workflows grep `^❌.*STALE` but the scripts emit an ANSI escape first — the anchored pattern **cannot match**, even when drift is correctly found |
| Drift script | `check-deployment-drift.sh:257` loops over `$SERVICES`, **defined nowhere**; not `set -u`, so `:269` unconditionally prints `All services routing to latest revisions`. 212 references to this script. |
| CD workflow | `auto-deploy.yml:57` diffs `HEAD~1 HEAD` with `fetch-depth: 2` — on a 9-commit push it inspects only the tip (a docs commit), skips all 7 deploy jobs, reports **success** |
| Cloud Functions | `updateTime` and `state: ACTIVE` at the functions layer both lie; **9 CFs** report `commit-sha=b81937e` while serving older revisions. `latestReady == latestCreated` passes for all nine. |
| `emit_metric` | fail-open on missing dependency — **5 more services'** lock files still lack `google-cloud-monitoring` (coordinator, phase3, phase4, nba-scrapers, nba-grading-service). Phases 3 and 4 have **never emitted a datapoint.** |
| Alert policy | `phase-error-rate` encodes `RUNNING: 0.5`, `EXPECTED: 0.5` against threshold `LT 0.7` — normal in-flight state is below the alert line. 572 buckets in 30 days. |
| Uptime check | `/mlb` — **504/504 probes false** over 7 days while returning HTTP 200 in 71–164ms. Matcher looks for `"MLB"`; page contains `"mlb"` 14×, `"MLB"` 0×. |
| `verify-deploy.sh` | folds `MISSING` into `STALE`; `BUILD_COMMIT` covers **43 of 93** components and is unauthenticated free text (`mlb-phase1-scrapers` carries `BUILD_COMMIT=auto-discovery-fix`, a string absent from the repo) |

### 1.1 The absent-build rate is 37.9%, not ~1 in 10

Across 14 consecutive pushes: **169 triggers matched `includedFiles`, 64 produced no build.**
Loss scales with fan-out (≤14 expected → 0-14% absent; 26-30 expected → 43-65%).

The 2026-08-30 push lost **13 triggers, not 2**. `deploy-phase6-export` and `deploy-live-export`
appear 31 minutes later — manually re-run.

**Glob error is ruled out empirically:** in the `bc57ecb` push a single file
(`shared/utils/error_context.py`) matched 25 triggers through *identical* `shared/utils/**`
patterns; **8 built, 17 did not** — same file, same pattern, same second. Concurrency caps and
per-trigger diff bases are both refuted. Mechanism **remains unknown**; 64 is a floor, since the
one residual measurement risk produces false negatives.

Additionally: of 437 untriggered GCF child builds, **20 CANCELLED and 20 EXPIRED**, all carrying
no `TRIGGER_NAME` and no `SHORT_SHA` — invisible to any SHA-filtered query.

### 1.2 Components that have never run on their deployed code

- `nba-phase4-precompute-processors` — last `processor_run_history` row **2026-07-03** on revision
  `-00371-4rj`, *older than the deployed* `-00384-tn2`. **Nothing has ever run on the current code.**
- `nba-grading-service` — **2 HTTP requests total since 2026-02-01**, both `GET /health`.
- `phase5b-grading` — `phase_completion{phase="phase5b_grading"}` declared, deployed, **never once
  observed in 90 days**.
- `decay-detection`, `weekly-retrain` — never run.
- `weekly-gcs-backup` — **31/31 failures; no weekly backup has ever been produced.**
- `nba-phase2-raw-processors` — zero `processor_run_history` rows in 30 days despite logging
  `Started run tracking`; shutdown logs read `Flushed all 0 batch writers`.

### 1.3 Two log-suppression paths that make "no logs" meaningless

1. A `_Default` sink exclusion **`monitoring-info-suppression`** drops `severity=INFO` for
   services matching `(.*-check$)|(.*-monitor$)|(.*-reconcil.*)|(.*-decay.*)|grading-gap-detector`.
   `phase-completion-reconciler` demonstrably ran at 2026-09-01T19:00:05Z; its last log line of any
   kind is 2026-08-22.
2. `emit_metric` fail-open (§1 table).

**The best artifact class, missed by everyone until now:**
`region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT`. Four functions run under dedicated service
accounts, so `user_email` is a perfect fingerprint; the rest fingerprint on query text. It proves
execution, needs no library, no code change, and is **immune to both suppression paths**. It is
the only thing that proved the reconciler alive today.

---

## 2. Corrections to CLAUDE.md / MEMORY / the session-9 handoff

Ordered by how much each one has been steering decisions.

| Claim | Verdict | Correction |
|---|---|---|
| `weekly-retrain-trigger` was **DELETED**, must be **RE-CREATED**; "fires NEVER" | **WRONG** ✓✓ (3 agents) | It **exists, PAUSED**, correct cron `0 5 * * 1`, created 2026-08-22. The "deleted" finding came from the 08-20/08-21 snapshots, which hold **only 110 of 169 jobs — they were truncated.** Fix is `jobs resume`. ⚠ Check its `attemptDeadline: 180s` against a CF documented at 1800s first. |
| "59 jobs paused/deleted" — a multi-day reconstruction | **Misleading** ✓✓ | All 59 were restored 2026-08-22, PAUSED. Live estate is **170 jobs, 96 paused**. ~1 hour of `resume`, and the work is *verification*, not restoration. |
| Fleet is "10+ enabled shadow models" | **WRONG** | **3 enabled**, all `feature_set='v12_noveg'`, differing only by GBDT library, all trained through **2026-04-02** — 6.5 months stale on opening night. Also means `combo_3way` / `book_disagreement` (the two best live signals) are *cross-model* signals with no cross-model diversity. |
| "Season record 415-235 = 63.8%" | **WRONG** ✓✓ | It is the same ~175 picks counted **3.7×** — an unscoped join missing `system_id`. Scoped: **105-70 = 60.0%**, which is what the public site has shown all along. The §4 table prints both as if they were different layers of lift. The May 2026 audit's defence ("HR is invariant to replication") is false: replication is biased, since picks more systems agreed on are both more replicated and more likely to win. Effective N is 175, not 650; CI widens ±3.7pp → ±6.9pp. |
| "edge-6+ OVER hit 92.6% vs 38.9% across four prior seasons" | **Technically true, strategically worthless** ✓✓ | **25/27 vs 7/18.** The entire "OVER is structurally fragile" thesis rests on **eighteen picks across four seasons**. Defensible version: prior-4-season OVER edge≥3 = 48.6% (n=622) vs UNDER 54.9% (n=750) — a real ~6pp gap with a monotone UNDER curve, not the ~54pp implied. |
| CLAUDE.md "Top signals by HR": combo_3way 95.5%, combo_he_ms 94.9%, line_rising_over 96.6%, book_disagreement 93.0%, sharp_line_drop_under 87.5%, fast_pace_over 81.5% | **All six WRONG** ✓✓ | Live: **68.0 / 68.0 / 58.3 / 75.0 / never fired / 0% (n=2)**. Overstated by 20-40pp each. `sharp_line_drop_under` is advertised at 87.5% and **has never once fired.** |
| BDB "blocks every player" framing "may be wrong" | **The framing is RIGHT** | Feature 6 `shot_zone_mismatch_score` defaults to 0.0, is in `CRITICAL_FEATURES`, not in `OPTIONAL_FEATURES` → blocked under zero-tolerance. **But the NBA.com fallback is ~2 lines from working** — see §3.3. |
| "Cloud Run CPU quota is why builds go green while revisions never become ready" | **Was true 08-20, not the current constraint** | Cloud Run `cpu_allocation` = **20,000** with headroom. Real constraint is **Cloud Build queue starvation**: measured concurrency 7, `ongoing_builds` quota **5**, `concurrent_public_pool_build_cpus` default pool **4**, nested function builds dying on `queueTtl: 360s`. The 08-20 retry guard greps for `"Quota exceeded"`; the actual message was `CANCELLED` — **all four failed builds from 08-30 are still stale today.** |
| "`shared/config/nba_season_dates.py` alone pulled in 24" | **26**, and not the peak | `shared/clients/**` → **27 triggers**. Narrowing only `shared/config` fixes little. |
| "assume ~1 in 10 triggers silently does not fire" | **WRONG by ~4×** | **37.9%** (64 of 169 across 14 pushes). |
| "24 test files stub `google`… run per-directory" | **23 files, and not the CI blocker** | 22 under `tests/processors/` + `tests/fixtures/bq_mocks.py:38`. CI runs `tests/unit/`, broken by **2 different** `sys.modules` polluters. Deleting them: **4 collection errors, 0 tests → 101 passed, 13 failed.** |
| "SLACK_WEBHOOK_URL un-deadened 35 call sites" | **11** | 6 in `phase3_to_phase4`, 5 in `phase4_to_phase5`. `phase5_to_phase6/main.py` contains **zero** Slack code. 35 counted grep hits on the string, including guards and `logger.warning`. |
| "`decay-detection` has NO scheduler" | **WRONG** | `decay-detection-daily` exists, **PAUSED**. `AUTO_DISABLE_ENABLED` also defaults off — double-off, not absent. |
| "`deploy-monthly-retrain` is permanently red / red noise" | **Dormant, not red** | Its deleted dir is its only watched path, so the path can never change: **zero builds ever**. The real red noise is entirely GitHub Actions (~1,900 false reds/year). |
| "590 `AI call failed` rows"; "what invokes it is unidentified" | **WRONG on both** | **857 and growing 28/day** since 2026-08-20, during an off-season with zero games. Invoked by `registry-ai-resolution` (**ENABLED**, 04:30 ET) → `nba-reference-service/resolve-pending`, which is itself manually deployed and stale since 2026-04-04. |
| "the `past_game_days` guard keeps this from zeroing opening night" (`halt_state_writer:387`) | **Protects Oct 20 only** | `predictions_inactive` fires Oct 21 and stays active through the whole dead window. Incidentally suppresses 26 days of false DEGRADED — convenient, but undesigned. **Oct 20 itself is uncovered**: halt inactive + games present + zero outputs → DEGRADED → FAILED → `gap_detector` → backfill loop into processors that deliberately skip. |
| "Predictions blocked for ANY player with `default_feature_count > 0`" | **Wrong column** | Executing gate is `required_default_count` (`quality_gate.py:369`). Taken literally the documented rule would block ~every player. |
| "Clean rates 93%+ across all 4 seasons" | **High** | Measured 88.8 / 86.8 / 85.5 / 83.1 / 65.3%. |
| `high_spread_over_would_block` "CF HR 50% (7-7, N=14), need N≥30 at ≥55%" | **WRONG — gate already met** | Actual **28-19, N=47, CF HR 59.6%.** Nobody re-checked. |
| Manual-deploy CFs not in `deploy-function.sh` | **Stale** | All four **are** registered. `halt-state-writer`'s staleness is label-only, not behavioural. |
| "First predictions ~Nov 3-4" | **Rows yes, picks no** | See §3.1. First *pick* is **~Nov 16-17**. |

**An undocumented fourth deploy path exists:** `.github/workflows/auto-deploy.yml` deploys 7 core
Cloud Run services on push to main, watching `shared/**` → all 7. Absent from CLAUDE.md, every
handoff, and MEMORY. Its 8 recorded "successes" are vacuous (§1 table).

---

## 3. Season readiness — the dates are not where the docs put them

### 3.1 First pick is ~Nov 16-17, not Nov 3. Two stacked gates.

**Gate 1 — `BOOTSTRAP_DAYS = 14`** (`shared/validation/config.py:256`). `is_early_season(2026-11-02)
→ True`, `(2026-11-03) → False`. Confirmed by three tables: first 2025-26 row in
`player_prop_predictions`, `player_shot_zone_analysis`, and `player_composite_factors` is all
**2025-11-04**. Phase 3 is *not* gated — `player_game_summary` has rows from opening night.

**Gate 2 — the 15-game team-defense rule (this is what binds).**
`team_defense_zone_analysis_processor.py:94` `min_games_required = 15`; `:955` writes no row when
short. Features 13/14 read it with an **exact-date lookup and no fallback window**, default to
112.0/100.0 (`ml_feature_store_processor.py:1833`), and are in `CRITICAL_FEATURES`, not
`OPTIONAL_FEATURES` → every player blocked.

Load-bearing proof: across all **27,288 rows ever written**,
`MIN(games_in_sample) = MAX(games_in_sample) = 15`. First `analysis_date` per season: 2021-11-02,
2022-11-13, 2023-11-20, 2024-11-16, 2025-11-16.

Projected on the loaded 2026-27 schedule: Nov 12-16 → **0 teams**; **Nov 17 → 5**; Nov 19 → 19;
Nov 23 → 30.

> **Nov 3 = rows start. ~Nov 16-17 = first clean player. ~Nov 19 = volume. ~Nov 22-23 = full
> coverage. ~Dec 1 = first graded rows** (grading lagged first predictions by 15 days last season),
> which is when decay states, `fleet_blocked` and every retrain gate come alive.

Latent dead code: `_calculate_minimum_games_required` (`:1255-1294`) relaxes the threshold for days
0-21 measured from **Oct 1**, while the processor is skipped Oct 20–Nov 2 and first runs on day 33.
**The relaxation can never fire.** The sibling processor was fixed for exactly this
(`player_shot_zone_analysis_processor.py:621`); this one was not.

### 3.2 The binding deadline is ~Sep 20 — nineteen days out, and on nobody's list

All three roster seed sources are dead, and the NBA.com source has a **7-day** window:

| source | last data | seed window |
|---|---|---|
| `nbac_player_list_current` | **2026-04-26** | **7 days** |
| `espn_team_rosters` | 2026-04-26 (35 rows, 2 teams — playoff tail) | 30 days |
| `br_rosters_current` | 2026-02-01; `season_year` ∈ {2021…2025}, **no 2026** | 30 days + `season_year = @season_year` |

An Oct 1 seed needs an NBA.com scrape **between Sep 24 and Oct 1**. Resuming Wave A by ~Sep 20
leaves 4 days to notice a broken scraper. **October has two weeks of slack; September has none.**

`nba_reference.nba_players_registry` max season = `2025-26` — no 2026-27 rows, confirming MEMORY.

**Minimum viable Phase 1 restore is 2 jobs:** `master-controller-hourly` (`/evaluate`) +
`execute-workflows` (`:05`), both PAUSED. Every core feed — rosters, boxscores, gamebook, PBP,
injuries, **all betting lines** — runs inside workflows those two drive. The paused dedicated
scrapers (numberfire, vsin, rotowire, hashtag, teamrankings) are supplementary analytics only.
Everything downstream is event-driven and already deployed.

**Two jobs genuinely do not exist:**
- `br-rosters-batch-daily` — in the catalog as Wave A, `verified: true`, **never created**. On the
  roster-seed critical path. Can also be run by hand against the `br-rosters-backfill` Cloud Run job.
- `nba-closing-lines-sweep` — never in any backup ✓✓. **The sole blocker on CLV** (§4.2).

### 3.3 BigDataBall is existential *today* and ~2 lines from not being

Right: `nba_raw.nbac_play_by_play` **does** carry `shot_x`, `shot_y`, `shot_distance`, `shot_made`,
`shot_type`, with better tail coverage than BDB (last game 2026-05-03 vs 2026-04-17). And
`player_shot_zone_analysis_processor.py:489-490` declares **both** PBP sources while the
availability check at **`:532-536` queries only BDB**.

Wrong to conclude BDB is optional, because the fallback is broken twice over —
`sources/shot_zone_analyzer.py`:
- `:352` selects `COALESCE(player_name, player_id)`; **neither column exists** in
  `nbac_play_by_play` (the real one is `player_1_lookup`). The query errors.
- `:361` filters `WHERE event_type = 'fieldgoal'`; actual values are
  `2pt, 3pt, freethrow, rebound, foul, …` — **no `fieldgoal`.** Zero rows even if the columns existed.

It has never produced a row: `data_source` over 2025-10-01+ is `bigdataball` (992 games) + NULL (6)
— **no `nbacom_fallback`.** The scenario has never been tested because BDB delivered from day one
last season.

Fix: `player_1_lookup`, swap the filter to `shot_type IN ('2PT','3PT')`, widen the availability
check to accept either source. Prove it by withholding BDB on a historical date and asserting
`shot_zones_source = 'nba_play_by_play'` with non-zero `paint_attempts`. Delivery is a Google Drive
folder shared with the service account, so "delivery-proven" is one scraper run.

**Real BDB deadline is opening night, not Oct 1** — first Phase 4 run is Nov 3 over an Oct 20+
window. Oct 1 is a buffer, not the constraint.

### 3.4 Both money breakers are dormant through the ramp — by design

`VOL_MIN_PRIOR_PICK_DAYS = 5`, `DD_MIN_GRADED = 20` (`shared/config/drawdown_halt.py:210,172`).
Season scoping uses Oct 1, safely before the opener, so peaks reset cleanly. But the first ~5
pick-days and first 20 graded picks run with **no drawdown and no volume protection** — in a season
where the OVER side is explicitly unproven.

---

## 4. The betting side

### 4.1 ⚠ THE UNRESOLVED CONTRADICTION — read this before touching the OVER floor

Two agents measured different populations and reached opposite conclusions.

**Profitability agent** — leak-free `walkforward_sim_predictions`, 5 seasons, *pre-selection
candidates*:

| dir | prior-4 | 2025-26 |
|---|---|---|
| OVER edge≥3 | **48.6% (n=622)** → −7.2% ROI | — |
| UNDER edge≥3 | **54.9% (n=750)** → **+4.9% ROI** | — |

UNDER's edge→HR curve is **monotone** in normal seasons (52.6 → 53.8 → 55.4 → 57.3 → 61.3); OVER's
is flat-to-negative at every bucket. → *Hold the OVER floor at 6.0.*

**Red team** — the 189 graded *published* picks, i.e. **post-selection**, the only genuine
out-of-sample money record:

| edge | OVER | UNDER |
|---|---|---|
| 3-5 | 45.7% (n=35) | 44.4% (n=27) |
| 5-6 | **62.1% (n=29)** | 55.6% (n=27) |
| 6+ | **72.3% (n=47)** | 66.7% (n=24) |

**OVER beat UNDER in every bucket.** Session 522's 5.0→6.0 floor raise deletes the edge 5-6 OVER
bucket that hit 62.1% live. → *The floor raise was a wrong-direction decision made on n=18.*

**Both can be true** — pre-selection candidates and post-selection published picks are different
populations, and the selection layer is exactly the difference. But note what that implies: if the
selection layer is what makes OVER work, then it was tuned on the one season OVER worked. Neither
sample is large enough to settle this alone. **This is an owner decision and it should not be made
by whichever agent is quoted last.**

Also in the red team's numbers, and awkward: picks *without* the `high_edge` tag — i.e. signal
rescues that bypassed the edge floor — went **29-35 (45.3%)**, below breakeven. And the base
signals `real_sc` exists specifically to discount as "zero value" carry **65.6% at n=125**, while
the non-base signals they defer to run 36-58%.

### 4.2 CLV is blocked on one uncreated scheduler ✓✓

`scrapers/routes/closing_lines.py` (T-30 per-game sweep) **is deployed and registered**
(`main_scraper_service.py:33,54`); `bin/deploy/deploy_closing_lines_scheduler.sh` exists. The job
`nba-closing-lines-sweep` has simply never been created. `phase6-clv-reexport-late` (19:30) also
never deployed. The single 16:30 checkpoint sees only **47% of eventual against-moves** (75% by
18:40, 99% by 21:00).

Live and blocking today: `clv_diverge_under_block` (`aggregator.py:1268-1282`, UNDER only,
threshold −0.5) — but on a **T-3h to T-6h read, not a close.**

The measured value is entirely in the **negative** tail:

| tag | n | HR |
|---|---|---|
| `negative_clv_filter` | 21 | **28.6%** |
| `positive_clv_under` | 50 | 50.0% |
| `positive_clv_over` | 37 | 51.4% |

⚠ The "+14pp on true close" figure is a conditional split of the whole population (N=1,155,
2025-26 only). The **rule's** value, sized on the repo's own larger analysis (N=4,795,
`00-GAMEPLAN.md:236-252`): UNDER picks whose multi-book mean rises ≥1.0 post-publish run **44.3%
(N=97) vs 60.3% flat** → **+0.5-1.5u per 100 picks**, not +14pp. OVER against-movers were
**refuted** as poison.

### 4.3 The 2025-26 record is unauditable, and the machinery that destroyed it is about to run more

`gs://…/signal-best-bets/*.json`: 198 files, **95 regenerated after their own game date**; the
entire 2025-11-19 → 2026-01-24 stretch was overwritten to `picks: []` on 2026-02-22. **98 picks
across 28 days survive**, going 31-39, −10.80u. `best_bets_export_audit` starts 2026-01-25.

If CLV ships, the re-export path runs *more* often, not less. **An immutable append-only publish
log is the precondition for 2026-27 being measurable at all.**

### 4.4 The selection layer is mostly inert, and its promotion gates are unreachable

Of 97 registry entries, exactly **16** can ever increment `real_sc`. Measured live:

- **5 active signals have never fired**, including `sharp_line_drop_under` (advertised 87.5%) and
  **`quantile_ceiling_under`, which carries the highest UNDER weight (3.0) and has no row in
  `signal_health_daily` at all**.
- **12 active signals have <10 live fires.**
- **15 active filters have never blocked anything.**
- 3 registry-`active` filters have **no implementation**: `star_under`, `neg_pm_streak`,
  `anti_pattern`. `opponent_depleted_under`'s `continue` is commented out.
- The **top-2 OVER weights** (`line_rising_over` 3.0, `book_disagree_over` 3.0) are stripped by
  `SHADOW_SIGNALS` before the weight lookup — dead.
- 50 shadow signals + 20 observation filters accumulate at ~200 picks/season. **An N≥30 gate takes
  3-15 seasons for most of them.** `whole_line_precision` needs ~2,500 lined picks.
- Two non-base signals in all of history have ever reached N≥30.

Against ~189 live graded picks sit **100+ tuned degrees of freedom** — roughly two observations per
parameter — and the 3-month window contains **18 distinct `algorithm_version` values.** The
selection layer was rewritten more often than it was measured.

### 4.5 Nobody can verify a published pick was bettable

`line_bookmaker` and `line_source_api` are **100% NULL across all 74,108 lined rows of 2025-26.**
No book attribution, no odds-snapshot age, no price. `roi_simulation` and `roi_summary`: **0 rows**
— so the drawdown breaker computes "realized P&L ≥ 6u" from a quantity **nothing persists**.

⚠ And `DEFAULT_BREAKEVEN_HR = 52.4` (`shared/config/breakeven.py:26`) assumes execution at the best
of four majors. Measured single-book payout is 0.870 → **53.5%**. If four books are not actually
shopped every night, **every gate in the system is 1.1pp too loose** — worth more units than any
code change on the list.

### 4.6 Tested and dead — do not retry

- **Rolling absolute margin** `|actual − line|` (the §6 "genuinely new thing"): built and tested
  directly. All four z-stats **|z| < 1.2**, quintiles non-monotone in both directions. Variance
  persisting cross-season (r=0.642) **does not translate into directional edge.** Build the chart;
  do not build the signal.
- Note f56 `margin_vs_line_avg_last_5` (signed) has **zero consumers**, and f55 `over_rate_last_10`
  has exactly two — **both in `SHADOW_SIGNALS`**, so it also has zero effect on picks today.
- Any streak / "beat his line N straight" leaderboard: r=0.143; `over_trend_over` at 53.2% (n=47).
- New model features: held-out residual R² = +0.004. ⚠ But see §5.3 — that conclusion is weaker
  than it looks.

---

## 5. The three genuine strategic forks

These are not task-list items. Each is a decision the owner has to make, and each has been made
implicitly by inheritance rather than explicitly.

### 5.1 OVER floor: 6.0, back to 5.0, or suppress OVER entirely?
See §4.1. Currently set at 6.0 on the strength of **n=18**, against a live record where OVER
outperformed UNDER in every bucket. The HSE rescue already bypasses the floor anyway.

### 5.2 Does anyone actually place these bets, and at which book?
This changes everything downstream. If yes: the book/CLV/units gap (§4.5) is the top item, the
53.5% breakeven correction applies immediately, and CLV is genuinely the #1 lever. If the product
is informational only, CLV is **not** the #1 lever and that framing should come out of the docs.

### 5.3 Is "features are done" actually established?
`scripts/nba/training/discovery/error_decomposition.py` trains a model to predict `actual −
predicted` **from the same feature columns the base model already consumed**, leave-one-season-out.
Three objections, and they are serious:
1. **Near-tautological.** A well-fit GBDT leaves residuals ~orthogonal to its own inputs. R²≈0
   proves the base model extracted what is in X; it says nothing about features *not in X* — which
   is the actual question.
2. **LOSO conflates "no structure" with "season-specific structure"** — and this project's own
   position is that almost nothing transfers across seasons.
3. **Resolution is inadequate to the economics.** Residual sd is 6.75. Moving edge-3+ HR from 53%
   to 56% needs a conditional shift of ~0.3 pts → **R² ≈ 0.002**. The reported **+0.004 is larger
   than the effect that would matter.** Calling it "≈0" is a units error.

"Three independent confirmations" describes **three runs of one construction.** If this wall comes
down, the research program's central premise changes.

---

## 6. Candidate paths

Costs are working days. Path 0 is not optional and is not counted.

### Path 0 — Unbreak (≈1.5 days). Prerequisite to everything.
Recreate the `prediction-request-prod` push subscription with a DLQ; set
`--expiration-period=never` on **all** production subs; add DLQs to the 15 without one; fix the
`phase5b-grading` 403; push the 3 commits and verify `deploy-post-grading-export` **by name**.
*Nothing else on this list matters if this is not done.*

### Path A — "Make green mean something" (≈3-4 days)
Fix the 4 fail-open drift checks; delete the 2 `sys.modules` polluters so CI runs for the first
time; fix `auto-deploy.yml`'s diff base; build the `INFORMATION_SCHEMA.JOBS_BY_PROJECT` liveness
query (hours, no code change, immune to both suppression paths); compute the expected trigger set
and feed it into `verify-deploy.sh` as `$@`. Fix the `/mlb` matcher and `phase-error-rate`
threshold.
**Buys:** ~1,900 false reds/year → ~0, a real test signal before a 6-month unattended run, and one
command that would have caught all three 08-30 failure modes (13 absent builds, 4 failed builds, 9
green-but-stale functions).
**Risks:** turning CI on exposes 13 real coordinator failures — that is the point, but it is
unplanned work.

### Path B — "Make the season happen" (≈3-4 days, deadline-driven)
Resume `master-controller-hourly` + `execute-workflows` **by ~Sep 20**; create and run
`br-rosters-batch-daily`; fix the two-line NBA.com shot-zone fallback and prove it with BDB
withheld; seed rosters Oct 1-6 **checking per-source contribution and team count**, not
`Status: success`; resume Waves B/C in October (fix `weekly-retrain-trigger`'s 180s
`attemptDeadline` first); create `nba-closing-lines-sweep`.
**Buys:** the season, and it removes a supplier from the critical path permanently.
**Risks:** the Sep 20 date has no slack and is currently unowned.

### Path C — "Instrument the money" (≈2 weeks)
Book attribution on every pick; the closing line captured at tip; a units ledger; an immutable
append-only publish log.
**Buys:** 2026-27 becomes the first honestly measurable season. Without it, next year ends exactly
as this one did — a headline number that cannot be reproduced from any table and turns out to be
inflated by a join.
**Risks:** zero units this season; it is pure infrastructure for future decisions.

### Path D — "Edge only, first month" (contrarian; ≈1 day of deletion)
Turn off signals, filters, rescue, per-model pipelines and the merger. Publish `edge≥6` both
directions from the 3 enabled models, capped at 5/day, ranked by edge. Keep the halt gate,
drawdown breaker, volume cap, zero-tolerance.
**Buys:** on the live record edge 6+ = 72.3% OVER / 66.7% UNDER, and everything the selection layer
adds on top of edge is either unmeasurable (n<10) or negative (rescue at 45.3%). **~90% reduction
in failure surface** with no *measured* loss of EV, and it produces the first clean unconfounded
sample the project has ever had.
**Risks:** discards machinery that may genuinely work but is unmeasurable at this N; halves volume
into a documented pick-drought failure mode.

### Path E — "Fix the fleet" (≈2-3 days + retrain time)
Resume `weekly-retrain-trigger` (a *resume*); train at least one genuinely different model (not a
fourth GBDT on `v12_noveg`); then **re-derive every conclusion that used `model_performance_daily`
before the 2026-08-31 grading fix** — `fleet_blocked` reachability, the OVER floor, the signal HR
table, the CF HRs.
**Buys:** the fleet is 3 stale clones; cross-model signals cannot work without diversity.
**Risks:** ⚠ **the retrain gate deadlock** — governance needs graded 2026-27 data (~Dec 1) while
the fleet's training data ends in 2025-26. There is a plausible window where nothing can legally
retrain while serving models are 13+ months from their training data.

### Deletion, available under any path (≈1 day, free)
20 signals + 15 filters with **literally zero live fires**; the breakout classifier (7+ months
shadow on an AUC from a *disabled V1 with a broken feature pipeline*, both its signals never
fired); `roi_simulation`/`roi_summary` (0 rows, implying a P&L that does not exist); the 4 broken
verification scripts (`verify_deployment.sh`, `verify-phase6-deployment.sh`,
`check-active-deployments.sh`, and **`deploy-all-stale.sh` — a mutator gated on a broken predicate
that deploys `:latest` rather than HEAD**). Pause the assists/rebounds props scrapers (4 enabled
schedulers for markets the system does not bet). Set `minScale=0` on the 4 always-on services until
~Oct 15.

**Suggested sequencing: 0 → B (Sep 20 is the wall) → A → C, with deletion folded in anywhere.**
D and E are strategic bets that depend on §5.

---

## 7. Open questions only the owner can answer

1. **415-235 or 105-70?** Every internal doc, MEMORY, and the strategic gameplan use 63.8% on
   n=650. Propagate the correction and re-examine every decision made against it?
2. **Are you willing to act on n=18?** The OVER floor and the whole UNDER-first thesis rest on it,
   against a live record that says the opposite.
3. **Do you actually place these bets, at which book, and how many?** Determines whether 52.4% or
   53.5% is the real bar, and whether CLV is the #1 lever or a doc artifact.
4. **Was `prediction-request-prod` load-bearing, or has Phase 5 moved to another dispatch since
   July?** i.e. is §0.1 a regression or a long-standing hole. Determines how much else to distrust.
5. **Who owns the ~Sep 20 Wave A resume?** 19 days, no slack, currently on no list.
6. **Buy the BDB pass, or fund the ~half-day fallback fix?** The fix is cheaper than one season
   pass and also covers the pass lapsing mid-season.
7. **Will you delete?** 20 signals and 15 filters with zero live fires. Free to remove; keeping
   them means every future debug session reads machinery that has never executed.
8. **Retrain policy given the gate deadlock** (§6 Path E) — manual `./bin/retrain.sh` on a relaxed
   gate in late November, or serve as-is into December?
9. **Re-run `error_decomposition.py` with features the base model never saw?** If the answer
   changes, "features are done" comes down.
10. **Which deploy pipeline is authoritative** — Cloud Build triggers or the undocumented GitHub
    Actions CD? Running both doubles quota pressure and creates two silent-skip modes.

---

*Five agents, ~1.08M tokens, all read-only. Nothing was changed. The `prediction-request-prod`
finding was independently re-verified in-session before this document was written.*
