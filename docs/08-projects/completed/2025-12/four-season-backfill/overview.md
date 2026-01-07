# Four-Season Historical Backfill Project

**Status:** In Progress - Phase 5 Backfill
**Created:** 2025-12-11
**Last Updated:** 2025-12-14

---

## Objective

Backfill all prediction pipeline phases for the past 4 NBA seasons (2021-22 through 2024-25) to:
1. Build historical prediction accuracy data for model evaluation
2. Enable ML feedback loop improvements based on historical performance
3. Prepare for daily production orchestration

---

## Current Data Coverage (Updated 2025-12-14)

### Phase 1/2: Raw Box Scores (bdl_player_boxscores) - COMPLETE ✅
| Season | Game Dates | Status |
|--------|------------|--------|
| 2021-22 | 167 dates | ✅ Complete |
| 2022-23 | 168 dates | ✅ Complete |
| 2023-24 | 160 dates | ✅ Complete |
| 2024-25 | 164 dates | ✅ Complete |

### Phase 3: Analytics Tables - COMPLETE ✅

| Table | 2021-22 | 2022-23 | 2023-24 | 2024-25 | Status |
|-------|---------|---------|---------|---------|--------|
| player_game_summary | 168 | 167 | 160 | 213 | ✅ Complete |
| team_defense_game_summary | 215 | 214 | 209 | 164 | ✅ Complete |
| team_offense_game_summary | 215 | 214 | 209 | 164 | ✅ Complete |
| upcoming_team_game_context | 74 | 214 | 162 | - | ✅ Complete |

### Phase 4: Precompute Tables - COMPLETE ✅

| Processor | Dates | Rows | Status |
|-----------|-------|------|--------|
| TDZA (Team Defense Zone Analysis) | 520 | 15,339 | ✅ Complete |
| PSZA (Player Shot Zone Analysis) | 536 | 218,017 | ✅ Complete |
| PCF (Player Composite Factors) | 495 | 101,184 | ✅ Complete |
| PDC (Player Daily Cache) | 459 | 58,614 | ✅ Complete |
| MLFS (ML Feature Store) | 453 | 75,688 | ✅ Complete |

### Phase 5/6 Coverage - IN PROGRESS
| Season | Phase 5A (Predictions) | Phase 5B (Grading) | Phase 6 (Publishing) |
|--------|------------------------|--------------------|--------------------|
| 2021-22 | 61 dates | 61 dates | 62 dates |
| 2022-23 | 0 dates | 0 dates | 0 dates |
| 2023-24 | 0 dates | 0 dates | 0 dates |
| 2024-25 | 0 dates | 0 dates | 0 dates |

**Current Task:** Run Phase 5A/5B backfills for 2021-2024 seasons.

---

## Documents

- **EXECUTION-PLAN.md** - Detailed step-by-step execution plan with commands
- **VALIDATION-CHECKLIST.md** - Queries and scripts to validate each phase
- **PROGRESS-LOG.md** - Track progress during execution

---

## High-Level Plan

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PHASE 3/4 BACKFILL - COMPLETE ✅                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  PHASE 5A PREDICTIONS BACKFILL ← CURRENT                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  Run predictions for all dates with MLFS data                               │
│  Date range: 2021-11-02 to 2024-04-14 (~450 dates)                         │
│  Features: 5 prediction systems, tier adjustments, batch loading            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       PHASE 5B GRADING BACKFILL                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Grade all predictions against actual results                               │
│  Compute MAE, bias, recommendation accuracy                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PHASE 6 PUBLISHING                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  Export all results to GCS as JSON for website                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Success Criteria

- [x] Phase 3 analytics tables complete for all seasons
- [x] Phase 4 MLFS data exists for all game dates (453 dates)
- [x] Data quality validated - Grade A (no duplicates, no errors)
- [ ] Phase 5A predictions exist for all dates (5 systems per date)
- [ ] Phase 5B grading complete for all predictions
- [ ] Overall MAE < 5.0 points
- [ ] Tier adjustments validated (improving MAE, not hurting)
- [ ] Phase 6 JSON exports available for all dates
- [ ] Daily orchestration ready to take over

---

## Related Documentation

- `docs/02-operations/backfill/backfill-guide.md` - General backfill guide
- `docs/02-operations/backfill/backfill-validation-checklist.md` - **Comprehensive validation, failure analysis, troubleshooting**
- `docs/02-operations/backfill/runbooks/phase4-precompute-backfill.md` - Phase 4 runbook
- `docs/08-projects/current/phase-5c-ml-feedback/` - ML feedback loop docs

---

## Issues Discovered & Lessons Learned

### Issue 1: Phase 3 Analytics Tables Have Major Gaps (2025-12-11)

**Discovery:** While preparing for Phase 4 backfill, validation revealed that Phase 3 analytics tables have significant gaps:

1. **player_game_summary**: Only 70-74% complete for 2021-24 seasons
   - Gap periods: Mid-season onwards (Jan-Apr for each season)
   - Impact: ALL Phase 4 processors depend on this table

2. **upcoming_player_game_context / upcoming_team_game_context**: 0% coverage for 2022-23 and 2023-24
   - Impact: player_composite_factors (PCF) processor will fail without this data
   - Root cause: These tables track "upcoming" games - may not be designed for historical backfill

3. **team_defense_game_summary**: 2024-25 season only 40% complete (66/164 dates)

**Lesson:** Always run `bin/backfill/verify_phase3_for_phase4.py` BEFORE starting Phase 4 backfills.

**Resolution:** Running Phase 3 backfills first:
```bash
# player_game_summary backfill (run for each season with gaps)
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-01-08 --end-date 2022-04-15  # 2021-22 gaps
```

### Issue 2: Original Handoff Understated Data Gaps

**Discovery:** The Session 124 handoff document listed Phase 3 dates as complete (117, 117, 119 dates) without noting these were partial compared to actual game dates (167, 168, 160).

**Lesson:** When documenting data state, always compare against the source of truth (raw box scores) to identify coverage percentage, not just absolute numbers.

### Validation Query to Prevent This in Future

```sql
-- Compare Phase 3 analytics coverage against raw data
WITH box AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2021-10-01' AND '2022-04-15' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-01' AND '2023-04-15' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-01' AND '2024-04-15' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-01' AND '2025-04-15' THEN '2024-25'
    END as season,
    COUNT(DISTINCT game_date) as raw_dates
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= '2021-10-01' AND game_date <= '2025-04-15'
  GROUP BY 1
),
pgs AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2021-10-01' AND '2022-04-15' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-01' AND '2023-04-15' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-01' AND '2024-04-15' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-01' AND '2025-04-15' THEN '2024-25'
    END as season,
    COUNT(DISTINCT game_date) as pgs_dates
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01' AND game_date <= '2025-04-15'
  GROUP BY 1
)
SELECT
  b.season,
  b.raw_dates,
  COALESCE(p.pgs_dates, 0) as pgs_dates,
  b.raw_dates - COALESCE(p.pgs_dates, 0) as gap,
  ROUND(100.0 * COALESCE(p.pgs_dates, 0) / b.raw_dates, 1) as pct_complete
FROM box b
LEFT JOIN pgs p ON b.season = p.season
WHERE b.season IS NOT NULL
ORDER BY b.season
```
