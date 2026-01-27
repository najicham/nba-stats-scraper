# Pipeline Recovery Handoff

**Date**: 2026-01-27 ~1:00 AM ET
**Status**: Bug fixes committed, Phase 3 needs redeployment
**Priority**: P1 - Complete recovery after quota reset

---

## TL;DR

Four bugs were fixed that were blocking the pipeline. Phase 3 needs one more deployment, then trigger the pipeline after the quota resets at 3 AM ET.

---

## Current State

### What Was Fixed This Session

| Bug | File | Commit | Status |
|-----|------|--------|--------|
| `new_state` undefined | `circuit_breaker_mixin.py` | `8cb96558` | Deployed |
| Missing `flush_unresolved_players()` | `player_registry.py` | `8cb96558` | Deployed |
| Non-critical deps blocking | `dependency_mixin.py` | `7a0c8c71` | Deployed |
| `parse_minutes` not imported | `async_upcoming_player_game_context_processor.py` | `0c9581a6` | **NOT DEPLOYED** |

### Deployment Status

| Service | Deployed Commit | Latest Commit | Action Needed |
|---------|-----------------|---------------|---------------|
| `nba-phase3-analytics-processors` | `7a0c8c71` | `0c9581a6` | **REDEPLOY** |
| `nba-phase4-precompute-processors` | `8cb96558` | `0c9581a6` | OK (no changes affect Phase 4) |

---

## Your Tasks

### Task 1: Redeploy Phase 3 (Required)

```bash
bash bin/analytics/deploy/deploy_analytics_processors.sh
```

This deploys the `parse_minutes` fix. Takes ~10 minutes.

### Task 2: Wait for Quota Reset

- **Quota resets**: 3:00 AM ET (midnight Pacific)
- **Self-healing window**: 3:00-3:30 AM ET (auto-enables monitoring)

### Task 3: Trigger Pipeline (After 3 AM ET)

```bash
# Trigger Phase 3
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Wait 5 minutes, then trigger Phase 4
gcloud scheduler jobs run same-day-phase4 --location=us-west2

# Wait 5 minutes, then trigger predictions
gcloud scheduler jobs run same-day-predictions --location=us-west2
```

### Task 4: Validate Predictions

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"
```

**Expected**: > 0 predictions (7 games scheduled for Jan 27)

---

## Troubleshooting

### If Phase 3 Still Fails

Check logs for the specific error:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-phase3-analytics-processors AND textPayload:error" --limit=20 --format="value(textPayload)"
```

### If No Predictions After Pipeline

Check each phase:
```bash
# Phase 3 - should have upcoming_player_game_context for today
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM nba_analytics.upcoming_player_game_context
WHERE game_date = CURRENT_DATE()"

# Phase 4 - should have ml_feature_store for today
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()"
```

---

## Context: What Happened

### Original Issue (from previous handoff)
- BigQuery quota exceeded (1,500 load jobs/day limit)
- Batching fix deployed to reduce usage from 2,466 → 32 jobs/day

### Issues Discovered This Session
1. **Code bugs** in circuit breaker and player registry
2. **Non-critical stale dependencies** were blocking processors (e.g., `odds_api_game_lines` marked as `critical: False` but still blocking when stale)
3. **Queue backlog** - old dates from Jan 1-7 were stuck in retry loop (abandoned)
4. **Missing import** - `parse_minutes` function not imported in async processor

### Root Cause Chain
```
Raw data stale check → Phase 3 blocked → Phase 4 blocked → No ML features → No predictions
```

Fixed by:
- Making non-critical stale deps into warnings (not failures)
- Fixing code bugs
- Abandoning stuck queue entries

---

## Files Changed

```
shared/processors/patterns/circuit_breaker_mixin.py      # new_state fix
data_processors/analytics/player_game_summary/sources/player_registry.py  # delegate methods
data_processors/analytics/mixins/dependency_mixin.py     # non-critical deps fix
data_processors/analytics/upcoming_player_game_context/async_upcoming_player_game_context_processor.py  # parse_minutes import
```

---

## Success Criteria

- [ ] Phase 3 deployed with commit `0c9581a6`
- [ ] `upcoming_player_game_context` has data for today
- [ ] `ml_feature_store_v2` has data for today
- [ ] Predictions generated for today (count > 0)
- [ ] No quota errors in logs

---

## Timeline

| Time (ET) | Event |
|-----------|-------|
| ~1:00 AM | This handoff created |
| 3:00 AM | Quota resets |
| 3:00-3:30 AM | Self-healing window |
| After 3:00 AM | Safe to trigger pipeline |
