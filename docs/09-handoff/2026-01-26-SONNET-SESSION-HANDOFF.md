# Handoff: Pipeline Recovery & Validation

**For**: Claude Sonnet Session
**Date**: 2026-01-26 ~10:45 PM ET
**Priority**: P1 - Pipeline needs to generate predictions

---

## TL;DR

The pipeline was blocked by BigQuery quota limits. Everything is now fixed and deployed. You need to:

1. **Trigger the pipeline** (if predictions not already generated)
2. **Validate predictions exist** for today
3. **Optionally verify** self-healing works after midnight

---

## Current State

### What Was Wrong
- BigQuery has 1,500 load jobs/table/day limit (hard limit)
- We were using 2,466/day (164% of quota)
- Pipeline blocked, 0 predictions generated

### What Was Fixed
- **Batching**: Reduces quota from 2,466 → 32 jobs/day (98% reduction)
- **Emergency mode**: `MONITORING_WRITES_DISABLED=true` skips monitoring writes
- **Self-healing**: Auto-enables monitoring after midnight Pacific

### Current Deployment Status

| Service | Status | Monitoring |
|---------|--------|------------|
| `nba-phase2-raw-processors` | ✅ Deployed | DISABLED |
| `nba-phase3-analytics-processors` | ✅ Deployed | DISABLED |
| `nba-phase4-precompute-processors` | ✅ Deployed | DISABLED |

**Pipeline is ready to run without hitting quota errors.**

---

## Your Tasks

### Task 1: Check If Pipeline Already Ran Today

```bash
# Check for today's predictions
bq query --use_legacy_sql=false "
SELECT COUNT(*) as prediction_count
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"
```

**If count > 0**: Pipeline already ran, skip to Task 3
**If count = 0**: Proceed to Task 2

---

### Task 2: Trigger Pipeline (If Needed)

```bash
# Trigger Phase 3 (analytics)
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Wait 5-10 minutes for Phase 3 to complete
# Phase 4 and 5 should auto-trigger after Phase 3
```

**Monitor progress:**
```bash
# Check Phase 3 logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=30 | grep -iE "complete|success|error|failed"

# Check Phase 4 logs (after Phase 3 completes)
gcloud run services logs read nba-phase4-precompute-processors \
  --region=us-west2 --limit=30 | grep -iE "complete|success|error|failed"
```

---

### Task 3: Validate Predictions

```bash
# Count predictions for today
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_id) as unique_players,
  COUNT(DISTINCT game_id) as unique_games
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"
```

**Expected**:
- `total_predictions`: Should be > 0 (typically 500-2000 depending on games)
- `unique_players`: Should match number of active players in today's games
- `unique_games`: Should match number of NBA games today

**Check today's games:**
```bash
bq query --use_legacy_sql=false "
SELECT game_id, home_team, away_team, game_status
FROM nba_raw.bdl_games
WHERE game_date = CURRENT_DATE()"
```

---

### Task 4: Verify Self-Healing (Optional - After 3 AM ET)

After quota resets at 3:00 AM ET (midnight Pacific), the self-healing should auto-enable monitoring.

**To verify (run after 3:00 AM ET):**
```bash
# Check logs for self-healing message
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50 | grep -i "auto-enabling\|quota reset"
```

**The self-healing window is 12:00-12:30 AM Pacific (3:00-3:30 AM ET).**

---

## Troubleshooting

### If Phase 3 Fails

```bash
# Check detailed error
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=100 | grep -iE "error|exception|failed" | head -20
```

**Common issues:**
- If still quota error: Env var may not have propagated. Wait 2 min and retry.
- If different error: Check the specific error message.

### If No Predictions After Phase 4

```bash
# Check Phase 5 (predictions)
gcloud run services logs read predictions-coordinator \
  --region=us-west2 --limit=50 | grep -iE "complete|success|error"
```

### If You Need to Re-disable Monitoring

```bash
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=true" \
    --quiet
done
```

### If You Need to Re-enable Monitoring

```bash
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=false" \
    --quiet
done
```

---

## Context: What Happened This Session

### Problem Discovery
1. Pipeline was blocked by BigQuery quota exceeded
2. Root cause: Each monitoring write = 1 load job, 2,466/day exceeds 1,500 limit

### Solution Implemented
1. **Batching**: `shared/utils/bigquery_batch_writer.py` - batches 100 records per write
2. **Emergency disable**: `MONITORING_WRITES_DISABLED` env var
3. **Self-healing**: Auto-enables monitoring after midnight Pacific

### Code Changes
- Commit `129d0185`: Initial batching implementation
- Commit `6e84130a`: Add MONITORING_WRITES_DISABLED env var
- Commit `db28159f`: Add self-healing + documentation
- Commit `bc8de84c`: Update handoff with deployed status

### Documentation Created
- `docs/08-projects/current/bigquery-quota-fix/README.md` - Full project docs
- `docs/08-projects/current/bigquery-quota-fix/TONIGHT-RUNBOOK.md` - Operations guide
- `docs/08-projects/current/bigquery-quota-fix/HANDOFF-FOR-EXECUTION.md` - Execution guide

---

## Architecture Decision: Firestore Migration

We also discussed migrating circuit breaker state to Firestore for faster reads (500ms → 10ms). Decision:

**For now**: Keep everything in BigQuery with batching
- Batching solves the quota problem (2% usage)
- No migration risk
- Team knows BigQuery

**Future consideration**: Migrate circuit breaker to Firestore if:
- We need faster circuit breaker reads
- We hit quota again despite batching (would need 47x growth)

See: `docs/08-projects/current/monitoring-storage-evaluation/` for full analysis.

---

## Timeline

| Time (ET) | Event |
|-----------|-------|
| ~10:45 PM | This handoff created, services deployed |
| When triggered | Pipeline runs with monitoring disabled |
| 3:00 AM | Quota resets (midnight Pacific) |
| 3:00-3:30 AM | Self-healing enables monitoring |
| Tomorrow | Everything automatic (2% quota) |

---

## Success Criteria

- [ ] Predictions exist for today (`prediction_count > 0`)
- [ ] Phase 3 completed successfully
- [ ] Phase 4 completed successfully
- [ ] No quota errors in logs
- [ ] (After 3 AM) Self-healing message in logs

---

## Files to Reference

| Purpose | File |
|---------|------|
| Full BigQuery quota docs | `docs/08-projects/current/bigquery-quota-fix/README.md` |
| Tonight's runbook | `docs/08-projects/current/bigquery-quota-fix/TONIGHT-RUNBOOK.md` |
| Batch writer code | `shared/utils/bigquery_batch_writer.py` |
| Firestore decision | `docs/08-projects/current/monitoring-storage-evaluation/` |

---

## Questions?

If something is unclear:
1. Check the logs first (commands above)
2. Check the documentation files listed above
3. The batch writer code has detailed comments

**Key insight**: The batching fix means this quota issue should never happen again. Tonight is just about getting through while quota is already exceeded.
