# MLB Strikeout Predictions - Synthetic Hit Rate Analysis

**Generated**: 2026-01-13 19:17:32
**Analysis Type**: Layer 2 - Synthetic Betting Performance
**Data Period**: 2024-04-09 to 2025-09-28
**Methodology**: Rolling average synthetic betting lines

---

## Executive Summary

**Verdict**: PROMISING
**Recommendation**: Model shows strong value detection. Proceed with forward validation.

### Key Metrics (Simple Method)
- **Total Bets**: 5,327
- **Hit Rate**: 78.04%
- **vs Breakeven (52.4%)**: +25.64%
- **Avg Edge**: 1.181 K

---

## Methodology

### Synthetic Betting Lines

**Method A - Simple (Primary)**:
- Synthetic Line = Pitcher's 10-game rolling average strikeouts
- Bet when |predicted - synthetic_line| > 0.5 K
- OVER when predicted > line, UNDER when predicted < line

**Method B - Context Adjusted**:
- Adjusts rolling average for home/away context
- Home: +5% boost, Away: -5% penalty
- Otherwise same as Method A

### Important Caveats

- Synthetic lines may differ significantly from real betting lines
- Real markets incorporate information not in our features
- This is a directional indicator, not a profitability guarantee
- Forward validation with real lines is essential


---

## Results: Simple Method (Primary)

### Overall Hit Rate

| Metric | Value |
|--------|-------|
| Total Bets | 5,327 |
| Wins | 4,157 |
| Losses | 1,170 |
| Hit Rate | 78.04% |
| vs Breakeven | +25.64% |

### By Recommendation Type

| Type | Bets | Wins | Hit Rate |
|------|------|------|----------|
| OVER | 3,041 | 2,291 | 75.34% |
| UNDER | 2,286 | 1,866 | 81.63% |

### Edge Analysis

| Metric | Value |
|--------|-------|
| Avg Edge (All Bets) | 1.181 K |
| Avg Edge (Wins) | 1.255 K |
| Avg Edge (Losses) | 0.916 K |

**Interpretation**: Wins have higher edge ✅

---

## Hit Rate by Edge Size

| Edge Size (K) | Bets | Hit Rate | vs Breakeven |
|---------------|------|----------|-------------|
| 0.5-1.0 | 2,515 | 68.43% | +16.03% |
| 1.0-1.5 | 1,583 | 81.49% | +29.09% |
| 1.5-2.0 | 737 | 91.59% | +39.19% |
| 2.0+ | 492 | 95.73% | +43.33% |


**Interpretation**: Hit rate should generally increase with edge size. If not, model may not be well calibrated for betting.

---

## Hit Rate by Confidence Tier

| Confidence Tier | Bets | Hit Rate | Avg Confidence |
|-----------------|------|----------|----------------|
| 75-85% | 5,327 | 78.04% | 0.8 |


---

## Hit Rate by Context

### Home vs Away

- **Home Games**: 2,647 bets, 78.43% hit rate
- **Away Games**: 2,680 bets, 77.65% hit rate

### By Season

- **2024**: 2,479 bets, 83.02% hit rate
- **2025**: 2,848 bets, 73.7% hit rate


---

## Comparison: Simple vs Adjusted Method

| Method | Hit Rate | Bets | Edge vs Breakeven |
|--------|----------|------|-------------------|
| Simple (10-game avg) | 78.04% | 5,327 | +25.64% |
| Adjusted (home/away) | 79.11% | 5,281 | +26.71% |

**Recommendation**: Use adjusted method for forward validation.

---

## Overall Verdict

**Assessment**: PROMISING

**Hit Rate**: 78.04%

**Edge vs Breakeven**: +25.64%

**Confidence Level**: MEDIUM-HIGH

### Recommendation

Model shows strong value detection. Proceed with forward validation.

### Next Steps

1. ✅ HIGH PRIORITY: Implement forward validation pipeline
2. ✅ Start collecting real betting lines daily
3. ✅ Run predictions with real lines
4. ✅ Build 50+ prediction track record
5. ✅ Compare real hit rate to synthetic estimates
6. ✅ Deploy to production if real hit rate validates


---

## Limitations & Disclaimers

### Why Synthetic Lines May Differ from Real Lines

1. **Information Asymmetry**: Real betting lines incorporate sharp bettor action, injury news, weather, and other factors not in our model
2. **Market Efficiency**: Professional bookmakers are sophisticated - they may price lines better than simple rolling averages
3. **Sample Bias**: We only bet when we see edge - real markets may not offer edge on these same games
4. **Vig/Juice**: Real betting has -110 odds (52.4% breakeven), synthetic analysis doesn't model this perfectly
5. **Line Movement**: Real lines move based on betting action - we're using static synthetic lines

### Confidence in Results

✅ Synthetic hit rate is strong enough that even with real-world inefficiencies, model likely profitable


**Forward validation with real betting lines is ESSENTIAL before any production deployment.**

---

**Analysis Script**: `scripts/mlb/historical_odds_backfill/analyze_synthetic_hit_rate.py`
**Data Sources**:
- Predictions: `mlb_predictions.pitcher_strikeouts`
- Synthetic Lines: `mlb_analytics.pitcher_game_summary` (k_avg_last_10)
- Actuals: `mlb_analytics.pitcher_game_summary` (actual_strikeouts)
