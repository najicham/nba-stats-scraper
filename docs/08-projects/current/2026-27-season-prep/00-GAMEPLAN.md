# 2026-27 Season Game Plan

**Created:** 2026-08-19 · **Opener:** Tuesday **20 October 2026** (confirmed vs the published
schedule AND `MIN(game_date)` over the 1,207 regular-season rows in `nba_raw.nbac_schedule`;
season ends 2027-04-11, 160 game days) · **Days remaining at creation: 62**

**Supersedes the sequencing sections of** `docs/09-handoff/2026-07-03-5-adjudicated-plan.md`.
That plan's July work landed; its August/September/October sections are replaced by this
document, which is built on findings that did not exist when it was written.

---

## 1. The thesis

The system's failures have not been modeling failures. Adding model features cannot help —
held-out residual R² for new features is ≈ **+0.004**, confirmed three separate times, and a
2026-08-19 sweep of ten independent analyses added no counter-evidence. What has actually cost
seasons:

- a **deleted scheduler nobody could see** (weekly retraining fired never — the 2025-26 root cause),
- **code that runs and affects nothing** — three separate silent no-ops found in one night,
- **panic-deploy churn during drawdown** — ten algorithm versions in the March 2026 window,
- **execution leakage** — ROI reported at a flat -110 overstates reality by 3.1-4.5 pp.

The edge itself is real and cross-season validated: the best-bets pipeline runs **60-66%** against
a break-even of 52.4-53.5%; UNDER at edge ≥6 holds ~61% across five seasons; the low-line
low-variance UNDER archetype hit 62.0% (N=819) in 4 of 4 seasons. **The work is not finding an
edge. It is stopping the leaks around one that already exists.**

---

## STATUS — updated 2026-08-20

Owner decisions 1, 2, 3 and 5 are made. §2.1 auto-halt, §2.3 worker filters and
§2.4 deploy gate are **DONE** and now **PUSHED AND DEPLOYED** (2026-08-20).
§2.2 health multipliers is **MEASURED but not decided**. The P1 list is open.

| § | Item | Status |
|---|---|---|
| 2.1 | Auto-halt recalibration | **DONE** — median variant + hysteresis, `shared/config/edge_halt.py` |
| 2.2 | Health multipliers never apply | **MEASURED 2026-08-20** — confirmed inert: **0 of 3,855** `signal_health_daily` rows exist on their own game_date (min lag 1d), so the read returns empty every time and `_health_multiplier` always returns 1.0. Fork still undecided — the lag-1 predictiveness test is the remaining work |
| 2.3 | Panic-era worker filters | **DONE** — 3 deleted, `star_under_bias_suspect` moved to observation |
| 2.4 | Deploy test gate + build timeout | **DONE** — gate is step 0 of all four NBA build configs |
| 2.2b | Scheduler restore script | **DONE** — but the backup it was meant to replay was deleted; see below |
| 4.2 | Break-even (four majors, 52.4) | **DONE** — production and discovery scripts now share one constant |
| NEW | Deploy integrity | **DONE 2026-08-20** (`13cc1c3d`) — six CFs were found serving old code behind green builds. Both build paths now assert `latestReady == latestCreated`, deploys retry on CPU quota, and the two MLB configs gained the test gate |
| NEW | `halt-state-writer` deployed | **DONE 2026-08-20** — it has no build trigger and was still running the old always-firing halt logic. Now deployed, verified, and registered in `bin/deploy-function.sh` along with the other three pipeline-state CFs |

**New P0 discovered:** the GCS scheduler backup named as the restore plan's source
of truth was deleted by a 30-day bucket lifecycle rule around 2026-08-02. The 59
jobs have been reconstructed into `ops/scheduler-catalog-2026.yaml` (42 of 59
verified, 3 refused pending input), and snapshots now live in git. **17 jobs need a
human to confirm a body or parameter before their wave is resumed.**

Also corrected: the auto-halt fires on **865 of 865** prediction-days, not 91.9%,
and its threshold margin rests on leak-contaminated prior seasons — on the one
clean season the binding margin is 2.4%, not 28.8%.

---

## 2. P0 — must land before opening night

### 2.1 The auto-halt would publish nothing (BUG, not tuning)

