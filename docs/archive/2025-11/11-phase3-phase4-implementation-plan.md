# Phase 3→4 Connection Implementation Plan

**Date:** 2025-11-18
**Goal:** Complete Phase 3 (Analytics) → Phase 4 (Precompute) event-driven connection
**Status:** Ready to implement

---

## 🔍 Current State Summary

### ✅ What Exists

**Phase 3 Analytics:**
- ✅ Service deployed: `nba-phase3-analytics-processors` (us-west2)
- ✅ Processors implemented:
  - `PlayerGameSummaryProcessor`
  - `TeamOffenseGameSummaryProcessor`
  - `TeamDefenseGameSummaryProcessor`
- ✅ Base class: `analytics_base.py` (complete run() lifecycle)
- ✅ Receives Phase 2→3 messages successfully

**Phase 4 Precompute:**
- ✅ Code exists in `data_processors/precompute/`
- ✅ Base class: `precompute_base.py` (44KB, comprehensive)
- ✅ Processors exist:
  - `PlayerDailyCacheProcessor`
  - `PlayerShotZoneAnalysisProcessor`
  - `TeamDefenseZoneAnalysisProcessor`
  - `PlayerCompositeFactorsProcessor`
  - `MLFeatureStoreProcessor`
- ✅ Basic service: `main_precompute_service.py` (Flask skeleton)

### ❌ What's Missing

**Pub/Sub Infrastructure:**
- ❌ Topic `nba-phase3-analytics-complete` not created
- ❌ Topic `nba-phase3-analytics-complete-dlq` not created
- ❌ Subscription to Phase 4 service not created

**Phase 3 Publishing:**
- ❌ `analytics_base.py` does NOT call `_publish_completion_event()`
- ❌ No code to publish to Phase 4 when analytics complete

**Phase 4 Service:**
- ❌ Not deployed to Cloud Run
- ❌ `main_precompute_service.py` is a stub (marked with TODO)
- ❌ Doesn't decode Pub/Sub messages
- ❌ Doesn't trigger processors

---

## 📋 Implementation Tasks

### Task 1: Create Pub/Sub Infrastructure Script ⭐ HIGH PRIORITY

**File:** `bin/infrastructure/create_phase3_phase4_topics.sh`

**What to Create:**
```bash
# Topics
- nba-phase3-analytics-complete (main event topic)
- nba-phase3-analytics-complete-dlq (dead letter queue)
- nba-phase4-fallback-trigger (already exists, verify)

# Subscriptions
- nba-phase4-precompute-sub (push to Phase 4 service)
  - Topic: nba-phase3-analytics-complete
  - Endpoint: https://nba-phase4-precompute-processors-{hash}-wl.a.run.app/process
  - DLQ: nba-phase3-analytics-complete-dlq
  - Max delivery attempts: 5

- nba-phase3-analytics-complete-dlq-sub (pull, for monitoring)
  - Topic: nba-phase3-analytics-complete-dlq

- nba-phase4-fallback-sub (push to Phase 4 service)
  - Topic: nba-phase4-fallback-trigger
  - Endpoint: https://nba-phase4-precompute-processors-{hash}-wl.a.run.app/process
```

**Model After:** `bin/infrastructure/create_phase2_phase3_topics.sh`

**Estimated Time:** 30 minutes

---

### Task 2: Add Phase 3 Publishing Code ⭐ HIGH PRIORITY

**File:** `data_processors/analytics/analytics_base.py`

**Changes Required:**

1. Add `_publish_completion_event()` method (copy from `processor_base.py:492`)
2. Call it after `save_analytics()` succeeds
3. Use `AnalyticsPubSubPublisher` from `shared/utils/pubsub_publishers.py`

**Implementation:**

