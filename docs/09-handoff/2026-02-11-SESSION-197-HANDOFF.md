# Session 197 Handoff — Quality Gate Falsy Zero Bug, Phase 6 Deploy, Star Players Resolution

**Date:** 2026-02-11 (7:40 AM - 11 AM ET)
**Commits:** `bc2c03d2` fix: Quality gate treating 0 required_default_count as falsy
**Status:** Fix committed and deploying, verification pending

---

## Critical Finding: Quality Gate Falsy Zero Bug

### The Bug

`predictions/coordinator/quality_gate.py` line 210 (now fixed):

```python
# OLD (buggy):
'required_default_count': int(row.required_default_count or row.default_feature_count or 0),

# NEW (fixed):
'required_default_count': int(row.required_default_count if row.required_default_count is not None else (row.default_feature_count or 0)),
```

**Root cause:** Python's `or` operator treats `0` as falsy. When `required_default_count = 0` (correct for players with only optional vegas defaults on features 25-27), `0 or 3` evaluates to `3`, causing the hard floor check to block them.

**Impact:** On Feb 11 (14 games), **92 of 192 players** in the feature store had only vegas defaults (required_default_count=0, default_feature_count=3) and were incorrectly blocked. Only 7 predictions were generated instead of potentially 20-30+.

**Impact across dates:**

| Date | Total Players | Vegas-only Blocked | Quality Ready |
|------|--------------|-------------------|---------------|
| Feb 11 | 192 | **92** | 113 |
| Feb 10 | 137 | **31** | 59 |
| Feb 9 | 341 | **83** | 162 |
| Feb 8 | 145 | **55** | 110 |

**This bug existed since Session 145** when `required_default_count` was introduced with optional vegas features. Every day since then, players with only vegas defaults were silently blocked.

### Deployment Status

- Commit `bc2c03d2` pushed to main at ~15:47 UTC
- Cloud Build `915753a1` deploying `prediction-coordinator` (was WORKING as of 15:50 UTC)
- Next hourly `/start` at 16:01 UTC should use the fixed code if build completes in time
- If build not done by 16:01, the 17:01 run will be the first with the fix

### Verification Steps (MUST DO)

```bash
# 1. Verify build completed
gcloud builds describe 915753a1-8bed-457d-9107-ac473f4d7707 --region=us-west2 --project=nba-props-platform --format="value(status)"

# 2. Check prediction count after next /start run
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-11'
GROUP BY 1 ORDER BY 1"

# Expected: Significantly more than 7 per model (likely 15-30+)

# 3. Check coordinator logs for quality gate summary
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-coordinator" AND textPayload=~"QUALITY_GATE_SUMMARY"' --project=nba-props-platform --limit=5 --format="value(timestamp,textPayload)" --freshness=2h

# Expected: to_predict should be much higher, hard_blocked should be lower

# 4. Verify no more false "HARD_FLOOR: Blocking" for vegas-only players
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-coordinator" AND textPayload=~"HARD_FLOOR"' --project=nba-props-platform --limit=10 --format="value(timestamp,textPayload)" --freshness=2h

# Remaining blocks should only be for players with REAL required defaults (features 18-20 shot zone, etc.)
```

---

## Completed Actions

### 1. Phase 6 Export Function Deployed

- Fixed `exc_info` syntax error (already done in commit `8803f556`)
- Deployed Phase 6 Cloud Function with latest code including `created_at` per-pick timestamps
- Cloud Build trigger `deploy-phase6-export` already existed (created 2026-02-11 06:03 UTC)
- Watches: `orchestration/cloud_functions/phase6_export/**`, `data_processors/publishing/**`, `backfill_jobs/publishing/**`, `shared/**`

### 2. Star Players Investigation — NOT a Bug

The 28 "missing" star players from the daily cache are **genuinely injured/inactive**:

| Player | Status | Injury |
|--------|--------|--------|
| Jayson Tatum | Inactive | Right Achilles; Repair |
| Damian Lillard | Inactive | Left Achilles Tendon; Injury Management |
| Tyrese Haliburton | Inactive | Right Achilles Tendon; Tear |
| Dejounte Murray | Inactive | Right Achilles; Rupture |
| Fred VanVleet | Inactive | Right Knee; ACL Repair |
| Bradley Beal | Inactive | Left Hip; Fracture |
| + ~22 others | Inactive/G-League/DNP | Various |

