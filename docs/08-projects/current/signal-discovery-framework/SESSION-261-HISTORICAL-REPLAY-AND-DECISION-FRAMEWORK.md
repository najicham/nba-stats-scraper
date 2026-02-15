# Session 261: Historical Replay Analysis & Decision Framework

**Date:** 2026-02-15
**Status:** Analysis complete, framework designed, automation plan drafted
**Scope:** Season-long replay, model lifecycle management, signal effectiveness analysis

---

## Executive Summary

We replayed the entire prediction history across all models to answer: **"How should we have managed model selection, decay detection, and signal usage?"** The findings fundamentally reshape how we operate.

### Key Conclusions

1. **Model decay is predictable.** The champion (catboost_v9) showed a steady 20-day decline from 77.4% to 42.3% HR. A simple 7-day rolling alert at 55% would have given 4-5 days of lead time before the breakeven crash.

2. **Signals amplify, they don't generate.** Every signal crashed the same week the model crashed. `high_edge` went from 84.6% to 22.1%. Signals concentrate bets on model-confident picks — which is great when the model is right and catastrophic when it's decaying.

3. **We lost ~13 days of value** between when decay was detectable (Jan 28) and when it was manually flagged. This is the gap automated monitoring closes.

4. **catboost_v12 is now driving best bets** (56.0% HR, N=50, +6.9% ROI). The decayed champion (40.6% HR, -22.4% ROI) has been replaced via `BEST_BETS_MODEL_ID` env var.

---

## Replay Results

### Model Performance Over Time

| Model | Period | Edge 3+ HR | Edge 3+ N | ROI | Notes |
|-------|--------|-----------|-----------|-----|-------|
| catboost_v8 | 4 seasons | 79.7% | 27,675 | +52.1% | All-time champion, $1.59M simulated P&L |
| v9_train1102_0108 | Jan 9-Feb 8 | 83.4% | 151 | +59.3% | Best V9 variant, very conservative |
| catboost_v9 | Jan 9-Feb 12 | 57.4% | 575 | +9.6% | Dragged down by decay |
| catboost_v12 | Feb 1-12 | 56.0% | 50 | +6.9% | New best bets model |
| Q45 | Feb 8-12 | 60.0% | 25 | +14.5% | Highest HR, thin sample |
| Q43 | Feb 8-12 | 54.1% | 37 | +3.2% | Above breakeven |
| v9_2026_02 | Feb 1-3 | 30.0% | 60 | -42.7% | Catastrophic retrain |

### Champion Decay Timeline

```
Jan 12: 77.4% ████████████████████████████████████████  Peak
Jan 15: 70.5% ████████████████████████████████████
Jan 19: 56.5% ████████████████████████████            First dip
Jan 25: 67.0% ██████████████████████████████████      Last good week
Jan 28: 59.2% █████████████████████████████           WATCH should fire
Feb  1: 57.3% ████████████████████████████            Last day above breakeven
Feb  2: 42.3% █████████████████████                   CRASH — 33 picks, 5 wins
Feb  6: 34.4% █████████████████                       Rock bottom
Feb 12: 47.4% ███████████████████████                 Slight recovery, still losing
```

### Best Model Each Week (Hindsight)

| Week | Best Model | Edge 3+ HR | Picks |
|------|-----------|-----------|-------|
| Jan 5 | v9_train1102_0108 | 90.0% | 10 |
| Jan 12 | v9_train1102_0108 | 83.8% | 80 |
| Jan 19 | ensemble_v1 | 100.0% | 7 |
| Jan 26 | v9_train1102_0108 | 85.0% | 20 |
| Feb 2 | Q43 | 66.7% | 6 |
| Feb 9 | zone_matchup_v1 | 77.8% | 18 |

### Signal Performance: Good Week vs Bad Week

During the peak week (Jan 12-18) vs the crash week (Feb 1-7):

