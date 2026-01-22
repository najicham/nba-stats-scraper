# Week 5-6: Self-Heal Expansion - Implementation Complete

**Date:** January 21, 2026  
**Session:** Robustness Improvements - Self-Heal Expansion  
**Status:** ✅ Complete (7/7 tasks)

---

## Summary

Extended the self-healing pipeline to detect and heal Phase 2 and Phase 4 data gaps, with comprehensive alerting and logging.

### What Was Implemented

**Core Capabilities:**
- Phase 2 completeness detection (raw data scrapers)
- Phase 4 completeness detection (precompute processors)  
- Automated healing triggers with correlation tracking
- Slack alerts for all healing operations
- Firestore logging for healing history

**Total:** ~250 lines of new code in `orchestration/cloud_functions/self_heal/main.py`

---

## Implementation Details

### 1. Phase 2 Completeness Detection

**Function:** `check_phase2_completeness(bq_client, target_date)`

**Checks tables:**
```python
- nba_raw.bdl_player_boxscores
- nba_raw.nbac_gamebook_player_stats  
- nba_raw.odds_api_game_lines
- nba_raw.nbac_schedule
```

**Returns:**
```python
{
    'is_complete': bool,           # True if all processors ran
    'missing_processors': list,    # Names of missing processors
    'record_counts': dict          # Processor -> record count mapping
}
```

**Location:** Lines 220-267

---

### 2. Phase 2 Healing Trigger

**Function:** `trigger_phase2_healing(target_date, missing_processors, correlation_id)`

