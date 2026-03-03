# Session 377b Prompt — Best Bets Deep Review + Ultra Check

## Context

Session 377 completed morning pipeline validation and fixed the post-grading-export to handle `manual_override` system_ids and patch signal-best-bets JSON with grading results after games finish. That fix is deployed.

## Tasks

### 1. Review Tonight's Best Bets (Mar 1, 2026)

4 picks were published. Review each one in detail — verify the selection logic, check if the signals and filters were applied correctly, and confirm the pick angles make sense.

```sql
-- Get full best bets detail
SELECT *
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date = '2026-03-01'
ORDER BY edge DESC;
```

The 4 picks are:
1. **Kawhi Leonard UNDER 29.5** — Edge 5.3, 5 signals, model `catboost_v12_train0104_0208`, 5/6 models agree UNDER
2. **Cam Thomas OVER 12.5** — Edge 5.2, 6 signals, model `catboost_v12_noveg_train0110_0220`, cold streak + line rising + volatile scorer
3. **Luke Kennard OVER 7.5** — Edge 3.6, 4 signals, model `lgbm_v12_noveg_train1102_0209` (best fleet model 71.4% 7d HR)
4. **James Harden UNDER 21.5** — Edge 3.5, 3 signals (minimum), model `catboost_v12_vw015_train1201_1231`, only 1 model agrees

For each pick, verify:
- The prediction source model's recent performance (check `model_performance_daily`)
- Signal firing conditions are met (cross-reference feature values)
- No negative filters should have blocked it but didn't
- The pick angles are accurate

### 2. Check Ultra Bets Classification

Check if any of tonight's picks qualify as ultra bets. Ultra criteria are in `ml/signals/ultra_bets.py`.

```sql
-- Check ultra classification for today
SELECT player_name, recommendation, line_value, edge, ultra_tier, ultra_criteria
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date = '2026-03-01'
  AND ultra_tier IS NOT NULL;
```

Key ultra criteria (validated):
- `v12_edge_6plus`: V12 family + edge >= 6.0 (95.2% HR, 20-1)
- `v12_over_edge_5plus`: V12 family + OVER + edge >= 5.0 (89.5% HR, 17-2)
- `v12_edge_4_5plus`: V12 family + edge >= 4.5 (75.8% HR, 25-8)

Kawhi (UNDER 29.5, edge 5.3, V12) and Cam Thomas (OVER 12.5, edge 5.2, V12) should both potentially qualify — verify.

### 3. Verify Model Health for Sourcing Models

```sql
-- Check recent performance of models sourcing tonight's picks
SELECT system_id, report_date,
  hr_7d, n_7d, hr_14d, n_14d,
  over_hr_14d, under_hr_14d,
  best_bets_hr_14d, best_bets_n_14d
FROM `nba-props-platform.nba_predictions.model_performance_daily`
WHERE system_id IN (
  'catboost_v12_train0104_0208',
  'catboost_v12_noveg_train0110_0220',
  'lgbm_v12_noveg_train1102_0209',
  'catboost_v12_vw015_train1201_1231'
)
AND report_date >= '2026-02-25'
ORDER BY system_id, report_date DESC;
```

### 4. Season Record Context

Season: **77-39 (66.4%)**, +32.25 units. ATH was +33.52 on Feb 22. Currently in a FLAT regime — profitable but grinding. Signal count 4+ = 76.0% HR historically.

## Key Files

- `ml/signals/ultra_bets.py` — Ultra classification logic
- `ml/signals/signal_annotator.py` — Signal firing conditions
- `ml/signals/aggregator.py` — Best bets selection algorithm
- `ml/signals/pick_angle_builder.py` — Pick angle generation
- `shared/config/cross_model_subsets.py` — Dynamic subset definitions
- `predictions/coordinator/supplemental_data.py` — Model HR and supplemental features
