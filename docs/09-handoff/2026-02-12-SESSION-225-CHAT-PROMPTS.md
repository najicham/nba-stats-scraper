# Session 225 — Chat Prompts for Parallel Execution

These are self-contained prompts for separate Claude Code chats. Each can run independently.
Copy-paste each prompt into a new chat.

**Dependency order:**
- Chat 1 (SQL) and Chat 2 (Training) can run **in parallel**
- Chat 3 (V10 code changes) can start immediately (no dependencies)
- Chat 4 (Analysis) needs results from Chats 1 + 2
- Chat 5 (Post-processing) needs results from Chat 4's decisions

---

## Chat 1: Session A — SQL Pattern Mining & CLV Analysis

```
You are continuing work on the NBA props prediction project. The champion model (catboost_v9) has decayed from 71.2% to 38.0% edge 3+ hit rate. We need diagnostic SQL queries to understand WHY and determine strategy.

CRITICAL SCHEMA NOTE: The `prediction_accuracy` table uses these column names (NOT what the planning docs say):
- `recommendation` (not predicted_direction) — values are OVER/UNDER
- `line_value` (not vegas_line)
- `prediction_correct` (not is_correct)
- `predicted_margin` (signed: predicted_points - line_value). Edge = ABS(predicted_margin)
- `predicted_points`, `actual_points`, `absolute_error`, `signed_error` also available
- There is NO `edge` column — always use ABS(predicted_margin)

For `odds_api_player_points_props`: uses `bookmaker` (not bookmaker_key), `points_line` (not outcome_point), has `snapshot_timestamp` and `player_lookup`.

YOUR TASK: Run these 9 SQL queries and report ALL results. Do NOT skip any.

### Query 1: Pre-flight — Verify recommendation values
bq query --use_legacy_sql=false '
SELECT DISTINCT recommendation, COUNT(*) as cnt
FROM nba_predictions.prediction_accuracy
WHERE system_id = "catboost_v9" AND game_date >= "2026-02-01"
GROUP BY 1'

If recommendation values are lowercase ("over"/"under"), adjust all subsequent queries.

### Query 2: UNDER collapse — monthly breakdown by direction
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

### Query 3: Trade deadline impact
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

### Query 4: Role player UNDER disaster zone — monthly
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

### Query 5: Direction filter simulation — all models, February
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

### Query 6: Ensemble simulation (champion OVER + Q43 UNDER + star OVER)
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

### Query 7: CLV Analysis (MOST IMPORTANT — determines entire strategy)
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

### Query 8: Per-game correlation analysis
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

### Query 9: Dynamic edge threshold by model age
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

### AFTER ALL QUERIES: Write a summary report

Create a file at docs/08-projects/current/model-improvement-analysis/06-SESSION-A-SQL-RESULTS.md with:
1. Raw results from all 9 queries
2. Key findings section answering:
   - Is the UNDER collapse February-specific or was it always bad? (Query 2)
   - Did the trade deadline make things worse? (Query 3)
   - How much does the direction filter help? (Query 5) — What's the HR after filtering?
   - Does the ensemble (champion OVER + Q43 UNDER) work? (Query 6)
   - CLV VERDICT: Was CLV positive in January? Negative in February? Or negative in both? (Query 7)
   - Are per-game pick clusters correlated failures? (Query 8)
   - Does tightening edge threshold with model age help? (Query 9)
3. Recommendation: Based on results, which of these paths should we take?
   - Path A: CLV positive Jan, negative Feb → Staleness confirmed, proceed with retraining
   - Path B: CLV negative both months → No real edge ever, pivot to post-processing only
   - Path C: CLV positive both → Edge exists, selection problem, focus on filtering

Do NOT run any training experiments. This is SQL analysis only.
```

---

## Chat 2: Session B — Multi-Season Training Matrix (5 Experiments)

