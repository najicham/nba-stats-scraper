# Multi-Season Training Data Audit

**Date:** 2026-02-12
**Sessions:** 224 (planning)
**Status:** Audit complete
**Related:** `02-MASTER-EXPERIMENT-PLAN.md`, `03-NEW-FEATURES-DEEP-DIVE.md`

---

## Executive Summary

We're using **11% of available training data** (8.4K of 38K trainable rows). This audit confirms multi-season training is feasible but with important caveats about data quality by season.

**Bottom line:** Train on 2+ seasons starting from **December** (not November), use recency weighting, and be aware of the Vegas coverage cliff in the current season.

---

## 1. Training Data Inventory

### Feature Store (`ml_feature_store_v2`)

| Season | Months | Total Rows | Clean Rows | Clean % | Trainable* |
|--------|--------|-----------|------------|---------|-----------|
| 2023-24 | Nov 2023 - Jun 2024 | 25,948 | ~15,500 | 54-70% | **13,671** |
| 2024-25 | Nov 2024 - Jun 2025 | 25,846 | ~16,200 | 61-76% | **13,193** |
| 2025-26 | Nov 2025 - Feb 2026 | 25,749 | ~15,200 | 27-74% | **11,287** |
| **TOTAL** | — | **77,543** | **~46,900** | — | **38,151** |

*Trainable = clean rows (zero required defaults) WITH matching actuals AND minutes > 0.

### Schema Consistency

**Feature count:** Exactly 37 features per row across ALL months and ALL seasons. No schema drift. No missing-feature rows.

### Actuals Join Rate (`player_game_summary`)

| Season | Feature Rows | Join % | Notes |
|--------|-------------|--------|-------|
| 2023-24 | 25,948 | **100%** | Perfect join |
| 2024-25 | 25,846 | **100%** | Perfect join |
| 2025-26 | 25,749 | **59-64%** | 40% unmatched (pre-game rows without post-game stats) |

The 2025-26 join gap is because the feature store now generates rows for more players (including many who DNP). The training data loader's quality gates (`points IS NOT NULL AND minutes_played > 0`) automatically filter these out.

---

## 2. Quality by Month — Critical Findings

### Clean Data Percentage by Month (All Seasons)

```
2023-11: ████████░░░░░░░░░░░░ 21.5%  ← Season start, bad
2023-12: ██████████████████░░ 54.5%
2024-01: ██████████████████░░ 57.0%
2024-02: ██████████████████░░ 53.8%
2024-03: ███████████████████░ 58.8%
2024-04: ████████████████████ 63.0%
2024-05: ██████████████████████ 70.8%  ← Playoffs, best quality
2024-06: ██████████████████░░ 56.1%

2024-11: ████████████░░░░░░░░ 27.9%  ← Season start, bad
2024-12: ████████████████████ 61.7%
2025-01: ████████████████████ 62.3%
2025-02: ████████████████████ 61.1%
2025-03: ████████████████████ 64.3%
2025-04: ██████████████████████ 72.8%
2025-05: ██████████████████████ 72.3%
2025-06: ████████████████████████ 76.1%

2025-11: ███████████░░░░░░░░░ 26.7%  ← Season start, bad
2025-12: ██████████████████████ 69.3%
2026-01: ██████████████████████ 73.9%  ← Current season peak
2026-02: ██████████████████████ 69.6%
```

### Key Pattern: November Is Always Bad

| Season | November Clean % | December Clean % | Improvement |
|--------|-----------------|-----------------|-------------|
| 2023-24 | 21.5% | 54.5% | +33pp |
| 2024-25 | 27.9% | 61.7% | +34pp |
| 2025-26 | 26.7% | 69.3% | +43pp |

