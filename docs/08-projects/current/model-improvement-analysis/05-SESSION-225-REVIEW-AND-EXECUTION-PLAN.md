# Session 225 Review & Execution Plan

**Date:** 2026-02-12
**Session:** 225
**Status:** Final review complete, execution plan ready
**Inputs:** Docs 01-04 + Session 224 handoff

---

## Part 1: Final Review — Gaps, Contradictions, Corrections

### 1.1 CORRECTED: Feature Index Situation

The documents appeared to disagree, but after checking:

| Document | V10 Feature Count | New Features Start At |
|----------|------------------|-----------------------|
| Doc 02 (Master Plan) | **37** (indices 0-36) | Index 37 |
| Doc 01 (Analysis) | **39** (indices 0-38) | Index 39 |
| Doc 03 (Features Deep Dive) | **37** (indices 0-36) | Index 37 |
| **feature_contract.py V10_CONTRACT** | **37** (indices 0-36) | — |
| **feature_contract.py FEATURE_STORE** | **39** (indices 0-38) | — |

**Resolution:** The feature store has 39 features, but `V10_CONTRACT` in `feature_contract.py` explicitly defines V10 as 37 features (0-36). Indices 37 (`breakout_risk_score`) and 38 (`composite_breakout_signal`) exist in the store but are NOT part of the V10 contract. Docs 02 and 03 are **correct** — V10 = 37 features. New features start at index 37.

**Doc 01 is the outlier** with its claim of V10 = 39 features. The V10_FEATURE_NAMES list adds only `dnp_rate`, `pts_slope_10g`, `pts_vs_season_zscore`, `breakout_flag` (33-36) to V9's 33.

**Note:** Indices 37-38 (breakout features) could optionally be included. AUC for breakout classifier is 0.57 (weak) — likely not worth including until improved.

### 1.2 CRITICAL: Feature Slicing Implementation Is Wrong in Docs

Docs 02 and 03 describe this code change for V10 activation:

```python
# Docs say to change:
X_train = np.array([row[:33] for row in features])
# To:
X_train = np.array([row[:37] for row in features])
```

**ACTUAL:** `quick_retrain.py` switched to **name-based extraction** in Session 107. There is no position slicing. The current code uses `V9_FEATURE_NAMES` (33 feature names from the V9 contract).

**Fix needed:** To activate V10 features, we need to update the feature name list used by `quick_retrain.py`, NOT change array slicing. Add a `--feature-set` argument (`v9`=33 features, `v10`=37 features) that maps to the V9/V10 `FEATURE_NAMES` lists already defined in `feature_contract.py`. The V10_FEATURE_NAMES already exists with 37 features — just need to wire it up.

### 1.3 BLOCKING: Missing CLI Parameters

Three parameters referenced in the master plan **do not exist** in `quick_retrain.py`:

| Parameter | Used In | Status | Blocking? |
|-----------|---------|--------|-----------|
| `--feature-count` | Wave 3 (V10) | NOT IMPLEMENTED | Blocks Wave 3 |
| `--monotone-constraints` | Wave 8a | NOT IMPLEMENTED | Blocks Wave 8a |
| `--feature-interaction-constraints` | Wave 8e | NOT IMPLEMENTED | Blocks Wave 8e |

**Impact:** Waves 0-2 can proceed immediately (zero code changes). Wave 3 needs a small code change to `quick_retrain.py`. Wave 8 needs additional parameter support.

### 1.4 Hit Rate Discrepancy

Doc 01 says champion edge 3+ HR is **39.9%**. Doc 02 says **38.0%**. Different computation windows. Use **38.0%** as the canonical February figure (192 picks, more recent).

### 1.5 Priority Order Assessment

The revised priority order (post-review) is **mostly sound** with one adjustment:

**Agree:**
- Priority 1 (direction filter) — correct, immediate triage, zero risk
- Priority 2 (CLV tracking) — correct, diagnostic, determines if edge ever existed
- Priority 3-4 (line shopping, pick limits) — correct, zero-model improvements

**Disagree:**
- **Multi-season training is too low at priority 8.** It requires ZERO code changes and tests the single biggest untested variable (11% data utilization). Move to **priority 5**, alongside V10 activation.
- **Alpha fine-tuning should be eliminated entirely**, not just deprioritized. The reviewers are right that Q42 vs Q43 is noise at these sample sizes.

**Recommended priority reorder:**

