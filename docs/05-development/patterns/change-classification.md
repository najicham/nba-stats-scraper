# Pattern #12: Change Classification

**Created:** 2025-11-20 8:14 AM PST
**Status:** ⚠️ Phase 3+ Reference - Requires Infrastructure (Week 8+ decision)
**Complexity:** High (2-4 weeks infrastructure + 1-2 days pattern)
**Value:** High IF minor-change noise is frequent (unknown until Week 8)

---

## ⚠️ CRITICAL PREREQUISITES

**This pattern requires field-level change detection infrastructure that we don't have yet:**

1. **Snapshot diffing system** - Compare OLD vs NEW records field-by-field
2. **Field metadata registry** - Define which fields are CRITICAL vs MINOR
3. **Entity-level processing** - Phase 3 infrastructure (not date-range mode)
4. **Change tracking tables** - Store what changed, not just if something changed

**Current state:**
- We have coarse-grained change detection: `COUNT + MAX(processed_at)` hash
- This tells us IF a table changed, not WHAT changed
- Pattern #12 needs to know WHICH FIELDS changed to classify importance

**Timeline reality:**
- Infrastructure work: 2-4 weeks (snapshot diffing, field registry, change tracking)
- Pattern implementation: 1-2 days (after infrastructure exists)
- Total: 3-5 weeks of work

**Don't implement unless:**
1. Week 1-8 monitoring shows frequent "false alarm" processing from minor changes
2. You're committed to Phase 3 (entity-level processing)
3. You've built the prerequisite infrastructure
4. The noise problem is costing > 3-5 weeks of your time to deal with

---

## Is This Needed?

**Run these queries during Week 1-8 monitoring to detect if we have a "noise" problem:**

### Query 1: Detect High-Frequency Unchanged Processing
```sql
-- Find processors that run frequently but produce identical outputs
-- (Symptom: processing triggered by minor changes only)

WITH processing_frequency AS (
  SELECT
    processor_name,
    DATE(processed_at) as process_date,
    COUNT(*) as run_count,
    COUNT(DISTINCT output_hash) as unique_outputs  -- Needs: content hashing
  FROM analytics_processing_metadata
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY processor_name, process_date
  HAVING run_count > 3  -- Multiple runs same day
)
SELECT
  processor_name,
  AVG(run_count) as avg_daily_runs,
  AVG(unique_outputs) as avg_unique_outputs,
  AVG(run_count - unique_outputs) as avg_redundant_runs
FROM processing_frequency
GROUP BY processor_name
ORDER BY avg_redundant_runs DESC;

-- Pattern needed if: avg_redundant_runs > 2 for any processor
```

### Query 2: Identify Timestamp-Only Changes
```sql
-- Detect if upstream tables frequently change only metadata fields
-- (Requires: comparing snapshots before/after)

-- NOTE: This query is conceptual - requires infrastructure we don't have yet
-- Shows what you'd need to detect minor-change noise

WITH snapshot_diffs AS (
  SELECT
    source_table,
    entity_id,
    game_date,
    -- Field categories (would come from field registry)
    COUNTIF(field_name IN ('updated_at', 'processed_at', 'version')) as minor_changes,
    COUNTIF(field_name NOT IN ('updated_at', 'processed_at', 'version')) as important_changes
  FROM change_detection_diffs  -- Doesn't exist yet!
  WHERE detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY source_table, entity_id, game_date
)
SELECT
  source_table,
  COUNT(*) as total_changes,
  COUNTIF(important_changes = 0 AND minor_changes > 0) as metadata_only_changes,
  SAFE_DIVIDE(
    COUNTIF(important_changes = 0 AND minor_changes > 0),
    COUNT(*)
  ) * 100 as pct_noise
FROM snapshot_diffs
GROUP BY source_table
ORDER BY pct_noise DESC;

-- Pattern needed if: pct_noise > 30% for key source tables
```

