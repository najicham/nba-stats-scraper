# Robustness Improvements - Project Index
**Created:** January 21, 2026
**Status:** Active Development

---

## Overview

This directory contains documentation for improving data pipeline robustness, specifically addressing missing game data and implementing better monitoring/alerting.

---

## Documents

### 1. BDL Missing Games - Root Cause & Fixes
**File:** `BDL-MISSING-GAMES-ROOT-CAUSE-AND-FIXES.md`

**Purpose:** Comprehensive analysis of why 31 games were missing from BigQuery and detailed implementation plan to prevent future occurrences.

**Contents:**
- Root cause analysis (scraper timing + missing workflow executions)
- Current infrastructure review
- Critical gaps identified
- 3-phase improvement plan (Immediate, Short-term, Medium-term)
- Implementation checklist
- Success metrics

**Read this if:** You need to understand the full context and implement the fixes.

---

### 2. Quick Start Guide
**File:** `QUICK-START-BDL-FIXES.md`

**Purpose:** Fast-track implementation guide with copy-paste commands.

**Contents:**
- 4 immediate actions (backfill, logging, completeness check, investigation)
- Exact commands to run
- Code snippets to add
- Verification queries
- Expected timeline (~1.5 hours)

**Read this if:** You want to start implementing immediately.

---

### 3. Latency Visibility & Resolution Plan 🚀 IMPLEMENTATION READY
**File:** `LATENCY-VISIBILITY-AND-RESOLUTION-PLAN.md`

**Purpose:** Actionable implementation plan synthesizing all previous investigations into a unified latency visibility and automated resolution strategy.

**Contents:**
- 5-phase implementation plan (deploy existing → integrate logging → validation → retry queue → expand)
- Detailed code examples and integration points
- Deploy scripts and SQL schemas ready to use
- Success metrics and monitoring dashboards
- 20-hour implementation timeline over 3 weeks
- Builds on what exists: activates ready-to-deploy monitoring, completes started work

**Read this if:** You want step-by-step instructions to implement latency improvements NOW.

---

### 4. Multi-Scraper Visibility & Latency Plan
**File:** `MULTI-SCRAPER-VISIBILITY-AND-LATENCY-PLAN.md`

**Purpose:** Strategic overview for improving visibility and latency monitoring across ALL scrapers (BDL, NBAC, OddsAPI, ESPN, etc.)

**Contents:**
- Unified architecture for monitoring all 33 scrapers
- 4-phase implementation plan with time estimates
- Reusable patterns (availability logger, completeness validator, retry queue)
- Success metrics and quick start commands
- Builds on existing monitoring infrastructure + BDL fixes

**Read this if:** You want the complete strategic roadmap for scraper monitoring.

---

### 5. All Scrapers Latency Expansion Plan 📅 WEEK 2-4 ROADMAP
**File:** `ALL-SCRAPERS-LATENCY-EXPANSION-PLAN.md`

**Purpose:** 4-week implementation roadmap for expanding latency monitoring to all 33 NBA scrapers.

**Contents:**
- Scraper inventory by priority tier (Critical, Props, Supplementary, Alternative)
- Week-by-week implementation plan
- NBAC and OddsAPI availability logger patterns
- Player props validation strategy
- Unified monitoring dashboard design
- Success metrics per scraper category

**Read this if:** You want to expand monitoring beyond BDL to all data sources.

---

### 6. Error Tracking Proposal
**File:** `ERROR-TRACKING-PROPOSAL.md`

**Purpose:** Future-looking proposal for comprehensive error tracking system.

**Contents:**
- Error classification taxonomy
- Automatic retry logic
- Alert routing strategy
- BigQuery schema designs

**Read this if:** You want to understand the longer-term vision.

---

## Related Documentation

### Historical Backfill Audit
**Location:** `../historical-backfill-audit/`

Key files:
- `2026-01-21-DATA-VALIDATION-REPORT.md` - 30-day data completeness validation
- `BDL-AVAILABILITY-INVESTIGATION-JAN-21-2026.md` - Investigation of BDL API availability
- `BDL-SUPPORT-EMAIL-DRAFT.md` - Email to BDL support (sent, they confirmed data exists)
- `data-completeness-validation-guide.md` - How to validate data completeness

### Monitoring Infrastructure
**Location:** `../../schemas/bigquery/monitoring/`

Key files:
- `bdl_game_availability_tracking.sql` - Views for tracking BDL vs NBAC data availability
- Views deployed: `v_bdl_game_availability`, `v_bdl_availability_latency`, `v_bdl_availability_summary`

### Code Created (Ready to Deploy)
**Location:** `../../shared/utils/` and `../../schemas/bigquery/`