```python
def run(self, opts: Optional[Dict] = None) -> bool:
    """Main entry point."""
    try:
        # ... existing code ...

        # Save to analytics tables
        self.mark_time("save")
        self.save_analytics()
        save_seconds = self.get_elapsed_seconds("save")
        self.stats["save_time"] = save_seconds

        # ✨ NEW: Publish Phase 3 completion event (triggers Phase 4)
        self._publish_completion_event()

        # Complete
        total_seconds = self.get_elapsed_seconds("total")
        # ... rest of existing code ...

def _publish_completion_event(self) -> None:
    """
    Publish Phase 3 completion event to trigger Phase 4 precompute.

    This method is called after save_analytics() successfully completes.
    Publishing is non-blocking - failures are logged but don't fail the processor.
    """
    try:
        from shared.utils.pubsub_publishers import AnalyticsPubSubPublisher

        # Extract game_date from opts
        game_date = self.opts.get('start_date') or self.opts.get('game_date')
        if not game_date:
            logger.debug(
                f"No game_date in opts for {self.__class__.__name__}, "
                f"skipping Phase 3 completion publish"
            )
            return

        # Get correlation_id if available
        correlation_id = self.opts.get('correlation_id') or self.opts.get('execution_id')

        # Initialize publisher
        project_id = self.project_id
        publisher = AnalyticsPubSubPublisher(project_id=project_id)

        # Publish completion event
        message_id = publisher.publish_analytics_complete(
            analytics_table=self.table_name,
            game_date=str(game_date),
            record_count=self.stats.get('rows_processed', 0),
            execution_id=self.run_id,
            correlation_id=correlation_id,
            success=True
        )

        if message_id:
            logger.info(
                f"✅ Published Phase 3 completion event (message_id={message_id})"
            )

    except Exception as e:
        # Log error but don't fail the processor
        logger.error(
            f"Failed to publish Phase 3 completion for {self.table_name}: {e}",
            exc_info=True
        )
```

**Location to Add:** After line 208 (after `save_analytics()` call)

**Estimated Time:** 20 minutes

---

### Task 3: Enhance Phase 4 Service ⭐ HIGH PRIORITY

**File:** `data_processors/precompute/main_precompute_service.py`

**Changes Required:**

Replace stub with full implementation that:
1. Decodes Pub/Sub messages
2. Extracts `analytics_table` and `game_date`
3. Determines which precompute processors to run
4. Runs processors with proper error handling
5. Returns 200 to acknowledge message

**Implementation:**