### Query 3: Measure Processing Time Waste
```sql
-- Calculate time spent processing changes that didn't matter
-- (Requires: knowing which runs were triggered by minor changes only)

SELECT
  processor_name,
  SUM(
    CASE
      WHEN change_priority = 'MINOR'  -- Needs: change classification
      THEN execution_time_seconds
      ELSE 0
    END
  ) as seconds_wasted_on_minor,
  SUM(execution_time_seconds) as total_seconds,
  SAFE_DIVIDE(
    SUM(CASE WHEN change_priority = 'MINOR' THEN execution_time_seconds ELSE 0 END),
    SUM(execution_time_seconds)
  ) * 100 as pct_time_wasted
FROM analytics_processing_metadata
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name
ORDER BY pct_time_wasted DESC;

-- Pattern needed if: pct_time_wasted > 20% for any processor
```

**Decision criteria:**
- Query 1 shows avg_redundant_runs > 2: Moderate signal
- Query 2 shows pct_noise > 30%: Strong signal
- Query 3 shows pct_time_wasted > 20%: Strong signal
- **ALL THREE combined:** Definitely implement
- **None of the above:** Don't implement, no problem to solve

---

## What Problem Does This Solve?

**Problem:** Not all changes are equal in importance.

**Example scenario:**
```
11:00 AM - Player injury status changes: ACTIVE → OUT
          ↓ This is CRITICAL, must process immediately

11:05 AM - Same player record updated: processed_at timestamp changed
          ↓ This is MINOR, don't waste time processing
```

**Without this pattern:**
- Both changes trigger processing (waste time on minor change)
- Analytics processors can't distinguish signal from noise
- False alarms reduce trust in the system

**With this pattern:**
- Classify changes by importance
- Skip processing for MINOR changes
- Prioritize CRITICAL changes
- Prevent "alert fatigue" from timestamp-only updates

---

## How It Works

### 1. Change Priority Levels

```python
from enum import IntEnum

class ChangePriority(IntEnum):
    """
    Change importance classification.
    Lower number = higher priority.
    """
    CRITICAL = 1    # Immediate action required
                    # Examples: injury_status change, player_status OUT → ACTIVE

    IMPORTANT = 2   # Should process soon
                    # Examples: stats changed (points, rebounds, assists)

    NORMAL = 3      # Regular processing
                    # Examples: minutes_played, field_goal_pct

    MINOR = 4       # Can skip processing
                    # Examples: updated_at, processed_at, version, etag
```

### 2. Field Priority Registry

**Define which fields matter:**

```python
# shared/change_detection/field_registry.py

FIELD_PRIORITIES = {
    # Player status fields - CRITICAL
    'injury_status': ChangePriority.CRITICAL,
    'player_status': ChangePriority.CRITICAL,
    'active': ChangePriority.CRITICAL,

    # Game stats - IMPORTANT
    'points': ChangePriority.IMPORTANT,
    'rebounds': ChangePriority.IMPORTANT,
    'assists': ChangePriority.IMPORTANT,
    'minutes': ChangePriority.IMPORTANT,

    # Derived stats - NORMAL
    'field_goal_percentage': ChangePriority.NORMAL,
    'plus_minus': ChangePriority.NORMAL,

    # Metadata - MINOR (don't process on these alone)
    'updated_at': ChangePriority.MINOR,
    'processed_at': ChangePriority.MINOR,
    'version': ChangePriority.MINOR,
    'etag': ChangePriority.MINOR,
    'last_modified': ChangePriority.MINOR,
}

def get_field_priority(field_name: str) -> ChangePriority:
    """
    Get priority for a field. Default to NORMAL if not in registry.
    """
    return FIELD_PRIORITIES.get(field_name, ChangePriority.NORMAL)
```

### 3. Snapshot Diffing (Infrastructure Needed)

**Compare OLD vs NEW snapshots:**

