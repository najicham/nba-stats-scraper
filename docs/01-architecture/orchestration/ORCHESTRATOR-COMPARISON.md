# Orchestrator Comparison: Which to Keep, Which to Remove

**CRITICAL:** Only Phase 2→3 should be removed. The others are FUNCTIONAL and REQUIRED.

---

## Quick Reference

| Orchestrator | Status | Triggers Downstream? | Can Remove? |
|--------------|--------|---------------------|-------------|
| **Phase 2→3** | 🗑️ **REMOVED** | ❌ NO (monitoring-only) | ✅ YES |
| **Phase 3→4** | ✅ **KEEP** | ✅ YES (publishes to nba-phase4-trigger) | ❌ **NO - BREAKING** |
| **Phase 4→5** | ✅ **KEEP** | ✅ YES (publishes to nba-phase5-trigger) | ❌ **NO - BREAKING** |
| **Phase 5→6** | ✅ **KEEP** | ✅ YES (publishes to nba-phase6-trigger) | ❌ **NO - BREAKING** |

---

## Why Phase 2→3 Was Unique (And Removable)

### Phase 2→3: MONITORING-ONLY

**Code Evidence:**
```python
# orchestration/cloud_functions/phase2_to_phase3/main.py lines 6-8
NOTE: This orchestrator is now MONITORING-ONLY. Phase 3 is triggered directly
via Pub/Sub subscription (nba-phase3-analytics-sub), not by this orchestrator.
The nba-phase3-trigger topic has no subscribers.
```

