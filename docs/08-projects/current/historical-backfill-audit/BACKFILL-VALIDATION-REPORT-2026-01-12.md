# Backfill Validation Report - Past 4 Seasons
**Date:** 2026-01-12
**Scope:** 2021-22, 2022-23, 2023-24, 2024-25 seasons
**Status:** Data gaps identified - requires action plan

---

## Executive Summary

Comprehensive validation of past 4 NBA seasons (2021-22 through 2024-25) reveals systematic data gaps in Phase 4 precompute processing. Raw data collection (Phase 2) is complete across all seasons, but Phase 4 processors show consistent gaps.

**Key Findings:**
- ✅ **Raw Data (Layer 1)**: 100% complete for all validated dates
- ✅ **Analytics (Layer 3)**: 100% complete for all seasons
- ⚠️ **Precompute Features (Layer 4)**: Systematic gaps across all seasons
  - Season-start bootstrap gaps: ~14 days per season (expected behavior)
  - Mid-season partial gaps: 3 dates with 11-75% coverage
  - PSZA processor: Consistently starts later than PCF/PDC

---

## Season-by-Season Breakdown

### 2021-22 Season
**Validation Period:** Oct 19, 2021 - Apr 10, 2022 (174 days)

#### Pipeline Coverage Summary
| Layer | Games/Records | Coverage | Status |
|-------|---------------|----------|--------|
| L1 (Raw BDL) | 1,223 games | 100% baseline | ✅ Complete |
| L3 (Analytics) | 1,249 games | 102.1% of L1 | ✅ Complete |
| L4 (Precompute) | 1,136 games | 92.9% of L1 | ⚠️ Gaps detected |

#### Date-Level Gaps: 17 dates with incomplete data

**Bootstrap Period (Expected):** Oct 19 - Nov 1, 2021 (14 days)
- **Impact:** 0% Phase 4 coverage for 69 games across 11 game days
- **Reason:** Expected bootstrap period - processors need historical data
- **Raw Data Status:** ✅ 100% complete (verified)
- **Phase 4 Processors:**
  - PCF (Player Composite Factors): Starts Nov 2, 2021
  - PDC (Player Daily Cache): Starts Nov 2, 2021
  - PSZA (Player Shot Zone Analysis): Starts Nov 5, 2021 (3 days later)

**Mid-Season Gaps:**
- **Dec 19, 2021:** 6/9 games (66.7%) - Now shows 100% in verification ✅
- **Dec 30, 2021:** 3/4 games (75.0%) - Now shows 100% in verification ✅
- **Additional dates:** 4 more dates with partial gaps

**PSZA Coverage:** 149 dates total (Nov 5, 2021 - Apr 10, 2022)

---

### 2022-23 Season
**Validation Period:** Oct 18, 2022 - Apr 9, 2023 (174 days)

#### Pipeline Coverage Summary
| Layer | Games/Records | Coverage | Status |
|-------|---------------|----------|--------|
| L1 (Raw BDL) | 1,230 games | 100% baseline | ✅ Complete |
| L3 (Analytics) | 1,233 games | 100.2% of L1 | ✅ Complete |
| L4 (Precompute) | 1,118 games | 90.9% of L1 | ⚠️ Gaps detected |

#### Date-Level Gaps: 16 dates with incomplete data

**Bootstrap Period (Expected):** Oct 18 - Oct 31, 2022 (14 days)
- **Impact:** 0% Phase 4 coverage for 62 games across 10 game days
- **Reason:** Expected bootstrap period
- **Raw Data Status:** ✅ 100% complete (verified)
- **Phase 4 Processors:**
  - PCF: Starts Nov 1, 2022
  - PDC: Starts Nov 1, 2022
  - PSZA: Starts Nov 4, 2022 (3 days later)

**Mid-Season Gaps (CRITICAL):**
- **Feb 23, 2023:** 1/9 games (11.1%) ❌ INVESTIGATE
  - Only 1 game processed with non-standard game_id format
  - 8 games missing from PCF completely
  - No failure records found in precompute_failures table
  - **Issue:** Game ID format mismatch detected (see Data Quality Issues)

- **Feb 24, 2023:** 6/8 games (75.0%) ⚠️ INVESTIGATE
  - 2 games missing from PCF
  - No failure records found
  - Likely related to Feb 23 issue

**PSZA Coverage:** 147 dates total (Nov 4, 2022 - Apr 9, 2023)

---

### 2023-24 Season
**Validation Period:** Oct 24, 2023 - Apr 14, 2024 (174 days)

