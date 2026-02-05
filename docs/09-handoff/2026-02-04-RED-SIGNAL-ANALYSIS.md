# February 4, 2026 - RED Signal Analysis

**Date:** 2026-02-04
**Games:** 7 scheduled
**Signal:** 🔴 EXTREME RED (100% UNDER skew)
**Validation Time:** 8:50 PM ET

---

## Signal Metrics

| Metric | Value | Context |
|--------|-------|---------|
| **Total Predictions** | 99 | CatBoost V9 |
| **Actionable Bets** | 58 | Edge >= threshold |
| **High-Edge Picks** | 17 | Edge >= 5 pts |
| **Medium-Edge Picks** | 41 | Edge 3-5 pts |
| **OVER Picks** | **0** | 0% of directional bets |
| **UNDER Picks** | **55** | 100% of directional bets |
| **pct_over** | **0%** | Historical RED threshold: <25% |

---

## What This Signal Means

### Historical Context

Based on Session 70 findings (23 days analyzed, p=0.0065):

| Signal Type | pct_over Range | Historical Hit Rate | Status |
|-------------|----------------|---------------------|--------|
| 🟢 GREEN (Balanced) | 25-40% | **82%** on high-edge picks | Normal operations |
| 🟡 YELLOW (Skewed) | >40% or <3 picks | Monitor closely | Caution |
| 🔴 RED (UNDER Heavy) | <25% | **54%** on high-edge picks | High risk |

**Tonight's 0% UNDER skew is EXTREME** - worst possible signal category.

### Why This Happens

The 100% UNDER skew is a symptom of the **known CatBoost V9 regression-to-mean bias**:

- **Stars under-predicted by ~9 pts** → Model says UNDER when should say OVER
- **Model predicts closer to mean (~15 pts)** → Biases toward UNDER on high scorers
- **Tonight likely has star-heavy matchups** → All high-edge picks are UNDERs on stars

**Reference:** Sessions 101-104 model bias investigation

---

## Tonight's Top Picks (High-Edge >= 5)

| Rank | Player | Predicted | Line | Margin | Confidence | Rec |
|------|--------|-----------|------|--------|------------|-----|
| 1 | Karl-Anthony Towns | 10.4 | 19.5 | -9.1 | 89% | UNDER |
| 2 | Jalen Brunson | 17.5 | 25.5 | -8.0 | 84% | UNDER |
| 3 | Jamal Murray | 14.7 | 22.5 | -7.8 | 84% | UNDER |
| 4 | Bobby Portis | 11.1 | 18.5 | -7.4 | 92% | UNDER |
| 5 | Sam Merrill | 4.3 | 11.5 | -7.2 | 87% | UNDER |
| 6 | Alperen Sengun | 14.6 | 21.5 | -6.9 | 87% | UNDER |
| 7 | Cedric Coward | 9.0 | 15.5 | -6.5 | 89% | UNDER |
| 8 | AJ Green | 5.1 | 11.5 | -6.4 | 89% | UNDER |
| 9 | Neemias Queta | 4.3 | 10.5 | -6.2 | 89% | UNDER |
| 10 | Chet Holmgren | 10.6 | 16.5 | -5.9 | 87% | UNDER |

**Notable:** All picks are UNDERs, many on players who are stars/starters (KAT, Brunson, Murray, Sengun, Holmgren).

---

## Risk Assessment

### Scenario Analysis

**If model bias is the cause (likely):**
- These picks are based on systematic under-prediction
- Stars will likely score MORE than predicted
- UNDER bets will lose at higher rate than usual
- Expected hit rate: ~54% (vs 82% on balanced days)

**If matchups genuinely favor unders (unlikely at 100% skew):**
- Defensive matchups, pace factors, etc.
- Would still expect SOME over picks mixed in
- 100% UNDER is statistically improbable from genuine analysis

**Most likely explanation:** Model bias + star-heavy slate = all UNDERs flagged as high-edge

---

## Recommended Strategy

### Option 1: Conservative (Recommended)

**Reduce exposure significantly:**
- **Bet sizing:** 25% of normal unit size
- **Selection:** Only top 5 high-edge picks (edge >= 7)
- **Skip:** All medium-edge picks (edge 3-5)
- **Monitor:** First 2-3 games before betting later slate

