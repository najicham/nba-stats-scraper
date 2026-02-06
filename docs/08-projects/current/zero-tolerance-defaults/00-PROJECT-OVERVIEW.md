# Zero Tolerance for Default Features (Session 141)

## Problem

The ML feature store uses hardcoded default values when real data is missing:
- `avg_points=10.0` for Jayson Tatum (actual: ~27 PPG)
- `minutes_avg=28.0` for bench players (actual: ~12 min)
- `fatigue_score=0.5` when fatigue data is missing

These defaults poison predictions. Before this change:
- 126/201 players (63%) had at least one defaulted feature
- 5 players with 11 defaults passed `is_quality_ready=true`
- 80 players had 3 defaults (vegas features 25-27 missing) -- largest group

## Solution: Refuse to Predict with Any Defaults

**Philosophy:** Better to skip a player than to predict with fake data. Even during bootstrap periods, nulls are honest ("we don't have this data") while defaults are lies.

### Changes Made

| File | Change | Purpose |
|------|--------|---------|
| `quality_scorer.py` | `is_quality_ready` requires `default_count == 0` | Phase 4: Mark rows with defaults as not ready |
| `quality_scorer.py` | Alert level yellow threshold: `default_count > 0` (was > 10) | Phase 4: Flag any defaults |
| `quality_gate.py` | New Rule 2b: Block `default_feature_count > 0` | Coordinator: Hard floor enforcement |
| `quality_gate.py` | Fetch `default_feature_count` in quality query | Coordinator: Data access |
| `worker.py` | Defense-in-depth filter: `has_default_features` | Worker: Catch edge cases |
| `worker.py` | Write `default_feature_count` to prediction record | Worker: Audit trail |
| `01_player_prop_predictions.sql` | Add `default_feature_count INT64` column | Schema: Audit trail |

### Three Layers of Protection

1. **Phase 4 (quality_scorer.py):** `is_quality_ready=false` when defaults exist
2. **Coordinator (quality_gate.py):** Rule 2b hard floor blocks `default_feature_count > 0`
3. **Worker (worker.py):** Defense-in-depth sets `is_actionable=false` for defaults

## Impact

- **Before:** ~180 predictions per game day (~89% of feature store players)
- **After:** ~75 predictions per game day (~37% of feature store players)
- **Largest blocked group:** 80 players with 3 vegas defaults (features 25-27)
- **This is intentional** -- accuracy > coverage

## Verification

```sql
-- Confirm is_quality_ready is false for all rows with defaults
SELECT default_feature_count, is_quality_ready, COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
GROUP BY 1, 2 ORDER BY 1;

-- Check prediction coverage after enforcement
SELECT game_date, COUNT(*) as predictions,
       COUNTIF(default_feature_count = 0) as clean,
       COUNTIF(default_feature_count > 0) as has_defaults
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC;
```

## Future Considerations

If coverage needs to increase, the right approach is to **fix the data pipeline** (ensure Phase 4 processors run for more players, improve vegas line coverage) -- NOT to relax the zero tolerance policy. Defaults are never acceptable because they are actively misleading to the model.
