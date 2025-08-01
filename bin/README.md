# NBA Stats Scraper - Workflow Operations Guide
*Production-ready NBA prop betting data pipeline with Google Cloud Workflows*

## 🏗️ System Architecture (August 2025)

**Current Production System:**
- **Google Cloud Workflows** - 4 orchestrated business processes ✅
- **Cloud Schedulers** - Automatic workflow triggers ✅  
- **Cloud Run** - Unified scraper service ✅
- **Individual Schedulers** - Migrated/Paused ✅

**Data Flow:** `Cloud Scheduler → Google Cloud Workflow → Cloud Run Scrapers → GCS → Pub/Sub → Processors`

---

## 📁 Directory Structure

### **`deployment/`** - Application Deployment
Core deployment scripts for the NBA data pipeline:

- **`deploy_workflows.sh`** - Deploy all 4 NBA workflows ⭐ **Primary**
- **`deploy_scrapers.sh`** - Deploy Cloud Run scraper service ⭐ **Still Critical**
- **`setup_infrastructure.sh`** - Initial GCP infrastructure setup
- **`build_base.sh`** / **`build_service.sh`** - Container building
- **`deploy_fast.sh`** - Quick scraper deployment updates

### **`scheduling/`** - Workflow & Scheduler Management
Scripts for managing automated execution:

- **`setup_workflow_schedulers.sh`** - Create/update workflow schedulers ⭐ **Primary**
- **`pause_all_schedulers.sh`** - Transition management (old → new system) ⭐ **Migration**
- **`resume_individual_schedulers.sh`** - Emergency rollback capability

### **`monitoring/`** - System Health & Observability
Monitor workflows, schedulers, and system health:

- **`monitor_workflows.sh`** - Comprehensive workflow monitoring ⭐ **Primary**  
- **`system_overview.sh`** - System-wide health check ⭐ **Still Useful**
- **`scraper_status.sh`** - Individual scraper health ⭐ **Still Useful**
- **`nba_monitor_scheduler.sh`** - Legacy scheduler monitoring (backup)

### **`testing/`** - Validation & Testing
Test and validate system components:

- **`test_scrapers.sh`** - Test individual scrapers ⭐ **Still Critical**
- **`test_workflow.sh`** - Test workflow execution
- **`validate_data.sh`** - Data quality validation

### **`utilities/`** - Helper Scripts
Utility and maintenance scripts:

- **`api_status.sh`** - Check external API health ⭐ **Still Critical**
- **`logs_scrapers.sh`** - Scraper log analysis ⭐ **Still Critical**
- **`clear_old_data.sh`** - Data cleanup utilities

### **`archive/`** - Legacy Scripts
Archived scripts from individual scheduler system (pre-August 2025).

---

## 🚀 Quick Start Guide

### **📊 Daily Operations**
```bash
# Morning health check
./bin/monitoring/monitor_workflows.sh

# Check workflow executions
./bin/monitoring/monitor_workflows.sh detailed

# Check individual scraper health (if needed)
./bin/monitoring/scraper_status.sh
```

### **🔧 Deployment & Updates**
```bash
# Deploy workflow changes
./bin/deployment/deploy_workflows.sh

# Deploy scraper service updates  
./bin/deployment/deploy_scrapers.sh

# Quick scraper updates
./bin/deployment/deploy_fast.sh
```

### **⚙️ Scheduler Management**
```bash
# Update workflow schedulers
./bin/scheduling/setup_workflow_schedulers.sh

# Check scheduler status
gcloud scheduler jobs list --location=us-west2 --filter="name ~ .*trigger"
```

### **🧪 Testing & Validation**
```bash
# Test scraper service
./bin/testing/test_scrapers.sh

# Test workflow execution
./bin/testing/test_workflow.sh

# Check API connectivity
./bin/utilities/api_status.sh
```

---

## 📅 Production Schedule (Automated)

### **🎯 Active Workflows**
- **Real-Time Business**: Every 2 hours (8 AM - 8 PM PT) - Events → Props dependency
- **Morning Operations**: Daily at 8 AM PT - Roster & schedule updates
- **Game Day Evening**: 6 PM, 9 PM, 11 PM PT - Live game monitoring  
- **Post-Game Analysis**: Daily at 9 PM PT - Detailed stats & analytics

### **💼 Critical Business Dependencies**
- **Events API → Props API**: Revenue-blocking dependency (properly managed) ✅
- **Foundation Data**: Player lists, injury reports, rosters (shared across workflows) ✅

---

## 🎯 Key Business Processes

