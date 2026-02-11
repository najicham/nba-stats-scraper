# Session 204 Handoff - Phase 4 Coverage Fix & Pipeline Rerun

**Date:** 2026-02-11
**Previous:** Session 203 (Phase 3 coverage fix, Phase 6 exports)

## Summary

Continued from Session 203 which fixed Phase 3 (200→481 players). This session discovered Phase 4 hadn't re-run after the Phase 3 fix, causing the feature store to only have 192 players. After re-running Phase 4, coverage jumped to 372 feature store players with 282 quality-ready.

## What Was Accomplished

### 1. Root Cause Analysis - Why Pipeline Had Issues

**Three cascading failures identified (Sessions 201-204):**

| Layer | Root Cause | Impact | Fix |
|-------|-----------|--------|-----|
| **Phase 3** | BDL dependency marked `critical: True` | Blocked `/process-date-range` entirely | Changed to `nbac_gamebook_player_stats` (commit `922b8c16`) |
| **Phase 3** | 474 circuit breakers tripped | Locked out players for 24h after failures | Cleared records, made completeness non-blocking (commit `2d1570d9`) |
| **Phase 4** | Phase 4 ran BEFORE Phase 3 fix | Only 200/481 players got composite_factors | Manual re-trigger (this session) |

### 2. Phase 4 Re-run Results

**Coverage funnel for Feb 11:**

| Stage | Before | After | Notes |
|-------|--------|-------|-------|
| upcoming_context (Phase 3) | 200 → 481 | 481 | Fixed in Session 203 |
| shot_zone (Phase 4) | 460 | 460 | Already good |
| daily_cache (Phase 4) | 439 | 439 | Already good |
| composite_factors (Phase 4) | **200** | **481** | Re-triggered this session |
| feature_store (Phase 4) | **192** | **372** | ~2x improvement |
| quality_ready | **114** | **282** | ~2.5x improvement |
| predictions (Phase 5) | 25 | **In progress** | REGENERATE mode running |

### 3. Zero Tolerance Verification

**Confirmed: No non-Vegas defaults in predictions.**

The 4 predictions with defaults on Feb 11 ALL have only Vegas defaults (features 25, 26, 27 = `vegas_points_line`, `vegas_opening_line`, `vegas_line_move`). These are correctly marked optional in `FEATURES_OPTIONAL` (Session 145).

**Feature store default breakdown (372 players):**
- 192 players: zero defaults → quality-ready
- 90 players: only Vegas defaults → quality-ready
- 90 players: non-Vegas defaults → correctly BLOCKED

**Non-Vegas defaults are legitimate data gaps:**
- Shot zones (18-20): 75 players - no shot distribution data (low-minute/new players)
- ppm_avg_last_10 (32): 50 players - missing from daily cache
- Player history (0-4): 28-33 players - insufficient game history
- These players SHOULD be blocked (model performs poorly with fabricated values)

### 4. Frontend Review Issues Status

| Issue | Priority | Status | Notes |
|-------|----------|--------|-------|
| **last_10_results mostly dashes** | P0 | Understood | O/U only computed when player has Odds API line. ~35% coverage is normal. See below. |
| **Player profiles 62 days stale** | P1 | **FIXED** | Regenerated 93 profiles. KAT now dated 2026-02-11. SAFE_OFFSET fix deployed (commit `a564cbcb`). |
| **Date-specific tonight file** | P1 | By design | Only `tonight/all-players.json` exists. No date-specific file. Frontend should use `game_date` field inside the JSON. |
| **Confidence scale** | P2 | By design | Values 87-95 are percentage (0-100 scale). Frontend correctly divides by 100. |
| **Null scores** | P2 | Working | Scores populate when games go final. Chat C fix deployed in Session 202. |

### 5. P0 last_10_results Analysis

**Root cause:** `over_under_result` is only computed when a player had a sportsbook points line for that game. Games without lines get NULL (displayed as dash "-").

**Current coverage (Feb 8-10):**
- Feb 10: 41.7% have O/U results (58/139 players)
- Feb 9: 32.8% (119/363)
- Feb 8: 34.6% (46/133)

