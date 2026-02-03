# Phase 6 Subset Exporters - Push Strategy

**Date:** 2026-02-03
**Status:** Proposed

## Summary

Phase 6 subset exporters should use **event-driven + hourly hybrid** strategy:
- Subset picks update immediately after predictions (event-driven)
- Performance/signals refresh hourly during game day (to reflect completed games)
- Definitions update daily (rarely change)

## Exporter Push Patterns

### 1. AllSubsetsPicksExporter (Main Endpoint)

**Endpoint:** `/picks/{date}.json`
**Update Pattern:** **Event-Driven** (after predictions)
**Cache:** 5 minutes

**Why:**
- Picks depend on predictions → must update when predictions change
- No need to update during games (picks are for pre-game betting)
- Lines might change, but predictions don't regenerate mid-day

**Triggers:**
1. **Primary:** Phase 5 predictions complete (via `phase5_to_phase6` orchestrator)
2. **Secondary:** Manual re-prediction (via `phase6-tonight-picks` scheduler at 1 PM)

**Implementation:**
```python
# In phase5_to_phase6/main.py
TONIGHT_EXPORT_TYPES = [
    'tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks',
    'subset-picks',      # NEW
    'daily-signals',     # NEW
]
```

---

### 2. DailySignalsExporter

**Endpoint:** `/signals/{date}.json`
**Update Pattern:** **Event-Driven** (after predictions)
**Cache:** 5 minutes

**Why:**
- Signal is calculated from prediction distribution (pct_over, etc.)
- Only changes when predictions change
- Pre-game metric, doesn't need live updates

**Triggers:**
1. Same as AllSubsetsPicksExporter (tied to predictions)

---

### 3. SubsetPerformanceExporter

**Endpoint:** `/subsets/performance.json`
**Update Pattern:** **Hourly** (6 AM - 11 PM ET) + **Post-Game** (2 AM ET)
**Cache:** 1 hour

**Why:**
- Performance changes as games complete and get graded
- Needs fresh data throughout the day
- Website might show "last 7 days" performance → should reflect tonight's results

**Triggers:**
1. **Hourly refresh:** Use existing `phase6-hourly-trends` scheduler
2. **Post-game update:** After grading completes (~2 AM ET next day)

**Implementation:**
```python
# Add to phase6-hourly-trends scheduler
{"export_types": ["trends-hot-cold", "trends-bounce-back", "tonight-trend-plays",
                  "subset-performance"], "target_date": "today"}
```

---

### 4. SubsetDefinitionsExporter

**Endpoint:** `/systems/subsets.json`
**Update Pattern:** **Daily** (6 AM ET)
**Cache:** 24 hours

**Why:**
- Definitions rarely change (only when adding new subsets)
- Static metadata
- No need for frequent updates

**Triggers:**
1. **Daily:** Use existing `phase6-daily-results` scheduler at 5 AM

**Implementation:**
```python
# Add to phase6-daily-results scheduler
{"export_types": ["results", "performance", "best-bets",
                  "subset-definitions"], "target_date": "yesterday"}
```

---

## Integration Plan

### Step 1: Add to Event-Driven Flow (Immediate)

**File:** `orchestration/cloud_functions/phase5_to_phase6/main.py`

```python
# Line 77 - Add new export types
TONIGHT_EXPORT_TYPES = [
    'tonight',
    'tonight-players',
    'predictions',
    'best-bets',
    'streaks',
    'subset-picks',      # NEW - All 9 groups in one file
    'daily-signals',     # NEW - Market signal
]
```

### Step 2: Add to Hourly Refresh

**Scheduler:** `phase6-hourly-trends` (already runs 6 AM - 11 PM hourly)

```bash
# Update scheduler configuration
gcloud scheduler jobs update pubsub phase6-hourly-trends \
  --location=us-west2 \
  --message-body='{"export_types": ["trends-hot-cold", "trends-bounce-back", "tonight-trend-plays", "subset-performance"], "target_date": "today"}'
```

### Step 3: Add to Daily Batch

**Scheduler:** `phase6-daily-results` (runs 5 AM ET)

```bash
# Update scheduler configuration
gcloud scheduler jobs update pubsub phase6-daily-results \
  --location=us-west2 \
  --message-body='{"export_types": ["results", "performance", "best-bets", "subset-definitions"], "target_date": "yesterday"}'
```

### Step 4: Update daily_export.py

**File:** `backfill_jobs/publishing/daily_export.py`