| # | Action | Type | Rationale |
|---|--------|------|-----------|
| 1 | Wave 0 SQL analyses + direction filter | SQL | Free, immediate |
| 2 | CLV tracking | SQL | Diagnostic — determines strategy |
| 3 | Line shopping analysis + per-game limits | SQL | Free improvements |
| 4 | Multi-season training (Wave 1, 5 experiments) | Training | Zero code changes, biggest untested variable |
| 5 | V10 activation (Wave 3) | 1 code change | Unlocks features 33-38 |
| 6 | Monotonic constraints | 1 code change | Prevents overfitting structurally |
| 7 | star_teammates_out + game_total_line extraction | Feature eng. | Addresses root failure mode |
| 8 | Multi-quantile ensemble (Q30/Q43/Q57) | Train 3 models | Confidence scoring |
| 9 | New features (shooting, context, profile) | Feature eng. | Incremental signal |
| 10 | Calibration (Platt/isotonic) | Post-processing | Better thresholds |
| 11 | Late injury cascade trigger | New trigger | Highest-alpha opportunity |
| 12 | Referee features | New processor | Medium effort, unknown signal |

### 1.6 Experiments to Cut

| Cut | Reason | Savings |
|-----|--------|---------|
| Wave 2 entirely (4 alpha sweep experiments) | Alpha ±0.01 is noise at these sample sizes. Q43 is proven. | 4 experiments, 1 session |
| Wave 1 experiments 1a, 1d, 1h | 1a (60d) is between 14d and 120d; 1d (240d) is too gentle; 1h combines too many variables | 3 experiments |
| Experiment 5d (Seasonal Cycle) | Acknowledged duplicate of 1c in the doc itself | 1 experiment |
| Player Archetype Clustering (Doc 01 Exp 6) | High effort, fragile K-means, uncertain value. Use simpler features instead. | 2-3 sessions |
| Per-Player Calibration (Doc 01 Exp 7) | Reviewers correctly flagged as lagging indicator. Feature-based fixes better. Defer to Wave 7 post-processing. | 1-2 sessions |

**Net result:** ~56 experiments → ~44 experiments. Saves 3-4 sessions.

### 1.7 Governance Gate Assessment

The tiered gate system replacing the 60% absolute threshold is **statistically sound**.

**Specific feedback:**

| Gate | Assessment |
|------|-----------|
| Gate 1: HR > 52.4% on 100+ picks | GOOD — appropriate minimum |
| Gate 2: Bayesian P(true HR > 52.4%) > 0.90 | GOOD — but note: the code uses `beta.cdf()` (Bayesian credible interval), not Wilson CI (frequentist). Both valid. Pick one term and be consistent. |
| Gate 3: New > champion + 5pp | TOO LOW — champion is at 38%. A 43% model "passes" but is barely above breakeven. Recommend **+8pp AND > 52.4%** |
| Gate 4: No week below 45% | TOO STRICT — with 15-20 picks/week, a single bad week at 44% blocks a 56% overall model. Recommend **no week below 40% with 10+ picks** |
| Gate 5: 30+ edge 3+ picks/week | REASONABLE for commercial viability |

**Missing gate:** Factor in the **backtest-production gap** (5-10pp per reviewer estimates). A model hitting 55% in backtest may only achieve 45-50% live. Consider adding Gate 6: "walkforward HR on most recent eval week > 52.4%" (most recent = closest to production conditions).

**Implementation:** Update governance gates in `quick_retrain.py` lines 1451-1475. The Bayesian formula is correct:
```python
from scipy.stats import beta
p_above_breakeven = 1 - beta.cdf(0.524, wins + 1, losses + 1)
promote = p_above_breakeven > 0.90
```

### 1.8 Expert Reviewer Pushbacks

**Mostly correct. Two areas of pushback:**

1. **"71.2% was probably noise" is too pessimistic.** With 254/392 correct picks (64.8% HR), the Wilson CI lower bound at 90% is ~60.3%. The staleness exploitation pattern (peak at 2-3 weeks) was consistent across 4 weeks. Realistic target is **58-63% with proper staleness management**, not 55-58%. However, 55-58% is the right target for a *fresh* model.

2. **"Alpha fine-tuning is curve-fitting" is correct AND sufficient.** The reviewers correctly identified this. Cut the entire Wave 2 and use Q43 as the fixed alpha going forward. The difference between Q42 and Q43 on 50-100 picks is within the margin of error.

**Reviewers got right:**
- Direction filter first (unanimous)
- CLV tracking is the most important analytical gap
- Line shopping is free edge
- Per-player calibration is a lagging indicator
- 32+ experiments with 4-day eval = p-hacking risk
- Per-game pick limits reduce correlated variance

**Reviewers potentially wrong about:**
- Referee features being "overhyped" — 5-10 pts game-level does translate to ~0.3 pts/player on average, but the value is at the extremes (specific crews 10+ points off baseline). Worth testing but correctly deprioritized.

