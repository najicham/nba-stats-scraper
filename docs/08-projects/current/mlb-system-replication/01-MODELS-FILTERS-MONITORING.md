# Models, Filters, Signals & Monitoring — Deep Dive

> **Purpose:** This document explains how the NBA system measures performance, discovers and validates filters/signals, trains and monitors models, and runs health checks. Written for a new chat building an equivalent MLB system.

---

## 1. How We Measure Hit Rate

### 1.1 The Core WIN/LOSS Determination

A prediction is graded by comparing the model's recommendation against the actual outcome:

```python
# From prediction_accuracy_processor.py
went_over = actual_points > line_value
recommended_over = recommendation == 'OVER'
return bool(went_over == recommended_over)
```

- **WIN:** Model said OVER and player scored above the line, OR model said UNDER and player scored below
- **LOSS:** The opposite
- **Push:** actual_points == line_value — excluded from grading (like sportsbook pushes)
- **Voided:** Player didn't play (DNP/injury) — excluded entirely, like sportsbook void

### 1.2 Edge: The Model's Conviction

Edge is how far the model's prediction deviates from the betting line:

```python
edge = predicted_points - betting_line
```

- **Positive edge** → OVER prediction (model thinks player scores more)
- **Negative edge** → UNDER prediction (model thinks player scores less)
- **Absolute edge** (`abs(edge)`) is used for threshold filtering

**Why edge >= 3 is the threshold:**

| Edge Range | Bets | Hit Rate | ROI | Verdict |
|:---:|:---:|:---:|:---:|:---|
| 0-2 | 754 (49%) | 51.1% | -2.5% | Losing — no better than chance |
| 2-3 | 375 (24%) | 50.9% | -2.8% | Losing |
| **3-5** | **265 (17%)** | **57.4%** | **+9.5%** | Winning |
| **5+** | **143 (9%)** | **79.0%** | **+50.9%** | Excellent |

Edge < 3 is coin-flip territory. Edge >= 3 is where the model actually has predictive power. We use 3 instead of 5 because edge 3-5 maximizes total profit ($97.9 units vs $72.7 for edge >= 5) while keeping ~17 bets/day.

### 1.3 The Breakeven Threshold: 52.4%

At standard -110 odds (risk $110 to win $100):

```
breakeven = 110 / (110 + 100) = 52.38% ≈ 52.4%
```

Any hit rate below 52.4% loses money over time. This is the single most important number in the system — every filter, signal, model gate, and decay threshold references it.

### 1.4 Hit Rate Computation

During training evaluation:

```python
def compute_hit_rate(preds, actuals, lines, min_edge=3.0):
    edges = preds - lines
    mask = np.abs(edges) >= min_edge
    wins = ((actuals[mask] > lines[mask]) & (edges[mask] > 0)) |
           ((actuals[mask] < lines[mask]) & (edges[mask] < 0))
    pushes = actuals[mask] == lines[mask]
    graded = len(actuals[mask]) - pushes.sum()
    return wins.sum() / graded * 100, graded
```

Three edge thresholds are always computed: edge 1+, edge 3+, edge 5+. The governance gates use **edge 3+** as the primary metric.

### 1.5 Directional Hit Rates

OVER and UNDER are measured separately because they have different failure modes:

```python
over_mask = mask & (edges > 0)   # Model predicted above line
under_mask = mask & (edges < 0)  # Model predicted below line
over_hr = (actuals[over_mask] > lines[over_mask]).mean()
under_hr = (actuals[under_mask] < lines[under_mask]).mean()
```

**Both OVER and UNDER must be >= 52.4%.** A model with 65% overall HR but 80% OVER / 40% UNDER is dangerous — it loses money on every UNDER bet. This is a governance gate.

### 1.6 Raw HR vs Best-Bets HR

Two different hit rates are tracked per model:

- **Raw HR:** Every edge 3+ prediction the model generates (from `prediction_accuracy`)
- **Best-Bets HR:** Only picks that survived the full filter stack (from `signal_best_bets_picks` joined to `prediction_accuracy`)

A model with poor raw HR (48%) can still contribute winning best bets picks if the filter stack correctly removes its bad predictions. **Best-bets HR is what matters for profitability.** Raw HR matters for model health monitoring and decay detection.

### 1.7 Rolling Windows

