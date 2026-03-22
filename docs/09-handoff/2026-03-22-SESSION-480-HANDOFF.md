# Session 480 Handoff — Morning Check, System Healthy

**Date:** 2026-03-22
**Previous:** Session 479 (canary fixes, MLB schedule populated, scheduler fixed)

---

## TL;DR

Morning diagnostic only — no code changes. Both enabled LGBM models are now HEALTHY with real graded data (resolved overnight from yesterday's INSUFFICIENT_DATA). Signal system is the hottest it's been in weeks (25 HOT signals). Recent picks 3-0. MLB schedule data in BQ through Apr 3. System is in good shape heading into the end-of-season push.

---

## Current System State (as of 2026-03-22 morning)

### Fleet (model_performance_daily as of 2026-03-21)

| Model | State | HR 7d | N 7d | OVER 7d | UNDER 7d | Notes |
|-------|-------|-------|------|---------|---------|-------|
| `lgbm_v12_noveg_train0103_0227` | HEALTHY | 60.0% | 20 | 66.7% (N=6) | 57.1% (N=14) | Feb 27 training end |
| `lgbm_v12_noveg_train1215_0214` | HEALTHY | 60.0% | 15 | 80.0% (N=5) | 50.0% (N=10) | Just enabled Mar 21, first pick hit |
| `catboost_v9_low_vegas_*0205` | DEGRADING | 53.5% | 43 | — | — | **Not enabled** — new DEGRADING state |
| `lgbm_v12_noveg_vw015_*0208` | BLOCKED | 52.4% | 42 | — | — | **Not enabled** — decay-blocked |

**No action needed on non-enabled models.** Decay detection auto-handles DEGRADING→BLOCKED transition.

### Best Bets Performance

| Period | W-L | HR |
|--------|-----|----|
| Last 7d | 3-0 | 100% |
| Last 14d | 9-4 | 69.2% |
| Last 30d | 36-35 | 50.7% |

30d distorted by Mar 8 crash (3-11, 21.4%). Excluding Mar 8: recent run is clean.

### Signal Health (2026-03-21)

- **25 HOT** / 21 NORMAL / 4 COLD (none model-dependent → no zeroing active)
- COLD: `sharp_line_drop_under` (33%), `ft_rate_bench_over` (0%), `positive_clv_over` (0%), `sharp_line_move_over` (50%)
- **Standouts:** `projection_consensus_over` 90% (N=10), `usage_surge_over` 100% (N=5), `consistent_scorer_over` 100% (N=2), `high_scoring_environment_over` 100% (N=2), `bench_under` 100% (N=4)
- **Watch:** `downtrend_under` WATCH state (33.3% 7d), `star_favorite_under` chronically poor (31.6% 30d)

### League Macro (2026-03-21)

| Metric | Value | Status |
|--------|-------|--------|
| Vegas MAE 7d | 5.43 | NORMAL |
| Model MAE 7d | 6.17 | — |
| MAE gap 7d | +0.74 | WARNING (>0.5) — improving from 0.97 |
| Avg edge 7d | 4.14 | Low |
| Market regime | NORMAL | |

MAE gap improving day-over-day (0.97 → 0.97 → 0.74). Cannot retrain until Vegas MAE gate clears (gate: 5.0, current: 5.43 — need to drop below 5.0 before retraining becomes allowed).

---

## MLB Status

| Item | Status |
|------|--------|
| `mlb_raw.mlb_schedule` 2026 data | ✅ Mar 27 - Apr 3 populated (8 dates, 101 total games) |
| `mlb-schedule-daily` scheduler | ✅ Fixed (now posts to `/scrape` endpoint correctly) |
| `mlb-predictions-generate` | ENABLED, no month restriction — will fire daily at 1 PM ET |
| MLB prediction worker | ✅ Ready/healthy |
| `mlb-resume-reminder-mar24` | ENABLED, fires Mar 24 8 AM ET |

---

## Open Items / Next Session

### Must Do Before March 27 (MLB Opening Day — 5 days away)
1. **Mar 24 — follow up on `mlb-resume-reminder-mar24` Slack alert**: Execute `./bin/mlb-season-resume.sh`. Verify pitcher props scrapers (`mlb-pitcher-props-validator-4hourly` etc.) are operational.
2. **Mar 27 AM — check MLB predictions**: Verify `mlb-predictions-generate` fired and `mlb_predictions.pitcher_strikeout_predictions` has rows for 2026-03-27.
3. **MLB pitcher props coverage**: `mlb-pitcher-props-validator-4hourly` is restricted Apr-Oct. Opening Day prop lines may need manual trigger on Mar 27.

### NBA Monitoring This Week
- **lgbm_1215 decision point (Mar 25)**: `lgbm_v12_noveg_train1215_0214` has N=15 graded. Deactivate if HR drops below 52.4% by Mar 25.
- **MAE gap**: Watching it normalize. At 0.74 today; should reach <0.5 as end-of-season games accumulate.
- **Weekly-retrain CF**: Keep paused (Vegas MAE gate 5.0).
- **OVER floor**: Keep at 5.0. Do NOT lower.
- **Mar 25**: 12 NBA games — biggest volume day of the week, good pick opportunity.

### Known Constraints
- Do NOT resume `weekly-retrain` CF
- Do NOT re-enable `catboost_v9_low_vegas` (now DEGRADING, heading to BLOCKED)
- Do NOT lower OVER floor to 4.5

---

## No Code Changes This Session

Session was morning diagnostic only. All commits are from Session 479.

Latest commit: `83c722c1` — docs: Session 479 handoff

---

## Quick Reference — Current Enabled Fleet

```bash
bq query --use_legacy_sql=false "
SELECT model_id, enabled, status, training_end_date
FROM nba_predictions.model_registry
WHERE enabled = TRUE
ORDER BY training_end_date DESC"
```

Both models: `lgbm_v12_noveg` family, training ends Feb 14 and Feb 27. Both HEALTHY.