### 1.9 Missing From the Plan

1. **No weekly retrain automation.** If the winning strategy requires freshness (retrain every 2-3 weeks), manual retraining is unsustainable. Need a scheduled retrain pipeline. (Not urgent — address after finding a viable model.)

2. **No A/B testing infrastructure for post-processing filters.** Direction filter, pick limits, line shopping all need shadow testing before production. Current shadow model infrastructure only handles full models, not filter stacks.

3. **The backtest-production gap isn't operationalized.** "Backtests overstate by 5-10pp" is stated but not factored into any decision criterion. All gates should target 60%+ backtest if expecting 52.4%+ in production.

4. **No plan for the `/model-experiment` skill to handle new parameters.** The skill wraps `quick_retrain.py` — any new argparse params also need the skill prompt updated.

---

### 1.10 CRITICAL: Schema Verification Results (Session 225 Discovery)

All SQL queries in Docs 01-02 use **wrong column names** for `prediction_accuracy`. These queries were written in Sessions 222-224 (planning only, never run). The column mapping is documented in Session A Step 1 below.

Additionally verified:
- `nba_raw.odds_api_player_points_props` — EXISTS. Uses `bookmaker` (not `bookmaker_key`), `points_line` (not `outcome_point`). Has `snapshot_timestamp`, `player_lookup`.
- `nba_raw.odds_api_game_lines` — EXISTS. All expected columns correct (`game_id`, `market_key`, `outcome_name`, `outcome_point`, `bookmaker_key`, `snapshot_timestamp`).

### 1.11 Multi-Season Training: Verified Feasible

Confirmed via code analysis:
- **No date limits** in `quick_retrain.py` or `training_data_loader.py`. Dec 2023 start date is supported.
- **Recency weighting** applies exponential decay to CatBoost `sample_weight` (not row filtering). Old data is kept but downweighted.
- **`--force`** only bypasses duplicate date check. All quality gates still enforced.
- **Walkforward** evaluates the specified eval period in weekly chunks. Training and eval are separate ranges (enforced by date overlap guard).
- **No max data size limit**. CatBoost handles 50K+ rows easily.
- **Minimum requirements:** 1,000 training rows, 100 eval rows.

---

## Part 2: Concrete Session-by-Session Execution Plan

### Session A: Pattern Mining + Quick Validations (SQL Only)

**Goal:** Run zero-cost analyses that inform all subsequent decisions.
**Time:** ~1 hour
**Code changes:** None
**Parallelism:** All queries can run simultaneously in separate bq shells

### IMPORTANT: Column Name Mapping

The `prediction_accuracy` table uses different column names than the original planning docs assumed:

| Plan Assumed | Actual Column | Notes |
|-------------|--------------|-------|
| `edge` | **Does not exist** | Compute: `ABS(predicted_margin)` |
| `predicted_direction` | `recommendation` | STRING: OVER/UNDER |
| `vegas_line` | `line_value` | NUMERIC(5,1) |
| `is_correct` | `prediction_correct` | BOOL |
| `game_date` | `game_date` | Correct |
| `system_id` | `system_id` | Correct |
| `player_lookup` | `player_lookup` | Correct |
| `game_id` | `game_id` | Correct |

Also available: `predicted_points`, `actual_points`, `predicted_margin`, `absolute_error`, `signed_error`, `confidence_score`, `line_source`, `line_bookmaker`, `team_abbr`, `opponent_team_abbr`, `minutes_played`.

All queries below use the **correct** column names.

**Pre-flight check:** Before running queries, verify `recommendation` column values:
```bash
bq query --use_legacy_sql=false '
SELECT DISTINCT recommendation, COUNT(*)
FROM nba_predictions.prediction_accuracy
WHERE system_id = "catboost_v9" AND game_date >= "2026-02-01"
GROUP BY 1'
```
If values are not "OVER"/"UNDER" (e.g., "over"/"under" lowercase), adjust all queries.

#### Step 1: Wave 0 SQL Analyses (5 queries)

Run all 5 in parallel:

```bash
# 0a: UNDER collapse — monthly breakdown by direction
bq query --use_legacy_sql=false '
SELECT
  FORMAT_DATE("%Y-%m", game_date) as month,
  recommendation,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE ABS(predicted_margin) >= 3 AND system_id = "catboost_v9"
GROUP BY 1, 2
ORDER BY 1, 2'
```