Replaying `ml/signals/regime_context.py`'s exact halt query across 2025-26: the halt fires on
**136 of 148 days (91.9%)**. Peak 7-day average edge all season was **4.41** against a 5.0
threshold; peak edge-5+ rate was **19.5%** against a 50% threshold. Neither bar was cleared once.
The 415-235 (63.8%) season would have produced essentially zero picks.

Cause: the query carries **no `system_id` filter**, so it averages edge over every model's every
prediction (typical edge ≈ 2.5), while the constants were calibrated on best-bets-level edges
(≥3 by construction).

**Second bug in the same code: the un-halt condition is unreachable.** It requires 5.0 avg edge
and 50% edge-5+; all-time maxima are 4.41 and 19.5%. Once fired it never releases — a permanent
zero-pick trap.

**Proposed recalibration** (replayed over 676 healthy in-season days across 5 seasons vs the
48-day collapse window):

| Variant | Condition (7d) | False positives | Collapse coverage | First fire |
|---|---|---|---|---|
| Minimal (constants only) | `avg_edge < 2.0 AND pct_e5 < 6%` | **0 / 676** | 48/48 | 2026-02-21 |
| Recommended (median per player-game) | `edge_med < 1.4 AND pct_e3 < 10%` | **0 / 676** | 45/48 | 2026-02-21 |

Plus hysteresis for release (`edge_med >= 1.6` for 3 days) — yields one clean transition in the
2025-26 replay, no flapping. Median-dedup is preferred: it holds scale as the fleet grows
(2.3 → 16.8 models/player); a max-over-models variant blew up with fleet size and was rejected.

**Caveat to state plainly:** 0-FP rests on 5 seasons of healthy days, but collapse detection is a
single episode (N=1). Thresholds were placed off healthy-day floors with 28-44% margin, not fitted
to the collapse.

**Owner decision required: which variant, and how conservative.**

### 2.2 The scheduler restore (the critical path)

**58 deleted schedulers must be re-created**, and `scripts/nba_offseason_restore_jobs.sh` **still
does not exist**. Verified absent as of 2026-08-19: `weekly-retrain-trigger`, `execute-workflows`,
`decay-detection-daily` — the manifest's own top-3 "wrong verdict hurts most" jobs.

Curated manifest: `docs/02-operations/scheduler-restore-manifest-2026.md` (waves A/B/C, plus a
full script spec at the bottom). Five documented traps: three jobs are `America/Los_Angeles` (do
not normalize); `nbac-player-movement-daily` hardcodes `"year":"2026"`; `master-controller-hourly`
must be paused-then-resumed *paired* with `execute-workflows`; `nba-closing-lines-sweep` is not in
the backup and needs a separate deploy; restoring the three `grading-*` jobs would cause
double-grading races.

**Do not hand-restore.** Write the script, create all jobs paused in September, resume in waves.

### 2.3 Remove the panic-era worker filters

Four UNDER filters in `predictions/worker/worker.py` (`is_actionable`) were **added 3-11 Feb 2026**
during the documented panic week — they were not dormant-then-awakened, they did not exist before.
Each was justified by a days-scale sample (one commit message cites *"Feb 2 went 0/7"*). They sit
upstream of all observability: blocked picks never reach `best_bets_filtered_picks` and never enter
the counterfactual system.

Realized blocked-pool hit rates (deduped, independently reproduced): `role_player_under_low_edge`
52.0% (N=477), `hot_streak_under_risk` 48.8% (N=252), `star_under_bias_suspect` 46.7% (N=90).

- **Delete** `stale_model_under_dampening` (dead code — cannot fire under current defaults; went
  12-6 blocking winners while alive), `role_player_under_low_edge` (its trigger — season avg 8-16,
  edge 3-5, UNDER — is close to an exact negation of the validated best archetype), and
  `hot_streak_under_risk` (directly contradicts `hot_3pt_under`, an *active* positive signal at
  weight 2.5).
- **Move** `star_under_bias_suspect` into the pipeline. It genuinely detected stale-champion star
  underprediction (blocked pool lost at 46.7%), but it needs to be measurable. It already required
  two ad-hoc exemptions — the signature of a proxy fighting the wrong variable (model staleness,
  not star-ness).
- **Structural rule:** no betting-selectivity logic in the worker. Data-quality gates only.
  Selectivity belongs where the counterfactual system can see it.

### 2.4 Deploy gate