```python
# shared/change_detection/snapshot_diff.py

from typing import Dict, List, Any
from dataclasses import dataclass

@dataclass
class FieldChange:
    """Single field change."""
    field_name: str
    old_value: Any
    new_value: Any
    priority: ChangePriority

@dataclass
class RecordDiff:
    """All changes in a record."""
    entity_id: str
    changes: List[FieldChange]
    highest_priority: ChangePriority  # Most important change

    def is_minor_only(self) -> bool:
        """True if only MINOR fields changed."""
        return self.highest_priority == ChangePriority.MINOR

    def has_critical_changes(self) -> bool:
        """True if any CRITICAL fields changed."""
        return self.highest_priority == ChangePriority.CRITICAL

def diff_records(old_record: Dict, new_record: Dict) -> RecordDiff:
    """
    Compare two records and classify all changes.

    PREREQUISITE: Both records must have same schema/structure.
    """
    changes = []

    # Compare all fields
    all_fields = set(old_record.keys()) | set(new_record.keys())

    for field_name in all_fields:
        old_value = old_record.get(field_name)
        new_value = new_record.get(field_name)

        # Skip if unchanged
        if old_value == new_value:
            continue

        # Record the change with priority
        field_priority = get_field_priority(field_name)
        changes.append(FieldChange(
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            priority=field_priority
        ))

    # Determine highest priority change
    if not changes:
        highest_priority = ChangePriority.NORMAL
    else:
        highest_priority = min(change.priority for change in changes)

    return RecordDiff(
        entity_id=new_record.get('id', 'unknown'),
        changes=changes,
        highest_priority=highest_priority
    )
```

### 4. Change Classification Mixin

**Use in analytics processors:**

```python
# data_processors/analytics/mixins/change_classification.py

from typing import Dict, List
from shared.change_detection.snapshot_diff import diff_records, RecordDiff, ChangePriority

class ChangeClassificationMixin:
    """
    Filter processing based on change importance.

    PREREQUISITE: Requires snapshot diffing infrastructure.
    Only works in Phase 3 (entity-level processing).
    """

    # Override in subclass if needed
    MIN_PRIORITY_TO_PROCESS = ChangePriority.IMPORTANT

    def classify_changes(
        self,
        old_snapshot: List[Dict],
        new_snapshot: List[Dict]
    ) -> Dict[str, RecordDiff]:
        """
        Compare snapshots and classify all changes.

        Returns:
            Dict mapping entity_id -> RecordDiff
        """
        # Index by entity_id
        old_by_id = {r['id']: r for r in old_snapshot}
        new_by_id = {r['id']: r for r in new_snapshot}

        diffs = {}

        # Find changed and new records
        for entity_id, new_record in new_by_id.items():
            old_record = old_by_id.get(entity_id)

            if old_record is None:
                # New record - always process
                # (Set to CRITICAL to ensure processing)
                diffs[entity_id] = RecordDiff(
                    entity_id=entity_id,
                    changes=[],
                    highest_priority=ChangePriority.CRITICAL
                )
            else:
                # Changed record - classify changes
                diff = diff_records(old_record, new_record)
                if diff.changes:  # Only include if actually changed
                    diffs[entity_id] = diff

        return diffs

    def filter_by_priority(self, diffs: Dict[str, RecordDiff]) -> List[str]:
        """
        Get entity IDs that should be processed based on change priority.

        Returns:
            List of entity_ids to process
        """
        return [
            entity_id
            for entity_id, diff in diffs.items()
            if diff.highest_priority <= self.MIN_PRIORITY_TO_PROCESS
        ]

    def should_process_changes(self, diffs: Dict[str, RecordDiff]) -> bool:
        """
        Determine if ANY changes are important enough to process.

        Returns False if only MINOR changes occurred.
        """
        if not diffs:
            return False  # No changes at all

        # Check if any diffs meet priority threshold
        important_diffs = self.filter_by_priority(diffs)
        return len(important_diffs) > 0
```

### 5. Usage in Analytics Processor

