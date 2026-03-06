# Session 422 Handoff — Edge Overconfidence Follow-Through + System Health Audit

**Date:** 2026-03-06
**Type:** Bug fix, registry fix, system audit
**Status:** System healthy — 62.2% HR 14d, market recovering, no urgent action items

---

## What This Session Did

### 1. Exporter Column Fix (Completed)

Session 421 added 5 observation columns (`player_tier`, `tier_edge_cap_delta`, `capped_composite_score`, `compression_ratio`, `compression_scaled_edge`) to the aggregator and BQ schema, but the exporter wasn't wiring them.

**Finding:** Already fixed in commit `c4ec0582` (Session 422b). Verified all 5 columns exist in BQ and the exporter maps them. Updated the schema SQL file for documentation alignment.

### 2. Registry Fix: Low-Vegas Model

`catboost_v9_low_vegas_train0106_0205` was stuck in BLOCKED status from a Mar 1-2 performance dip, but recovered to 75% HR 7d. Updated registry status to `active`.

This is the best UNDER model in the fleet: 88.2% UNDER HR 7d, 68.4% edge 5+ HR 14d.

### 3. System Health Audit (Steering Report)

Full daily steering revealed:

| Metric | Value | Status |
|--------|-------|--------|
| Best Bets HR 7d | 60.0% (15-10) | GREEN |
| Best Bets HR 14d | 62.2% (23-14) | GREEN |
| Market compression | 1.165 | GREEN (expanding) |
| OVER HR 14d | 60.9% (N=23) | GREEN |
| UNDER HR 14d | 64.3% (N=14) | GREEN |
| Residual bias | -0.2 pts | GREEN |
| Models | 15 HEALTHY, 2 WATCH, 1 DEGRADING, 7 BLOCKED | Stable |

### 4. Investigation: False Alarms Resolved

Four potential issues investigated, all resolved:

| Investigation | Finding | Action |
|---------------|---------|--------|
| **v12_q43 42.9% HR** | Join duplication inflated count. Real: 4 picks at 50%, all pre-disable (Feb 24-28). No new picks from March. | None — already disabled |
| **v12_noveg_q57 0% HR** | 1 pick (Kon Knueppel Feb 28). Model already disabled. | None — already disabled |
| **line_dropped_under blocking sharp_line_drop_under** | Different metrics (day-to-day vs intra-day DK). Filter blocked 3 picks, all 0% CF HR — correctly protecting us. | Keep filter as-is |
| **blowout_risk_under 16.7% HR** | Already demoted to BASE_SIGNALS in Session 422b commit `c4ec0582`. Cannot inflate real_sc. | None — already fixed |

### 5. Signal Rescue Analysis

Rescue outperforming normal picks:

| Population | HR | N |
|------------|-----|---|
| Rescued | 63.6% | 11 |
| Normal | 59.3% | 27 |

Top rescue sources: `high_scoring_environment_over` (3-0, 100%), `combo_he_ms` (2-1, 66.7%). `signal_stack_2plus` weak (1-2, 33.3%) — already demoted to obs in Session 415.

**87% of OVER picks on Mar 4-5 are rescued** (14/16). Rescue is carrying the OVER pipeline.

### 6. Combo Signal COLD — Not a Concern

`combo_3way` and `combo_he_ms` went COLD (50% 7d) but that's on N=2 picks. Season HR remains 67.7% / 78.9%. Both fired on 4 picks each on Mar 4-5 (all OVER, all rescued). Temporary noise, not degradation.

---

## Commits

```
e389c7ab docs: add edge overconfidence columns to picks schema
```

## Files Changed

| File | Changes |
|------|---------|
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | Added 5 edge overconfidence observation columns for documentation alignment |

## BQ Changes (Non-Code)

```sql
-- Registry fix (manual)
UPDATE nba_predictions.model_registry
SET status = 'active'
WHERE model_id = 'catboost_v9_low_vegas_train0106_0205'
```

---

## Deployment Status

- All 5 builds from push: **SUCCESS**
- **Drift:** `nba-phase1-scrapers` (stale since Mar 4, scraper fixes only — non-critical) and `pipeline-health-summary` (stale by ~12h, reporter function)
- Model deployment matches GCS manifest

---

## Scheduled Reviews

