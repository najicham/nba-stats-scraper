# Session 139 Handoff: Quality Gate Overhaul + Source Validation

**Date:** 2026-02-06
**Status:** Code complete, tests passing, schema migrated, NOT YET DEPLOYED

## What Was Done

### Part A: Quality Gate Overhaul (CORE CHANGE)

The prediction system no longer forces garbage predictions at LAST_CALL. Instead:

1. **Hard Floor** - `quality_alert_level = 'red'` or `matchup_quality_pct < 50%` ALWAYS blocks predictions, regardless of mode (including LAST_CALL)
2. **LAST_CALL threshold** - Changed from 0% (force all) to 70%
3. **BACKFILL mode** - New `PredictionMode.BACKFILL` for next-day record-keeping (70% threshold)
4. **Self-healing** - `QualityHealer` re-triggers Phase 4 processors when quality gate detects missing data
5. **PREDICTIONS_SKIPPED alert** - Clear Slack alert with player list, root cause, and recovery instructions
6. **prediction_made_before_game** - New BOOL field on predictions for grading accuracy

**Files changed:**
- `predictions/coordinator/quality_gate.py` - Hard floor, BACKFILL mode, no more forcing
- `predictions/coordinator/quality_healer.py` - NEW: Self-healing module
- `predictions/coordinator/quality_alerts.py` - PREDICTIONS_SKIPPED alert
- `predictions/coordinator/coordinator.py` - Wired healing + BACKFILL + new alert
- `predictions/worker/worker.py` - `prediction_made_before_game` field + helper
- `schemas/bigquery/predictions/01_player_prop_predictions.sql` - New column

### Part B: `/validate-source-alignment` Skill

New skill at `.claude/skills/validate-source-alignment/SKILL.md` (578 lines):
- Quick mode: 5 checks (coverage alignment, default-but-exists bugs, prediction coverage gamebook+lines, default summary)
- Deep mode: +2 checks (value comparison, freshness)
- Detects silent data flow failures where source has data but feature store used defaults

### Part C: Daily Validation Script Updates

- `bin/monitoring/compute_daily_scorecard.py` - Added `is_quality_ready`, category quality, red alert tracking
- `bin/monitoring/daily_reconciliation.py` - Updated Check 3/4 to use quality fields, added Check 6 (quality distribution)
- `bin/monitoring/feature_store_health_check.py` - Switched from `player_daily_cache` to `ml_feature_store_v2` quality fields

### Part D: Documentation Updates (7 files)

- `CLAUDE.md` - [QUALITY], [ISSUES], [QUERIES] sections updated
- `docs/06-reference/quality-columns-reference.md` - `prediction_made_before_game` documented
- `docs/06-reference/feature-quality-monitoring.md` - Hard floor rules section
- `docs/05-development/guides/quality-tracking-system.md` - Quality healer section
- `docs/03-phases/phase4-precompute/ml-feature-store-deepdive.md` - Quality gate integration
- `docs/02-operations/runbooks/feature-store-monitoring.md` - Issue 6 + readiness query
- `docs/06-reference/processor-cards/phase4-ml-feature-store-v2.md` - Success criteria + alerts

### Tests Written

- `tests/unit/prediction_tests/coordinator/test_quality_gate.py` - 32 tests
- `tests/unit/prediction_tests/coordinator/test_quality_healer.py` - 10 tests
- `tests/unit/prediction_tests/coordinator/test_quality_alerts.py` - 8 tests
- All 50 new tests PASS
- All 72 existing feature store tests PASS

### Schema Migration

- `prediction_made_before_game BOOL` added to `player_prop_predictions` (DONE)

## What Still Needs To Happen

### 1. DEPLOY (Critical)
```bash
# Deploy prediction-coordinator (quality gate, healer, alerts)
./bin/deploy-service.sh prediction-coordinator

# Deploy prediction-worker (prediction_made_before_game field)
./bin/deploy-service.sh prediction-worker
```

### 2. Monitor First Live Day
- Watch `#nba-alerts` for `PREDICTIONS_SKIPPED` alerts
- Verify predictions still generate with quality >= 70%
- Check `prediction_made_before_game` is populated:
```sql
SELECT prediction_made_before_game, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE()
  AND system_id = 'catboost_v9'
GROUP BY 1;
```

### 3. Test BACKFILL Mode (next day)
```bash
curl -X POST https://prediction-coordinator-URL/start \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"2026-02-06","prediction_run_mode":"BACKFILL"}'
```

### 4. Run `/validate-source-alignment`
After deployment, validate the feature store matches source data:
```
/validate-source-alignment quick
```

## Architecture Summary

```
Quality Gate Flow (Session 139):

1. Quality gate checks all players
   ├── Hard floor check (alert=red OR matchup<50%)
   │   └── BLOCKED → diagnosed missing processor
   ├── Threshold check (mode-dependent: 85%/80%/70%)
   │   └── BELOW → skipped
   └── Passes → predict

2. If players hard-blocked AND mode >= RETRY:
   └── QualityHealer.attempt_heal()
       ├── POST Phase 4 /process-date (specific processors)
       ├── Wait up to 5 min
       ├── Re-trigger MLFeatureStoreProcessor
       └── Re-run quality gate for blocked players

3. If still blocked after healing:
   └── send_predictions_skipped_alert() → #nba-alerts
       └── Includes player list, root cause, BACKFILL instructions

4. Next day: BACKFILL mode generates record-keeping predictions
   └── prediction_made_before_game = FALSE
```

## Key Design Decisions

1. **No more forcing** - LAST_CALL at 0% was creating garbage predictions that hurt ROI. Now 70% with hard floor.
2. **Hard floor is absolute** - `quality_alert_level='red'` blocks ALL modes. This prevents the Session 132 scenario.
3. **Self-healing is limited** - Max 1 attempt per batch. Non-fatal on failure. Tracked in Firestore.
4. **BACKFILL is distinct** - Requires `game_date < today`. Predictions marked `prediction_made_before_game=FALSE`.
5. **Alerts are actionable** - Include player list, root cause, and exact BACKFILL curl command.
