# NBA.com Referee Assignments - Missing Data Backfill

**Status:** 🔴 MISSING 3,890 games (~71% of target coverage)  
**Current Coverage:** 2024-01-01 to 2025-06-19 (1,613 games)  
**Target Coverage:** 2021-10-19 to 2025-06-20 (5,503 games)

---

## Missing Data Summary

| Season | Status | Games Missing | Priority |
|--------|--------|---------------|----------|
| 2021-22 | 🔴 Complete missing | ~1,320 | Medium |
| 2022-23 | 🔴 Complete missing | ~1,320 | High |
| 2023-24 | 🟡 Partial (only Apr-Jun) | ~950 | Critical |
| 2024-25 | 🟡 Partial gaps | ~300 | Critical |
| **TOTAL** | | **~3,890** | |

---

## Priority 1: 2024-25 Missing Dates (CRITICAL)

**Date Range:** ~70 dates scattered throughout season  
**Games:** ~300 total

### Missing Dates List

```
Early Season (Oct-Nov 2024):
2024-10-24, 2024-10-28, 2024-10-30
2024-11-03, 2024-11-07, 2024-11-11, 2024-11-15, 2024-11-16
2024-11-18, 2024-11-21, 2024-11-23, 2024-11-24, 2024-11-26, 2024-11-30

Mid Season (Dec 2024):
2024-12-03, 2024-12-19, 2024-12-29, 2024-12-31

Late Season (Jan-Apr 2025):
2025-01-02, 2025-01-03, 2025-01-04, 2025-01-05
2025-01-11, 2025-01-13, 2025-01-16, 2025-01-18, 2025-01-24, 2025-01-28
2025-02-01, 2025-02-09, 2025-02-16, 2025-02-23
2025-03-03, 2025-03-04, 2025-03-08
2025-03-16, 2025-03-17, 2025-03-19, 2025-03-21, 2025-03-25
2025-04-06, 2025-04-08, 2025-04-10
```

### Backfill Command

```bash
# Create dates file
cat > missing_2024_25_dates.txt << 'EOF'
2024-10-24
2024-10-28
2024-10-30
2024-11-03
2024-11-07
2024-11-11
2024-11-15
2024-11-16
2024-11-18
2024-11-21
2024-11-23
2024-11-24
2024-11-26
2024-11-30
2024-12-03
2024-12-19
2024-12-29
2024-12-31
2025-01-02
2025-01-03
2025-01-04
2025-01-05
2025-01-11
2025-01-13
2025-01-16
2025-01-18
2025-01-24
2025-01-28
2025-02-01
2025-02-09
2025-02-16
2025-02-23
2025-03-03
2025-03-04
2025-03-08
2025-03-16
2025-03-17
2025-03-19
2025-03-21
2025-03-25
2025-04-06
2025-04-08
2025-04-10
EOF

# Run scraper (adjust command for your scraper)
python scripts/scrapers/nba_com/nbac_referee_scraper.py \
  --dates-file missing_2024_25_dates.txt

# Process the scraped data
gcloud run jobs execute nbac-referee-processor-backfill \
  --region=us-west2 \
  --args="--dates-file,missing_2024_25_dates.txt"

# Validate
bq query --use_legacy_sql=false < season_completeness_check.sql
```

**Expected Result:** 2024-25 teams should show ~82/82 regular season games

---

## Priority 2: 2023-24 First Half (CRITICAL)

**Date Range:** 2023-10-24 to 2024-03-31  
**Games:** ~950 (first half of season)

### Backfill Command

```bash
# Run scraper for date range
python scripts/scrapers/nba_com/nbac_referee_scraper.py \
  --start-date 2023-10-24 \
  --end-date 2024-03-31 \
  --season 2023-24

# Process data
gcloud run jobs execute nbac-referee-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2023-10-24,--end-date,2024-03-31"

# Validate
bq query --use_legacy_sql=false < season_completeness_check.sql
```

**Expected Result:** 2023-24 teams should show ~82/82 regular season games

---

## Priority 3: 2022-23 Complete Season (HIGH)

**Date Range:** 2022-10-18 to 2023-06-12  
**Games:** ~1,320 (entire season)

### Backfill Command

```bash
# Run complete season scraper
python scripts/scrapers/nba_com/nbac_referee_scraper.py \
  --start-date 2022-10-18 \
  --end-date 2023-06-12 \
  --season 2022-23

# Process data
gcloud run jobs execute nbac-referee-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2022-10-18,--end-date,2023-06-12"

# Validate
bq query --use_legacy_sql=false < season_completeness_check.sql
```

**Expected Result:** 2022-23 teams should appear with 82/82 regular season games

---

## Priority 4: 2021-22 Complete Season (MEDIUM)

**Date Range:** 2021-10-19 to 2022-06-16  
**Games:** ~1,320 (entire season)

### Backfill Command

```bash
# Run complete season scraper
python scripts/scrapers/nba_com/nbac_referee_scraper.py \
  --start-date 2021-10-19 \
  --end-date 2022-06-16 \
  --season 2021-22

# Process data
gcloud run jobs execute nbac-referee-processor-backfill \
  --region=us-west2 \
  --args="--start-date,2021-10-19,--end-date,2022-06-16"

# Validate
bq query --use_legacy_sql=false < season_completeness_check.sql
```

**Expected Result:** 2021-22 teams should appear with 82/82 regular season games

---

## Validation After Each Priority

After completing each backfill, run:

```bash
# 1. Season completeness
bq query --use_legacy_sql=false < season_completeness_check.sql

# 2. Check for any remaining gaps
bq query --use_legacy_sql=false < find_missing_regular_season_games.sql

# 3. Verify playoff data
bq query --use_legacy_sql=false < verify_playoff_completeness.sql

# 4. Check official counts
bq query --use_legacy_sql=false '
WITH game_counts AS (
  SELECT 
    game_id,
    COUNT(DISTINCT official_code) as official_count
  FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
  WHERE game_date >= "2021-10-19"
  GROUP BY game_id
)
SELECT 
  official_count,
  COUNT(*) as games
FROM game_counts
GROUP BY official_count
ORDER BY official_count'
```

**Success Criteria:**
- ✅ All 30 teams show 82/82 regular season games
- ✅ Playoff games match actual results
- ✅ 100% of games have 3 officials (regular) or 4 officials (playoffs)
- ✅ 0 games with wrong official count

---

## Estimated Timeline

| Priority | Duration | Status |
|----------|----------|--------|
| Priority 1: 2024-25 gaps | 2-3 hours | 🔴 Not Started |
| Priority 2: 2023-24 first half | 6-8 hours | 🔴 Not Started |
| Priority 3: 2022-23 complete | 8-10 hours | 🔴 Not Started |
| Priority 4: 2021-22 complete | 8-10 hours | 🔴 Not Started |
| **TOTAL** | **24-31 hours** | 🔴 **Not Started** |

**Recommendation:** Execute one priority per day to allow validation between phases.

---

## Quick Reference: Current vs Target

**Current State:**
- Games: 1,613
- Officials: 83 unique
- Date Range: 2024-01-01 to 2025-06-19
- Coverage: 29% of target

**Target State:**
- Games: 5,503
- Officials: ~100+ unique
- Date Range: 2021-10-19 to 2025-06-20
- Coverage: 100%

**Gap:** 3,890 games missing (71%)