Model performance is tracked daily at three rolling windows:

| Window | Purpose |
|:---|:---|
| 7-day | Decay detection trigger (sensitive, catches fast drops) |
| 14-day | Primary evaluation window (balanced sensitivity vs stability) |
| 30-day | Trend confirmation (stable, less reactive) |

Each window also breaks down into OVER HR and UNDER HR. The decay state machine uses 7-day HR exclusively.

---

## 2. How We Discover and Validate Filters

### 2.1 The Discovery Process

Filters are discovered through a consistent cycle:

```
HYPOTHESIZE → QUERY → CROSS-VALIDATE → CHECK BEST-BETS IMPACT → IMPLEMENT → MONITOR
```

**Step 1: Hypothesize.** Research agents run parallel BQ queries across dimensions (direction, tier, opponent, line movement, etc.) looking for patterns where predictions systematically fail.

**Step 2: Query.** Test the hypothesis with BigQuery:

```sql
-- Example: "Do UNDER predictions against MIN lose?"
SELECT
  recommendation,
  opponent_team_abbr,
  COUNT(*) as n,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as hit_rate
FROM prediction_accuracy
WHERE ABS(predicted_points - line_value) >= 3
  AND game_date >= '2025-12-01'
  AND opponent_team_abbr = 'MIN'
GROUP BY 1, 2
```

**Step 3: Cross-validate independently.** This is critical. Session 372 caught 3 major errors in research agent findings:
- Wrong feature column (feature_36 is `breakout_flag`, not `days_rest`)
- Wrong team list (NOP was NOT in worst 15 opponents — research was wrong)
- Overstated HR (68.6% vs actual 54.8%)

**Never implement a filter based solely on research agent output without independent BQ validation.**

**Step 4: Check best-bets impact.** This is the step most people skip. A pattern with 48% raw HR might already be handled by existing filters — the picks never reach best bets. Always check:

```sql
-- Does the bad pattern actually reach best bets?
SELECT COUNT(*) as n,
  ROUND(AVG(CASE WHEN grade = 'WIN' THEN 1.0 ELSE 0.0 END) * 100, 1) as bb_hr
FROM signal_best_bets_picks
WHERE recommendation = 'UNDER'
  AND opponent_team_abbr = 'MIN'
  AND game_date >= '2025-12-01'
  AND grade IS NOT NULL
```

If N=5 and HR=60% in best bets — the filter stack already handles it. Don't add another filter.

### 2.2 Acceptance Criteria for Filters

| Criterion | Threshold | Rationale |
|:---|:---|:---|
| Blocked HR | < 45% | Must be substantially below 52.4% breakeven |
| Sample size | N >= 15 | Minimum statistical reliability |
| Feb resilience | Check both Jan and Feb | Feb has known structural degradation |
| Best-bets impact | Must reach best bets | No point blocking picks that don't survive existing filters |
| No profitable collateral | Must not block HR > 55% picks | Use counterfactual analysis |

### 2.3 Counterfactual Filter Audit

The `filter_health_audit.py` tool answers: **are our filters still blocking bad picks, or have they drifted to block good ones?**

For each filter, it:
1. Queries BQ for predictions that WOULD have been blocked
2. Computes their actual HR
3. Classifies: `OK` (blocked HR < 55%), `REVIEW` (blocked HR > 55% — investigate), `DRIFT` (HR diverged > 10pp from introduction time)

This is run periodically to ensure filters haven't gone stale. A filter introduced when UNDER + opponent MIL was 26.1% might become 55% as rosters change.

### 2.4 Filter Implementation Pattern

Every filter follows the same pattern in `aggregator.py`:

```python
# 1. Add counter to filter_counts dict (line ~162)
'your_new_filter': 0,

# 2. Add filter logic in order (cheapest checks first)
if (pred.get('recommendation') == 'UNDER'
        and pred.get('opponent_team_abbr', '') in TOXIC_OPPONENTS):
    filter_counts['opponent_under_block'] += 1
    continue

# 3. Bump ALGORITHM_VERSION
ALGORITHM_VERSION = 'v388_edge_tiered_sc4'

# 4. Add logging (at bottom)
if filter_counts['opponent_under_block'] > 0:
    logger.info(f"Opponent UNDER block: skipped {filter_counts['opponent_under_block']}")
```

---

