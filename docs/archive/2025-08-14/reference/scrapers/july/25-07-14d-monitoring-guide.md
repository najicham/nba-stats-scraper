# NBA Data Pipeline - Scraper Monitoring & Tracking Guide

## Overview

This document outlines the monitoring and tracking strategy for NBA data scrapers, focusing on operational visibility without adding complexity to scraper implementations. The approach emphasizes leveraging Google Cloud Platform's built-in monitoring capabilities rather than custom database tracking.

## Monitoring Philosophy

### **Keep Scrapers Simple**
- **Single responsibility**: Collect data, save to GCS, publish completion status
- **No database dependencies**: Reduces complexity and failure modes  
- **Stateless operation**: Easy to restart, scale, and debug
- **File existence = proof of success**: GCS files are the source of truth

### **Monitoring Architecture**
```
Scrapers → GCS + Pub/Sub (completion messages)
Workflows → Built-in execution logs and metrics
Processors → Database tracking (process_tracking table)
Report Generator → Database tracking (report_tracking table)
```

## Workflow Orchestration Logging

### **Google Cloud Workflows Integration**

#### **Built-in Execution Tracking**
Google Cloud Workflows automatically provides comprehensive logging:

```yaml
# Example workflow definition
main:
  steps:
    - morning_data_collection:
        parallel:
          shared: [scraper_results]
          branches:
            - scrape_rosters:
                call: run_scraper
                args:
                  scraper_url: ${roster_scraper_url}
                  timeout: 300
                result: roster_result
            - scrape_injuries:
                call: run_scraper
                args:
                  scraper_url: ${injuries_scraper_url}
                  timeout: 300
                result: injuries_result
            - scrape_schedule:
                call: run_scraper
                args:
                  scraper_url: ${schedule_scraper_url}
                  timeout: 300
                result: schedule_result
    
    - check_dependencies:
        switch:
          - condition: ${roster_result.status == "success"}
            next: afternoon_collection
          - condition: true
            raise: "Critical dependency failed"
```

#### **What You Get Automatically**
- **Execution logs**: Every step start/completion with precise timestamps
- **Error details**: Stack traces, HTTP response codes, timeout information
- **Execution history**: Complete record of past runs with success/failure status
- **Step-level timing**: Performance metrics for each scraper
- **Parallel execution tracking**: Which scrapers ran simultaneously
- **Retry attempts**: Built-in retry logic with attempt counts and backoff
- **Input/output logging**: Parameter values and response data

#### **Accessing Workflow Logs**
```bash
# View recent workflow executions
gcloud workflows executions list --workflow=nba-scraper-workflow --limit=10

# Get detailed execution information
gcloud workflows executions describe EXECUTION_ID --workflow=nba-scraper-workflow

# Stream real-time logs
gcloud logging read "resource.type=workflows.googleapis.com/Workflow" --limit=50 --format=json

# Filter by specific workflow
gcloud logging read 'resource.type="workflows.googleapis.com/Workflow" AND resource.labels.workflow_id="nba-scraper-workflow"'
```

#### **Workflow Monitoring Queries**
```sql
-- Cloud Logging queries for workflow analysis

-- Failed workflow executions
resource.type="workflows.googleapis.com/Workflow"
severity="ERROR"
timestamp >= "2025-07-15T00:00:00Z"

-- Slow-running scrapers (>5 minutes)
resource.type="workflows.googleapis.com/Workflow"
jsonPayload.step_name:"scrape_"
jsonPayload.duration > 300

-- Daily workflow success rate
resource.type="workflows.googleapis.com/Workflow"
jsonPayload.execution_status="SUCCEEDED" OR jsonPayload.execution_status="FAILED"
timestamp >= "2025-07-15T00:00:00Z"
```

## GCS File Monitoring

### **File Pattern Expectations**
Based on your scraper schedule, establish expected file patterns:

```python
# Expected daily file patterns
DAILY_EXPECTED_FILES = {
    'morning': {
        'ball-dont-lie': ['injuries', 'games'],
        'nba-com': ['schedule', 'injury-report'],
        'espn': ['rosters'],
        'odds-api': ['events']
    },
    'afternoon': {
        'odds-api': ['player-props', 'events'],
        'espn': ['scoreboard']
    },
    'evening': {
        'ball-dont-lie': ['boxscores', 'player-box-scores'],
        'nba-com': ['player-boxscores', 'play-by-play'],
        'espn': ['boxscores']
    },
    'night': {
        'big-data-ball': ['play-by-play']
    }
}
```

