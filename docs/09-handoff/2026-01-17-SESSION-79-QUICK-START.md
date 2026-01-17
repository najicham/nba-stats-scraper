# Session 79: Continue Placeholder Line Remediation

**Copy/paste this prompt to continue the project:**

---

I'm continuing the placeholder line remediation project from Session 78. Here's where we are:

## Quick Status

**✅ COMPLETE (Sessions 76-78)**:
- Phase 1: Validation gate fixed and deployed (worker revision 00044-g7f)
- Phase 2: 18,990 invalid predictions deleted with backup
- Phase 3: 12,579 Nov-Dec predictions backfilled with real lines

**⚠️ BLOCKED**:
- Phase 4a: Coordinator timeout preventing Jan 9-10 test regeneration

**⏸️ READY**:
- Phase 4b: XGBoost V1 regeneration (53 dates, ~4 hours)
- Phase 5: Monitoring setup (~10 minutes)

**Overall Progress**: 65% complete

## The Problem

The coordinator service times out (even at 15 minutes) when trying to start prediction batches. This is blocking Phase 4a validation, which tests whether Phase 1's validation gate actually blocks placeholders in production.

**Root cause**: Batch historical game loading in coordinator takes too long for 454 players on Jan 9.

## Your Task - Option A (RECOMMENDED)

**Fix the coordinator timeout by bypassing batch loading:**

1. **Read the handoff**: `docs/09-handoff/2026-01-17-SESSION-78-PHASE1-DEPLOYMENT-HANDOFF.md`

2. **Apply the quick fix**:
   - Edit `predictions/coordinator/coordinator.py` around line 396
   - Set `batch_historical_games = None` to skip batch loading
   - Or comment out lines 392-418 entirely
   - Workers will query individually (slower but functional)

3. **Redeploy coordinator**:
   ```bash
   cd /home/naji/code/nba-stats-scraper/predictions/coordinator
   # Copy shared module first
   cp -r ../../shared .
   # Deploy
   gcloud run deploy prediction-coordinator \
     --source . \
     --region us-west2 \
     --project nba-props-platform
   ```

4. **Test Phase 4a** (THE CRITICAL VALIDATION):
   ```bash
   # Trigger Jan 9 predictions
   curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "X-API-Key: 0B5gc7vv9oNZYjST9lhe4rY2jEG2kYdz" \
     -H "Content-Type: application/json" \
     -d '{"game_date": "2026-01-09", "min_minutes": 15, "force": true}'

   # Wait 5-10 minutes, then validate
   bq query --nouse_legacy_sql "
   SELECT
     game_date, system_id, COUNT(*) as count,
     COUNTIF(current_points_line = 20.0) as placeholders
   FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
   WHERE game_date = '2026-01-09'
     AND created_at >= TIMESTAMP('2026-01-17 04:30:00')
   GROUP BY game_date, system_id
   ORDER BY system_id"

   # CRITICAL CHECK: placeholders MUST = 0 for all systems
   # This proves Phase 1 validation gate works!
   ```

5. **If Phase 4a succeeds** (0 placeholders):
   - Repeat for Jan 10
   - Proceed to Phase 4b (regenerate XGBoost V1 - 53 dates)
   - Execute Phase 5 (monitoring setup)
   - Final validation
   - Update documentation

6. **If Phase 4a fails** (placeholders > 0):
   - Check worker logs for validation gate activity
   - Investigate why placeholders got through
   - May need to debug validation gate logic

## Alternative: Option B (If Option A Doesn't Work)

Use direct Pub/Sub publishing to bypass coordinator entirely:
- Query players from BigQuery for Jan 9
- Publish messages directly to `prediction-request-prod` topic
- See handoff doc Section "Option B: Direct Pub/Sub Approach"

## Key Files

**Handoff**: `docs/09-handoff/2026-01-17-SESSION-78-PHASE1-DEPLOYMENT-HANDOFF.md`
**Worker code**: `predictions/worker/worker.py` (validation gate at lines 320-368)
**Coordinator code**: `predictions/coordinator/coordinator.py` (batch loading at lines 392-418)
**Phase 4b script**: `scripts/nba/phase4_regenerate_predictions.sh`
**Phase 5 script**: `scripts/nba/phase5_setup_monitoring.sql`

## Success Criteria

The goal is to validate that Phase 1's validation gate actually works in production:
- Jan 9-10 predictions generated successfully
- **ZERO placeholders** (`current_points_line = 20.0`)
- All predictions use real sportsbook lines
- No validation gate alerts

Once validated, complete Phases 4b-5 to finish the remediation project.

## Context

**Working Directory**: `/home/naji/code/nba-stats-scraper`
**GCP Project**: `nba-props-platform`
**Worker Revision**: `prediction-worker-00044-g7f` (Phase 1 deployed)
**Coordinator Revision**: `prediction-coordinator-00044-tz9` (15-min timeout)

Let me know what you find and we'll proceed from there!
