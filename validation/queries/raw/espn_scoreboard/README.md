# ESPN Scoreboard Validation Queries

**Purpose**: Validate ESPN scoreboard data (backup validation source)  
**Pattern**: Pattern 1 (1 record per game with home/away in same row)  
**Business Role**: Early Morning Final Check workflow backup (5 AM PT)  
**Data Characteristics**: Sparse backup collection (~6 games/day average)

---

## 📊 Quick Stats

```
Total Records: 5,520 games
Date Range: 2021-10-19 → 2025-06-22
Coverage: 895 dates (sparse backup collection)
Seasons: 2021-22, 2022-23, 2023-24, 2024-25
Average: ~6 games per date (backup source pattern)
```

---

## 🎯 Business Context

ESPN Scoreboard is a **backup validation source** used in the Early Morning Final Check workflow (5 AM PT). It's **not expected to have complete coverage** - sparse data is normal and acceptable for a backup source.

**Key Characteristics**:
- Backup validation only (not primary data collection)
- Part of final game score verification chain
- Cross-validates against BDL and NBA.com official sources
- Processing confidence always 1.0 (ESPN data reliable)

---

## 📁 Query Files

### 1. **date_coverage_analysis.sql**
Understand sparse backup coverage patterns and identify gaps.

**Use Cases**:
- Weekly coverage review
- Identify large gaps (>10 days)
- Seasonal pattern analysis

**Expected Results**:
- 895 dates with data (sparse is NORMAL)
- ~6 games per date average
- Large gaps during offseason (100+ days = expected)

**Run Frequency**: Weekly or after backfills

---

### 2. **daily_check_yesterday.sql**
Morning validation routine after Early Morning Final Check (5 AM PT).

**Use Cases**:
- Daily operational check
- Verify yesterday's backup collection
- Flag any processing issues

