# Phase 2 (Raw Data) Audit for 2025-26 Season

**Date:** January 22, 2026
**Season Range:** October 22, 2025 - January 22, 2026 (92 game dates)
**Purpose:** Track raw data coverage and gaps to plan Phase 3-5 backfills

---

## Executive Summary

| Source | Dates | Coverage | Status | Impact |
|--------|-------|----------|--------|--------|
| **Schedule** | 91 | 99% | ✅ Complete | - |
| **Game ID Mapping** | 91 | 99% | ✅ Complete | - |
| **BDL Player Boxscores** | 90 | 98% | ✅ Complete | Player stats available |
| **Team Boxscore (NBA.com)** | 27 | 29% | ❌ **CRITICAL** | Team offense/defense broken |
| **Gamebook Player Stats** | 42 | 46% | ⚠️ Gap | Some player stats missing |
| **BettingPros Props** | 29 | 32% | ⚠️ Gap | Only Dec 20+ |
| **NBA Injury Report** | 22 | 24% | ⚠️ Gap | Only Dec 22+ |
| **ESPN Boxscores** | 0 | 0% | ❌ Empty | Not used currently |
| **BDL Injuries** | 0 | 0% | ❌ Empty | Not used currently |

---

## Critical Gap: Team Boxscore (nbac_team_boxscore)

### Missing Dates: 65 dates (Oct 22 - Dec 25, 2025)

```
October 2025:   22 23 24 25 26 27 28 29 30 31         (10 dates)
November 2025:  01 02 03 04 05 06 07 08 09 10 11 12   (30 dates)
                13 14 15 16 17 18 19 20 21 22 23 24
                25 26 28 29 30
December 2025:  01 02 03 04 05 06 07 08 09 10 11 12   (25 dates)
                13 14 15 16 17 18 19 20 21 22 23 25
```

### Games to Backfill: 454 games

**Backfill file:** `backfill_jobs/scrapers/nbac_team_boxscore/game_ids_to_scrape.csv`

### Downstream Impact

When team boxscore is missing, these Phase 3+ tables are affected:

| Table | Field Affected | Current State |
|-------|----------------|---------------|
| `team_offense_game_summary` | All offensive stats | Populated from fallback |
| `team_defense_game_summary` | `opp_paint_attempts`, `opp_mid_range_attempts` | 29% zeros |
| `team_defense_zone_analysis` | Zone defense metrics | Incomplete |
| `player_composite_factors` | `opponent_strength_score` | **100% zeros** |
| `ml_feature_store_v2` | `opp_def_*` features | Bad values |

---

## Gap: Gamebook Player Stats (nbac_gamebook_player_stats)

### Missing Dates: 50 dates

```
October 2025:    22-31 (10 dates) - ALL MISSING
November 2025:   01-12 (12 dates) - MISSING
                 13-17 (5 dates)  - PRESENT
                 18-30 (13 dates) - MISSING
December 2025:   01-14 (14 dates) - MISSING
                 15-25 (10 dates) - PRESENT
```

### Mitigation

**BDL Player Boxscores has 90 dates** - can be used as fallback for player stats.

However, gamebook provides:
- DNP reasons (injury info)
- Starter/bench designation
- More detailed stats

### Games to Backfill

Need to generate list of missing game IDs for gamebook backfill.

---

## Complete Data Availability Matrix

| Date | Schedule | Team Box | Gamebook | BDL Box | Notes |
|------|----------|----------|----------|---------|-------|
| Oct 22-31 | ✅ | ❌ | ❌ | ✅ | Early season gap |
| Nov 01-12 | ✅ | ❌ | ❌ | ✅ | Gap continues |
| Nov 13-17 | ✅ | ❌ | ✅ | ✅ | Gamebook starts |
| Nov 18-30 | ✅ | ❌ | ❌ | ✅ | Gamebook gap |
| Dec 01-14 | ✅ | ❌ | ❌ | ✅ | Gamebook gap |
| Dec 15-25 | ✅ | ❌ | ✅ | ✅ | Gamebook resumes |
| Dec 26 | ✅ | ✅ (1 game) | ✅ | ✅ | Team box starts |
| Dec 27+ | ✅ | ✅ | ✅ | ✅ | **All sources available** |

---

## Backfill Priority Order

