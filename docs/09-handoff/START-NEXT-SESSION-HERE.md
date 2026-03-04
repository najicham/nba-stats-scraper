# Start Your Next Session Here

**Updated:** 2026-03-04 (Session 400 — Signal-First UNDER + Dedup + Model Retrain)
**Status:** Signal-first UNDER ranking live, 26 active signals, 18 negative filters, 16+ shadow models + 1 production. Algorithm `v400_signal_first_under`.

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

## What's New (Session 400)

1. **Signal-first UNDER architecture** — UNDER edge is flat at 52-53% across ALL buckets (useless for ranking). UNDER picks now ranked by weighted signal quality score: `sharp_book_lean_under` (3.0), `book_disagreement` (2.5), `bench_under` (2.0), `home_under` (1.5), `extended_rest_under` (1.5), `starter_under` (1.0). Edge is 0.1x tiebreaker. OVER unchanged.
2. **signal_health_daily dedup** — `write_health_rows()` now DELETE-before-INSERT. Cleaned 989 duplicate rows (1,616 → 627 unique).
3. **New model: `catboost_v12_noveg_train0104_0215`** — ALL 6 governance gates passed. 67.57% HR edge 3+ (n=37), OVER 90.0%, UNDER 59.3%, MAE 5.20, vegas bias -0.45. Enabled in shadow fleet.
4. **Signal rescue validation** — Zero production data (no picks below edge 3.0 in recent days = no candidates). Code works correctly (simulation showed 13 rescues). Follow up in ~2 weeks.
5. **All 4 stale services deployed** — daily-health-check, validation-runner, pipeline-health-summary, nba-phase1-scrapers.

---

## Tomorrow: Validate Session 400 Deployment

After today's predictions run (~6 AM ET tomorrow), check:

```sql
-- 1. Verify algorithm version is v400
SELECT DISTINCT algorithm_version
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-05'

-- 2. Check UNDER composite scores use signal quality (not edge)
-- UNDER scores should be ~1-10 scale, OVER scores should be ~3-8 edge scale
SELECT player_lookup, recommendation, composite_score, signal_count, real_signal_count, edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-05'
ORDER BY recommendation, composite_score DESC

-- 3. Verify signal_health_daily has no duplicates
SELECT game_date, signal_tag, COUNT(*) as cnt
FROM nba_predictions.signal_health_daily
WHERE game_date >= '2026-03-04'
GROUP BY 1, 2
HAVING COUNT(*) > 1

-- 4. Verify new model is producing predictions
SELECT system_id, COUNT(*) as pred_count
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-03-05'
  AND system_id = 'catboost_v12_noveg_train0104_0215'
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

### Fleet (16+ shadow + 1 production)

| Model | Framework | HR 3+ | Status |
|-------|-----------|-------|--------|
| `catboost_v12` (production) | CatBoost | 48.7% Feb | Interim champion, degrading |
| `catboost_v12_noveg_train0104_0215` | CatBoost | **67.57% backtest** | **NEW — shadow (Session 400)** |
| `v9_low_vegas_train0106_0205` | CatBoost | 51.9% 7d | Best live model |
| `v16_noveg_train1201_0215` | CatBoost | 70.83% backtest | Shadow |
| `xgb_v12_noveg_s42_train1215_0208` | XGBoost | 71.7% backtest | Shadow |
| `xgb_v12_noveg_s999_train1215_0208` | XGBoost | 69.6% backtest | Shadow |
| `lgbm_v12_noveg_vw015_train1215_0208` | LightGBM | 66.7% backtest | Shadow |
| + 9 more CatBoost/LightGBM shadows | | | |

### Signal System (26 active, 24 removed)

**Best Bets pipeline:** `edge 3+ (or signal rescue) → negative filters → signal count >= 3 → real_sc gate → OVER: rank by edge, UNDER: rank by signal quality`

### Known Issues

- PBP backfill deferred (59 dates of NBA.com PBP in GCS, not in BQ)
- All production models degrading — shadow fleet is rebuilding
- Signal rescue has 0 live data — no rescue candidates yet

---

## Strategic Priorities

### Priority 1: Monitor New Model + UNDER Architecture
- Check `catboost_v12_noveg_train0104_0215` live HR after 2 days → promote if confirms backtest
- Compare UNDER pick quality before/after signal-first ranking
- Promote to production: `UPDATE nba_predictions.model_registry SET is_production=TRUE, status='production' WHERE model_id='catboost_v12_noveg_train0104_0215'`

### Priority 2: Validate Signal Rescue (After 2 Weeks)
- Check per-rescue-tag HR (especially `sharp_book_lean_over`/`under`)
- Remove underperforming rescue tags if < 52.4% on 15+ picks

### Priority 3: Brier-Weighted Model Selection
- Use Brier scores to weight model selection instead of raw HR
- Requires 2+ weeks of Brier data (accumulating since Session 399)

### Priority 4: Signal Combo Expansion
- `sharp_book_lean_over` + `high_scoring_environment_over` potential SYNERGISTIC combo
- Need N>=20 overlap before registering

---

## Key References

- **Session 400 handoff:** `docs/09-handoff/2026-03-04-SESSION-400-HANDOFF.md`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **External research:** `docs/08-projects/current/external-research-angles/00-FINDINGS.md`
- **Calendar regime:** `docs/08-projects/current/calendar-regime-analysis/00-FINDINGS.md`
- **Session learnings:** `docs/02-operations/session-learnings.md`
