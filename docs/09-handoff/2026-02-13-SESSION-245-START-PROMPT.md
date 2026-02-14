# Session 245 Start Prompt

Copy everything below the line into a new chat.

---

Read the handoff and results docs first, then continue the experiment suite:

```
cat docs/09-handoff/2026-02-13-SESSION-244-HANDOFF.md
cat docs/08-projects/current/mean-reversion-analysis/06-SESSION-244-RSM-VARIANTS-AND-SQL.md
```

## Context

Sessions 243-244 ran 13 model experiments (8 V12, 5 RSM variants) and 9 SQL analyses. Key findings:

- **V12 RSM50 is the best config** (57.1% edge 3+ HR) using `--feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise`
- **RSM50_HUBER is the closest contender** (57.35% HR, 68 samples, 5/6 governance gates — only misses 60% HR by 2.65pp)
- **V12 augmentation is BROKEN** — 0% JOIN match rate across ALL experiments. Every "V12" model is actually running on V9 base features (33 features). The augmentation queries return data (UPCG: 19K rows, Stats: 11K rows) but 0 rows match when joining to the training DataFrame. Likely a `player_lookup` format mismatch.
- **V14 feature contract is implemented** (5 engineered FG% features) but untested
- **3PT cold is the real mean-reversion signal** (55.6% OVER rate), not overall FG% cold (50.9%)
- **`line_vs_season_avg` is critical** — removing it crashes HR from 57.1% to 51.85%
- All code changes are uncommitted

## What to Do

### 1. FIX V12 Augmentation Bug (HIGHEST PRIORITY)

This is the single highest-leverage fix. All V12+ experiments are handicapped without it. The augmentation functions in `quick_retrain.py` (`augment_v11_features`, `augment_v12_features`) query BQ successfully but fail to join to the training DataFrame.

**Debug approach:**
```python
# Add to augment_v12_features() after building lookups
print(f"  DEBUG df player_lookup sample: {df['player_lookup'].head(3).tolist()}")
print(f"  DEBUG df game_date sample: {df['game_date'].head(3).tolist()}, dtype: {df['game_date'].dtype}")
# Compare with UPCG/stats lookup key format
```

The JOIN key is `(player_lookup, game_date_str)`. Check:
- Is `player_lookup` in different formats between feature store and raw tables?
- Is `game_date` a string vs date object?
- Are the lookup keys being constructed differently?

Once fixed, re-run RSM50 and RSM50_HUBER to see the real V12 performance.

### 2. Run V14 Experiments (after or parallel to bug fix)

```bash
# V14 RSM50
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V14_RSM50" \
  --feature-set v14 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register

# V14 RSM50 + Huber
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V14_RSM50_HUBER" \
  --feature-set v14 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --loss-function "Huber:delta=5" \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-12 \
  --walkforward --include-no-line --force --skip-register
```

### 3. Post-Prediction 3PT Cold Filter Analysis

SQL showed 3PT cold (L2 < 30%) at 55.6% OVER rate. Test as a post-prediction rule:
- OVER predictions where player is 3PT cold: what's the HR?
- UNDER predictions where player is 3PT hot (>40% L2): what's the HR?
- Query against `prediction_accuracy` joined with `nbac_gamebook_player_stats`

### 4. Extended Eval Window (if ASB is over)

RSM50 only had 35 edge 3+ samples (governance needs 50). Extend eval:
```bash
--eval-start 2026-02-01 --eval-end 2026-02-20
```

## Schema Reminders

- `prediction_accuracy`: `line_value` (not prop_line), `actual_points` (not actual_stat), no `stat_type` column
- `nbac_gamebook_player_stats`: `minutes_decimal` (not minutes_played), `field_goals_made/attempted`, `three_pointers_made/attempted`
- `player_game_summary`: `minutes_played`, `points`, `usage_rate`
- Feature store JOIN key: `(player_lookup, game_date)` — check format carefully

## Approach

Use the DOC procedure — save results to `docs/08-projects/current/mean-reversion-analysis/`. Run experiments in parallel where possible. Fix the augmentation bug first since it affects everything downstream. Present results in decision matrices. Check governance gates (60% edge 3+ HR, 50+ samples, directional balance, vegas bias +/-1.5, tier bias +/-5).