| Signal | Good Week HR | Bad Week HR | Delta |
|--------|-------------|------------|-------|
| edge_spread_optimal | 92.3% | 16.7% | -75.6 |
| high_edge | 84.6% | 22.1% | -62.5 |
| prop_value_gap_extreme | 93.1% | 0.0% | -93.1 |
| minutes_surge | 61.9% | ~40% | -22 |
| cold_snap | varies | 25-80% | volatile |

**Conclusion:** Model-dependent signals (high_edge, edge_spread_optimal) are NOT independent alpha. They are amplifiers that concentrate exposure on the model's highest-confidence picks.

### Signal Health Backfill Confirms Decay Was Visible

| Date Range | COLD Signals | DEGRADING | Pattern |
|-----------|-------------|-----------|---------|
| Jan 9-18 | 0 | 0 | All healthy |
| Jan 19-22 | 2-4 | 0 | First COLD signals appear |
| Jan 27-Feb 2 | 7-14 | 4-8 | Peak distress |
| Feb 3-10 | 4-8 | 0-2 | Gradual recovery |

The signal health data showed distress **5 days before** the breakeven crash. Automated alerts on COLD signal count would have been early warning.

---

## Decision Framework

### What Gets Automated (No Human Required)

| System | Trigger | Action |
|--------|---------|--------|
| **model_performance_daily** table | After grading completes | Compute 7d/14d/30d rolling HR per model, write to BQ |
| **Decay WATCH alert** | 7d rolling HR < 58% for 2+ days | Slack alert to #nba-alerts |
| **Decay ALERT** | 7d rolling HR < 55% for 3+ days | Slack alert, mark model DEGRADING |
| **Decay BLOCK** | 7d rolling HR < 52.4% | Auto-block best bets for that model (produces 0 picks) |
| **Signal health regimes** | After grading | Compute HOT/NORMAL/COLD per signal, write to BQ |
| **Challenger comparison** | Daily | Compute all shadow model HRs, include in daily summary |
| **Combo registry refresh** | Weekly (Sunday) | Recompute combo hit rates from last 30 days |

### What Requires Human Decision

| Decision | System Provides | You Decide |
|----------|----------------|-----------|
| **Switch best bets model** | "V12 outperforming at 56% HR (N=50) vs champion 40%. Switch?" | Yes/No + which model |
| **Retrain trigger** | "Champion is 21 days stale, entering decay window" | When to retrain, training dates |
| **Promote shadow to champion** | "Q45 at 60% HR with 50+ graded edge 3+ picks" | Whether to promote |
| **Deploy retrained model** | "All governance gates passed" | Approve deployment |
| **Override auto-block** | "No models above breakeven. Best bets producing 0 picks." | Wait vs force-enable |
| **Adjust thresholds** | Monthly replay analysis results | New WATCH/ALERT/BLOCK levels |

### How the System Reports to You

1. **Daily Slack summary** (via `validate-daily`):
   - Model performance table (all active models, 7d/14d HR)
   - Best bets status (blocked/active, model driving, pick count)
   - Signal health summary (N COLD, N HOT)
   - Any action needed flag

2. **Alert-triggered Slack** (via Cloud Functions):
   - WATCH/ALERT/BLOCK state changes
   - Challenger-beats-champion notifications
   - Model staleness warnings (>21 days since training end date)

3. **Weekly email digest** (via pipeline-health-summary):
   - P&L summary for the week
   - Model comparison table
   - Combo performance changes
   - Recommended actions

---

## Replay Tool Design

### Purpose

A reusable tool to simulate historical decision-making: "If we had automated model switching with these thresholds, what would the P&L have been?"

### Python Scripts

```
ml/analysis/
├── replay_engine.py          # Core replay logic
├── replay_strategies.py      # Pluggable decision strategies
├── replay_visualizer.py      # Output formatting and charts
└── replay_cli.py             # CLI entry point
```