**What it did:**
- ❌ Did NOT publish to any trigger topic
- ❌ Did NOT gate Phase 3 execution
- ✅ Only tracked completion in Firestore
- ✅ Only ran quality checks (but didn't block on failures)

**How Phase 3 actually triggers:**
- Direct Pub/Sub subscription (`nba-phase3-analytics-sub`)
- Pushes to Phase 3 service `/process` endpoint
- Fires on EVERY Phase 2 processor completion (event-driven)

**Impact of removal:**
- ✅ ZERO - Phase 3 continues to work perfectly
- Proven during 7-day orchestrator outage (Feb 5-11, 2026)

---

## Why Phase 3→4 is FUNCTIONAL (And Required)

### Phase 3→4: TRIGGERS PHASE 4

**Code Evidence:**
```python
# orchestration/cloud_functions/phase3_to_phase4/main.py line 9
- Publishes to: nba-phase4-trigger (when all expected processors complete)

# Line 1928-1964: Actual publishing code
topic_path = publisher.topic_path(PROJECT_ID, PHASE4_TRIGGER_TOPIC)
future = publisher.publish(
    topic_path,
    data=json.dumps(message).encode('utf-8'),
    # ...
)
```

**What it does:**
- ✅ **Publishes to `nba-phase4-trigger` topic**
- ✅ **Gates Phase 4 execution** (Phase 4 waits for this trigger)
- ✅ Validates Phase 3 data quality (NULL rates, coverage)
- ✅ Checks minutes_played coverage (alerts <90%, blocks <80%)
- ✅ Performs health checks on downstream services
- ✅ Mode-aware orchestration (overnight vs same-day vs tomorrow)

**How Phase 4 triggers:**
```
Phase 3 Processors complete
  ↓
Phase 3→4 Orchestrator
  ↓ (validates quality, checks health)
Publishes to: nba-phase4-trigger
  ↓
Phase 4 Precompute Service listens to this topic
  ↓
Phase 4 executes
```

**Impact of removal:**
- 🔴 **BREAKING** - Phase 4 would never trigger
- 🔴 Pipeline would halt after Phase 3
- 🔴 No predictions would be generated

---

## Why Phase 4→5 is FUNCTIONAL (And Required)

### Phase 4→5: TRIGGERS PHASE 5

**What it does:**
- ✅ Publishes to `nba-phase5-trigger` topic
- ✅ Gates Phase 5 execution (predictions wait for Phase 4 completion)
- ✅ Validates Phase 4 feature store quality
- ✅ Checks feature completeness before allowing predictions

**Impact of removal:**
- 🔴 **BREAKING** - Predictions would never trigger
- 🔴 No daily predictions generated

---

## Why Phase 5→6 is FUNCTIONAL (And Required)

### Phase 5→6: TRIGGERS PHASE 6

**What it does:**
- ✅ Publishes to `nba-phase6-export-trigger` topic
- ✅ Gates Phase 6 execution (exports wait for predictions)
- ✅ Validates prediction quality before export

**Impact of removal:**
- 🔴 **BREAKING** - API exports would never publish
- 🔴 Frontend would have no data

---

## Key Differences

### Phase 2→3 (REMOVED)

**Why it was different:**
1. Explicitly stated "MONITORING-ONLY" in code comments
2. Did NOT publish to any trigger topic
3. The trigger topic (`nba-phase3-trigger`) had NO subscribers
4. Phase 3 triggered via DIFFERENT mechanism (direct Pub/Sub subscription)
5. Was broken for 7+ days with ZERO pipeline impact

**The smoking gun:**
```python
# Phase 2→3 orchestrator, line 979
if should_trigger:
    # NOTE: Phase 3 is triggered directly via Pub/Sub subscription, not here
    logger.info("✅ MONITORING: All processors complete...")
    # Does NOT publish to trigger topic!
```

### Phase 3→4, 4→5, 5→6 (FUNCTIONAL)

**Why they're different:**
1. Code says they trigger downstream (no "monitoring-only" disclaimer)
2. Actually publish to trigger topics with code evidence
3. Trigger topics HAVE subscribers (downstream services listen)
4. Downstream phases DEPEND on these triggers
5. Include quality gates that BLOCK bad data

**The proof:**
```python
# Phase 3→4 orchestrator, line 1928-1964
topic_path = publisher.topic_path(PROJECT_ID, PHASE4_TRIGGER_TOPIC)
future = publisher.publish(topic_path, ...)  # Actually publishes!
```

---

## How to Tell if an Orchestrator is Removable

### ✅ Signs it CAN be removed (like Phase 2→3):

1. Code explicitly says "monitoring-only"
2. Does NOT publish to a trigger topic
3. The trigger topic has no subscribers
4. Downstream phase has an alternative trigger mechanism
5. Has been broken for days with no pipeline impact
6. Only writes to Firestore (redundant with BigQuery)

### ❌ Signs it CANNOT be removed (like Phase 3→4):

1. Code says it "triggers" or "publishes to trigger topic"
2. Contains actual `publisher.publish()` calls
3. The trigger topic has subscribers (downstream services)
4. Downstream phase waits for this trigger
5. Includes quality gates that block transitions
6. Breaking it would halt the pipeline

---

## Decision Tree

```
Is the orchestrator broken?
  ├─ YES → Does the pipeline still work?
  │   ├─ YES → Probably monitoring-only (investigate removal)
  │   └─ NO → Functional orchestrator (fix immediately!)
  └─ NO → Check code comments
      ├─ Says "MONITORING-ONLY" → Consider removal
      └─ Says "triggers Phase X" → Keep (functional)
```

---

## For Other Chats/Sessions

**If you're evaluating an orchestrator for removal:**

1. **Read the code comments** - Does it say "monitoring-only"?
2. **Search for publish calls** - Does it actually publish to a trigger topic?
3. **Check subscribers** - Does the trigger topic have any subscribers?
4. **Test the hypothesis** - Break it intentionally, does pipeline halt?
5. **Compare to Phase 2→3** - Does it match the removal criteria?

**If in doubt, ASK before removing!** Only Phase 2→3 matched ALL the criteria for safe removal.

---

## Summary

**ONLY Phase 2→3 should be removed.**

It was a unique case:
- Explicitly monitoring-only (stated in code)
- Did not trigger downstream
- Alternative trigger existed (direct Pub/Sub)
- Proven non-critical (7-day outage, zero impact)

**All other orchestrators are FUNCTIONAL and CRITICAL:**
- They actually trigger downstream phases
- Downstream phases depend on them
- Removing them would break the pipeline

**Do NOT apply the Phase 2→3 removal logic to other orchestrators.**

---

**Document Created:** February 12, 2026 (Session 204)
**Purpose:** Prevent accidental removal of functional orchestrators