All confirmed via `nba_raw.nbac_gamebook_player_stats` — `player_status = 'inactive'` with real injury reasons. The cache correctly excludes them.

**Optimization opportunity (not urgent):** These players still appear in `upcoming_player_game_context` and the feature store, wasting Phase 4 computation (~63% of feature computation is for players that will never be predicted). Could apply coordinator filters earlier in the pipeline.

### 3. tonight/all-players.json

Root cause was the Phase 6 function being stale (no auto-deploy trigger previously). Now deployed with latest code. The exporter already correctly uses `upcoming_player_game_context`. Should work on next export trigger.

### 4. Daily Validation Results (2 AM ET)

| Check | Status | Details |
|-------|--------|---------|
| Deployment Drift | ⚠️ | `nba-grading-service` 1 commit behind (multi-model v2 exports) |
| Phase 3 (Feb 10) | ✅ | 4 games, 139 records, 89 active — correct |
| Features (Feb 11) | ✅ | 113/192 quality_ready, matchup=100%, history=93% |
| Model Drift | 🔴 | Champion 43.7% HR this week, 41 days stale |
| QUANT Volume | 🔴 | Only 7 predictions (bug blocked more — now fixed) |

---

## Open Issues for Next Session

### Priority 1: Verify Quality Gate Fix Impact

After the coordinator deploys and the next `/start` fires:
- Check prediction count increased significantly
- Check QUANT Q43/Q45 volume specifically — they should also benefit
- If predictions still low, check coordinator logs for remaining blockers

### Priority 2: Deploy Grading Service

`nba-grading-service` is 1 commit behind (`6dfc2b4c` multi-model v2 exports, fix performance view 30-day cap, frontend API docs). Deploy:

```bash
./bin/deploy-service.sh nba-grading-service
```

### Priority 3: Champion Model Decay

Champion `catboost_v9` continues declining:
- Jan 18 week: 56.4% HR
- Jan 25 week: 51.6% HR
- Feb 1 week: 48.2% HR
- Feb 8 week: 43.7% HR (below breakeven)

41 days stale. QUANT Q43 is the designed replacement (65.8% HR when fresh in backtests). With the quality gate fix, Q43 should now produce enough volume to evaluate. After 2-3 days of full-volume data, assess promotion.

### Priority 4: Historical Impact Assessment

The falsy zero bug has been blocking predictions since Session 145. Consider:
- How many predictions were lost per day?
- Should any dates be backfilled?
- Check if QUANT shadow models were especially affected (they rely on the same quality gate)

### Priority 5: Phase 6 Scheduler Fix

From Session 196 handoff (still open): Two Cloud Scheduler jobs publish to non-existent `nba-phase6-export` topic. Should be `nba-phase6-export-trigger`. This causes morning/pregame exports not to fire automatically.

---

## Files Changed

| File | Change | Deployed? |
|------|--------|-----------|
| `predictions/coordinator/quality_gate.py` | Fix falsy zero in required_default_count | Deploying (Cloud Build 915753a1) |

## Previous Session Files (Session 196, already deployed)

| File | Change | Deployed? |
|------|--------|-----------|
| `data_processors/publishing/all_subsets_picks_exporter.py` | Per-pick `created_at` | YES (Phase 6 deployed this session) |
| `data_processors/publishing/season_subset_picks_exporter.py` | Per-pick `created_at` | YES (Phase 6 deployed this session) |

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-11-SESSION-197-HANDOFF.md

# 2. Verify coordinator deployed with fix
gcloud run services describe prediction-coordinator --region=us-west2 --format="value(metadata.labels.commit-sha)"
# Expected: bc2c03d2 or later

# 3. Check prediction volume (should be 15-30+ per model now)
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-11'
GROUP BY 1 ORDER BY 1"

# 4. Check QUANT volume specifically
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE '%q4%' AND game_date >= '2026-02-11'
GROUP BY 1, 2 ORDER BY 2 DESC, 1"

# 5. Deploy grading service
./bin/deploy-service.sh nba-grading-service

# 6. Run daily validation
/validate-daily
```
