# Runbook: 2026-27 NBA Season Resume — Opening-Night Operating Posture

**Purpose:** Sequence the validated opening-night config so the system resumes producing picks safely after
the off-season halt. The 2025-26 collapse (Jan 73.8% → Mar 46.7%) was diagnosed as **stale models + a
scoring-regime shift**, not an architecture flaw. The fix is operational: **let the edge-based auto-halt gate
output, retrain the fleet on new-season data early, and keep the training anchor in place.** This runbook is
the season-opener checklist for that posture.

**Created:** 2026-06-22 (off-season review). **Owner action window:** ~early-to-mid Oct 2026 (pre-opener) →
through November 2026.

**Context refs:** `memory/offseason-review-corrections-2026-06.md`, `memory/2025-26-anomaly-rootcause.md`,
`memory/staleness-arm-2026-06.md`, `docs/09-handoff/2026-06-23-SESSION-HANDOFF.md`.

---

## State at off-season end (carry-in)
- All 7 NBA models BLOCKED; **edge-based auto-halt ACTIVE** (7d avg edge ~1.45 ≪ 5.0); **0 picks since ~Mar 28**.
- This is CORRECT. Do not force picks. The halt recovers **automatically** once fresh models produce edge.
- ~67 NBA Cloud Scheduler jobs paused for the off-season (verified 2026-06-27: 67 PAUSED / 72 ENABLED);
  the 4 REB/AST data-clock jobs (`nba-{assists,rebounds}-props-{morning,pregame}`) are intentionally ENABLED
  (confirmed). `weekly-retrain-trigger` is among the PAUSED set — its cron is correct (`0 5 * * 1`, year-round);
  it just needs RESUMING pre-opener (forgetting it was the 2025-26 root cause). All MLB betting-path jobs are
  also paused (MLB betting concluded/mothballed 2026-06-26 — leave paused).

## How the two safety mechanisms work (do not disable)
1. **Edge-based auto-halt** (`ml/signals/regime_context.py`, Session 515). Halts ALL best-bets output when
   `7d avg edge < 5.0 AND edge-5+ rate < 50%`. Never fired in normal seasons (2021-2025); fired late Feb 2026.
   It is the primary opening-night guardrail — it suppresses picks until the retrained fleet is genuinely
   confident, then releases automatically. **Leave it on.**
