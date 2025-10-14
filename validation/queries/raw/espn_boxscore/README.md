# ESPN Boxscore Validation Queries

**File:** `validation/queries/raw/espn_boxscore/README.md`  
**Data Source:** ESPN Game Boxscores  
**Table:** `nba_raw.espn_boxscores`  
**Pattern:** Pattern 3 (Single Event) - Extremely Sparse Backup Source  
**Created:** October 13, 2025  
**Status:** ✅ Production Ready

---

## 🎯 Quick Start

### Understanding ESPN Boxscore Data

**CRITICAL:** ESPN is an **extremely sparse backup data source**, NOT a comprehensive dataset like BDL or NBA.com.

**Key Characteristics:**
- ⚪ **Minimal Coverage:** Only 1 game in current dataset (2025-01-15)
- 🎯 **Backup Only:** Collected during Early Morning Final Check workflow failures
- ✅ **High Quality:** When data exists, it's accurate and complete
- 🔴 **Game ID Mismatch:** Cannot join with schedule on `game_id` - must use date + teams

**Expected Behavior:**
- ✅ Zero ESPN data on most days = **NORMAL**
- ✅ Sparse collection, gaps expected = **NORMAL**
- ⚠️ ESPN data exists but BDL doesn't = **INVESTIGATE**

---

## 📊 Available Validation Queries

### 1. **Data Existence Check** ⭐ START HERE
**File:** `data_existence_check.sql`  
**Purpose:** Verify ESPN backup data exists and understand its scope

```bash
bq query --use_legacy_sql=false < data_existence_check.sql
```

**What it checks:**
- Do we have ANY ESPN data?
- What date range is covered?
- How many games and players?
- Recent activity (last 7/30 days)
- Average players per game

**Expected:** Minimal coverage (1 game as of Oct 2025) - **THIS IS NORMAL**

---

### 2. **Cross-Validation with BDL** 🔥 MOST IMPORTANT
**File:** `cross_validate_with_bdl.sql`  
**Purpose:** Compare ESPN backup data against BDL primary source

```bash
bq query --use_legacy_sql=false < cross_validate_with_bdl.sql
```

**What it checks:**
- Which games exist in ESPN vs BDL?
- Do player stats match between sources?
- Points, rebounds, assists accuracy
- Team assignment consistency

**Expected:** Currently 0 overlap (1 ESPN-only, 227 BDL-only in Jan 2025)

---

### 3. **Daily Check Yesterday**
**File:** `daily_check_yesterday.sql`  
**Purpose:** Monitor if ESPN backup collection ran yesterday

```bash
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

**What it checks:**
- Did ESPN collect data yesterday?
- How many games vs schedule?
- Does BDL have same data?

**Expected:** Most days = "No ESPN data" - **THIS IS NORMAL FOR BACKUP SOURCE**

⚠️ **DO NOT ALERT** on "no ESPN data" - only alert if ESPN exists but BDL doesn't

---

### 4. **Data Quality Checks**
**File:** `data_quality_checks.sql`  
**Purpose:** Identify suspicious patterns when ESPN data exists

```bash
bq query --use_legacy_sql=false < data_quality_checks.sql
```

**What it checks:**
- Player counts per game (expect 20-30)
- NULL values in core stats
- Team balance (2 teams per game)
- Unusual but valid stats (50+ pts, 20+ reb)

**Red Flags:**
- 🔴 NULL points values
- 🔴 Wrong team count (≠2)
- ⚠️ Player count <20 or >35

---

### 5. **Player Stats Comparison**
**File:** `player_stats_comparison.sql`  
**Purpose:** Detailed stat validation between ESPN and BDL

```bash
bq query --use_legacy_sql=false < player_stats_comparison.sql
```

**What it checks:**
- Individual player stat differences
- Perfect match rate
- Core stat accuracy (points, rebounds, assists)
- Shooting stats comparison

**Expected:** When overlap exists, >95% stat accuracy

---

## 🔍 Discovery Findings Summary

### **Current Coverage (as of Oct 2025)**

```
Earliest Date:        2025-01-15
Latest Date:          2025-01-15
Total Games:          1
Total Player Records: 25
Unique Players:       25

