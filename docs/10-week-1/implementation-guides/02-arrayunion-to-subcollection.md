# Implementation Guide: ArrayUnion to Subcollection Migration

**Time:** 2-4 hours (dual-write pattern for safety)
**Priority:** 🔴 CRITICAL
**Impact:** Unlimited player scalability
**Risk:** Medium (data migration)

---

## 🎯 Overview

### Problem
The `completed_players` field in Firestore batch documents uses ArrayUnion, which has a soft limit of ~1,000 elements. With 450+ active NBA players per day, we're approaching this limit.

### Solution
Migrate to subcollection pattern where each completion is a separate document. This provides:
- Unlimited scalability
- Better write performance (no array scanning)
- Easier queries
- Atomic counter updates

### Approach
**Dual-write pattern** for safety:
1. Write to both old (array) and new (subcollection)
2. Validate both structures match
3. Switch reads to new structure
4. Stop writing to old structure
5. Clean up old data

---

## 📋 Prerequisites

### Knowledge Required
- Firestore data modeling
- Firestore transactions
- Python dataclasses
- Feature flags

### Files to Review
- `predictions/coordinator/batch_state_manager.py` - Main file to modify
- `predictions/coordinator/coordinator.py` - Completion event handler

### Environment Setup
```bash
# Create feature branch
git checkout -b feature/subcollection-completions

# Install dependencies (if needed)
pip install google-cloud-firestore

# Set up local Firestore emulator (optional)
gcloud emulators firestore start
```

---

## 🔧 Implementation Steps

### Step 1: Update Data Model (30 min)

**File:** `predictions/coordinator/batch_state_manager.py`

Add new subcollection methods:

```python
from google.cloud import firestore
from google.cloud.firestore_v1 import Increment
from datetime import datetime, timezone

class BatchStateManager:
    def __init__(self, db):
        self.db = db
        self.collection = db.collection('predictions_batches')

        # Feature flags
        self.enable_subcollection = os.getenv('ENABLE_SUBCOLLECTION_COMPLETIONS', 'false').lower() == 'true'
        self.dual_write_mode = os.getenv('DUAL_WRITE_MODE', 'true').lower() == 'true'
        self.use_subcollection_reads = os.getenv('USE_SUBCOLLECTION_READS', 'false').lower() == 'true'

    def record_completion_subcollection(self, batch_id: str, player_lookup: str,
                                       predictions_count: int) -> None:
        """
        Record completion in subcollection (new approach).

        Structure:
        predictions_batches/{batch_id}/completions/{player_lookup}
        {
            completed_at: timestamp,
            predictions_count: int
        }
        """
        batch_ref = self.collection.document(batch_id)
        completion_ref = batch_ref.collection('completions').document(player_lookup)

        # Write completion document
        completion_ref.set({
            'completed_at': firestore.SERVER_TIMESTAMP,
            'predictions_count': predictions_count,
            'player_lookup': player_lookup
        })

        # Update counters atomically
        batch_ref.update({
            'completed_count': Increment(1),
            'total_predictions': Increment(predictions_count),
            'last_updated': firestore.SERVER_TIMESTAMP
        })

        logger.info(f"Recorded completion for {player_lookup} in subcollection")

    def get_completed_players_subcollection(self, batch_id: str) -> list:
        """
        Get completed players from subcollection (new approach).
        """
        batch_ref = self.collection.document(batch_id)
        completions = batch_ref.collection('completions').stream()

        completed_players = [comp.id for comp in completions]
        logger.info(f"Retrieved {len(completed_players)} completed players from subcollection")

        return completed_players

    def get_completion_count_subcollection(self, batch_id: str) -> int:
        """
        Get completion count from counter (efficient).
        """
        batch_ref = self.collection.document(batch_id)
        batch_doc = batch_ref.get()

        if batch_doc.exists:
            return batch_doc.to_dict().get('completed_count', 0)

        return 0
```

---

### Step 2: Implement Dual-Write Logic (30 min)

Update the main `record_completion` method to support dual-write:

