# Start Your Next Session Here

**Updated:** 2026-03-04 (Session 399 Follow-up — Brier Backfill + V19 Experiment)
**Status:** Signal rescue + sharp book lean live, 26 active signals, 17 negative filters, 15 shadow models + 1 production. Algorithm `v399_skew_filter`.

---

## Quick Start

```bash
# 1. Morning steering report
/daily-steering

# 2. Check pipeline health
/validate-daily

# 3. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 4. Review best bets config
/best-bets-config
```

---

## What's New (Session 399 + Follow-up)

1. **`high_skew_over_block` filter (17th negative filter)** — OVER + mean_median_gap > 2.0 = 49.1% HR. Blocks right-skewed scoring distributions that inflate OVER mean predictions.
2. **Sharp book lean signals** — `sharp_book_lean_over` (70.3% HR, N=508) + `sharp_book_lean_under` (84.7% HR, N=202). FanDuel/DraftKings vs BetRivers/Bovada/Fliff line divergence.
3. **Brier score calibration** — `model_performance_daily` now has `brier_score_7d/14d/30d`. 351 rows backfilled via BQ MERGE. Best calibrated: v13_vw025 (0.217), v12_noveg_q55_tw (0.225).
4. **V19 scoring skewness experiment — DEAD END** — Feature <2% importance, CatBoost ignores it (same iter/loss as V12_NOVEG). 63.16% HR, below 66% target. Works better as filter only.
5. **Friday OVER block** (Session 398) — 37.5% HR best bets, 53.0% raw.
6. **BQ query fix** — V19 augmentation correlated subquery rewritten to self-join + APPROX_QUANTILES.

**Full details:** `docs/09-handoff/2026-03-04-SESSION-398-HANDOFF.md`

---

## Tomorrow: Validate Session 399 Deployment

After today's predictions run (~6 AM ET tomorrow), check:

```sql
-- 1. Verify new filter fires
SELECT game_date, algorithm_version,
  JSON_VALUE(rejected_json, '$.high_skew_over_block') as skew_blocked
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-04'

-- 2. Verify sharp book lean signals fire
SELECT signal_tags, real_signal_count, recommendation, player_lookup
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-04'
  AND ('sharp_book_lean_over' IN UNNEST(signal_tags)
    OR 'sharp_book_lean_under' IN UNNEST(signal_tags))

-- 3. Verify sharp book lean rescues
SELECT player_lookup, recommendation, edge, rescue_signal, signal_rescued
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-04'
  AND signal_rescued = TRUE AND rescue_signal LIKE 'sharp_book%'

-- 4. Check algorithm version is v399
SELECT DISTINCT algorithm_version
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-04'
```

---

## Immediate Priority: Validate Signal Rescue Performance

Signal rescue went live Mar 4. After ~14 days of live data, validate:

```sql
SELECT bb.rescue_signal, bb.recommendation,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.signal_best_bets_picks bb
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
WHERE bb.signal_rescued = TRUE
  AND bb.game_date >= '2026-03-04'
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1, 2
ORDER BY hr DESC
```

**Action thresholds:**
- Any rescue tag < 52.4% on 15+ picks → remove from `RESCUE_TAGS` in `aggregator.py`
- Overall rescued pick HR < 55% on 30+ picks → tighten rescue criteria

---

## Current State

### Fleet (15 shadow + 1 production)

| Model | Framework | HR 3+ | Status |
|-------|-----------|-------|--------|
| `catboost_v12` (production) | CatBoost | 48.7% Feb | Interim champion, degrading |
| `v9_low_vegas_train0106_0205` | CatBoost | 51.9% 7d | Best current model |
| `v16_noveg_train1201_0215` | CatBoost | 70.83% backtest | Shadow |
| `xgb_v12_noveg_s42_train1215_0208` | XGBoost | 71.7% backtest | Shadow |
| `xgb_v12_noveg_s999_train1215_0208` | XGBoost | 69.6% backtest | Shadow |
| `lgbm_v12_noveg_vw015_train1215_0208` | LightGBM | 66.7% backtest | Shadow |
| + 10 more CatBoost/LightGBM shadows | | | |

### Brier Score Calibration (Latest)

| Model | Brier 30d | Calibration |
|-------|-----------|-------------|
| v13_vw025 | 0.217 | Well-calibrated |
| v12_noveg_q55_tw | 0.225 | Well-calibrated |
| v15_noveg_vw025 | 0.229 | Well-calibrated |
| v12_q43 | 0.247 | Decent |
| v9 (production) | 0.287 | Decent |
| catboost_v12_noveg_train0108 | 0.516 | Poor |

### Signal System (26 active, 24 removed)

**Best Bets pipeline:** `edge 3+ (or signal rescue) → negative filters → signal count >= 3 → real_sc gate → rank by edge`

### Known Issues

- 4 monitoring CFs stale (daily-health-check, pipeline-health-summary, validation-runner, nba-phase1-scrapers) — non-critical
- `signal_health_daily` has duplicate rows from multiple backfills (functional, cosmetic issue)
- PBP backfill deferred (59 dates of NBA.com PBP in GCS, not in BQ)
- All production models degrading — shadow fleet is rebuilding

---

## Strategic Priorities

### Priority 1: Validate Signal Rescue + New Signals (After 2 Weeks)
- Check per-rescue-tag HR (especially `sharp_book_lean_over`/`under`)
- Check `high_skew_over_block` filter rejection rate
- Remove underperforming rescue tags if < 52.4% on 15+ picks

### Priority 2: Brier-Weighted Model Selection
- Use Brier scores to weight model selection instead of raw HR
- Requires 2 weeks of Brier data (accumulating now)
- Walsh 2024 reference: +34.69% ROI improvement

### Priority 3: Signal Combo Expansion
- `sharp_book_lean_over` + `high_scoring_environment_over` potential SYNERGISTIC combo
- Need N>=20 overlap before registering

### Priority 4: Model Retraining
- Production model is stale (27+ days)
- Use 56-day training window (validated sweet spot)
- Vegas weight 0.15x (cross-session validated)

### Priority 5: Signal-First UNDER Architecture
UNDER edge is flat at 52-53% — edge doesn't discriminate UNDER quality. Signals are the only differentiator.

---

## Key References

- **Session 399 handoff:** `docs/09-handoff/2026-03-04-SESSION-398-HANDOFF.md` (covers 398+399)
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **External research:** `docs/08-projects/current/external-research-angles/00-FINDINGS.md`
- **Calendar regime:** `docs/08-projects/current/calendar-regime-analysis/00-FINDINGS.md`
- **Session learnings:** `docs/02-operations/session-learnings.md`