### **File Monitoring Strategies**

#### 1. **Real-time GCS Notifications**
```python
# Cloud Function triggered by GCS object creation
def on_file_created(event, context):
    """Track file creation in real-time"""
    file_path = event['name']
    bucket = event['bucket']
    
    # Parse file metadata
    metadata = parse_gcs_file_path(file_path)
    
    # Update monitoring dashboard
    update_file_tracking_dashboard({
        'source': metadata['source'],
        'data_type': metadata['data_type'], 
        'date': metadata['date'],
        'timestamp': event['timeCreated'],
        'size': event['size'],
        'status': 'created'
    })
    
    # Check against expected patterns
    validate_expected_file(metadata)

def parse_gcs_file_path(file_path):
    """Extract metadata from GCS file path"""
    # /raw-data/ball-dont-lie/games/2025-07-15/20250715_143000.json
    parts = file_path.split('/')
    return {
        'source': parts[2],           # ball-dont-lie
        'data_type': parts[3],        # games  
        'date': parts[4],             # 2025-07-15
        'filename': parts[5],         # 20250715_143000.json
        'timestamp': extract_timestamp_from_filename(parts[5])
    }
```

#### 2. **Scheduled File Audits**
```python
# Daily health check function
def daily_scraper_audit():
    """Comprehensive daily audit of scraper outputs"""
    target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    audit_results = {}
    
    for time_period, expected in DAILY_EXPECTED_FILES.items():
        period_results = {}
        
        for source, data_types in expected.items():
            source_results = {}
            
            for data_type in data_types:
                files = list_gcs_files(f'/raw-data/{source}/{data_type}/{target_date}/')
                
                source_results[data_type] = {
                    'expected': True,
                    'found': len(files),
                    'files': [f['name'] for f in files],
                    'latest': max([f['updated'] for f in files]) if files else None,
                    'total_size': sum([f['size'] for f in files]),
                    'status': 'healthy' if files else 'missing'
                }
            
            period_results[source] = source_results
        audit_results[time_period] = period_results
    
    # Generate audit report
    generate_audit_report(target_date, audit_results)
    
    # Send alerts for missing data
    send_missing_data_alerts(audit_results)
    
    return audit_results

def list_gcs_files(prefix):
    """List files in GCS with metadata"""
    from google.cloud import storage
    
    client = storage.Client()
    bucket = client.bucket('your-nba-data-bucket')
    
    blobs = bucket.list_blobs(prefix=prefix)
    return [{
        'name': blob.name,
        'size': blob.size,
        'updated': blob.updated,
        'created': blob.time_created
    } for blob in blobs]
```

#### 3. **File Freshness Monitoring**
```python
def check_data_freshness():
    """Monitor data staleness and gaps"""
    freshness_report = {}
    
    for source in ['ball-dont-lie', 'odds-api', 'espn', 'nba-com']:
        source_freshness = {}
        
        # Check each data type for this source
        data_types = get_data_types_for_source(source)
        
        for data_type in data_types:
            latest_file = get_latest_file(source, data_type)
            
            if latest_file:
                age_hours = (datetime.now() - latest_file['created']).total_seconds() / 3600
                source_freshness[data_type] = {
                    'latest_file': latest_file['name'],
                    'age_hours': age_hours,
                    'status': 'fresh' if age_hours < 24 else 'stale'
                }
            else:
                source_freshness[data_type] = {
                    'status': 'missing',
                    'age_hours': float('inf')
                }
        
        freshness_report[source] = source_freshness
    
    return freshness_report
```

## Pub/Sub Message Monitoring

### **Completion Message Tracking**
Monitor scraper completion messages for operational insights:

```python
# Pub/Sub message handler for monitoring
def track_scraper_completion(message):
    """Process scraper completion messages for monitoring"""
    data = json.loads(message.data.decode('utf-8'))
    
    completion_record = {
        'scraper_class': data['scraper_class'],
        'status': data['status'],
        'file_path': data.get('file_path'),
        'timestamp': data['timestamp'],
        'execution_time': data.get('execution_time'),
        'file_size': data.get('file_size'),
        'error_message': data.get('error_message'),
        'parameters': data.get('parameters', {})
    }
    
    # Store in monitoring database
    store_completion_record(completion_record)
    
    # Update real-time dashboard
    update_scraper_dashboard(completion_record)
    
    # Check for alerts
    check_completion_alerts(completion_record)
    
    message.ack()

def store_completion_record(record):
    """Store scraper completion in monitoring table"""
    # Optional: Lightweight monitoring table separate from process tracking
    query = """
    INSERT INTO scraper_completions 
    (scraper_class, status, file_path, timestamp, execution_time, file_size, error_message)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    # Execute query...
```

