# Vegas Line Sharpness Analysis

**Date:** 2026-01-31
**Purpose:** Track Vegas accuracy to identify when lines are beatable

---

## Key Finding: Vegas Got Sharper in January

| Period | Model Beats Vegas | Status |
|--------|------------------|--------|
| All-time | 59.3% | SOFT |
| **January 2026** | **45.2%** | **SHARP** |

When model beats Vegas < 50%, we're losing money fighting the market.

---

## Monthly Trend by Tier

| Month | Star | Starter | Rotation | Bench |
|-------|------|---------|----------|-------|
| Nov '25 | 25.0% | 28.6% | 47.9% | N/A |
| **Dec '25** | 42.9% | 49.8% | **56.5%** | 53.4% |
| **Jan '26** | 44.1% | 43.6% | **46.3%** | 44.8% |

### What Happened:
- **November**: Model was terrible (25-48%)
- **December**: Model improved, beat Vegas on Rotation (56.5%)
- **January**: Model regressed, lost edge on Rotation (46.3%)

The biggest drop was Rotation: **56.5% → 46.3%** (-10.2%)

---

## January 2026 Sharpness by Tier

| Tier | Games | Vegas MAE | Model MAE | Model Beats Vegas |
|------|-------|-----------|-----------|-------------------|
| Star | 259 | 7.54 | 8.13 | 44.8% |
| Starter | 707 | 5.80 | 6.28 | 43.3% |
| Rotation | 1,431 | 4.51 | 4.77 | 46.0% |
| Bench | 210 | 2.98 | 3.05 | 46.7% |

**Vegas is more accurate than our model across all tiers in January.**

---

## Edge Availability

| Tier | 3+ Edge % | 5+ Edge % | Vegas Within 3pts |
|------|-----------|-----------|-------------------|
| Star | 56.0% | 27.8% | 31.7% |
| Starter | 50.4% | 25.3% | 34.5% |
| Rotation | 29.6% | 11.7% | 41.0% |
| Bench | 11.9% | 2.4% | 51.9% |

**Stars have the most edge opportunities (56% have 3+ edge)**
**Bench has almost none (only 11.9% have 3+ edge)**

---

## Sharpest Lines (Hardest to Beat)

These players have very accurate Vegas lines:

| Player | Games | Vegas MAE | Model Beats |
|--------|-------|-----------|-------------|
| Ben Sheppard | 8 | 1.51 | 37.5% |
| Dorian Finney-Smith | 10 | 1.82 | 30.0% |
| Alex Caruso | 6 | 1.88 | 16.7% |
| Dwight Powell | 5 | 1.88 | 40.0% |

**Avoid betting on these players** - Vegas has them dialed in.

---

## Softest Lines (Potential Opportunities)

These players have inaccurate Vegas lines:

| Player | Games | Vegas MAE | Model Beats | Opportunity? |
|--------|-------|-----------|-------------|--------------|
| Lauri Markkanen | 9 | 11.91 | 33.3% | ❌ Model also bad |
| Jamal Murray | 11 | 10.68 | 45.5% | ❌ Model also bad |
| **Jalen Brunson** | 10 | 10.64 | **80.0%** | ✅ Model beats Vegas |
| **Cooper Flagg** | 7 | 10.63 | **71.4%** | ✅ Model beats Vegas |
| Anthony Edwards | 9 | 10.56 | 44.4% | ❌ Model also bad |

**Vegas is bad at predicting volatile stars, but so is our model for most of them.**

Exceptions: Brunson (80%) and Flagg (71%) - model is good here.

---

## Monitoring Script

Created `bin/monitoring/vegas_sharpness_monitor.py`:

```bash
# Run sharpness analysis
PYTHONPATH=. python bin/monitoring/vegas_sharpness_monitor.py

# January only
PYTHONPATH=. python bin/monitoring/vegas_sharpness_monitor.py \
    --start-date 2026-01-01 --end-date 2026-01-31

# JSON output for automation
PYTHONPATH=. python bin/monitoring/vegas_sharpness_monitor.py --json
```

---

## Recommendations

### When Vegas is SHARP (model beats < 50%)
1. Increase confidence threshold to 90+
2. Increase edge threshold to 5+
3. Reduce bet sizing
4. Focus on "soft line" players like Brunson, Flagg

### When Vegas is SOFT (model beats > 55%)
1. Standard thresholds (85+ conf, 3+ edge)
2. Increase volume
3. All tiers are fair game

---

## Why Does Vegas Sharpness Fluctuate?

### Vegas Gets Sharper When:
1. **More data accumulates** - Mid-season Vegas has 3 months of data
2. **Player roles stabilize** - Rotations settle, minutes predictable
3. **Injuries are known** - No surprise DNPs
4. **Market converges** - More bettors = more efficient lines

### Vegas Gets Softer When:
1. **Season start** - Limited recent data
2. **Roster changes** - Trades, injuries, callups
3. **Back-to-backs** - Load management unpredictable
4. **Player breakouts** - Emerging stars not yet priced in

---

## Summary

| Metric | December | January | Change |
|--------|----------|---------|--------|
| Model beats Vegas | 52.8% | 45.2% | **-7.6%** |
| Rotation tier | 56.5% | 46.3% | **-10.2%** |
| Status | NORMAL | **SHARP** | Degraded |

**January = Vegas is sharper. Use stricter filters (90+ conf, 5+ edge).**

---

*Created: Session 55*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