Files:
- `shared/utils/bdl_availability_logger.py` - Logs per-game availability ✅
- `schemas/bigquery/nba_orchestration/bdl_game_scrape_attempts.sql` - Table definition ✅

---

## Current Status

### ✅ Completed
- Root cause analysis (BDL missing games)
- BDL API verification (data IS available)
- Multi-scraper monitoring views (BDL, NBAC, OddsAPI) - DEPLOYED
- **Scraper availability monitor Cloud Function** - ✅ **DEPLOYED & RUNNING** (Jan 22, 2026)
- **BDL game scrape attempts table** - ✅ **DEPLOYED** (Jan 22, 2026)
- **BDL availability logger integration** - ✅ **INTEGRATED** into bdl_box_scores.py
- **Monitoring dashboard queries** - ✅ **CREATED** (monitoring/daily_scraper_health.sql)
- Comprehensive multi-scraper visibility plan
- **Latency visibility & resolution implementation plan** - ✅ **READY** (Phases 0-1 complete)
- **All scrapers expansion plan** - ✅ **READY** (4-week roadmap for 33 scrapers)
- Codebase exploration (3 specialized agents: execution, monitoring, latency)
- Documentation

### 🔄 In Progress
- BDL availability tracking (will populate after next scraper run)
- Daily monitoring alerts (first alert: Jan 23, 8 AM ET)

### ⏳ Pending (Priority Order)

**P0 - Immediate (This Week):**
1. Backfill 31 missing games
2. Deploy game-level logging
3. Add completeness check to scraper
4. Investigate missing workflow executions

**P1 - Short-term (Next 2 Weeks):**
5. Create missing game retry queue
6. Add 10 AM ET recovery window

**P2 - Medium-term (Next Month):**
7. Real-time completeness monitor
8. Weekly reconciliation job

---

## Quick Links

### Commands

**Backfill missing games:**
```bash
gcloud run jobs execute bdl-boxscore-backfill \
  --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app,--dates=2026-01-01,2026-01-15,2026-01-16,2026-01-17,2026-01-18,2026-01-19" \
  --region=us-west2
```

**Check data completeness:**
```sql
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM nba_raw.bdl_player_boxscores
WHERE game_date BETWEEN '2026-01-01' AND '2026-01-19'
GROUP BY game_date
ORDER BY game_date DESC;
```

**View BDL availability:**
```sql
SELECT game_date, matchup, has_bdl_data, has_nbac_data, first_available_source
FROM nba_orchestration.v_bdl_game_availability
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;
```

---

## Key Findings Summary

### The Problem
- 31 games missing from `nba_raw.bdl_player_boxscores` (Jan 1-19, 2026)
- 76% of missing games are West Coast home teams
- Games are in BDL's API, but weren't scraped at the right time

### Root Causes
1. **Timing Issue:** Some scrapers ran before games finished or before BDL processed the data
2. **Missing Executions:** Recovery windows (2 AM, 4 AM, 6 AM) didn't run (only 1 AM ran)
3. **No Validation:** Scraper doesn't detect missing games automatically

### The Fix
1. Backfill the data (5 min)
2. Add per-game logging (tracks when each game becomes available)
3. Add completeness check (alerts when games are missing)
4. Fix workflow execution (ensure all retry windows run)
5. Add retry queue (automatically retries missing games)

---

## Contact / Ownership

**Project Lead:** Data Engineering Team
**Created By:** Claude Code sessions (Jan 21, 2026)
**Next Review:** After P0 implementation (within 1 week)

---

## Change Log

| Date | Change | By |
|------|--------|-----|
| 2026-01-21 | Initial documentation created | Claude Code |
| 2026-01-21 | Root cause analysis completed | Claude Code |
| 2026-01-21 | BDL API verification (data confirmed available) | Claude Code |
| 2026-01-21 | Monitoring views deployed | Claude Code |
| 2026-01-21 | Multi-scraper visibility & latency plan created | Claude Code |
| 2026-01-21 | Codebase exploration completed (3 exploration agents) | Claude Code (Sonnet 4.5) |
| 2026-01-21 | Latency visibility & resolution implementation plan created | Claude Code (Sonnet 4.5) |
| 2026-01-22 | ✅ **Scraper availability monitor DEPLOYED** | Claude Code (Sonnet 4.5) |
| 2026-01-22 | ✅ **BDL game scrape attempts table DEPLOYED** | Claude Code (Sonnet 4.5) |
| 2026-01-22 | ✅ **BDL availability logger INTEGRATED** | Claude Code (Sonnet 4.5) |
| 2026-01-22 | ✅ **Monitoring dashboard queries CREATED** | Claude Code (Sonnet 4.5) |
| 2026-01-22 | All scrapers latency expansion plan created (33 scrapers, 4-week roadmap) | Claude Code (Sonnet 4.5) |

---

**Last Updated:** January 22, 2026
