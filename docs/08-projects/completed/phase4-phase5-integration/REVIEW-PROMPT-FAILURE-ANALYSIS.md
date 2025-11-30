# Review Prompt: Failure Analysis & Troubleshooting

**Created:** 2025-11-28 9:10 PM PST
**Purpose:** Prompt for secondary review of failure analysis
**Target:** Fresh Claude instance for thorough review

---

## Context

We're building an event-driven data pipeline for NBA sports betting predictions with 5 phases:

1. **Phase 1:** Scrapers collect data from NBA.com APIs → GCS
2. **Phase 2:** Raw processors load JSON from GCS → BigQuery raw tables
3. **Phase 3:** Analytics processors aggregate raw data → BigQuery analytics tables
4. **Phase 4:** Precompute processors generate ML features → BigQuery precompute tables
5. **Phase 5:** Prediction workers generate point predictions for 450+ players

**Architecture:**
- Event-driven using Pub/Sub for phase transitions
- 3 orchestrators (Cloud Functions + Firestore) coordinate phases
- Change detection to process only modified entities
- Deduplication via processor_run_history table
- Backup schedulers for reliability
- All services on Cloud Run

**Current Status:**
- Phases 1-2 working in production (4 seasons backfilled)
- Phases 3-5 designed but never run (greenfield)
- About to implement v1.0 unified architecture

---

## Your Task

Review the failure analysis document and architectural design to identify:

1. **Missing failure scenarios** we didn't consider
2. **Edge cases** in the failure modes we documented
3. **Cascading failures** where one failure triggers others
4. **Silent failures** that might go undetected
5. **Race conditions** in the orchestration logic
6. **Data consistency issues** across phases
7. **Operational blindspots** where we lack observability
8. **Recovery gaps** where manual procedures might fail
9. **Prevention weaknesses** in our mitigation strategies
10. **Scale issues** that emerge at high volume

---

## Documents to Review

**Primary Review Target:**
- `FAILURE-ANALYSIS-TROUBLESHOOTING.md` - The main failure analysis (just created)

**Architecture Context:**
- `V1.0-IMPLEMENTATION-PLAN-FINAL.md` - Complete implementation plan
- `UNIFIED-ARCHITECTURE-DESIGN.md` - Technical architecture specification
- `DECISIONS-SUMMARY.md` - Key architectural decisions

**Supporting Context:**
- `PUBSUB-INFRASTRUCTURE-AUDIT.md` - Current Pub/Sub setup
- `QUICK-START-GUIDE.md` - System overview

**Read in this order:**
1. QUICK-START-GUIDE.md (5 min) - Get oriented
2. FAILURE-ANALYSIS-TROUBLESHOOTING.md (20 min) - The review target
3. V1.0-IMPLEMENTATION-PLAN-FINAL.md (15 min) - Implementation details
4. UNIFIED-ARCHITECTURE-DESIGN.md (skim sections 3-5) - Architecture details

---

## Specific Areas to Scrutinize

### 1. Orchestrator Failure Modes

**Current Analysis:**
- Firestore write failures
- Cloud Function crashes
- Duplicate messages
- Partial state (missing processors)

**Questions to Consider:**
- What if Firestore is eventually consistent and two function instances update same document?
- What if orchestrator triggers Phase N+1 twice due to race condition?
- What if Firestore quota is exceeded?
- What if orchestrator aggregates entities_changed incorrectly?
- What if multiple game dates processing simultaneously conflict?
- What if orchestrator state becomes corrupted in a way we can't detect?

### 2. Change Detection Failure Modes

**Current Analysis:**
- Hash comparison fails → falls back to full batch
- Change detection identifies wrong entities

**Questions to Consider:**
- What if hash function has collisions with real data?
- What if row order in BigQuery affects hash computation?
- What if schema changes between runs affect hashes?
- What if timezone differences cause same data to hash differently?
- What if we miss a changed entity due to hash bug?
- What if change detection performance degrades with scale?
- What if previous_run_id query returns wrong run?

### 3. Cross-Phase Data Consistency

**Current Analysis:**
- Various per-phase failures documented

**Questions to Consider:**
- What if Phase 2 processes v1 data while Phase 3 still processing v0?
- What if scraper runs twice for same date (race condition)?
- What if MERGE statement in Phase 2 partially succeeds?
- What if BigQuery table modified by another process?
- What if read-your-writes consistency issues in BigQuery?
- What if phases process different time ranges (date boundary issues)?
- What if daylight saving time causes date confusion?

