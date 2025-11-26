# Phase 2 Pub/Sub Integration - Complete Implementation Guide

**Date**: November 13, 2025  
**Status**: Ready for Implementation  
**Estimated Time**: 2-3 hours total  

---

## 🎯 **Mission**

Enable automatic event-driven processing by establishing Pub/Sub handoff from Phase 1 (scrapers) to Phase 2 (processors).

**Current State**: ❌ Scrapers log to BigQuery but don't notify processors  
**Target State**: ✅ Scrapers publish Pub/Sub events → Processors auto-trigger  

---

## 📊 **What We Discovered**

### ✅ **What EXISTS** (Good News)
1. **Phase 1 Orchestration Logging**: Scrapers already log to `nba_orchestration.scraper_execution_log` ✅
2. **Cloud Run Services**: 3 consolidated services (efficient architecture) ✅
   - `nba-scrapers` (Phase 1)
   - `nba-processors` (Phase 2)
   - `nba-analytics-processors` (Phase 3)
3. **GCS Output Tracking**: Scrapers track `gcs_output_path` ✅
4. **3-Status System**: success/no_data/failed tracking ✅

### ❌ **What's MISSING** (Need to Implement)
1. **Pub/Sub Publishing**: Scrapers don't publish completion events ❌
2. **Pub/Sub Infrastructure**: No topics or subscriptions exist ❌
3. **Scraper Endpoints**: `/scraper/bdl-games` returns 404 ❌
4. **BigQuery Tables**: `nba_raw.*` tables don't exist yet ❌

---

## 🚨 **Answers to Your Critical Questions**

### **Q1: Scraper Endpoints - Why 404?**

**Answer**: Your deployment script copies `scrapers/Dockerfile` to root and uses `--source=.` deployment. The 404 suggests:

**Possible Issues**:
1. Flask/FastAPI app doesn't have `/scraper/{name}` routes
2. App is using different endpoint pattern
3. Orchestration uses `/generate-daily-schedule`, `/evaluate` instead

**To Find Actual Endpoints**:
```bash
# Check scraper service health endpoint
curl -s "https://nba-scrapers-XXX.run.app/health" | jq '.'

# This should show available endpoints/scrapers
```

**Recommendation**: For now, focus on Pub/Sub integration. Scraper triggering is handled by orchestration system (which is working). The Pub/Sub publishing happens AFTER scraper execution, regardless of trigger method.

---

### **Q2: Processor Architecture - How Do 3 Services Work?**

**Answer**: Based on your deployment scripts:

**Architecture**: Consolidated services (cost-efficient)
- Single `/process` endpoint per service
- Internal routing based on `scraper_name` attribute
- All scrapers → `nba-processors-sub` → `nba-processors/process`

**NOT** individual endpoints like `/process/bdl-games` (that would require 21 services)

**Subscription Strategy**:
```bash
# One subscription for ALL Phase 2 processing
nba-processors-sub → nba-processors/process
  • No message filter (receives ALL scraper events)
  • Processor routes internally based on message.scraper_name
```

**Benefits**:
- Lower cost (3 services vs 21)
- Easier deployment
- Simpler monitoring

---

### **Q3: BigQuery Tables - When Are They Created?**

**Answer**: Likely created by processors on first run (common pattern).

**Recommendation**: 
1. Implement Pub/Sub integration first
2. Test with one scraper + processor
3. Verify table creation happens automatically
4. If not, we'll create schemas separately

**Alternative**: Create all table schemas upfront (safer):
```bash
# If you have schema files
./bin/schemas/create_bigquery_schemas.sh
```

---

### **Q4: Priority - What Should We Implement?**

**Recommendation**: **Option A - Fix Everything End-to-End (2-3 hours)**

**Why**: 
- You already have solid foundation (orchestration working)
- Pub/Sub is straightforward (1 hour)
- Testing confirms end-to-end flow works
- Prevents partial implementations

**Timeline**:
- Infrastructure setup: 30 minutes
- Code modifications: 30 minutes  
- Deployment: 30 minutes
- Testing: 30 minutes
- Buffer: 30 minutes

---

## 📋 **Complete Implementation Steps**

### **Phase 1: Infrastructure Setup (30 minutes)**

#### **Step 1.1: Create Files in Your Project**

```bash
# Navigate to your project
cd ~/code/nba-stats-scraper

# Create directories
mkdir -p bin/pubsub
mkdir -p scrapers/utils

# Copy files from artifacts (I created these for you):
# - pubsub_utils.py → scrapers/utils/pubsub_utils.py
# - create_pubsub_infrastructure.sh → bin/pubsub/create_pubsub_infrastructure.sh
# - create_processor_subscriptions.sh → bin/pubsub/create_processor_subscriptions.sh
# - test_pubsub_flow.sh → bin/pubsub/test_pubsub_flow.sh
# - scraper_base_pubsub_modifications.md → docs/patches/scraper_base_pubsub_modifications.md

# Make scripts executable
chmod +x bin/pubsub/*.sh
```