```
You are continuing work on the NBA props prediction project. We're running 5 multi-season training experiments to test whether more training data improves the Q43 quantile model.

CONTEXT:
- Champion model (catboost_v9) decayed from 71.2% → 38.0% edge 3+ HR (35 days stale)
- Best known technique: quantile alpha=0.43 + 14d recency = 55.4% HR on 92 picks (single season)
- Currently using only 11% of available data (8.4K of 38K trainable rows)
- Feature store has 3 seasons of clean data (Dec 2023+). November data is always bad (21-28% clean) — start from December.
- Recency weighting applies exponential decay to CatBoost sample weights (not row filtering)
- All commands verified to work with existing quick_retrain.py — no code changes needed

YOUR TASK: Run these 5 experiments using /model-experiment. Run them in parallel where possible. After all complete, compare results and write a summary.

### Experiment 1b: 2 seasons, Q43, 120-day recency
/model-experiment --name "2SZN_Q43_R120" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

Hypothesis: 2x more data with moderate recency improves Q43 generalization.

### Experiment 1c: 3 seasons, Q43, 120-day recency
/model-experiment --name "3SZN_Q43_R120" --quantile-alpha 0.43 --train-start 2023-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

Hypothesis: Maximum data (3 seasons, ~35K rows) gives broadest pattern coverage.

### Experiment 1e: 2 seasons, NO quantile (baseline control), 120-day recency
/model-experiment --name "2SZN_BASE_R120" --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 120 --walkforward --force

Hypothesis: Does more data alone solve the retrain paradox without needing quantile?

### Experiment 1f: 2 seasons, Q43, 14-day recency
/model-experiment --name "2SZN_Q43_R14" --quantile-alpha 0.43 --train-start 2024-12-01 --train-end 2026-02-07 --recency-weight 14 --walkforward --force

Hypothesis: Best single-season combo (Q43 + 14d recency = 55.4%) with 2x more training data.

### Experiment 1g: 3 seasons, Q43, 14-day recency (February-focused)
/model-experiment --name "FEB_FOCUS_Q43" --quantile-alpha 0.43 --train-start 2023-12-01 --train-end 2026-02-07 --recency-weight 14 --walkforward --force

Hypothesis: 14d recency on 3 seasons means model sees all 3 seasons but recent Feb data dominates. Learns past February patterns while focusing on current conditions.

### AFTER ALL 5 COMPLETE: Analysis & Summary

Use /compare-models or manual queries to compare all 5.

Create a file at docs/08-projects/current/model-improvement-analysis/07-WAVE1-TRAINING-RESULTS.md with:

1. Results table for all 5 experiments:
   | Experiment | Edge 3+ Picks | Edge 3+ HR | Edge 5+ Picks | Edge 5+ HR | OVER HR | UNDER HR | Vegas Bias | MAE | Walkforward (per-week) |

2. Answer these key questions:
   - Does 2-season beat single-season? (Compare 1f results vs the known single-season baseline: Q43_RECENCY14 = 55.4% on 92 picks)
   - Does 3-season beat 2-season? (Compare 1c vs 1b)
   - Which recency weight wins? (Compare 120d [1b] vs 14d [1f] on 2-season data)
   - Does baseline + multi-season solve the retrain paradox? (1e — if yes, quantile is unnecessary with enough data)
   - Walkforward stability: Does any model have a week below 40%?
   - Which model has the best Bayesian probability of being above 52.4% breakeven?

3. Governance gate check for each: Would it pass the proposed tiered gates?
   - Gate 1: HR > 52.4% on 100+ picks?
   - Gate 2: P(true HR > 52.4%) > 90%? (Use: from scipy.stats import beta; 1 - beta.cdf(0.524, wins+1, losses+1))
   - Gate 3: Better than champion (38.0%) by 8+ pp?
   - Gate 4: No walkforward week below 40%?
   - Gate 5: 30+ edge 3+ picks per week?

4. Recommendation:
   - BEST CONFIG: Which train-start, recency-weight, and alpha to carry forward?
   - NEXT STEP: If any > 55% → shadow deploy candidate. If 52.4-55% → proceed to V10 activation. If all < 52.4% → multi-season alone isn't enough.

Do NOT deploy any model. Do NOT make code changes. Training and analysis only.
```

---

## Chat 3: Session C Prep — V10 Code Changes + Monotonic Constraints

