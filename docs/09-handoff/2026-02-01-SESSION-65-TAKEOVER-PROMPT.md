# Session 65 Takeover Prompt

**Date:** 2026-02-01
**Status:** Investigation Needed - Feature Version Mismatch

---

## Start Here

Continue investigating V8 hit rate degradation from Session 65.

**Read first:** `docs/09-handoff/2026-02-01-SESSION-65-HANDOFF.md`

---

## The Problem

Premium picks hit rate collapsed:

| Period | Premium Picks (92+ conf, 3+ edge) |
|--------|-----------------------------------|
| Jan 1-8 (healthy) | **84.5%** |
| Jan 9-28 (after fix) | **52.5%** |
| **Gap** | **-32 pts** |

Session 65 fixed the deployment timing bug (50.4% → 53.1%), but the gap to healthy baseline remains massive.

---

## Hypothesis: Feature Version Mismatch

The CatBoost V8 model was trained with **33 features**, but the ML feature store now generates **37 features**.

The feature store backfill (Session 65) created v37 records:
- `feature_count = 37` for all new records
- Model expects `feature_count = 33`
- Backfill script uses first 33 features from v37 records

**Potential Issues:**
1. Feature order might not match between v33 and v37
2. Extra features might have shifted column positions
3. Feature value distributions might differ

---

## Priority Tasks

1. **Verify feature order alignment**
   - Check `ml/backfill_v8_predictions.py` FEATURE_NAMES
   - Compare with feature store generation order
   - File: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

2. **Compare feature distributions**
   ```sql
   SELECT
     CASE WHEN game_date <= '2026-01-08' THEN 'healthy' ELSE 'degraded' END as period,
     ROUND(AVG(features[OFFSET(0)]), 2) as points_avg_season,
     ROUND(AVG(features[OFFSET(25)]), 2) as vegas_line
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date >= '2026-01-01' AND game_date <= '2026-01-28'
   GROUP BY 1;
   ```

3. **If mismatch confirmed:**
   - Option A: Fix feature store to generate v33
   - Option B: Retrain model on v37 features
   - Option C: Run `exp_20260201_current_szn` challenger experiment

---

## Known Broken Features

| Feature | Status |
|---------|--------|
| `pace_score` | 100% zeros |
| `usage_spike_score` | 100% zeros (by design) |
| `team_win_pct` | Always 0.5 |
| `fatigue_score` | Partially broken |

---

## Session 65 Commits

```
6d1e30d5 docs: Add deploy-before-backfill rule to CLAUDE.md
da38ee61 fix: Update backfill script to accept v37 feature store records
373cd868 docs: Add Session 65 handoff with feature mismatch investigation
```

---

*Created: 2026-02-01 Session 65*
