# Handoff: Service Rename to Phase-Based Naming (IN PROGRESS)

**Date:** 2025-11-16
**Session Focus:** Rename all services to include phase numbers + complete Phase 2→3 publishing
**Status:** PARTIAL - Phase 1 deployed, Phases 2-3 pending
**Next Session:** Complete service renames, update subscriptions, test end-to-end

---

## ✅ What We Accomplished This Session

### **1. Phase 1 Dual Publishing Deployed**
- ✅ Updated `scrapers/utils/pubsub_utils.py` for dual publishing
- ✅ Deployed `nba-scrapers` service (revision 00083-srr)
- ✅ Fixed OIDC authentication for `nba-processors-sub-v2`
- ✅ Verified Phase 1→2 infrastructure working

### **2. Phase 2 Publisher Created**
- ✅ Created `shared/utils/pubsub_publishers.py` (367 lines)
  - `RawDataPubSubPublisher` class for Phase 2→3 events
  - `AnalyticsPubSubPublisher` class for Phase 3→4 events
  - Uses centralized `TOPICS` config
  - Non-blocking publishing with error handling

### **3. Phase 2 Base Class Updated**
- ✅ Updated `data_processors/raw/processor_base.py`
  - Added `_publish_completion_event()` method (51 lines)
  - Integrated into processor run() flow
  - Non-blocking, graceful error handling

### **4. Phase 3 ImportError Fixed**
- ✅ Fixed `data_processors/analytics/main_analytics_service.py`
  - Corrected class name imports:
    - `TeamOffenseProcessor` → `TeamOffenseGameSummaryProcessor`
    - `TeamDefenseProcessor` → `TeamDefenseGameSummaryProcessor`
- ✅ Deployed Phase 3 with fix (revision 00005-gph)
- ✅ Deployed Phase 2 with publishing (revision 00035-mqg)
- ✅ Verified Phase 2→3 flow (HTTP 200 responses)

### **5. Naming Convention Established**
- ✅ Created `docs/infrastructure/PUBSUB_AND_SERVICE_NAMES.md`
  - Complete naming reference for all 6 phases
  - Patterns for services, topics, subscriptions
  - Current deployment status
  - Migration notes

### **6. Service Rename Started**
- ✅ Deployed `nba-phase1-scrapers` (new name)
  - URL: `https://nba-phase1-scrapers-756957797294.us-west2.run.app`
  - Revision: `nba-phase1-scrapers-00001-tdl`
  - Old service `nba-scrapers` still running

---

## 🎯 Current State

### Services Deployed

| Phase | Old Name | New Name | Status |
|-------|----------|----------|--------|
| 1 | `nba-scrapers` | `nba-phase1-scrapers` | ✅ NEW DEPLOYED, OLD RUNNING |
| 2 | `nba-processors` | `nba-phase2-raw-processors` | ⏳ NOT YET DEPLOYED |
| 3 | `nba-analytics-processors` | `nba-phase3-analytics-processors` | ⏳ NOT YET DEPLOYED |

### Subscriptions Status

| Subscription | Topic | Push Endpoint | Status |
|--------------|-------|---------------|--------|
| `nba-processors-sub` | `nba-scraper-complete` | OLD Phase 2 URL | ⏳ NEEDS UPDATE |
| `nba-processors-sub-v2` | `nba-phase1-scrapers-complete` | OLD Phase 2 URL | ⏳ NEEDS UPDATE + RENAME |
| `nba-phase3-analytics-sub` | `nba-phase2-raw-complete` | OLD Phase 3 URL | ⏳ NEEDS UPDATE |
| `nba-phase3-fallback-sub` | `nba-phase3-fallback-trigger` | OLD Phase 3 URL | ⏳ NEEDS UPDATE |

### Code Changes (Ready to Deploy)

| File | Changes | Deployed |
|------|---------|----------|
| `scrapers/utils/pubsub_utils.py` | Dual publishing | ✅ YES (in nba-scrapers) |
| `shared/utils/pubsub_publishers.py` | Phase 2+ publishers | ✅ YES (in nba-processors) |
| `data_processors/raw/processor_base.py` | Phase 2 publishing | ✅ YES (in nba-processors) |
| `data_processors/analytics/main_analytics_service.py` | ImportError fix | ✅ YES (in nba-analytics-processors) |

---

## 🚀 Next Steps (Exact Order)

### Step 1: Deploy Phase 2 with New Name (20 mins)
**Deploy as:** `nba-phase2-raw-processors`

```bash
cd data_processors/raw
cp ../../docker/raw-processor.Dockerfile ../../Dockerfile
gcloud run deploy nba-phase2-raw-processors \
  --source ../.. \
  --region us-west2 \
  --platform managed \
  --no-allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --cpu 2
cd ../..
rm Dockerfile
```

**Expected result:**
- New URL: `https://nba-phase2-raw-processors-{hash}.us-west2.run.app`
- Old service `nba-processors` still running

---

### Step 2: Deploy Phase 3 with New Name (20 mins)
**Deploy as:** `nba-phase3-analytics-processors`

