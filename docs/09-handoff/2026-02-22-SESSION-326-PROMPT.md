# Session 326 Prompt — Deploy, Signal Study, Ultra Bets Investigation

**Date:** 2026-02-22
**Prerequisite:** Session 325 completed V12+vegas replay + fresh retrains. Code changes NOT yet committed.

## Task 1: Commit, Push, Verify Deployment

Session 325 modified 2 files:
- `bin/backfill-challenger-predictions.py` — V12 contract support for backfill
- `predictions/worker/prediction_systems/catboost_monthly.py` — 5 new MONTHLY_MODELS entries

```bash
# Commit and push
git add bin/backfill-challenger-predictions.py predictions/worker/prediction_systems/catboost_monthly.py
git commit -m "feat: V12+vegas replay models + fresh retrains for multi-model best bets"
git push origin main

# Verify builds
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
./bin/check-deployment-drift.sh --verbose
```

## Task 2: Materialize Best Bets Backfill

Session 325 ran a dry-run showing **66.0% HR, $2,680 P&L** across 100 picks (Jan 9 - Feb 21). Now write the picks to BigQuery:

```bash
PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-01-09 --end 2026-02-21 --write
```

After writing, verify:
```sql
SELECT game_date, COUNT(*) as picks,
       COUNTIF(prediction_correct) as wins,
       ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1) as hr
FROM nba_predictions.signal_best_bets_picks
WHERE game_date BETWEEN '2026-01-09' AND '2026-02-21'
GROUP BY 1 ORDER BY 1
```

## Task 3: Signal Effectiveness Study

**Goal:** Which of the 16 active signals actually correlate with winning picks? Which are noise?

### Approach
Query `prediction_accuracy` joined with signal data to measure each signal's contribution:

```sql
-- For each signal, what's the HR when it fires vs when it doesn't?
-- For edge 3+ and edge 5+ picks
-- Across the full Jan 9 - Feb 21 period
-- Compare V9 vs V12+vegas
```

**Key questions:**
1. Which signals have the highest win correlation?
2. Are any signals actively hurting (should be negative filters)?
3. Do signals interact differently with V12+vegas vs V9?
4. Is the MIN_SIGNAL_COUNT=2 requirement too strict? (caused 0-pick days on Jan 18, 23, 24, 27, Feb 6)

**Signals to evaluate:** `high_edge`, `edge_spread_optimal`, `combo_he_ms`, `combo_3way`, `bench_under`, `3pt_bounce`, `b2b_fatigue_under`, `high_ft_under`, `rest_advantage_2d`, `prop_line_drop_over`, `book_disagreement`, `self_creator_under`, `volatile_under`, `high_usage_under`, `blowout_recovery`, `model_health`

**Files:** `ml/signals/` (individual signal implementations), `ml/signals/aggregator.py` (how signals are combined), `data_processors/publishing/signal_best_bets_exporter.py` (how picks are selected)

## Task 4: Investigate "Ultra Bets" — High-Confidence Subset

**Concept:** A Layer 3 subset above best bets that only includes picks meeting extremely strict criteria. Targeting 75%+ HR for users who want fewer but more reliable picks.

### Candidate Criteria to Test (from Session 325 data)

The dry-run showed these high-HR segments:

| Criteria | HR | N | Notes |
|----------|-----|---|-------|
| Edge 7+ (OVER only) | ~100% | small | UNDER edge 7+ is blocked (40.7% HR) |
| V12+vegas + edge 5+ | 82.5% | 40 | V12+vegas at high edge dominates |
| Multiple models agree (same direction, edge 5+) | TBD | TBD | Consensus = confidence |
| Mid-line (12.5-20.5) + edge 5+ | 87.5% | 8 | Sweet spot for line range |
| Starters (15-24) + UNDER | 85.7% | 7 | Interesting niche |

### Investigation Steps