```bash
# 0b: Trade deadline impact
bq query --use_legacy_sql=false '
SELECT
  CASE
    WHEN game_date BETWEEN "2026-02-01" AND "2026-02-08" THEN "Trade window"
    WHEN game_date BETWEEN "2026-02-09" AND "2026-02-12" THEN "Post-trade"
    ELSE "Normal"
  END as period,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE ABS(predicted_margin) >= 3 AND system_id = "catboost_v9" AND game_date >= "2026-01-15"
GROUP BY 1'
```

```bash
# 0c: Role player UNDER disaster zone
bq query --use_legacy_sql=false '
SELECT
  FORMAT_DATE("%Y-%m", game_date) as month,
  COUNT(*) as role_under_picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE ABS(predicted_margin) >= 3
  AND recommendation = "UNDER"
  AND line_value BETWEEN 5 AND 14
  AND system_id = "catboost_v9"
GROUP BY 1 ORDER BY 1'
```

```bash
# 0d: Direction filter simulation — all models, February
bq query --use_legacy_sql=false '
SELECT
  system_id,
  COUNT(*) as total_e3,
  COUNTIF(NOT (recommendation = "UNDER" AND line_value BETWEEN 5 AND 14)) as filtered_picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as original_hr,
  ROUND(100.0 * COUNTIF(prediction_correct AND NOT (recommendation = "UNDER" AND line_value BETWEEN 5 AND 14)) /
    NULLIF(COUNTIF(NOT (recommendation = "UNDER" AND line_value BETWEEN 5 AND 14)), 0), 1) as filtered_hr
FROM nba_predictions.prediction_accuracy
WHERE ABS(predicted_margin) >= 3 AND game_date >= "2026-02-01"
GROUP BY 1
ORDER BY filtered_hr DESC'
```

```bash
# 0e: Ensemble simulation (champion OVER + Q43 UNDER)
bq query --use_legacy_sql=false '
SELECT "Champion OVER" as source, COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE system_id = "catboost_v9" AND ABS(predicted_margin) >= 3
  AND recommendation = "OVER" AND game_date >= "2026-02-01"
UNION ALL
SELECT "Q43 UNDER", COUNT(*), ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1)
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE "%q43%" AND ABS(predicted_margin) >= 3
  AND recommendation = "UNDER" AND game_date >= "2026-02-01"
UNION ALL
SELECT "Champion Star OVER (25+)", COUNT(*), ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1)
FROM nba_predictions.prediction_accuracy
WHERE system_id = "catboost_v9" AND ABS(predicted_margin) >= 3
  AND recommendation = "OVER" AND line_value >= 25 AND game_date >= "2026-02-01"'
```

#### Step 2: CLV Tracking (Priority 2 — Diagnostic)

```bash
# CLV analysis: Did we ever have real edge?
bq query --use_legacy_sql=false '
WITH predictions AS (
  SELECT pa.player_lookup, pa.game_date, pa.recommendation,
    pa.line_value as bet_line, ABS(pa.predicted_margin) as edge, pa.prediction_correct
  FROM nba_predictions.prediction_accuracy pa
  WHERE ABS(pa.predicted_margin) >= 3 AND pa.system_id = "catboost_v9"
    AND pa.game_date >= "2026-01-01"
),
closing AS (
  SELECT player_lookup, game_date, points_line as closing_line
  FROM (
    SELECT player_lookup, game_date, points_line,
      ROW_NUMBER() OVER (PARTITION BY player_lookup, game_date ORDER BY snapshot_timestamp DESC) as rn
    FROM nba_raw.odds_api_player_points_props
    WHERE bookmaker = "draftkings" AND game_date >= "2026-01-01"
  ) WHERE rn = 1
)
SELECT
  FORMAT_DATE("%Y-%m", p.game_date) as month,
  COUNT(*) as picks,
  ROUND(AVG(CASE
    WHEN p.recommendation = "UNDER" THEN p.bet_line - c.closing_line
    ELSE c.closing_line - p.bet_line
  END), 2) as avg_clv_points,
  COUNTIF(CASE
    WHEN p.recommendation = "UNDER" THEN p.bet_line > c.closing_line
    ELSE c.closing_line > p.bet_line
  END) as positive_clv_count,
  ROUND(100.0 * COUNTIF(p.prediction_correct) / COUNT(*), 1) as hr
FROM predictions p
LEFT JOIN closing c USING (player_lookup, game_date)
WHERE c.closing_line IS NOT NULL
GROUP BY 1 ORDER BY 1'
```

**Decision tree after CLV:**
- **If CLV positive in January, negative in February** → Real edge that decayed. Freshness-based strategy is correct. Proceed with multi-season experiments.
- **If CLV negative in BOTH months** → Model never had real edge, 71.2% was variance. Fundamental rethink needed — focus entirely on post-processing filters and new signal sources.
- **If CLV positive in both** → Model has edge but direction/pick-selection is the problem. Focus on filtering.

