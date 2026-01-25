# Quick Deployment Guide - 2026-01-25 Session

## Critical Path Deployment (Do These First)

### 1. Deploy Auto-Retry Processor Fix ⚠️ CRITICAL
```bash
cd /home/naji/code/nba-stats-scraper
./bin/orchestrators/deploy_auto_retry_processor.sh
```

**What it fixes:**
- Stops 404 errors from non-existent Pub/Sub topics
- Enables automatic retry processing
- Unblocks GSW@MIN boxscore recovery

**Verify:**
```bash
# Check logs (should no longer see 404 errors)
gcloud functions logs read auto-retry-processor --region us-west2 --limit 10

# Should see successful HTTP calls instead of Pub/Sub errors
```

---

### 2. Setup Fallback Subscriptions
```bash
./bin/orchestrators/setup_fallback_subscriptions.sh
```

**What it does:**
- Creates 4 Pub/Sub subscriptions for fallback topics
- Enables fallback processing paths
- Improves pipeline resilience

**Verify:**
```bash
gcloud pubsub subscriptions list | grep fallback
# Should see 4 subscriptions: phase2, phase3, phase4, phase5
```

---

### 3. Recover Missing GSW@MIN Boxscore
```bash
# Option A: Wait for auto-retry (runs every 15 minutes)
# Option B: Manual backfill
python bin/backfill/bdl_boxscores.py --date 2026-01-24

# Verify recovery
python bin/validation/validate_backfill.py --phase raw --date 2026-01-24
```

---

## Test New Validators

### Quality Trend Monitoring
```bash
python bin/validation/quality_trend_monitor.py --date 2026-01-25
```

**What it checks:**
- Feature quality score trends
- Player count trends
- NULL rate increases
- Processing time anomalies

---

### Cross-Phase Consistency
```bash
python bin/validation/cross_phase_consistency.py --date 2026-01-24
```

**What it checks:**
- Data flows through all phases
- Entity counts match between phases
- Orphan records detected

---

### Entity Tracing (Debug Tool)
```bash
# Trace a player through all phases
python bin/validation/trace_entity.py --player "lebron-james" --date 2026-01-24

# Trace a game through all phases
python bin/validation/trace_entity.py --game 0022500644
```

**What it shows:**
- Which phases have data
- Where pipeline stops
- Root cause of issues

---

### Post-Backfill Validation
```bash
# After any backfill, verify it worked
python bin/validation/validate_backfill.py --phase raw --date 2026-01-24
```

**What it validates:**
- Gap is filled
- Data quality acceptable
- Downstream phases reprocessed

---

## Verification Commands

### Check System Health
```bash
# Check failed processor queue
bq query --use_legacy_sql=false "
SELECT game_date, processor_name, status, retry_count, error_message
FROM nba_orchestration.failed_processor_queue
WHERE status IN ('pending', 'retrying')
ORDER BY first_failure_at DESC
LIMIT 10"

# Check game ID mapping view
bq query --use_legacy_sql=false "
SELECT * FROM nba_raw.v_game_id_mappings
WHERE game_date = '2026-01-24'
LIMIT 5"

# Check data completeness for today
bq query --use_legacy_sql=false "
SELECT
  'schedule' as phase, COUNT(*) as records FROM nba_raw.v_nbac_schedule_latest WHERE game_date = CURRENT_DATE()
UNION ALL SELECT 'boxscores', COUNT(DISTINCT game_id) FROM nba_raw.bdl_player_boxscores WHERE game_date = CURRENT_DATE()
UNION ALL SELECT 'analytics', COUNT(DISTINCT player_lookup) FROM nba_analytics.player_game_summary WHERE game_date = CURRENT_DATE()
UNION ALL SELECT 'features', COUNT(DISTINCT player_lookup) FROM nba_precompute.ml_feature_store WHERE game_date = CURRENT_DATE()
UNION ALL SELECT 'predictions', COUNT(DISTINCT player_lookup) FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE()
"
```

---

## Integration Tasks (For Next Session)

### Integrate Phase 4→5 Gate
```python
# Add to /orchestration/cloud_functions/phase4_to_phase5/main.py

from validation.validators.gates.phase4_to_phase5_gate import evaluate_phase4_to_phase5_gate

def should_trigger_phase5(target_date: str) -> bool:
    """Check if Phase 5 should be triggered."""

    result = evaluate_phase4_to_phase5_gate(target_date)

    if result.decision == GateDecision.BLOCK:
        logger.error(f"Phase 4→5 gate BLOCKING: {result.blocking_reasons}")
        send_alert(f"Phase 5 blocked for {target_date}", result.blocking_reasons)
        return False

    if result.decision == GateDecision.WARN_AND_PROCEED:
        logger.warning(f"Phase 4→5 gate WARNINGS: {result.warnings}")
        send_alert(f"Phase 5 warnings for {target_date}", result.warnings)

    logger.info(f"Phase 4→5 gate PASSED for {target_date}")
    return True
```

---

## Files Created (19 total)

### Validators (9 files)
- `validation/validators/gates/__init__.py`
- `validation/validators/gates/base_gate.py`
- `validation/validators/gates/phase4_to_phase5_gate.py`
- `validation/validators/trends/__init__.py`
- `validation/validators/trends/quality_trend_validator.py`
- `validation/validators/consistency/__init__.py`
- `validation/validators/consistency/cross_phase_validator.py`
- `validation/validators/recovery/__init__.py`
- `validation/validators/recovery/post_backfill_validator.py`

### CLI Scripts (4 files)
- `bin/validation/quality_trend_monitor.py`
- `bin/validation/cross_phase_consistency.py`
- `bin/validation/validate_backfill.py`
- `bin/validation/trace_entity.py`

### Infrastructure (2 files)
- `bin/orchestrators/setup_fallback_subscriptions.sh`
- `schemas/bigquery/raw/v_game_id_mappings.sql`

### Documentation (4 files)
- `docs/08-projects/current/validation-framework/MASTER-IMPROVEMENT-PLAN.md`
- `docs/09-handoff/2026-01-25-SESSION-COMPLETE-HANDOFF.md`
- `DEPLOYMENT-GUIDE.md` (this file)

### Modified (2 files)
- `orchestration/cloud_functions/auto_retry_processor/main.py`
- `shared/utils/__init__.py`

---

## Next Steps

1. ✅ Deploy auto-retry processor (CRITICAL)
2. ✅ Setup fallback subscriptions
3. ✅ Test validators on recent data
4. 🔄 Integrate Phase 4→5 gate into orchestrator
5. 🔄 Setup validation scheduling (Cloud Scheduler)
6. 🔄 Implement remaining P1/P2 features

---

*Created: 2026-01-25*
*Session: Comprehensive System Improvements*
