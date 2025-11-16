# Phase 2 Pub/Sub Integration - Executive Summary

**Date**: November 13, 2025  
**Status**: Ready for Implementation  
**Time Estimate**: 2-3 hours  

---

## 🎯 **What We're Doing**

Adding Pub/Sub event publishing to scrapers so Phase 2 processors can automatically process scraped data.

**Before**: Scrapers write to GCS → Nothing happens  
**After**: Scrapers write to GCS → Publish Pub/Sub event → Processor auto-triggers → Writes to BigQuery  

---

## 📦 **Files Created for You**

I've created 6 implementation files as artifacts. Save them to your project:

| # | File | Save Location | Purpose |
|---|------|---------------|---------|
| 1 | `pubsub_utils.py` | `scrapers/utils/pubsub_utils.py` | Pub/Sub publisher utility |
| 2 | `create_pubsub_infrastructure.sh` | `bin/pubsub/create_pubsub_infrastructure.sh` | Creates topics & IAM |
| 3 | `create_processor_subscriptions.sh` | `bin/pubsub/create_processor_subscriptions.sh` | Creates subscriptions |
| 4 | `test_pubsub_flow.sh` | `bin/pubsub/test_pubsub_flow.sh` | End-to-end testing |
| 5 | `monitor_pubsub.sh` | `bin/pubsub/monitor_pubsub.sh` | Health monitoring |
| 6 | `scraper_base_pubsub_modifications.md` | `docs/patches/scraper_base_pubsub_modifications.md` | Code changes guide |

---

## 🚀 **Quick Start (30 Minutes)**

### **Step 1: Save Files**

```bash
cd ~/code/nba-stats-scraper

# Create directories
mkdir -p bin/pubsub
mkdir -p scrapers/utils
mkdir -p docs/patches

# Copy the 6 files from artifacts to locations above

# Make scripts executable
chmod +x bin/pubsub/*.sh
```

### **Step 2: Create Infrastructure**

```bash
# Creates Pub/Sub topics and IAM permissions
./bin/pubsub/create_pubsub_infrastructure.sh

# ✅ Creates:
# - nba-scraper-complete topic
# - nba-scraper-complete-dlq topic  
# - nba-phase2-complete topic
# - IAM permissions
```

### **Step 3: Modify scraper_base.py**

Follow instructions in `docs/patches/scraper_base_pubsub_modifications.md`:

1. Add two methods (30 lines of code)
2. Add two method calls in `run()`
3. Add `google-cloud-pubsub>=2.13.0` to requirements.txt

### **Step 4: Deploy & Test**

```bash
# Deploy scrapers
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# Create subscriptions
./bin/pubsub/create_processor_subscriptions.sh

# Test everything
./bin/pubsub/test_pubsub_flow.sh

# ✅ If all tests pass, you're done!
```

---

## 🔍 **What We Discovered**

### ✅ **Good News**
- Phase 1 orchestration is working great
- Scrapers already log to BigQuery
- Consolidated 3-service architecture (efficient)
- GCS paths tracked properly

### 🔧 **What We're Adding**
- Pub/Sub event publishing in scrapers
- Pub/Sub infrastructure (topics, subscriptions)
- Automated processor triggering

---

## 📊 **Architecture After Implementation**

```
Phase 1: Scrapers
    ↓
Write JSON to GCS
    ↓
Log to orchestration.scraper_execution_log ✅
    ↓
Publish Pub/Sub event 🆕
    ↓
nba-scraper-complete topic 🆕
    ↓
nba-processors-sub subscription 🆕
    ↓
Phase 2: nba-processors/process
    ↓
Write to nba_raw.* tables
```

---

## 🎯 **Success Criteria**

You'll know it's working when:

- [x] Topics exist (3 topics created)
- [x] Subscription exists (0 backlog)
- [x] Scrapers publish events (check logs)
- [x] Processors auto-trigger (check logs)
- [x] Data in BigQuery (<30 seconds latency)
- [x] No errors in logs

---

## 📋 **Complete Implementation Checklist**