#### Step 3: Per-Game Correlation Analysis

```bash
# Same-game pick clusters and their HR
bq query --use_legacy_sql=false '
SELECT
  game_id,
  recommendation,
  COUNT(*) as picks_on_game,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE ABS(predicted_margin) >= 3 AND game_date >= "2026-01-15" AND system_id = "catboost_v9"
GROUP BY 1, 2
HAVING COUNT(*) >= 3
ORDER BY picks_on_game DESC
LIMIT 30'
```

#### Step 4: Dynamic Edge Threshold Analysis

```bash
# HR by model age (weeks since training) and edge level
bq query --use_legacy_sql=false '
SELECT
  CASE
    WHEN DATE_DIFF(game_date, DATE("2026-01-08"), DAY) BETWEEN 0 AND 14 THEN "Week 1-2"
    WHEN DATE_DIFF(game_date, DATE("2026-01-08"), DAY) BETWEEN 15 AND 21 THEN "Week 3"
    WHEN DATE_DIFF(game_date, DATE("2026-01-08"), DAY) BETWEEN 22 AND 28 THEN "Week 4"
    ELSE "Week 5+"
  END as model_age,
  CAST(FLOOR(ABS(predicted_margin)) AS INT64) as edge_floor,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE system_id = "catboost_v9" AND ABS(predicted_margin) >= 3
GROUP BY 1, 2
ORDER BY 1, 2'
```

#### Session A Decision Gate

After all SQL queries complete, evaluate:

| Result | Next Action |
|--------|------------|
| Direction filter lifts HR > 52.4% | **Implement production post-processor immediately** (priority, can be done within Session A) |
| CLV positive in Jan, negative in Feb | Proceed to Session B (multi-season training). Staleness hypothesis confirmed. |
| CLV negative in both months | **PAUSE.** Pivot to post-processing stack (Wave 7) and new features. Skip model retraining. |
| Per-game limits help | Add to post-processing stack |
| Dynamic edge threshold helps | Add to post-processing stack |

---

### Session B: Multi-Season Training Matrix (Wave 1 — Trimmed)

**Goal:** Test whether more training data improves Q43 model performance.
**Time:** ~2-3 hours (experiments run in parallel, ~30 min each)
**Code changes:** None
**Prerequisites:** Session A SQL results reviewed

#### 5 Experiments (trimmed from 8)

Run all 5 in parallel via `/model-experiment`:

```bash
# 1b: 2 seasons, Q43, 120-day recency (moderate recency, 2x data)
/model-experiment --name "2SZN_Q43_R120" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

# 1c: 3 seasons, Q43, 120-day recency (max data, moderate recency)
/model-experiment --name "3SZN_Q43_R120" --quantile-alpha 0.43 --train-start 2023-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

# 1e: 2 seasons, baseline (NO quantile), 120-day recency (control)
/model-experiment --name "2SZN_BASE_R120" --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

# 1f: 2 seasons, Q43, 14-day recency (best single-season combo + 2x data)
/model-experiment --name "2SZN_Q43_R14" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 14 --walkforward --force

# 1g: 3 seasons, Q43, 14-day recency (February-focused — 14d recency on 3 seasons means recent Feb dominates)
/model-experiment --name "FEB_FOCUS_Q43" --quantile-alpha 0.43 --train-start 2023-12-01 --train-end 2026-02-07 --recency-weight 14 --walkforward --force
```

#### Session B Analysis

After all 5 complete, compare results:

```bash
# Compare all Wave 1 results
/compare-models
```

**Key questions to answer:**
1. Does 2-season beat single-season? (Compare 1f vs original Q43_RECENCY14)
2. Does 3-season beat 2-season? (Compare 1c vs 1b)
3. Which recency weight wins? (Compare 1b [120d] vs 1f [14d])
4. Does baseline + multi-season solve retrain paradox? (1e — if yes, quantile unnecessary)
5. Is any model above 55% HR on 50+ picks?

#### Session B Decision Gate

| Result | Next Action |
|--------|------------|
| **Any model > 55% HR on 50+ picks** | Best candidate for shadow deployment. Proceed to Session C (V10 activation on winning config). |
| **Best model 52.4-55%** | Marginal. Proceed to Session C (V10 may provide the needed 2-3pp boost). |
| **All models < 52.4%** | Multi-season doesn't help enough alone. Skip to Session D (monotonic constraints + post-processing stack). |
| **Baseline (1e) beats Q43** | Quantile may be unnecessary with enough data. Test baseline with V10 features. |
| **14d recency consistently beats 120d** | Short recency + more data = better. Use 14d as the standard. |
| **120d consistently beats 14d** | Broader context helps. Use 120d as the standard. |