## 3. How We Discover and Validate Signals

### 3.1 The Signal Discovery Process

Signals follow the same cycle as filters, but they ADD qualifying indicators rather than BLOCK bad picks.

**Step 1: Hypothesize.** "Pitchers facing a fast-pace opponent should have more strikeout opportunities" (MLB example).

**Step 2: Backtest with `signal_backtest.py`.** This harness:
- Loads graded predictions with supplemental data across 4 evaluation windows (W1-W4)
- Evaluates the signal against every prediction
- Computes per-signal HR, N, and ROI at -110 odds in each window
- Simulates the production aggregator to see best-bets-level impact

**Step 3: Multi-window validation.** A signal must work across time periods. If it's 80% in December but 40% in February, it's not a real signal — it's tracking a transient pattern (likely the same OVER collapse that affects everything in Feb).

**Step 4: Segment analysis.** Check if the signal works across player tiers (stars, starters, role players) or is confined to one segment.

### 3.2 Acceptance Criteria for Signals

| Criterion | Threshold | Rationale |
|:---|:---|:---|
| HR | > 52.4% (above breakeven) | Must be profitable |
| Typical target | 60%+ | Good signals are well above breakeven |
| Sample size | N >= 10 | Minimum for directional reliability |
| Multi-window stability | Check Dec, Jan, Feb | Feb is the stress test |
| Causal mechanism | Must have one | Correlation alone isn't enough |
| Best-bets level | Must improve filtered picks | Signal must add value on top of existing filters |

### 3.3 Signal Architecture

Every signal extends `BaseSignal`:

```python
class FastPaceOverSignal(BaseSignal):
    tag = "fast_pace_over"

    def evaluate(self, prediction, features, supplemental):
        if (prediction.get('recommendation') == 'OVER'
                and supplemental.get('opponent_pace', 0) >= 0.75):
            return SignalResult(qualifies=True, confidence=0.7, source_tag=self.tag)
        return self._no_qualify()
```

Signals are registered in `registry.py`, get supplemental data from `supplemental_data.py`, and have pick angle templates in `pick_angle_builder.py`.

### 3.4 How Signals Interact with the Filter Stack

Signals don't select picks — they filter and annotate:

1. Model generates predictions with edge values
2. Negative filters remove known-bad patterns (14+ filters)
3. **Signal count gate:** Remaining picks must have SC >= 4 (edge < 7) or SC >= 3 (edge >= 7)
4. Picks ranked by edge (model conviction), not signal score
5. Signal tags attached as pick angles (human-readable explanations)

The signal count gate is the key mechanism. A prediction can have high edge but if only 3 base signals fire (model_health, high_edge, edge_spread_optimal), it lacks confirmatory evidence. SC=3 at edge 5-7 = 51.3% HR. SC=4 at edge 5-7 = 70.6%. The additional signal is what separates marginal from profitable.

### 3.5 Dead Signals: The Graveyard

24 signals have been removed/disabled. Each is documented with:
- Session number when removed
- HR data that led to removal
- Why it failed

Examples:
- `b2b_fatigue_under` — 39.5% Feb HR, only 3 best bets picks total. The signal boosts a losing pattern.
- `prop_line_drop_over` — Conceptually backward. Line drops are BEARISH for OVER (39.1% HR). Replaced by `line_rising_over` (96.6% HR).
- `blowout_recovery` — 50% HR overall, 25% in Feb. No predictive value.

**The dead-end documentation is as valuable as the working signals.** It prevents revisiting approaches that already failed.

---

## 4. Why We Don't Use Different Filters on Different Models

### 4.1 The Temptation

With 15+ models in the fleet, it seems natural to have model-specific filters. V9 is an OVER specialist (63.9% HR), V12_noveg excels at UNDER. Why not filter each model differently?

### 4.2 The Investigation (Session 384-385)

We built the full infrastructure for per-model filtering:
- `model_profile.py` — Profiles each model across 6 dimensions (direction, tier, line_range, edge_band, home_away, signal)
- `model_profile_loader.py` — Loads profiles for aggregator use
- `model_profile_monitor.py` — Monitors dimension-level performance

Then tested 5 decision gates — **ALL returned NO-GO:**

**Q1: Signal effectiveness differs by model group?**
No signal met the >10pp gap threshold with N>=15 on both sides. The biggest gap (book_disagreement for v12_noveg at 14.3%) had only N=7.

