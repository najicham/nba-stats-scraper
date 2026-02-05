# Session 135 - Self-Healing with Observability Implementation

**Date:** 2026-02-05
**Status:** ✅ COMPLETE
**Philosophy:** "Auto-heal, but track everything so we can prevent recurrence"

## Executive Summary

Implemented self-healing infrastructure with full audit trail. System now auto-heals stalled prediction batches while tracking every action for root cause analysis and prevention.

**Key Achievement:** Self-healing that enables prevention, not masks problems

## What Was Completed

### 1. Investigation (Agents) ✅

**Bug #1: Worker Injury Handling**
- **Status:** ✅ ALREADY FIXED in Session 131
- **Root Cause:** `'player_injury_out'` missing from `PERMANENT_SKIP_REASONS`
- **Impact:** Eliminated 12,240 retries/day for injured players
- **Commit:** `73f58e33`

**Bug #2: Batch Completion Tracking**
- **Status:** ✅ NOT A BUG - Expected behavior
- **Finding:** Dark deploy phase, feature flag OFF by design
- **Recommendation:** No action needed (cosmetic only)

### 2. Healing Infrastructure ✅

**Component:** `shared/utils/healing_tracker.py` (374 lines)

**Features:**
- Dual-write to Firestore (real-time) + BigQuery (analytics)
- Pattern detection with automatic alerting
- Success rate tracking
- Root cause aggregation

**Alert Thresholds:**
- Yellow: 3+ healings in 1 hour
- Red: 10+ healings in 24 hours
- Critical: >20% failure rate

**Healing Event Schema:**
```python
{
    'healing_id': str,  # Unique ID
    'timestamp': datetime,
    'healing_type': str,  # 'batch_cleanup', 'retry', 'fallback', etc.
    'trigger_reason': str,  # Why healing was needed (ROOT CAUSE)
    'action_taken': str,  # What we did
    'before_state': dict,  # State before healing
    'after_state': dict,  # State after healing
    'success': bool,  # Did it work?
    'metadata': dict  # Type-specific data
}
```

### 3. Auto-Batch Cleanup ✅

**Component:** `bin/monitoring/auto_batch_cleanup.py` (437 lines)

**Triggers:**
- Batch stalled 15+ minutes
- Completion >= 90%
- Created within 24 hours

**Actions:**
1. Marks batch as complete
2. Sets `auto_completed: true` flag
3. Records full before/after state
4. Tracks in healing_events
5. Alerts if cleanup runs too frequently

**Observability:**
- Every cleanup logged to Firestore + BigQuery
- Slack alerts with stall details
- Pattern analysis (1h and 24h windows)
- Root cause tracking

### 4. Analysis Tools ✅

**Component:** `bin/monitoring/analyze_healing_patterns.py` (288 lines)

**Features:**
- Query healing events by time range or type
- Success rate analysis
- Root cause aggregation
- Top 5 common triggers
- CSV export for deeper analysis
- Automated recommendations

**Usage:**
```bash
# Last 24 hours
python bin/monitoring/analyze_healing_patterns.py

# Specific time range
python bin/monitoring/analyze_healing_patterns.py \
    --start "2026-02-05 00:00" \
    --end "2026-02-05 23:59"

# Export to CSV
python bin/monitoring/analyze_healing_patterns.py --export report.csv
```

### 5. Deployment Infrastructure ✅

**Component:** `bin/monitoring/setup_auto_batch_cleanup.sh`

**Creates:**
- BigQuery table: `nba_orchestration.healing_events`
- Cloud Run Job: `nba-auto-batch-cleanup`
- Cloud Scheduler: Runs every 15 minutes

### 6. BigQuery Schema ✅

**Table:** `nba_orchestration.healing_events`