---

### Session C: V10 Activation + Monotonic Constraints

**Goal:** Activate unused features 33-38 and test structural overfitting prevention.
**Time:** ~2-3 hours
**Code changes required BEFORE running experiments:**

#### Code Change 1: Add `--feature-set` to quick_retrain.py

```python
# In parse_args(), add:
parser.add_argument('--feature-set', choices=['v9', 'v10'], default='v9',
                    help='Feature set to use (v9=33 features, v10=39 features)')
```

In the feature extraction section, branch on this:
```python
if args.feature_set == 'v10':
    feature_names = V10_FEATURE_NAMES  # All 39 from feature_contract.py
else:
    feature_names = V9_FEATURE_NAMES   # Original 33
```

#### Code Change 2: Add `--monotone-constraints` to quick_retrain.py

```python
# In parse_args(), add:
parser.add_argument('--monotone-constraints', type=str, default=None,
                    help='Comma-separated list of -1/0/1 per feature (CatBoost monotone_constraints)')
```

In the CatBoost model creation:
```python
if args.monotone_constraints:
    constraints = [int(x) for x in args.monotone_constraints.split(',')]
    model_params['monotone_constraints'] = constraints
```

#### Experiments (run after code changes)

```bash
# 3a: V10 features with best Wave 1/2 config
/model-experiment --name "V10_BEST_Q43" --feature-set v10 --quantile-alpha 0.43 --train-start {BEST_START} --train-end 2026-02-07 --recency-weight {BEST_RECENCY} --walkforward --force

# 3b: V10 + single season control (isolate feature impact)
/model-experiment --name "V10_1SZN_Q43_R14" --feature-set v10 --quantile-alpha 0.43 --train-start 2025-11-02 --train-end 2026-02-07 --recency-weight 14 --walkforward --force

# 8a: Monotonic constraints (domain-correct relationships)
# Constraint key: 0=unconstrained, 1=monotone increasing, -1=monotone decreasing
# Index 25 (vegas_points_line): +1 (higher line → higher prediction)
# Index 13 (opponent_def_rating): -1 (better defense → lower prediction)
# Index 31 (minutes_avg_last_10): +1 (more minutes → more points)
# Index 5 (fatigue_score): -1 (more fatigue → fewer points)
# Index 1 (points_avg_last_10): +1 (higher avg → higher prediction)
/model-experiment --name "MONO_Q43_BEST" --quantile-alpha 0.43 --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0" --train-start {BEST_START} --train-end 2026-02-07 --recency-weight {BEST_RECENCY} --walkforward --force

# 8a+V10: Monotonic constraints WITH V10 features
/model-experiment --name "V10_MONO_Q43" --feature-set v10 --quantile-alpha 0.43 --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0,0,0,0,0,0,0" --train-start {BEST_START} --train-end 2026-02-07 --recency-weight {BEST_RECENCY} --walkforward --force
```

#### Session C Decision Gate

| Result | Next Action |
|--------|------------|
| V10 improves HR by 2+ pp | Features 33-38 are valuable. Keep permanently. Check feature importance for `pts_slope_10g` and `pts_vs_season_zscore` — if top 15, proceed to more features. |
| V10 is neutral | 33 features are sufficient. Don't add more features for now. Focus on post-processing. |
| Monotonic constraints improve HR | Structural overfitting was a problem. Make monotonic constraints the default. |
| Monotonic + V10 is best | Double win. This becomes the new best config. |

---

### Session D: Multi-Quantile Ensemble + Post-Processing Stack

**Goal:** Test confidence-based filtering via multiple quantile models and implement production post-processors.
**Time:** ~3-4 hours
**Code changes:** Small additions to quick_retrain.py for multi-quantile support

#### Multi-Quantile Ensemble (Wave 8b)

Train 3 models with different quantile alphas. High-confidence picks = when all 3 agree.

```bash
# Q30 (predicts ABOVE median — optimistic)
/model-experiment --name "MULTIQ_Q30" --quantile-alpha 0.30 --train-start {BEST_START} --train-end 2026-02-07 --recency-weight {BEST_RECENCY} --walkforward --force

# Q43 (predicts BELOW median — conservative, our known best)
/model-experiment --name "MULTIQ_Q43" --quantile-alpha 0.43 --train-start {BEST_START} --train-end 2026-02-07 --recency-weight {BEST_RECENCY} --walkforward --force

# Q57 (predicts ABOVE median — optimistic from other side)
/model-experiment --name "MULTIQ_Q57" --quantile-alpha 0.57 --train-start {BEST_START} --train-end 2026-02-07 --recency-weight {BEST_RECENCY} --walkforward --force
```