## Alerting & Notification Strategy

### **Alert Categories**

#### **Critical Alerts (Immediate Response)**
- **Workflow execution failures**: Entire scraper workflow failed
- **Missing dependency data**: Events API failed (blocks prop collection)
- **Schedule disruptions**: Games postponed/rescheduled during game day
- **Data corruption**: Invalid file formats or corrupted data

#### **Warning Alerts (Within 2 Hours)**
- **Individual scraper failures**: Single scraper failed but workflow continued
- **Data delays**: Expected files missing beyond normal schedule
- **Performance degradation**: Scrapers taking significantly longer than usual
- **Capacity issues**: GCS storage or processing limits approaching

#### **Info Alerts (Daily Summary)**
- **Daily completion summary**: Success rates and file counts
- **Data freshness report**: Oldest data by source and type
- **Performance trends**: Average execution times and file sizes
- **Capacity utilization**: Storage and processing resource usage

### **Alert Implementation**

#### **Cloud Monitoring Alert Policies**
```yaml
# Workflow failure alert
displayName: "NBA Scraper Workflow Failed"
conditions:
  - displayName: "Workflow execution failed"
    conditionThreshold:
      filter: 'resource.type="workflows.googleapis.com/Workflow" AND severity="ERROR"'
      comparison: COMPARISON_GREATER_THAN
      thresholdValue: 0
      duration: 60s
notificationChannels:
  - "projects/PROJECT_ID/notificationChannels/SLACK_CHANNEL"

# Missing files alert  
displayName: "Expected Files Missing"
conditions:
  - displayName: "Daily audit found missing files"
    conditionThreshold:
      filter: 'resource.type="cloud_function" AND jsonPayload.missing_files > 0'
      comparison: COMPARISON_GREATER_THAN  
      thresholdValue: 0
      duration: 300s

# Performance degradation alert
displayName: "Scraper Performance Degraded"
conditions:
  - displayName: "Execution time exceeded threshold"
    conditionThreshold:
      filter: 'resource.type="workflows.googleapis.com/Workflow" AND jsonPayload.execution_time > 600'
      comparison: COMPARISON_GREATER_THAN
      thresholdValue: 0
      duration: 120s
```

#### **Custom Alert Functions**
```python
def send_slack_alert(message, severity='warning'):
    """Send alert to Slack channel"""
    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    
    color_map = {
        'critical': '#FF0000',
        'warning': '#FFA500', 
        'info': '#00FF00'
    }
    
    payload = {
        'attachments': [{
            'color': color_map.get(severity, '#FFA500'),
            'title': f'NBA Data Pipeline Alert - {severity.upper()}',
            'text': message,
            'timestamp': int(datetime.now().timestamp())
        }]
    }
    
    requests.post(webhook_url, json=payload)

def send_email_alert(subject, body, recipients):
    """Send email alert for critical issues"""
    # Use SendGrid, Gmail API, or Cloud Pub/Sub → Cloud Functions
    pass

def check_completion_alerts(completion_record):
    """Check completion record against alert conditions"""
    if completion_record['status'] == 'failure':
        if completion_record['scraper_class'] in CRITICAL_SCRAPERS:
            send_slack_alert(
                f"CRITICAL: {completion_record['scraper_class']} failed: {completion_record['error_message']}", 
                severity='critical'
            )
        else:
            send_slack_alert(
                f"WARNING: {completion_record['scraper_class']} failed: {completion_record['error_message']}", 
                severity='warning'
            )
    
    # Check performance alerts
    if completion_record.get('execution_time', 0) > 600:  # 10 minutes
        send_slack_alert(
            f"PERFORMANCE: {completion_record['scraper_class']} took {completion_record['execution_time']}s",
            severity='warning'
        )
```

## Monitoring Dashboard

