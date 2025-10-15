# Cloud Run Production Guide - NBA Analytics Platform

## 🎯 Overview

This guide documents our NBA Analytics scraper service running on Google Cloud Run, explains key concepts, and provides a roadmap for making it production-ready with monitoring, alerting, and resilience features.

## 📋 Current State - What We Built

### **Service Architecture**
```
🌐 Internet Request
    ↓
☁️  Cloud Run Service: nba-scrapers
    ↓ (routes to)
🐳 Container Instance(s)
    ↓ (executes)
📊 Scraper Classes (10 available)
    ↓ (writes to)
🗄️  Google Cloud Storage
```

### **Deployment Details**
- **Service Name**: `nba-scrapers`
- **Region**: `us-west2` (Oregon)
- **URL**: `https://nba-scrapers-f7p3g7f6ya-wl.a.run.app`
- **Container Registry**: Artifact Registry (`us-west2-docker.pkg.dev/nba-props-platform/pipeline/`)
- **Deployment Strategy**: Sophisticated base image with layered builds

---

## 🎓 Cloud Run Terminology & Concepts

### **Service vs Instance vs Revision**

#### **Service** 
- **What**: The top-level Cloud Run resource
- **Think of it as**: Your application's "permanent address"
- **Example**: `nba-scrapers` service lives at a stable URL
- **Lifecycle**: Persists across deployments

#### **Revision**
- **What**: An immutable snapshot of your service configuration + code
- **Think of it as**: A "version" of your service
- **Example**: Each time you deploy, Cloud Run creates a new revision
- **Naming**: Automatically named (e.g., `nba-scrapers-00042-abc`)
- **Traffic**: Can split traffic between revisions (blue/green deployments)

#### **Instance** 
- **What**: A running container serving requests
- **Think of it as**: The actual "worker" handling requests
- **Lifecycle**: Created on-demand when requests come in
- **Scaling**: Cloud Run automatically creates/destroys instances based on load

### **Key Cloud Run Features**

#### **Auto-scaling**
```
0 requests → 0 instances (scale-to-zero)
1 request  → 1 instance  (cold start)
100 requests → 5 instances (automatic scaling)
0 requests → 0 instances (scale back down)
```

#### **Concurrency**
- **Default**: 80 concurrent requests per instance
- **Our setting**: Can be tuned based on scraper performance

#### **Cold Starts**
- **What**: Time for new instance to start when scaling from 0
- **Impact**: First request after idle period takes longer (~2-10 seconds)
- **Mitigation**: Keep warm instances, optimize container startup

---

## 📊 Current Service Configuration

### **Resource Allocation**
```yaml
CPU: 2 vCPU
Memory: 2 GiB
Timeout: 3600 seconds (1 hour)
Max Instances: 10
Concurrency: 80 requests/instance
```

### **Environment Variables**
```bash
GCP_PROJECT=nba-props-platform
GCS_BUCKET_RAW=nba-analytics-raw-data
GCS_BUCKET_PROCESSED=nba-analytics-processed-data
ENVIRONMENT=production
ODDS_API_KEY=***
BDL_API_KEY=***
SENTRY_DSN=***
```

### **Available Scrapers**
1. `oddsa_events_his` - Historical odds events
2. `oddsa_events` - Current odds events  
3. `oddsa_player_props` - Player proposition bets
4. `bdl_players` - Ball Don't Lie players
5. `bdl_games` - Ball Don't Lie games
6. `bdl_box_scores` - Ball Don't Lie box scores
7. `espn_roster` - ESPN team rosters
8. `espn_scoreboard` - ESPN scoreboards
9. `nbac_roster` - NBA.com rosters
10. `nbac_schedule` - NBA.com schedules

---

## 🔍 Making It Production-Ready

### **1. Monitoring & Observability**

#### **Cloud Run Native Metrics (Already Available)**
```bash
# View in Google Cloud Console
Cloud Run → nba-scrapers → Metrics

Key metrics to watch:
- Request count
- Request latency (p50, p95, p99)
- Error rate
- Instance count
- CPU utilization
- Memory utilization
- Container startup time
```

#### **Custom Application Metrics**
Add to your scrapers:

```python
# In scrapers/scraper_base.py
import time
from google.cloud import monitoring_v3

class ScraperBase:
    def __init__(self):
        self.metrics_client = monitoring_v3.MetricServiceClient()
        self.start_time = time.time()
    
    def record_scraper_metrics(self, scraper_name, success, row_count):
        """Record custom metrics for scraper execution"""
        project_name = f"projects/{os.getenv('GCP_PROJECT')}"
        
        # Record execution time
        execution_time = time.time() - self.start_time
        
        # Record success/failure
        # Record data volume
        # etc.
```

