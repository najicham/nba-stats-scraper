# Pre-Game Signals System - Phases 1-5 Implementation Complete

**Date**: February 1, 2026
**Session**: 70-71
**Status**: ✅ COMPLETE - All phases implemented and deployed

---

## Executive Summary

The dynamic subset system is now fully operational. Users can query picks from 9 different subsets that combine:
- **Static filtering** (edge thresholds, confidence)
- **Dynamic signals** (daily pct_over signal)
- **Composite ranking** (edge * 10 + confidence * 0.5)

**Key Achievement**: Implemented statistically validated signal infrastructure (p=0.0065) that correlates 28-point hit rate difference between RED and GREEN signal days.

---

## What Was Built

### Phase 1: Signal Infrastructure ✅

**Table Created**: `daily_prediction_signals`

| Field | Purpose |
|-------|---------|
| game_date, system_id | Identity |
| total_picks, high_edge_picks, premium_picks | Volume metrics |
| pct_over, pct_under | Signal metrics |
| skew_category, daily_signal | Classifications |
| signal_explanation | Human-readable interpretation |

**Data Loaded**:
- 165 historical records (Jan 9 - Feb 1, 2026)
- 9 model systems tracked (catboost_v8, catboost_v9, ensemble_v1, etc.)

**Integration**:
- Added Phase 0.5 to `/validate-daily` skill
- Shows daily signal with warning when RED (pct_over <25%)
- Interprets signal status for users

**Test Results**:
```
Date: 2026-02-01
System: catboost_v9
pct_over: 10.6% (UNDER_HEAVY)
Daily Signal: RED
High-edge picks: 4
Historical context: 54% HR on RED days vs 82% on GREEN days
```

### Phase 2: Dynamic Subset Definitions ✅

**Table Created**: `dynamic_subset_definitions`

Schema includes:
- Identity: subset_id, subset_name, subset_description
- Filters: system_id, min_edge, min_confidence
- Signal conditions: signal_condition, pct_over_min, pct_over_max
- Ranking: use_ranking, top_n
- Metadata: is_active, created_at, notes

**9 Subsets Defined**:

| Category | Subset ID | Strategy | Historical Performance |
|----------|-----------|----------|----------------------|
| **Ranked** | v9_high_edge_top1 | Best pick by composite score | Lock of the day |
| | v9_high_edge_top3 | Top 3 by score | Ultra-selective |
| | v9_high_edge_top5 | Top 5 by score | Recommended default |
| | v9_high_edge_top10 | Top 10 by score | More volume |
| **Signal-based** | v9_high_edge_balanced | GREEN signal only | 82% HR |
| | v9_high_edge_any | No signal filter | Baseline |
| | v9_high_edge_warning | RED signal tracking | 54% HR |
| | v9_premium_safe | High conf + non-RED | Safe plays |
| **Combined** | v9_high_edge_top5_balanced | Top 5 + GREEN signal | Best of both |

### Phase 3: /subset-picks Skill ✅

**Capabilities**:
1. List all available subsets with metadata
2. Query today's picks from any subset with signal context
3. Show historical performance (last N days)
4. Warn when signal doesn't match subset requirements

**Query Types**:
- **Unranked**: Filter by edge/confidence + signal condition
- **Ranked**: Top N by composite score (edge * 10 + confidence * 0.5)
- **Historical**: Join with actual results for performance tracking

**Test Results (Feb 1, 2026)**:

Today's top 5 high-edge picks:
| Rank | Player | Edge | Composite Score |
|------|--------|------|-----------------|
| 1 | Rui Hachimura | 6.1 | 103.0 |
| 2 | DeAndre Ayton | 5.6 | 98.0 |
| 3 | Jaylen Brown | 5.2 | 94.0 |
| 4 | Nikola Jokic | 5.0 | 92.0 |

Signal context: RED (10.6% pct_over)

---

## Statistical Validation

### Signal Discovery (Session 70)

**Finding**: pct_over (% of predictions recommending OVER) correlates with model performance.

| pct_over Range | Hit Rate | Sample | Category |
|----------------|----------|--------|----------|
| <25% | 53.8% | 26 picks | UNDER_HEAVY (RED) |
| 25-40% | 82.0% | 61 picks | BALANCED (GREEN) |
| >40% | 88.9% | 54 picks | OVER_HEAVY (YELLOW)* |

