# Cross-Source Reconciliation - Investigation Findings

**Investigated**: 2026-01-28
**Status**: Infrastructure Exists, Needs Automation

---

## Key Finding: Infrastructure Already Exists!

Cross-source reconciliation is **largely built** but **not fully automated**:
- ✅ SQL views for comparison exist
- ✅ Validation queries with thresholds
- ✅ Python validation framework
- ⚠️ Missing: Hourly automation and `/validate-daily` integration

---

## 1. Tables Containing Source Data

| Source | Table | Key ID Field |
|--------|-------|--------------|
| NBA.com | `nba_raw.nbac_player_boxscores` | `nba_player_id` |
| BDL | `nba_raw.bdl_player_boxscores` | `bdl_player_id` |
| ESPN | `nba_raw.espn_boxscores` | `espn_player_id` |

**Field Differences:**
- NBA.com uses `total_rebounds`, BDL uses `rebounds`
- NBA.com has `plus_minus`, BDL does not

---

## 2. Player Matching

**Primary Join Key**: `player_lookup` (normalized name)

Normalization process:
1. NFKC Unicode normalization
2. Remove diacritics (José → jose)
3. Casefold (better than lowercase)
4. Normalize suffixes (Junior → jr)
5. Remove punctuation

**Mapping Table**: `nba_reference.player_name_mappings`

---

## 3. Existing Comparison Code

**SQL Views:**
- `nba_raw.player_boxscore_comparison` - NBA.com vs BDL
- `nba_raw.boxscores_cross_validation` - ESPN vs BDL

**Validation Queries:**
- `validation/queries/raw/nbac_player_boxscores/cross_validate_with_bdl.sql`
- `validation/queries/raw/espn_boxscore/cross_validate_with_bdl.sql`

**Python Validator:**
- `validation/validators/raw/nbac_player_boxscore_validator.py`
  - Method: `_validate_against_bdl()`

---

## 4. Alert Thresholds

| Level | Difference | Action |
|-------|------------|--------|
| ✅ Perfect | 0 | Expected (95%+) |
| ⚪ Minor | 1-2 points | Acceptable (<5%) |
| ⚠️ Warning | >2 in assists/rebounds | Investigate |
| 🔴 Critical | >2 points | Immediate investigation |

---

## 5. Source Priority

1. **NBA.com** - Official, authoritative (source of truth)
2. **BDL** - Primary real-time source
3. **ESPN** - Backup validation only

---

## 6. Recommended Actions

1. **Create scheduled query** to run hourly comparison
2. **Add to /validate-daily** output
3. **Create** `nba_monitoring.source_reconciliation` view
4. **Automate** alerting for critical discrepancies

---

## 7. Expected Match Rate

- **Target**: 95%+ perfect match
- **<1%** critical discrepancies acceptable
- **<5%** minor discrepancies acceptable
