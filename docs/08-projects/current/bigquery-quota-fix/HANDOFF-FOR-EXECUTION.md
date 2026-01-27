# Handoff: Execute Pipeline Tonight

**For**: Claude Sonnet Session
**Date**: 2026-01-26 ~10:30 PM ET
**Status**: Ready to Execute

---

## What You Need To Do

### If Running Pipeline Tonight (Before 3 AM ET)

Execute these commands in order:

```bash
# Step 1: Disable monitoring to avoid quota errors
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=true" \
    --quiet
done

# Step 2: Trigger Phase 3
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Step 3: Wait 5-10 minutes, then check completion
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=20 | grep -i "complete\|success"

# Step 4: Verify predictions
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"
```

### After 3:00 AM ET (Quota Reset)

**Self-healing is now automatic!**

The batch writer auto-enables monitoring between 12:00-12:30 AM Pacific (3:00-3:30 AM ET).
No manual action needed.

If you want to manually re-enable anyway:
```bash
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=false" \
    --quiet
done
```

---

## Context

- BigQuery has 1,500 load jobs/table/day limit
- We were using 2,466/day (164%) - quota exceeded
- Batching fix deployed (now uses 32/day = 2%)
- But quota already exceeded TODAY, so monitoring writes still fail
- Solution: Disable monitoring writes for tonight, re-enable after quota reset

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `docs/08-projects/current/bigquery-quota-fix/README.md` | Full project documentation |
| `docs/08-projects/current/bigquery-quota-fix/TONIGHT-RUNBOOK.md` | Tonight's operations guide |
| `docs/08-projects/current/bigquery-quota-fix/HANDOFF-FOR-EXECUTION.md` | This file |

---

## What Was Already Done

1. ✅ Batching fix implemented (`shared/utils/bigquery_batch_writer.py`)
2. ✅ `MONITORING_WRITES_DISABLED` env var added
3. ✅ Code pushed to origin/main
4. ✅ Phase 3 and Phase 4 Cloud Run services deployed with new code
5. ❌ Monitoring not yet disabled (needs execution above)

---

## Success Criteria

- [ ] Monitoring disabled on phase services
- [ ] Phase 3 triggers successfully
- [ ] Phase 4 triggers successfully
- [ ] Predictions generated for today
- [ ] Monitoring re-enabled after 3 AM ET

---

## If Something Goes Wrong

### Check logs:
```bash
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50
```

### Check env var was set:
```bash
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="yaml(spec.template.spec.containers[0].env)"
```

### Force new revision:
```bash
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --update-env-vars="MONITORING_WRITES_DISABLED=true"
```

---

## Timeline

| Time | Event |
|------|-------|
| ~10:30 PM ET | Handoff created |
| When ready | Disable monitoring + trigger pipeline |
| 3:00 AM ET | Quota resets (midnight Pacific) |
| After 3 AM | Re-enable monitoring |
| Tomorrow | Everything automatic (batching handles it) |
