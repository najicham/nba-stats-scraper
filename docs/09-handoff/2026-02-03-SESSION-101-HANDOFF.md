# Session 101 Handoff - Feature Mismatch Investigation Complete

**Date:** 2026-02-03
**Time:** 8:30 PM UTC (12:30 PM PT)
**Model:** Claude Opus 4.5

---

## Session Summary

**Deep investigation identified the TRUE root cause**: Worker instance-level cache served stale feature data after the feature store was overwritten via `WRITE_TRUNCATE`. This caused 0% high-edge hit rate on Feb 2 and affected 69% of Feb 3 predictions.

---

## Root Cause (UPDATED from earlier analysis)

### Technical Details

The issue is a **race condition between feature store WRITE_TRUNCATE and worker cache**:

1. **Feature Store Uses WRITE_TRUNCATE** (`batch_writer.py:319`)
   - Each run completely overwrites data for that date

2. **Worker Has Instance-Level Cache** (`data_loaders.py:80-87`)
   - 5-minute TTL for same-day/future dates
   - Cache NOT shared across Cloud Run instances

3. **Timeline Evidence:**
   ```
   ???         - Feature store first populated for Feb 3 (quality ~65.5, wrong data)
   ~21:38     - Worker instance cached this stale data
   22:30:07   - Feature store re-populated with WRITE_TRUNCATE (quality 87.59, correct)
   23:12:42   - Worker STILL used stale cached 65.5 data to make predictions
   ```

### Key Evidence

- Worker logs at 23:12 explicitly show: `"Features validated for petenance (quality: 65.5)"`
- Current feature store shows ONLY 87.59 quality (old 65.5 data was truncated)
- `critical_features.features_snapshot` preserved wrong values: `pts_avg_5: 12.8` (should be 24.2)

---

## Impact Assessment

| Date | Total | Null Quality | % Affected | Results |
|------|-------|--------------|------------|---------|
| **Feb 2** | 97 | 97 (100%) | **100%** | 41.9% overall, **0/7 high-edge (0%)** |
| **Feb 3** | 147 | 102 | 69.4% | Games not yet played |
| Jan 31+ | 200+ | 0 | 0% | Normal (not affected) |

**The 0% high-edge hit rate on Feb 2 was caused by this issue.**

---

## Actions Taken

### 1. Regenerated Predictions

```bash
# Feb 3 regeneration
curl -X POST .../regenerate-with-supersede -d '{"game_date": "2026-02-03", "reason": "feature_cache_stale"}'
# Result: 154 new prediction requests published

# Feb 2 regeneration
curl -X POST .../regenerate-with-supersede -d '{"game_date": "2026-02-02", "reason": "feature_cache_stale"}'
# Result: 69 new prediction requests published
```

### 2. Historical Data Preserved

- Old predictions marked with `superseded = TRUE`
- `critical_features.features_snapshot` preserves wrong feature values for comparison
- Can query both old and new predictions to compare

### 3. Documentation Created

- `docs/08-projects/current/feature-mismatch-investigation/SESSION-101-FINDINGS.md`

---

## Current State After Regeneration

| Date | Superseded (old) | New | Total | New Avg Quality |
|------|-----------------|-----|-------|-----------------|
| Feb 2 | 87 | 11+ | 97+ | 87.15 |
| Feb 3 | 104 | 45+ | 149+ | 87.59 |

**Regeneration in progress** - new predictions being generated with correct features.

---

## Outstanding Work

### High Priority

1. **Monitor regeneration completion** - Verify all new predictions generated
2. **Verify Feb 3 predictions** - All players should have correct quality scores

### Medium Priority

3. **Fix cache invalidation** - Add Pub/Sub notification when feature store is written
4. **Add pre-prediction validation** - Check feature quality before making predictions

### Low Priority

5. **Replace WRITE_TRUNCATE** - Consider WRITE_APPEND with deduplication
6. **Update validate-daily skill** - Add feature quality score checks

---

## Validation Skill Enhancement Ideas

Based on this investigation, `/validate-daily` could be enhanced to:

```sql
-- Check 1: Feature quality scores present
SELECT COUNT(*) as null_quality
FROM player_prop_predictions
WHERE game_date = CURRENT_DATE() AND feature_quality_score IS NULL

-- Check 2: Quality scores match feature store
SELECT p.player_lookup, p.feature_quality_score as pred_q, f.feature_quality_score as store_q
FROM player_prop_predictions p
JOIN ml_feature_store_v2 f ON p.player_lookup = f.player_lookup AND p.game_date = f.game_date
WHERE ABS(p.feature_quality_score - f.feature_quality_score) > 1
```

---

## Verification Queries

### Check New Predictions Have Correct Quality
```sql
SELECT player_lookup, feature_quality_score, created_at
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-03' AND system_id = 'catboost_v9'
  AND feature_quality_score IS NOT NULL
ORDER BY created_at DESC
LIMIT 5
```

### Check Batch Status
```bash
curl -s "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq
```

### Check Worker Logs for Errors
```bash
gcloud logging read 'resource.labels.service_name="prediction-worker" AND severity>=WARNING' \
  --limit=10 --freshness=15m
```

---

## Session 100 Issue Status

| Session 100 Finding | Status | Resolution |
|---------------------|--------|------------|
| Feature values mismatch | ✅ Root cause found | Worker cache + WRITE_TRUNCATE race |
| 65.46 quality score | ✅ Explained | Stale cache from earlier feature store write |
| 12.8 pts_avg_5 | ✅ Explained | Old feature store data (pre-TRUNCATE) |
| Predictions wrong | ✅ Regenerating | 223 new predictions triggered |

**Root cause**: Worker cached stale data from first feature store write. WRITE_TRUNCATE at 22:30 replaced data, but cache wasn't invalidated.

---

## Files Changed This Session

| File | Change |
|------|--------|
| `docs/08-projects/current/usage-rate-prevention/` | Moved to completed |
| `docs/09-handoff/2026-02-03-SESSION-101-HANDOFF.md` | Created (this file) |

---

## Next Session Priorities

### P0 - Verify Regeneration Complete
```bash
# Check prediction counts
bq query "SELECT superseded, COUNT(*) FROM player_prop_predictions WHERE game_date IN ('2026-02-02', '2026-02-03') AND system_id = 'catboost_v9' GROUP BY 1"
```

### P1 - Monitor Feb 3 Games
- Games start evening ET (~7 PM ET / midnight UTC)
- After games complete, compare hit rate for old vs new predictions
- Use `superseded` flag to distinguish

### P2 - Implement Cache Invalidation Fix
- Add Pub/Sub notification when feature store is written
- Worker subscribes and invalidates cache
- Or: Add timestamp check - don't use cache if feature store is newer

---

## Environment Status

| Service | Status | Notes |
|---------|--------|-------|
| prediction-coordinator | Healthy | Batch stalled |
| prediction-worker | Auth issues | Pub/Sub delivery failing |
| nba-phase3-analytics-processors | Up to date | |
| nba-phase4-precompute-processors | Up to date | |
| morning-deployment-check | Working | Returns healthy/0 stale |
| analytics-quality-check | Working | Writing to history table |

---

## Quick Commands

```bash
# Check coordinator status
curl -s "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq '.is_stalled,.progress'

# Check predictions quality
bq query --use_legacy_sql=false "
SELECT COUNT(*), COUNTIF(feature_quality_score IS NOT NULL)
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-03' AND system_id = 'catboost_v9'"

# Check worker errors
gcloud logging read 'resource.labels.service_name="prediction-worker" AND severity>=WARNING' \
  --limit=5 --freshness=10m
```

---

**End of Session 101**
