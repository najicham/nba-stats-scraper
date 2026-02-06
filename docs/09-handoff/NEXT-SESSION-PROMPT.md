# Session 139 Prompt - Validate Feature Quality Visibility + Continue Breakout V3

Copy and paste this to start the next session:

---

## Context

Sessions 137-138 deployed the **Feature Quality Visibility** system to `ml_feature_store_v2` (121 new columns). The system detects Session 132-style silent failures in <5 seconds. A 4-season backfill was launched and should be complete or nearly complete by now.

## Priority 1: Validate Backfill Completion

### Step 1: Push unpushed commit
```bash
git log --oneline -3
git push
```
Commit `90dcbb6c` (schedule fix) should be pushed.

### Step 2: Check if backfill processes finished
```bash
ps aux | grep "backfill" | grep -v grep | wc -l
# Should be 0 (all done)
# If still running, check logs: tail -5 /tmp/backfill_chunk{1,2,3,4}.log
```

### Step 3: Validate all records have quality fields
```sql
SELECT
  CASE
    WHEN game_date >= '2025-10-01' THEN '2025-26'
    WHEN game_date >= '2024-10-01' THEN '2024-25'
    WHEN game_date >= '2023-10-01' THEN '2023-24'
    WHEN game_date >= '2022-10-01' THEN '2022-23'
    WHEN game_date >= '2021-10-01' THEN '2021-22'
  END as season,
  COUNT(*) as total,
  COUNTIF(quality_alert_level IS NOT NULL) as backfilled,
  ROUND(COUNTIF(quality_alert_level IS NOT NULL) * 100.0 / COUNT(*), 1) as pct
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2021-10-01'
GROUP BY 1 ORDER BY 1;
```

**Expected:** All seasons at 100% (or close). If 2021-22 still has ~11% gap, investigate and re-run backfill for those dates.

### Step 4: Quality distribution check
```sql
SELECT quality_tier, COUNT(*) as cnt,
       ROUND(AVG(feature_quality_score), 1) as avg_score,
       ROUND(AVG(matchup_quality_pct), 1) as avg_matchup
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2025-11-01' AND quality_alert_level IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

### Step 5: Verify today's pipeline run populated quality fields
```sql
SELECT player_lookup, quality_tier, quality_alert_level,
       matchup_quality_pct, is_quality_ready, default_feature_count
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
LIMIT 10;
```

## Priority 2: Fix Any Gaps

If backfill left gaps:
```bash
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date <gap-start> --end-date <gap-end> --skip-preflight --no-resume
```

## Priority 3: Continue Breakout V3 (if time)

After validation is done, continue the Breakout V3 work from Session 135:
- Read `docs/09-handoff/2026-02-05-SESSION-135-HANDOFF.md` for V3 plan
- Add `star_teammate_out` feature to breakout classifier
- See CLAUDE.md [BREAKOUT] section for details

## Key Files

```
docs/09-handoff/2026-02-06-SESSION-138-HANDOFF.md  # Full Session 137/138 handoff
data_processors/precompute/ml_feature_store/quality_scorer.py  # Quality visibility logic
data_processors/precompute/ml_feature_store/batch_writer.py    # Dynamic MERGE
data_processors/precompute/ml_feature_store/ml_feature_store_processor.py  # Integration
schemas/bigquery/predictions/04_ml_feature_store_v2.sql        # Schema
```

## What NOT to Change

- `is_production_ready` — unchanged, 20+ consumers
- `calculated` source weight — keep at 100, defer change
- Shared `QualityTier` enum — feature store uses its own `get_feature_quality_tier()`
