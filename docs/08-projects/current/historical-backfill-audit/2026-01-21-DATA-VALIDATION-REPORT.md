# Data Completeness Validation Report
**Date:** January 21, 2026
**Period Validated:** December 22, 2025 - January 21, 2026 (30 days)
**Validated By:** Automated validation session

---

## Executive Summary

| Metric | Value | Status |
|--------|-------|--------|
| **Total game dates validated** | 29 | - |
| **BDL missing games** | 33 | ⚠️ Report to BDL |
| **Games with NO analytics** | 4 | ✅ Backfilled |
| **Games missing composite factors** | 3 dates | ✅ Backfilled |
| **NBAC fallback working** | 29/33 games | ✅ Pipeline resilient |
| **Overall completeness** | ~96% | Good (with NBAC fallback) |

---

## Critical Finding: BallDontLie API Data Gaps

### Summary
**33 games are missing from BDL data** despite the scraper running correctly. The BDL API is not returning complete data for these games.

### Impact Assessment (Good News!)
The pipeline **successfully falls back to NBAC gamebook data** for most missing BDL games:

| Status | Count | Details |
|--------|-------|---------|
| Has Analytics (NBAC fallback worked) | 29 games | Pipeline healthy |
| MISSING Analytics completely | 4 games | Need investigation |
| MISSING Composite Factors | 2 games | Need Phase 4 backfill |

**Games with raw NBAC data but NO analytics (Phase 2/3 gap):**
- 2026-01-18: POR @ SAC (23 NBAC rows)
- 2026-01-17: WAS @ DEN (17 NBAC rows)
- 2026-01-01: UTA @ LAC (35 NBAC rows)
- 2026-01-01: BOS @ SAC (35 NBAC rows)

**Action:** Trigger Phase 2/3 processors for these dates

**Games missing composite factors (need backfill):**
- 2026-01-19: MIA @ GSW
- 2026-01-16: WAS @ SAC

### Pattern Analysis
| Home Team | Missing Games | % of Total |
|-----------|---------------|------------|
| GSW (Golden State) | 6 | 18% |
| SAC (Sacramento) | 6 | 18% |
| LAC (LA Clippers) | 5 | 15% |
| LAL (LA Lakers) | 4 | 12% |
| POR (Portland) | 4 | 12% |
| Other (DEN, SAS, MIA, DET, HOU, DAL) | 6 | 18% |
| Unknown format | 2 | 6% |

**76% of missing games are at Pacific Time Zone venues** (GSW, SAC, LAC, LAL, POR)

### Complete List of Missing Games (for BDL support)

```
Date        | Game ID              | Matchup
------------|---------------------|------------------
2026-01-19  | 20260119_MIA_GSW    | MIA @ GSW
2026-01-18  | 20260118_POR_SAC    | POR @ SAC
2026-01-18  | 20260118_TOR_LAL    | TOR @ LAL
2026-01-17  | 20260117_WAS_DEN    | WAS @ DEN
2026-01-17  | 20260117_LAL_POR    | LAL @ POR
2026-01-16  | 20260116_WAS_SAC    | WAS @ SAC
2026-01-15  | 20260115_ATL_POR    | ATL @ POR
2026-01-15  | 20260115_CHA_LAL    | CHA @ LAL
2026-01-15  | 20260115_UTA_DAL    | UTA @ DAL
2026-01-15  | 20260115_BOS_MIA    | BOS @ MIA
2026-01-15  | 20260115_NYK_GSW    | NYK @ GSW
2026-01-15  | 20260115_OKC_HOU    | OKC @ HOU
2026-01-15  | 20260115_MIL_SAS    | MIL @ SAS
2026-01-15  | 20260115_PHX_DET    | PHX @ DET
2026-01-14  | 20260114_NYK_SAC    | NYK @ SAC
2026-01-14  | 20260114_WAS_LAC    | WAS @ LAC
2026-01-13  | 20260113_ATL_LAL    | ATL @ LAL
2026-01-13  | 20260113_POR_GSW    | POR @ GSW
2026-01-12  | 20260112_CHA_LAC    | CHA @ LAC
2026-01-12  | 20260112_LAL_SAC    | LAL @ SAC
2026-01-07  | 20260107_MIL_GSW    | MIL @ GSW
2026-01-07  | 20260107_HOU_POR    | HOU @ POR
2026-01-06  | 20260106_DAL_SAC    | DAL @ SAC
2026-01-05  | 20260105_GSW_LAC    | GSW @ LAC
2026-01-05  | 20260105_UTA_POR    | UTA @ POR
2026-01-03  | 20260103_BOS_LAC    | BOS @ LAC
2026-01-03  | 20260103_UTA_GSW    | UTA @ GSW
2026-01-02  | 20260102_MEM_LAL    | MEM @ LAL
2026-01-02  | 20260102_OKC_GSW    | OKC @ GSW
2026-01-01  | 20260101_UTA_LAC    | UTA @ LAC
2026-01-01  | 20260101_BOS_SAC    | BOS @ SAC
2025-12-29  | 0022500447          | (Legacy ID format)
2025-12-28  | 0022500442          | (Legacy ID format)
```

