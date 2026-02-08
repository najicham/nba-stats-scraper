# Next Session: Backfill Pub/Sub Stalling Investigation

**Recommended agent:** Opus (requires live infrastructure debugging, unclear root cause)

## Copy-paste prompt:

```
Session: Fix Backfill Pub/Sub Stalling

Read the handoff: docs/09-handoff/2026-02-08-SESSION-164-HANDOFF.md

## Problem

Manual prediction backfills via the coordinator /start endpoint create batches, but workers NEVER process them. The batch stays at 0/N completed for minutes then stalls.

Key facts:
- Coordinator publishes to `prediction-request-prod` Pub/Sub topic
- Push subscription pushes to `https://prediction-worker-f7p3g7f6ya-wl.a.run.app/predict`
- Worker passes /health and /health/deep checks
- No error logs in coordinator or worker during stall
- Earlier in Session 164, backfills DID work (Feb 1 got 143/181 predictions)
- The stalling began after Cloud Build redeployed all services mid-session

## Investigation steps

1. First check if the morning Feb 9 prediction run worked (it uses the same pipeline but is triggered by the scheduler, not manual /start). If it worked, the issue is specific to manual backfills.

2. Check Pub/Sub delivery metrics in Cloud Console or via:
   - gcloud monitoring dashboards (Pub/Sub subscription metrics)
   - Check `num_undelivered_messages` for prediction-request-prod subscription

3. Check if the coordinator is actually calling publish_prediction_requests() after batch creation:
   - Read predictions/coordinator/coordinator.py and trace the /start endpoint flow
   - Add logging if needed to confirm messages are published

4. Test the worker's /predict endpoint directly with a crafted Pub/Sub message

5. Check Cloud Run instance scaling: if min-instances=0, Pub/Sub push may fail on cold starts (503) and back off exponentially

6. If Pub/Sub push is confirmed broken, consider:
   - Setting min-instances=1 for the worker
   - Or switching to pull-based subscription

## Also while investigating:
- Run subset backfill for Feb 1-8 (script at /tmp/backfill_subsets_feb.py or use SubsetMaterializer)
- Verify Feb 9 predictions show dynamic model_version (v9_20260201_011018)

## Report back with:
- Root cause of the stalling
- Fix implemented
- Whether backfills now work
- Feb 1-8 prediction and subset status
```

## Why Opus

This requires:
- Live infrastructure debugging across multiple GCP services
- Tracing message flow through coordinator → Pub/Sub → worker
- Potentially reading/modifying Cloud Run configuration
- Understanding complex async patterns
- No clear solution path — needs investigation
