# Recurring Incident Patterns Analysis
**Generated:** December 30, 2025
**Source:** Analysis of postmortems and handoffs (Dec 27-30)
**Purpose:** Identify systemic issues needing automation

---

## Critical Recurring Patterns (P0)

### 1. Data Completeness Not Validated Until Too Late
**Incidents:** Gamebook gap (Dec 27-28), Boxscore gaps (Nov-Dec), Phase 3 analytics gap (Dec 29)

**Pattern:** System logs "success" without checking if ALL expected data was collected

**Example:** Gamebook scraper logged "success (3 records)" but was only 1/9 games

**Fix Needed:**
- Completeness validators at all collection points
- Compare records found vs records expected
- Alert when ratio < 100%

---

### 2. Missing Scheduler for Yesterday's Analytics
**Incident:** Dec 29 grading blocked - `player_game_summary` not calculated for yesterday

**Root Cause:** Only same-day schedulers existed; no daily analytics for completed games

**Fix Needed:**
- Create `daily-yesterday-analytics` scheduler (5:30 AM ET)
- Run before grading (6 AM ET)
- Process: PlayerGameSummary, TeamGameSummary, RollingAverages, ContextualMetrics

---

### 3. Orchestrator Design Mismatch
**Incident:** Phase 3→4 waits for 5 processors, but same-day scheduler only triggers 1

**Pattern:** Orchestrator designed for overnight mode, not same-day selective mode

**Fix Needed:**
- Mode-aware orchestration
- Explicit processor subset configuration
- Don't wait for processors that won't run

---

## High Priority Patterns (P1)

### 4. Data Format Inconsistency
**Incidents:** game_id format mismatch (NBA.com vs standard YYYYMMDD_AWAY_HOME)

**Fix Needed:**
- Centralized game_id standardization at ingestion
- Single source of truth for format
- Validation at every boundary

---

### 5. Single Point of Failure: Firestore
**Risk:** All orchestrators depend on Firestore; no fallback

**Fix Needed:**
- BigQuery as backup state tracking
- Health check with automatic failover
- Or: Reduce Firestore dependency

---

### 6. Fixed Timing Without Dependency Checks
**Incidents:** Grading at 7 AM assumes analytics complete in 30 min

**Pattern:** Schedulers on fixed times; no validation prerequisites complete

**Fix Needed:**
- Event-driven triggers instead of fixed times
- Or: Explicit wait with timeout
- Health check before each phase

---

### 7. Missing Data Source Redundancy
**Incident:** BDL API failures → 125 players locked out

**Fix Needed:**
- Multi-source fallback: BDL → NBA.com → ESPN
- Retry with exponential backoff
- Circuit breaker with auto-recovery

---

### 8. Misleading Success Metrics
**Incident:** "Success (3 records)" was actually partial failure

**Fix Needed:**
- Include completeness ratio in all logs: "3/9 records (33%)"
- Alert on partial completion
- Separate "completed" from "fully successful"

---

## Medium Priority Patterns (P2)

### 9. Processor Slowdown Not Detected
**Incident:** 8.2x baseline slowdown discovered manually

**Fix Needed:**
- Continuous baseline comparison
- Alert at 2x threshold
- Critical at 3x threshold
- Already implemented: `monitoring/processor_slowdown_detector.py`

---

### 10. No End-to-End Latency Tracking
**Gap:** Can't measure game_end → predictions_graded

**Fix Needed:**
- Create `nba_monitoring.pipeline_execution_log` table
- Track all phase timestamps per game
- Calculate total latency
- Define 6-hour SLA

---

### 11. DLQ Messages Not Monitored
**Gap:** Pub/Sub DLQ messages expire silently

**Fix Needed:**
- Cloud Monitoring alert on message count > 0
- Auto-replay mechanism
- Dashboard visibility

---

### 12. Circuit Breaker Too Aggressive
**Incident:** 7-day lockout after 3 failures

**Fix Needed:**
- Shorter timeout (24 hours, not 7 days)
- Auto-unlock when data becomes available
- Gradual recovery (half-open state)

---

### 13. No Pre-Game State in Live Export
**Gap:** Export shows yesterday's data before games start

**Fix Needed:**
- Detect "no games started yet" state
- Show upcoming schedule instead of stale data
- Or: Show "waiting for games" message

---

## Systemic Automation Roadmap

### Week 1: Validation & Alerting
1. Completeness validators for all scrapers
2. Alert manager email/Slack implementation
3. DLQ monitoring alerts

### Week 2: Redundancy & Fallbacks
1. Multi-source scraper fallback
2. Firestore health check with BigQuery backup
3. Circuit breaker auto-recovery

### Week 3: Observability
1. End-to-end latency tracking
2. Completeness ratio in all logs
3. SLA monitoring dashboard

### Week 4: Orchestration Fixes
1. Mode-aware orchestration
2. Event-driven phase triggers
3. Explicit dependency checks

---

## Latest Incident: 2026-01-18

### 14. Missing Dependency Management Across Services
**Incident:** Jan 18 - Firestore import error in prediction-worker

**Pattern:** Dependencies added to one service but not related services

**Example:** Distributed lock feature (Session 92) added Firestore to coordinator but not worker

**Fix Needed:**
- Centralized dependency management
- Dependency audit script
- Pre-commit hooks to validate dependencies
- Integration tests that catch import errors

**Status:** 🔴 NEW PATTERN - Documented in incidents/2026-01-18/

---

### 15. All-or-Nothing Orchestration Too Strict
**Incident:** Jan 18 - Phase 4 not triggered due to 2/5 Phase 3 processors complete

**Pattern:** Single processor failure blocks entire pipeline

**Example:** Phase 3→4 requires ALL 5 processors; if 1 fails, Phase 4 never runs

**Fix Needed:**
- Critical-processor-only trigger mode
- Separate critical path from optional tasks
- Graceful degradation with quality flags
- Already designed: See incidents/2026-01-18/FIX-AND-ROBUSTNESS-PLAN.md

**Status:** 🔴 HIGH PRIORITY - Fix ready for implementation

---

### 16. Data Availability Timing Issues
**Incident:** Jan 18 - Phase 3 created 1 record instead of 156 (Jan 17), then 156 records 21 hours later

**Pattern:** Fixed schedules fail when external data has variable availability

**Example:** Betting lines for Sunday games not published until Saturday afternoon

**Fix Needed:**
- Event-driven triggers instead of fixed schedules
- Data availability signals before processing
- Retry logic when data incomplete
- Already designed: See plans/EVENT-DRIVEN-ORCHESTRATION-DESIGN.md

**Status:** 🔴 RECURRING - 3rd occurrence, fix designed

---

## Files Referenced

| Document | Location |
|----------|----------|
| Gamebook Postmortem | postmortems/GAMEBOOK-INCIDENT-POSTMORTEM.md |
| Dec 29 Orchestration Postmortem | postmortems/2025-12-29-DAILY-ORCHESTRATION-POSTMORTEM.md |
| Boxscore Gaps Analysis | live-data-reliability/BOXSCORE-DATA-GAPS-ANALYSIS.md |
| Live Data Analysis | live-data-reliability/LIVE-DATA-PIPELINE-ANALYSIS.md |
| Morning Pipeline Fixes | session-handoffs/2025-12/2025-12-30-MORNING-PIPELINE-FIXES.md |
| **2026-01-18 Incident** | **incidents/2026-01-18/** |

---

**Last Updated:** January 18, 2026

*This analysis should drive prioritization of systemic fixes over reactive patches.*