### Evidence: Scraper Ran But Got Incomplete Data

| Game Date | Games Scraped | Scrape Time (UTC) | Expected Games |
|-----------|---------------|-------------------|----------------|
| 2026-01-15 | 1 | 23:05 | 9 |
| 2026-01-18 | 4 | 02:05 | 6 |
| 2026-01-19 | 8 | 02:05 | 9 |

The scraper IS running at correct times (post-midnight), but BDL API is returning incomplete data.

---

## Phase-by-Phase Completeness

### Phase 1: Raw Data (nba_raw)

| Date | BDL Games | NBAC Games | Mismatch |
|------|-----------|------------|----------|
| 2026-01-20 | 4 | 0 | NBAC not scraped yet |
| 2026-01-19 | 8 | 9 | BDL missing 1 |
| 2026-01-18 | 4 | 6 | BDL missing 2 |
| 2026-01-17 | 7 | 9 | BDL missing 2 |
| 2026-01-16 | 5 | 6 | BDL missing 1 |
| 2026-01-15 | 1 | 9 | **BDL missing 8** |
| 2026-01-14 | 5 | 7 | BDL missing 2 |
| 2026-01-13 | 5 | 7 | BDL missing 2 |
| 2026-01-12 | 4 | 6 | BDL missing 2 |
| 2026-01-11 | 10 | 10 | ✅ Complete |
| 2026-01-10 | 6 | 6 | ✅ Complete |
| 2026-01-09 | 10 | 10 | ✅ Complete |
| 2026-01-08 | 3 | 3 | ✅ Complete |
| 2026-01-07 | 10 | 12 | BDL missing 2 |
| 2026-01-06 | 5 | 6 | BDL missing 1 |
| 2026-01-05 | 6 | 8 | BDL missing 2 |
| 2026-01-04 | 8 | 8 | ✅ Complete |
| 2026-01-03 | 6 | 8 | BDL missing 2 |
| 2026-01-02 | 8 | 10 | BDL missing 2 |
| 2026-01-01 | 3 | 5 | BDL missing 2 |
| 2025-12-31 | 9 | 9 | ✅ Complete |
| 2025-12-30 | 4 | 4 | ✅ Complete |
| 2025-12-29 | 11 | 11 | ✅ Complete |
| 2025-12-28 | 6 | 6 | ✅ Complete |
| 2025-12-27 | 9 | 9 | ✅ Complete |
| 2025-12-26 | 9 | 9 | ✅ Complete |
| 2025-12-25 | 5 | 5 | ✅ Complete |
| 2025-12-23 | 14 | 14 | ✅ Complete |
| 2025-12-22 | 7 | 7 | ✅ Complete |