| Date | Review | Query / Action |
|------|--------|---------------|
| **Mar 7** | Verify observation columns | Check `player_tier`, `compression_ratio` populating in `signal_best_bets_picks` after tonight's run |
| **Mar 12** | Rescue cap (40%) | Compare rescued vs normal HR (7 days of data). Decision: keep 40%, tighten to 30%, or loosen to 50% |
| **Mar 19** | under_star_away counterfactual | Check CF HR in `best_bets_filtered_picks`. If >60% keep in obs, if <50% re-activate block |
| **Mar 20+** | Compression detector | Need RED + GREEN periods observed. If RED edge 5+ HR < 50% at N >= 30 → activate |

### Mar 12 Rescue Cap Query

```sql
SELECT game_date, COUNT(*) as total_picks,
  COUNTIF(signal_rescued) as rescued,
  ROUND(100.0 * COUNTIF(signal_rescued) / COUNT(*), 1) as rescue_pct,
  ROUND(100.0 * COUNTIF(signal_rescued AND p.prediction_correct) /
    NULLIF(COUNTIF(signal_rescued AND p.prediction_correct IS NOT NULL), 0), 1) as rescue_hr,
  ROUND(100.0 * COUNTIF(NOT signal_rescued AND p.prediction_correct) /
    NULLIF(COUNTIF(NOT signal_rescued AND p.prediction_correct IS NOT NULL), 0), 1) as normal_hr
FROM nba_predictions.signal_best_bets_picks b
LEFT JOIN nba_predictions.prediction_accuracy p
  ON b.player_lookup = p.player_lookup AND b.game_date = p.game_date
  AND p.has_prop_line = TRUE AND b.system_id = p.system_id
WHERE b.game_date BETWEEN '2026-03-06' AND '2026-03-12'
GROUP BY 1 ORDER BY 1;
```

### Mar 19 under_star_away Query

```sql
SELECT COUNT(*) as n,
  COUNTIF(prediction_correct) as would_have_won,
  ROUND(100.0 * COUNTIF(prediction_correct) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as cf_hr
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason = 'under_star_away'
  AND game_date BETWEEN '2026-03-06' AND '2026-03-19'
  AND prediction_correct IS NOT NULL;
```

---

## Priority Actions for Next Session

### P1: Verify Observation Columns Populating (Mar 7)
After tonight's pipeline run:
```sql
SELECT player_tier, COUNT(*) as n, compression_ratio
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-06' AND player_tier IS NOT NULL
GROUP BY 1, 3;
```

### P2: Deploy Stale Services (Low Priority)
```bash
./bin/deploy-service.sh nba-phase1-scrapers      # Scraper fixes from earlier sessions
./bin/deploy-service.sh pipeline-health-summary   # Grading bug fix
```

### P3: Monitor v422 Filter Rebalance Effects
- `mean_reversion_under` relaxed thresholds (2.0 → 1.5) — watch for first BB fires
- `bench_under` + `high_spread_over` demoted to obs — monitor whether picks improve
- `over_edge_floor` lowered 5.0 → 3.0 — OVER volume should increase on high-volume slates

### P4: Low-Vegas Retrain (When Needed)
Model is hot (75% HR 7d) but training data is 24 days stale. No urgency unless HR drops below 55% 7d. Command when ready:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_LOW_VEGAS_56D" --feature-set v9 \
    --train-days 56 --category-weight "vegas=0.25" \
    --eval-days 7 --no-upload
```

---

## Key Context for Future Sessions

- **Algorithm version:** `v422_filter_rebalance`
- **Fleet:** 15 HEALTHY, 2 WATCH, 1 DEGRADING, 7 BLOCKED. All q43/q55/q57 quantile models disabled.
- **Market:** Post-ASB recovery, compression GREEN (1.165), edges expanding
- **Rescue dominance:** 87% of OVER picks are rescued. Without rescue, OVER pipeline is nearly empty.
- **Best model:** `catboost_v9_low_vegas` — 75% HR 7d, 88.2% UNDER, 68.4% edge 5+
- **sharp_line_drop_under (87.5% HR):** Signal fires but picks don't survive to BB. Not blocked by `line_dropped_under` filter (different metrics). Picks fail at other filters. May need deeper investigation when N grows.
- **line_dropped_under filter:** Correctly blocking losers (0-3 CF HR). Do not relax.