**Analysis:** Compare predictions across all 3. When Q30, Q43, and Q57 all predict the same direction, that's a high-confidence pick.

#### Post-Processing Stack Implementation

Based on Session A SQL results, implement the winning filters:

```python
# predictions/worker/postprocessing/pick_filter_stack.py

class PickFilterStack:
    """
    Layered filter stack applied after model prediction.
    Each filter independently testable. Combined score 0-6.
    """

    def score_pick(self, pick):
        score = 0

        # Layer 1: Base edge (always +1 for edge >= 3)
        if pick.edge >= 3:
            score += 1

        # Layer 2: Direction filter (suppress role UNDER)
        if not (pick.direction == 'UNDER' and pick.vegas_line >= 5 and pick.vegas_line <= 14):
            score += 1

        # Layer 3: Dynamic edge threshold (model age)
        model_age_days = (today - model_train_end).days
        if model_age_days <= 14 and pick.edge >= 3:
            score += 1
        elif model_age_days <= 21 and pick.edge >= 4:
            score += 1
        elif model_age_days <= 28 and pick.edge >= 5:
            score += 1
        elif pick.edge >= 7:
            score += 1

        # Layer 4: Per-game limit (max 2-3 per game)
        # Applied at batch level, not per-pick

        # Layer 5: Multi-model agreement (if available)
        # +1 if 2+ models agree on direction

        # Layer 6: Game total supports direction
        # High total (225+) + OVER or Low total (<210) + UNDER

        return score

    def filter_batch(self, picks, max_per_game=3):
        """Apply per-game limits: keep top N by edge per game."""
        by_game = defaultdict(list)
        for pick in picks:
            by_game[pick.game_id].append(pick)

        filtered = []
        for game_id, game_picks in by_game.items():
            sorted_picks = sorted(game_picks, key=lambda p: p.edge, reverse=True)
            filtered.extend(sorted_picks[:max_per_game])
        return filtered
```

#### Session D Decision Gate

| Result | Next Action |
|--------|------------|
| Multi-quantile confidence scoring hits 60%+ on agreement picks | This is a viable production strategy. Shadow deploy. |
| Post-processing stack lifts any model above 55% | Implement in production. |
| Nothing above 52.4% even with filters | Move to Session E (new features). |

---

### Session E: Feature Extraction + Engineering

**Goal:** Extract already-computed features into the feature store and add low-effort new features.
**Time:** ~4-6 hours (significant code)
**Code changes:** Multiple files

#### Priority extraction targets (data already exists):

1. **star_teammates_out** from `nba_analytics.upcoming_player_game_context` → feature store
2. **game_total_line** from `nba_raw.odds_api_game_lines` → feature store
3. **opponent_b2b** derived from `upcoming_player_game_context.opponent_days_rest`
4. **player_age** from `upcoming_player_game_context.player_age`
5. **scoring_cv_season** computed from existing features (points_std / points_avg)

#### Files to modify:

