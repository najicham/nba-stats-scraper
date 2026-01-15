# MLB Performance Analysis

**Project:** MLB Pitcher Strikeouts Prediction
**Current Model:** V1 XGBoost (67.27% hit rate)
**Status:** Production, monitoring for improvements

---

## Documents

| Document | Purpose |
|----------|---------|
| [PERFORMANCE-ANALYSIS-GUIDE.md](./PERFORMANCE-ANALYSIS-GUIDE.md) | Quick commands, seasonal patterns, monitoring |
| [FEATURE-IMPROVEMENT-ROADMAP.md](./FEATURE-IMPROVEMENT-ROADMAP.md) | Future features, implementation priorities |

---

## Quick Stats

```
Overall Hit Rate:  67.27% (+14.89pp over breakeven)
Total Picks:       7,196
MAE:               1.46 strikeouts
Best Month:        March 2025 (75.45%)
Worst Month:       August 2025 (56.64%)
Best Direction:    UNDER (70.0% vs 65.4% OVER)
```

---

## Key Findings

### Seasonal Pattern (Critical)

```
Spring (Mar-May):  70-75% hit rate
Summer (Jun-Aug):  56-65% hit rate (⚠️ decline)
Fall (Sep):        63% hit rate (recovery)
```

**Action:** Add seasonal features, consider mid-season retraining

### Edge Correlation (V1 Strength)

```
Edge 2.5+:   92% win rate
Edge 2.0+:   90% win rate
Edge 1.5+:   81% win rate
Edge 1.0+:   79% win rate
Edge 0.5+:   68% win rate
```

**Action:** Raise minimum edge to 1.0 for better ROI

### Direction Bias

```
UNDER: 70.0% win rate (outperforms)
OVER:  65.4% win rate
```

**Action:** Weight UNDER picks, investigate cause

---

## Next Actions

1. **Immediate:** Add `month_of_season` feature to V1
2. **Short-term:** Scrape pitcher splits (home/away, day/night)
3. **Medium-term:** Integrate game totals from Odds API
4. **Long-term:** Statcast velocity/spin data

---

## Related Projects

- [mlb-pitcher-strikeouts/](../mlb-pitcher-strikeouts/) - Main project docs
- [mlb-pitcher-strikeouts/SESSION-42](../mlb-pitcher-strikeouts/2026-01-14-SESSION-42-V2-DATA-AUDIT.md) - V2 training analysis