**Q2: Would per-model AWAY blocking help?**
AWAY blocks would have removed PROFITABLE picks (66.7% HR, N=12). A filter that looks correct at raw prediction level destroys value in the filtered pipeline.

**Q3: Model × direction × tier interactions?**
V9 OVER starter was 45.5% (N=11) — only 0.5pp above the 45% threshold. Not actionable.

**Q4: Would swapping which model wins per-player help?**
Net swap benefit was ±1. Current model selection is already near-optimal.

**Q5: Star tier varies by model?**
Star UNDER is above breakeven for all models in all months (63.6% Jan, 55.6% Feb).

### 4.3 The Fundamental Insight

> "Within each affinity group, models make identical predictions on the same players."

Models in the same group (e.g., all V12_noveg variants) were trained on overlapping data with similar features. They make the same mistakes on the same players. Per-model filtering at the individual level (33+ models) is the wrong abstraction.

### 4.4 The One Exception: Affinity Groups

The system DOES use group-level direction blocking through 4 affinity groups:

| Group | Models | Known Weakness |
|:---|:---|:---|
| `v9` | All standard V9 models | UNDER 5+ = 30.7% HR (N=88) — catastrophic |
| `v9_low_vegas` | V9 with 0.25x vegas weight | Protected — 62.5% UNDER 5+ |
| `v12_noveg` | V12/V16/LightGBM/XGBoost noveg | AWAY = 43.8% HR (N=105) |
| `v12_vegas` | V12 with full vegas | No current blocks |

This works because groups represent genuinely different model architectures with distinct behavioral patterns. Within a group, models behave identically.

### 4.5 The Profile System Stays in Observation Mode

The per-model profiling infrastructure remains deployed but in observation mode. The aggregator logs `model_profile_would_block` without actually filtering. This lets us accumulate data and revisit the question when sample sizes grow.

---

## 5. How Often We Retrain Models (and How We Figured That Out)

### 5.1 The Season Replay Experiment (Sessions 280-283)

We built a full season replay simulator that trained all 6 model families at different cadences across two complete NBA seasons (2024-25 and 2025-26).

**Retrain cadence results:**

| Cadence | Combined P&L | vs 14-day baseline |
|:---:|:---:|:---:|
| 21-day | +$82,040 | **+$12,070 (+17.3%)** |
| 10-day | +$77,850 | +$7,880 (+11.3%) |
| **7-day** | **+$77,640** | **+$7,670 (+11.0%)** |
| 14-day | +$69,970 | baseline |

**Training window results:**

| Window | Combined P&L | vs 56-day baseline |
|:---:|:---:|:---:|
| **42-day** | **+$75,340** | **+$5,370 (+7.7%)** |
| 56-day | +$69,970 | baseline |
| 70-day | +$68,880 | -$1,090 |
| 84-day | +$63,390 | -$6,580 |

**Key findings:**
- Shorter windows (fresher data) outperform longer windows
- 42 days is the sweet spot — enough data to train without diluting with stale patterns
- 7-day cadence captures roster changes, injury impacts, and schedule effects

### 5.2 The Sliding Window Validation (Session 369)

8 sliding windows (31-day each, shifting by 7 days) tested stability:

- W1-W6: Remarkably stable — 70.4-75.4% HR, StdDev 1.6pp
- W7-W8: Sharp cliff when evaluation enters pure February (known structural degradation)
- 10-seed stability test: 69.8% ± 2.5pp, all seeds above breakeven
- **Critical threshold: any config difference < 5pp is within noise**

### 5.3 The ~21-Day Shelf Life

Models degrade structurally over time due to:
- Roster changes (injuries, trades, rotations stabilizing)
- `usage_spike_score` drift (1.14 → 0.28 as rotations stabilize post-December)
- Opponent adjustment patterns

The decay detection system quantifies this with state machine thresholds:

| State | 7d HR Threshold | Consecutive Days |
|:---|:---:|:---:|
| HEALTHY | >= 58% | — |
| WATCH | < 58% | 2+ |
| DEGRADING | < 55% | 3+ |
| BLOCKED | < 52.4% | any |

### 5.4 Production Implementation

