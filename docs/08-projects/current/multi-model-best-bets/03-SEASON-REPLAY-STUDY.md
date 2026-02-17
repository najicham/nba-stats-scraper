# Season Replay with Biweekly Retraining + Subset Picks — Study

**Session 279 — Research**
**Goal:** Replay this season (and optionally last season) with biweekly retraining, generate all subset picks at each point, measure subset performance.

---

## What Already Exists

We have mature infrastructure for each piece, but no single tool that stitches them together:

### 1. Walk-Forward Season Simulator (`ml/experiments/season_walkforward.py`)
- Trains fresh CatBoost model every N days, evaluates on next window
- Proven finding: **14-day cadence = 68.8% HR, +31.3% ROI**
- Evaluates **raw edge 3+ picks only** — no subset filtering, no signals
- Supports expanding + rolling windows, multiple cadences
- Already runs for this season (2025-11-02 to present)

### 2. Steering Replay (`ml/analysis/steering_replay.py`)
- Replays the **full signal pipeline** per day: model health, signals, combos, aggregator
- Produces top-5 signal-curated picks per day, grades against actuals
- Uses **production predictions** from `prediction_accuracy` (not simulated)
- Cannot replay with different models or retraining cadences

### 3. Subset Infrastructure
- **SubsetMaterializer** — applies 35 subset definitions to predictions
- **SubsetGradingProcessor** — grades materialized subsets against actuals
- **v_dynamic_subset_performance** — retroactive view computing per-subset daily performance
- All operate on LIVE `player_prop_predictions` data, not simulated predictions

### 4. Replay Pipeline (`bin/testing/replay_pipeline.py`)
- Full Phase 2-6 pipeline replay for a single date
- Writes to test datasets to avoid contaminating production
- Doesn't handle retraining or multi-date orchestration

---

## The Gap

No tool combines: **train model → make predictions → apply subsets → grade → repeat for N cycles across a season.**