1. `shared/ml/feature_contract.py` — Add new feature names (indices 39+)
2. `data_processors/precompute/ml_feature_store/feature_extractor.py` — Add extraction queries
3. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` — Include in vector
4. `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` — Schema update
5. `ml/experiments/quick_retrain.py` — Extend feature set support

#### After feature extraction, train:

```bash
# V11 with all new features + best config
/model-experiment --name "V11_ALL_Q43" --feature-set v11 --quantile-alpha 0.43 --train-start {BEST_START} --train-end 2026-02-07 --recency-weight {BEST_RECENCY} --walkforward --force
```

---

### Session F: Shadow Deployment

**Goal:** Deploy best model from Sessions B-E as shadow alongside champion.
**Time:** ~1 hour
**Prerequisites:** A model that passes governance gates (or adjusted gates)

#### Steps:

1. Upload model to GCS
2. Register in model registry
3. Deploy as shadow (separate system_id)
4. Monitor for 7+ days via:
   - `validate-daily` Phase 0.56
   - `reconcile-yesterday` Phase 9
   - Pipeline canary auto-heal

#### Promotion criteria (updated gates):

| Gate | Threshold |
|------|-----------|
| Edge 3+ HR | > 52.4% |
| Bayesian P(true HR > 52.4%) | > 90% |
| Better than champion | +8pp on same eval window |
| Walkforward stability | No week < 40% (10+ picks) |
| Volume | >= 30 edge 3+ picks/week |
| Sample size | >= 100 graded edge 3+ picks |

---

### Sessions G-H: Advanced Techniques (Wave 7-8 remainder)

Only if Sessions B-F haven't produced a viable model.

**Session G priorities:**
- Platt/isotonic calibration on edge (convert edge → win probability)
- Edge-based bet sizing (Kelly criterion)
- Late injury cascade trigger design

**Session H priorities:**
- Optuna hyperparameter search (100+ trials)
- Model stacking with meta-learner
- Shooting efficiency features (fg_pct_last_3, ts_pct_last_5)

---

## Part 3: Master Decision Tree

```
Session A: SQL Pattern Mining
├── CLV positive in Jan, negative in Feb → STALENESS CONFIRMED
│   ├── Direction filter lifts HR > 52.4% → IMPLEMENT FILTER NOW
│   │   └── Session B: Multi-season training (5 experiments)
│   │       ├── Any model > 55% → Shadow deploy best + Session C (V10)
│   │       ├── 52.4-55% → Session C (V10 may boost 2-3pp)
│   │       │   ├── V10 + mono helps → Shadow deploy → Session F
│   │       │   └── V10 neutral → Session D (multi-quantile + filter stack)
│   │       └── All < 52.4% → Session D (monotonic + filter stack)
│   │           ├── Filter stack helps → Implement → Session E (new features)
│   │           └── Nothing works → Direction filter only + wait for March
│   └── Direction filter doesn't help → Session B anyway
│
├── CLV negative in BOTH months → NO REAL EDGE EVER
│   └── PIVOT: Focus entirely on post-processing (Wave 7)
│       ├── Multi-model consensus → test
│       ├── Line shopping → implement
│       ├── Dynamic edge threshold → implement
│       └── New features (Session E) to build genuine signal
│
└── CLV positive in both → EDGE EXISTS, SELECTION PROBLEM
    └── Focus on pick filtering (direction filter + game limits)
        └── Then Session B for freshness improvements
```

---

## Part 4: Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Multi-season data has hidden quality issues | MEDIUM | HIGH | Run data verification queries from doc 04 before training |
| V10 features hurt performance (noise) | LOW | LOW | Experiment 3b is the control — can revert to V9 |
| Monotonic constraints over-constrain | MEDIUM | LOW | Compare constrained vs unconstrained on same config |
| Direction filter reduces volume below viability | MEDIUM | MEDIUM | Check volume in Session A SQL. If <20 picks/week, filter is too aggressive. |
| Backtest inflation makes all results look better than reality | HIGH | HIGH | Require 100+ picks AND Bayesian gate. Shadow test EVERYTHING before production. |
| Quick_retrain.py code changes break existing functionality | LOW | HIGH | Run existing experiments (Q43_RECENCY14) after code changes to verify no regression. |
| February is structurally unprofitable | MEDIUM | HIGH | Direction filter + wait for March. Staleness exploitation works better in stable lineup periods. |

---

## Part 5: Experiment Tracking Template

For each experiment, record:

```
Experiment: {NAME}
Config: alpha={}, recency={}, seasons={}, features={}
Edge 3+ Picks: N
Edge 3+ HR: X%
Edge 5+ Picks: N
Edge 5+ HR: X%
OVER HR: X% (N picks)
UNDER HR: X% (N picks)
Walkforward stability: [week1%, week2%, ...]
Vegas bias: X
MAE: X
Feature importance top 5: [...]
Gate status: PASS / FAIL (which gates)
Bayesian P(HR > 52.4%): X%
Decision: ADVANCE / SHADOW / DISCARD
```

---

## Summary: What Changed From the Master Plan

| Master Plan | This Execution Plan | Reason |
|-------------|-------------------|--------|
| 56 experiments | ~44 experiments | Cut alpha sweep (noise), trim Wave 1, cut player archetypes |
| Wave 2 (4 alpha sweep experiments) | ELIMINATED | Expert consensus: alpha ±0.01 is curve-fitting |
| Wave 1 (8 experiments) | 5 experiments | Cut redundant configs (60d, 240d, multi-variable combo) |
| Multi-season at priority 8 | Priority 4 | Zero code changes, biggest untested variable |
| 60% absolute gate | Bayesian tiered gates | Statistically sound replacement |
| Gate 3: champion + 5pp | Champion + 8pp AND > 52.4% | 5pp too low when champion at 38% |
| Gate 4: no week < 45% | No week < 40% (10+ picks) | 45% too strict for small weekly samples |
| V10 = 37 features | V10 = 39 features | Feature contract already has 39 features |
| Position slicing code change | Name-based feature set switching | Actual implementation uses name-based extraction |
| Per-player calibration (priority MEDIUM) | Deferred | Expert consensus: lagging indicator |
| Player archetype clustering | Deferred | High effort, uncertain value |
