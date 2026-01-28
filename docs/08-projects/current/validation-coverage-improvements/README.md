# Validation Coverage Improvements

**Created**: 2026-01-28
**Status**: Investigation Phase
**Priority**: P1

---

## Overview

This project aims to close critical validation blind spots identified during the Jan 25-28 pipeline stall investigation. The pipeline was stalled for 2+ days without detection, highlighting gaps in our observability.

## Current Validation Coverage

### What We Have (Working Well)

| Component | Tool/Skill | Detection Capability |
|-----------|------------|---------------------|
| Daily Health | `/validate-daily` | Field completeness, usage_rate anomalies, prediction coverage |
| Historical Audit | `/validate-historical` | Data gaps over date ranges, cascade contamination |
| Gap Detection | `/spot-check-*` skills | Missing players, DNP tracking, roster issues |
| Infrastructure | Stall detection (15-min) | Phase processor stalls |
| Email Alerts | 6 AM health summary | Daily digest of issues |

### What We're Missing (Blind Spots)

| Blind Spot | Impact | Example from Jan 25-28 |
|------------|--------|------------------------|
| Orchestrator health | 2-day stall undetected | `phase3-to-phase4-orchestrator` failed silently |
| Calculation verification | Could ship wrong data | No way to verify rolling averages are correct |
| Cross-source reconciliation | Data inconsistencies | NBA.com vs BDL differences |
| Trend alerting | Gradual degradation | Quality slowly declining over weeks |
| Real-time alerts | Delayed response | 6 AM summary is too late for overnight issues |
| Schema drift | Missing columns | New fields not being populated |
| Service deployment errors | Import failures | ModuleNotFoundError not caught |

---

## Improvement Areas

### Area 1: Phase 0.5 Checks (Orchestrator Health)
**File**: `01-PHASE-ZERO-POINT-FIVE.md`

Add pre-validation checks to `/validate-daily` that detect:
- Missing phase execution logs
- Stalled orchestrators (started but not completed)
- Phase transition timing gaps
- Service deployment errors

### Area 2: Calculation Verification (Golden Dataset)
**File**: `02-GOLDEN-DATASET.md`

Create a small set of manually-verified player-dates to compare against:
- Verify rolling average calculations
- Catch silent calculation bugs
- Alert on >2% deviation

### Area 3: Cross-Source Reconciliation
**File**: `03-CROSS-SOURCE-RECONCILIATION.md`

Daily comparison between data sources:
- NBA.com vs BDL stats
- Flag significant differences (>2 points)
- Track source preference decisions

### Area 4: Trend Alerting
**File**: `04-TREND-ALERTING.md`

Monitor quality metrics over time:
- 7-day rolling quality trends
- Alert on declining coverage
- Detect gradual degradation

### Area 5: Service Error Centralization
**File**: `05-SERVICE-ERRORS-TABLE.md`

Centralized error logging:
- All Cloud Run/Function errors in BigQuery
- Pattern detection (same error recurring)
- Severity classification

### Area 6: Pipeline Health Dashboard
**File**: `06-PIPELINE-HEALTH-VIEW.md`

Single view showing:
- Last successful run per phase/processor
- Failures in last 24h
- Health status (HEALTHY/DEGRADED/UNHEALTHY/STALE)

---

## Implementation Priority

| Priority | Area | Effort | Impact |
|----------|------|--------|--------|
| P1 | Phase 0.5 Checks | 3-4h | Would have caught Jan 25-28 stall |
| P1 | Pipeline Health View | 4-6h | Single source of truth for health |
| P1 | Service Errors Table | 8-10h | Centralized debugging |
| P2 | Golden Dataset | 6-8h | Catches calculation bugs |
| P2 | Cross-Source Reconciliation | 4-6h | Data consistency |
| P3 | Trend Alerting | 4-6h | Long-term quality monitoring |

---

## Files in This Project

```
validation-coverage-improvements/
├── README.md                          # This file
├── 01-PHASE-ZERO-POINT-FIVE.md       # Orchestrator health checks
├── 02-GOLDEN-DATASET.md              # Calculation verification
├── 03-CROSS-SOURCE-RECONCILIATION.md # Source comparison
├── 04-TREND-ALERTING.md              # Quality trends
├── 05-SERVICE-ERRORS-TABLE.md        # Error centralization
├── 06-PIPELINE-HEALTH-VIEW.md        # Health dashboard
└── IMPLEMENTATION-LOG.md             # Progress tracking
```

---

## Success Criteria

After implementing these improvements:

1. **Detection Time**: Orchestrator stalls detected within 30 minutes (not 2 days)
2. **Calculation Confidence**: Golden dataset validates accuracy daily
3. **Source Consistency**: Cross-source differences flagged automatically
4. **Trend Visibility**: Quality trends visible in dashboard
5. **Error Traceability**: All service errors queryable in BigQuery