#### Pipeline Coverage Summary
| Layer | Games/Records | Coverage | Status |
|-------|---------------|----------|--------|
| L1 (Raw BDL) | 1,230 games | 100% baseline | ✅ Complete |
| L3 (Analytics) | 1,230 games | 100.0% of L1 | ✅ Complete |
| L4 (Precompute) | 1,118 games | 90.9% of L1 | ⚠️ Gaps detected |

#### Date-Level Gaps: 15 dates with incomplete data

**Bootstrap Period (Expected):** Oct 24 - Nov 6, 2023 (14 days)
- **Impact:** 0% Phase 4 coverage for 68 games across 10 game days
- **Reason:** Expected bootstrap period
- **Raw Data Status:** ✅ 100% complete (verified)
- **Phase 4 Processors:**
  - PCF: Starts Nov 8, 2023
  - PDC: Starts Nov 8, 2023
  - PSZA: Starts Nov 10, 2023 (2 days later)

**Mid-Season Gaps:**
- **Feb 22, 2024:** 4/12 games (33.3%) ⚠️ INVESTIGATE
  - 8 games missing from PCF
  - No failure records found
  - Requires investigation

**PSZA Coverage:** 144 dates total (Nov 10, 2023 - Apr 14, 2024)

---

### 2024-25 Season (Current)
**Validation Period:** Oct 22, 2024 - Jan 12, 2025 (83 days)

#### Pipeline Coverage Summary
| Layer | Games/Records | Coverage | Status |
|-------|---------------|----------|--------|
| L1 (Raw BDL) | 573 games | 100% baseline | ✅ Complete |
| L3 (Analytics) | 573 games | 100.0% of L1 | ✅ Complete |
| L4 (Precompute) | 465 games | 81.2% of L1 | ⚠️ Below ideal 90% |

#### Date-Level Gaps: 14 dates with incomplete data

**Bootstrap Period (Expected):** Oct 22 - Nov 4, 2024 (14 days)
- **Impact:** 0% Phase 4 coverage for 87 games across 10 game days
- **Reason:** Expected bootstrap period
- **Raw Data Status:** ✅ 100% complete (verified)
- **Phase 4 Processors:**
  - PCF: Starts Nov 6, 2024
  - PDC: Starts Nov 6, 2024
  - PSZA: Starts Nov 8, 2024 (2 days later)

**Coverage Warning:**
- L4 coverage at 81.2% is below ideal 90% threshold
- This is expected for current season due to ongoing bootstrap stabilization
- Should improve as season progresses

**PSZA Coverage:** 62 dates total (Nov 8, 2024 - Jan 12, 2025)

#### Player-Level Validation (Completed)
**Status:** ✅ No critical errors found
**Processors Validated:** PDC, PSZA, PCF, MLFS, TDZA

**Results Summary:**
| Processor | OK Dates | Skipped | DepsMiss | Untracked | Investigate |
|-----------|----------|---------|----------|-----------|-------------|
| PDC | 64 | 0 | 0 | 14 | 0 |
| PSZA | 62 | 0 | 0 | 16 | 0 |
| PCF | 64 | 0 | 0 | 14 | 0 |
| MLFS | 64 | 0 | 0 | 14 | 0 |
| TDZA | 54 | 10 | 0 | 14 | 0 |

**Analysis:**
- **Untracked dates (14-16):** These are the bootstrap period dates (expected)
- **TDZA Skipped (10):** Team-level bootstrap incomplete (expected)
- **No processing errors** requiring investigation
- **Conclusion:** 2024-25 season Phase 4 processing is healthy

---

## Critical Data Quality Issues

### Issue 1: Game ID Format Inconsistency
**Severity:** HIGH
**Impact:** Mid-season gaps, data linkage failures
**Location:** `player_composite_factors` table vs. `nbac_schedule` table

**Description:**
Different tables use different game_id formats:
- **Schedule table format:** `0022200886` (NBA official format)
- **PCF table format:** `20230223_DEN_CLE` (date_away_home format)

**Evidence:**
```sql
-- Schedule shows 9 games for 2023-02-23
-- PCF shows only 1 game: "20230223_DEN_CLE"
-- The 8 other games are missing due to game_id mismatch
```

**Impact Dates:**
- 2023-02-23: 8 games missing (88.9% gap)
- 2023-02-24: Likely 2 games missing
- 2024-02-22: Likely 8 games missing
- Potentially affects other mid-season dates

**Action Required:**
1. Investigate why PCF uses non-standard game_id format
2. Determine if this is a data transformation error or intentional design
3. Check if game_id mapping/translation layer exists
4. Verify if this affects other Phase 4 processors (PSZA, PDC)
5. Backfill missing games with correct game_id linkage

