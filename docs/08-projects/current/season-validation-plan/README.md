# Season-Wide Data Validation Plan

**Project:** Comprehensive 2024-25 Season Data Validation
**Status:** Planning
**Created:** 2026-01-25
**Priority:** P0 (Critical)

## Objective

Validate all backfilled data for the 2024-25 NBA season to ensure:
1. **Completeness**: All expected data exists for every game date
2. **Integrity**: Data is accurate and consistent across phases
3. **Cascade Health**: Downstream data properly reflects upstream sources
4. **Production Readiness**: All data meets quality thresholds for predictions

## Season Scope

| Parameter | Value |
|-----------|-------|
| Season | 2024-25 |
| Season Start | October 22, 2024 |
| Regular Season End | April 13, 2025 |
| Playoffs End | ~June 17, 2025 |
| Total Regular Season Days | ~174 days |
| Validation Date Range | Oct 22, 2024 → Present (Jan 25, 2026) |

## Key Documents

| Document | Purpose |
|----------|---------|
| [QUICKSTART.md](./QUICKSTART.md) | TL;DR commands and common scenarios |
| [01-VALIDATION-APPROACH.md](./01-VALIDATION-APPROACH.md) | Overall validation strategy and methodology |
| [02-PHASE-VALIDATION-MATRIX.md](./02-PHASE-VALIDATION-MATRIX.md) | What to validate for each phase |
| [03-CASCADE-IMPACT-TRACKING.md](./03-CASCADE-IMPACT-TRACKING.md) | How to identify downstream dates needing re-run |
| [04-RESULTS-STORAGE-SCHEMA.md](./04-RESULTS-STORAGE-SCHEMA.md) | BigQuery schema for storing validation results |
| [05-EXECUTION-PLAN.md](./05-EXECUTION-PLAN.md) | Step-by-step execution commands |
| [06-PRIORITIZATION-FRAMEWORK.md](./06-PRIORITIZATION-FRAMEWORK.md) | How to prioritize backfill work |
| [07-RESEARCH-FINDINGS.md](./07-RESEARCH-FINDINGS.md) | **Schema corrections and known issues** |

## Quick Overview

### The Problem

We need to validate ~95+ days of NBA season data across 6 pipeline phases to identify:
- Missing data (gaps)
- Incomplete data (partial records)
- Cascade contamination (downstream data built on incomplete upstream)
- Quality degradation (low completeness scores)

### The Solution

A systematic validation approach that:
1. Scans each date across all phases
2. Records validation results in BigQuery
3. Identifies cascade impact (which downstream dates are affected)
4. Prioritizes backfill work by severity and recency
5. Provides clear remediation commands

### Key Insight: Cascade Impact

Due to rolling window calculations (L5, L10, L7d, L14d, L20), **a single missing date can affect up to 30 downstream dates**:

```
Missing Date X in Phase 2
    ↓
Phase 3: Date X missing, Dates X+1 to X+10 have degraded quality
    ↓
Phase 4: Date X missing, Dates X+1 to X+20 have degraded quality
    ↓
Phase 5: Date X missing, Dates X+1 to X+30 have degraded quality
```

This means validation must track both:
- **Direct gaps**: Dates with missing data
- **Cascade-affected dates**: Dates with potentially degraded downstream data

## Success Criteria

- [ ] All season dates validated across all 6 phases
- [ ] All gaps identified and documented
- [ ] Cascade impact calculated for each gap
- [ ] Validation results stored in queryable BigQuery table
- [ ] Prioritized backfill queue generated
- [ ] Clear remediation plan for each issue type
