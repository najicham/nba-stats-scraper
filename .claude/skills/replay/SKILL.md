---
name: replay
description: Replay historical model performance and test decision strategies against real data
---

# Replay Skill

Simulate model selection strategies against historical prediction data. Shows what P&L, hit rate, and model switches would have occurred under different decision rules.

## Trigger
- User wants to replay/backtest model decisions
- "How would threshold strategy have performed?"
- "Compare strategies", "replay last month"
- "What if we had switched models earlier?"
- `/replay`

## What This Skill Does

1. Loads graded predictions from `prediction_accuracy` for a date range
2. Computes rolling 7d/14d/30d hit rates for each model
3. Applies a decision strategy (threshold, best-of-N, conservative, oracle)
4. Simulates daily P&L ($110 stake per bet, $100 win)
5. Reports decisions, switches, blocked days, and cumulative P&L

## How to Run

### Quick replay (last 30 days, default threshold strategy)

```bash
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start $(date -d '-30 days' +%Y-%m-%d) --end $(date -d '-1 day' +%Y-%m-%d) \
    --models catboost_v9,catboost_v12
```

### Compare all strategies side-by-side

```bash
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2025-11-15 --end 2026-02-12 \
    --models catboost_v9,catboost_v12 \
    --compare
```

### Full season replay

```bash
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2025-11-02 --end 2026-02-12 \
    --models catboost_v9,catboost_v12,catboost_v9_q43,catboost_v9_q45 \
    --strategy threshold \
    --verbose
```

### Custom thresholds

```bash
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2026-01-01 --end 2026-02-12 \
    --models catboost_v9,catboost_v12 \
    --strategy threshold \
    --watch 60 --alert 57 --block 54
```

### Save results to JSON

```bash
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2025-11-02 --end 2026-02-12 \
    --models catboost_v9,catboost_v12 \
    --compare \
    --output ./replay_results
```

## Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `threshold` | Block when champion HR drops below thresholds (58%/55%/52.4%). Switch to challengers when available. | Production use — primary recommended strategy |
| `best_of_n` | Always use the model with highest 7d rolling HR | Upper bound with perfect model selection |
| `conservative` | Only act after 5+ consecutive days below threshold | Reducing false positives from daily variance |
| `oracle` | Perfect hindsight — best model each day | Theoretical ceiling |

## Interpreting Results

### Key Metrics

- **Hit Rate**: Percentage of winning bets (need > 52.4% at -110 odds)
- **ROI**: Return on investment ((wins * $100 - losses * $110) / total_staked)
- **Blocked Days**: Days where all picks were withheld (model below breakeven)
- **Switches**: Number of times the active model changed

### What Good Looks Like

- Threshold strategy should **block** during decay periods (like Feb 1-7 crash)
- ROI should be positive (> 0%) — means the strategy made money
- Few switches (< 5 per month) — too many switches = overfitting to noise
- Hit rate > 55% on non-blocked days

### Decision Timeline Symbols

- `[+]` HEALTHY — model above all thresholds
- `[!]` WATCH — model below 58% for 2+ days
- `[!!]` DEGRADING — model below 55% for 3+ days
- `[X]` BLOCKED — model below 52.4% breakeven

## Model Performance Daily Table

The replay engine uses data from `prediction_accuracy`. For pre-computed daily metrics, query:

```sql
SELECT game_date, model_id, rolling_hr_7d, rolling_n_7d, state, action
FROM nba_predictions.model_performance_daily
WHERE game_date >= CURRENT_DATE() - 14
ORDER BY game_date DESC, model_id;
```

## Files

| File | Purpose |
|------|---------|
| `ml/analysis/replay_cli.py` | CLI entry point |
| `ml/analysis/replay_engine.py` | Core simulation engine |
| `ml/analysis/replay_strategies.py` | Pluggable decision strategies |
| `ml/analysis/model_performance.py` | Daily metrics compute + backfill |

---
*Created: Session 262*
*Part of: Signal Discovery Framework / Decision Automation*
