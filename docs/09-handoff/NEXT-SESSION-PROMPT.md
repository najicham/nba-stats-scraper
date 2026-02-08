# Session 158 Prompt

Copy everything below this line into a new chat:

---

START, then read `docs/09-handoff/2026-02-07-SESSION-157-HANDOFF.md` for full context.

## Session 157 Summary

We investigated and fixed training data contamination in the ML pipeline:

- **Discovery:** 33.2% of V9 training data had non-vegas defaults (garbage values). The quality score weighted average (`feature_quality_score >= 70`) masked individual feature defaults.
- **Root cause:** Training scripts used `feature_quality_score >= 70` instead of `required_default_count = 0`. The prediction pipeline was already correctly gated since Session 141, but training scripts were not.
- **Fix:** Created `shared/ml/training_data_loader.py` — a shared module that enforces zero-tolerance quality filters at the SQL level. Migrated all 6 active training scripts to use it. Archived 41 legacy V6-V10 scripts.
- **V9 retrain:** Tested but inconclusive (6-day eval window too small). V9 performance is adequate (54-56% hit rate) — plan is to wait 2-3 weeks for clean data and retrain with larger eval window.

## What needs to happen this session

### 1. Verify deployed Session 156 data improvements
Check if today's feature store data shows improvement from the cache fallback and player filtering changes:
```sql
-- Compare default rates: today vs last week
SELECT game_date,
  COUNT(*) as total,
  COUNTIF(required_default_count = 0) as clean,
  ROUND(100.0 * COUNTIF(required_default_count = 0) / COUNT(*), 1) as clean_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1 DESC;
```

### 2. Feature store backfill (optional)
Re-run ML feature store processor for Jan-Feb 2026 to produce cleaner records with the improved cache fallback. This gives the V9 retrain (task 3) better training data.

### 3. V9 retrain (if enough clean data)
If 2+ weeks of clean data have accumulated:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_CLEAN_FEB20" \
    --train-start 2025-11-02 \
    --train-end 2026-02-18 \
    --eval-start 2026-02-01 \
    --eval-end 2026-02-18
```

### 4. Tier bias investigation
Both old V9 and clean retrain show: stars underestimated by 9 pts, bench overestimated by 7 pts. This is a regression-to-mean issue separate from contamination. Investigate and fix.