**Rationale:** Historical 54% hit rate on RED signals barely breaks even after vig (52.4% needed). At 25% sizing, losses are limited if signal proves accurate.

### Option 2: Moderate

**Selective participation:**
- **Bet sizing:** 50% of normal
- **Selection:** All 17 high-edge picks (edge >= 5)
- **Skip:** Medium-edge picks
- **Focus:** Bench/role player UNDERs (less affected by star bias)

**Rationale:** High-edge picks historically 79% hit rate overall. Even with RED signal penalty (54%), portfolio might perform.

### Option 3: Aggressive (Not Recommended)

**Normal operations:**
- **Bet sizing:** 100%
- **Selection:** All 58 actionable picks

**Rationale:** Trust that model has genuinely identified UNDER-heavy slate. **Risk:** If model bias is the cause, significant losses likely.

### Option 4: Skip Entirely

**No bets tonight:**
- **Rationale:** 100% UNDER skew is unprecedented signal
- Wait for model bias fix before trusting extreme signals
- Use tonight as validation data for model improvement

---

## Data to Collect Tonight

**For model improvement investigation:**

1. **Track actual outcomes** of all 17 high-edge UNDER picks
2. **Compare to Vegas closing lines** - did sportsbooks also favor unders?
3. **Check player tier distribution** - what % were stars vs role players?
4. **Analyze misses** - which picks failed and why?

**Validation queries for tomorrow:**

```sql
-- Tonight's high-edge performance
SELECT
  game_date,
  COUNT(*) as high_edge_picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date = '2026-02-04'
  AND ABS(predicted_points - line_value) >= 5
  AND recommendation IN ('OVER', 'UNDER');

-- Compare to player tier
SELECT
  CASE
    WHEN actual_points >= 25 THEN 'Stars'
    WHEN actual_points >= 15 THEN 'Starters'
    ELSE 'Role/Bench'
  END as tier,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date = '2026-02-04'
  AND ABS(predicted_points - line_value) >= 5
GROUP BY 1;
```

---

## Historical Precedent

**Recent RED/UNDER_HEAVY days:**

| Date | pct_over | High-Edge Picks | Hit Rate | Notes |
|------|----------|-----------------|----------|-------|
| Feb 1 | 10.6% | 4 | 54% | Session 70 example |
| Feb 2 | ~20% | 7 | 0% | All failed (model bias) |
| Feb 3 | ~25% | 8 | TBD | Borderline RED |
| **Feb 4** | **0%** | **17** | **TBD** | Unprecedented |

**Feb 2 precedent is concerning:** 0/7 on high-edge picks suggests model bias, not genuine signal.

---

## Long-Term Actions

### Immediate (After Tonight)
1. Validate hit rate on Feb 4 picks
2. Analyze tier distribution of picks
3. Document findings in model bias investigation

### Short-Term (This Week)
1. Fix DNP pollution in Phase 4 cache (may affect features)
2. Complete Session 104 recommended investigation (feature importance, variance analysis)
3. Consider implementing recalibration (Option A from Session 102)

### Medium-Term (Next Sprint)
1. Retrain V10 with debiasing features or quantile regression
2. Add automated alerts for extreme signals (pct_over <10% or >90%)
3. Build validation framework for testing signal reliability

---

## Decision Framework

**Questions to ask:**

1. **Do you trust the model?** If yes → Option 2 (Moderate). If no → Option 4 (Skip).
2. **What's your risk tolerance?** High → Option 2. Low → Option 1 or 4.
3. **Is this a learning opportunity?** Yes → Option 1 (small bets to validate signal)
4. **Has model bias been fixed?** No → Lean toward conservative approach.

**Our assessment:** Model bias has NOT been fixed. Recommend **Option 1 (Conservative)** or **Option 4 (Skip)**.

---

## References

- **Signal Discovery:** Session 70 (23-day analysis, p=0.0065)
- **Model Bias Investigation:** Sessions 101-104
- **Signal Table:** `nba_predictions.daily_prediction_signals`
- **Validation Queries:** `.claude/skills/validate-daily/SKILL.md`

---

**Prepared by:** Claude Sonnet 4.5
**Session:** Daily Validation 2026-02-04
**Status:** ⚠️ CAUTION - Extreme signal warrants conservative approach