```bash
cd data_processors/analytics
cp ../../docker/analytics-processor.Dockerfile ../../Dockerfile
gcloud run deploy nba-phase3-analytics-processors \
  --source ../.. \
  --region us-west2 \
  --platform managed \
  --no-allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --cpu 2
cd ../..
rm Dockerfile
```

**Expected result:**
- New URL: `https://nba-phase3-analytics-processors-{hash}.us-west2.run.app`
- Old service `nba-analytics-processors` still running

---

### Step 3: Update All Subscriptions (15 mins)

**Get new service URLs first:**
```bash
# Get Phase 2 URL
PHASE2_URL=$(gcloud run services describe nba-phase2-raw-processors --region=us-west2 --format='value(status.url)')

# Get Phase 3 URL
PHASE3_URL=$(gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format='value(status.url)')

echo "Phase 2: $PHASE2_URL"
echo "Phase 3: $PHASE3_URL"
```

**Update 4 subscriptions:**

```bash
# 1. Update nba-processors-sub (OLD topic → Phase 2)
gcloud pubsub subscriptions update nba-processors-sub \
  --push-endpoint=${PHASE2_URL}/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com

# 2. Update nba-processors-sub-v2 (NEW topic → Phase 2)
gcloud pubsub subscriptions update nba-processors-sub-v2 \
  --push-endpoint=${PHASE2_URL}/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com

# 3. Update nba-phase3-analytics-sub (Phase 2 → Phase 3)
gcloud pubsub subscriptions update nba-phase3-analytics-sub \
  --push-endpoint=${PHASE3_URL}/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com

# 4. Update nba-phase3-fallback-sub (Fallback → Phase 3)
gcloud pubsub subscriptions update nba-phase3-fallback-sub \
  --push-endpoint=${PHASE3_URL}/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com
```

---

### Step 4: Test End-to-End Flow (30 mins)

**Test Phase 1 → Phase 2:**
```bash
# Publish test message to Phase 1 topic
gcloud pubsub topics publish nba-phase1-scrapers-complete \
  --message='{
    "name":"test_rename_e2e",
    "execution_id":"test-'$(date +%s)'",
    "status":"success",
    "gcs_path":"gs://test/rename-test.json",
    "record_count":1
  }'

# Check Phase 2 received it
gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=20 | grep test_rename
```

**Test Phase 2 → Phase 3:**
```bash
# Publish test message to Phase 2 topic
gcloud pubsub topics publish nba-phase2-raw-complete \
  --message='{
    "event_type":"raw_data_loaded",
    "source_table":"test_table",
    "game_date":"2024-11-16",
    "record_count":1,
    "execution_id":"test-phase2-'$(date +%s)'"
  }'

# Check Phase 3 received it
gcloud run services logs read nba-phase3-analytics-processors --region=us-west2 --limit=20 | grep test-phase2
```

**Verify no errors:**
```bash
# Check DLQ depth (should be 0)
gcloud pubsub subscriptions describe nba-phase1-scrapers-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"

gcloud pubsub subscriptions describe nba-phase2-raw-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"
```

---

### Step 5: Rename Subscription (10 mins)

**After verifying everything works:**

```bash
# Create new subscription with proper name
gcloud pubsub subscriptions create nba-phase2-raw-sub \
  --topic=nba-phase1-scrapers-complete \
  --push-endpoint=${PHASE2_URL}/process \
  --push-auth-service-account=756957797294-compute@developer.gserviceaccount.com \
  --ack-deadline=600 \
  --message-retention-duration=7d

# Verify it works
gcloud pubsub topics publish nba-phase1-scrapers-complete \
  --message='{"name":"test_new_sub","execution_id":"test-123","status":"success"}'

# Check logs
gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=10
```

---

### Step 6: Monitor for 24 Hours

**Let both old and new services run in parallel for 24 hours.**

**Check regularly:**
```bash
# Traffic going to new services
gcloud run services logs read nba-phase2-raw-processors --region=us-west2 --limit=20

# Old services still getting traffic (expected during migration)
gcloud run services logs read nba-processors --region=us-west2 --limit=20
```

---

### Step 7: Cleanup (After 24h Verification)

**Delete old services:**
```bash
gcloud run services delete nba-scrapers --region=us-west2 --quiet
gcloud run services delete nba-processors --region=us-west2 --quiet
gcloud run services delete nba-analytics-processors --region=us-west2 --quiet
```

**Delete old subscription:**
```bash
# First verify new subscription is working
gcloud pubsub subscriptions delete nba-processors-sub-v2 --quiet
```

**Eventually delete old topics (after dual publishing migration complete):**
```bash
# DO NOT DO THIS YET - dual publishing still active
# gcloud pubsub topics delete nba-scraper-complete --quiet
# gcloud pubsub subscriptions delete nba-processors-sub --quiet
```

---

## 🗂️ Key Files Reference

