# Session 463 NBA Handoff — Signal Discovery + Retrain Infrastructure Fix

**Date:** 2026-03-10
**Focus:** P0/P1 simulator experiments, retrain scheduler creation, governance fix
**Previous:** Session 462 (BB simulator validated signals/filters)
**Algorithm:** `v463_ft_anomaly_slow_pace`

## What Changed

### New Shadow Signals (5-season cross-validated, accumulating BB data)
| Signal | HR | N | Mechanism |
|--------|-----|---|-----------|
| `ft_anomaly_under` | 63.3% | 278 | FTA CV >= 0.5 + FTA >= 5/game → scoring regression |
| `sharp_consensus_under` | 69.3% | 205 | BettingPros line dropped 0.5+ AND cross-book std >= 1.0 |
| `star_line_under` | 57.6% | 1,018 | Line >= 25, edge 3-7 → market overprices stars |
| `slow_pace_under` | 56.6% | 777 | Opponent pace <= 99 → fewer possessions |

### New Active Filters
| Filter | Blocked HR | N | Mechanism |
|--------|-----------|---|-----------|
| `ft_anomaly_over_block` | 37.5% | 56 | OVER when FTA CV >= 0.6 + FTA >= 5/game |
| `counter_market_under` | 43.2% | 447 | UNDER when line rose 0.5+ with book std >= 1.0 |

### Retrain Infrastructure Fixes
| Fix | Before | After |
|-----|--------|-------|
| Scheduler | NO scheduler job existed | `weekly-retrain-trigger` created (Mon 5 AM ET) |
| Governance gate | `min_n_graded = 50` (blocked ALL retrains) | `min_n_graded = 25` (matches quick_retrain.py) |
| Registration SQL | `model_sha256` (column doesn't exist) | `sha256_hash` (correct column name) |

### FTA Data Pipeline
- Added `fta_avg_last_10` and `fta_cv_last_10` window functions to `per_model_pipeline.py`
- Both legacy `supplemental_data.py` and per-model paths now have FTA data

## Experiment Results (5-Season Walk-Forward)

### Winners
| Signal | HR | N | Type |
|--------|-----|---|------|
| FT anomaly UNDER | 63.3% | 278 | Shadow signal |
| Sharp consensus UNDER | 69.3% | 205 | Shadow signal |
| Star line UNDER | 57.6% | 1,018 | Shadow signal |
| Slow pace UNDER | 56.6% | 777 | Shadow signal |
| FT anomaly OVER block | 37.5% CF | 56 | Active filter |
| Counter-market UNDER | 43.2% CF | 447 | Active filter |

### Dead Ends
| Hypothesis | Result | Why |
|-----------|--------|-----|
| Bounce-back AWAY OVER | 47-49% | Model already prices bounce-back |
| Bench pre-game proxy | 52.2% | No reliable proxy beats model |
| Scoring skew filter | <1pp spread | Not predictive at all |
| Minutes trend decline | Anti-signal | UNDER with declining minutes is WORSE |
| Usage crash UNDER | +0.7pp | Too weak for standalone signal |
| Sharp vs soft book gap | 0.009 pts avg | Books are too similar |
| Tight lines (all agree) | 50.7% | Below baseline |

## Performance Context

**Mar 7-9: 14-46 (23.3% HR) — catastrophic stretch.**
Root cause: model staleness (5-41 days) + algorithm version fragmentation.
Weekly-retrain scheduler was NEVER created. Fixed this session.

## Files Changed

| File | Changes |
|------|---------|
| `ml/signals/ft_anomaly_under.py` | NEW — FTA variance UNDER signal |
| `ml/signals/slow_pace_under.py` | NEW — opponent pace UNDER signal |
| `ml/signals/star_line_under.py` | NEW — star overpricing UNDER signal |
| `ml/signals/sharp_consensus_under.py` | NEW — line dropped + book disagreement |
| `ml/signals/registry.py` | +5 signal registrations (61 total) |
| `ml/signals/aggregator.py` | +5 shadow signals, +2 active filters |
| `ml/signals/per_model_pipeline.py` | FTA window functions + pred dict |
| `ml/signals/pipeline_merger.py` | Version bump to v463 |
| `ml/signals/pick_angle_builder.py` | +5 angle templates |
| `orchestration/cloud_functions/weekly_retrain/main.py` | N=50→25, sha256→sha256_hash |
| `tests/unit/signals/test_aggregator.py` | +2 filter keys (236 tests passing) |

## Monitoring

- **Day 1:** Verify v463 algorithm_version in tomorrow's picks
- **Day 1:** Check retrain CF logs — should succeed with sha256 fix + N=25 gate
- **Day 3:** Check `ft_anomaly_over_block` and `counter_market_under` fire rates
- **Day 7:** Query `signal_health_daily` for all 5 new shadow signals
- **Weekly:** Retrain should auto-fire every Monday 5 AM ET

## Next Steps

### P1: Retrain validation
- Confirm retrain succeeds after sha256 fix deploys
- If N=25 still blocks some families, extend eval window to 14 days

### P2: Signal graduation (7+ days)
- Monitor 5 new shadow signals for BB-level HR
- `sharp_consensus_under` (69.3% backtest) is highest priority for promotion
- Graduation: HR >= 60% + N >= 30

### P3: Remaining signal ideas
- Referee tendencies (Covers data exists, needs walk-forward integration)
- FanDuel line divergence (60.8% but needs per-book pipeline)
- Game total environment (needs historical O/U backfill)
