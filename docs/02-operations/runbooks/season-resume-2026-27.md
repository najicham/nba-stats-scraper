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
- 73 Cloud Scheduler jobs were paused for the off-season; 4 REB/AST data-clock jobs are intentionally ENABLED.

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
- [ ] **Validated cheap signal to consider:** low-line + low-variance UNDER (62% HR, N=819, 4/4 seasons,
      strictly pre-game) — higher-certainty than the deferred non-tree diversity build.
- [ ] **OVER-signal decay watch (2026-06-23 finding):** `line_rising_over` (weight 3.0, rescue) and
      `book_disagree_over` (weight 3.0) are **2025-26-only artifacts** — breakeven in all 4 prior seasons,
      strong only in 2025-26 (`line_rising_over` 2025-26 vs prior Fisher p=0.001; `book_disagree_over` no edge
      any era). Re-grade both by ~Dec 2026; if 2026-27 HR < 58% at N≥30, demote weight. They are prime
      Jan→Mar decay candidates — this is mechanically why OVER collapsed last season. Do NOT delete pre-season.
      `line_drifted_down_under` (UNDER) is the more defensible cross-book signal; keep ACTIVE. Detail:
      `docs/09-handoff/2026-06-23-crossbook-OVER-multiseason-RESULT.md`.

## DON'Ts (carry-forward)
- Don't relax/remove `cap_to_pre_late_season`; don't lower auto-halt thresholds to force picks; don't flip
  cadence or enable HSE 'active' on thin data; don't `--set-env-vars`; don't project the 63.8% BB record
  forward as a stable expectation (real breakeven ≈ 53.5%; edge5+ is the money zone both directions).