### **Phase 1: Infrastructure (15 min)**
- [ ] Save 6 files to project
- [ ] Run `create_pubsub_infrastructure.sh`
- [ ] Verify 3 topics created

### **Phase 2: Code Changes (15 min)**
- [ ] Add `pubsub_utils.py` to scrapers/utils/
- [ ] Modify `scraper_base.py` (2 methods + 2 calls)
- [ ] Add `google-cloud-pubsub` to requirements.txt
- [ ] Test locally: `python -m scrapers.utils.pubsub_utils`

### **Phase 3: Deployment (30 min)**
- [ ] Deploy scrapers: `./bin/scrapers/deploy/deploy_scrapers_simple.sh`
- [ ] Create subscriptions: `./bin/pubsub/create_processor_subscriptions.sh`
- [ ] Verify health: `curl SERVICE_URL/health`

### **Phase 4: Testing (30 min)**
- [ ] Run test script: `./bin/pubsub/test_pubsub_flow.sh`
- [ ] Manual test: Trigger scraper → Check Pub/Sub → Check BigQuery
- [ ] Monitor: `./bin/pubsub/monitor_pubsub.sh`

---

## 🔧 **Common Issues & Fixes**

| Issue | Fix |
|-------|-----|
| ModuleNotFoundError: google.cloud.pubsub | Add to requirements.txt & redeploy |
| Topic not found | Run `create_pubsub_infrastructure.sh` |
| Permission denied | Check IAM (script does this automatically) |
| Processor not triggered | Check subscription exists & has 0 backlog |
| Messages in DLQ | Check processor logs for errors |

---

## 📚 **Detailed Documentation**

For complete details, see:
- **Implementation Guide**: `COMPLETE_IMPLEMENTATION_GUIDE.md`
- **Code Changes**: `scraper_base_pubsub_modifications.md`
- **Handoff Docs**: Already in your project

---

## 🆘 **Getting Help**

### **Health Checks**

```bash
# Monitor Pub/Sub (one-time)
./bin/pubsub/monitor_pubsub.sh

# Monitor continuously (refresh every 30s)
./bin/pubsub/monitor_pubsub.sh --watch

# Check scraper logs
gcloud logging read \
  "resource.type=cloud_run_revision 
   AND resource.labels.service_name=nba-scrapers" \
  --limit=20

# Check processor logs
gcloud logging read \
  "resource.type=cloud_run_revision 
   AND resource.labels.service_name=nba-processors" \
  --limit=20

# Check DLQ
gcloud pubsub subscriptions pull nba-scraper-complete-dlq-sub --limit=10
```

---

## 🎉 **After Implementation**

Once working:

1. **Monitor for 48 hours** - Use `monitor_pubsub.sh --watch`
2. **Week 2**: Implement per-game iteration
3. **Week 3**: Add Phase 3 (analytics) handoff
4. **Month 2**: Build Grafana dashboards

---

## 📝 **Quick Commands Reference**

```bash
# Save files (one-time setup)
mkdir -p bin/pubsub scrapers/utils docs/patches
# Copy 6 artifact files to locations above
chmod +x bin/pubsub/*.sh

# Create infrastructure
./bin/pubsub/create_pubsub_infrastructure.sh

# Modify scraper_base.py (follow guide)
# Add google-cloud-pubsub to requirements.txt

# Deploy
./bin/scrapers/deploy/deploy_scrapers_simple.sh
./bin/pubsub/create_processor_subscriptions.sh

# Test
./bin/pubsub/test_pubsub_flow.sh

# Monitor
./bin/pubsub/monitor_pubsub.sh --watch
```

---

## ✅ **Ready to Start?**

1. Save the 6 artifact files to your project
2. Start with Phase 1 (Infrastructure)
3. Follow the checklist above
4. Test at each step

**Estimated time**: 2-3 hours from start to fully working system.

Good luck! 🚀

---

**Questions?** Everything is documented in:
- `COMPLETE_IMPLEMENTATION_GUIDE.md` (detailed walkthrough)
- `scraper_base_pubsub_modifications.md` (code changes)