#### **Structured Logging**
Enhance logging for better observability:

```python
# In scrapers/main_scraper_service.py
import structlog
import json

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

@app.route('/scrape', methods=['POST'])
def route_scraper():
    logger.info(
        "scraper_request_started",
        scraper=scraper_name,
        request_id=request.headers.get('X-Cloud-Trace-Context'),
        user_agent=request.headers.get('User-Agent')
    )
```

### **2. Health Checks & Probes**

#### **Enhanced Health Check**
```python
@app.route('/health', methods=['GET'])
def health_check():
    """Comprehensive health check"""
    health_status = {
        "status": "healthy",
        "service": "nba-scrapers",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "gcs_connectivity": check_gcs_connection(),
            "api_keys": check_api_keys(),
            "memory_usage": get_memory_usage(),
            "available_scrapers": len(SCRAPER_REGISTRY)
        }
    }
    
    # Return 503 if any critical check fails
    if not all([
        health_status["checks"]["gcs_connectivity"],
        health_status["checks"]["api_keys"]
    ]):
        return jsonify(health_status), 503
    
    return jsonify(health_status), 200

def check_gcs_connection():
    """Verify GCS connectivity"""
    try:
        client = storage.Client()
        bucket = client.bucket(os.getenv('GCS_BUCKET_RAW'))
        bucket.reload()
        return True
    except Exception:
        return False
```

#### **Readiness Probe**
```python
@app.route('/ready', methods=['GET'])
def readiness_check():
    """Check if service is ready to handle requests"""
    return jsonify({
        "ready": True,
        "scrapers_loaded": len(SCRAPER_REGISTRY),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200
```

### **3. Error Handling & Circuit Breakers**

#### **Graceful Error Handling**
```python
from tenacity import retry, stop_after_attempt, wait_exponential

class ScraperBase:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def make_api_call(self, url, **kwargs):
        """API call with retry logic"""
        try:
            response = requests.get(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error("api_call_failed", url=url, error=str(e))
            raise
```

#### **Circuit Breaker Pattern**
```python
from pybreaker import CircuitBreaker

# Add to scraper initialization
api_circuit_breaker = CircuitBreaker(
    fail_max=5,  # Open circuit after 5 failures
    reset_timeout=60  # Try again after 60 seconds
)

@api_circuit_breaker
def protected_api_call(self, url):
    return requests.get(url)
```

### **4. Alerting & Notifications**

#### **Error Rate Alerts**
```yaml
# Cloud Monitoring Alert Policy
Display Name: "NBA Scrapers - High Error Rate"
Condition:
  - Metric: cloud_run_revision/request_count
  - Filter: resource.service_name="nba-scrapers"
  - Threshold: Error rate > 5% for 5 minutes
  - Notification: Slack + Email
```

#### **Memory/CPU Alerts**  
```yaml
# High Memory Usage
Display Name: "NBA Scrapers - High Memory Usage"
Condition:
  - Metric: cloud_run_revision/memory/utilizations
  - Threshold: > 80% for 10 minutes
```

#### **Custom Scraper Alerts**
```python
# In your scrapers
def send_scraper_alert(scraper_name, error_message):
    """Send alert when scraper fails"""
    slack_webhook = os.getenv('SLACK_WEBHOOK_URL')
    
    message = {
        "text": f"🚨 Scraper Alert: {scraper_name}",
        "attachments": [{
            "color": "danger",
            "fields": [
                {"title": "Scraper", "value": scraper_name, "short": True},
                {"title": "Error", "value": error_message, "short": False},
                {"title": "Time", "value": datetime.now().isoformat(), "short": True}
            ]
        }]
    }
    
    requests.post(slack_webhook, json=message)
```

### **5. Auto-healing & Recovery**

#### **Automatic Restarts**
Cloud Run automatically handles:
- ✅ **Container crashes**: Automatically restarts failed instances
- ✅ **Memory leaks**: Kills and restarts high-memory instances  
- ✅ **Hanging requests**: Times out after configured duration
- ✅ **Load balancing**: Routes around unhealthy instances

#### **Enhanced Recovery Logic**
```python
def handle_scraper_failure(scraper_name, error, retry_count=0):
    """Handle scraper failures with intelligent retry"""
    max_retries = 3
    
    if retry_count < max_retries:
        # Exponential backoff
        sleep_time = 2 ** retry_count
        time.sleep(sleep_time)
        
        logger.info(
            "retrying_scraper",
            scraper=scraper_name,
            retry_count=retry_count,
            sleep_time=sleep_time
        )
        
        return retry_scraper(scraper_name, retry_count + 1)
    else:
        # Max retries exceeded - alert and graceful degradation
        send_scraper_alert(scraper_name, str(error))
        return {"status": "failed", "retries_exhausted": True}
```

