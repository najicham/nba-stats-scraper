# Session 315 Handoff — Directional Concentration Cap Investigation

**Date:** 2026-02-21
**Focus:** Investigated whether a directional concentration cap in the best bets aggregator would have prevented the Feb 2-9 collapse and improved P&L
**Status:** Investigation complete. **No implementation** — backtest showed all cap formulations are net negative or negligible.
**Prior sessions:** 314C (root cause analysis + what-if tool), 314 (investigation), 297 (edge-first architecture)

---

## TL;DR

**A directional concentration cap does not backtest positively in any formulation.** The Feb 2 catastrophe was a black swan event that no mechanical cap can meaningfully prevent. The existing UNDER-specific filters (added Sessions 278-306) already address the structural UNDER weakness.

---

## Investigation Methodology

1. Queried directional concentration history (Jan 1 - Feb 14) at edge 3+ and 5+
2. Tested bidirectional 60% cap, UNDER-only 60/70/75% caps, max 3/5 UNDER per day
3. Broke down OVER vs UNDER HR by edge bucket (3-4, 4-5, 5-6, 6-7, 7+)
4. Checked actual production best bets (`signal_best_bets_picks`) during collapse period
5. All queries against `prediction_accuracy` for `catboost_v9`, Jan 1 - Feb 14

---

## Key Finding: The Asymmetry is OVER vs UNDER

| Concentration Bucket | Days | Picks | HR | P&L |
|---|---|---|---|---|
| 80%+ OVER | 5 | 63 | **85.7%** | **+$4,410** |
| 60-79% OVER | 6 | 28 | 75.0% | +$1,330 |
| 40-59% (balanced) | 6 | 25 | 64.0% | +$610 |
| 60-79% UNDER | 5 | 20 | 60.0% | +$320 |
| 80%+ UNDER | 11 | 57 | **45.6%** | **-$810** |

**OVER concentration is massively profitable. UNDER concentration loses money.** A bidirectional cap would destroy the best-performing bucket.

---

## OVER vs UNDER HR by Edge Bucket

| Edge | OVER HR | OVER P&L | UNDER HR | UNDER P&L |
|---|---|---|---|---|
| 3-3.99 | 53.5% (N=127) | +$310 | 49.3% (N=134) | -$880 |
| 4-4.99 | 58.3% (N=48) | +$600 | 53.4% (N=73) | +$160 |
| **5-5.99** | **72.0% (N=25)** | **+$1,030** | **54.5% (N=33)** | **+$150** |
| 6-6.99 | 66.7% (N=24) | +$720 | 65.4% (N=26) | +$710 |
| 7+ | 84.5% (N=58) | +$3,910 | 40.7% (N=27, blocked) | -$660 |

**UNDER 5-5.99 = 54.5% HR** — barely above breakeven (52.4%). This is where marginal UNDER picks cluster. But raising UNDER MIN_EDGE to 6.0 only saves $150 over the period.

---

## Backtest Results (Edge 5+, After UNDER 7+ Block)

| Approach | N | HR | P&L | vs Baseline |
|---|---|---|---|---|
| **No cap** (baseline) | 166 | 71.1% | +$6,520 | — |
| Bidirectional 60% cap | 131 | 65.6% | +$3,650 | **-$2,870** |
| UNDER-only 60% cap | 149 | 71.1% | +$5,870 | -$650 |
| **Max 5 UNDER/day** | **157** | **72.6%** | **+$6,670** | **+$150** |
| Max 3 UNDER/day | 140 | 74.3% | +$6,440 | -$80 |

**Max 5 UNDER/day** is the only positive variant, but +$150 over 7 weeks is negligible.

### Weekly Breakdown (Max 5 UNDER/day)

| Week | Actual P&L | Capped P&L | Delta |
|---|---|---|---|
| Jan 5 | +$760 | +$770 | +$10 |
| Jan 12 | +$4,780 | +$4,780 | $0 |
| Jan 19 | +$1,460 | +$1,460 | $0 |
| Jan 26 | +$640 | +$540 | -$100 |
| **Feb 2** | **-$980** | **-$740** | **+$240** |
| Feb 9 | -$140 | -$140 | $0 |

Cap only helps on Feb 2 week (+$240) and hurts on Jan 26 (-$100). Net: +$150.

---

## Why the Concentration Cap Fails

1. **Bidirectional cap destroys OVER value**: 80%+ OVER concentration = 85.7% HR. Capping this loses $2,870.

2. **UNDER-only cap removes profitable picks**: After the UNDER 7+ block, remaining UNDER picks (edge 5-6.99) are 70.6% HR. Removing them costs money.

