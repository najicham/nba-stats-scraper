# Scraper Update Plan - Dual Publishing Migration

**Date:** 2025-11-16
**Purpose:** Update scrapers to publish to both old and new Phase 1 topics
**Impact:** ZERO changes needed to individual scrapers!

---

## **What Needs to Change**

### **File to Update:** `scrapers/utils/pubsub_utils.py`

**Current behavior:**
- Publishes to: `nba-scraper-complete` (hardcoded on line 52)

**New behavior (dual publishing):**
- Publishes to: `nba-scraper-complete` (OLD - for backward compatibility)
- Publishes to: `nba-phase1-scrapers-complete` (NEW - from TOPICS config)

---

## **Detailed Changes**

### **Change 1: Add import for centralized config** (Line 39)

**Add after line 39:**
```python
from google.cloud import pubsub_v1

# NEW: Import centralized topic config
from shared.config.pubsub_topics import TOPICS
```

---

### **Change 2: Update __init__ to support dual publishing** (Lines 52-66)

**Replace lines 52-66:**

```python
def __init__(self, project_id: str = None, topic_name: str = 'nba-scraper-complete'):
    """
    Initialize publisher.

    Args:
        project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)
        topic_name: Pub/Sub topic name (default: 'nba-scraper-complete')
    """
    self.project_id = project_id or os.getenv('GCP_PROJECT_ID', 'nba-props-platform')
    self.topic_name = topic_name

    try:
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)
        logger.debug(f"Initialized Pub/Sub publisher: {self.topic_path}")
    except Exception as e:
        logger.error(f"Failed to initialize Pub/Sub publisher: {e}")
        raise
```

**With:**

```python
def __init__(
    self,
    project_id: str = None,
    dual_publish: bool = True  # NEW: Enable dual publishing during migration
):
    """
    Initialize publisher.

    Args:
        project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)
        dual_publish: If True, publishes to both old and new topics (migration mode)
    """
    self.project_id = project_id or os.getenv('GCP_PROJECT_ID', 'nba-props-platform')
    self.dual_publish = dual_publish

    # OLD topic (will deprecate after migration)
    self.old_topic_name = 'nba-scraper-complete'

    # NEW topic (from centralized config)
    self.new_topic_name = TOPICS.PHASE1_SCRAPERS_COMPLETE

    try:
        self.publisher = pubsub_v1.PublisherClient()

        # Create topic paths for both
        self.old_topic_path = self.publisher.topic_path(self.project_id, self.old_topic_name)
        self.new_topic_path = self.publisher.topic_path(self.project_id, self.new_topic_name)

        if self.dual_publish:
            logger.info(
                f"Dual publishing mode: {self.old_topic_name} + {self.new_topic_name}"
            )
        else:
            logger.info(f"Publishing to: {self.new_topic_name}")

    except Exception as e:
        logger.error(f"Failed to initialize Pub/Sub publisher: {e}")
        raise
```

---

### **Change 3: Update publish_completion_event to dual publish** (Lines 148-183)

**Replace the try block (lines 148-183):**

```python
try:
    # Publish with message attributes for subscription filtering
    future = self.publisher.publish(
        self.topic_path,
        data=json.dumps(message_data).encode('utf-8'),
        # Message attributes for Pub/Sub filtering
        scraper_name=scraper_name,
        status=status,
        execution_id=execution_id,
        workflow=workflow or 'MANUAL'
    )

    # Wait for publish to complete (blocking, max 10 seconds)
    message_id = future.result(timeout=10)

    logger.info(
        f"✅ Published Pub/Sub event: {scraper_name} "
        f"(status={status}, records={record_count}, message_id={message_id})"
    )

    return message_id
```

**With:**