### Priority 1: Team Boxscore (CRITICAL)
- **Why:** Blocks team defense calculations, opponent strength scores
- **Games:** 454
- **Script:** `backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py`
- **Estimated time:** 30-45 minutes with 15 workers

### Priority 2: Gamebook Player Stats (MEDIUM)
- **Why:** Provides DNP reasons, detailed player data
- **Games:** ~350 (estimate)
- **Script:** `backfill_jobs/scrapers/nbac_gamebook_pdf/` (if exists)
- **Mitigation:** BDL boxscores available as fallback

### Priority 3: Injury Report (LOW)
- **Why:** Historical injury data useful but not blocking
- **Dates:** Oct 22 - Dec 21 (61 dates)
- **Note:** May not be retrievable for past dates

### Priority 4: BettingPros Props (LOW)
- **Why:** Historical odds useful for analysis but not blocking predictions
- **Dates:** Oct 22 - Dec 19 (59 dates)
- **Note:** May not be retrievable for past dates

---

## Phase 3-5 Reprocessing Plan

After raw data backfill is complete, these processors need to run:

### Phase 3 (Analytics) - Full Season Reprocess
```
Dates: Oct 22, 2025 - Jan 22, 2026 (all 92 dates)

Processors to run (in order):
1. TeamOffenseGameSummaryProcessor
2. TeamDefenseGameSummaryProcessor
3. PlayerGameSummaryProcessor
4. UpcomingTeamGameContextProcessor
5. UpcomingPlayerGameContextProcessor
```

### Phase 4 (Precompute) - Full Season Reprocess
```
Dates: Oct 22, 2025 - Jan 22, 2026 (all 92 dates)

Processors to run (in order):
1. TeamDefenseZoneAnalysisProcessor
2. PlayerShotZoneAnalysisProcessor
3. PlayerDailyCacheProcessor
4. PlayerCompositeFactorsProcessor
```

### Phase 5 (ML Features) - Full Season Reprocess
```
Dates: Oct 22, 2025 - Jan 22, 2026 (all 92 dates)

Processors to run:
1. MLFeatureStoreProcessor
```

---

## Validation After Backfill

Run these checks after each phase:

```bash
# After Phase 2 (Raw) backfill
bq query "SELECT COUNT(DISTINCT game_date) FROM nba_raw.nbac_team_boxscore WHERE game_date >= '2025-10-22'"
# Expected: 91+ dates

# After Phase 3 backfill
PYTHONPATH=. python scripts/validate_cascade_contamination.py \
  --start-date 2025-10-22 --end-date 2026-01-22 --stage phase3

# After Phase 4 backfill
PYTHONPATH=. python scripts/validate_cascade_contamination.py \
  --start-date 2025-10-22 --end-date 2026-01-22 --stage phase4

# After Phase 5 backfill
PYTHONPATH=. python bin/spot_check_features.py --date 2026-01-21 --count 20
```

---

## Tracking: What Was Backfilled

### Raw Data Backfills

| Date | Source | Games/Records | Status | Notes |
|------|--------|---------------|--------|-------|
| Jan 22, 2026 | nbac_team_boxscore | 199 games (Dec 27 - Jan 21) | ✅ Complete | V3 API fix |
| TBD | nbac_team_boxscore | 454 games (Oct 22 - Dec 26) | ⏳ Pending | Full season |
| TBD | nbac_gamebook_player_stats | ~350 games | ⏳ Pending | If needed |

### Phase 3 Reprocessing

| Date | Processor | Date Range | Status | Notes |
|------|-----------|------------|--------|-------|
| TBD | All Phase 3 | Oct 22 - Jan 22 | ⏳ Pending | After raw backfill |

### Phase 4 Reprocessing

| Date | Processor | Date Range | Status | Notes |
|------|-----------|------------|--------|-------|
| TBD | All Phase 4 | Oct 22 - Jan 22 | ⏳ Pending | After Phase 3 |

### Phase 5 Reprocessing

| Date | Processor | Date Range | Status | Notes |
|------|-----------|------------|--------|-------|
| TBD | MLFeatureStore | Oct 22 - Jan 22 | ⏳ Pending | After Phase 4 |

---

## Commands for Backfill

### Team Boxscore Raw Backfill
```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app \
  --workers=15
```

### Phase 3 Backfill (example)
```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-22
```

---

**Document Status:** Active - Update tracking tables as backfills complete