```python
"""
Phase 4: Precompute Service
Handles Pub/Sub messages when analytics processing completes
"""
import os
import json
import logging
import base64
from flask import Flask, request, jsonify
from datetime import datetime, timezone

# Import precompute processors
from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor
from data_processors.precompute.player_composite_factors.player_composite_factors_processor import PlayerCompositeFactorsProcessor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Precompute processor triggers - maps analytics tables to dependent precompute processors
PRECOMPUTE_TRIGGERS = {
    'player_game_summary': [
        PlayerDailyCacheProcessor,
        PlayerShotZoneAnalysisProcessor,
        PlayerCompositeFactorsProcessor
    ],
    'team_offense_game_summary': [
        TeamDefenseZoneAnalysisProcessor
    ],
    'team_defense_game_summary': [
        TeamDefenseZoneAnalysisProcessor
    ],
}

@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "precompute_processors",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

@app.route('/process', methods=['POST'])
def process_precompute():
    """
    Handle Pub/Sub messages for precompute processing.
    Triggered when analytics processing completes.

    Expected message format:
    {
        "analytics_table": "player_game_summary",
        "game_date": "2024-11-18",
        "processor_name": "PlayerGameSummaryProcessor",
        "success": true
    }
    """
    envelope = request.get_json()

    if not envelope:
        return jsonify({"error": "No Pub/Sub message received"}), 400

    # Decode Pub/Sub message
    if 'message' not in envelope:
        return jsonify({"error": "Invalid Pub/Sub message format"}), 400

    try:
        # Decode the message
        pubsub_message = envelope['message']

        if 'data' in pubsub_message:
            data = base64.b64decode(pubsub_message['data']).decode('utf-8')
            message = json.loads(data)
        else:
            return jsonify({"error": "No data in Pub/Sub message"}), 400

        # Extract trigger info
        analytics_table = message.get('analytics_table')
        game_date = message.get('game_date')
        success = message.get('success', True)

        if not success:
            logger.info(f"Analytics processing failed for {analytics_table}, skipping precompute")
            return jsonify({"status": "skipped", "reason": "Analytics processing failed"}), 200

        if not analytics_table:
            return jsonify({"error": "Missing analytics_table in message"}), 400

        logger.info(f"Processing precompute for {analytics_table}, date: {game_date}")

        # Determine which precompute processors to run
        processors_to_run = PRECOMPUTE_TRIGGERS.get(analytics_table, [])

        if not processors_to_run:
            logger.info(f"No precompute processors configured for {analytics_table}")
            return jsonify({"status": "no_processors", "analytics_table": analytics_table}), 200

        # Process precompute for date range (single day)
        start_date = game_date
        end_date = game_date

        results = []
        for processor_class in processors_to_run:
            try:
                logger.info(f"Running {processor_class.__name__} for {game_date}")

                processor = processor_class()
                opts = {
                    'start_date': start_date,
                    'end_date': end_date,
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'triggered_by': analytics_table
                }

                success = processor.run(opts)

                if success:
                    stats = processor.get_precompute_stats() if hasattr(processor, 'get_precompute_stats') else {}
                    logger.info(f"Successfully ran {processor_class.__name__}: {stats}")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "success",
                        "stats": stats
                    })
                else:
                    logger.error(f"Failed to run {processor_class.__name__}")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "error"
                    })

            except Exception as e:
                logger.error(f"Precompute processor {processor_class.__name__} failed: {e}", exc_info=True)
                results.append({
                    "processor": processor_class.__name__,
                    "status": "exception",
                    "error": str(e)
                })

        return jsonify({
            "status": "completed",
            "analytics_table": analytics_table,
            "game_date": game_date,
            "results": results
        }), 200

    except Exception as e:
        logger.error(f"Error processing precompute message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

**Estimated Time:** 30 minutes

---

### Task 4: Deploy Phase 4 Service 🚀

**Create Deployment Script:** `bin/precompute/deploy/deploy_precompute_processors.sh`

**Model After:** `bin/analytics/deploy/deploy_analytics_processors.sh`

**Key Configuration:**
```bash
SERVICE_NAME="nba-phase4-precompute-processors"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SERVICE_ACCOUNT="nba-pipeline@nba-props-platform.iam.gserviceaccount.com"

gcloud run deploy $SERVICE_NAME \
  --source=. \
  --region=$REGION \
  --project=$PROJECT_ID \
  --platform=managed \
  --service-account=$SERVICE_ACCOUNT \
  --timeout=540 \
  --memory=2Gi \
  --cpu=2 \
  --max-instances=10 \
  --no-allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID"
```

**Estimated Time:** 20 minutes (+ 5 min deploy time)

---

### Task 5: Run Infrastructure Script 🏗️

**Execute:**
```bash
chmod +x bin/infrastructure/create_phase3_phase4_topics.sh
./bin/infrastructure/create_phase3_phase4_topics.sh
```

**Verify:**
```bash
# Check topics created
gcloud pubsub topics list --project=nba-props-platform | grep phase3-analytics

# Check subscriptions created
gcloud pubsub subscriptions list --project=nba-props-platform | grep phase4

# Check subscription details
gcloud pubsub subscriptions describe nba-phase4-precompute-sub \
  --project=nba-props-platform
```

**Estimated Time:** 10 minutes

---

### Task 6: Test End-to-End Flow 🧪

**Test Steps:**

1. **Trigger Phase 3 with test message:**
```bash
# Publish to Phase 2→3 topic (will trigger analytics)
gcloud pubsub topics publish nba-phase2-raw-complete \
  --project=nba-props-platform \
  --message='{
    "event_type": "raw_data_loaded",
    "source_table": "nbac_gamebook_player_stats",
    "game_date": "2024-11-18",
    "record_count": 100,
    "execution_id": "test-123",
    "correlation_id": "test-correlation-456"
  }'
