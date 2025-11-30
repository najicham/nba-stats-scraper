# Phase 2 Smart Idempotency - Discussion Summary

**File:** `docs/08-projects/completed/smart-idempotency/01-phase2-idempotency-discussion-summary.md`
**Created:** 2025-11-21 09:45 AM PST
**Last Updated:** 2025-11-29
**Purpose:** Summary of design decisions from Phase 2 smart idempotency planning session
**Status:** ✅ COMPLETE - Deployed

> **📚 Main Documentation:** [`docs/05-development/guides/processor-patterns/01-smart-idempotency.md`](../../../05-development/guides/processor-patterns/01-smart-idempotency.md)

---

## Discussion Points & Resolutions

### 1. Injury Report Strategy: APPEND_ALWAYS vs MERGE_UPDATE ✅

**Question:** Should injury reports use MERGE_UPDATE instead of APPEND_ALWAYS?

**Decision: Keep APPEND_ALWAYS with hash checking**

**Rationale:**
- APPEND_ALWAYS preserves historical timeline of injury status changes
- Downstream uses `nbac_injury_report_latest` view (ROW_NUMBER gets latest)
- With hash checking, we only write when status **actually changes**
- Best of both worlds: historical tracking + efficient downstream queries

**Example behavior with hash checking:**
```
9am: "Out - Ankle" → Write (new data)
12pm: "Out - Ankle" → Skip (hash matches, no write)
3pm: "Out - Ankle" → Skip (hash matches, no write)
6pm: "Questionable - Ankle" → Write (hash changed!)
```

**Result:** 4 scrapes → 2 writes (50% reduction)

---

### 2. Phase 3/4/5 Source Hash Tracking ✅ CRITICAL

**Question:** Should Phase 3/4/5 track which source hash they last processed?

**Decision: YES - Add `source_data_hash` column to all Phase 3/4/5 output tables**

**Why this matters:**
- Phase 2 writes `data_hash` to raw tables
- Phase 3/4/5 need to know: "Did my input data change?"
- Without this: Phase 3 reprocesses every time Phase 2 `processed_at` updates
- With this: Phase 3 only processes when Phase 2 `data_hash` actually changes

**Implementation Approach: Option A (Recommended)**

Add single `source_data_hash` column to each output table:

```sql
-- Phase 3 tables
ALTER TABLE `nba_analytics.player_game_summary` ADD COLUMN source_data_hash STRING;
ALTER TABLE `nba_analytics.team_defense_game_summary` ADD COLUMN source_data_hash STRING;
ALTER TABLE `nba_analytics.team_offense_game_summary` ADD COLUMN source_data_hash STRING;
ALTER TABLE `nba_analytics.upcoming_player_game_context` ADD COLUMN source_data_hash STRING;
ALTER TABLE `nba_analytics.upcoming_team_game_context` ADD COLUMN source_data_hash STRING;

-- Phase 4 tables
ALTER TABLE `nba_precompute.player_composite_factors` ADD COLUMN source_data_hash STRING;
ALTER TABLE `nba_precompute.player_shot_zone_analysis` ADD COLUMN source_data_hash STRING;
ALTER TABLE `nba_precompute.team_defense_zone_analysis` ADD COLUMN source_data_hash STRING;
ALTER TABLE `nba_precompute.player_daily_cache` ADD COLUMN source_data_hash STRING;
ALTER TABLE `nba_precompute.ml_feature_store` ADD COLUMN source_data_hash STRING;

-- Phase 5 table
ALTER TABLE `nba_predictions.prediction_worker_runs` ADD COLUMN source_data_hash STRING;
```

**Logic:**
1. Phase 3 reads dependencies from Phase 2
2. Concatenates all Phase 2 `data_hash` values → computes composite hash
3. Checks: "Does my output `source_data_hash` match current input hash?"
   - If YES: Skip processing (input unchanged)
   - If NO: Process and write with new `source_data_hash`

**Implementation location:**
- Add to `analytics_base.py`:
  - `compute_source_data_hash(dependencies_data)`
  - `check_if_source_data_changed(output_key, new_hash)`

**Benefits:**
- Complete cascade prevention across all phases
- Traceable: see exactly what source data was used for each output
- Simple: one column per table (vs. one column per dependency)

**Design document:** Created `/tmp/phase3_hash_tracking.md` with full implementation details

---

### 3. Where Hash Fields Are Defined ✅

**Question:** Where are hash fields set?

**Answer: In each Phase 2 processor as a class attribute**