**Expected Results**:
- 0 games = VALID (backup source doesn't collect all games)
- If games exist, verify completion status
- Team mapping checks (ESPN → NBA codes)

**Run Frequency**: Daily at 6 AM PT

---

### 3. **cross_validate_with_bdl.sql**
Compare ESPN scores vs Ball Don't Lie (primary data source).

**Use Cases**:
- Score accuracy validation
- Detect data quality issues
- Identify missing games in either source

**Expected Results**:
- Most games should match exactly (Δ = 0)
- BDL has more games (primary source)
- Any difference >2 points = investigation needed

**Run Frequency**: Weekly or when investigating score discrepancies

---

### 4. **cross_validate_with_nbac.sql**
Compare ESPN vs NBA.com Scoreboard V2 (official source).

**Use Cases**:
- **CRITICAL**: ESPN vs official NBA.com validation
- Detect data corruption
- Verify backup source accuracy

**Expected Results**:
- Perfect matches expected (both use official scores)
- **Any mismatch = CRITICAL ISSUE**
- NBA.com has more games (official source)

**Run Frequency**: Weekly or when investigating critical issues

---

### 5. **team_mapping_validation.sql**
Verify ESPN team code conversions to NBA standard codes.

**Use Cases**:
- Validate processor mapping logic
- Detect unmapped/unknown codes
- Identify All-Star games

**Expected Results**:
- Standard mappings: GS→GSW, NY→NYK, SA→SAS, NO→NOP, UTAH→UTA, WSH→WAS
- Unknown codes flagged: CHK (2), SHQ (1)
- All-Star codes: EAST, WEST (should be filtered)

**Run Frequency**: After processor updates or when new codes appear

**Known Issues**:
```
CHK → CHK (2 occurrences) - Unknown team code
SHQ → SHQ (1 occurrence) - Unknown team code  
EAST → EAST (1 occurrence) - All-Star game (filter in processor)
```

---

### 6. **data_quality_check.sql**
Comprehensive quality validation for scores and status flags.

**Use Cases**:
- Overall data health monitoring
- Score reasonableness checks
- Completion status validation

**Expected Results**:
- Scores: 180-240 typical range (NBA games)
- Very low (<150) or very high (>280) = outliers (review)
- is_completed should match game_status = 'final'
- processing_confidence always 1.0

**Run Frequency**: Weekly or monthly health checks

---

### 7. **find_score_discrepancies.sql**
Three-way comparison (ESPN vs BDL vs NBA.com) to find specific issues.

**Use Cases**:
- Investigate reported score discrepancies
- Multi-source validation
- Priority issue identification

**Expected Results**:
- Most games agree across all 3 sources
- ESPN vs NBA.com differences = CRITICAL (both official)
- BDL differences = less critical (third-party API)

**Run Frequency**: Ad-hoc when investigating specific games

---

## 🚀 Quick Start

```bash
# 1. Daily morning check (run at 6 AM PT)
bq query --use_legacy_sql=false < daily_check_yesterday.sql

# 2. Weekly coverage review
bq query --use_legacy_sql=false < date_coverage_analysis.sql

# 3. Weekly cross-validation (both queries)
bq query --use_legacy_sql=false < cross_validate_with_bdl.sql
bq query --use_legacy_sql=false < cross_validate_with_nbac.sql

# 4. Monthly health check
bq query --use_legacy_sql=false < data_quality_check.sql
bq query --use_legacy_sql=false < team_mapping_validation.sql
```

---

## ⚠️ Important Notes

### Partition Filter Required
All queries **MUST** include `game_date >= 'YYYY-MM-DD'` filter:

```sql
-- ❌ WILL FAIL
SELECT COUNT(*) FROM `nba_raw.espn_scoreboard`

-- ✅ REQUIRED
SELECT COUNT(*) FROM `nba_raw.espn_scoreboard`
WHERE game_date >= '2021-01-01'
```

### Sparse Coverage is Normal
ESPN Scoreboard is a **backup source**:
- **Expected**: ~6 games per day (not all NBA games)
- **Expected**: Large gaps (offseason, collection patterns)
- **Expected**: Fewer games than BDL or NBA.com

### 0 Games is Valid
For daily checks:
- 0 games yesterday = **VALID** (backup doesn't collect everything)
- Don't treat as error or missing data
- Only flag if pattern changes (e.g., 0 games for 7+ consecutive days)

---

## 🔍 Investigation Workflows

### Score Discrepancy
1. Run `find_score_discrepancies.sql` to identify issue
2. Check if ESPN vs NBA.com differ (CRITICAL) vs ESPN vs BDL (less critical)
3. Review source files in GCS: `gs://nba-scraped-data/espn/scoreboard/`
4. Verify game_id construction in processor
5. Cross-check with official NBA.com game report

### Unknown Team Code
1. Run `team_mapping_validation.sql` to see all unmapped codes
2. Check processor `team_mapping` dictionary
3. Research ESPN team abbreviation conventions
4. Update processor if new valid code found
5. Filter out if special event (All-Star, international)

### Low Coverage
1. Run `date_coverage_analysis.sql` for pattern
2. Check scraper execution logs in GCS
3. Verify Early Morning Final Check workflow running
4. Acceptable if recent trend (new backup collection)
5. Only concern if historical data suddenly missing

---

## 📈 Health Thresholds

### Green (✅ Healthy)
- Daily: 0-12 games collected (backup pattern)
- Weekly: Any games collected
- Score differences: 0 across all sources
- Team mapping: All standard codes working

### Yellow (⚠️ Review)
- Daily: Unusual pattern (e.g., suddenly 0 for 7+ days after period of collection)
- Score differences: 1-2 points (minor discrepancies)
- Unknown codes: New unmapped codes appear
- Coverage: Large unexpected gaps

### Red (🔴 Critical)
- ESPN vs NBA.com score differences (both official sources)
- Data corruption: NULL scores for completed games
- Processing failures: processing_confidence != 1.0
- Status mismatches: is_completed doesn't match game_status

---

## 🔗 Related Tables

**Primary Cross-Validation Sources**:
- `nba_raw.bdl_player_boxscores` - Primary game results
- `nba_raw.nbac_scoreboard_v2` - Official NBA.com scores

**Supporting Tables**:
- `nba_raw.nbac_schedule` - Game schedule (expected games)
- `nba_raw.nbac_player_list_current` - Current rosters

---

## 📝 Change Log

**2025-10-13**: Initial validation queries created
- 7 comprehensive queries for backup source validation
- Three-way cross-validation (ESPN vs BDL vs NBA.com)
- Team mapping validation for ESPN codes
- Daily operational checks

---

## 💡 Tips

1. **Backup Source Mentality**: ESPN is backup validation only - don't expect complete coverage
2. **Cross-Validation Priority**: ESPN vs NBA.com mismatches are CRITICAL (both official)
3. **Team Mapping**: Update processor when new valid ESPN codes discovered
4. **0 Games Valid**: Don't treat 0 games as error for backup sources
5. **Use Latest Results**: Focus validation on last 30-90 days (recent data quality)

---

**Last Updated**: 2025-10-13  
**Validation Pattern**: Pattern 1 (1 record per game)  
**Business Priority**: MEDIUM (backup validation source)  
**Processing Strategy**: MERGE_UPDATE with staging table (production-safe)
