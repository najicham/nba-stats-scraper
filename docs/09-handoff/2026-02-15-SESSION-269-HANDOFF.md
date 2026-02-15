# Session 269 Handoff — Steering Replay System

**Date:** 2026-02-15
**Focus:** Built and ran the full steering replay backtester

---

## What Was Built

### `ml/analysis/steering_replay.py` (~420 lines)

A standalone backtesting script that replays the **complete** steering + signal pipeline as a unit. Unlike the existing replay engine (which sorts raw picks by edge), this runs:

1. Pre-computed model health lookup (from `model_performance_daily`)
2. Steering decision (champion/challenger/sit-out per playbook)
3. Signal evaluation (all 20+ signals with supplemental data)
4. Signal health weighting (HOT/COLD/NORMAL from `signal_health_daily`)
5. `BestBetsAggregator` top-5 scoring (combo registry, anti-pattern blocking)
6. Grading against actuals + P&L tracking

**CLI:**
```bash
# Full range
PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-09 --end 2026-02-12

# Verbose (pick-level detail)
PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-15 --end 2026-01-15 --verbose

# Force a model (ignore steering)
PYTHONPATH=. python ml/analysis/steering_replay.py --force-model catboost_v9

# Bypass health gate (counterfactual)
PYTHONPATH=. python ml/analysis/steering_replay.py --no-health-gate
```

---

## Replay Results (Jan 9 – Feb 12)

| Strategy | Picks | W-L | HR% | P&L | ROI |
|----------|-------|-----|-----|-----|-----|
| **Steering (production)** | 93 | 53-40 | 57.0% | **$+900** | +8.8% |
| **No health gate (V9)** | 165 | 96-69 | 58.2% | **$+2,010** | +11.1% |
| **V12 only** | 36 | 21-15 | 58.3% | **$+450** | +11.4% |

### Key Findings

1. **Signal system is profitable across all strategies** — 57-58% HR, above 52.4% breakeven
2. **Sitting out cost $1,110** — BLOCKED days in Feb had 62% HR when signal-filtered. The 2-signal minimum was already doing quality filtering; the model health gate was redundant
3. **Steering preserved capital as designed** — it's insurance. Can't know in real-time that blocked days would've been fine
4. **V12 too low-volume** — 36 picks in 35 days, not viable standalone
5. **The 80% days are real** — 7 days hit 4/5 or 5/5. Driven by high_edge + minutes_surge and blowout_recovery combos
6. **Best stretch:** Jan 10-13 (four straight 80% days, +$1,160)
7. **February decay period:** system sat out Jan 31–Feb 12 (13 days), preserving $800+ in gains

### Implication for Thursday (Feb 19)

The signal system works. The question is whether to:
- **Keep health gate** (conservative, safe, leaves ~$1K on table per month)
- **Relax health gate** (trust signals more, higher volume + P&L but more risk)

One middle ground: change from BLOCKED = sit out to BLOCKED = reduce to 3 picks (lower exposure, not zero).

---

## Files Changed

| File | Action |
|------|--------|
| `ml/analysis/steering_replay.py` | **CREATED** — full steering replay backtester |

## Files Reused (not modified)

| File | What |
|------|------|
| `ml/experiments/signal_backfill.py` | Query template (adapted with parameterized system_id) |
| `ml/signals/registry.py` | `build_default_registry()` |
| `ml/signals/aggregator.py` | `BestBetsAggregator` with signal_health + combo_registry |
| `ml/signals/combo_registry.py` | `load_combo_registry()` |
| `ml/analysis/model_performance.py` | Threshold constants |

---

## Verification

- Syntax + import checks pass
- 8 steering logic unit tests pass (all states + challenger thresholds)
- Grading math verified (W/L/PnL arithmetic)
- Full replay ran successfully (35 dates, ~40s total)

---

## Next Steps

1. **Decision: Health gate policy for Feb 19** — keep strict, relax, or middle-ground?
2. **Run replay again after Feb 19-21** (first 3 game days) to see if the system performs out-of-sample
3. **Consider adding `--compare` mode** to print the steering vs no-gate table side-by-side
4. **Potential: expose steering replay as a skill** (`/steering-replay`) for quick daily checks