```python
def record_completion(self, batch_id: str, player_lookup: str,
                     predictions_count: int) -> None:
    """
    Record completion with dual-write support.

    Dual-write pattern:
    1. Write to old structure (ArrayUnion)
    2. Write to new structure (subcollection)
    3. Both writes must succeed
    """
    batch_ref = self.collection.document(batch_id)

    if self.enable_subcollection:
        if self.dual_write_mode:
            # DUAL-WRITE MODE: Write to both old and new
            logger.info(f"Dual-write mode: Recording {player_lookup} to both structures")

            # Write to OLD structure (ArrayUnion)
            batch_ref.update({
                'completed_players': firestore.ArrayUnion([player_lookup]),
                'last_updated': firestore.SERVER_TIMESTAMP
            })

            # Write to NEW structure (subcollection)
            self.record_completion_subcollection(batch_id, player_lookup, predictions_count)

            # Validate consistency (optional but recommended)
            self._validate_dual_write_consistency(batch_id)

        else:
            # NEW STRUCTURE ONLY: Only write to subcollection
            logger.info(f"Subcollection mode: Recording {player_lookup} to subcollection only")
            self.record_completion_subcollection(batch_id, player_lookup, predictions_count)
    else:
        # OLD BEHAVIOR: Only ArrayUnion
        logger.info(f"Legacy mode: Recording {player_lookup} to array only")
        batch_ref.update({
            'completed_players': firestore.ArrayUnion([player_lookup]),
            'last_updated': firestore.SERVER_TIMESTAMP
        })

def _validate_dual_write_consistency(self, batch_id: str) -> None:
    """
    Validate that array and subcollection have same count.
    Log warning if mismatch detected.
    """
    try:
        # Get array count
        batch_doc = self.collection.document(batch_id).get()
        array_count = len(batch_doc.to_dict().get('completed_players', []))

        # Get subcollection count
        subcoll_count = self.get_completion_count_subcollection(batch_id)

        if array_count != subcoll_count:
            logger.warning(
                f"CONSISTENCY MISMATCH: Batch {batch_id} has {array_count} "
                f"in array but {subcoll_count} in subcollection!"
            )
            # Send alert
            send_slack_alert(
                f"⚠️ Dual-write consistency issue detected in batch {batch_id}: "
                f"array={array_count}, subcollection={subcoll_count}"
            )
    except Exception as e:
        logger.error(f"Failed to validate consistency: {e}")
```

---

### Step 3: Update Read Logic (30 min)

Update methods that read completed players:

```python
def get_completed_players(self, batch_id: str) -> list:
    """
    Get completed players with feature flag support.
    """
    if self.enable_subcollection and self.use_subcollection_reads:
        # NEW: Read from subcollection
        logger.info(f"Reading completed players from subcollection for {batch_id}")
        return self.get_completed_players_subcollection(batch_id)
    else:
        # OLD: Read from array
        logger.info(f"Reading completed players from array for {batch_id}")
        batch_doc = self.collection.document(batch_id).get()
        if batch_doc.exists:
            return batch_doc.to_dict().get('completed_players', [])
        return []

def get_completion_progress(self, batch_id: str) -> dict:
    """
    Get batch completion progress.
    """
    if self.enable_subcollection and self.use_subcollection_reads:
        # NEW: Use counter
        completed_count = self.get_completion_count_subcollection(batch_id)
        batch_doc = self.collection.document(batch_id).get()
        total_players = batch_doc.to_dict().get('total_players', 0)
    else:
        # OLD: Count array length
        batch_doc = self.collection.document(batch_id).get()
        if batch_doc.exists:
            data = batch_doc.to_dict()
            completed_count = len(data.get('completed_players', []))
            total_players = data.get('total_players', 0)
        else:
            completed_count = 0
            total_players = 0

    completion_pct = (completed_count / total_players * 100) if total_players > 0 else 0

    return {
        'batch_id': batch_id,
        'completed': completed_count,
        'total': total_players,
        'completion_pct': completion_pct
    }
```

---

### Step 4: Add Monitoring & Metrics (15 min)

Add consistency monitoring:

```python
def monitor_dual_write_consistency(self):
    """
    Background job to monitor dual-write consistency.
    Run this periodically (e.g., every hour) during migration.
    """
    if not (self.enable_subcollection and self.dual_write_mode):
        return

    # Get all active batches
    batches = self.collection.where('status', '==', 'active').stream()

    mismatches = []

    for batch_doc in batches:
        batch_id = batch_doc.id
        data = batch_doc.to_dict()

        # Array count
        array_count = len(data.get('completed_players', []))

        # Subcollection count
        subcoll_count = self.get_completion_count_subcollection(batch_id)

        if array_count != subcoll_count:
            mismatches.append({
                'batch_id': batch_id,
                'array_count': array_count,
                'subcollection_count': subcoll_count,
                'diff': abs(array_count - subcoll_count)
            })

    if mismatches:
        logger.error(f"Found {len(mismatches)} consistency mismatches")
        send_slack_alert(
            f"⚠️ Dual-write consistency issues detected:\n" +
            "\n".join([f"- Batch {m['batch_id']}: array={m['array_count']}, "
                      f"subcollection={m['subcollection_count']}"
                      for m in mismatches[:5]])  # First 5
        )
    else:
        logger.info("✅ All batches consistent between array and subcollection")

    return mismatches
```

---

## 🧪 Testing

### Unit Tests

Create `test_batch_state_manager_subcollection.py`:

```python
import pytest
from unittest.mock import Mock, patch
from predictions.coordinator.batch_state_manager import BatchStateManager

@pytest.fixture
def mock_db():
    return Mock()

@pytest.fixture
def batch_manager(mock_db):
    return BatchStateManager(mock_db)

def test_record_completion_subcollection(batch_manager, mock_db):
    """Test subcollection write."""
    batch_id = "test_batch_123"
    player_lookup = "PLAYER_LeBron James"
    predictions_count = 5

    # Enable subcollection mode
    batch_manager.enable_subcollection = True
    batch_manager.dual_write_mode = False

    # Execute
    batch_manager.record_completion(batch_id, player_lookup, predictions_count)

    # Verify subcollection write was called
    mock_db.collection.assert_called_with('predictions_batches')
    # Add more specific assertions

def test_dual_write_mode(batch_manager, mock_db):
    """Test dual-write writes to both structures."""
    batch_id = "test_batch_456"
    player_lookup = "PLAYER_Stephen Curry"
    predictions_count = 3

    # Enable dual-write mode
    batch_manager.enable_subcollection = True
    batch_manager.dual_write_mode = True

    # Execute
    batch_manager.record_completion(batch_id, player_lookup, predictions_count)

    # Verify both writes happened
    # ArrayUnion call + subcollection call
    assert mock_db.collection.call_count >= 2

def test_consistency_validation(batch_manager):
    """Test consistency validation detects mismatches."""
    batch_id = "test_batch_789"

    # Mock array count = 10
    # Mock subcollection count = 11
    # Should detect mismatch

    with patch.object(batch_manager, 'get_completion_count_subcollection', return_value=11):
        # Execute validation
        batch_manager._validate_dual_write_consistency(batch_id)

        # Verify warning was logged
        # (check logs or mock logger)
```

---

### Integration Tests

```python
def test_end_to_end_migration():
    """
    Test complete migration flow:
    1. Dual-write enabled
    2. Record completions
    3. Validate consistency
    4. Switch reads
    5. Verify correctness
    """
    # Set up test batch
    batch_id = create_test_batch()

    # Phase 1: Dual-write enabled, reads from old
    os.environ['ENABLE_SUBCOLLECTION_COMPLETIONS'] = 'true'
    os.environ['DUAL_WRITE_MODE'] = 'true'
    os.environ['USE_SUBCOLLECTION_READS'] = 'false'

    manager = BatchStateManager(db)

    # Record completions
    for i in range(10):
        manager.record_completion(batch_id, f"PLAYER_{i}", 5)

    # Verify both structures have 10
    array_count = len(get_array_completions(batch_id))
    subcoll_count = manager.get_completion_count_subcollection(batch_id)
    assert array_count == 10
    assert subcoll_count == 10

    # Phase 2: Switch reads to subcollection
    os.environ['USE_SUBCOLLECTION_READS'] = 'true'
    manager = BatchStateManager(db)  # Reload config

    # Verify reads work
    players = manager.get_completed_players(batch_id)
    assert len(players) == 10

    # Phase 3: Stop dual-write
    os.environ['DUAL_WRITE_MODE'] = 'false'
    manager = BatchStateManager(db)

    # Record more completions
    for i in range(10, 15):
        manager.record_completion(batch_id, f"PLAYER_{i}", 5)

    # Array should still be 10, subcollection should be 15
    array_count = len(get_array_completions(batch_id))
    subcoll_count = manager.get_completion_count_subcollection(batch_id)
    assert array_count == 10  # No new writes
    assert subcoll_count == 15  # New writes here
```