Coverage Pattern:     Extremely sparse (backup only)
Schedule Match:       0% (game_id format mismatch)
BDL Overlap:          0 games (no overlap)
```

### **Critical Finding: Game ID Format Mismatch** 🚨

```
ESPN Format:      20250115_HOU_PHI  (Our standard)
Schedule Format:  0022400604         (NBA.com official)

❌ CANNOT JOIN ON game_id!
✅ MUST JOIN ON: game_date + home_team_abbr + away_team_abbr
```

**Correct Join Strategy:**
```sql
-- ❌ WRONG: This will NOT work
LEFT JOIN nba_raw.nbac_schedule s 
  ON espn.game_id = s.game_id

-- ✅ CORRECT: Use date + teams
LEFT JOIN nba_raw.nbac_schedule s
  ON espn.game_date = s.game_date
  AND espn.home_team_abbr = s.home_team_tricode
  AND espn.away_team_abbr = s.away_team_tricode
```

---

## ⚠️ Common Pitfalls

### Pitfall 1: Expecting Comprehensive Coverage

**Problem:**
```sql
-- This query will show 0% coverage - DON'T PANIC!
SELECT COUNT(*) FROM schedule WHERE NOT EXISTS (
  SELECT 1 FROM espn_boxscores WHERE ...
)
```

**Reality:**  
ESPN is a **sparse backup source**. 0% coverage is **EXPECTED and NORMAL**.

**Solution:**  
Don't create "missing games" queries. Focus on data quality when it exists.

---

### Pitfall 2: Joining on game_id with Schedule

**Problem:**
```sql
-- This join will FAIL - game_id formats don't match
LEFT JOIN nbac_schedule s ON espn.game_id = s.game_id
```

**Solution:**
```sql
-- Always use date + teams for schedule joins
LEFT JOIN nbac_schedule s 
  ON espn.game_date = s.game_date
  AND espn.home_team_abbr = s.home_team_tricode
  AND espn.away_team_abbr = s.away_team_tricode