```
You are continuing work on the NBA props prediction project. We need to make 2 code changes to ml/experiments/quick_retrain.py to enable V10 feature activation and monotonic constraints for upcoming experiments.

CONTEXT:
- quick_retrain.py currently uses V9_FEATURE_NAMES (33 features) via name-based extraction (NOT position slicing — changed in Session 107)
- V10_FEATURE_NAMES already exists in shared/ml/feature_contract.py with 37 features (adds: dnp_rate, pts_slope_10g, pts_vs_season_zscore, breakout_flag at indices 33-36)
- V10_CONTRACT also exists with feature_count=37
- We need a way to switch between V9 and V10 feature sets at training time
- We also need to pass monotonic constraints to CatBoost

YOUR TASK: Make these 2 code changes. Do NOT run any experiments — just the code changes + verification.

### Code Change 1: Add --feature-set argument

In ml/experiments/quick_retrain.py:

1. Find the argparse section and add:
   parser.add_argument('--feature-set', choices=['v9', 'v10'], default='v9',
                       help='Feature set to use (v9=33 features, v10=37 features)')

2. Find where V9_FEATURE_NAMES is used for feature extraction. Update to branch on the argument:
   - If args.feature_set == 'v10': use V10_FEATURE_NAMES from feature_contract
   - If args.feature_set == 'v9': use V9_FEATURE_NAMES (current default behavior)

3. Make sure the correct feature count is used throughout (model registration, metadata, etc.)

IMPORTANT: Read the relevant sections of quick_retrain.py carefully before making changes. The feature extraction uses name-based lookups, not position slicing. Find all places where V9_FEATURE_NAMES or FEATURES is referenced and update appropriately.

### Code Change 2: Add --monotone-constraints argument

In ml/experiments/quick_retrain.py:

1. Add argparse argument:
   parser.add_argument('--monotone-constraints', type=str, default=None,
                       help='Comma-separated -1/0/1 per feature for CatBoost monotone_constraints. '
                            'Example for V9 (33 features): "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0"')

2. Find where the CatBoost model params dict is built. Add:
   if args.monotone_constraints:
       constraints = [int(x) for x in args.monotone_constraints.split(',')]
       if len(constraints) != len(feature_names):
           print(f"ERROR: monotone_constraints length ({len(constraints)}) != feature count ({len(feature_names)})")
           return
       model_params['monotone_constraints'] = constraints

### Verification

After both changes:

1. Run a dry-run to verify V10 works:
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "V10_TEST" --feature-set v10 --dry-run --force

2. Run a dry-run to verify monotonic constraints parse:
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "MONO_TEST" --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0" --dry-run --force

3. Run the existing Q43 config to verify NO regression:
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "REGRESSION_CHECK" --quantile-alpha 0.43 --train-start 2025-11-02 --train-end 2026-02-07 --recency-weight 14 --dry-run --force

All 3 should complete without errors. If --dry-run doesn't exist, use --skip-register instead and let them train (they're quick).

Do NOT commit. Do NOT deploy. Code changes + verification only. We'll commit after reviewing.
```

---

## Chat 4: Session D — Results Analysis & Decision (Run AFTER Chats 1+2)

```
You are continuing work on the NBA props prediction project. Chats 1 and 2 produced results that need analysis. Your job is to read both result files and make recommendations.

YOUR TASK:

1. Read the SQL analysis results:
   cat docs/08-projects/current/model-improvement-analysis/06-SESSION-A-SQL-RESULTS.md

2. Read the training experiment results:
   cat docs/08-projects/current/model-improvement-analysis/07-WAVE1-TRAINING-RESULTS.md

3. Read the execution plan for decision criteria:
   cat docs/08-projects/current/model-improvement-analysis/05-SESSION-225-REVIEW-AND-EXECUTION-PLAN.md

4. Based on the decision trees in the execution plan (Part 3), determine:

   a) CLV VERDICT — Which path are we on?
      - Path A: CLV positive Jan, negative Feb → staleness confirmed
      - Path B: CLV negative both → no real edge
      - Path C: CLV positive both → selection problem

   b) DIRECTION FILTER — How much does suppressing role-UNDER help?
      - What's the filtered HR? Is it above 52.4%?
      - How many picks remain after filtering?

   c) BEST TRAINING CONFIG — From Wave 1:
      - Which experiment had the best edge 3+ HR on 50+ picks?
      - Does more data help? (2-season vs single-season)
      - Which recency weight won? (14d vs 120d)
      - Did baseline without quantile work? (1e result)

   d) COMBINED RECOMMENDATION — What should we do next?
      - If best model > 55% → recommend shadow deployment + V10 experiment
      - If best model 52.4-55% → recommend V10 activation (may add the needed 2-3pp)
      - If nothing above 52.4% → recommend post-processing stack (direction filter + dynamic edge threshold + per-game limits)
      - If CLV was negative in both months → recommend pivoting entirely to post-processing

5. Write your analysis to:
   docs/08-projects/current/model-improvement-analysis/08-DECISION-ANALYSIS.md

Include:
- Summary table of all results (SQL + training)
- The decision path taken and why
- Exact next commands to run (either V10 experiments, shadow deployment, or post-processing implementation)
- Updated governance gate assessment

Do NOT run any experiments or make code changes. Analysis and recommendations only.
```

---

## Chat 5: Session E — Post-Processing Implementation (Run IF needed based on Chat 4)

