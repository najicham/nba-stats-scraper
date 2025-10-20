# ESPN Boxscore Validation CLI

**Data Source:** ESPN Game Boxscores  
**Table:** `nba_raw.espn_boxscores`  
**Pattern:** Sparse Backup Source (expect 0-10 games)  
**Last Updated:** October 18, 2025

---

## Quick Start

```bash
# Run full validation
./scripts/validate-espn-recent.sh

# Check for phantom games (should always be 0)
bq query --use_legacy_sql=false < \
  validation/queries/raw/espn_boxscore/cross_validate_with_bdl.sql
```

---

## Understanding ESPN Boxscore Data

**CRITICAL:** ESPN is an **extremely sparse backup source**, NOT comprehensive like BDL.

### Expected Behavior
- ⚪ 0-10 games total = NORMAL
- ⚪ No data yesterday = NORMAL (ad-hoc collection)
- ⚪ No overlap with BDL = EXPECTED
- ✅ High quality when data exists

### Unexpected Behavior
- 🔴 ESPN-only games = INVESTIGATE (possible phantom game)
- 🔴 Stats differ >5 points from BDL = DATA ERROR
- 🔴 NULL points values = PROCESSING ERROR

---

## Available Commands

### 1. Full Validation
```bash
./scripts/validate-espn-recent.sh
```
Runs all validation checks with explanations.

### 2. Individual Checks

**Data Existence:**
```bash
bq query --use_legacy_sql=false < \
  validation/queries/raw/espn_boxscore/data_existence_check.sql
```

**Cross-Validation with BDL (Most Important):**
```bash
bq query --use_legacy_sql=false < \
  validation/queries/raw/espn_boxscore/cross_validate_with_bdl.sql
```

**Data Quality:**
```bash
bq query --use_legacy_sql=false < \
  validation/queries/raw/espn_boxscore/data_quality_checks.sql
```

**BQ Commands Reference:**
```bash
bash scripts/espn_validation_bq_commands.sh
```

---

## Interpreting Results

### ✅ GOOD (Expected)
```
ESPN Games: 0-10
ESPN Only: 0
BDL Only: 5000+
Quality: All checks pass
```
**Action:** None needed

### ⚠️ WARNING (Investigate)
```
ESPN Only: 1-2 games
Stats differ: 3-5 points
```
**Action:** Run investigation queries, review scraper logs

### 🔴 CRITICAL (Fix Immediately)
```
ESPN Only: >0 (phantom games)
Stats differ: >5 points
NULL points values
```
**Action:** 
1. Run `scripts/espn_validation_bq_commands.sh` to investigate
2. Verify game exists in schedule
3. Compare with BDL data
4. If phantom game, use deletion script

---

## Handling Phantom Games

### Detection
```bash
# Check for ESP-only games
bq query --use_legacy_sql=false "
WITH espn_only AS (
  SELECT e.game_id, e.game_date,
    CONCAT(e.away_team_abbr, ' @ ', e.home_team_abbr) as matchup
  FROM (SELECT DISTINCT game_date, game_id, away_team_abbr, home_team_abbr 
        FROM \`nba-props-platform.nba_raw.espn_boxscores\`
        WHERE game_date >= '2020-01-01') e
  LEFT JOIN (SELECT DISTINCT game_id 
             FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
             WHERE game_date >= '2020-01-01') b
    ON e.game_id = b.game_id
  WHERE b.game_id IS NULL
)
SELECT * FROM espn_only
"
```

### Verification
```bash
# Check if game exists in schedule
bq query --use_legacy_sql=false "
SELECT 'Game in schedule?' as check,
  CASE WHEN COUNT(*) > 0 THEN 'YES' ELSE 'NO' END as result
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = '[DATE]'
  AND home_team_tricode = '[HOME]'
  AND away_team_tricode = '[AWAY]'
"
```

### Safe Deletion
```bash
# Use the guided script (recommended)
./scripts/delete_espn_phantom_game.sh

# Or manual (after verification)
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date = '[DATE]'
  AND game_id = '[GAME_ID]'
"
```

---

## Validation Schedule

### Daily (Automated)
```bash
# Add to crontab
0 8 * * * /path/to/scripts/validate-espn-recent.sh >> /var/log/espn-validation.log
```

### Weekly (Manual)
- Review ESPN collection activity
- Check for any ESP-only games
- Verify BDL coverage complete

### After ESPN Collection (Ad-Hoc)
- Run full validation
- Cross-check with BDL
- Verify game exists in schedule

---

## Common Issues

### Issue: "ESPN Only" games detected
**Cause:** ESPN scraped a game BDL doesn't have  
**Solution:**
1. Check if game exists in schedule
2. Check if BDL has any games on that date
3. If game doesn't exist → phantom game, delete it
4. If BDL missed it → investigate BDL scraper

### Issue: Partition filter errors
**Cause:** BigQuery table requires partition filter  
**Solution:** Always include `WHERE game_date >= 'YYYY-MM-DD'`

### Issue: No ESPN data but expected
**Cause:** ESPN is sparse backup, not daily collection  
**Solution:** This is NORMAL, not an error

---

## Related Documentation

- **Full Details:** `validation/queries/raw/espn_boxscore/README.md`
- **Discovery:** `validation/queries/raw/espn_boxscore/DISCOVERY_FINDINGS.md`
- **Validation Report:** `docs/validation/ESPN_BOXSCORE_VALIDATION_REPORT.md`
- **Scraper Code:** `scrapers/espn/espn_game_boxscore.py`

---

## Emergency Contacts

**Data Issues:** Check validation reports  
**Scraper Issues:** Review scraper logs  
**Questions:** See README.md in validation/queries/raw/espn_boxscore/

---

**Last Validation:** October 18, 2025  
**Status:** ✅ Clean (phantom game removed)  
**Next Review:** Weekly