20 Cloud Build jobs fired from 4 commits touching 6 files, because nearly every trigger includes
`shared/config/**`. The fan-out is the safe direction of that trade-off and should stay. **The real
gap is that nothing runs tests before deploying** — Cloud Build builds the image and ships it.
Add an import check + `pytest tests/unit/signals -q` as a build step so a broken HEAD fails in
Cloud Build rather than in production. `props-web` already has this model (branch protection + 2
required checks); mirror it on the backend for the Sept 15 - Nov 15 window at minimum.

Also: two builds report `TIMEOUT` on a 600s limit while the Cloud Function deploy completes
server-side seconds later. Always-red builds train you to ignore red. Raise the timeout.

---

## 3. P1 — high value, land before opening night if possible

- **Backfill `filter_counterfactual_daily`** with the corrected dedup. 117 of 333 rows mismatch,
  max ΔHR 37.5pp, and the auto-demote streak logic reads this table.
- **Replace the auto-demote rule.** It has **never fired once** — both entries in
  `filter_overrides` are manual. The 7-consecutive-day requirement makes false-keep 87-100% even
  for a filter whose blocked picks win 65%. Replace with a cumulative Wilson lower-bound rule
  (~20 lines): demote when one-sided 95% Wilson LB of rolling-30-game-day CF HR ≥ 50% at N≥40.
- **Effect assertions.** Every behavioral fix ships with a query proving it took effect, checked
  daily. Seed with `book_count` coverage, health-row presence, tracking drives ≠ 0, CF distinct
  picks, `model_bb_candidates` provenance. See `docs/02-operations/runbooks/morning-canary-set.md`.
- **Purge the observation-filter backlog.** Six observation filters have **zero rows ever** (dead
  code); `signal_stack_2plus_obs` is a coin flip at N=108; `bench_under_obs` (78.6%) and
  `high_skew_over_block_obs` (76.9%) are disproven. `opponent_under_block` looks *wrongly demoted*
  (CF 37.5% = correctly blocking losers) — re-promotion candidate.
- **Health multipliers: decide.** They have never applied in production (the exporter queries
  `signal_health_daily WHERE game_date = @target_date`, but the row for day D is written D+1, so
  the lookup returns empty and `_health_multiplier` fails open to 1.0). Either fix the read to use
  the most recent available row, or delete the mechanism. Do not leave it documented-as-active and
  inert. Note: independent analysis suggests the multipliers may be *anti*-predictive on a
  leak-free lag-1 basis (HOT next-day underperforms) — so fixing the read is not obviously the
  right move; measure first.

---

## 4. Owner decisions (blocking)

| # | Decision | Why it matters |
|---|---|---|
| 1 | **Auto-halt variant + thresholds** | Without it the season publishes nothing |
| 2 | **Where you actually bet** | Sets break-even at 53.5% (one book) / 52.4% (four majors) / 51.5% (ten). Gates model governance, signal promotion, filter demotion, decay alerts. `DEFAULT_BREAKEVEN_HR` is currently 52.4 pending this |
| 3 | **REB/AST backfill go/no-go** | ~37,000 calls, ~14h across both markets. Validated and ready |
| 4 | ~~**Drawdown tolerance**~~ | **DECIDED 2026-08-21: halt at a fixed unit drawdown from peak.** Mechanical, not judgement — the March 2026 alternative was ten algorithm versions shipped during the drawdown. Implement as a `manual`-class reason in `nba_orchestration.halt_state` so it flows through the existing `halt_envelope()` path rather than becoming a second, parallel halt. **Open: the exact unit threshold.** For scale, March 2026 (46.7% HR) cost ~6-7u, so a −8u trigger would not have fired until the month was essentially over; −5u is the more protective end. Requires the §2 halt work first, since `halt_state` does not currently gate picks on its own. |
| 5 | **Backend deploy gate** | Test gate only, or full branch protection? |

---

## 5. The highest-leverage lever is execution, not modeling

Line shopping is worth **+1.8 pp vs the system's current assumption and +3.8 pp vs a single
average book** — larger than every modeling change available, combined. It creates no alpha; it
stops a leak and lowers the bar the existing UNDER edge must clear from 53.5% to 51.5%.

Measured mean payout per book at the consensus number is **0.870**, stable across all five seasons
(0.8803 / 0.8756 / 0.8764 / 0.8754 / 0.8701). Reporting at flat -110 overstated ROI by 3.1-4.5 pp,
worst on high-edge UNDER: UNDER edge 3-5 looked like +0.69% and was actually **-3.68%**; UNDER
edge 6+ looked like -4.94% and was **-9.46%**.