```

---

### Pitfall 3: Alerting on "No Data"

**Problem:**  
Setting up alerts for "ESPN has no data yesterday"

**Reality:**  
ESPN backup collection runs **ad-hoc**, not daily. Most days have no data.

**Solution:**  
Only alert if:
- ✅ ESPN data exists BUT BDL doesn't (role reversal = problem)
- ✅ ESPN and BDL stats differ by >5 points (validation failure)

❌ **DO NOT** alert on "no ESPN data" - this is normal!

---

## 📋 Validation Checklist

When running ESPN validation:

### Initial Setup
- [ ] Run `data_existence_check.sql` to understand current coverage
- [ ] Review `DISCOVERY_FINDINGS.md` to understand data characteristics
- [ ] Verify partition filter requirements (game_date must be in WHERE clause)

### Regular Validation (When ESPN Data Exists)
- [ ] Run `cross_validate_with_bdl.sql` to check accuracy
- [ ] Run `data_quality_checks.sql` to identify issues
- [ ] Run `player_stats_comparison.sql` for detailed validation

### When Issues Found
- [ ] Check if BDL also has same game (ESPN should be backup)
- [ ] Compare individual player stats for major discrepancies (>5 points)
- [ ] Verify team abbreviations match between sources
- [ ] Document issues in processing logs

---

## 🎯 Status Interpretation Guide

### ✅ Good (Expected Patterns)

```
⚪ No ESPN data = NORMAL (backup source, sparse collection)
✅ ESPN + BDL both exist = EXCELLENT (can cross-validate)
✅ Stats match exactly = PERFECT (ESPN validating BDL correctly)
⚪ Stats differ by 1-2 points = ACCEPTABLE (minor scoring differences)
```

### ⚠️ Warning (Investigate)

```
⚠️ Stats differ by 3-5 points = REVIEW (could be scoring disagreement)
⚠️ Player count <20 or >35 = UNUSUAL (check game circumstances)
⚠️ Missing rebounds/assists = DATA QUALITY (nice-to-have stats)
```

### 🔴 Critical (Alert Immediately)

```
🔴 ESPN exists, BDL doesn't = PROBLEM (role reversal)
🔴 Stats differ by >5 points = VALIDATION FAILURE
🔴 Team mismatch = DATA CORRUPTION
🔴 NULL points values = PROCESSING ERROR
```

---

## 🔧 Troubleshooting

### "Why is coverage so low?"

**Answer:** ESPN is a backup source, not a primary data collection. Low coverage is **EXPECTED**.

**Action:** No action needed. This is normal operation.

---

### "ESPN and BDL don't overlap - is this a problem?"

**Answer:** No. ESPN collects data ad-hoc during backup scenarios. Zero overlap is currently normal.

**Action:** When overlap exists in future, validate stat accuracy with `cross_validate_with_bdl.sql`

---

### "How do I find missing games?"

**Answer:** Don't. ESPN is not comprehensive. "Missing games" is the normal state.

**Action:** Focus on data quality when ESPN data exists, not completeness.

---

### "Stats differ between ESPN and BDL - which is right?"

**Answer:** BDL is the primary source. ESPN is backup validation.

**Action:**
1. If difference ≤2 points: Normal scoring variance, accept BDL
2. If difference 3-5 points: Review both, likely minor discrepancy
3. If difference >5 points: **CRITICAL** - investigate both sources, check NBA.com official

---

## 📁 File Structure

```
validation/queries/raw/espn_boxscore/
├── README.md                          # This file - Quick start guide
├── DISCOVERY_FINDINGS.md              # Detailed data characteristics
├── data_existence_check.sql           # Do we have ANY ESPN data?
├── cross_validate_with_bdl.sql        # Compare with primary source
├── daily_check_yesterday.sql          # Did backup collection run?
├── data_quality_checks.sql            # Suspicious patterns
└── player_stats_comparison.sql        # Detailed stat validation
```

---

## 🚀 Quick Commands

**Check if ESPN has ANY data:**
```bash
bq query --use_legacy_sql=false < data_existence_check.sql
```

**Validate against BDL (most important):**
```bash
bq query --use_legacy_sql=false < cross_validate_with_bdl.sql
```

**Morning check (did backup run yesterday?):**
```bash
bq query --use_legacy_sql=false < daily_check_yesterday.sql
```

---

## 📝 Key Takeaways

1. **ESPN is extremely sparse** - 1 game in dataset is NORMAL for backup source
2. **Game ID mismatch** - Must join on date + teams, not game_id
3. **Quality over quantity** - Validate accuracy when data exists
4. **Don't alert on gaps** - Most days have no ESPN data (expected)
5. **BDL is primary** - ESPN is backup validation only

---

## 📞 Related Documentation

- **Master Validation Guide:** `validation/NBA_DATA_VALIDATION_MASTER_GUIDE.md`
- **Advanced Topics:** `validation/NBA_DATA_VALIDATION_ADVANCED_TOPICS.md`
- **Processor Documentation:** `processors/espn/espn_boxscore_processor.py`
- **BDL Boxscore Validation:** `validation/queries/raw/bdl_boxscores/` (primary source)

---

## 🎓 Understanding ESPN's Role

**ESPN Boxscore Position in Data Pipeline:**

```
Primary Sources (Comprehensive Coverage):
├── Ball Don't Lie Boxscores     (Primary, 227 games/month)
└── NBA.com Gamebooks             (Official, comprehensive)

Backup Sources (Sparse Coverage):
└── ESPN Boxscores                (Backup, 0-10 games/month)
    ↑
    Used only during Early Morning Final Check workflow
    Validates BDL accuracy in edge cases
```

**Revenue Impact:** **MEDIUM-LOW**  
ESPN failure doesn't impact operations (BDL is primary). Provides extra validation confidence.

---

**Last Updated:** October 13, 2025  
**Status:** ✅ Production Ready - Validation queries complete  
**Pattern:** Pattern 3 with date + team join strategy  
**Coverage:** Extremely sparse (1 game) - **NORMAL** for backup source