**Current Implementation:**
- Logs need for healing (Phase 1 scrapers don't have individual endpoints yet)
- Returns skipped processors with reason
- Sends alerts and logs to Firestore

**Future Enhancement:**
When Phase 1 scrapers support individual endpoints, will call:
```python
PHASE1_SCRAPER_URL = os.getenv('PHASE1_SCRAPER_URL')
# POST {PHASE1_SCRAPER_URL}/bdl_player_boxscores
# POST {PHASE1_SCRAPER_URL}/nbac_gamebook_player_stats
# etc.
```

**Location:** Lines 494-526

---

### 3. Phase 4 Completeness Detection

**Function:** `check_phase4_completeness(bq_client, target_date)`

**Checks tables:**
```python
- nba_predictions.ml_feature_store_v2 (game_date)
- nba_predictions.player_daily_cache (game_date)
- nba_precompute.player_composite_factors (analysis_date)
```

**Returns:**
```python
{
    'is_complete': bool,           # True if all processors ran
    'missing_processors': list,    # Names of missing tables
    'record_counts': dict          # Table -> record count mapping
}
```

**Location:** Lines 270-312

---

### 4. Phase 4 Healing Trigger

**Function:** `trigger_phase4_healing(target_date, missing_processors, correlation_id)`

**Implementation:**
- Calls existing `trigger_phase4(target_date)` which runs ALL Phase 4 processors
- Running all processors ensures dependencies are satisfied
- Returns success status and list of processors

**Why run all processors?**
Phase 4 has dependency chains:
```
1. TeamDefenseZoneAnalysisProcessor (no deps)
2. PlayerShotZoneAnalysisProcessor (no deps)
3. PlayerDailyCacheProcessor (no deps)
4. PlayerCompositeFactorsProcessor (depends on 1-3)
5. MLFeatureStoreProcessor (depends on 1-4)
```

**Location:** Lines 529-562

---

### 5. Healing Alerts with Correlation IDs

**Function:** `send_healing_alert(phase, target_date, missing_components, healing_triggered, correlation_id)`

**Slack Message Format:**
```
🔧 Self-Heal Triggered: Phase 2

Date: 2026-01-21
Phase: Phase 2
Healing Triggered: ✅ Yes
Correlation ID: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`

Missing Components:
• bdl_player_boxscores
• odds_api_game_lines
```

**Configuration:**
- Requires `SLACK_WEBHOOK_URL` environment variable
- Gracefully skips if not configured
- Uses orange color (#FFA500) for healing alerts

**Location:** Lines 565-621

---

### 6. Firestore Logging

**Function:** `log_healing_to_firestore(phase, target_date, missing_components, healing_result, correlation_id)`

**Document Structure:**
```python
{
    'phase': 'phase2',
    'target_date': '2026-01-21',
    'missing_components': ['bdl_player_boxscores', 'odds_api_game_lines'],
    'healing_result': {
        'triggered': [],
        'failed': [],
        'skipped': ['bdl_player_boxscores', 'odds_api_game_lines'],
        'reason': 'Phase 1 scrapers do not have individual healing endpoints yet'
    },
    'correlation_id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    'timestamp': SERVER_TIMESTAMP,
    'success': False
}
```

**Collection:** `self_heal_history`  
**Document ID:** `{date}_{phase}_{correlation_id[:8]}`  
**Example:** `2026-01-21_phase2_a1b2c3d4`

**Location:** Lines 624-659

---

### 7. Integration into Main Flow

**Updated:** `self_heal_check(request)` function

**New Checks Added:**

#### Phase 2 Check (Lines 765-825)
```python
# Check yesterday's Phase 2 data
if yesterday_games > 0:
    phase2_data = check_phase2_completeness(bq_client, yesterday)
    
    if not phase2_data['is_complete']:
        # Trigger healing
        healing_result = trigger_phase2_healing(
            yesterday, 
            phase2_data['missing_processors'],
            correlation_id
        )
        
        # Send alert
        send_healing_alert(...)
        
        # Log to Firestore
        log_healing_to_firestore(...)
```

#### Phase 4 Check (Lines 932-999)
```python
# Check today's Phase 4 data
if today_games > 0:
    phase4_data = check_phase4_completeness(bq_client, today)
    
    if not phase4_data['is_complete']:
        # Trigger healing
        healing_result = trigger_phase4_healing(
            today,
            phase4_data['missing_processors'],
            correlation_id
        )
        
        # Send alert
        send_healing_alert(...)
        
        # Log to Firestore
        log_healing_to_firestore(...)
```

**Correlation ID:**
- Generated once per self-heal run: `str(uuid.uuid4())`
- Used across all healing operations in same run
- Enables tracking related healing actions

---

## Code Quality

### Syntax Validation
```bash
$ python -m py_compile orchestration/cloud_functions/self_heal/main.py
# ✅ No errors
```

### Error Handling
- All BigQuery queries wrapped in try/except
- Graceful degradation if Slack/Firestore unavailable
- Detailed error logging with truncation
- Continue execution on individual check failures

### Logging
- INFO level: Successful checks and triggers
- WARNING level: Missing data detected
- ERROR level: Healing failures

---

## Usage

### Monitoring Healing Operations

**Check Firestore:**
```python
from google.cloud import firestore
db = firestore.Client()

# Get all healing operations for a date
docs = db.collection('self_heal_history').where('target_date', '==', '2026-01-21').stream()
for doc in docs:
    print(f"{doc.id}: {doc.to_dict()}")
```

**Query by Correlation ID:**
```python
docs = db.collection('self_heal_history').where('correlation_id', '==', 'abc123').stream()
```

**Check Slack Alerts:**
- Self-heal alerts go to configured Slack webhook
- Orange colored messages with 🔧 emoji
- Includes correlation ID for tracking

---

## Testing Recommendations

### Manual Testing

1. **Simulate Phase 2 Missing Data:**
   ```sql
   -- Temporarily rename table
   ALTER TABLE `nba-props-platform.nba_raw.bdl_player_boxscores` 
   RENAME TO `bdl_player_boxscores_backup`;
   
   -- Trigger self-heal
   -- curl to self-heal endpoint
   
   -- Restore table
   ALTER TABLE `nba-props-platform.nba_raw.bdl_player_boxscores_backup`
   RENAME TO `bdl_player_boxscores`;
   ```

2. **Simulate Phase 4 Missing Data:**
   ```sql
   -- Delete records for test date
   DELETE FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
   WHERE DATE(game_date) = '2026-01-21';
   
   -- Trigger self-heal
   -- Verify Phase 4 runs
   ```

3. **Check Correlation ID Tracking:**
   - Trigger self-heal
   - Extract correlation_id from response
   - Query Firestore for all docs with that correlation_id
   - Verify all related operations tracked

### Automated Testing

**Integration Test:**
```python
def test_phase2_completeness_detection():
    """Test Phase 2 completeness detection"""
    from orchestration.cloud_functions.self_heal.main import check_phase2_completeness
    
    bq_client = get_test_client()
    result = check_phase2_completeness(bq_client, '2026-01-20')
    
    assert 'is_complete' in result
    assert 'missing_processors' in result
    assert 'record_counts' in result
```

**E2E Test:**
```python
def test_self_heal_phase4_healing():
    """Test end-to-end Phase 4 healing"""
    # Delete Phase 4 data
    # Trigger self-heal
    # Verify healing triggered
    # Verify data restored
    # Verify Firestore logged
```

---

## Known Limitations

### 1. Phase 2 Healing (Placeholder)
**Issue:** Phase 1 scrapers don't have individual healing endpoints

**Current Behavior:** Logs need for healing but doesn't trigger re-runs

**Workaround:** Manual re-run of Phase 1 scrapers when alerted

**Future Fix:** Add individual scraper endpoints:
```python
POST /bdl_player_boxscores?game_date=2026-01-21
POST /nbac_gamebook_player_stats?game_date=2026-01-21
```

### 2. Phase 4 Processor Selection
**Issue:** Cannot selectively run individual Phase 4 processors

**Current Behavior:** Runs ALL Phase 4 processors when healing

**Impact:** Longer execution time (~3-5 minutes vs <1 minute)

**Rationale:** Ensures all dependencies are satisfied

**Future Optimization:** Smart dependency resolution to run only necessary processors

### 3. Correlation ID Scope
**Issue:** Correlation ID is per self-heal run, not per healing operation

**Impact:** Multiple healings in same run share correlation ID

**Benefit:** Easier to track related operations

**Trade-off:** Cannot distinguish individual healing attempts within same run

---

## Deployment Checklist

### Pre-Deployment

- [x] Code syntax validated
- [x] Error handling implemented
- [ ] Manual testing in staging
- [ ] Integration tests created
- [ ] Firestore permissions verified
- [ ] Slack webhook configured

### Deployment

```bash
# Deploy to staging
gcloud functions deploy self-heal-check \
    --gen2 \
    --region=us-west1 \
    --runtime=python312 \
    --source=orchestration/cloud_functions/self_heal \
    --entry-point=self_heal_check \
    --set-env-vars=SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL} \
    --trigger-http \
    --allow-unauthenticated=false