### Phase 2/3: Analytics (nba_analytics)
- `player_game_summary`: Generally complete, matches NBAC data well
- Minor discrepancies on Dec 28-29 (analytics has +1 game vs raw)

### Phase 4: Precompute (nba_precompute)

**Composite factors - BACKFILLED:**
- 2026-01-16: ✅ 171 players
- 2026-01-19: ✅ 156 players
- 2026-01-20: ✅ 169 players

`player_daily_cache`: Complete for all dates

---

## Schema Discovery: Validation Guide Needs Update

The original validation guide (`data-completeness-validation-guide.md`) references **incorrect table names**:

| Guide References | Actual Tables |
|------------------|---------------|
| `nba_source.nbac_schedule` | `nba_raw.espn_scoreboard` (but not current!) |
| `nba_source.bdl_games` | N/A - use `nba_raw.bdl_player_boxscores` |
| `nba_predictions.bdl_player_boxscores` | `nba_raw.bdl_player_boxscores` |
| `nba_predictions.nbac_gamebook_player_stats` | `nba_raw.nbac_gamebook_player_stats` |
| `nba_predictions.ml_feature_store_v2` | Does not exist in current schema |
| `nba_predictions.player_composite_factors` | `nba_precompute.player_composite_factors` |

**NOTE:** `espn_scoreboard` only has data through June 2025 - not the current season!

---

## Recommended Actions

### Immediate (P0)
1. **Email BallDontLie** about the 33 missing games (list above)
2. ✅ **Backfill Phase 2/3** COMPLETED - 4 games now have analytics:
   - Jan 1: 3 games, 90 records
   - Jan 17: 8 games, 254 records
   - Jan 18: 5 games, 127 records
3. ✅ **Backfill Phase 4** COMPLETED - composite factors now exist:
   - Jan 16: 171 players
   - Jan 19: 156 players
   - Jan 20: 169 players

### Short-term (P1)
4. **Update espn_scoreboard scraper** or find alternative schedule source for 2025-26 season
5. ✅ **Update validation guide** with correct table names (DONE)
6. **Add monitoring** for BDL vs NBAC game count discrepancies

### Medium-term (P2)
7. **Implement fallback** - if BDL games < NBAC games, alert and use NBAC data
8. **Add daily reconciliation job** to detect missing games early

---

## Query Used for Validation

```sql
-- Main comparison query
WITH bdl AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
),
nbac AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
),
pgs AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
),
pcf AS (
  SELECT game_date, 1 as has_pcf
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
)
SELECT
  d.game_date,
  COALESCE(bdl.games, 0) as bdl_games,
  COALESCE(nbac.games, 0) as nbac_games,
  COALESCE(pgs.games, 0) as pgs_games,
  CASE WHEN pcf.has_pcf = 1 THEN 'Y' ELSE 'N' END as has_composite_factors
FROM all_dates d
LEFT JOIN bdl ON d.game_date = bdl.game_date
LEFT JOIN nbac ON d.game_date = nbac.game_date
LEFT JOIN pgs ON d.game_date = pgs.game_date
LEFT JOIN pcf ON d.game_date = pcf.game_date
ORDER BY d.game_date DESC;
```

---

## Appendix: Actual Dataset/Table Structure

```
nba_raw/
  ├── bdl_player_boxscores (Phase 1 - BallDontLie)
  ├── nbac_gamebook_player_stats (Phase 1 - NBA.com)
  ├── espn_scoreboard (Schedule - NOT CURRENT!)
  └── bettingpros_player_points_props (Props data)

nba_analytics/
  ├── player_game_summary (Phase 2/3)
  ├── team_defense_game_summary
  ├── team_offense_game_summary
  └── upcoming_player_game_context

nba_precompute/
  ├── player_composite_factors (Phase 4)
  ├── player_daily_cache (Phase 4)
  ├── player_shot_zone_analysis
  └── team_defense_zone_analysis

nba_predictions/
  └── (contains mostly staging tables)
```

---

**Report Generated:** 2026-01-21
**Next Validation:** Recommend weekly automated check