**`replay_engine.py`** — Core simulation:
- Input: date range, list of models, strategy parameters
- For each day: compute rolling metrics, apply strategy, select model, compute P&L
- Output: daily log of decisions + cumulative P&L

**`replay_strategies.py`** — Pluggable decision strategies:
- `ThresholdStrategy` — Switch when rolling HR crosses threshold
- `BestOfNStrategy` — Always use best model from last N days
- `HybridStrategy` — Threshold + minimum sample size
- `ConservativeStrategy` — Only switch after 3 consecutive days below threshold
- `OracleStrategy` — Perfect hindsight (upper bound on achievable P&L)

**`replay_cli.py`** — Entry point:
```bash
# Replay last 3 months with threshold strategy
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2025-11-01 --end 2026-02-14 \
    --models catboost_v9,catboost_v12,catboost_v9_q43,catboost_v9_q45 \
    --strategy threshold --watch-threshold 58 --block-threshold 52.4 \
    --min-sample 20

# Compare strategies
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2025-11-01 --end 2026-02-14 \
    --compare-strategies threshold,best_of_n,conservative
```

### Claude Skill: `/replay`

A Claude Code skill that wraps the replay tool:

```
/replay                          # Replay last 30 days with default strategy
/replay --season                 # Replay full season
/replay --compare               # Compare all strategies
/replay --investigate 2026-02-02 # Deep dive on a specific date
```

The skill would:
1. Run the Python replay CLI
2. Parse the output
3. Present findings in a readable summary
4. Suggest threshold adjustments if current settings would have lost money
5. Flag dates where human intervention would have been needed

### Running Against Past Seasons

V8 has 4+ seasons of data (27,675 edge 3+ picks). We can replay:
- **2021-22 season** — V8's first season, find optimal thresholds
- **2022-23 season** — Validate thresholds hold
- **2023-24 season** — Out-of-sample test
- **2025-26 season** — Current, with multi-model comparison

This gives us statistically robust threshold parameters calibrated across thousands of decisions.

---

## Subset Analysis Results

### Confidence Tier Performance (Edge 3+ Picks)

This answers the question: "Are we filtering by confidence the way we should be?"

| Model | Confidence Tier | Picks | HR | Finding |
|-------|----------------|------:|---:|---------|
| **catboost_v12** | 90+ | 38 | **60.5%** | Sweet spot |
| **catboost_v12** | 85-90 | 12 | **41.7%** | **DANGER ZONE** — same gap as V8 |
| catboost_v8 | 90+ | 1,271 | 71.9% | Best tier |
| catboost_v8 | 85-90 | 1,409 | 56.2% | Decent |
| catboost_v8 | 80-85 | 291 | 50.5% | Barely breakeven |
| catboost_v8 | 70-80 | 17 | 23.5% | Death zone |
| catboost_v9 | 85-90 | 371 | 59.3% | Best V9 tier |
| catboost_v9 | 80-85 | 93 | 58.1% | Also good |
| **catboost_v9** | **90+** | 108 | **51.9%** | **INVERTS** — overconfidence loses money |

**Critical findings:**
1. **V12 has the V8 85-90% gap.** The 85-90% confidence tier hits only 41.7% — well below breakeven. We MUST filter V12 best bets to 90+ confidence only, or exclude 85-90 explicitly.
2. **V9 inverts at 90+.** The champion's highest confidence picks (90+) actually perform WORSE (51.9%) than its 85-90% tier (59.3%). This is a sign of model overconfidence — possibly the root cause of the decay.
3. **V8's clean tier progression** (71.9% → 56.2% → 50.5% → 23.5%) is what a healthy model looks like. V12 and V9 both have anomalies.

### Over vs Under Direction

| Model | Direction | Picks | HR |
|-------|----------|------:|---:|
| **catboost_v12** | UNDER | 44 | **56.8%** |
| catboost_v12 | OVER | 6 | 50.0% |
| catboost_v9 | OVER | 169 | 53.8% |
| catboost_v9 | UNDER | 240 | 50.8% |