2. **Training anchor caps** (`orchestration/cloud_functions/weekly_retrain/main.py`):
   `cap_to_pre_late_season()` (caps `train_end` at Feb 28 to keep March's compressed edge out of training) +
   `cap_to_last_loose_market_date()` (caps when recent TIGHT days `vegas_mae_7d<4.5` are within 7d), composed
   via `min()`. **Keep both.** The off-season review re-confirmed: do NOT relax `cap_to_pre_late_season` (the
   "cap refuted" finding is non-significant single-season and ignores edge availability).

---

## Pre-opener checklist (~early-to-mid Oct 2026, BEFORE first game)

- [ ] **Add 2026 to `FALLBACK_SEASON_START_DATES`** in `shared/config/nba_season_dates.py` once the 2026-27
      schedule is published. Until then the season-start helper falls to the Oct-22 *default* (safe — never
      blends seasons — but ~1-day imprecise). Verify: `get_season_start_date(2026, use_schedule_service=False)`
      returns the true opener. (Closes the residual of the season-start bug fixed 2026-06-22.)
- [ ] **Resume the paused schedulers.** Confirm the daily pipeline schedulers (phase scrapers, orchestrators,
      monitoring) are ENABLED. `gcloud scheduler jobs list` HANGS in this env — verify per-job:
      `gcloud scheduler jobs describe JOB --location=us-west2 --project=nba-props-platform --format='value(state,schedule)'`.
- [ ] **Verify REB/AST data clock is still ENABLED** (4 jobs: `nba-{assists,rebounds}-props-{morning,pregame}`)
      and that `market_type IN ('assists','rebounds')` rows actually land on the first NBA game days. Keep
      strictly data-only (no model build until a full season + Feb-2027 backtest).
- [ ] **Flip the HSE floor off→observe** on BOTH `prediction-worker` and `prediction-coordinator`:
      `gcloud run services update SERVICE --region=us-west2 --project=nba-props-platform --update-env-vars=HSE_RESCUE_FLOOR_MODE=observe`
      **NEVER `--set-env-vars`** (wipes all env incl. model paths + halt config). 'observe' is non-blocking and
      accrues `hse_rescue_floor` CF rows to `best_bets_filtered_picks`. Flipping pre-opener maximizes the
      data-accrual window toward the N≥30 promotion gate.
- [ ] **Confirm auto-halt is healthy** (not silently failing — recall the Session 516 missing-import bug). Check
      that `regime_context.get_regime_context()` runs without exception and `bb_auto_halt_active` is populated.
- [ ] **Merge any phase6-path fixes staged during the off-season** (auto-halt hardening, signal/filter registry
      reconciliation, rescue-cap behavior) NOW — at season resume, where live filter/halt traffic can validate
      them. Do not merge these during the shutdown window (unvalidatable redeploy).

## ⚠️ OVER is a normal-season liability — UNDER-dominant posture (2026-06-23 finding)
**"edge5+ is the money zone" is OVER-FALSE.** 5-season walk-forward: high-edge OVER has NO cross-season edge —
edge≥6 OVER (the floor-allowed band) hit **38.9% in the prior 4 seasons** (below breakeven in all four), and
only worked in 2025-26 (92.6%) because of that season's scoring-environment anomaly. UNDER edge≥6 is durable
(61% cross-season). **This is the true root of the Jan→Mar collapse: an OVER book reverting to its real ~39%.**
Detail: `docs/09-handoff/2026-06-23-edge-calibration-RESULT.md`.

**2026-27 implication:** if the scoring environment is normal, every edge≥6 OVER pick is expected to LOSE.
- [ ] **Treat OVER as UNPROVEN at season open.** Do NOT assume the 2025-26 OVER performance recurs. Add an
      early-season scoring-environment check (is the league scoring *above* line/model expectation, like
      2025-26? — `league_macro_daily.pred_bias`, `league_avg_ppg_7d` vs prior). Only lean into OVER once that
      anomaly is confirmed present in 2026-27. Otherwise expect OVER ≈ breakeven-or-below and rely on UNDER.
- [ ] **Concentrate EV on UNDER + edge.** UNDER edge≥6 (61% cross-season) is the most reliable lane; UNDER
      edge≥3 (56%+) the durable base. The high OVER floor (6.0) is correct but only throttles volume — it does
      not make OVER profitable.

## Early-season sequence (opening night → ~late Nov 2026)

1. **Expect ZERO or very few picks initially.** The auto-halt holds output until edge recovers; models are
   stale-to-the-new-season and the fleet is BLOCKED. This is the system working as designed.
2. **Retrain the fleet on 2026-27 data as soon as governance N is reachable.** `weekly-retrain` CF fires Mon
   5 AM ET (`orchestration/cloud_functions/weekly_retrain/`). Governance gates (HR≥53% edge3+, N≥15 graded,
   Vegas bias ±1.5, no tier bias >±5) will block models until enough new-season graded data exists — typically
   2-3 weeks in. Manual ad-hoc: `./bin/retrain.sh --all --enable` (use `--no-production-lines`, see CLAUDE.md).
3. **Watch the scoring-regime shift.** The 2025-26 break correlated with `avg_actual` rising ~1K/player between
   seasons and Nov pred_bias −2.23K. Monitor `league_macro_daily` (`league_avg_ppg_7d`, `vegas_mae_7d`,
   `pred_bias`) and `model_performance_daily`. A fresh regime shift is the single most likely repeat failure —
   early retraining on new-season data is the mitigation.
4. **Let the halt release itself.** Once retrained models produce `7d avg edge ≥ 5.0` (and edge-5+ rate ≥50%),
   picks resume automatically. Do NOT lower the halt thresholds to force volume.

## Gated follow-ups (after the season is live and data accrues)

- [ ] **HSE observe→active:** promote ONLY at CF HR ≤ 45%, N ≥ 30 from production shadow (query
      `best_bets_filtered_picks WHERE filter_reason='hse_rescue_floor'`). Same `--update-env-vars` pattern.
- [ ] **Cadence 7d→14d A/B:** edge3+ is HR-equivalent but edge5+ (the money zone) is INCONCLUSIVE (see
      `memory/offseason-review-corrections-2026-06.md`). Run a formal season-start equivalence test (TOST vs a
      2pp margin, more edge5+ N) before changing the `weekly-retrain` cron. If adopted, gate by `isoweek % 2`
      in `main.py`, not day-of-month. Rollback = revert. **Needs user sign-off (experiment ≠ deploy).**
- [ ] **Cross-book OVER multi-season test:** the +13.7pp work left this on the table. `line_movement` /
      `line_std` / `book_count` BettingPros feeds DO have full pre-2025 coverage (only HSE/pace/projection are
      dead pre-2025), so `over_line_rose_heavy` / `book_disagree_over` are genuinely cross-season testable.
- [ ] **PROMOTE `b2b_fatigue_under` shadow→active (2026-06-23 — already wired, validated):** the signal is
      REINSTATED in SHADOW (commit on this branch; registered, tracked, excluded from `real_sc` → zero pick
      impact). 5-season b2b (days_rest=1) UNDER = **63.2%, above breakeven 5/5 seasons**, passes the FORMAL
      discovery gate (BH-FDR adj p=0.0035, block-bootstrap [56.7,70.0], cross-season PASS) — and is WEAKEST in
      2025-26 (54%), so NOT an artifact. It was wrongly disabled (S373) on Feb-2026-only data + the `is_b2b`
      feature (populated only in 2025-26). **To promote:** move `'b2b_fatigue_under'` out of `SHADOW_SIGNALS`
      and add to `UNDER_SIGNAL_WEIGHTS` (~2.0) in `aggregator.py`, once it accrues live N≥30 at HR≥58% in
      2026-27. Needs sign-off.
- [ ] **FLAG `b2b_boost_over` (ACTIVE) for the OVER decay watch:** its "B2B is bullish for OVER, 64.3%" basis
      was 2025-26-era. 5-season b2b OVER = 44/53/47/62/70 (2/5 above breakeven) — another 2025-26 OVER artifact.
      Re-grade in 2026-27; demote if it doesn't clear breakeven at N≥30.
- [ ] **Consider `high_line_under` (star UNDER, line≥25):** even stronger than b2b in the formal gate — 59.9%,
      **5/5 seasons, cv=0.076, BH-FDR p=0.0007**. Check overlap with existing UNDER signals before adding;
      may already be partially captured. Detail: `docs/09-handoff/2026-06-23-broad-research-findings.md`.
- [ ] ~~`rested_under_block`~~ — FAILS the formal gate (p=0.88, noise); dropped. ~~low-line+low-var UNDER
      archetype~~ — does not reproduce (50%). Prefer b2b_fatigue_under + high_line_under above.
- [ ] **OVER-signal RESTORE watch (the 5 fragile OVER signals were PRE-DEMOTED 2026-06-26):** a 5-season
      walk-forward re-grade (independently reproduced; matches the `over_decay_watch.py` baselines) confirmed
      the OVER signal layer is 2025-26-overfit, so the five were moved to `SHADOW_SIGNALS` for season open
      (commit `99941b41`, merged to main — zero weight + excluded from `real_sc`; their `OVER_SIGNAL_WEIGHTS`
      entries are retained as the RESTORE target). The decay-watch's job in 2026-27 therefore FLIPS from
      "demote if they fail" to **"restore only if they EARN it"** — each stays in shadow until it clears ≥58%
      at N≥30 on live 2026-27 data, then (with sign-off) is removed from `SHADOW_SIGNALS`:
      - `fast_pace_over` (now SHADOW) — sub-BE 4/4 prior seasons (N=622), 71.5% 2025-26 only (p<0.001).
      - `cold_3pt_over` (now SHADOW) — sub-BE 4/5 (prior pooled 40%), 74.1% 2025-26 (p=0.007). Worst offender.
      - `line_rising_over` (now SHADOW) — pooled 53.6% (~breakeven); the "96.6%" was one Jan-Feb 2026 window.
      - `book_disagree_over` (now SHADOW) — N=18 total cross-season (UNPROVEN); the "79.6% N=211" does not reproduce.
      - `b2b_boost_over` (now SHADOW) — sub-BE 3/5 (p=0.071); the b2b pair was backwards (favor `b2b_under`).
      This is mechanically why OVER collapsed Jan(80%)→Mar(47%) 2026: overfit signals reverting. UNDER signals
      are healthier — `home_under` durable (56-60% 4/5 yrs); keep ACTIVE. Detail:
      `docs/09-handoff/2026-06-23-signal-trustmap-RESULT.md`, `2026-06-23-crossbook-OVER-multiseason-RESULT.md`,
      `2026-06-26-offseason-priorities.md`.
      **TOOL: run `PYTHONPATH=. python bin/monitoring/over_decay_watch.py` from ~Dec 2026 — it re-grades all
      five (now-shadow) OVER signals + the raw high-edge OVER band on live data (presumed-fragile: each must
      clear ≥58% at N≥30 for a KEEP/restore verdict). Read-only; validated via `--smoke-test`. The RAW high-edge
      band is the high-N early signal — if edge6+ OVER stays near the prior-4-season 38.9%, the shadow demotion
      is vindicated; if it climbs above ≥58% durably, that's the restore trigger.**

## DON'Ts (carry-forward)
- Don't relax/remove `cap_to_pre_late_season`; don't lower auto-halt thresholds to force picks; don't flip
  cadence or enable HSE 'active' on thin data; don't `--set-env-vars`; don't project the 63.8% BB record
  forward as a stable expectation (real breakeven ≈ 53.5%); don't call edge5+ "the money zone" for OVER —
  it's UNDER-only (high-edge OVER is sub-breakeven in normal seasons; see the OVER-liability section above).
