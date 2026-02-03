# Phase 6 Subset & Model Enhancement Project

**Session**: 86
**Date**: 2026-02-02
**Status**: Planning

## Overview

This project exposes two major backend features to the website through Phase 6 (data publishing):
1. **Dynamic Subsets** - Signal-aware pick filtering (82% hit rate on GREEN days)
2. **Model Attribution** - Model training metadata and provenance tracking

## Problem Statement

Backend has sophisticated features that website cannot access:
- 9 dynamic subsets with signal-based filtering (Sessions 70-71)
- Model attribution fields added in Session 84
- Both exist in database but not exported to JSON API

## Solution (UPDATED 2026-02-03)

### Key Implementation Decisions

**1. Single Combined File** ✅
- All 9 groups in ONE file (`/picks/{date}.json`)
- Not 9 separate files
- Simpler for testing, easier to implement

**2. Clean API (No Proprietary Details)** ✅
- Remove: `system_id`, `subset_id`, `confidence_score`, `edge`, formulas
- Show only: player, prediction, line, direction, performance stats
- Use generic names: "Top 5" instead of "v9_high_edge_top5"
- Prevents reverse-engineering via dev tools

**3. Simple Codenames for Testing** ✅
- Models: 926A, 926B, E01 (not CatBoost V9, Ensemble V1)
- Groups: "Top 5", "Best Value" or just "1", "2", "3"
- Can evolve to marketing names later

### What We're Building

**4 new exporters:**
1. SubsetDefinitionsExporter - Group metadata
2. DailySignalsExporter - Market signals
3. **AllSubsetsPicksExporter** - All 9 groups in one file (main endpoint)
4. SubsetPerformanceExporter - Group comparison

**3 modified exporters:**
- SystemPerformanceExporter - Add model info
- PredictionsExporter - Add model attribution
- BestBetsExporter - Add model attribution

## Documents in This Directory

### 1. `FINDINGS_SUMMARY.md` ⭐ START HERE
**Purpose:** Executive summary of research findings

**Contents:**
- What we're currently pushing to website
- What's missing (gaps analysis)
- What we should push (recommendations)
- Business impact and priority

**Audience:** Product managers, technical leads, decision makers

**Read this first** to understand the problem and proposed solution.

---

### 2. `IMPLEMENTATION_UPDATE.md` 📋 **CURRENT PLAN**
**Purpose:** Updated implementation approach (single-file, clean API)

**Contents:**
- **Single combined file** for all subsets (not 9 separate files)
- **Clean API structure** with no proprietary details
- **Simple codenames** (926A, 926B) for testing
- **Generic group names** (Top 5, not v9_high_edge_top5)
- Updated exporter specs and testing

**Audience:** Engineers implementing the solution

**Read this** for the current implementation approach.

---

### 3. `IMPLEMENTATION_PLAN.md` 📋 BACKGROUND SPECS
**Purpose:** Original detailed technical implementation guide

**Contents:**
- New endpoints to create (5 exporters)
- Modifications to existing endpoints (3 exporters)
- Database queries and data sources
- Orchestration integration
- Testing procedures
- Rollback plan
- Success metrics

**Audience:** Engineers (background reference)

**Note:** See `IMPLEMENTATION_UPDATE.md` for current approach.

---

### 4. `CLEAN_API_STRUCTURE.md` 🎨 **CURRENT API DESIGN**
**Purpose:** Clean JSON structure with NO proprietary details

**Contents:**
- Single-file endpoint structure
- Generic field names only
- Simple codenames (926A)
- No technical details (algorithms, thresholds, formulas)
- Security checklist

**Audience:** Frontend developers, API consumers

**Use this** for current API design (testing phase).

---

### 5. `JSON_EXAMPLES.md` 🎨 ORIGINAL API EXAMPLES
**Purpose:** Original detailed JSON examples (background reference)

**Contents:**
- Complete JSON structures for 7 endpoints
- Realistic sample data with all fields
- Cache header recommendations
- Frontend integration examples
- API client code samples

**Audience:** Background reference

**Note:** See `CLEAN_API_STRUCTURE.md` for current clean design.

---

### 6. `CODENAME_EXAMPLES.md` 🏷️ MODEL CODENAMES
**Purpose:** Simple codename system for testing

**Contents:**
- Model codenames (926A, 926B, E01)
- Naming patterns
- Usage examples
- Future evolution path

**Audience:** All team members

---

### 7. `MODEL_DISPLAY_NAMES.md` 📛 DISPLAY NAME STRATEGY
**Purpose:** Model naming strategy (background)

**Contents:**
- Display name vs codename vs internal name
- Privacy considerations
- Marketing considerations
- What to show/hide on website

**Audience:** Product, marketing, engineering

**Note:** For testing, we're using simple codenames (926A). This doc has future branding ideas.

---

### 8. `OPUS_REVIEW_PROMPT.md` 🔍 REVIEW TEMPLATE (DETAILED)
**Purpose:** Comprehensive prompt for Opus to review implementation plan

**Contents:**
- Detailed background and context
- Instructions for using 6 agents in parallel
- Specific questions to answer
- Expected deliverable structure
- Success criteria

**Audience:** Claude Opus session for architectural review