#### **Step 1.2: Create Pub/Sub Infrastructure**

```bash
# Run infrastructure creation script
./bin/pubsub/create_pubsub_infrastructure.sh

# Expected output:
# ✅ Created topic: nba-scraper-complete
# ✅ Created DLQ topic: nba-scraper-complete-dlq
# ✅ Created topic: nba-phase2-complete
# ✅ IAM permissions configured
```

**Verification**:
```bash
# Check topics exist
gcloud pubsub topics list --project=nba-props-platform

# Should show:
# nba-scraper-complete
# nba-scraper-complete-dlq
# nba-phase2-complete
```

---

### **Phase 2: Code Modifications (30 minutes)**

#### **Step 2.1: Add Dependencies**

```bash
# Add to scrapers/requirements.txt
echo "google-cloud-pubsub>=2.13.0" >> scrapers/requirements.txt

# Or if using pyproject.toml, add:
# google-cloud-pubsub = ">=2.13.0"
```

#### **Step 2.2: Modify scraper_base.py**

Follow the instructions in `scraper_base_pubsub_modifications.md`:

1. Add two new methods after `_log_failed_execution_to_bigquery()`:
   - `_publish_completion_event_to_pubsub()`
   - `_publish_failed_event_to_pubsub(error)`

2. Add method calls in `run()`:
   - Success path: Add `self._publish_completion_event_to_pubsub()` after `self._log_execution_to_bigquery()`
   - Failure path: Add try/except with `self._publish_failed_event_to_pubsub(e)` after failed execution logging

**Quick Test** (before deploying):
```bash
# Test Pub/Sub utility locally
python -m scrapers.utils.pubsub_utils

# Expected output:
# 🧪 Testing Pub/Sub Publisher...
# ✅ Publisher initialized: projects/nba-props-platform/topics/nba-scraper-complete
# ✅ Test event published successfully: 1234567890
```

---

### **Phase 3: Deployment (30 minutes)**

#### **Step 3.1: Deploy Scrapers**

```bash
# Deploy scrapers with new Pub/Sub code
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# Wait for deployment (2-3 minutes)
# Expected: ✅ Deployment completed successfully
```

**Verification**:
```bash
# Check scraper service health
SERVICE_URL=$(gcloud run services describe nba-scrapers \
  --region=us-west2 --format="value(status.url)")

curl -s "$SERVICE_URL/health" | jq '.status'
# Expected: "healthy"
```

#### **Step 3.2: Create Processor Subscriptions**

```bash
# Create Pub/Sub subscriptions for processors
./bin/pubsub/create_processor_subscriptions.sh

# Expected output:
# ✅ Created subscription: nba-processors-sub
# ✅ Service account can invoke Cloud Run processor
```

**Verification**:
```bash
# Check subscription exists
gcloud pubsub subscriptions describe nba-processors-sub \
  --project=nba-props-platform

# Check subscription has no backlog
gcloud pubsub subscriptions describe nba-processors-sub \
  --format='value(numUndeliveredMessages)' \
  --project=nba-props-platform
# Expected: 0
```

---

### **Phase 4: Testing & Verification (30 minutes)**

#### **Step 4.1: Run Automated Tests**

```bash
# Run comprehensive test suite
./bin/pubsub/test_pubsub_flow.sh

# This tests:
# ✅ Pub/Sub infrastructure exists
# ✅ Cloud Run services are healthy
# ✅ Event publishing works
# ✅ Message delivery works
```

#### **Step 4.2: Manual End-to-End Test**

```bash
# Option 1: Trigger scraper via orchestration
TOKEN=$(gcloud auth print-identity-token)
SERVICE_URL=$(gcloud run services describe nba-scrapers \
  --region=us-west2 --format="value(status.url)")

# Trigger schedule generation
curl -X POST "${SERVICE_URL}/generate-daily-schedule" \
  -H "Authorization: Bearer $TOKEN"

# Wait 30 seconds

# Option 2: Trigger specific scraper (if endpoint exists)
# curl -X POST "${SERVICE_URL}/scraper/bdl-games" ...

# Check for Pub/Sub event
gcloud pubsub subscriptions pull nba-processors-sub \
  --limit=1 \
  --project=nba-props-platform

# Expected: Event with scraper_name, status, gcs_path
```

#### **Step 4.3: Check BigQuery**

```bash
# Check orchestration log
bq query --use_legacy_sql=false "
SELECT 
  scraper_name,
  status,
  record_count,
  gcs_path,
  triggered_at
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE DATE(triggered_at, 'America/New_York') = CURRENT_DATE('America/New_York')
ORDER BY triggered_at DESC
LIMIT 10
"

# Check processor logs
gcloud logging read \
  "resource.type=cloud_run_revision 
   AND resource.labels.service_name=nba-processors" \
  --limit=20 \
  --format="table(timestamp,severity,textPayload)"

# Check if raw data table exists (if processor ran)
bq query --use_legacy_sql=false "
SELECT COUNT(*) as record_count
FROM \`nba-props-platform.nba_raw.bdl_games\`
WHERE game_date = CURRENT_DATE()
"
```