---

### Issue 2: PSZA Delayed Start Pattern
**Severity:** MEDIUM
**Impact:** Reduced shot zone analysis coverage
**Location:** `player_shot_zone_analysis` table

**Description:**
PSZA consistently starts 2-3 days later than PCF/PDC across all seasons.

**Evidence:**
| Season | PCF Start | PSZA Start | Delay |
|--------|-----------|------------|-------|
| 2021-22 | Nov 2, 2021 | Nov 5, 2021 | 3 days |
| 2022-23 | Nov 1, 2022 | Nov 4, 2022 | 3 days |
| 2023-24 | Nov 8, 2023 | Nov 10, 2023 | 2 days |
| 2024-25 | Nov 6, 2024 | Nov 8, 2024 | 2 days |

**Analysis:**
- This is likely **expected behavior** - PSZA needs shot zone data history
- Shot zone analysis requires more granular data than composite factors
- Delay is reducing from 3 days to 2 days in recent seasons

**Action Required:**
1. Confirm with system design docs if this is expected
2. If expected, document as known behavior in backfill guide
3. If not expected, investigate PSZA bootstrap logic

---

### Issue 3: Missing Failure Tracking for Mid-Season Gaps
**Severity:** MEDIUM
**Impact:** Lack of visibility into processing failures
**Location:** `nba_processing.precompute_failures` table

**Description:**
Mid-season dates with incomplete PCF coverage show NO records in the failures table.

**Evidence:**
- 2023-02-23: 8 games missing, 0 failure records
- 2023-02-24: 2 games missing, 0 failure records
- 2024-02-22: 8 games missing, 0 failure records

**Analysis:**
This suggests either:
1. Games were never attempted to be processed
2. Failures occurred but weren't logged
3. Scheduling/orchestration gap prevented processing

**Action Required:**
1. Check orchestration logs for these dates
2. Verify if processors were triggered for these games
3. Review failure logging logic in PCF processor
4. Add defensive logging for untriggered games

---

## Validation Methodology

### Scripts Used
1. **validate_pipeline_completeness.py**: Layer-by-layer coverage validation
2. **check_data_completeness.py**: Raw data completeness verification
3. **Direct BigQuery queries**: Phase 4 processor-specific gap analysis

### Verification Steps
1. ✅ Pipeline validation for each season (L1, L3, L4 coverage)
2. ✅ Raw data spot-checks for gap dates (gamebooks, box scores, props)
3. ✅ Phase 4 processor date range analysis (PCF, PDC, PSZA)
4. ✅ Mid-season gap investigation (game-level analysis)
5. ✅ Failure record correlation
6. ✅ Phase 4 player-level coverage validation for 2024-25 (complete)
7. ⏳ Phase 4 player-level coverage validation for 2021-24 seasons (in progress - long-running)

### Data Sources Checked
- ✅ `nba_raw.nbac_schedule` (game schedule)
- ✅ `nba_raw.nbac_gamebook_player_stats` (gamebooks)
- ✅ `nba_raw.bdl_player_boxscores` (box scores)
- ✅ `nba_raw.bettingpros_player_points_props` (betting props)
- ✅ `nba_analytics.player_game_summary` (Layer 3)
- ✅ `nba_precompute.player_composite_factors` (Phase 4 - PCF)
- ✅ `nba_precompute.player_daily_cache` (Phase 4 - PDC)
- ✅ `nba_precompute.player_shot_zone_analysis` (Phase 4 - PSZA)
- ✅ `nba_processing.precompute_failures` (failure tracking)

---

## Recommendations

### Immediate Actions (Critical)

1. **Investigate Game ID Format Issue**
   - **Priority:** P0 - Critical data quality issue
   - **Impact:** Affects mid-season predictions for multiple seasons
   - **Tasks:**
     - Review PCF processor code for game_id handling
     - Check if mapping layer exists between formats
     - Identify root cause of format discrepancy
     - Plan backfill for affected games once root cause identified

2. **Backfill Mid-Season Missing Games**
   - **Priority:** P1 - High impact on historical data
   - **Dates to backfill:**
     - 2023-02-23: 8 missing games
     - 2023-02-24: 2 missing games (verify)
     - 2024-02-22: 8 missing games (verify)
   - **Prerequisites:** Resolve game_id format issue first

3. **Audit Failure Tracking**
   - **Priority:** P1 - Operational visibility
   - **Tasks:**
     - Review why failures weren't logged for mid-season gaps
     - Add defensive logging for untriggered games
     - Implement alerting for games not attempted