```

2. **Check Phase 3 service logs:**
```bash
gcloud run services logs read nba-phase3-analytics-processors \
  --project=nba-props-platform \
  --region=us-west2 \
  --limit=50
```

**Expected:** Should see "Published Phase 3 completion event"

3. **Check Phase 4 topic received message:**
```bash
gcloud pubsub topics list-subscriptions nba-phase3-analytics-complete \
  --project=nba-props-platform

# Pull message (before subscription is push)
gcloud pubsub subscriptions pull nba-phase4-precompute-sub \
  --project=nba-props-platform \
  --limit=1 \
  --auto-ack
```

4. **Check Phase 4 service logs:**
```bash
gcloud run services logs read nba-phase4-precompute-processors \
  --project=nba-props-platform \
  --region=us-west2 \
  --limit=50
```

**Expected:** Should see precompute processors running

5. **Check DLQ is empty:**
```bash
gcloud pubsub subscriptions pull nba-phase3-analytics-complete-dlq-sub \
  --project=nba-props-platform \
  --limit=10
```

**Expected:** No messages (all successful)

**Estimated Time:** 30 minutes

---

## 📊 Implementation Order

### Day 1: Infrastructure & Code (2-3 hours)

1. ✅ Create infrastructure script (30 min)
2. ✅ Add Phase 3 publishing code (20 min)
3. ✅ Enhance Phase 4 service (30 min)
4. ✅ Create deployment script (20 min)
5. ✅ Deploy Phase 4 service (25 min)
6. ✅ Run infrastructure script (10 min)

### Day 2: Testing & Validation (1-2 hours)

7. ✅ Test end-to-end flow (30 min)
8. ✅ Verify monitoring works (20 min)
9. ✅ Test error scenarios (30 min)
10. ✅ Document results (20 min)

**Total Estimated Time:** 3-5 hours

---

## 🎯 Success Criteria

### Must Have ✅

- [ ] Phase 3→4 topics and subscriptions created
- [ ] Phase 3 processors publish completion events
- [ ] Phase 4 service receives and decodes messages
- [ ] Phase 4 processors run successfully
- [ ] Messages acknowledged (not sent to DLQ)
- [ ] End-to-end test passes

### Nice to Have 🌟

- [ ] Grafana dashboard showing Phase 3→4 flow
- [ ] DLQ monitoring alerts configured
- [ ] Documentation updated with new flow
- [ ] Performance benchmarks collected

---

## 🚨 Risk Assessment

### Low Risk
- Infrastructure creation (script is idempotent)
- Phase 3 publishing (non-blocking, logs errors)
- Phase 4 service deployment (can rollback)

### Medium Risk
- Phase 4 processor bugs (new code paths)
  - **Mitigation:** Test with small date range first
  - **Mitigation:** Monitor DLQ closely

### Low Impact
- Publishing failures don't break Phase 3
- Phase 4 retries via Pub/Sub
- DLQ preserves failed messages

---

## 📝 Follow-Up Tasks (After Completion)

1. Add Phase 4 publishing to Phase 5 (predictions)
2. Create Phase 4→5 infrastructure
3. Deploy Phase 5 coordinator/workers
4. Implement pipeline execution logging table
5. Add correlation_id to all phases
6. Create comprehensive monitoring dashboard

---

## 🔗 Related Documents

- `docs/PUBSUB_GAP_ANALYSIS.md` - Full gap analysis
- `docs/architecture/04-event-driven-pipeline-architecture.md` - Overall architecture
- `shared/config/pubsub_topics.py` - Topic name configuration
- `bin/infrastructure/create_phase2_phase3_topics.sh` - Reference script

---

**Created:** 2025-11-18
**Ready to Start:** Yes
**Blocking Issues:** None
