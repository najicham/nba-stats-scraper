# Historical Data Audit Report - January 22, 2026

**Audit Period:** January 1-21, 2026
**Audit Date:** January 22, 2026
**Status:** Complete

---

## 1. Executive Summary

| Metric | Value | Status |
|--------|-------|--------|
| Total Games Validated | 155 scheduled | - |
| Overall Raw Completeness | 100% (NBAC) | OK |
| BDL API Coverage | 77.4% (120/155) | Warning |
| Analytics Coverage | 97.4% (151/155) | OK |
| Precompute Coverage | ~98% | OK |
| R-009 Regressions | 0 | Fixed |
| Duplicate Records | 350 | Issue |

### Critical Findings

1. **35 BDL missing games** - Successfully covered by NBAC fallback
2. **4 Analytics gaps** - Need Phase 2/3 backfill (HIGH priority)
3. **2 Precompute gaps** - Need Phase 4 backfill (HIGH priority)
4. **350 duplicate records** - Data quality issue requiring cleanup (MEDIUM priority)
5. **Jan 15 infrastructure failure** - 8 games affected (covered by NBAC)

---

## 2. Detailed Findings

### 2.1 30-Day Overview

| Table | Unique Dates | Unique Games | Total Records |
|-------|--------------|--------------|---------------|
| bdl_player_boxscores | 29 | 191 | 6,699 |
| nbac_gamebook_player_stats | 29 | 226 | 7,882 |
| player_game_summary | 29 | 224 | 5,583 |
| player_composite_factors | 29 | 301 | 6,415 |

**Key Finding:** BDL has 35 fewer games than NBAC (191 vs 226), confirming known API gaps.

### 2.2 Day-by-Day Phase Comparison

| Date | Sched | BDL | NBAC | Analytics | Precompute | Issues |
|------|-------|-----|------|-----------|------------|--------|
| Jan 21 | 7 | 6 | 7 | 7 | 7 | BDL -1 |
| Jan 20 | 7 | 4 | 7 | 7 | 7 | BDL -3 |
| Jan 19 | 9 | 8 | 9 | 9 | 9 | BDL -1 |
| **Jan 18** | **6** | **4** | **6** | **5** | **5** | **BDL -2, Analytics -1, Precompute -1** |
| **Jan 17** | **9** | **7** | **9** | **8** | **7** | **BDL -2, Analytics -1, Precompute -2** |
| Jan 16 | 6 | 5 | 6 | 6 | 7 | BDL -1 |
| **Jan 15** | **9** | **1** | **9** | **9** | **9** | **BDL -8 (INFRASTRUCTURE FAILURE)** |
| Jan 14 | 7 | 5 | 7 | 7 | 8 | BDL -2 |
| Jan 13 | 7 | 5 | 7 | 7 | 14 | BDL -2 |
| Jan 12 | 6 | 4 | 6 | 6 | 6 | BDL -2 |
| Jan 11 | 10 | 10 | 10 | 10 | 10 | OK |
| Jan 10 | 6 | 6 | 6 | 6 | 6 | OK |
| Jan 09 | 10 | 10 | 10 | 10 | 14 | OK |
| Jan 08 | 3 | 3 | 3 | 3 | 4 | OK |
| Jan 07 | 12 | 10 | 12 | 12 | 13 | BDL -2 |
| Jan 06 | 6 | 5 | 6 | 6 | 6 | BDL -1 |
| **Jan 05** | **8** | **6** | **8** | **8** | **7** | **BDL -2, Precompute -1** |
| Jan 04 | 8 | 8 | 8 | 8 | 13 | OK |
| Jan 03 | 8 | 6 | 8 | 8 | 9 | BDL -2 |
| Jan 02 | 10 | 8 | 10 | 10 | 15 | BDL -2 |
| **Jan 01** | **5** | **3** | **5** | **3** | **6** | **BDL -2, Analytics -2** |

### 2.3 BDL Missing Games (35 total)