**V12 is primarily an UNDER model** (88% of its edge 3+ picks are UNDER). This is fine as long as there isn't a market-wide over-bias developing. V9 was more balanced but slightly better at OVER.

### Signal Performance: Good Week (Jan 12-18) vs Bad Week (Feb 1-7)

Actual BQ data with correct UNNEST on signal_tags array:

| Signal | Good Week HR | Bad Week HR | Delta | Type |
|--------|-------------|------------|------:|------|
| prop_value_gap_extreme | 93.1% (29) | 0.0% (7) | **-93.1** | Model-dependent |
| edge_spread_optimal | 83.3% (126) | 24.3% (111) | **-59.0** | Model-dependent |
| high_edge | 83.8% (222) | 27.5% (153) | **-56.3** | Model-dependent |
| combo_3way | 87.5% (16) | 75.0% (8) | -12.5 | Combo |
| blowout_recovery | 64.3% (84) | 56.9% (58) | -7.4 | Behavioral |
| minutes_surge | 54.4% (204) | **65.1%** (129) | **+10.7** | Behavioral |
| combo_he_ms | 70.6% (34) | **100%** (8) | +29.4 | Behavioral combo |
| 3pt_bounce | 66.7% (18) | **100%** (6) | +33.3 | Behavioral |
| cold_snap | — | **83.3%** (6) | — | Behavioral |

**This is the most important table in this document.**

The behavioral signals (minutes_surge, cold_snap, 3pt_bounce, combo_he_ms) **actually improved** during the crash week. The model-dependent signals (high_edge, edge_spread_optimal, prop_value_gap_extreme) catastrophically collapsed.

**Implication:** During model decay, we should have been using ONLY behavioral signals and EXCLUDING model-dependent signals. The current COLD weighting (0.5x) for model-dependent signals during decay is too generous — they should be fully excluded (0.0x).

---

## Lessons for Signal Management

### Signals That Work Independently of Model Health
- **cold_snap (home only)** — 93.3% HR, player-behavioral (not model-dependent)
- **3pt_bounce (guards + home)** — 69.0% HR, stat-pattern based
- **minutes_surge** — correlates with playing time, partially independent

### Signals That Are Pure Model Amplifiers
- **high_edge** — directly measures model confidence (model-dependent by definition)
- **edge_spread_optimal** — measures edge distribution (model-dependent)
- **prop_value_gap_extreme** — measures model vs vegas gap (model-dependent)

### Implication for Signal Strategy
When the model is decaying, model-dependent signals should be given LESS weight, not more. The current Session 260 health weighting (COLD = 0.5x) is directionally correct but may need to be more aggressive:
- Consider COLD model-dependent signals at 0.0x (fully excluded)
- Keep COLD player-behavioral signals at 0.5x (still have some independent value)

---

## Remaining Items

### Immediate (Before Feb 19 games resume)
- [ ] Clean up duplicate combo registry rows (14 rows → 7)
- [ ] Verify catboost_v12 predictions will be generated for Feb 19 games
- [ ] Confirm shadow models (Q43, Q45) are still running

### Phase 2 (Next 1-2 sessions)
- [ ] Build `model_performance_daily` BQ table
- [ ] Build automated decay detection Cloud Function
- [ ] Build Slack alerting for WATCH/ALERT/BLOCK
- [ ] Add `validate-daily` Phase 0.58 (model performance check)
- [ ] Build replay tool (Python scripts)

### Phase 3 (Following sessions)
- [ ] Build `/replay` Claude skill
- [ ] Run V8 multi-season replay to calibrate thresholds
- [ ] Weekly combo registry auto-refresh
- [ ] Challenger-beats-champion automated alerts
- [ ] Monthly retrain automation (with human approval gate)