1. **Query historical data** to find combinations with 75%+ HR and N >= 30:
```sql
-- Test combinations of: edge bucket, direction, line range, tier, source model family
-- Look for segments where HR >= 75% with reasonable sample size
SELECT
  CASE WHEN ABS(predicted_margin) >= 7 THEN '7+'
       WHEN ABS(predicted_margin) >= 5 THEN '5-7' ELSE '3-5' END as edge_bucket,
  recommendation as direction,
  CASE WHEN line_value < 12.5 THEN 'low' WHEN line_value <= 20.5 THEN 'mid' ELSE 'high' END as line_range,
  COUNT(*) as n,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE game_date BETWEEN '2026-01-09' AND '2026-02-21'
  AND system_id IN ('catboost_v12_train1102_1225', 'catboost_v12_train1102_0125', 'catboost_v12_train1225_0205')
  AND ABS(predicted_margin) >= 3
GROUP BY 1, 2, 3
HAVING COUNT(*) >= 10
ORDER BY hr DESC
```

2. **Design the Ultra Bets filter chain** — additional filters on top of best bets:
   - Higher edge floor (7+? V12+vegas-only?)
   - Direction restrictions (OVER-only at high edge?)
   - Multi-model agreement requirement
   - Line range filter (mid-line sweet spot?)

3. **Backtest Ultra Bets** — run the filter chain on Jan 9 - Feb 21 data
   - Target: 75%+ HR, 1-3 picks per day (some days 0)
   - Compare P&L vs best bets (fewer picks but higher win rate)

4. **Implementation** — if the criteria look good:
   - Add as a new subset in `shared/config/dynamic_subsets.py`
   - Add to `SignalBestBetsExporter` as a separate tier
   - Export to `v1/ultra-bets/{date}.json` for the API

### Key Architecture Questions
- Should Ultra Bets be a separate export (new file) or a flag on best bets picks?
- Should it have its own algorithm version string for traceability?
- How does it interact with the existing best bets (superset? independent?)

## Task 5: Filter Audit

Review the negative filters that rejected picks in the dry-run to see if any are too aggressive:

| Filter | Rejections | Question |
|--------|-----------|----------|
| edge_floor (5.0) | 3,704 | Is 5.0 still optimal? What about 4.5? |
| quality_floor (85) | 24 | Are good picks being dropped? |
| line_jumped_under | 15 | All correct rejections? |
| blacklist | 12 | Review blacklisted players |
| under_edge_7plus | 30 | Confirmed bad (40.7% HR) |
| bench_under | 4 | Small N, probably fine |

For each filter, query the actual HR of rejected picks to confirm they're genuinely bad.

## Context: Current System State

### Models (13 shadows + 1 champion)
- **Champion:** `catboost_v9` (33f, trained Nov 2 - Feb 5, 48.3% HR edge 3+)
- **V12+vegas replay:** 3 walk-forward models covering Jan 9 - Feb 21 (62.7% combined HR)
- **Fresh retrains:** V9 MAE, V12+vegas MAE, V12+vegas Q43 — all Dec 25 - Feb 5 window
- **Existing shadows:** V12 noveg, V9 Q43/Q45, V9 low-vegas, V12+vegas Q43 Session 324

### Best Bets Algorithm
Multi-model candidate generation → per-player highest edge → edge floor 5.0 → negative filters → signal eval (MIN_SIGNAL_COUNT=2) → rank by edge

### Key Files
- `ml/signals/aggregator.py` — filter chain + ranking
- `ml/signals/` — individual signal implementations
- `data_processors/publishing/signal_best_bets_exporter.py` — pick selection
- `shared/config/dynamic_subsets.py` — subset definitions
- `shared/config/cross_model_subsets.py` — model discovery
- `bin/backfill_dry_run.py` — simulation tool

### Recent Performance
- Best bets dry-run: **66.0% HR** (94 graded picks, $2,680 P&L)
- V12+vegas walk-forward: **62.7% HR edge 3+** (220 picks)
- V9 baseline same period: 48.3% HR edge 3+