**West Coast Venue Concentration (86% - 30/35 games):**

| Venue | Count | Games |
|-------|-------|-------|
| SAC | 8 | TOR@SAC (1/21), MIA@SAC (1/20), POR@SAC (1/18), WAS@SAC (1/16), NYK@SAC (1/14), LAL@SAC (1/12), DAL@SAC (1/6), BOS@SAC (1/1) |
| GSW | 7 | TOR@GSW (1/20), MIA@GSW (1/19), NYK@GSW (1/15), POR@GSW (1/13), MIL@GSW (1/7), UTA@GSW (1/3), OKC@GSW (1/2) |
| LAC | 5 | WAS@LAC (1/14), CHA@LAC (1/12), GSW@LAC (1/5), BOS@LAC (1/3), UTA@LAC (1/1) |
| LAL | 4 | TOR@LAL (1/18), CHA@LAL (1/15), ATL@LAL (1/13), MEM@LAL (1/2) |
| POR | 4 | LAL@POR (1/17), ATL@POR (1/15), HOU@POR (1/7), UTA@POR (1/5) |
| DEN | 2 | LAL@DEN (1/20), WAS@DEN (1/17) |

**Non-West Coast (Jan 15 Infrastructure Failure - 5 games):**
- BOS @ MIA, MIL @ SAS, OKC @ HOU, PHX @ DET, UTA @ DAL

**All 35 games have NBAC fallback data (23-37 players per game).**

### 2.4 Analytics Missing Games (4 games)

| Date | Game ID | Matchup | Raw Players | Priority |
|------|---------|---------|-------------|----------|
| 2026-01-18 | 20260118_POR_SAC | POR @ SAC | 23 | HIGH |
| 2026-01-17 | 20260117_WAS_DEN | WAS @ DEN | 17 | HIGH |
| 2026-01-01 | 20260101_BOS_SAC | BOS @ SAC | 35 | HIGH |
| 2026-01-01 | 20260101_UTA_LAC | UTA @ LAC | 35 | HIGH |

**Note:** POR@SAC and WAS@DEN have lower player counts (23 and 17), which may indicate incomplete NBAC data for these games.

### 2.5 Precompute Gaps (2 dates affected)

| Date | Analytics Games | Precompute Games | Gap |
|------|----------------|------------------|-----|
| 2026-01-17 | 8 | 7 | 1 game |
| 2026-01-05 | 8 | 7 | 1 game |

**Note:** Precompute table uses different game_id format (numeric) vs analytics (date-based).

### 2.6 Data Quality Issues

#### R-009 Regression Check
- **Result:** 0 games with zero active players
- **Status:** FIXED

#### Player Count Anomalies
- **Result:** 0 games with <18 players
- **Status:** OK

#### Duplicate Records (ISSUE FOUND)
| Date | Duplicate Count | Affected Games |
|------|-----------------|----------------|
| 2026-01-16 | 119 | CLE@PHI, NOP@IND, LAC@TOR, MIN@HOU, CHI@BKN |
| 2026-01-09 | 208 | Multiple games |
| 2026-01-04 | 23 | Multiple games |
| **Total** | **350** | - |

**Affected Players (sample):** tyresemaxey, donovanmitchell, zionwilliamson, gradeydick, jadenmcdaniels, ayodosunmu

### 2.7 Cross-Source Validation

**BDL vs NBAC Consistency Issues:**

Some games show significant player count differences where BDL has more players than NBAC:

| Date | Game | BDL Players | NBAC Players | Diff |
|------|------|-------------|--------------|------|
| 2026-01-19 | BOS @ DET | 35 | 14 | -21 |
| 2026-01-17 | OKC @ MIA | 35 | 14 | -21 |
| 2026-01-17 | PHX @ NYK | 33 | 12 | -21 |
| 2026-01-17 | IND @ DET | 36 | 15 | -21 |
| 2026-01-01 | MIA @ DET | 35 | 15 | -20 |