---

## ✅ **Success Criteria**

You'll know everything is working when:

- [x] **Infrastructure**: 3 Pub/Sub topics exist
- [x] **Subscriptions**: `nba-processors-sub` created with 0 backlog
- [x] **Publishing**: Scrapers publish events (check logs)
- [x] **Processing**: Processors receive and process events
- [x] **Data Flow**: Data appears in BigQuery within 30 seconds
- [x] **No Errors**: No errors in scraper or processor logs

---

## 🔧 **Troubleshooting Guide**

### **Issue 1: ModuleNotFoundError: google.cloud.pubsub**

**Cause**: Pub/Sub library not installed  
**Fix**:
```bash
echo "google-cloud-pubsub>=2.13.0" >> scrapers/requirements.txt
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

---

### **Issue 2: Topic Not Found**

**Cause**: Pub/Sub infrastructure not created  
**Fix**:
```bash
./bin/pubsub/create_pubsub_infrastructure.sh
```

---

### **Issue 3: Permission Denied When Publishing**

**Cause**: Service account lacks Pub/Sub publisher role  
**Fix**:
```bash
SA="756957797294-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:$SA" \
  --role="roles/pubsub.publisher"
```

---

### **Issue 4: Processor Not Triggered**

**Cause**: Subscription not created or misconfigured  
**Fix**:
```bash
# Check subscription exists
gcloud pubsub subscriptions list --project=nba-props-platform

# Recreate if needed
gcloud pubsub subscriptions delete nba-processors-sub
./bin/pubsub/create_processor_subscriptions.sh
```

---

### **Issue 5: Messages in DLQ**

**Cause**: Processor failing to process messages  
**Fix**:
```bash
# Check DLQ
gcloud pubsub subscriptions pull nba-scraper-complete-dlq-sub --limit=10

# Check processor logs for errors
gcloud logging read \
  "resource.type=cloud_run_revision 
   AND resource.labels.service_name=nba-processors
   AND severity>=ERROR" \
  --limit=50
```

---

## 📊 **Monitoring Commands**

### **Health Checks**

```bash
# Scraper health
curl -s "$(gcloud run services describe nba-scrapers --region=us-west2 --format='value(status.url)')/health"

# Processor health
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$(gcloud run services describe nba-processors --region=us-west2 --format='value(status.url)')/health"
```

### **Pub/Sub Status**

```bash
# Check subscription backlog
gcloud pubsub subscriptions describe nba-processors-sub \
  --format='value(numUndeliveredMessages)'
# Expected: 0 (or low number)

# Check DLQ for failures
gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub \
  --format='value(numUndeliveredMessages)'
# Expected: 0

# Pull recent events
gcloud pubsub subscriptions pull nba-processors-sub --limit=5
```

### **Execution Logs**

```bash
# Scraper executions today
bq query --use_legacy_sql=false "
SELECT 
  scraper_name,
  status,
  COUNT(*) as executions
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE DATE(triggered_at, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY scraper_name, status
ORDER BY scraper_name
"

# Processor logs (last 20)
gcloud logging read \
  "resource.type=cloud_run_revision 
   AND resource.labels.service_name=nba-processors" \
  --limit=20
```

---

## 🎯 **Next Steps After Implementation**

Once Phase 2 Pub/Sub integration is working:

1. **Week 2**: Monitor for 48 hours, fix any issues
2. **Week 3**: Implement per-game iteration for game-specific scrapers
3. **Week 4**: Add Phase 3 (analytics) Pub/Sub handoff
4. **Month 2**: Build Grafana dashboards for monitoring

---

## 📚 **Reference Files**

All implementation files are available as artifacts:

1. `pubsub_utils.py` - Pub/Sub publisher utility
2. `create_pubsub_infrastructure.sh` - Infrastructure setup
3. `create_processor_subscriptions.sh` - Subscription creation
4. `test_pubsub_flow.sh` - End-to-end testing
5. `scraper_base_pubsub_modifications.md` - Code changes guide

Save these to your project and follow the implementation steps above.

---

## 🆘 **Getting Help**

If you encounter issues:

1. **Check logs**: `gcloud logging read ...`
2. **Check health endpoints**: `/health` for both services
3. **Check DLQ**: `gcloud pubsub subscriptions pull nba-scraper-complete-dlq-sub`
4. **Verify infrastructure**: Run test script

---

**Ready to implement?** Start with Phase 1 (Infrastructure Setup) and work through each phase sequentially.

Good luck! 🚀