```python
# data_processors/analytics/player_game_stats_processor.py

from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from data_processors.analytics.mixins.change_classification import ChangeClassificationMixin
from shared.change_detection.snapshot_diff import ChangePriority

class PlayerGameStatsProcessor(AnalyticsProcessorBase, ChangeClassificationMixin):
    """
    Player game stats with change classification.

    Only processes when IMPORTANT+ changes occur.
    Skips processing for metadata-only updates.
    """

    # Don't process for NORMAL or MINOR changes
    MIN_PRIORITY_TO_PROCESS = ChangePriority.IMPORTANT

    def run(self, opts: Dict) -> bool:
        game_date = opts.get('game_date', self.default_game_date)

        # Get old and new snapshots (from Phase 3 infrastructure)
        old_snapshot = self._get_previous_snapshot(game_date)
        new_snapshot = self._get_current_snapshot(game_date)

        # Classify all changes
        diffs = self.classify_changes(old_snapshot, new_snapshot)

        # Early exit if only minor changes
        if not self.should_process_changes(diffs):
            self.logger.info(
                f"Skipping {game_date}: only MINOR changes detected "
                f"(metadata timestamps, no stat changes)"
            )
            return True  # Success, but no processing needed

        # Get entities to process (IMPORTANT+ changes only)
        entity_ids = self.filter_by_priority(diffs)

        self.logger.info(
            f"Processing {len(entity_ids)} entities with IMPORTANT+ changes "
            f"(skipped {len(diffs) - len(entity_ids)} NORMAL/MINOR changes)"
        )

        # Process filtered entities
        results = []
        for entity_id in entity_ids:
            diff = diffs[entity_id]

            # Log what changed for debugging
            change_summary = ", ".join([
                f"{c.field_name}: {c.old_value} → {c.new_value}"
                for c in diff.changes[:3]  # First 3 changes
            ])
            self.logger.info(
                f"Processing {entity_id} (priority={diff.highest_priority.name}): "
                f"{change_summary}"
            )

            # Do actual processing
            result = self._process_entity(entity_id, new_snapshot)
            results.append(result)

        # Write results
        self._write_to_bigquery(results, game_date)
        return True
```

---

## Metrics to Track

**If you implement this pattern, measure:**

```python
# In analytics_base.py processing metadata

processing_metadata = {
    # Change classification metrics
    'total_changes_detected': len(diffs),
    'critical_changes': sum(1 for d in diffs.values() if d.highest_priority == ChangePriority.CRITICAL),
    'important_changes': sum(1 for d in diffs.values() if d.highest_priority == ChangePriority.IMPORTANT),
    'normal_changes': sum(1 for d in diffs.values() if d.highest_priority == ChangePriority.NORMAL),
    'minor_changes': sum(1 for d in diffs.values() if d.highest_priority == ChangePriority.MINOR),
    'entities_skipped': len(diffs) - len(entity_ids),
    'entities_processed': len(entity_ids),
}
```

**Dashboard queries:**

```sql
-- Track change classification effectiveness
SELECT
  processor_name,
  DATE(processed_at) as process_date,
  AVG(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.entities_skipped') AS INT64)) as avg_skipped,
  AVG(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.entities_processed') AS INT64)) as avg_processed,
  SAFE_DIVIDE(
    AVG(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.entities_skipped') AS INT64)),
    AVG(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.total_changes_detected') AS INT64))
  ) * 100 as pct_skipped
FROM analytics_processing_metadata
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name, process_date
ORDER BY process_date DESC, processor_name;

-- Expect: 20-40% skipped if pattern is effective
```

---

## Implementation Roadmap

**This is 3-5 weeks of work. Don't start unless you're committed.**

### Phase A: Infrastructure (2-4 weeks)

**Week 1-2: Snapshot Storage**
```
1. Design snapshot table schema
2. Modify analytics processors to save snapshots
3. Implement snapshot retrieval functions
4. Add snapshot cleanup (retention policy)
```

**Week 2-3: Diffing Engine**
```
1. Create field registry (FIELD_PRIORITIES dict)
2. Implement diff_records() function
3. Add RecordDiff, FieldChange data classes
4. Write tests for edge cases (new records, deleted records, null values)
```

