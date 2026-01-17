# MLB Feature Parity Project

**Created**: 2026-01-16
**Status**: In Progress
**Priority**: HIGH - Complete before Opening Day (March 2026)

## Overview

This project brings MLB infrastructure to feature parity with NBA. Session 69 confirmed MLB is "100% production-ready" for predictions, but the supporting infrastructure (monitoring, validation, publishing, alerting) is significantly behind NBA.

## Gap Summary

| Category | NBA | MLB | Gap |
|----------|-----|-----|-----|
| **Publishing/Exporters** | 22 exporters | 0 | Missing all consumer-facing exports |
| **Monitoring Systems** | 15+ modules | 1 script | Missing gap detection, freshness, stall detection |
| **Validation Framework** | 7+ validators | 0 production | Missing data quality validation |
| **Alert Manager Integration** | Full | Unknown | Need to verify/integrate |

## Priority Order

### P0: Monitoring (Week 1)
Without monitoring, we can't know if the pipeline is healthy. Critical for production.

### P1: Validation (Week 2)
Catches data quality issues before they affect predictions.

### P2: Publishing (Week 3)
Makes predictions consumable by APIs/websites.

### P3: Alert Integration (Week 4)
Ensures alerts are rate-limited and properly routed.

## Documents

| Document | Purpose |
|----------|---------|
| [GAP-ANALYSIS.md](./GAP-ANALYSIS.md) | Detailed comparison of NBA vs MLB features |
| [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md) | Step-by-step implementation guide |
| [MONITORING-SPEC.md](./MONITORING-SPEC.md) | Monitoring system specifications |
| [PUBLISHING-SPEC.md](./PUBLISHING-SPEC.md) | Publishing/exporter specifications |
| [VALIDATION-SPEC.md](./VALIDATION-SPEC.md) | Validation framework specifications |

## Success Criteria

1. MLB has equivalent monitoring coverage to NBA
2. MLB has data validation running daily
3. MLB predictions exported to GCS for API consumption
4. MLB alerts properly rate-limited during backfills
5. All systems tested with historical data before Opening Day

## Related Projects

- `mlb-pitcher-strikeouts/` - Core MLB prediction system
- `mlb-e2e-testing/` - End-to-end testing infrastructure
- `monitoring-improvements/` - General monitoring enhancements