---

## 🚀 Deployment

### Phase 1: Enable Dual-Write (Days 1-7)

```bash
# Deploy code changes
git push origin feature/subcollection-completions

# Deploy to staging
gcloud run services update prediction-coordinator \
  --source . \
  --region us-west2

# Enable dual-write in staging
gcloud run services update prediction-coordinator \
  --update-env-vars \
  ENABLE_SUBCOLLECTION_COMPLETIONS=true,\
  DUAL_WRITE_MODE=true,\
  USE_SUBCOLLECTION_READS=false

# Test in staging for 24 hours

# Deploy to production
gcloud run services update prediction-coordinator \
  --update-env-vars \
  ENABLE_SUBCOLLECTION_COMPLETIONS=true,\
  DUAL_WRITE_MODE=true,\
  USE_SUBCOLLECTION_READS=false \
  --region us-west2
```

### Phase 2: Monitor Consistency (Days 2-7)

```bash
# Set up daily consistency check (Cloud Scheduler)
gcloud scheduler jobs create http dual-write-consistency-check \
  --schedule="0 */6 * * *" \
  --uri="https://prediction-coordinator-XXX.run.app/admin/check-consistency" \
  --http-method=POST

# Monitor Slack alerts for any mismatches
# Review logs daily
```

### Phase 3: Switch Reads (Day 8)

```bash
# After 7 days of consistent dual-write, switch reads
gcloud run services update prediction-coordinator \
  --update-env-vars \
  USE_SUBCOLLECTION_READS=true \
  --region us-west2

# Monitor for 24 hours
# Check error rates, latency
```

### Phase 4: Stop Dual-Write (Day 15)

```bash
# After 7 more days of confidence, stop writing to array
gcloud run services update prediction-coordinator \
  --update-env-vars \
  DUAL_WRITE_MODE=false \
  --region us-west2

# Monitor for issues
```

### Phase 5: Cleanup (Day 30)

```bash
# After 30 days, remove old array field
# Manual Firestore cleanup script
python scripts/cleanup_completed_players_array.py

# Remove feature flag code (code cleanup)
# Deploy cleaned-up version
```

---

## ⚠️ Rollback

### Emergency Rollback (< 5 min)

```bash
# Revert to reading from array
gcloud run services update prediction-coordinator \
  --update-env-vars \
  USE_SUBCOLLECTION_READS=false \
  --region us-west2

# Continue dual-write for safety
# Investigate issue
```

### Full Rollback

```bash
# Disable subcollection completely
gcloud run services update prediction-coordinator \
  --update-env-vars \
  ENABLE_SUBCOLLECTION_COMPLETIONS=false \
  --region us-west2

# Revert code changes
git revert <commit-hash>
git push origin main

# Redeploy
```

---

## ✅ Success Criteria

- [ ] Dual-write working for 7 days
- [ ] Zero consistency mismatches
- [ ] Reads switched to subcollection successfully
- [ ] No performance degradation
- [ ] No data loss
- [ ] Supports 1000+ players
- [ ] Old array field can be deleted

---

## 📊 Monitoring

### Metrics to Track
- Dual-write consistency rate
- Subcollection write latency
- Subcollection read latency
- Array vs subcollection count divergence
- Error rates during migration

### Alerts
- Consistency mismatch detected
- Subcollection write failure
- Migration taking too long

---

**Estimated Duration:** 2-4 hours implementation + 30 days migration
**Risk Level:** Medium (data migration)
**Impact:** CRITICAL - Unlimited scalability

Good luck with the migration! 🚀