Attainability caveat: "best of ten books" means holding accounts at Fliff, PrizePicks, ESPN Bet and
Hard Rock alongside the majors, and always taking the outlier quote — the one most likely to be
stale and to limit. Read the prize as **+1.8 pp if you genuinely shop wide, 0 if you shop four
majors, -2.1 if you bet one book.**

---

## 6. Research tracks (sequenced, evidence-gated)

### 6.1 Candidate stream as the measurement instrument — VALIDATED, bounded

Accrual **3.6× (conservative Tier-1) to 6.4× (full stream)**. Rank agreement with published picks
(Spearman 0.645) is statistically indistinguishable from a perfect proxy and distinguishable from
independence (p≈0.016); sign agreement 13/15; observed lift disagreement only ~2pp worse than
binomial noise. Promotion backtest: ranking signals by stream HR and pooling their *published*
picks gives 62.9% / 40.4% / 42.9% by tercile. **23 of 54 signals reach stream N≥100 in one
season; at published level almost none reach N=30.**

**Scope limits — enforce these:** UNDER ranking-weight promotion only. **Not** rescue activation
(`low_line_over` runs 48% on the stream and 18% published — the rescue lane re-conditions the
population). **Not** OVER (frozen). **Not** absolute-HR claims.

**The critical caution — the selection offset sign-flips.** Verified: published picks ran 66.9%
(N=118) Jan 9 - Mar 2 and **46.6%** (N=58) Mar 3 - Apr 7, while concurrently *filtered* candidates
ran **51.8%** (N=419). During the collapse the system published worse picks than it blocked. Any
gate assuming a fixed positive offset would have been wrong for a third of the season.

**Gate spec:** stream N≥100 replaces published N≥30; keep the HR bar (no discount) with Wilson
LCB90 ≥ break-even; mandatory Tier-2 veto (published N≥15, veto if published HR <50%); quarterly
BH-FDR batches for anything outside the 6 pre-registered gates; and a **regime brake** — a stream
gate may not close on data spanning <10 calendar weeks, and must clear break-even in both halves
of its window.

**Blocker:** `model_bb_candidates` is **still 33 rows**. The writer fix is code-verified (14/14
tests) but has never run live, and the merge-rejected leg contributes zero unique rows. Add a
season-open canary; do not budget the 6.4× until confirmed.

### 6.2 Execution timing — narrowed to one real rule

At N=4,795 (25× the original sample), most of the original finding was small-N artifact. What
survives, independently reproduced:

**UNDER picks whose multi-book mean line rises ≥1.0 after publish are toxic** — 44.3% (N=97) vs
flat 60.3%, z = -3.2, and -7.5pp after controlling for the weekly regime baseline.

Refuted: OVER against-movers as "poison" (50-53% at N=26-64, not 35.7%); a T-30 cliff (it is a
shallow monotone curve — most value is earned by T-120-T-60); and the direction-split thesis
(UNDER is *not* hurt by waiting: +5.4 → +5.7u/100 unfiltered). Also: **"toward" movers are below
flat too** (UNDER 56.1%, OVER 53.7%) — so the mechanism is **news arrival**, not market
convergence. Correlation between model gap and line movement is only 0.13.

**Config:** sensor = mean line across ≥3 sane books (American odds within [-250, +250]) vs the
13:00-13:30 ET publish snapshot. Checkpoints = keep 16:30 (`phase6-clv-reexport`), **add 18:40 and
21:00 ET**. Rule = UNDER drop at ≥1.0 against; flag at ≥0.5. OVER same thresholds as cheap
insurance only, not booked as edge. Run in shadow ~4 weeks first.

Only 47% of eventual against-moves are visible by 16:30, 75% by 18:40, 99% by 21:00 — so the
current single checkpoint misses about half the signal. But three fixed clock checks capture ~90%
of the value; per-game T-30 vigilance buys another ~0.06pp against 4-6 decision moments a night.
**Honest sizing: +0.5-0.8 pp kept-pick HR ≈ +0.5-1.5u per 100 picks.** Automate, don't staff.

### 6.3 New markets (rebounds + assists) — validated, awaiting go

**Pre-tip discipline PASSES** — the gating question. Max line update was +10.2 min past scheduled
tip (NBA games tip ~9-10 min late), zero in-game, zero post-game contamination. Validated on 5
dates across 5 seasons, 37 API calls.