- **`bin/retrain.sh`:** Automated weekly retraining for all enabled model families. Database-driven (reads configs from registry). 42-day rolling window.
- **`retrain-reminder` Cloud Function:** Monday 9 AM ET. Checks per-family staleness. Urgency: ROUTINE (7-10d), OVERDUE (11-14d), URGENT (15+d). Slack + push notification.
- **Decay-gated promotion:** If champion is HEALTHY/WATCH → standard promotion. If DEGRADING/BLOCKED → urgent promotion (skip shadow period).

---

## 6. How We Keep Track of Signal Health

### 6.1 Signal Health Computation

**File:** `ml/signals/signal_health.py`

For each of the 21 active signals, the system computes rolling hit rates at 4 timeframes:

| Timeframe | Purpose |
|:---|:---|
| 7-day | Regime detection (recent performance) |
| 14-day | Short-term trend |
| 30-day | Medium-term baseline |
| Season | Long-term baseline for divergence |

**Regime classification** is based on 7d-vs-season divergence:
- **HOT:** 7d HR is 10+ pp ABOVE season HR
- **NORMAL:** Within ±10pp of season HR
- **COLD:** 7d HR is 10+ pp BELOW season HR

**Status assignment:**
- `DEGRADING`: Signal is COLD AND model-dependent (its HR tracks model quality)
- `WATCH`: 7d divergence < -5pp
- `HEALTHY`: Everything else

Written to `signal_health_daily` BigQuery table daily.

### 6.2 The Signal Firing Canary (Session 387)

**The problem it solves:** Two 80%+ HR signals (`line_rising_over` and `fast_pace_over`) died silently for weeks. Nobody noticed because:
- `line_rising_over` depended on a `prev_prop_lines` query that filtered by the champion model's system_id. When the champion was decommissioned, `prop_line_delta` went NULL → signal never fired.
- `fast_pace_over` had threshold of 102.0 but the feature is normalized 0-1 → mathematically impossible to fire.

**How the canary works:**
- Compares 7-day firing count to prior 23-day baseline for each active signal
- Classification:
  - `DEAD`: 0 fires in 7d, was active in prior 23d
  - `DEGRADING`: >70% drop from baseline
  - `NEVER_FIRED`: 0 fires in entire 30d window
  - `HEALTHY`: Normal firing rate
- Runs after each grading cycle (in `post_grading_export`)
- Sends Slack alert if any signal is DEAD or DEGRADING

### 6.3 Model-Dependent vs Independent Signals

4 signals are flagged as **model-dependent** (their HR tracks model quality):
- `high_edge`, `edge_spread_optimal`, `combo_he_ms`, `combo_3way`