**Fields:**
- healing_id (STRING, REQUIRED)
- timestamp (TIMESTAMP, REQUIRED)
- healing_type (STRING, REQUIRED)
- trigger_reason (STRING, REQUIRED) ← ROOT CAUSE
- action_taken (STRING, REQUIRED)
- before_state (STRING, NULLABLE) - JSON
- after_state (STRING, NULLABLE) - JSON
- success (BOOLEAN, REQUIRED)
- metadata (STRING, NULLABLE) - JSON

## How It Works

### Healing Flow

```
1. Auto-batch cleanup runs every 15 minutes
   ↓
2. Finds stalled batches (>90% complete, stalled 15+ min)
   ↓
3. For each stalled batch:
   - Capture before_state (completion %, stall time, players)
   - Mark batch complete in Firestore
   - Capture after_state
   - Record healing event in tracker
   ↓
4. Healing tracker:
   - Writes to Firestore (real-time)
   - Writes to BigQuery (analytics)
   - Checks for patterns (1h, 24h windows)
   - Alerts if too frequent
   ↓
5. If pattern detected (3+ in 1h, 10+ in 24h):
   - Send Slack alert
   - Include root causes
   - Provide investigation query
```

### Pattern Detection

**Yellow Alert (3+ in 1 hour):**
```
⚠️ YELLOW ALERT: batch_cleanup triggered 3 times in 1h

Recent Events:
• 14:30:45: Batch stalled at 87.5% (injured players)
• 14:15:22: Batch stalled at 91.2% (worker timeout)
• 14:00:11: Batch stalled at 93.1% (injured players)

Action Required:
1. Review healing events
2. Identify root cause
3. Implement prevention fix
```

**Red Alert (10+ in 24 hours):**
```
🔴 RED ALERT: batch_cleanup triggered 12 times in 24h

This indicates a systemic issue causing batches to stall.
Review healing events to identify root cause:

SELECT * FROM nba_orchestration.healing_events
WHERE healing_type = 'batch_cleanup'
ORDER BY timestamp DESC LIMIT 20
```

**Critical Alert (>20% failure rate):**
```
🚨 CRITICAL: batch_cleanup has 30% failure rate (3/10 failed in 1h)

Healing itself is failing. Immediate investigation required.
```

## Observability Features

### 1. Real-Time Tracking (Firestore)

**Collection:** `healing_events`

**Query recent healings:**
```python
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')

events = db.collection('healing_events') \
    .order_by('timestamp', direction=firestore.Query.DESCENDING) \
    .limit(10) \
    .stream()

for event in events:
    data = event.to_dict()
    print(f"{data['healing_type']}: {data['trigger_reason']}")
```

### 2. Analytics (BigQuery)

**Most common root causes:**
```sql
SELECT
    trigger_reason,
    COUNT(*) as occurrences,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate
FROM `nba-props-platform.nba_orchestration.healing_events`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY trigger_reason
ORDER BY occurrences DESC
LIMIT 10
```

**Healing frequency over time:**
```sql
SELECT
    DATE(timestamp) as date,
    healing_type,
    COUNT(*) as events_per_day
FROM `nba-props-platform.nba_orchestration.healing_events`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date, healing_type
ORDER BY date DESC, events_per_day DESC
```

### 3. Batch Audit Trail

**Auto-completed batches:**
```python
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')

batches = db.collection('prediction_batches') \
    .where('auto_completed', '==', True) \
    .stream()

for batch in batches:
    data = batch.to_dict()
    print(f"{batch.id}: {data.get('auto_completion_reason')}")
```

## Prevention Workflow

### Step 1: Detect Pattern
Auto-batch cleanup runs → triggers 3+ times in 1 hour → Yellow alert

### Step 2: Analyze Root Causes
```bash
python bin/monitoring/analyze_healing_patterns.py --type batch_cleanup
```

Output:
```
TOP 5 ROOT CAUSES
Batch stalled at 87% (injured players): 8x
Batch stalled at 91% (worker timeout): 3x
Batch stalled at 93% (missing features): 2x
```