3. **Feb 2 was a black swan**: ALL UNDER edge levels failed simultaneously (5-5.99: 20%, 6-6.99: 0%, 7+: 9.1%). A concentration cap at any threshold only removes a few picks — not enough to prevent the catastrophe.

4. **Best bets pick counts are too small**: The aggregator outputs ~2-5 picks/day after all filters. A percentage-based cap on 3 picks barely makes mathematical sense.

5. **Existing UNDER filters already handle structural issues**:
   - UNDER 7+ block (Session 297): would have saved $990 on Feb 2 alone
   - Bench UNDER block (Session 278)
   - Line jump/drop UNDER blocks (Sessions 294, 306)
   - Neg +/- streak UNDER block (Session 294)

---

## Production Best Bets Were NOT Affected

Query of `signal_best_bets_picks` for Jan 9 - Feb 2 showed the old production system selected **0 UNDER picks**. The old signal-scored algorithm naturally preferred OVER. The Feb 2 UNDER catastrophe only affected raw predictions and subsets, not best bets.

The current edge-first system (v314_consolidated) IS more exposed to UNDER concentration because it ranks by edge regardless of direction. However, the MIN_SIGNAL_COUNT=2 requirement and other filters significantly limit exposure.

---

## What NOT to Do (Confirmed by Data)

- **Don't implement a bidirectional cap** — destroys profitable OVER concentration (-$2,870)
- **Don't implement an UNDER day detector** — market timing, historically AUC < 0.50
- **Don't change retrain cadence** — the collapse was pick construction, not model quality (Session 314C confirmed: stale and fresh models had identical MAE of 4.91)
- **Don't raise UNDER MIN_EDGE to 6.0** — only saves $150 over the period, removes 33 picks at 54.5% HR

---

## Recommendations

1. **Keep existing UNDER filters as-is** — they already catch the structural weakness
2. **Keep validate-daily Phase 0.57 alert** — continues monitoring >80% directional concentration for manual review
3. **Monitor the edge-first system's UNDER exposure** — since v314_consolidated hasn't been through a real UNDER collapse yet, watch for high UNDER concentration in daily picks
4. **Consider UNDER volume monitoring** — track daily UNDER pick count at best bets level. If consistently >5 UNDER/day, investigate

---

## Files Created/Modified

| File | Action | Description |
|---|---|---|
| `docs/09-handoff/2026-02-21-SESSION-315-HANDOFF.md` | CREATE | This handoff |

No code changes. Investigation only.

---

## Queries Used

### Directional concentration history (edge 3+)
```sql
SELECT game_date,
  COUNTIF(recommendation = 'OVER' AND ABS(predicted_points - line_value) >= 3) as over_e3,
  COUNTIF(recommendation = 'UNDER' AND ABS(predicted_points - line_value) >= 3) as under_e3,
  ROUND(100.0 * GREATEST(
    COUNTIF(recommendation = 'OVER' AND ABS(predicted_points - line_value) >= 3),
    COUNTIF(recommendation = 'UNDER' AND ABS(predicted_points - line_value) >= 3)
  ) / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 0) as max_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2026-01-01' AND '2026-02-14'
  AND system_id = 'catboost_v9' AND is_voided = FALSE AND prediction_correct IS NOT NULL
GROUP BY 1
HAVING max_pct > 60
ORDER BY 1;
```

### Concentration bucket analysis (edge 5+)
```sql
WITH daily_picks AS (
  SELECT game_date, recommendation, prediction_correct
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date BETWEEN '2026-01-01' AND '2026-02-14'
    AND system_id = 'catboost_v9' AND is_voided = FALSE AND prediction_correct IS NOT NULL
    AND ABS(predicted_points - line_value) >= 5.0
),
daily_stats AS (
  SELECT game_date,
    ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as under_pct,
    COUNT(*) as total, COUNTIF(prediction_correct) as wins
  FROM daily_picks GROUP BY 1
)
SELECT
  CASE
    WHEN under_pct >= 80 THEN '80%+ UNDER'
    WHEN under_pct >= 60 THEN '60-79% UNDER'
    WHEN under_pct >= 40 THEN '40-59% (balanced)'
    WHEN under_pct >= 20 THEN '60-79% OVER'
    ELSE '80%+ OVER'
  END as bucket,
  COUNT(*) as days, SUM(total) as picks, SUM(wins) as wins,
  ROUND(100.0 * SUM(wins) / SUM(total), 1) as hr
FROM daily_stats GROUP BY 1 ORDER BY 1;
```

---
*Created: Session 315. Prior: Session 314C (root cause + what-if tool).*