**Week 3-4: Change Detection Integration**
```
1. Add snapshot comparison to analytics_base.py
2. Store change classifications in processing metadata
3. Add Grafana dashboard for change patterns
4. Monitor for 1 week to validate detection works
```

### Phase B: Pattern Implementation (1-2 days)

**Day 1: Mixin Creation**
```
1. Create ChangeClassificationMixin
2. Add classify_changes() method
3. Add filter_by_priority() method
4. Add should_process_changes() method
```

**Day 2: Rollout**
```
1. Add mixin to 1-2 high-frequency processors
2. Monitor skip rates (expect 20-40%)
3. Verify we're not missing important changes
4. Rollout to remaining processors
```

---

## Alternative: Simpler Approaches

**Before building this full infrastructure, consider simpler solutions:**

### Option 1: Source-Level Filtering (Pattern #1 - Already Documented)
```python
# If problem is "wrong sources trigger processing"
# Use Smart Skip (already documented, can implement Week 1)
class SmartSkipMixin:
    RELEVANT_SOURCES = {
        'odds_api_spreads': False,  # Not relevant to player stats
    }
```

### Option 2: Time-Based Throttling
```python
# If problem is "too frequent updates from same source"
# Add simple cooldown period
class ThrottlingMixin:
    MIN_SECONDS_BETWEEN_RUNS = 300  # 5 minutes

    def should_process_source(self, source_table: str) -> bool:
        last_run = self._get_last_run_time(source_table)
        if (datetime.now() - last_run).seconds < self.MIN_SECONDS_BETWEEN_RUNS:
            return False  # Too soon, skip
        return True
```

### Option 3: Manual Source Prioritization
```python
# If problem is "low-value sources waste time"
# Manually configure which sources matter
class SourcePriorityMixin:
    HIGH_PRIORITY_SOURCES = [
        'nbac_boxscore',  # Game stats - always process
        'nbac_injury_report',  # Critical updates
    ]

    def should_process_source(self, source_table: str) -> bool:
        if source_table not in self.HIGH_PRIORITY_SOURCES:
            # Low priority - only process during off-peak
            if not self._is_off_peak_hours():
                return False
        return True
```

**Try these first before building full change classification infrastructure.**

---

## When NOT to Use This Pattern

❌ **Don't use if:**
- You're in Phase 1 (date-range processing) - pattern requires entity-level
- Week 1-8 monitoring shows low noise (< 20% redundant runs)
- Simple solutions (Smart Skip, throttling) solve the problem
- You don't have 3-5 weeks for infrastructure work
- Processing is fast anyway (< 30 seconds) - not worth optimizing

✅ **Use if:**
- Week 1-8 shows > 30% of processing is noise (minor changes only)
- You're committed to Phase 3 (entity-level processing)
- You have 3-5 weeks for infrastructure + pattern implementation
- High-frequency processors are wasting significant time
- Simple solutions didn't solve the problem

---

## Summary

**Pattern #12 helps distinguish signal from noise by classifying changes by importance.**

**Key points:**
- ⚠️ Requires 2-4 weeks of infrastructure (snapshot diffing, field registry, change tracking)
- Only needed IF Week 1-8 monitoring shows > 30% noise problem
- Only works in Phase 3 (entity-level processing mode)
- Try simpler solutions first (Smart Skip, throttling, source prioritization)
- Don't implement speculatively - wait for data to show you need it

**Timeline:**
- Week 1-8: Monitor for noise problem (run "Is This Needed?" queries)
- Week 8: Decide if pattern is worth 3-5 weeks of work
- Week 9-12: Build infrastructure (if committed)
- Week 13: Implement pattern (1-2 days after infrastructure exists)
- Week 14+: Monitor effectiveness (expect 20-40% reduction in unnecessary processing)

**This is a "nice to have" optimization, not a "must have" foundation pattern.**