```
You are continuing work on the NBA props prediction project. Based on analysis results, we need to implement production post-processing filters to improve pick quality without model changes.

CONTEXT:
- Champion model at 38.0% edge 3+ HR (losing money)
- Direction filter (suppress role player UNDER where line_value 5-14) shown to improve HR by [X]pp (from Chat 1 results)
- Per-game pick limits reduce correlated failures
- Dynamic edge threshold (tighten with model age) exploits known decay curve

CRITICAL: The prediction_accuracy table uses these columns:
- recommendation (OVER/UNDER), line_value, prediction_correct, predicted_margin, predicted_points, actual_points

YOUR TASK: Implement a pick filter stack as a post-processing layer.

### Step 1: Create the filter module

Create predictions/worker/postprocessing/pick_filters.py with:

1. DirectionFilter: Suppress picks where recommendation="UNDER" AND line_value BETWEEN 5 AND 14
2. DynamicEdgeFilter: Adjust minimum edge based on model age (days since train_end)
   - Week 1-2: edge >= 3
   - Week 3: edge >= 4
   - Week 4: edge >= 5
   - Week 5+: edge >= 7
3. PerGameLimit: Keep max N picks per game (sorted by edge descending)
4. PickFilterStack: Combines all filters, applies in order, logs what was filtered and why

### Step 2: Integration point

Find where picks are published/exported (likely in the Phase 6 export or the prediction coordinator). Add the filter stack as an optional post-processing step that can be enabled via environment variable (ENABLE_PICK_FILTERS=true).

### Step 3: Backtest validation

Write a SQL query that simulates the full filter stack on historical prediction_accuracy data:
- Apply direction filter + dynamic edge threshold + per-game limit (max 3)
- Compare filtered HR vs unfiltered HR for Feb 2026
- Report: picks kept, picks filtered, new HR, volume per day

### Step 4: Shadow mode

The filter should LOG what it would filter but NOT actually filter in production until explicitly enabled. Add a PICK_FILTER_MODE env var:
- "shadow" = log only (default)
- "active" = actually filter
- "disabled" = no logging or filtering

Do NOT deploy. Do NOT commit. Implementation + backtest query only.
```

---

## Chat 6: Session F — V10 Experiments (Run AFTER Chat 3 code changes)

```
You are continuing work on the NBA props prediction project. Code changes from Chat 3 added --feature-set and --monotone-constraints to quick_retrain.py. Now run V10 experiments.

CONTEXT:
- V10 adds 4 features (indices 33-36): dnp_rate, pts_slope_10g, pts_vs_season_zscore, breakout_flag
- pts_slope_10g (scoring momentum) and pts_vs_season_zscore (role change detection) are the most promising
- These features are 96-100% populated across all 3 seasons
- Best training config from Wave 1: [FILL IN from Chat 2 results — train-start, recency-weight]

YOUR TASK: Run 4 experiments testing V10 features and monotonic constraints.

### Experiment 3a: V10 with best Wave 1 config
/model-experiment --name "V10_BEST_Q43" --feature-set v10 --quantile-alpha 0.43 --train-start [BEST_START] --train-end 2026-02-07 --recency-weight [BEST_RECENCY] --walkforward --force

### Experiment 3b: V10 + single season (control — isolates feature impact)
/model-experiment --name "V10_1SZN_Q43_R14" --feature-set v10 --quantile-alpha 0.43 --train-start 2025-12-01 --train-end 2026-02-07 --recency-weight 14 --walkforward --force

### Experiment 8a: Monotonic constraints (V9, best config)
# Constraints: index 1 (pts_avg_10) +1, index 5 (fatigue) -1, index 13 (opp_def) -1, index 25 (vegas_line) +1, index 31 (min_avg_10) +1
/model-experiment --name "MONO_Q43_BEST" --quantile-alpha 0.43 --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0" --train-start [BEST_START] --train-end 2026-02-07 --recency-weight [BEST_RECENCY] --walkforward --force

### Experiment 8a+V10: Monotonic constraints WITH V10 features
/model-experiment --name "V10_MONO_Q43" --feature-set v10 --quantile-alpha 0.43 --monotone-constraints "0,1,0,0,0,-1,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0,0,0,0,0" --train-start [BEST_START] --train-end 2026-02-07 --recency-weight [BEST_RECENCY] --walkforward --force

### AFTER ALL 4 COMPLETE: Analysis

Create docs/08-projects/current/model-improvement-analysis/09-V10-MONO-RESULTS.md with:

1. Results table (same format as Wave 1)
2. Feature importance comparison: Do pts_slope_10g and pts_vs_season_zscore rank in top 15?
3. V10 vs V9 comparison on same config: Does V10 improve HR by 2+ pp?
4. Monotonic vs unconstrained: Does constraining improve generalization?
5. Best overall model so far (across Wave 1 + this wave)
6. Governance gate assessment for best model

Do NOT deploy. Training and analysis only.
```

---

## Notes for the Operator

- **Chats 1, 2, 3** can all start immediately in parallel
- **Chat 4** needs results from Chats 1 + 2 (wait for both result files)
- **Chat 5** is conditional — only run if Chat 4 recommends post-processing path
- **Chat 6** needs Chat 3 (code changes) + Chat 2 (best config values to fill in [BEST_START] and [BEST_RECENCY] placeholders)
- All chats write results to `docs/08-projects/current/model-improvement-analysis/` for cross-reference
- No chat should commit or deploy anything
