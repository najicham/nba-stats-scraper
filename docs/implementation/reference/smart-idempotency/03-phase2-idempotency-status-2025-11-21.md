# Phase 2 Smart Idempotency - Status Update

**File:** `docs/implementation/phase2-idempotency-status-2025-11-21.md`
**Created:** 2025-11-21 10:30 AM PST
**Last Updated:** 2025-11-21 10:30 AM PST
**Purpose:** Status update after addressing user feedback on schema updates and dependencies
**Status:** Awaiting User Approval

---

## Summary of Changes

### ✅ Completed

1. **Scraper → Processor Mapping** (`docs/reference/scraper-to-processor-mapping.md`)
   - Mapped all 30+ scrapers to Phase 2 processors
   - Identified 5 critical, 7 medium, 8 low priority processors
   - Flagged 1 potentially inactive processor (scoreboard_v2)

2. **Comprehensive Schema Update Plan** (`docs/implementation/schema-update-plan-smart-idempotency.md`)
   - **Addresses your requirement:** Updates both CREATE TABLE SQL and migrations
   - Phase 2: Add `data_hash` to 5 critical tables
   - Phase 3/4/5: Add `source_data_hash` + per-source tracking
   - Complete file structure and implementation workflow
   - Rollback plan included

3. **Dependency Tracking Integration Design** (`/tmp/dependency_tracking_integration.md`)
   - Analyzed how wiki guide complements smart idempotency
   - Unified field strategy: 4 fields per source + 1 composite
   - Ready to create integrated documentation

4. **Timestamps Fixed**
   - Updated all documentation with `YYYY-MM-DD HH:MM AM/PM PST` format
   - Updated project instructions with mandatory timestamp requirements
   - Applied to all existing docs

---

## Documents Created/Updated

### Created:
1. `docs/reference/scraper-to-processor-mapping.md` - Scraper to processor mapping with priorities
2. `docs/implementation/schema-update-plan-smart-idempotency.md` - Complete schema update plan
3. `docs/implementation/phase2-idempotency-discussion-summary.md` - Discussion decisions
4. `/tmp/dependency_tracking_integration.md` - Integration design (ready to formalize)

### Updated:
1. `.claude/claude_project_instructions.md` - Timestamp requirements emphasized
2. `docs/reference/phase2-processor-hash-strategy.md` - Timestamps fixed
3. `docs/testing/README.md` - Timestamps added

---

## Key Decisions Requiring Your Approval

### 1. ✅ Dependency Tracking Integration - APPROVED

**Your response:** "I approve of your tracking approach"

**Implementation:**
- Phase 2 tables: Add `data_hash STRING`
- Phase 3/4/5 tables: Add per-source hashing + existing dependency tracking fields
- Create new integrated doc: `docs/implementation/dependency-tracking-with-smart-idempotency.md`

---

### 2. ⏳ Inactive Processors - NEED CONFIRMATION

**Question:** Is `nbac_scoreboard_v2_processor.py` actually inactive?

From your earlier comment: "Some processors/scrapers are no longer active like scoreboard v2"

**Action Required:**
- [ ] Confirm scoreboard_v2 is inactive → Remove from implementation plan
- [ ] Identify any other inactive processors

---

### 3. ⏳ Schema Update Approach - NEED APPROVAL

**Your requirement:** "Please make sure we are updating the original create table sql for every table we update and not just adding migrations"

**My plan (from `schema-update-plan-smart-idempotency.md`):**

**Step 1:** Update original CREATE TABLE SQL files in `schemas/bigquery/`
- Example: `schemas/bigquery/raw/nbac_injury_report_tables.sql`
- Add `data_hash STRING` in appropriate location
- Update OPTIONS description
- Add comments explaining what's hashed

**Step 2:** Create migration SQL in `monitoring/schemas/migrations/`
- Example: `add_data_hash_to_nbac_injury_report.sql`
- Use `ADD COLUMN IF NOT EXISTS` for safety
- Add header with date, pattern reference

**Step 3:** Run migrations
**Step 4:** Verify schema changes
**Step 5:** Update all documentation

**Does this approach meet your requirements?**

---

## Field Strategy Summary

### Phase 2 Tables (Raw)
**Add 1 field:**
```sql
data_hash STRING  -- Hash of meaningful fields only (exclude metadata/timestamps)
```

**Example (Injury Report):**
- Hash: player_lookup, team, game_date, game_id, injury_status, reason, reason_category
- Exclude: report_date, scrape_time, processed_at, confidence scores

---