```python
# Add imports
from data_processors.publishing.subset_definitions_exporter import SubsetDefinitionsExporter
from data_processors.publishing.daily_signals_exporter import DailySignalsExporter
from data_processors.publishing.subset_performance_exporter import SubsetPerformanceExporter
from data_processors.publishing.all_subsets_picks_exporter import AllSubsetsPicksExporter

# Update EXPORT_TYPES list (line 83)
EXPORT_TYPES = [
    'results', 'performance', 'best-bets', 'predictions',
    'tonight', 'tonight-players', 'streaks',
    # Trends v2
    'trends-hot-cold', 'trends-bounce-back', 'trends-what-matters',
    'trends-team', 'trends-quick-hits', 'trends-deep-dive',
    # Frontend API Backend (Session 143)
    'tonight-trend-plays',
    # Live scoring for Challenge System
    'live', 'live-grading',
    # Phase 6 Subset Exports (NEW)
    'subset-picks', 'daily-signals', 'subset-performance', 'subset-definitions',
    # Shorthand groups
    'trends-daily', 'trends-weekly', 'trends-all'
]

# Add to export_date() function (after line 327)
# Subset picks exporter (all 9 groups)
if 'subset-picks' in export_types:
    try:
        exporter = AllSubsetsPicksExporter()
        path = exporter.export(target_date)
        result['paths']['subset_picks'] = path
        logger.info(f"  Subset Picks: {path}")
    except Exception as e:
        result['errors'].append(f"subset-picks: {e}")
        logger.error(f"  Subset Picks error: {e}")

# Daily signals exporter
if 'daily-signals' in export_types:
    try:
        exporter = DailySignalsExporter()
        path = exporter.export(target_date)
        result['paths']['daily_signals'] = path
        logger.info(f"  Daily Signals: {path}")
    except Exception as e:
        result['errors'].append(f"daily-signals: {e}")
        logger.error(f"  Daily Signals error: {e}")

# Subset performance exporter
if 'subset-performance' in export_types:
    try:
        exporter = SubsetPerformanceExporter()
        path = exporter.export()
        result['paths']['subset_performance'] = path
        logger.info(f"  Subset Performance: {path}")
    except Exception as e:
        result['errors'].append(f"subset-performance: {e}")
        logger.error(f"  Subset Performance error: {e}")

# Subset definitions exporter
if 'subset-definitions' in export_types:
    try:
        exporter = SubsetDefinitionsExporter()
        path = exporter.export()
        result['paths']['subset_definitions'] = path
        logger.info(f"  Subset Definitions: {path}")
    except Exception as e:
        result['errors'].append(f"subset-definitions: {e}")
        logger.error(f"  Subset Definitions error: {e}")
```

---

## Alternative Considered: Live Feed Integration

**Not Recommended** for subset picks because:

| Factor | Live Feed (3 min) | Event-Driven (once) | Winner |
|--------|------------------|---------------------|--------|
| Data freshness | Overkill - picks don't change | Sufficient | Event ✅ |
| Server load | High (20 exports/hour) | Low (2-3/day) | Event ✅ |
| Cache effectiveness | Poor (3 min TTL) | Good (5 min TTL) | Event ✅ |
| Use case fit | Real-time scoring | Pre-game betting | Event ✅ |
| Cost | $$$$ | $ | Event ✅ |

**Live feed is for:**
- Live game scores (every possession matters)
- Challenge grading (real-time accuracy)
- Status updates (injury, lineup changes)

**Subset picks are for:**
- Pre-game betting decisions
- Research/analysis
- Historical comparison

---

## Expected File Update Frequency

| File | Updates/Day | When |
|------|-------------|------|
| `/picks/{date}.json` | 2-3 | After predictions (2:30 AM, 7 AM, 11:30 AM) |
| `/signals/{date}.json` | 2-3 | Same as picks |
| `/subsets/performance.json` | 18 | Hourly 6 AM-11 PM + post-game 2 AM |
| `/systems/subsets.json` | 1 | Daily 6 AM |

---

## Monitoring & Validation

### Verify Event-Driven Export

```bash
# Check if subset picks are exported after predictions
gcloud logging read 'resource.type="cloud_function_2nd_gen"
  AND resource.labels.function_name="phase5_to_phase6"
  AND textPayload=~"subset-picks"' \
  --limit=5 --freshness=2h

# Verify GCS file was created
gsutil ls -l gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json
```

### Verify Hourly Refresh

```bash
# Check subset performance hourly updates
gsutil ls -lh gs://nba-props-platform-api/v1/subsets/performance.json

# Should show updated timestamp within last hour
```

---

## Rollback Plan

If subset exports cause issues:

```python
# In phase5_to_phase6/main.py - remove from TONIGHT_EXPORT_TYPES
TONIGHT_EXPORT_TYPES = [
    'tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks',
    # 'subset-picks',      # DISABLED
    # 'daily-signals',     # DISABLED
]

# Redeploy orchestrator
gcloud functions deploy phase5-to-phase6 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/phase5_to_phase6
```

---

## Summary

**Recommended Strategy:**
1. ✅ **Subset picks** → Event-driven (after predictions)
2. ✅ **Daily signals** → Event-driven (after predictions)
3. ✅ **Subset performance** → Hourly refresh (6 AM-11 PM)
4. ✅ **Subset definitions** → Daily (6 AM)

**Not using live feed (3 min) because:**
- Picks don't change during games
- Unnecessary server load
- Poor cache hit rate
- Wrong use case fit

**Total new files:** 4 exporters, ~20 exports/day, minimal infrastructure changes