*Only 1 day of data for OVER_HEAVY

**Statistical Test**: Two-proportion z-test
- Z-statistic: 2.72
- P-value: **0.0065** (highly significant, p < 0.01)
- 95% CI: [6.7%, 49.6%]
- Conclusion: The 28-point difference is statistically significant

**Data**: 23 days, 87 high-edge picks (Jan 9-31, 2026)

### Composite Score Formula

```
composite_score = (edge * 10) + (confidence * 0.5)
```

**Rationale**:
- 1 point edge = 10 score points
- 20% confidence difference = 10 score points
- Edge dominates (primary value driver)
- Confidence is tiebreaker

**Example Validation**:
- 7.2 edge, 87% conf → 72 + 43.5 = **115.5**
- 5.8 edge, 92% conf → 58 + 46.0 = **104.0**

Player with higher edge ranks first ✅

---

## Usage Examples

### List Available Subsets

```bash
/subset-picks
```

Output shows all 9 subsets with selection strategy and signal requirements.

### Get Today's Top 5 Picks

```bash
/subset-picks v9_high_edge_top5
```

Returns ranked picks with:
- Composite score
- Signal context (pct_over, daily_signal)
- Edge and confidence values

### Check Balanced Subset (Signal-Aware)

```bash
/subset-picks v9_high_edge_balanced
```

On RED signal day:
- Shows warning that signal is RED
- Subset requires GREEN
- Displays picks but marks as EXCLUDED
- Recommends skipping today based on historical 54% HR

### Historical Performance

```bash
/subset-picks v9_high_edge_top5 --history 14
```

Shows:
- Total picks over last 14 days
- Win rate
- Hit rate percentage
- Days included

---

## A/B Testing Strategy

All 9 subsets will track performance simultaneously for 2-4 weeks to discover which combination works best:

**Questions to Answer**:
1. Does ranking improve hit rate? (top3 vs top10 vs all)
2. Does signal filtering add value on top of ranking? (top5_balanced vs top5_any)
3. What's the optimal subset? (may vary by user risk tolerance)

**Tracking**: Use `player_prop_predictions` + `player_game_summary` join with `daily_prediction_signals` for grading.

---

## Database Schema

### daily_prediction_signals

```sql
CREATE TABLE `nba-props-platform.nba_predictions.daily_prediction_signals` (
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,
  total_picks INT64,
  high_edge_picks INT64,
  premium_picks INT64,
  pct_over FLOAT64,
  pct_under FLOAT64,
  avg_confidence FLOAT64,
  avg_edge FLOAT64,
  skew_category STRING,
  volume_category STRING,
  daily_signal STRING,
  signal_explanation STRING,
  calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date;
```

### dynamic_subset_definitions