**Root cause:** Early-season players lack sufficient game history for rolling averages (last 5/10 games spans into previous season or doesn't exist for rookies). Opponent defense ratings take ~15 games to stabilize.

**Recommendation:** **Start training from December 1st of each season**, not October/November. The November data quality penalty (~25% clean) significantly dilutes training quality.

---

## 3. Vegas Line Coverage — The 2025-26 Cliff

### Coverage by Season (Feature 25: `vegas_points_line`)

| Season Period | Vegas Coverage | Avg Non-Zero Line |
|---------------|---------------|-------------------|
| 2023-24 | **59-75%** | 8.4-9.5 |
| 2024-25 | **64-83%** | 8.6-9.5 |
| 2025-26 | **31-47%** | 4.3-6.0 |

**The 2025-26 season shows a dramatic drop in Vegas coverage:**
- Only 31% coverage in November 2025 vs 60% in November 2023
- Even at best (February 2026), only 47% vs 73% in February 2025
- Average line values are ~half of prior seasons (4-6 vs 8-10)

**Possible causes:**
1. Feature store now includes more bench/marginal players who never have prop lines
2. Odds API coverage may have changed
3. The lower average is skewed by more zero-value rows

**Impact on training:**
- Vegas features (25-28) account for **50%+ of model importance**
- Training on 2025-26 data means ~55% of rows have no Vegas signal
- The model learned from 60-75% Vegas coverage but now sees 43% in production
- **Multi-season training mitigates this** — older seasons have better coverage

**Recommendation:** When training multi-season, the higher Vegas coverage in 2023-24 and 2024-25 will provide more complete training signal. Recency weighting ensures current-season patterns still dominate decision-making.

---

## 4. Feature 33-36 (V10 Features) Quality Audit

### Coverage by Month

| Feature | 2023-24 | 2024-25 | 2025-26 | Notes |
|---------|---------|---------|---------|-------|
| f33: `dnp_rate` | 100% | 100% | 97-100% | Fully populated |
| f34: `pts_slope_10g` | 100% | 100% | 97-100% | Fully populated |
| f35: `pts_vs_season_zscore` | 100% | 100% | 97-100% | Fully populated |
| f36: `breakout_flag` | 100% | 100% | 97-100% | Fully populated |

**These features are safe to activate.** The 97% in early 2025-26 months corresponds to the same rows missing opponent defense data — not a separate issue.

---

## 5. Key Feature Coverage Across Seasons

### Critical Features (Non-Vegas)

| Feature | 2023-24 | 2024-25 | 2025-26 |
|---------|---------|---------|---------|
| f0: `points_avg_last_5` | 92-99% | 92-99% | **83-87%** |
| f13: `opponent_def_rating` | **37%** (Nov) → 100% | **45%** (Nov) → 100% | **46%** (Nov) → 97% |
| f1: `points_avg_last_10` | 92-99% | 92-99% | 83-87% |
| f31: `minutes_avg_last_10` | 92-99% | 92-99% | 83-87% |

**Opponent defense rating** is the biggest quality gatekeeper:
- Always bad in November (~37-46%) — requires ~15 games to compute
- Jumps to 100% by December in historical seasons
- Slightly lower (96-97%) in current season December-February

**Points averages** also show a quality dip in 2025-26 (83-87% vs 92-99%). This aligns with the larger player pool in the feature store generating more rows with incomplete histories.

---

## 6. Model Accuracy Over Time

| Month | Total Graded | Edge 3+ Picks | Edge 3+ HR | Edge 5+ Picks | Edge 5+ HR |
|-------|-------------|---------------|-----------|---------------|-----------|
| **2026-01** | 2,417 | 392 | **64.8%** | 140 | **79.3%** |
| **2026-02** | 1,137 | 192 | **38.0%** | 59 | **30.5%** |

Only 2 months of graded data exist for `catboost_v9`. The decay is severe and accelerating:
- Edge 3+ dropped 26.8pp in one month
- Edge 5+ (our best filter) collapsed from 79.3% to 30.5%
- The champion model was trained through Jan 8 — by Feb 12 it's 35 days stale

**No historical prediction data from prior seasons** (V9 wasn't deployed then). We cannot analyze seasonal accuracy patterns.

---

## 7. Scoring Environment by Season

### Monthly Average Points Per Player

| Month | 2023-24 | 2024-25 | 2025-26 |
|-------|---------|---------|---------|
| January | 10.76 | 10.55 | 10.54 |
| February | 10.71 | 10.90 | 10.65* |
| March | 10.53 | 10.92 | — |

*Partial month (Feb 1-12)

**February is NOT an anomaly.** Scoring environment is remarkably stable across years (10.5-10.9). The model's struggles are not caused by a structural scoring shift — they're caused by model staleness and UNDER bias.

**February 2026 has slightly lower scoring variance** (std dev 8.21 vs 8.87-8.88 in prior Februaries). Less variance = harder to generate edge through statistical divergence.

---

## 8. Multi-Season Training Configurations

### Configuration A: 2 Seasons (Recommended Starting Point)

```
Train: Dec 2024 → Feb 7, 2026 (15 months)
Trainable rows: ~24,000 (13,193 from 2024-25 + ~11,000 from 2025-26)
Recency weight: 60-120 days
```

**Pros:** Good data quality, manageable compute, last season's February patterns included.
**Cons:** May not capture longer-term player tendencies.

### Configuration B: 3 Seasons

```
Train: Dec 2023 → Feb 7, 2026 (27 months)
Trainable rows: ~35,000+
Recency weight: 120-240 days
```

**Pros:** Maximum data, 2 prior Februaries for pattern learning, broader opponent/player coverage.
**Cons:** Oldest data has lower quality (54% clean in early 2024). Longer compute time.

### Configuration C: February Specialist

```
Train: Jan 15 - Mar 15 from each season (3 × 2 months)
Trainable rows: ~10,000-12,000
Recency weight: 30 days
```

**Pros:** Model learns February-specific patterns (trade deadline, all-star break).
**Cons:** Much less data. May overfit to mid-season patterns.

### Configuration D: December Start, Current Season Only (Control)

```
Train: Dec 1, 2025 → Feb 7, 2026 (68 days)
Trainable rows: ~8,000
Recency weight: 14 days
```

**Pros:** Freshest data, highest quality.
**Cons:** Limited data volume, no cross-season learning. This is essentially what we've been doing.

---

## 9. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| November data quality | HIGH | Exclude November from all training windows |
| Vegas coverage cliff (2025-26) | HIGH | Recency weighting ensures older (better coverage) data contributes; also test with/without current season |
| Feature distribution shift | MEDIUM | Monitor feature importance changes between single-season and multi-season models |
| Overfitting to old patterns | MEDIUM | Recency weighting (120d half-life = 2-season-ago data at 12.5% weight) |
| Compute time with 35K rows | LOW | CatBoost handles 35K rows in <5 minutes |
| Schema changes between seasons | LOW | Confirmed: identical 37-feature schema across all seasons |

---

## 10. Recommended Training Dates by Experiment

| Experiment | Train Start | Train End | Eval Start | Eval End | Rows (est) |
|-----------|-------------|-----------|-----------|---------|-----------|
| 2-season Q43 | 2024-12-01 | 2026-02-07 | 2026-02-08 | 2026-02-11 | ~24K |
| 3-season Q43 | 2023-12-01 | 2026-02-07 | 2026-02-08 | 2026-02-11 | ~35K |
| Feb specialist | 2024-01-15 | 2024-03-15 | 2026-02-08 | 2026-02-11 | ~6K |
| Current season (control) | 2025-12-01 | 2026-02-07 | 2026-02-08 | 2026-02-11 | ~8K |

**Always use `--force`** to bypass duplicate date detection when running new experiments on previously-tested windows.

---

## 11. Data Quality Verification Queries

### Before Training — Run These Checks

```sql
-- 1. Verify trainable row count for your date range
SELECT COUNT(*) as trainable_rows
FROM nba_predictions.ml_feature_store_v2 mf
JOIN nba_analytics.player_game_summary pgs
  ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
WHERE mf.game_date BETWEEN '2024-12-01' AND '2026-02-07'
  AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
  AND pgs.points IS NOT NULL
  AND pgs.minutes_played > 0;

-- 2. Check Vegas coverage in your training window
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  ROUND(AVG(CASE WHEN features[OFFSET(25)] > 0 THEN 1 ELSE 0 END) * 100, 1) as vegas_coverage_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2024-12-01' AND '2026-02-07'
  AND COALESCE(required_default_count, default_feature_count, 0) = 0
GROUP BY 1 ORDER BY 1;

-- 3. Check feature quality score distribution
SELECT
  CASE
    WHEN feature_quality_score >= 90 THEN 'A (90+)'
    WHEN feature_quality_score >= 70 THEN 'B (70-89)'
    WHEN feature_quality_score >= 50 THEN 'C (50-69)'
    ELSE 'D (<50)'
  END as quality_tier,
  COUNT(*) as rows,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2024-12-01' AND '2026-02-07'
  AND COALESCE(required_default_count, default_feature_count, 0) = 0
GROUP BY 1 ORDER BY 1;
```

---

## Summary

| Finding | Implication |
|---------|------------|
| 38K trainable rows across 3 seasons | 4.5x more data available than currently used |
| November always bad (21-28% clean) | Start from December, not October |
| Features 33-36 fully populated | Safe to activate as V10 |
| Vegas coverage dropped in 2025-26 | Multi-season training mitigates (older seasons have 60-83%) |
| February scoring is stable across years | Model decay is about staleness, not environment |
| Schema perfectly consistent | No risk of feature drift across seasons |
| Only 2 months of prediction data | Cannot analyze seasonal accuracy patterns yet |