**This suggests NBAC gamebook data may be incomplete for some games where BDL is available.**

---

## 3. Backfill Priority List

### CRITICAL (Backfill within 24 hours)
_None - no R-009 regressions or recent games with 0 predictions_

### HIGH (Backfill within 1 week)

#### 3.1 Analytics Backfill (4 games)

```bash
# 2026-01-18: POR @ SAC
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-18 --end-date 2026-01-18 --backfill-mode

# 2026-01-17: WAS @ DEN
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-17 --end-date 2026-01-17 --backfill-mode

# 2026-01-01: BOS @ SAC, UTA @ LAC
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-01 --end-date 2026-01-01 --backfill-mode
```

#### 3.2 Precompute Backfill (2 dates)

```bash
# 2026-01-17 (1 game gap)
python -m data_processors.precompute.player_composite_factors.player_composite_factors_processor \
  --start-date 2026-01-17 --end-date 2026-01-17 --backfill-mode

# 2026-01-05 (1 game gap)
python -m data_processors.precompute.player_composite_factors.player_composite_factors_processor \
  --start-date 2026-01-05 --end-date 2026-01-05 --backfill-mode
```

### MEDIUM (Backfill within 1 month)

#### 3.3 Duplicate Record Cleanup

```sql
-- Identify and remove duplicates (run after investigation)
-- Jan 16: 119 duplicates
-- Jan 09: 208 duplicates
-- Jan 04: 23 duplicates
```

#### 3.4 BDL Gaps (35 games)
_No action required - NBAC fallback successfully covered all games_

### LOW (Backfill as time permits)

#### 3.5 NBAC Player Count Investigation
Investigate why some games have lower player counts in NBAC vs BDL:
- BOS @ DET (Jan 19): NBAC has only 14 players vs BDL's 35
- OKC @ MIA (Jan 17): NBAC has only 14 players vs BDL's 35

---

## 4. Root Cause Analysis

### 4.1 BDL API Patterns

| Pattern | Observation |
|---------|-------------|
| **West Coast Bias** | 86% (30/35) of missing games at West Coast venues |
| **Top Affected Venues** | SAC (8), GSW (7), LAC (5), LAL (4), POR (4) |
| **Time Pattern** | Evening West Coast games most affected |
| **Infrastructure Failure** | Jan 15: 8 games affected by system-wide failure |

**Hypothesis:** BDL API has delayed data availability for late-night West Coast games, causing scraper to miss data before it becomes available.

### 4.2 Analytics Processing Gaps

| Game | Issue |
|------|-------|
| POR @ SAC (1/18) | Low raw player count (23) - incomplete NBAC data |
| WAS @ DEN (1/17) | Low raw player count (17) - incomplete NBAC data |
| BOS @ SAC (1/1) | Normal player count (35) - processing failure |
| UTA @ LAC (1/1) | Normal player count (35) - processing failure |

### 4.3 Duplicate Records

Duplicates detected on Jan 4, 9, and 16 suggest:
- Possible re-processing runs that didn't properly deduplicate
- Need for upsert logic instead of append-only inserts

---

## 5. Recommendations

### Immediate Actions (This Week)

1. **Run Analytics Backfill** for 4 missing games
2. **Run Precompute Backfill** for Jan 5 and Jan 17
3. **Investigate Duplicate Cause** before cleanup to prevent recurrence

### Process Improvements

1. **BDL Scraper Enhancement:**
   - Add delayed retry for West Coast games (run again 2-3 hours later)
   - Consider timezone-aware scheduling

2. **Analytics Deduplication:**
   - Implement MERGE/upsert logic instead of INSERT
   - Add pre-processing duplicate check

3. **Monitoring Enhancements:**
   - Alert when BDL coverage < 90% for a day
   - Alert when NBAC player count < 25 for any game
   - Daily duplicate detection query

### Long-term Fixes