### Phase 3/4/5 Tables (Analytics/Precompute/Predictions)
**Add 4 fields per dependency + 1 composite:**

```sql
-- Per dependency (repeat for each source)
source_{prefix}_data_hash STRING,           -- NEW: Hash from Phase 2
source_{prefix}_last_updated TIMESTAMP,     -- Existing: Dependency tracking
source_{prefix}_rows_found INT64,           -- Existing: Dependency tracking
source_{prefix}_completeness_pct NUMERIC(5,2),  -- Existing: Dependency tracking

-- Composite (once per table)
source_data_hash STRING  -- NEW: Combined hash of all dependencies
```

**Example (Player Game Summary with 6 dependencies):**
- 6 sources × 4 fields = 24 source tracking fields
- 1 composite hash = 1 field
- Total: 25 tracking fields

**Benefits:**
1. **Skip unnecessary processing** - Check composite hash before running
2. **Track data quality** - Monitor completeness_pct for each source
3. **Debug failures** - See which source had issues
4. **Audit trail** - Know exactly what data was used

---

## Implementation Phases

### Phase 1: Critical Priority (Week 1)
**5 tables - Highest cascade prevention impact**

1. nba_raw.nbac_injury_report
2. nba_raw.bdl_injuries
3. nba_raw.odds_api_player_points_props
4. nba_raw.bettingpros_player_points_props
5. nba_raw.odds_api_game_lines

**Then add source tracking to Phase 3/4/5 tables (15 tables)**

### Phase 2: Medium Priority (Week 2)
**7 tables - Post-game updates**

Boxscore and gamebook processors

### Phase 3: Low Priority (Week 3+)
**8 tables - Infrequent updates**

Schedule, roster, and reference tables

---

## Open Questions for You

### 1. Inactive Processors
**Question:** Besides scoreboard_v2, are there any other inactive processors?

**Action:** Please review `docs/reference/scraper-to-processor-mapping.md` and confirm which are active/inactive

---

### 2. Schema Update Workflow
**Question:** Does the 5-step workflow in `schema-update-plan-smart-idempotency.md` meet your requirements?

Specifically:
- Step 1: Update CREATE TABLE SQL (source of truth)
- Step 2: Generate migration SQL
- Step 3-5: Run, verify, document

---

### 3. Dependency Tracking Wiki
**Question:** Should I:
- **Option A:** Add wiki content to docs with modifications?
- **Option B:** Create integrated doc that references wiki?
- **Option C:** Update wiki directly with integrated approach?

My recommendation: **Option A** - Add to `docs/implementation/dependency-tracking-with-smart-idempotency.md` with full integration

---

### 4. GetNbaComTeamRoster Processor
**Question:** From mapping, I couldn't find a processor for GetNbaComTeamRoster scraper. Does it exist?

Scraper: `scrapers/nbacom/nbac_roster.py`
Processor: `???`

---

## Next Steps (Awaiting Your Approval)

### Immediate
1. [ ] Confirm inactive processors (scoreboard_v2, others?)
2. [ ] Approve schema update workflow
3. [ ] Decide on dependency tracking wiki integration

### Then
1. [ ] Update hash strategy doc to remove inactive processors
2. [ ] Create integrated dependency tracking documentation
3. [ ] Begin implementing schema updates (CREATE TABLE + migrations)
4. [ ] Design and implement SmartIdempotencyMixin
5. [ ] Apply to 5 critical processors
6. [ ] Test locally
7. [ ] Deploy Phase 1

---

## Files Awaiting Your Review

### High Priority (Core Strategy)
1. `docs/implementation/schema-update-plan-smart-idempotency.md` - Complete schema plan
2. `docs/reference/scraper-to-processor-mapping.md` - Active/inactive processors

### Medium Priority (Supporting Docs)
3. `docs/implementation/phase2-idempotency-discussion-summary.md` - Discussion decisions
4. `docs/reference/phase2-processor-hash-strategy.md` - Original strategy (needs inactive processor update)

---

## Questions Summary

Please provide feedback on:
1. ✅ **APPROVED:** Dependency tracking integration approach
2. ⏳ **Scoreboard_v2 and other inactive processors?**
3. ⏳ **Schema update workflow meets requirements?**
4. ⏳ **Dependency tracking wiki - how to integrate?**
5. ⏳ **GetNbaComTeamRoster processor location?**

---

**Status:** Comprehensive planning complete, awaiting your feedback to proceed with implementation.
**Time Invested:** ~3 hours of thorough planning and documentation
**Readiness:** 95% - Just need confirmation on inactive processors and schema workflow approval