When these go COLD, it indicates model degradation (not signal failure). The health system distinguishes this from independent signals going COLD (which indicates the signal's underlying pattern has changed).

---

## 7. What Health Checks Run Regularly

### 7.1 The Complete Schedule

| Time (ET) | Check | What It Does | Alert Channel |
|:---|:---|:---|:---|
| 6:00 AM | Pipeline reconciliation | 7 cross-phase consistency checks | `#nba-alerts` |
| 7:00 AM | Daily health summary | 11 check categories across full pipeline | `#daily-orchestration` |
| 8:00 AM | Daily health check | 8 categories including meta-monitoring | `#app-error-alerts` (critical) |
| 8:00 AM | Scraper availability | BDL, NBAC, OddsAPI data presence | `#nba-alerts` |
| 9:00 AM | Grading gap detector | < 80% grading completeness → auto-backfill | `#nba-alerts` |
| 9:00 AM Mon | Retrain reminder | Per-family model staleness | `#nba-alerts` + push |
| 9:00 AM Mon | Shadow performance report | Shadow model tier comparison | `#nba-alerts` |
| 11:00 AM | Decay detection | Model state machine transitions | `#nba-alerts` |
| 12:45 PM | Self-heal | Missing Phase 3 data or predictions → trigger healing | `#nba-alerts` |
| 7:00 PM | Prediction health alert | Fallback predictions, no actionable picks, feature issues | `#nba-alerts` |
| 7:00 PM | Data quality alerts | Zero predictions, low usage_rate, duplicates | `#nba-alerts` |
| Every 5 min (4 PM-1 AM) | Live freshness monitor | Live data staleness during games | `#nba-alerts` |
| Every 15 min (10 PM-3 AM) | Grading readiness | Triggers grading when all games complete | — |
| Every 15 min | Healing pattern analysis | Self-healing audit | — |
| Every 30 min | Pipeline canary queries | 12 canary checks across all 6 phases + auto-heal | `#canary-alerts` |
| Every 2 hours | Deployment drift alerter | Code committed but not deployed | `#deployment-alerts` |
| Hourly | Transition monitor | Stuck phase transitions | Email |
| Post-grading | Signal firing canary | Dead/degrading signal detection | `#nba-alerts` |
| Post-grading | Model performance daily | Populates decay detection data | — |
| Post-grading | Model profile daily | Per-model dimension profiling | — |

### 7.2 Meta-Monitoring (Monitoring the Monitors)

The daily health check (8 AM) explicitly monitors the monitoring infrastructure:

1. **`model_performance_daily` freshness** — If this table goes stale (>2 days), decay detection reads stale data and won't alert properly
2. **`signal_health_daily` freshness** — Same check for signal health data
3. **`decay-detection-daily` scheduler execution** — Verifies the Cloud Scheduler job ran within 25 hours
4. **Signal firing canary** (post-grading) — Detects signals that stopped firing due to external dependency changes

**Known gap:** BLOCKED models are NOT auto-disabled (requires manual intervention). This is documented in the fleet lifecycle automation plan.

### 7.3 Interactive Health Checks (Claude Code Skills)

Three skills provide interactive health assessment during sessions:

| Skill | Purpose |
|:---|:---|
| `/daily-steering` | Morning report: model health, signal health, best bets performance, ONE recommendation (ALL CLEAR / WATCH / SWITCH / RETRAIN / BLOCKED) |
| `/validate-daily` | Pipeline phase validation with remediation commands |
| `/reconcile-yesterday` | 10-phase reconciliation: who played vs who was predicted, cache miss rates, cross-model coverage |

### 7.4 Pre-Commit Prevention

17 pre-commit hooks prevent common mistakes before they reach production:

| Hook | Prevents |
|:---|:---|
| `validate-schema-fields` | BigQuery schema misalignment |
| `validate-deploy-safety` | `--set-env-vars` wipe (destroys all env vars) |
| `validate-model-references` | Hardcoded model system_ids |
| `validate-dockerfile-imports` | Missing COPY directories |
| `validate-python-syntax` | Syntax errors breaking Cloud Function deploys |
| `validate-pipeline-patterns` | Invalid enums, processor name gaps |

---

## 8. Governance Gates: The Six Checks Before Any Model Goes Live

Every trained model must pass all 6 gates before it can be registered (even as shadow):

| Gate | Threshold | What It Catches |
|:---|:---|:---|
| **Hit Rate (edge 3+)** | >= 60% | Overall prediction quality |
| **Sample Size** | >= 25 edge 3+ bets | Statistical reliability |
| **Vegas Bias** | within ±1.5 | Systematic over/under-prediction vs market |
| **Tier Bias** | no tier > ±5 pts | Per-tier calibration (stars, starters, role, bench) |
| **Directional Balance** | OVER >= 52.4% AND UNDER >= 52.4% | Prevents one-sided models |
| **MAE** (soft gate) | Reported only, does NOT block | Lower MAE ≠ better betting (4.12 MAE → 51.2% HR) |

**Why MAE was demoted from hard gate to soft gate:** Session 382c discovered a model with the best MAE ever (4.12) had HR of only 51.2%. It was biased toward UNDER predictions — excellent at predicting exact scores, terrible at predicting over/under outcomes. MAE measures point accuracy; hit rate measures betting profitability. **They are not correlated.**

### 8.1 The Dead Ends List

The CLAUDE.md file contains a massive dead-ends list — every experiment that failed, with session number, HR data, and reasoning. Key themes:

- **Adding features hurts:** V13, V15, V16, V17, V18 all performed worse than V12_noveg
- **Quantile regression is non-deterministic:** LightGBM Q55 swung 62% → 52% between runs
- **Two-stage pipelines create circular dependencies** at prediction time
- **Stacked residuals learn noise** (47.37% HR)
- **Direction-specific models don't work** (AUC = 0.507 = random)
- **Any config difference < 5pp is within noise** — the critical threshold for trusting model comparisons

**This documentation prevents wasting weeks revisiting failed approaches. Replicate it for MLB.**