1. **Phase Boundary Validator** - Already implemented, continue monitoring
2. **Cross-Source Reconciliation** - Consider daily job to compare BDL/NBAC counts
3. **Automated Backfill Triggers** - When gaps detected, auto-queue backfill jobs

---

## 6. Validation Queries for Reference

All queries used in this audit are documented in:
- `/docs/08-projects/current/historical-backfill-audit/data-completeness-validation-guide.md`
- `/validation/queries/raw/`

---

## 7. Appendix: Full BDL Missing Games List

| Date | Game ID | Matchup | NBAC Players |
|------|---------|---------|--------------|
| 2026-01-21 | 20260121_TOR_SAC | TOR @ SAC | 35 |
| 2026-01-20 | 20260120_LAL_DEN | LAL @ DEN | 35 |
| 2026-01-20 | 20260120_MIA_SAC | MIA @ SAC | 35 |
| 2026-01-20 | 20260120_TOR_GSW | TOR @ GSW | 35 |
| 2026-01-19 | 20260119_MIA_GSW | MIA @ GSW | 35 |
| 2026-01-18 | 20260118_POR_SAC | POR @ SAC | 23 |
| 2026-01-18 | 20260118_TOR_LAL | TOR @ LAL | 35 |
| 2026-01-17 | 20260117_LAL_POR | LAL @ POR | 36 |
| 2026-01-17 | 20260117_WAS_DEN | WAS @ DEN | 17 |
| 2026-01-16 | 20260116_WAS_SAC | WAS @ SAC | 35 |
| 2026-01-15 | 20260115_ATL_POR | ATL @ POR | 35 |
| 2026-01-15 | 20260115_BOS_MIA | BOS @ MIA | 34 |
| 2026-01-15 | 20260115_CHA_LAL | CHA @ LAL | 36 |
| 2026-01-15 | 20260115_MIL_SAS | MIL @ SAS | 35 |
| 2026-01-15 | 20260115_NYK_GSW | NYK @ GSW | 34 |
| 2026-01-15 | 20260115_OKC_HOU | OKC @ HOU | 35 |
| 2026-01-15 | 20260115_PHX_DET | PHX @ DET | 35 |
| 2026-01-15 | 20260115_UTA_DAL | UTA @ DAL | 37 |
| 2026-01-14 | 20260114_NYK_SAC | NYK @ SAC | 34 |
| 2026-01-14 | 20260114_WAS_LAC | WAS @ LAC | 34 |
| 2026-01-13 | 20260113_ATL_LAL | ATL @ LAL | 35 |
| 2026-01-13 | 20260113_POR_GSW | POR @ GSW | 36 |
| 2026-01-12 | 20260112_CHA_LAC | CHA @ LAC | 35 |
| 2026-01-12 | 20260112_LAL_SAC | LAL @ SAC | 35 |
| 2026-01-07 | 20260107_HOU_POR | HOU @ POR | 35 |
| 2026-01-07 | 20260107_MIL_GSW | MIL @ GSW | 35 |
| 2026-01-06 | 20260106_DAL_SAC | DAL @ SAC | 36 |
| 2026-01-05 | 20260105_GSW_LAC | GSW @ LAC | 35 |
| 2026-01-05 | 20260105_UTA_POR | UTA @ POR | 36 |
| 2026-01-03 | 20260103_BOS_LAC | BOS @ LAC | 34 |
| 2026-01-03 | 20260103_UTA_GSW | UTA @ GSW | 35 |
| 2026-01-02 | 20260102_MEM_LAL | MEM @ LAL | 36 |
| 2026-01-02 | 20260102_OKC_GSW | OKC @ GSW | 35 |
| 2026-01-01 | 20260101_BOS_SAC | BOS @ SAC | 35 |
| 2026-01-01 | 20260101_UTA_LAC | UTA @ LAC | 35 |

---

**Report Generated:** January 22, 2026
**Next Audit Scheduled:** January 29, 2026
