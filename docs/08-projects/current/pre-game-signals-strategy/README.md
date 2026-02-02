# Pre-Game Signals Strategy

**Created:** Session 69 (2026-02-01)
**Implemented:** Sessions 70-71 (2026-02-01)
**Status:** ✅ COMPLETE - All 5 phases implemented and deployed
**Purpose:** Identify pre-game signals that predict daily model performance

---

## Executive Summary

Analysis of V9 predictions (Jan 9-31, 2026) revealed a statistically significant pre-game signal: **pct_over** (the percentage of predictions recommending OVER) correlates strongly with high-edge hit rate.

| pct_over | High-Edge Hit Rate | Sample |
|----------|-------------------|--------|
| <25% (Under-heavy) | **53.8%** | 26 picks |
| >=25% (Balanced) | **82.0%** | 61 picks |

**P-value: 0.0065** - This is statistically significant.

---

## The pct_over Signal

### What It Is

`pct_over` = percentage of V9 predictions that recommend OVER (vs UNDER)

```sql
ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over
```

### Why It Matters

When V9 heavily skews toward UNDER predictions (<25% over):
- The model may be over-correcting for market conditions
- High-edge picks drop from 82% → 54% hit rate
- This is barely above the 52.4% breakeven threshold

### Thresholds

| pct_over | Category | Historical Performance | Action |
|----------|----------|----------------------|--------|
| <25% | UNDER_HEAVY | 53.8% hit rate | ⚠️ Reduce bet sizing |
| 25-40% | BALANCED | 82.0% hit rate | ✅ Normal confidence |
| >40% | OVER_HEAVY | 88.9% hit rate* | ✅ Higher confidence |

*Note: OVER_HEAVY based on 1 day (Jan 12), may be anomaly.

---

## Statistical Validation

### Data

- **Period:** Jan 9-31, 2026 (23 days)
- **Model:** catboost_v9
- **Filter:** High-edge picks only (5+ point edge)

### Results by Category

| Category | Days | Picks | Wins | Hit Rate |
|----------|------|-------|------|----------|
| UNDER_HEAVY (<25%) | 7 | 26 | 14 | 53.8% |
| BALANCED (25-40%) | 15 | 61 | 50 | 82.0% |
| OVER_HEAVY (>40%) | 1 | 54 | 48 | 88.9% |

### Statistical Test

Two-proportion z-test comparing UNDER_HEAVY vs BALANCED:

| Metric | Value |
|--------|-------|
| Z-statistic | 2.72 |
| P-value | **0.0065** |
| 95% CI | [6.7%, 49.6%] |
| Significant? | ✅ Yes (p < 0.01) |

The 28-point difference in hit rate is statistically significant.

---

## Daily Check Query

Run this each morning before betting:

```sql
-- Pre-game signal check
SELECT
  game_date,
  COUNT(*) as total_picks,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as high_edge_picks,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25
      THEN '⚠️ UNDER_HEAVY - Historical 54% HR'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 40
      THEN '✅ OVER_HEAVY - Historical 89% HR'
    ELSE '✅ BALANCED - Historical 82% HR'
  END as signal
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND current_points_line IS NOT NULL
GROUP BY game_date
```

---

## Implementation Status: ✅ COMPLETE

All implementation phases have been completed (Sessions 70-71):

### Available Skills

| Skill | Purpose |
|-------|---------|
| `/subset-picks` | Get picks from 9 dynamic subsets with signal context |
| `/subset-performance` | Compare subset performance over time |
| `/validate-daily` | Includes signal check in Phase 0.5 |

### Automation

- **Auto Signal Calculation**: Signals are calculated automatically after predictions consolidate
- **Storage**: `nba_predictions.daily_prediction_signals` table (165+ records)
- **Integration**: Coordinator calls `calculate_daily_signals()` after batch completion

### Full Documentation

See `IMPLEMENTATION-COMPLETE.md` for detailed implementation guide.

---

## Caveats

1. **Sample Size:** Only 23 days of data (Jan 9-31)
2. **Single Model:** Only validated for catboost_v9
3. **Jan 12 Anomaly:** One day had 98% pct_over with 59 high-edge picks
4. **Correlation ≠ Causation:** The signal may be a symptom, not a cause

### Ongoing Validation

Monitor this signal daily:
- Track pct_over vs actual hit rate
- If pattern breaks, investigate
- Expand to monthly models (catboost_v9_2026_02, etc.)

---

## Related Documents

- Session 70 Handoff: `docs/09-handoff/2026-02-01-SESSION-70-V9-PERFORMANCE-ANALYSIS.md`
- Hit Rate Analysis Skill: `.claude/skills/hit-rate-analysis/SKILL.md`
- Top Picks Skill: `.claude/skills/top-picks/SKILL.md`

---

## Change Log

| Date | Session | Change |
|------|---------|--------|
| 2026-02-01 | 69 | Created document, validated Session 70 findings |
| 2026-02-01 | 70 | Implemented Phases 1-3 (signal infrastructure, subsets, /subset-picks) |
| 2026-02-01 | 71 | Implemented Phases 4-5 (auto signal calculation, /subset-performance) |

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