### **Real-time Status Dashboard**
```python
def generate_dashboard_data():
    """Generate data for monitoring dashboard"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    dashboard_data = {
        'last_updated': datetime.now().isoformat(),
        'date': today,
        'workflow_status': get_workflow_status(),
        'scraper_health': get_scraper_health_status(today),
        'file_counts': get_daily_file_counts(today),
        'data_freshness': check_data_freshness(),
        'alerts': get_active_alerts(),
        'performance_metrics': get_performance_metrics()
    }
    
    return dashboard_data

def get_scraper_health_status(date):
    """Get health status for each scraper"""
    health_status = {}
    
    for scraper_class in ALL_SCRAPERS:
        files = get_files_for_scraper(scraper_class, date)
        latest_completion = get_latest_completion(scraper_class)
        
        health_status[scraper_class] = {
            'files_today': len(files),
            'expected_runs': get_expected_runs(scraper_class),
            'last_success': latest_completion['timestamp'] if latest_completion else None,
            'status': determine_health_status(scraper_class, files, latest_completion)
        }
    
    return health_status
```

### **Dashboard Display Format**
```
NBA Data Pipeline Status - July 15, 2025 14:30 ET

📊 WORKFLOW STATUS
✅ Morning Collection: Completed (3/3 scrapers)
🟡 Afternoon Prep: In Progress (2/3 scrapers)  
⚪ Evening Results: Pending
⚪ Night Analytics: Pending

📈 SCRAPER HEALTH  
✅ BdlGamesScraper: 3/3 runs (Last: 14:15)
✅ BdlInjuriesScraper: 4/4 runs (Last: 14:20)
❌ GetOddsApiEvents: 0/2 runs (Failed since 12:00)
🟡 GetEspnScoreboard: 1/2 runs (Delayed)

📁 FILE COUNTS
ball-dont-lie: 45 files (102MB)
odds-api: 12 files (34MB) 
espn: 28 files (78MB)
nba-com: 19 files (156MB)

⚠️  ACTIVE ALERTS
1. GetOddsApiEvents failing for 2 hours
2. Player props collection blocked waiting for events
```

## Implementation Steps

### **Phase 1: Basic Monitoring**
1. Set up workflow execution logging
2. Implement GCS file creation notifications
3. Create basic Slack alerting for failures
4. Build simple dashboard showing scraper status

### **Phase 2: Enhanced Tracking**
1. Add daily file audit functions
2. Implement performance monitoring
3. Create comprehensive alert policies
4. Build detailed monitoring dashboard

### **Phase 3: Advanced Analytics**
1. Historical trend analysis
2. Predictive failure detection
3. Capacity planning metrics
4. Advanced performance optimization

## Future Improvements

### **Machine Learning Enhancement**
- **Anomaly detection**: Identify unusual file sizes, timing patterns, or data distributions
- **Predictive maintenance**: Forecast scraper failures based on historical patterns  
- **Auto-scaling triggers**: Dynamic resource allocation based on predicted workloads

### **Advanced Monitoring Features**
- **Data quality metrics**: Content validation beyond just file existence
- **Cross-source correlation**: Detect inconsistencies between data sources
- **Business impact tracking**: Connect technical failures to business metrics
- **A/B testing framework**: Compare different scraper implementations

### **Operational Enhancements**
- **Auto-remediation**: Automatic retry of failed scrapers with backoff
- **Intelligent alerting**: Context-aware alerts based on business calendar
- **Capacity optimization**: Right-sizing based on actual usage patterns
- **Multi-region deployment**: Geographic redundancy for critical data sources

### **Integration Opportunities**
- **External monitoring**: Integration with Datadog, New Relic, or similar platforms
- **Business intelligence**: Connect scraper metrics to business dashboards
- **Cost optimization**: Track and optimize GCS storage and compute costs
- **Compliance monitoring**: Audit trails for data governance requirements

## Key Metrics to Track

### **Operational Metrics**
- **Scraper success rate**: Percentage of successful runs per scraper per day
- **Data completeness**: Files received vs. files expected  
- **Processing latency**: Time from scraper completion to database storage
- **Error recovery time**: Time to resolve failed scraper runs

### **Performance Metrics**
- **Execution time trends**: Average scraper runtime over time
- **File size trends**: Data volume growth patterns
- **Resource utilization**: CPU, memory, and storage usage
- **Cost per data point**: Economic efficiency of data collection

### **Business Metrics**  
- **Data freshness**: Age of most recent data for critical sources
- **Coverage completeness**: Percentage of games/players/props covered
- **Prediction accuracy**: How monitoring helps predict issues
- **Business impact**: Revenue/decision impact of data delays

This comprehensive monitoring approach provides visibility into scraper operations without adding complexity to the scraper implementations themselves, leveraging GCP's built-in capabilities while providing the operational insights needed for a production data pipeline.