**Options to improve (for next session):**
1. **Use current line as retroactive benchmark** - Compare historical points against today's line
2. **Use season average as fallback** - If no line, compute O/U vs season PPG
3. **Add `last_10_lines` array** - Include the line used for each game
4. **Accept 35% coverage** - Only show O/U for games that had real lines

Recommendation: Option 1 or 2 (discuss with frontend team).

## In-Progress / Needs Verification

### Phase 5 Predictions Running
A REGENERATE prediction run was triggered at ~21:19 UTC. The coordinator was loading 282 quality-ready players when context was running low.

**To verify:**
```bash
TOKEN=$(gcloud auth print-identity-token)
curl -s -X GET "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status" \
  -H "Authorization: Bearer $TOKEN"
```

**Expected:** 150-200 predictions generated (282 quality-ready minus those without betting lines)

**If 0 predictions:** Check coordinator logs for quality gate blockers:
```bash
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload:"QUALITY_GATE"' \
  --project=nba-props-platform --limit=5 --format="value(timestamp,textPayload)"
```

### Phase 6 Export Needs Re-trigger
After predictions complete, re-trigger Phase 6 exports to pick up new predictions:
```bash
gcloud scheduler jobs run phase6-tonight-picks-morning --location=us-west2 --project=nba-props-platform
```

## Priority Fixes for Next Session

### 1. Verify Predictions Completed (P0, 5 min)
Check if the REGENERATE run completed and re-trigger Phase 6.

### 2. Fix `bdl_games` Validation Reference (P1, 5 min)
**File:** `orchestration/cloud_functions/phase2_to_phase3/main.py` line 1089
**Change:** `'game_count_table': 'bdl_games'` → `'game_count_table': 'nbac_schedule'`

### 3. Add Orchestrator Health to `/validate-daily` (P1, 1 hour)
Check `_triggered` status in Firestore to catch orchestrator stalls.

### 4. Improve last_10_results O/U Coverage (P1, 1-2 hours)
Options: retroactive line comparison, season average fallback, or `last_10_lines` array.

### 5. Update CLAUDE.md Stale Entry (P2, 2 min)
Remove "Phase 6 scheduler broken" entry - schedulers are correctly configured.

### 6. Clean Up BDL References (P3, 30 min)
Three team processors still reference `bdl_player_boxscores`.

## Commands Reference

```bash
# Check prediction status
TOKEN=$(gcloud auth print-identity-token)
curl -s -X GET "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status" \
  -H "Authorization: Bearer $TOKEN"

# Trigger Phase 6 exports
gcloud scheduler jobs run phase6-tonight-picks-morning --location=us-west2 --project=nba-props-platform

# Check coverage funnel
bq query --use_legacy_sql=false "
SELECT 'feature_store' as stage, COUNT(DISTINCT player_lookup) as players FROM nba_predictions.ml_feature_store_v2 WHERE game_date = '2026-02-11'
UNION ALL SELECT 'quality_ready', COUNTIF(is_quality_ready) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = '2026-02-11'
UNION ALL SELECT 'predictions', COUNT(DISTINCT player_lookup) FROM nba_predictions.player_prop_predictions WHERE game_date = '2026-02-11' AND system_id = 'catboost_v9'"

# Re-trigger Phase 4 if needed
TOKEN=$(gcloud auth print-identity-token)
curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-02-12", "skip_dependency_check": true, "backfill_mode": true}'

# Validate daily pipeline
/validate-daily
```

## Key Learnings

### Phase 4 Doesn't Auto-Retrigger After Manual Phase 3 Runs
When Phase 3 is manually re-triggered (via `/process-date-range`), Phase 4 doesn't automatically re-run because the orchestrator only triggers on Phase 3 completion events. Manual Phase 3 backfills need manual Phase 4 follow-up.

### The Coverage Funnel Is Essential for Diagnosis
The pipeline has 6 stages (Phase 3 → shot zone → daily cache → composite factors → feature store → predictions). A drop at ANY stage cascades. Always check the full funnel when coverage is low.

### Composite Factors Is the Bottleneck
Shot zone (460) and daily cache (439) have good coverage. Composite factors was only 200 because it hadn't been re-triggered. The feature store is bounded by composite_factors coverage.

---

**Session 204 Complete**