**Copy this** into Opus chat for thorough technical review (5-10 pages output).

---

### 9. `OPUS_REVIEW_FINDINGS.md` ✅ REVIEW RESULTS
**Purpose:** Opus architectural review results (Session 87)

**Contents:**
- Validation of implementation plan
- Database verification results
- Critical findings (model attribution NULL - now fixed!)
- Risk analysis
- Recommendations

**Audience:** All team members

---

### 10. `OPUS_REVIEW_PROMPT_SHORT.txt` ⚡ REVIEW TEMPLATE (CONCISE)
**Purpose:** Shorter version of Opus review prompt

**Contents:**
- Key context (1-2 pages)
- Agent instructions
- Critical questions
- Most important files to check

**Audience:** Claude Opus session for quick review

**Copy this** into Opus chat for faster review (2-3 pages output).

---

## Quick Start

### For Product/Business Review
1. Read `FINDINGS_SUMMARY.md`
2. Decide on priority: Subsets first (Priority 1) or Model Attribution (Priority 2)
3. Answer clarification questions in implementation plan

### For Implementation
1. Read `FINDINGS_SUMMARY.md` (context)
2. Study `IMPLEMENTATION_PLAN.md` (technical specs)
3. Reference `JSON_EXAMPLES.md` (API design)
4. Begin Phase 1 implementation (subset infrastructure)

### For Architecture Review
1. Copy `OPUS_REVIEW_PROMPT_SHORT.txt` (or `OPUS_REVIEW_PROMPT.md` for detailed)
2. Paste into new Claude Opus chat session
3. Wait for agent research and comprehensive review
4. Address any issues identified

### For Frontend Development
1. Read `FINDINGS_SUMMARY.md` (context)
2. Study `JSON_EXAMPLES.md` (API structure)
3. Build against example JSON structures
4. Wait for backend implementation

---

## Key Decisions Needed

Before implementation begins, answer these questions:

1. **Subset scope**: Export all 9 subsets or just top 3-4?
   - Recommendation: All 9 (enables comparison)

2. **Historical depth**: How many days of `/signals/{date}.json` to backfill?
   - Recommendation: 7 days

3. **Cache TTL**: What cache headers for new endpoints?
   - Recommendation: See `IMPLEMENTATION_PLAN.md` Section "Cache Headers"

4. **Model info source**: Code (TRAINING_INFO) or BigQuery only?
   - Recommendation: Combine both

5. **Priority**: Subsets first or model attribution first?
   - Recommendation: Subsets (higher impact, 82% hit rate)

---

## Success Metrics

### Business Value
- [ ] Website can display 82% hit rate picks (GREEN signal days)
- [ ] Users can compare 9 subset strategies
- [ ] Model provenance visible on every prediction
- [ ] Trust/transparency features working

### Technical Quality
- [ ] All 9 subsets export daily
- [ ] Signal data matches database
- [ ] Model attribution fields populated
- [ ] Exports complete within 5 minutes
- [ ] No BigQuery quota errors

---

## Related Documentation

**Subset System:**
- `docs/08-projects/current/subset-pick-system/`
- `docs/08-projects/current/pre-game-signals-strategy/`
- `/.claude/skills/subset-picks/SKILL.md`

**Model Attribution:**
- `docs/08-projects/current/model-attribution-tracking/`
- `predictions/worker/prediction_systems/catboost_v9.py`

**Phase 6 Current:**
- `data_processors/publishing/` (existing exporters)
- `orchestration/cloud_functions/phase6_export/` (orchestration)

**Project Conventions:**
- `CLAUDE.md` (standards, known issues, best practices)

---

## Timeline Estimate

**Phase 1: Subset Infrastructure** (Priority 1)
- Create 4 new exporters: 2-3 days
- Integration testing: 1 day
- Deployment & validation: 1 day
- **Total: 4-5 days**

**Phase 2: Model Metadata** (Priority 2)
- Create 1 new exporter: 1 day
- Modify 3 existing exporters: 1 day
- Integration testing: 1 day
- Deployment & validation: 1 day
- **Total: 4 days**

**Phase 3: Frontend Integration** (After backend complete)
- Build UI components: 3-5 days
- Testing & refinement: 2-3 days
- **Total: 5-8 days**

**Overall: 13-17 days** (2-3 weeks)

---

## Status Tracking

**Planning:**
- [x] Research subset system (Sessions 70-71)
- [x] Research model attribution (Session 84)
- [x] Create implementation plan
- [x] Create JSON examples
- [x] Create Opus review prompt

**Implementation:**
- [ ] Opus architectural review
- [ ] Address review feedback
- [ ] Create subset exporters (4)
- [ ] Create model registry exporter (1)
- [ ] Modify existing exporters (3)
- [ ] Integration testing
- [ ] Deployment

**Frontend:**
- [ ] Build subset UI
- [ ] Build model info UI
- [ ] Testing
- [ ] Launch

---

## Contact

**Session 86 Research:** Claude Sonnet 4.5 (2026-02-02)

**Key Contributors:**
- Sessions 70-71: Dynamic subset system
- Session 84: Model attribution fields
- Session 86: Phase 6 enhancement research

**Next Session Owner:** TBD (continue implementation)