```python
try:
    message_ids = []

    # Publish to NEW topic (always)
    future_new = self.publisher.publish(
        self.new_topic_path,
        data=json.dumps(message_data).encode('utf-8'),
        scraper_name=scraper_name,
        status=status,
        execution_id=execution_id,
        workflow=workflow or 'MANUAL'
    )

    message_id_new = future_new.result(timeout=10)
    message_ids.append(message_id_new)

    logger.info(
        f"✅ Published to {self.new_topic_name}: {scraper_name} "
        f"(status={status}, records={record_count}, message_id={message_id_new})"
    )

    # DUAL PUBLISH: Also publish to OLD topic during migration
    if self.dual_publish:
        try:
            future_old = self.publisher.publish(
                self.old_topic_path,
                data=json.dumps(message_data).encode('utf-8'),
                scraper_name=scraper_name,
                status=status,
                execution_id=execution_id,
                workflow=workflow or 'MANUAL'
            )

            message_id_old = future_old.result(timeout=10)
            message_ids.append(message_id_old)

            logger.debug(
                f"✅ Also published to {self.old_topic_name} (backward compatibility)"
            )
        except Exception as dual_error:
            # Don't fail if old topic publish fails (migration period)
            logger.warning(
                f"Failed to publish to old topic {self.old_topic_name}: {dual_error}"
            )

    return message_id_new  # Return new topic's message ID
```

---

## **Migration Timeline**

### **Day 1: Deploy Dual Publishing** (Today)
1. Update `scrapers/utils/pubsub_utils.py` with changes above
2. Deploy updated scrapers
3. **Result:** Scrapers publish to BOTH topics
   - Phase 2 receives from both subscriptions (no data loss)
   - New infrastructure gets tested in production

### **Days 2-3: Verification Period** (24 hours minimum)
1. Monitor both topics for message flow:
   ```bash
   # Check old topic
   gcloud pubsub subscriptions pull nba-processors-sub --limit=5 --auto-ack

   # Check new topic
   gcloud pubsub subscriptions pull nba-processors-sub-v2 --limit=5 --auto-ack
   ```

2. Verify Phase 2 processing from both subscriptions

3. Confirm no errors in scraper logs

### **Day 4: Finalize Migration**
1. Update `pubsub_utils.py` to disable dual publishing:
   ```python
   def __init__(self, project_id=None, dual_publish=False):  # Set to False
   ```

2. Deploy (scrapers now publish to new topic ONLY)

3. Run migration finalize:
   ```bash
   ./bin/infrastructure/migrate_phase1_topic.sh finalize
   ```

4. Delete old topics after 7-day safety period

---

## **Testing Before Deploy**

**Test the updated publisher:**

```bash
# Test dual publishing
python -c "
from scrapers.utils.pubsub_utils import ScraperPubSubPublisher

publisher = ScraperPubSubPublisher()  # dual_publish=True by default
message_id = publisher.publish_completion_event(
    scraper_name='test_scraper',
    execution_id='test-dual-publish',
    status='success',
    record_count=1
)
print(f'Test published: {message_id}')
"
```

**Verify both topics received the message:**

```bash
# Check new topic
gcloud pubsub subscriptions pull nba-processors-sub-v2 --limit=1

# Check old topic
gcloud pubsub subscriptions pull nba-processors-sub --limit=1
```

---

## **Rollback Plan (If Needed)**

If issues occur:

1. **Revert `pubsub_utils.py`** to original version
2. **Redeploy scrapers** (back to single publishing)
3. **Investigate** issue
4. **Try again** when ready

---

## **Files Changed**

✅ **Files to Update:** 1 file
- `scrapers/utils/pubsub_utils.py`

❌ **Files NOT to Update:** 26+ individual scrapers
- All inherit from ScraperBase
- No changes needed!

---

## **Deployment Command**

After updating `pubsub_utils.py`:

```bash
# Deploy scrapers (assuming your deployment script)
cd scrapers
gcloud run deploy nba-scrapers \
  --source . \
  --region us-west2 \
  --project nba-props-platform
```

---

**Status:** Ready to implement
**Risk:** LOW (dual publishing is safe, backward compatible)
**Time:** 30 minutes to update + 10 minutes to deploy