- `season_walkforward.py` trains and evaluates, but doesn't apply subset filters
- `steering_replay.py` applies signals/subsets, but uses production predictions (no retraining)
- `SubsetMaterializer` writes to BQ, but needs a BQ source table (can't run on in-memory predictions)

---

## Three Approaches

### Approach A: Extend season_walkforward.py (Recommended)

**Add subset simulation layer on top of existing walkforward.**

After each cycle trains a model and produces predictions, apply subset definitions as in-memory filters:

```python
# Existing: train model, predict, compute hit rate
preds = model.predict(X_eval)

# NEW: apply each subset definition as a filter
for subset_def in subset_definitions:
    filtered = apply_subset_filter(preds, actuals, lines, eval_slice, subset_def)
    # filtered = top_n by edge, min_edge, direction, etc.
    # grade filtered picks
    subset_results[subset_def['subset_id']].append(grade(filtered))
```

The subset definitions are just filters: min_edge, min_confidence, direction, top_n (ranked by composite_score or edge). We don't need BigQuery — we can apply them in pure Python against the cycle's predictions.

**Pros:**
- Fastest to implement (~200 lines added to existing simulator)
- Runs entirely in-memory (2 BQ queries for all data, then pure Python)
- Can compare cadences AND subsets simultaneously
- Works for last season too (just needs feature store + actuals)

**Cons:**
- Doesn't test the full pipeline (no real BQ writes, no materializer)
- No signal evaluation (signals need supplemental BQ data)
- Subset composite_score needs confidence_score, which walkforward doesn't currently compute

**Effort:** ~2-3 hours

### Approach B: New Full-Pipeline Season Orchestrator

Build a new tool that orchestrates the real pipeline per-date:

```
For each 14-day cycle:
  1. Train model (quick_retrain.py)
  2. For each date in eval window:
     a. Write predictions to test BQ table
     b. Run SubsetMaterializer against test table
     c. Run CrossModelSubsetMaterializer
     d. Run SignalAnnotator + aggregator
     e. Run SubsetGradingProcessor
  3. Aggregate results across dates
```

**Pros:**
- Tests the REAL pipeline code (materializer, grading, signals)
- Discovers integration bugs
- Results are directly comparable to production

**Cons:**
- Slow: ~60 BQ queries per date (60 dates × 60 = 3,600 queries per cycle)
- Complex: needs test dataset management, cleanup
- Expensive: ~$10-20 in BQ costs per run
- Can't easily run for last season (feature store structure may differ)

**Effort:** ~8-12 hours

### Approach C: Retroactive Performance from Existing Data (Cheapest)

For the CURRENT season, subset performance is already tracked. Just query it:

```sql
-- Season-wide performance per subset
SELECT
  subset_id,
  COUNT(*) as game_days,
  SUM(graded_picks) as total_graded,
  SUM(wins) as total_wins,
  ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as season_hr,
  ROUND(SUM(wins * 0.909 - (graded_picks - wins)) / NULLIF(SUM(graded_picks), 0) * 100, 1) as roi
FROM nba_predictions.subset_grading_results
WHERE game_date >= '2025-11-02'
GROUP BY 1
ORDER BY season_hr DESC;
```

For retraining analysis, `season_walkforward.py` already answers "what cadence is optimal?"

**Pros:**
- Zero implementation work
- Uses real production data
- Immediate answers

**Cons:**
- Only works for current season (subsets didn't exist last season)
- Can't simulate "what if we had retrained differently?"
- Doesn't combine retraining + subset performance

**Effort:** ~30 minutes (just queries)

---

## Recommended Plan: Approach A + C Combined

### Phase 1: Query existing subset performance (30 min)
Run Approach C queries to see current season subset performance. This gives us immediate baseline numbers.

### Phase 2: Extend walkforward with subset simulation (2-3 hours)

Add to `season_walkforward.py`:

1. **Load subset definitions** from `dynamic_subset_definitions` table (or hardcode the key ones)

2. **After each cycle's predictions**, apply subset filters:
   ```python
   def apply_subset_filters(preds, lines, actuals, eval_df, subset_defs):
       """Apply each subset definition to cycle predictions.
       Returns dict of subset_id -> (picks, wins, losses, hr, pnl)."""
       results = {}
       for sdef in subset_defs:
           mask = np.abs(preds - lines) >= (sdef.get('min_edge') or 0)
           if sdef.get('direction') == 'OVER':
               mask &= (preds - lines) > 0
           elif sdef.get('direction') == 'UNDER':
               mask &= (preds - lines) < 0

           # Rank by |edge| descending, take top_n
           edges = np.abs(preds - lines)
           ranked = np.argsort(-edges[mask])
           top_n = sdef.get('top_n') or len(ranked)
           selected = ranked[:top_n]

           # Grade
           ...
       return results
   ```

3. **New output table**: per-subset per-cycle performance alongside the existing per-cycle output

4. **Cross-season comparison**: run for 2024-25 season too (feature store data goes back that far)

### Phase 3: Signal replay integration (future, optional)

Wire steering_replay into the walkforward so each cycle also runs signals. This is heavier and can wait.

---

## Data Availability

### Current Season (2025-26): Nov 2 → Present
- **Feature store (ml_feature_store_v2):** Full coverage
- **DraftKings lines (odds_api):** Full coverage
- **Actuals (player_game_summary):** Full coverage up to Feb 12 (All-Star break)
- **Subset picks (current_subset_picks):** Since subsets were created (~Dec 2025+)
- **Grading (subset_grading_results):** Same timeframe as subset picks

### Last Season (2024-25): Oct 22 → Apr 13
- **Feature store:** Should have coverage (check with query below)
- **DraftKings lines:** Should have coverage
- **Actuals:** Full coverage
- **Subset picks:** Does NOT exist (system wasn't built)
- **Grading:** Does NOT exist

```sql
-- Check last season feature store coverage
SELECT
  MIN(game_date) as earliest,
  MAX(game_date) as latest,
  COUNT(DISTINCT game_date) as game_days,
  COUNT(*) as total_records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13';
```

---

## Subset Definitions to Simulate

For the walkforward extension, simulate these key subsets (subset of 35):

| Subset | Definition | Why |
|--------|-----------|-----|
| `top_pick` | Top 1 by edge, edge >= 3 | Highest conviction |
| `top_3` | Top 3 by edge, edge >= 3 | Core portfolio |
| `top_5` | Top 5 by edge, edge >= 3 | Diversified portfolio |
| `high_edge_over` | Edge >= 5, OVER only | Direction specialist |
| `high_edge_all` | Edge >= 5, any direction | High conviction both ways |
| `ultra_high_edge` | Edge >= 7 | Max edge threshold |
| All UNDER subsets | Edge >= 3, UNDER only | Quantile model strength |

Cross-model subsets can't be simulated in walkforward (only one model per cycle), but per-model subsets cover the most important dimension.

---

## Expected Output

After extending walkforward:

```
===========================================
STRATEGY: expand_14d (with subsets)
===========================================

CYCLE 1: train 2025-11-02→2025-11-29 | eval 2025-11-30→2025-12-13
  Raw edge 3+: 47 picks, 68.8% HR, $+1,280
  Subsets:
    top_pick:        13/14d, 78.6% HR, $+580
    top_3:           38/42, 71.4% HR, $+1,240
    top_5:           52/56, 67.9% HR, $+1,320
    high_edge_over:  18/20, 72.0% HR, $+640
    ultra_high_edge: 8/8, 87.5% HR, $+700

CYCLE 2: train 2025-11-02→2025-12-13 | eval 2025-12-14→2025-12-27
  ...

SEASON SUMMARY:
  Subset     | Season HR | Season P&L | ROI   | Game Days
  -----------|-----------|------------|-------|-----------
  top_pick   | 66.2%     | $+3,200    | 28.5% | 65
  top_3      | 62.4%     | $+7,800    | 24.1% | 65
  top_5      | 59.8%     | $+8,200    | 18.3% | 65
  ...
```

This would validate whether our subset definitions are genuinely adding value beyond raw edge filtering, and whether biweekly retraining preserves or improves subset performance.

---

## Decision Points

Before implementing, confirm:

1. **Start with Approach C (queries)?** Can run immediately.
2. **Extend walkforward (Approach A)?** ~2-3 hour implementation.
3. **Run for last season too?** Depends on feature store coverage.
4. **Which subsets to simulate?** Top 7-10 most important, or all 35?

---

## Commands to Run Right Now (Approach C)

```bash
# 1. Current season subset performance
/subset-performance

# 2. Walkforward with 14-day cadence (already works)
PYTHONPATH=. python ml/experiments/season_walkforward.py \
    --season-start 2025-11-02 --season-end 2026-02-12 \
    --cadences 14 --window-type expanding

# 3. Steering replay (signals + aggregator)
PYTHONPATH=. python ml/analysis/steering_replay.py \
    --start 2025-12-01 --end 2026-02-12

# 4. Check last season data availability
bq query --use_legacy_sql=false "
SELECT MIN(game_date), MAX(game_date), COUNT(DISTINCT game_date), COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'
"
```