# Test in staging
curl -X POST https://STAGING_URL/ \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Monitor Firestore
# Check for self_heal_history collection

# Monitor Slack  
# Verify alerts received

# Deploy to production (after 48h validation)
gcloud functions deploy self-heal-check \
    --gen2 \
    --region=us-west1 \
    --runtime=python312 \
    --source=orchestration/cloud_functions/self_heal \
    --entry-point=self_heal_check \
    --set-env-vars=SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL_PROD} \
    --trigger-http \
    --allow-unauthenticated=false \
    --project=nba-props-platform
```

### Post-Deployment

- [ ] Monitor first 24 hours
- [ ] Verify Firestore logging
- [ ] Verify Slack alerts
- [ ] Check for false positives
- [ ] Tune detection thresholds if needed

---

## Success Metrics

### Achieved ✓
- 250+ lines of self-heal expansion code
- 7/7 tasks complete
- Phase 2 and Phase 4 detection implemented
- Correlation ID tracking
- Slack alerting
- Firestore logging
- Zero syntax errors

### To Measure in Production
- Phase 2 healing trigger rate
- Phase 4 healing trigger rate
- Healing success rate
- Time to detect data gaps
- Alert response time

---

## Related Documentation

- [Complete Handoff](./COMPLETE-HANDOFF-JAN-21-2026.md) - Overall project status
- [Week 1-2](./WEEK-1-2-RATE-LIMITING-COMPLETE.md) - Rate limiting implementation
- [Week 3-4](./WEEK-3-4-PHASE-VALIDATION-COMPLETE.md) - Phase validation implementation
- [Test Progress](./TEST-PROGRESS-JAN-21-2026.md) - Unit test coverage

---

**Document Version:** 1.0  
**Last Updated:** January 21, 2026  
**Author:** Claude (Sonnet 4.5)  
**Session ID:** nba-stats-scraper robustness improvements