### **6. Performance Optimization**

#### **Cold Start Reduction**
```yaml
# Cloud Run configuration
Min Instances: 1  # Keep one warm instance
CPU Allocation: "always"  # CPU available during request processing
```

#### **Connection Pooling**
```python
# In scrapers/scraper_base.py
import requests.adapters

class ScraperBase:
    def __init__(self):
        self.session = requests.Session()
        # Configure connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
```

### **7. Security Enhancements**

#### **IAM and Service Accounts**
```bash
# Create dedicated service account for scrapers
gcloud iam service-accounts create nba-scrapers-sa \
    --description="Service account for NBA scrapers" \
    --display-name="NBA Scrapers"

# Grant minimal required permissions
gcloud projects add-iam-policy-binding nba-props-platform \
    --member="serviceAccount:nba-scrapers-sa@nba-props-platform.iam.gserviceaccount.com" \
    --role="roles/storage.objectCreator"  # Only GCS write access
```

#### **Secret Management**
```python
# Use Secret Manager instead of environment variables
from google.cloud import secretmanager

def get_secret(secret_name):
    """Retrieve secret from Secret Manager"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

# Usage
ODDS_API_KEY = get_secret("odds-api-key")
BDL_API_KEY = get_secret("bdl-api-key")
```

### **8. Cost Optimization**

#### **Right-sizing Resources**
```yaml
# Monitor and adjust based on actual usage
CPU: 1 vCPU  # Reduce if underutilized
Memory: 1 GiB  # Reduce if memory usage is low
Timeout: 900s  # Reduce if scrapers complete faster
```

#### **Traffic Splitting for Testing**
```bash
# Deploy new version to 10% of traffic
gcloud run services update-traffic nba-scrapers \
    --to-revisions=new-revision=10,old-revision=90
```

---

## 🚀 Implementation Roadmap

### **Phase 1: Immediate (Next Week)**
- [ ] Add structured logging
- [ ] Enhance health checks
- [ ] Set up basic Cloud Monitoring alerts
- [ ] Add Slack notifications for failures

### **Phase 2: Short-term (Next Month)**  
- [ ] Implement Secret Manager
- [ ] Add custom metrics for scrapers
- [ ] Set up comprehensive alerting
- [ ] Add circuit breakers for external APIs

### **Phase 3: Long-term (Next Quarter)**
- [ ] Implement auto-scaling optimization
- [ ] Add performance profiling
- [ ] Set up automated rollback on failures
- [ ] Implement comprehensive testing pipeline

---

## 📋 Monitoring Dashboard

### **Key Metrics to Track**
```
Service Health:
- Request success rate (target: >99%)
- Request latency p95 (target: <30s)
- Instance count and scaling events
- Error rate by scraper type

Business Metrics:
- Successful scraper runs per day
- Data volume processed (rows/MB)
- API quota usage (Odds API, BDL API)
- GCS storage costs

Operational:
- Container startup time
- Memory/CPU utilization  
- Failed deployment rate
- Alert notification response time
```

### **Sample Dashboard Query**
```sql
-- Cloud Logging query for scraper success rates
resource.type="cloud_run_revision"
resource.labels.service_name="nba-scrapers"
jsonPayload.message="scraper completed successfully"
| summarize count by jsonPayload.scraper
```

---

## 🎯 Production Readiness Checklist

### **Reliability**
- [x] Service deployed and running
- [x] Basic health checks working
- [ ] Comprehensive error handling
- [ ] Automatic retry logic
- [ ] Circuit breakers for external dependencies

### **Observability**  
- [x] Basic Cloud Run metrics
- [x] Application logs
- [ ] Structured logging
- [ ] Custom business metrics
- [ ] Distributed tracing

### **Security**
- [x] HTTPS endpoint
- [x] Non-root container user
- [ ] Dedicated service account
- [ ] Secrets in Secret Manager
- [ ] Network security policies

### **Operations**
- [x] Automated deployment pipeline
- [x] Health checks
- [ ] Monitoring and alerting
- [ ] Runbooks for common issues
- [ ] Backup and recovery procedures

### **Performance**
- [x] Auto-scaling configuration
- [ ] Cold start optimization
- [ ] Connection pooling
- [ ] Resource right-sizing
- [ ] Load testing completed

---

This guide provides a comprehensive roadmap for evolving your NBA Analytics scraper service from a working prototype to a production-ready, resilient system. Each enhancement builds upon the solid foundation you've already established with the sophisticated Cloud Run deployment.