### 4. Pub/Sub Message Ordering

**Current Analysis:**
- Duplicate messages handled via deduplication
- Message too large

**Questions to Consider:**
- What if messages arrive out of order? (scraper for tomorrow before today)
- What if old message redelivered after newer data already processed?
- What if entities_changed list from Phase 2 contradicts Phase 3?
- What if correlation_id reused accidentally?
- What if message published before data fully written to BigQuery?
- What if Pub/Sub has regional failover and redelivers all messages?

### 5. Deduplication Issues

**Current Analysis:**
- False positives (skips when shouldn't)
- Bypass with force_reprocess flag

**Questions to Consider:**
- What if processor_run_history query is slow and times out?
- What if two instances of same processor run simultaneously?
- What if deduplication check happens before previous run commits?
- What if status='failed' but partial data was written?
- What if we want to reprocess but downstream already consumed data?
- What if deduplication based on wrong date (UTC vs PT)?

### 6. Phase 5 Coordinator State

**Current Analysis:**
- In-memory state lost on restart
- Partial batch handling

**Questions to Consider:**
- What if coordinator receives completion events out of order?
- What if coordinator thinks batch complete but some workers still running?
- What if worker publishes completion twice?
- What if coordinator restarts during critical section?
- What if two coordinators run simultaneously?
- What if prediction-ready messages lost before coordinator receives them?
- What if coordinator state shows 450/450 but only 400 rows in BigQuery?

### 7. Backfill Mode

**Current Analysis:**
- skip_downstream_trigger flag

**Questions to Consider:**
- What if processor forgets to check skip_downstream_trigger?
- What if backfill_mode inconsistent across phases?
- What if some processors in backfill mode, others not?
- What if backfill accidentally triggers production processing?
- What if we need to backfill but preserve some downstream data?
- What if backfill runs concurrently with production processing?

### 8. Resource Exhaustion

**Current Analysis:**
- BigQuery quota exceeded
- Memory limits exceeded
- Pub/Sub quota

**Questions to Consider:**
- What if Cloud Run concurrent request limit hit?
- What if Firestore write rate limit exceeded?
- What if Pub/Sub publish rate limit exceeded?
- What if BigQuery slot contention across queries?
- What if GCS bandwidth limits hit?
- What if too many Cloud Function instances spawn?
- What if connection pool exhausted?

### 9. Time-Based Edge Cases

**Current Analysis:**
- Various timeout scenarios

**Questions to Consider:**
- What if processing spans midnight and date changes?
- What if game rescheduled to different date mid-pipeline?
- What if clock skew between services?
- What if scheduler triggers during pipeline processing?
- What if backup scheduler triggers before Pub/Sub path completes?
- What if retry schedulers trigger before main scheduler?
- What if timeout set too short for large batches?

### 10. Data Quality Silent Failures

**Current Analysis:**
- Schema validation
- Row count validation

**Questions to Consider:**
- What if all hashes are same (bug in hash function)?
- What if data looks valid but is actually wrong (API returns test data)?
- What if predictions generated but all values are NaN?
- What if ml_feature_store has all rows but missing critical columns?
- What if change detection always reports 0 changes (bug)?
- What if correlation_id propagates but gets overwritten?
- What if processor reports success but didn't actually save data?

---

## Analysis Framework

For each potential failure you identify, please provide:

1. **Scenario:** Clear description of what goes wrong
2. **Trigger:** What causes this failure?
3. **Impact:** What breaks? Data loss? Corruption? Delay?
4. **Detection:** How would we know this happened?
5. **Current Handling:** Is this covered in existing analysis?
6. **Gaps:** What's missing from current analysis?
7. **Recommendation:** How should we handle it?
   - Self-healing mechanism?
   - Manual procedure?
   - Prevention strategy?
   - Monitoring/alerting?

---

## Deliverable Format

Please structure your response as:

### Part 1: Critical Gaps
Failures we MUST address before v1.0 launch
- List with justification
- Suggested fixes

### Part 2: Important Gaps
Failures that should be addressed in v1.0 or early v1.1
- List with justification
- Suggested fixes

### Part 3: Edge Cases
Unlikely but possible scenarios to document
- List with probability assessment
- Suggested monitoring or documentation

### Part 4: Cascading Failures
Scenarios where one failure triggers multiple others
- Failure chains
- Breakpoints to stop cascades

### Part 5: Silent Failure Detection
Ways the system could fail without obvious errors
- Detection mechanisms needed
- Monitoring improvements

### Part 6: Enhanced Recovery Procedures
Gaps in recovery procedures or additional procedures needed
- What's missing?
- New procedures to add

### Part 7: Prevention Strategies
Additional ways to prevent failures before they happen
- Design improvements
- Defensive coding patterns
- Testing approaches

---

## Key Assumptions to Challenge

Please specifically challenge these assumptions:

1. **"Deduplication prevents all duplicate processing"**
   - Are there edge cases where deduplication fails?
   - What if deduplication itself has bugs?

2. **"Orchestrator aggregates changed entities correctly"**
   - What if aggregation has race conditions?
   - What if Firestore reads are stale?

3. **"Backup schedulers provide reliable fallback"**
   - What if both Pub/Sub AND schedulers fail?
   - What if scheduler triggers at wrong time?

4. **"processor_run_history is source of truth"**
   - What if table is corrupted or deleted?
   - What if queries against it are slow/timeout?

5. **"Change detection falls back to full batch safely"**
   - Are there cases where fallback doesn't work?
   - What if full batch also fails?

6. **"MERGE operations are idempotent"**
   - Are there BigQuery consistency issues?
   - What if MERGE partially succeeds?

7. **"Correlation ID traces full pipeline"**
   - What if correlation_id is null or duplicated?
   - What if different phases have different correlation_ids?

8. **"Cloud Run auto-restarts handle crashes"**
   - What if restart loop happens?
   - What if all instances crash simultaneously?

---

## Success Criteria for Your Review

Your review should help us:

1. **Identify blind spots** in our failure analysis
2. **Find critical issues** we missed that could cause production incidents
3. **Improve recovery procedures** with better or additional procedures
4. **Enhance prevention** with architectural or implementation improvements
5. **Strengthen monitoring** by identifying what to watch
6. **Validate robustness** of the overall design

---

## Important Notes

- **Be critical** - we want to find problems now, not in production
- **Think adversarially** - how could this fail in unexpected ways?
- **Consider scale** - what works for 100 players but breaks at 10,000?
- **Real-world context** - sports betting requires high reliability
- **Cost of failure** - wrong predictions = lost money/reputation
- **Time pressure** - predictions must be ready by 10 AM ET daily

---

## Example of Good Feedback

**Bad:** "Orchestrator could fail"
- Too vague, already covered

**Good:** "Orchestrator race condition: If two Phase 3 processors complete simultaneously and both Cloud Function instances read Firestore before either writes, both might count same processor as #5 and trigger Phase 4 twice. Current analysis doesn't cover this. Recommend: Use Firestore transactions for atomic read-modify-write."

**Better:** "Orchestrator race condition with cascading impact: If Phase 4 triggered twice due to race condition, both instances process same data, creating duplicate writes. If Phase 4 uses INSERT instead of MERGE, we get duplicate rows in ml_feature_store_v2. Phase 5 then generates duplicate predictions with same player_lookup and game_date, violating uniqueness assumption. Detection: Row count validation would catch this. Recovery: Delete duplicates, reprocess. Prevention: Use MERGE everywhere, add unique constraints, use Firestore transactions in orchestrator."

---

## Your Task Checklist

- [ ] Read QUICK-START-GUIDE.md for context
- [ ] Read FAILURE-ANALYSIS-TROUBLESHOOTING.md thoroughly
- [ ] Review V1.0-IMPLEMENTATION-PLAN-FINAL.md for implementation details
- [ ] Skim UNIFIED-ARCHITECTURE-DESIGN.md for architecture
- [ ] Think through each of the 10 scrutiny areas above
- [ ] Challenge each of the 8 key assumptions
- [ ] Document findings in the 7-part deliverable format
- [ ] Prioritize findings (critical vs important vs edge case)
- [ ] Provide actionable recommendations

---

## Expected Output Length

Comprehensive review: 2000-4000 words covering:
- 10-20 critical gaps
- 10-30 important gaps
- 5-15 edge cases
- 5-10 cascading failure scenarios
- 5-10 silent failure mechanisms
- 3-5 enhanced recovery procedures
- 5-10 prevention strategies

Quality over quantity - focus on high-impact findings.

---

**Ready?** Start with QUICK-START-GUIDE.md to get oriented, then dive deep into FAILURE-ANALYSIS-TROUBLESHOOTING.md. We're counting on you to find what we missed! 🔍