### Documentation
- **Naming Reference:** `docs/infrastructure/PUBSUB_AND_SERVICE_NAMES.md`
- **This Handoff:** `docs/HANDOFF-2025-11-16-service-rename-in-progress.md`
- **Previous Handoff:** `docs/HANDOFF-2025-11-16-phase3-topics-deployed.md`
- **Topic Config:** `shared/config/pubsub_topics.py`

### Code Changes
- **Phase 1 Dual Pub:** `scrapers/utils/pubsub_utils.py`
- **Phase 2 Publisher:** `shared/utils/pubsub_publishers.py`
- **Phase 2 Base Class:** `data_processors/raw/processor_base.py`
- **Phase 3 Fix:** `data_processors/analytics/main_analytics_service.py`

### Deployment Scripts
- **Scrapers:** `bin/shortcuts/deploy-scrapers`
- **Raw Processors:** `bin/raw/deploy/deploy_processors_simple.sh`
- **Analytics:** `bin/shortcuts/deploy-analytics`

---

## 📊 Service URLs Reference

### Current Services (OLD names - still running)
```
nba-scrapers:              https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
nba-processors:            https://nba-processors-f7p3g7f6ya-wl.a.run.app
nba-analytics-processors:  https://nba-analytics-processors-f7p3g7f6ya-wl.a.run.app
```

### New Services (NEW names - some deployed)
```
nba-phase1-scrapers:                   https://nba-phase1-scrapers-756957797294.us-west2.run.app ✅
nba-phase2-raw-processors:             NOT YET DEPLOYED ⏳
nba-phase3-analytics-processors:       NOT YET DEPLOYED ⏳
```

---

## ⚠️ Important Notes

1. **Both old and new services will run in parallel during migration** - This is intentional for zero-downtime deployment

2. **Subscriptions point to old services until Step 3** - Traffic still flows through old services until subscriptions are updated

3. **Phase 1 has TWO services running:**
   - `nba-scrapers` (OLD) - Still receiving scheduler triggers
   - `nba-phase1-scrapers` (NEW) - Not yet receiving triggers
   - Need to update scheduler jobs eventually (separate task)

4. **Dual publishing is still active** - Phase 1 publishes to both old and new topics

5. **DO NOT delete old topics yet** - Wait until dual publishing migration is complete

6. **Test thoroughly before cleanup** - 24-48 hours of monitoring recommended

---

## 🚨 Rollback Plan (If Needed)

If issues occur, rollback is easy:

### Rollback Subscriptions
```bash
# Revert to old Phase 2 URL
OLD_PHASE2_URL="https://nba-processors-f7p3g7f6ya-wl.a.run.app"
gcloud pubsub subscriptions update nba-processors-sub \
  --push-endpoint=${OLD_PHASE2_URL}/process

gcloud pubsub subscriptions update nba-processors-sub-v2 \
  --push-endpoint=${OLD_PHASE2_URL}/process

# Revert to old Phase 3 URL
OLD_PHASE3_URL="https://nba-analytics-processors-f7p3g7f6ya-wl.a.run.app"
gcloud pubsub subscriptions update nba-phase3-analytics-sub \
  --push-endpoint=${OLD_PHASE3_URL}/process

gcloud pubsub subscriptions update nba-phase3-fallback-sub \
  --push-endpoint=${OLD_PHASE3_URL}/process
```

### Delete New Services
```bash
gcloud run services delete nba-phase1-scrapers --region=us-west2 --quiet
gcloud run services delete nba-phase2-raw-processors --region=us-west2 --quiet
gcloud run services delete nba-phase3-analytics-processors --region=us-west2 --quiet
```

Everything returns to working state with old names.

---

## 📝 Prompt for Next Chat Session

```
I'm continuing the service rename to phase-based naming for the NBA stats platform.

Previous session completed:
- ✅ Deployed nba-phase1-scrapers (new name)
- ✅ Created naming convention doc (docs/infrastructure/PUBSUB_AND_SERVICE_NAMES.md)
- ✅ Fixed Phase 3 ImportError
- ✅ Added Phase 2→3 publishing logic

Current state:
- Phase 1 deployed with new name, old service still running
- Phase 2 & 3 need deployment with new names
- 4 subscriptions need updating to point to new service URLs
- End-to-end testing needed
- Old services need cleanup after verification

Next steps:
1. Deploy nba-phase2-raw-processors
2. Deploy nba-phase3-analytics-processors
3. Update 4 subscriptions to new URLs
4. Test end-to-end flow (Phase 1→2→3)
5. Rename nba-processors-sub-v2 to nba-phase2-raw-sub
6. Monitor for 24h, then cleanup old services

Please read:
- docs/HANDOFF-2025-11-16-service-rename-in-progress.md (complete context)
- docs/infrastructure/PUBSUB_AND_SERVICE_NAMES.md (naming reference)

Let's continue with deploying Phase 2 and 3 with the new names.
```

---

**Session Complete:** 2025-11-16 at ~90% context
**Next Session:** Complete service renames and test end-to-end flow
**Estimated Time:** 1.5-2 hours for deployment + testing + monitoring
**Risk:** LOW (blue/green deployment, easy rollback)