**Example:**
```python
# data_processors/raw/nbacom/nbac_injury_report_processor.py

class InjuryReportProcessor(SmartIdempotencyMixin, ProcessorBase):
    """Processes NBA.com injury reports"""

    # Define which fields to hash (class attribute)
    HASH_FIELDS = [
        'player_lookup',
        'team',
        'game_date',
        'game_id',
        'injury_status',
        'reason',
        'reason_category'
    ]

    def load_to_bigquery(self, rows):
        """Write to BigQuery with hash checking"""
        rows_to_write = []

        for row in rows:
            # Mixin computes hash and checks if changed
            if self.should_write_row(row, self.table_name, 'player_lookup'):
                rows_to_write.append(row)  # row now has 'data_hash' field

        # Write only changed rows
        if rows_to_write:
            self.bq_client.insert_rows_json(self.table_name, rows_to_write)
```

**Mixin location:** `data_processors/raw/processor_base.py` (or new file)

**Action item:** Add clarification section to strategy document

---

### 4. Inactive Processors/Scrapers ⏳ PENDING

**Question:** Some processors/scrapers no longer active (e.g., scoreboard_v2). Should we skip documenting them?

**Status:** PENDING - Need scraper reference document

**Action:** User to provide scraper reference doc with active/inactive status

**Impact:** Will remove inactive processors from hash strategy document to avoid wasted effort

---

### 5. Documentation Timestamps ✅ FIXED

**Question:** All docs should have "Created" and "Last Updated" with date, time, and timezone

**Status:** FIXED

**Changes made:**
1. ✅ Updated `docs/reference/phase2-processor-hash-strategy.md`
   - Added: `**Created:** 2025-11-21 08:15 AM PST`
   - Updated: `**Last Updated:** 2025-11-21 09:30 AM PST`

2. ✅ Updated `docs/testing/README.md`
   - Added timestamps with time

3. ✅ Updated `.claude/claude_project_instructions.md`
   - Made timestamp requirements more explicit (MANDATORY)
   - Changed format from `YYYY-MM-DD` to `YYYY-MM-DD HH:MM AM/PM PST`
   - Added emphasis: **"This applies to ALL documentation files - no exceptions"**

**New standard format:**
```markdown
**Created:** 2025-11-21 09:30 AM PST
**Last Updated:** 2025-11-21 09:45 AM PST
```

---

## Documents Created/Updated

### Created:
1. `docs/reference/phase2-processor-hash-strategy.md` - 38-page comprehensive strategy
2. `/tmp/phase3_hash_tracking.md` - Phase 3/4/5 source hash tracking design

### Updated:
1. `.claude/claude_project_instructions.md` - Timestamp requirements emphasized
2. `docs/testing/README.md` - Timestamps added
3. `docs/reference/phase2-processor-hash-strategy.md` - Timestamps fixed

---

## Key Decisions Summary

| Topic | Decision | Impact |
|-------|----------|---------|
| **Injury Reports** | Keep APPEND_ALWAYS + hash check | Historical timeline preserved |
| **Phase 3/4/5 Tracking** | Add `source_data_hash` column | Complete cascade prevention |
| **Hash Field Location** | Class attribute `HASH_FIELDS` | Simple, declarative |
| **Inactive Processors** | Pending scraper reference | Avoid wasted documentation |
| **Doc Timestamps** | Mandatory time + timezone | Consistency enforced |

---

## Next Steps

### Immediate (Need Input):
1. [ ] **Get scraper reference doc** - Identify active/inactive processors
2. [ ] **Review Phase 3/4/5 hash tracking design** - Approve Option A approach

### Implementation (After Above):
1. [ ] Document hash field implementation details
2. [ ] Design SmartIdempotencyMixin
3. [ ] Create schema migrations (Phase 2 + Phase 3/4/5)
4. [ ] Implement mixin in processor_base.py
5. [ ] Apply to 5 critical Phase 2 processors
6. [ ] Test locally
7. [ ] Deploy Phase 1

---

## Open Questions

1. **Hash computation performance** - Will hashing thousands of rows be fast enough?
   - Need to test with realistic data volumes

2. **Granularity for Phase 3/4/5** - Per-player? Per-game? Per-date?
   - Player game summary: per (player, game_date)
   - Precompute: TBD

3. **Storage cost** - 16 chars × millions of rows = ?MB
   - Likely acceptable for cascade prevention benefits

4. **Gamebook stat corrections** - Do NBA.com stats ever get corrected post-game?
   - Research needed: if yes, hash checking could prevent corrections

---

## Reference Documents

- **Primary Strategy:** `docs/reference/phase2-processor-hash-strategy.md`
- **Phase 3/4/5 Design:** `/tmp/phase3_hash_tracking.md` (to be moved to docs/)
- **Pattern Catalog:** `docs/patterns/12-smart-idempotency-reference.md`
- **Project Instructions:** `.claude/claude_project_instructions.md`

---

**Status:** Planning complete, awaiting scraper reference doc and design approval before implementation.