**But: closing lines only.** One quote per book, no intraday series. So CLV-family signals
(`line_converging_under`, `clv_diverge_under_block`) and the T-3h machinery can **never** be
validated on this archive — they must earn REB/AST stripes live in shadow. What can be validated:
open→close drift, cross-book dispersion (stratified by book count — 4.6 books in 2021-22 vs 13.7
in 2025-26), line-level signals, and everything model/edge-based.

Corrections to earlier estimates: the API caps `limit` at **10, not ~50**, so it is **~12-14h for
both markets** season-sharded, not 40 minutes. The code change is ~15-25 lines in one file
(`backfill_jobs/scrapers/bp_props/bp_props_scraper_backfill.py`); the deployed scraper service, the
scraper class, and the raw processor are all already market-aware.

**Rationale is volume, not edge.** These markets are *noisier* than points normalized to what is
bet (CV: assists 0.64, rebounds 0.53, points 0.48), the vig is identical, and a naive 10-game
average explains as much variance. The prize is **2.4× the UNDER candidate funnel**.

**Gate 2 is pre-registered** (see the REB/AST scoping report) with the essential anti-anomaly
clause: **2025-26 cannot carry it** — at least 2 of the 4 pre-anomaly seasons must independently
clear break-even. That is the lesson from the OVER layer, encoded before any data exists.

---

## 7. Sequence

| Window | Work |
|---|---|
| **Late Aug** | Auto-halt recalibration (bug-fix, freeze-exempt) · worker filter removal · CF daily backfill · deploy test gate · build timeout raise |
| **Early Sept** | Restore script built and tested · auto-demote rule replaced · effect assertions wired · observation-filter purge · REB/AST backfill (if approved) |
| **Mid Sept** | All 58 schedulers created **paused** · centralize the `vegas_mae < 4.5` constant (hardcoded in ≥4 files) with hysteresis · anomaly detectors wired alert-only |
| **Late Sept** | Fleet-diversity candidate trained offline (ridge / sklearn-MLP — measured edge-space decorrelation 0.10-0.55 vs the clone fleet) · props-web merged |
| **October** | Preseason dress rehearsal on real games · resume scheduler waves · verify `weekly-retrain-trigger` exists · verify `model_bb_candidates` writer produces rows · expectations memo |
| **Post-open** | Nothing that changes live pick behavior after 1 Oct except pre-registered runbook items. No floor/halt/gate changes before 1 Dec absent a bug |

---

## 8. Settled — do not reopen

- **Adding model features cannot help.** R² +0.004, three confirmations, plus a ten-analysis sweep
  that produced no counter-evidence.
- **OVER is fragile.** ~39% cross-season at high edge outside the 2025-26 anomaly. The static 6.0
  floor stays; the correct response to an anomaly signal is alarm + forced retrain, not a floor
  change.
- **No-vig probability as a selection signal** — died on de-duplication (HR flat at 53.0/53.4/53.5
  while ROI fell monotonically). **Best-*number* shopping** — collapses at a single decision
  moment; books price half-points fairly.
- **Distributional / variance-adjusted probability** — refuted across 5 seasons and both
  directions; ΔAUC within noise. The calibrator is flat because true edge is 0-30% of stated edge
  against a 6.4-point outcome σ.
- **GBDT fleet diversity via more GBDTs or quantile heads** — refuted. Also: the "fleet diversity
  collapse killed `combo_3way` / `book_disagreement`" narrative is **falsified in-repo**
  (`combo_3way` is single-model; `book_disagreement` is cross-*book*). The real diversity case is
  candidate coverage.
- **Main-market spread/total, steals/blocks, threes, news scraping, alt-market forks, WNBA/NCAA.**
- **MLB stays halted** — five independent no-edge confirmations.
- **Kelly sizing** — flat 1u is near-optimal; Kelly loses on both ROI and drawdown with a noisy
  p_win proxy, and the break-even correction makes it strictly worse (1.3-1.7× oversizing).
- **Do not relax `cap_to_pre_late_season`.**

---

*Companions: `docs/02-operations/runbooks/drawdown-protocol.md` (what you may do when losing),
`docs/02-operations/runbooks/morning-canary-set.md` (is it alive and honest),
`docs/02-operations/scheduler-restore-manifest-2026.md` (the 58 jobs).*