### **Real-Time Business (Revenue Critical) 🔴**
**Purpose:** NBA prop betting data with Events→Props dependency  
**Schedule:** Every 2 hours (8 AM - 8 PM PT)  
**Monitor:** `./bin/monitoring/monitor_workflows.sh business`

### **Morning Operations 🌅**  
**Purpose:** Daily setup and roster management  
**Schedule:** Daily 8 AM PT  
**Components:** Team rosters, schedules, player movement

### **Game Day Evening 🎮**
**Purpose:** Live game monitoring  
**Schedule:** 6 PM, 9 PM, 11 PM PT  
**Components:** Live scoreboards, box scores

### **Post-Game Analysis 📊**
**Purpose:** End-of-day comprehensive analysis  
**Schedule:** Daily 9 PM PT  
**Components:** Final stats, historical data

---

## 📋 Development Workflow

### **Making Changes**
```bash
# 1. Test locally
./bin/testing/test_scrapers.sh

# 2. Deploy updates
./bin/deployment/deploy_workflows.sh    # For workflow changes
./bin/deployment/deploy_scrapers.sh     # For scraper changes

# 3. Monitor results
./bin/monitoring/monitor_workflows.sh
```

### **Troubleshooting**
```bash
# Check workflow health
./bin/monitoring/monitor_workflows.sh health

# Check individual scrapers
./bin/monitoring/scraper_status.sh

# View recent logs
./bin/utilities/logs_scrapers.sh

# Check external APIs
./bin/utilities/api_status.sh
```

### **Emergency Procedures**
```bash
# If workflows fail completely
./bin/scheduling/pause_all_schedulers.sh  # Resume old system

# Manual workflow execution
gcloud workflows run real-time-business --location=us-west2

# Check workflow execution details
gcloud workflows executions list WORKFLOW_NAME --location=us-west2
```

---

## 🔍 Monitoring & Health Checks

### **System Health Commands**
```bash
# Comprehensive dashboard
./bin/monitoring/monitor_workflows.sh detailed

# Quick health check
./bin/monitoring/monitor_workflows.sh

# Business metrics only
./bin/monitoring/monitor_workflows.sh business

# Recent activity
./bin/monitoring/monitor_workflows.sh activity
```

### **Key Metrics to Watch**
- **Workflow Success Rate**: >95% expected
- **Events→Props Dependency**: Critical for revenue
- **API Rate Limits**: BDL (600/min), Odds API (500/month)
- **Execution Duration**: <5 minutes typical

---

## 🏆 Implementation Status

### **✅ COMPLETE: Workflow Migration (August 2025)**
- ✅ **4 Production Workflows** deployed and running
- ✅ **Automatic Scheduling** every few hours  
- ✅ **Events→Props Dependency** properly managed
- ✅ **Individual Schedulers** successfully migrated/paused
- ✅ **Business Logic** embedded in workflow orchestration

### **🎯 Current Phase: Production Operations**
- **Focus**: Monitor workflow health and performance
- **Priority**: Ensure business continuity and revenue protection
- **Tools**: Comprehensive monitoring and alerting

### **📈 Future Enhancements**
- Enhanced business metrics and alerting
- Advanced data quality monitoring  
- Performance optimization based on usage patterns

---

## 🚨 Critical Information

### **Revenue Protection**
The **Real-Time Business** workflow is **revenue-critical**. It manages the Events→Props dependency that prevents betting revenue loss.

### **API Rate Limits**
- **Ball Don't Lie**: 600 requests/minute (currently ~15-20/day) ✅
- **Odds API**: 500 requests/month (currently ~60-80/month) ✅  
- **NBA.com/ESPN**: Monitor for 429 responses

### **Service Accounts**
- **Workflows**: `756957797294-compute@developer.gserviceaccount.com`
- **Schedulers**: `workflow-scheduler@nba-props-platform.iam.gserviceaccount.com`

### **Configuration**
- **Project**: `nba-props-platform`
- **Region**: `us-west2`
- **Cloud Run**: `nba-scrapers-756957797294.us-west2.run.app`

---

## 📚 Documentation References

- **Workflow YAML Files**: `workflows/` directory
- **Scraper Documentation**: `docs/scrapers/`
- **Architecture Decisions**: `docs/architecture.md`
- **Migration History**: This README (August 2025 migration)

---

## 🎉 Migration Success

**From:** 17 individual Cloud Scheduler jobs  
**To:** 4 orchestrated Google Cloud Workflows  
**Result:** Better dependency management, error handling, and business logic  
**Status:** Production ✅

---

*Last Updated: August 2025*  
*System Status: Production ✅*  
*Architecture: Google Cloud Workflows + Cloud Run*  
*Migration: Individual Schedulers → Workflows Complete ✅*
