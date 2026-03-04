# Start Your Next Session Here

**Updated:** 2026-03-04 (Session 400b — Star UNDER Removed + Signal-First UNDER + Model Retrain)
**Status:** Star UNDER filter removed, signal-first UNDER ranking live, 26 active signals, 17 negative filters, 16+ shadow models + 1 production. Algorithm `v400b_star_under_removed`.

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

## What's New (Session 400 + 400b)

1. **Star UNDER filter REMOVED** — Was blocking 2-4 high-edge picks/day. Feb 50% HR was model staleness, not structural (last season Feb = 64.1%). Mar recovered to 72.1%. Cross-season research confirms no seasonal filter needed.
2. **Signal-first UNDER architecture** — UNDER picks ranked by weighted signal quality instead of edge (flat at 52-53%). OVER ranking unchanged.
3. **New model: `catboost_v12_noveg_train0104_0215`** — ALL 6 gates passed. 67.57% HR edge 3+ (n=37), OVER 90.0%, UNDER 59.3%. Enabled in shadow.
4. **signal_health_daily dedup** — DELETE-before-INSERT. Cleaned 989 duplicate rows.
5. **All 4 stale services deployed** — zero drift. First signal rescue live (Jaylen Wells OVER).

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

### Priority 1: Monitor Star UNDER + Volume Recovery
- First night without star_under block — expect +2-4 UNDER picks on star-heavy slates
- Weekly monitor query in handoff doc. Re-evaluate ONLY if <50% on 30+ picks for 2 weeks.
- Check `away_noveg` filter next — blocked 3-6 picks/day, Mar noveg HR is 67.9%

### Priority 2: New Model Promotion
- `catboost_v12_noveg_train0104_0215` needs 2+ days of shadow data
- Promote if live HR >= 60% on edge 3+ graded picks

### Priority 3: Validate Signal Rescue (After 2 Weeks)
- First live rescue happened (Jaylen Wells OVER, edge 3.5)
- Track per-rescue-tag HR when N >= 15. Remove tags < 52.4%.

### Priority 4: Brier-Weighted Model Selection
- Use Brier scores to weight model selection instead of raw HR
- Requires 2+ weeks of data (accumulating since Session 399)

### Priority 5: away_noveg Filter Evaluation
- Blocking 3-6 picks/day. Mar noveg HR = 67.9% (N=81) — strongly recovering.
- If still high after 2 weeks, consider relaxing for newer models.

---

## Key References

- **Session 400/400b handoff:** `docs/09-handoff/2026-03-04-SESSION-400-HANDOFF.md`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **External research:** `docs/08-projects/current/external-research-angles/00-FINDINGS.md`
- **Calendar regime:** `docs/08-projects/current/calendar-regime-analysis/00-FINDINGS.md`
- **Session learnings:** `docs/02-operations/session-learnings.md`