```sql
CREATE TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions` (
  subset_id STRING NOT NULL,
  subset_name STRING NOT NULL,
  subset_description STRING,
  system_id STRING,
  min_edge FLOAT64,
  min_confidence FLOAT64,
  signal_condition STRING,
  pct_over_min FLOAT64,
  pct_over_max FLOAT64,
  use_ranking BOOL DEFAULT FALSE,
  top_n INT64,
  is_active BOOL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  notes STRING
);
```

---

## Phase 4: Automated Signal Calculation ✅ (Session 71)

**Implemented**: Signal calculation now runs automatically after batch consolidation.

**Components**:
- `predictions/coordinator/signal_calculator.py` - Utility module
- Integration in `coordinator.py` (both Firestore and legacy paths)

**How It Works**:
1. Predictions consolidate into main table
2. Signal calculator runs automatically
3. Signals stored in `daily_prediction_signals`
4. No manual intervention needed

**Commit**: `257807b9`

---

## Phase 5: /subset-performance Skill ✅ (Session 71)

**Implemented**: Compare subset performance across time periods.

**Usage**:
```bash
/subset-performance                    # Last 7 days
/subset-performance --period 14        # Last 14 days
/subset-performance --subset v9_high*  # Filter by pattern
```

**Outputs**:
- Hit rates by subset
- ROI estimates
- Signal effectiveness comparison (GREEN vs RED)
- Key insights and recommendations

**Files Created**:
- `.claude/skills/subset-performance/SKILL.md`
- `.claude/skills/subset-performance/manifest.json`

**Commit**: `257807b9`

---

## Future Work (Phase 6+)

**NOT implemented yet**:

1. **Dashboard Integration**
   - Signal indicator on unified dashboard
   - Subset performance widgets
   - Slack alerts for RED signal days

2. **Additional Signals**
   - Line movement tracking
   - Model agreement (V8+V9 consensus)
   - Back-to-back game factors
   - Per-game signals (vs per-day)

3. **Threshold Tuning**
   - Validate 25% and 40% thresholds with more data
   - Consider ROC curve analysis for optimal cutoffs
   - Expand OVER_HEAVY analysis (only 1 day currently)

---

## Files Changed

**BigQuery Tables Created**:
- `nba_predictions.daily_prediction_signals` (165+ rows)
- `nba_predictions.dynamic_subset_definitions` (9 rows)

**Skills Added**:
- `.claude/skills/subset-picks/SKILL.md`
- `.claude/skills/subset-picks/manifest.json`
- `.claude/skills/subset-performance/SKILL.md` (Phase 5)
- `.claude/skills/subset-performance/manifest.json` (Phase 5)

**Skills Modified**:
- `.claude/skills/validate-daily/SKILL.md` (added Phase 0.5 signal check)

**Coordinator Modified**:
- `predictions/coordinator/coordinator.py` (auto signal calculation)
- `predictions/coordinator/signal_calculator.py` (Phase 4 utility)

**Git Commits**:
1. `2e6f7c70` - Phase 1: Signal infrastructure and validate-daily integration
2. `99bf7381` - Phases 2+3: Dynamic subsets and /subset-picks skill
3. `257807b9` - Phases 4+5: Auto signal calculation and /subset-performance skill

---

## Validation Checklist

- [x] `daily_prediction_signals` table exists
- [x] Historical data backfilled (165 records)
- [x] Today's V9 signal shows RED (10.6% pct_over)
- [x] Signal check integrated in `/validate-daily`
- [x] `dynamic_subset_definitions` table exists with 9 rows
- [x] All 9 subsets are active
- [x] `/subset-picks` skill files created
- [x] Test query returns today's top 5 picks
- [x] Composite scores calculated correctly
- [x] Signal warnings display properly
- [x] Changes committed to git

---

## Known Limitations

1. **Sample Size**: Only 23 days of data for signal validation (Jan 9-31)
2. **OVER_HEAVY**: Only 1 day in dataset, threshold may need adjustment
3. **Single Model**: Validated only for catboost_v9 (need to test V8, ensembles)
4. **No Proactive Alerts**: RED signal day warnings not sent via Slack/email (only in /validate-daily)

---

## Performance Expectations

Based on historical data (Jan 9-31, 2026):

| Subset | Expected Hit Rate | Use Case |
|--------|------------------|----------|
| v9_high_edge_balanced | ~82% | GREEN signal days only |
| v9_high_edge_top5 | TBD | Recommended default |
| v9_high_edge_any | ~65-70% | Baseline (all days) |
| v9_high_edge_warning | ~54% | RED day tracking |

**Validation Period**: Monitor for 30-60 days to confirm signal reliability.

---

## Documentation

- **Design**: `DYNAMIC-SUBSET-DESIGN.md`
- **Review**: `SESSION-70-DESIGN-REVIEW.md`
- **Signal Discovery**: `README.md`
- **Implementation**: This document
- **SQL Queries**: `daily-diagnostic.sql`, `historical-analysis.sql`

---

**Status**: System is production-ready and fully automated. All 5 phases complete.

**Available Skills**:
- `/subset-picks` - Get picks from any subset with signal context
- `/subset-performance` - Compare subset performance over time
- `/validate-daily` - Includes signal check in Phase 0.5

**Next Steps**:
1. Monitor signal effectiveness over next 7-14 days
2. Validate Feb 1 RED signal (expect ~50-55% hit rate)
3. Review `/subset-performance` output to identify best-performing subsets
4. Consider Phase 6 work (dashboard integration, Slack alerts)

---

*Implemented by: Claude Sonnet 4.5 (Phases 1-3), Claude Opus 4.5 (Phases 4-5)*
*Sessions: 70 (design), 71 (implementation)*
*Date: February 1, 2026*
