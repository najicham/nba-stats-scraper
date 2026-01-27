# Investigation Handoff - For Sonnet Agent

## Current Status: INVESTIGATION IN PROGRESS

**Handoff Time**: 2026-01-27 ~14:00 PST
**From**: Opus 4.5 initial investigation
**To**: Sonnet for deeper investigation

---

## Summary of Findings

### Issue #1: BDL Data Incomplete ✅ RESOLVED
- **Root Cause**: BDL API returned stale/incomplete data for 4/7 games
- **Impact**: Analytics using NBAC (correct), so no action needed
- **Status**: DOCUMENTED, no fix required

### Issue #2: Game_ID Format Mismatch ⚠️ NEEDS REPROCESSING
- **Root Cause**: Player uses AWAY_HOME, Team uses HOME_AWAY format
- **Fix**: Commit d3066c88 adds game_id_reversed handling
- **Status**: Fix committed but data not reprocessed
- **Action Needed**: Reprocess Jan 26 analytics

### Issue #3: No Predictions Generated 🔴 UNDER INVESTIGATION
- **Symptom**: Zero predictions for Jan 26 and Jan 27
- **Context**:
  - Phase 3 shows SUCCESS for all processors on Jan 26
  - ML Feature Store has 239 records for Jan 26
  - Betting lines exist (122 players for Jan 26, 107 for Jan 27)
  - Last predictions: Jan 25 (936 predictions)
- **Status**: ROOT CAUSE UNKNOWN

---

## Data State Summary

### What EXISTS for Jan 26:
| Data | Count | Status |
|------|-------|--------|
| Raw boxscores (NBAC) | 226 | ✅ Complete |
| Raw boxscores (BDL) | 246 | ⚠️ Incomplete for 4 games |
| Analytics (player_game_summary) | 226 | ✅ Present |
| ML Features | 239 | ✅ Present |
| Betting Lines | 201,060 | ✅ Present (122 players) |
| Predictions | 0 | ❌ Missing |

### What EXISTS for Jan 27 (today):
| Data | Count | Status |
|------|-------|--------|
| Betting Lines | 177,910 | ✅ Present (107 players) |
| ML Features | 236 | ✅ Present |
| Predictions | 0 | ❌ Missing |

---

## Investigation Leads for Sonnet

### Priority 1: Why aren't predictions generating?

The pipeline has all prerequisites:
- ✅ Phase 3 complete
- ✅ ML features exist
- ✅ Betting lines exist

Check these:

1. **Phase 4 (Precompute) status**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT game_date, COUNT(*) as records
   FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
   WHERE game_date >= '2026-01-25'
   GROUP BY game_date ORDER BY game_date DESC"
   ```

2. **Phase 5 trigger conditions**
   - Is Phase 4 triggering Phase 5?
   - Check Cloud Run prediction-worker logs

3. **Prediction worker errors**
   ```bash
   gcloud run services logs read prediction-worker \
     --region=us-west2 --limit=50
   ```

4. **Firestore orchestration state**
   ```python
   from google.cloud import firestore
   db = firestore.Client()
   # Check phase4_completion and phase5_completion
   for phase in ['phase4_completion', 'phase5_completion']:
       doc = db.collection(phase).document('2026-01-26').get()
       print(f"{phase}: {doc.to_dict() if doc.exists else 'NOT FOUND'}")
   ```

### Priority 2: Validate game_id fix deployment

1. **Check Cloud Run service version**
   ```bash
   gcloud run services describe nba-phase3-analytics-processors \
     --region=us-west2 --format='value(status.traffic[0].revisionName)'
   ```

2. **Verify fix in deployed code**
   - Look for `game_id_reversed` in the service

3. **Reprocess Jan 26 if fix is deployed**
   ```bash
   # Trigger reprocessing
   python data_processors/analytics/player_game_summary/player_game_summary_processor.py \
     --date 2026-01-26
   ```

### Priority 3: Run lineage validation

Use the `/validate-lineage` skill to check cascade integrity for Jan 20-26.

---

## Queries Used in Investigation

### Source discrepancy query
```sql
WITH nbac AS (
  SELECT player_lookup, game_date, points as nbac_points, ROUND(minutes_decimal, 0) as nbac_mins
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date = '2026-01-26'
),
bdl AS (
  SELECT player_lookup, game_date, CAST(points AS INT64) as bdl_points, CAST(minutes AS INT64) as bdl_mins
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date = '2026-01-26'
)
SELECT n.player_lookup, n.nbac_points, b.bdl_points, n.nbac_points - b.bdl_points as diff
FROM nbac n JOIN bdl b ON n.player_lookup = b.player_lookup
WHERE n.nbac_points != b.bdl_points
ORDER BY ABS(n.nbac_points - b.bdl_points) DESC
```

### Game_id format mismatch query
```sql
SELECT DISTINCT
  p.game_id as player_game_id,
  t.game_id as team_game_id,
  CASE WHEN t.game_id IS NULL THEN 'NO MATCH' ELSE 'MATCHED' END
FROM `nba-props-platform.nba_analytics.player_game_summary` p
LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
  ON p.game_id = t.game_id AND p.game_date = t.game_date AND p.team_abbr = t.team_abbr
WHERE p.game_date = '2026-01-26'
```

### Prediction status query
```sql
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2026-01-24' AND is_active = TRUE
GROUP BY game_date ORDER BY game_date DESC
```

---

## Files Created

1. `docs/08-projects/current/2026-01-27-data-quality-investigation/README.md` - Main project doc
2. `docs/08-projects/current/2026-01-27-data-quality-investigation/findings.md` - Investigation findings
3. `docs/08-projects/current/2026-01-27-data-quality-investigation/handoff-to-sonnet.md` - This file

---

## Expected Outcomes

After Sonnet investigation:
1. ✅ Root cause identified for missing predictions
2. ✅ Predictions generating for Jan 26/27
3. ✅ Game_id fix validated and data reprocessed
4. ✅ Usage_rate coverage improved to 90%+

---

## Context Files to Read

If you need more context:
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - Main processor
- `predictions/` directory - Prediction systems
- `orchestration/workflow_executor.py` - Workflow logic
- `docs/02-operations/daily-operations-runbook.md` - Operations guide
