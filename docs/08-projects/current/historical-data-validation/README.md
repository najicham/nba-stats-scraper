# Historical Data Validation Project

**Created:** 2026-01-23
**Status:** Active
**Priority:** P1 - Data Quality

## Overview

This project tracks validation of historical NBA data across all seasons (2021-2026) to ensure data accuracy, identify gaps, and implement resilience improvements.

## Quick Links

- [Validation Findings](./VALIDATION-FINDINGS.md) - Comprehensive audit results
- [Resilience Improvements](./RESILIENCE-IMPROVEMENTS.md) - System hardening plans
- [Line Source Improvement](./LINE-SOURCE-IMPROVEMENT.md) - Sportsbook-priority fallback (IMPLEMENTED)
- [Backfill Strategy](./BACKFILL-STRATEGY.md) - Comprehensive backfill plan
- [Backfill Tracker](./BACKFILL-TRACKER.md) - Status of backfill operations

## Season Coverage Summary

| Season | Analytics | Predictions | Grading | Odds API | BettingPros | Coverage % |
|--------|-----------|-------------|---------|----------|-------------|------------|
| 2021-22 | 213 dates | 199 dates | 199 dates | 0 dates | **213 dates** | 93.4% |
| 2022-23 | 212 dates | 198 dates | 198 dates | 27 dates | **212 dates** | 93.4% |
| 2023-24 | 207 dates | 193 dates | 193 dates | 207 dates | 197 dates | 93.2% |
| 2024-25 | 213 dates | 199 dates | 199 dates | 213 dates | 213 dates | 93.4% |
| 2025-26 | 89 dates | 87 dates | 56 dates | 89 dates | 29 dates | 97.8% |

## Key Findings

### 1. Bootstrap Gap Pattern (All Seasons)

Every season has ~14 days missing at the start:
- 2021-22: Oct 19 - Nov 1 (14 dates)
- 2022-23: Oct 18 - Oct 31 (14 dates)
- 2023-24: Oct 24 - Nov 6 (14 dates)
- 2024-25: Oct 22 - Nov 4 (14 dates)

**Root Cause:** Prediction system requires historical game data to compute rolling averages.

### 2. Betting Line Data Availability

| Season | Odds API | BettingPros | Current Status |
|--------|----------|-------------|----------------|
| 2021-22 | No data | **Full (213 dates, DK/FD)** | Using estimates - should use BP! |
| 2022-23 | Playoffs only | **Full (212 dates, DK/FD)** | Using estimates - should use BP! |
| 2023-24+ | Full | Full | Using Odds API correctly |

**Key Discovery:** BettingPros has DraftKings and FanDuel lines for ALL historical seasons.
Current system doesn't use them because it only falls back to BettingPros when Odds API
has no data at all. See [Line Source Improvement](./LINE-SOURCE-IMPROVEMENT.md).

### 3. Grading Accuracy Trend

| Season | Accuracy | Model Version |
|--------|----------|---------------|
| 2021-22 | 16.4% | Legacy |
| 2022-23 | 16.7% | Legacy |
| 2023-24 | 17.8% | Legacy |
| 2024-25 | 21.0% | Transitional |
| 2025-26 | 57.5% | CatBoost V8 |

**Insight:** Major model improvement deployed in late 2025.

## Action Items

### Completed
- [x] **P1**: Implement sportsbook-priority fallback (DK/FD from any source)
- [x] **P1**: Create comprehensive backfill strategy documentation
- [x] **P0**: Eliminate ESTIMATED_AVG lines (see [No Estimated Lines Implementation](../../../09-handoff/2026-01-23-NO-ESTIMATED-LINES-IMPLEMENTATION.md))
- [x] **P0**: Delete ESTIMATED_AVG from grading table (49,522 rows removed)
- [x] **P1**: Deploy code changes to Cloud Run (revision 00086-pzl)

### In Progress
- [ ] **P1**: Run backfill for 2024-25 season (213 dates)
- [ ] **P1**: Backfill bootstrap gap predictions (Oct-Nov 2024)

### Pending
- [ ] **P2**: Backfill 2023-24 season (207 dates)
- [ ] **P2**: Add automated season-start bootstrap detection
- [ ] **P2**: Create daily validation job with alerting
- [ ] **P2**: Optional: Add MAE-only grading for NO_PROP_LINE predictions
- [ ] **P3**: Backfill 2022-23 season (212 dates)
- [ ] **P3**: Backfill 2021-22 season (213 dates)
- [ ] **P3**: Implement self-healing for prediction gaps

## Related Documentation

- [Backfill Guide](../../../02-operations/backfill/backfill-guide.md)
- [Scrapers Reference](../../../06-reference/scrapers.md)
- [Validation Findings Handoff](../../../09-handoff/2026-01-23-HISTORICAL-DATA-VALIDATION-FINDINGS.md)