### Step 3: Implement Prevention
**Example:** 87% stalls due to injured players
- **Investigation:** Worker returning 500 for OUT players
- **Root Cause:** Missing from PERMANENT_SKIP_REASONS
- **Prevention Fix:** Add to classification set
- **Result:** Eliminates 8/13 stalls (62% reduction)

### Step 4: Monitor Impact
```bash
python bin/monitoring/analyze_healing_patterns.py \
    --start "2026-02-06 00:00" \
    --end "2026-02-06 23:59"
```

Expected: Stall frequency decreases from 3/hour → 1/hour

## Deployment

### Prerequisites

```bash
# Create BigQuery table
bq mk --table \
    --project_id=nba-props-platform \
    nba_orchestration.healing_events \
    schemas/nba_orchestration/healing_events.json
```

### Deploy Auto-Cleanup

```bash
chmod +x bin/monitoring/setup_auto_batch_cleanup.sh
./bin/monitoring/setup_auto_batch_cleanup.sh
```

**Creates:**
- Cloud Run Job: `nba-auto-batch-cleanup`
- Cloud Scheduler: Runs every 15 minutes

### Verify Deployment

```bash
# Manual test
gcloud run jobs execute nba-auto-batch-cleanup \
    --region us-west2 --project nba-props-platform

# Check logs
gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=nba-auto-batch-cleanup" \
    --limit 50 --project nba-props-platform

# Query healing events
bq query --use_legacy_sql=false "
    SELECT * FROM nba_orchestration.healing_events
    ORDER BY timestamp DESC LIMIT 10
"
```

## Success Metrics

**Healing Effectiveness:**
- Auto-cleanup success rate: Target >95%
- Time to heal: <5 minutes from stall detection
- Alert precision: <5% false positives

**Prevention Impact:**
- Healing frequency trend: Decreasing week-over-week
- Root cause diversity: Fewer unique triggers over time
- Manual intervention: Reduced by 70%

## Files Created (7 total)

```
shared/utils/
└── healing_tracker.py                              (374 lines)

bin/monitoring/
├── auto_batch_cleanup.py                           (437 lines)
├── analyze_healing_patterns.py                     (288 lines)
└── setup_auto_batch_cleanup.sh                     (80 lines)

schemas/nba_orchestration/
└── healing_events.json                             (48 lines)

docs/08-projects/current/self-healing-with-observability/
├── README.md                                       (75 lines)
└── SESSION-135-IMPLEMENTATION.md                   (this file)
```

## Known Issues

None - all components tested and ready for deployment

## Next Steps

### Deploy Resilience Monitoring (15 min)
From earlier Session 135 work:
- Deploy deployment drift alerter
- Deploy pipeline canary queries
- Create Slack channels and webhooks

### Monitor Healing Patterns (7 days)
- Track auto-cleanup frequency
- Analyze root causes
- Implement prevention fixes
- Tune thresholds if needed

### Extend Healing Types (Future)
Currently supports:
- `batch_cleanup` (implemented)

Future healing types to add:
- `retry` - Intelligent retry with exponential backoff
- `fallback` - Graceful degradation to backup data sources
- `circuit_breaker_reset` - Auto-reset after cooldown
- `cache_refresh` - Refresh stale cache data
- `worker_restart` - Restart hung workers

## Related Documentation

- [Resilience Improvements README](../resilience-improvements-2026/README.md)
- [Session 130 Handoff](../../../09-handoff/2026-02-05-SESSION-130-BATCH-UNBLOCK-AND-MONITORING.md)
- [Session 131 Handoff](../../../09-handoff/2026-02-05-SESSION-131-INJURY-HANDLING-FIX.md)

## Key Learnings

**Pattern:** Self-healing without observability masks problems. Observable self-healing prevents them.

**Anti-Pattern:** Silent auto-recovery that prevents root cause analysis.

**Best Practice:** Every healing action must include:
1. Root cause (trigger_reason)
2. Before/after state
3. Success/failure tracking
4. Pattern detection
5. Alert on frequency

**Prevention Focus:** Healing events are data for prevention. Use them to eliminate root causes, not just symptoms.