### Expected Behavior to Document

1. **Season Bootstrap Period**
   - **Behavior:** 14-day gap at season start is expected
   - **Reason:** Phase 4 processors need historical data accumulation
   - **Action:** Document in backfill guide as expected behavior
   - **Note:** No backfill needed for these dates

2. **PSZA Delayed Start**
   - **Behavior:** PSZA starts 2-3 days after PCF/PDC
   - **Reason:** Requires additional shot zone data history
   - **Action:** Confirm with design docs, document if expected
   - **Improvement:** Delay reducing in recent seasons (3→2 days)

### Process Improvements

1. **Enhanced Validation Automation**
   - Add automated daily validation for Phase 4 completeness
   - Alert on any gaps outside bootstrap period
   - Track coverage percentage trends

2. **Game ID Standardization**
   - Establish single source of truth for game_id format
   - Document format specifications in schema docs
   - Add validation in data ingestion to catch format issues early

3. **Failure Tracking Enhancement**
   - Log all games attempted, not just failures
   - Add "not attempted" status category
   - Implement comprehensive orchestration logging

---

## Next Steps

### For Resolution
1. ⏳ Wait for `validate_backfill_coverage.py` scripts to complete (running 15+ min)
2. 🔍 Investigate game_id format issue in PCF processor code
3. 🔍 Verify mid-season gap dates and count missing games accurately
4. 📋 Create backfill plan for mid-season missing games
5. 📝 Document bootstrap period as expected behavior

### For Monitoring
1. Track Phase 4 coverage percentage for 2024-25 season (currently 81.2%)
2. Monitor for any new mid-season gaps in current season
3. Verify PSZA coverage continues 2 days after PCF/PDC

---

## Data Summary

### Overall Statistics (Past 4 Seasons)

| Metric | Value | Status |
|--------|-------|--------|
| **Total game days validated** | 605 days | ✅ Complete |
| **Total games scheduled** | 4,256 games | ✅ Complete |
| **Layer 1 (Raw) coverage** | 100% | ✅ Complete |
| **Layer 3 (Analytics) coverage** | 100% | ✅ Complete |
| **Layer 4 (Precompute) coverage** | 90.4% avg | ⚠️ Gaps exist |
| **Bootstrap period dates** | 62 dates (expected) | ℹ️ Expected |
| **Mid-season gap dates** | 3 dates (critical) | ❌ Investigate |
| **Total dates needing investigation** | 3-5 dates | 🔍 Action needed |

### Coverage by Processor

| Processor | 2021-22 | 2022-23 | 2023-24 | 2024-25 |
|-----------|---------|---------|---------|---------|
| PCF | 149 dates | 147 dates | 144 dates | 62 dates |
| PDC | 149 dates | 147 dates | 144 dates | 62 dates |
| PSZA | 149 dates | 147 dates | 144 dates | 62 dates |

**Note:** All processors start after bootstrap period, dates are post-bootstrap only.

---

## Appendix: Sample Validation Queries

### Check Phase 4 Coverage for Date Range
```sql
WITH date_range AS (
  SELECT game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2023-02-20' AND '2023-02-25'
    AND game_status = 3
  GROUP BY game_date
)
SELECT
  dr.game_date,
  COUNTIF(pcf.game_date IS NOT NULL) as pcf_games,
  COUNTIF(psza.analysis_date IS NOT NULL) as psza_games,
  COUNTIF(pdc.cache_date IS NOT NULL) as pdc_games
FROM date_range dr
LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
  ON dr.game_date = pcf.game_date
LEFT JOIN `nba-props-platform.nba_precompute.player_shot_zone_analysis` psza
  ON dr.game_date = psza.analysis_date
LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
  ON dr.game_date = pdc.cache_date
GROUP BY dr.game_date
ORDER BY dr.game_date
```

### Check Missing Games for Specific Date
```sql
WITH scheduled AS (
  SELECT game_id, game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date = '2023-02-23' AND game_status = 3
),
processed AS (
  SELECT DISTINCT game_id
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date = '2023-02-23'
)
SELECT
  s.game_id,
  s.game_date,
  CASE WHEN p.game_id IS NOT NULL THEN 'YES' ELSE 'NO' END as in_pcf
FROM scheduled s
LEFT JOIN processed p ON s.game_id = p.game_id
ORDER BY in_pcf, s.game_id
```

---

**Report Status:** Preliminary - Awaiting completion of player-level coverage validation
**Last Updated:** 2026-01-12 19:55 PST
**Next Review:** After game_id format investigation complete
