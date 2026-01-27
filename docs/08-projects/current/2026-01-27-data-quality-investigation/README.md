# Data Quality Investigation - 2026-01-27

## Status: IN PROGRESS

**Started**: 2026-01-27 13:34 PST
**Validation Date**: 2026-01-26 (yesterday's games)
**Processing Date**: 2026-01-27 (today)

---

## Executive Summary

Daily validation revealed **3 critical issues** affecting data quality:

1. **Source Data Discrepancy** - NBAC and BDL reporting different stats for same players
2. **Game_ID Format Mismatch** - Team stats JOIN failing, causing NULL usage_rate
3. **Low Prediction Coverage** - Zero predictions generated for Jan 26

---

## Issue #1: Source Data Discrepancy (P1 CRITICAL)

### Description
NBAC (NBA.com gamebook) and BDL (BallDontLie API) are reporting **different player statistics** for the same games on 2026-01-26.

### Evidence

| Player | NBAC Points | BDL Points | Difference | NBAC Mins | BDL Mins |
|--------|-------------|------------|------------|-----------|----------|
| Luka Doncic | 46 | 39 | +7 | 38 | 34 |
| Kevin Durant | 33 | 27 | +6 | 37 | 32 |
| LeBron James | 24 | 22 | +2 | 33 | 29 |
| Donovan Mitchell | 45 | 45 | 0 | 35 | 35 |
| Paolo Banchero | 37 | 37 | 0 | 40 | 40 |

### Historical Pattern
Checking Luka Doncic across recent dates:

| Date | NBAC | BDL | Diff |
|------|------|-----|------|
| 2026-01-26 | 46 | 39 | +7 |
| 2026-01-24 | 33 | 2 | +31 |
| 2026-01-20 | 38 | 38 | 0 |

The Jan 24 discrepancy (31 points!) suggests BDL may have incomplete data.

### Impact
- Analytics table uses NBAC as PRIMARY source
- If NBAC is wrong, all downstream calculations are affected
- If BDL is wrong, fallback logic won't help

### Investigation Needed
- [ ] Verify actual game stats from official NBA.com box scores
- [ ] Check if BDL API is returning partial game data
- [ ] Check gamebook PDF source files for accuracy

---

## Issue #2: Game_ID Format Mismatch (P1 CRITICAL)

### Description
The `player_game_summary` table uses **AWAY_HOME** format for game_id, while `team_offense_game_summary` uses **HOME_AWAY** format, causing JOIN failures.

### Evidence

| Source | Game ID Format | Example |
|--------|----------------|---------|
| player_game_summary | AWAY_HOME | `20260126_LAL_CHI` |
| team_offense_game_summary | HOME_AWAY | `20260126_CHI_LAL` |

### JOIN Results (Jan 26)

| Player Game ID | Team Game ID | Status |
|----------------|--------------|--------|
| 20260126_GSW_MIN | NULL | NO MATCH |
| 20260126_LAL_CHI | NULL | NO MATCH |
| 20260126_MEM_HOU | NULL | NO MATCH |
| 20260126_POR_BOS | NULL | NO MATCH |
| 20260126_IND_ATL | 20260126_IND_ATL | MATCHED |
| 20260126_ORL_CLE | 20260126_ORL_CLE | MATCHED |
| 20260126_PHI_CHA | 20260126_PHI_CHA | MATCHED |

Only 3/7 games matched (43%).

### Fix Status
- Commit `d3066c88` adds `game_id_reversed` column to handle both formats
- **NOT YET DEPLOYED** - data needs reprocessing

### Impact
- `usage_rate` is NULL for players in non-matching games
- Current coverage: 28.8% (threshold: 90%)
- Affects all downstream predictions using usage_rate

---

## Issue #3: Zero Predictions (P2 HIGH)

### Description
No predictions were generated for 2026-01-26.

### Evidence
```
+-------------------+---------+-------+
| total_predictions | players | games |
+-------------------+---------+-------+
|                 0 |       0 |     0 |
+-------------------+---------+-------+
```

### 7-Day Prediction Coverage
| Date | Predicted | Expected | Coverage |
|------|-----------|----------|----------|
| 2026-01-25 | 99 | 204 | 48.5% |
| 2026-01-24 | 65 | 181 | 35.9% |
| 2026-01-23 | 85 | 247 | 34.4% |
| 2026-01-22 | 82 | 184 | 44.6% |
| 2026-01-21 | 46 | 143 | 32.2% |
| 2026-01-20 | 80 | 169 | 47.3% |

Coverage has been consistently low (32-48%) for the past week.

### Investigation Needed
- [ ] Check Phase 5 processor logs
- [ ] Verify ML feature store has data
- [ ] Check if prediction workflow triggered

---

## Validation Metrics Summary

### Data Completeness (Raw → Analytics)

| Date | Games | Raw | Analytics | % | Minutes % | Usage % |
|------|-------|-----|-----------|---|-----------|---------|
| 2026-01-26 | 7 | 246 | 226 | 91.9% | 69.5% | 28.8% |
| 2026-01-25 | 6 | 212 | 139 | 65.6% | 100% | 35.3% |
| 2026-01-24 | 6 | 209 | 215 | 102.9% | 59.1% | 47.4% |
| 2026-01-23 | 8 | 281 | 281 | 100% | 56.6% | 55.9% |

### Spot Check Results
- **Accuracy**: 20% (2/10 samples passed)
- **Primary Failures**: Usage rate calculation (team stats missing)
- **Secondary Failures**: Rolling average mismatches

### Phase 3 Completion
- Processors complete: 2/5
- Phase 4 triggered: False
- Complete processors:
  - team_offense_game_summary
  - upcoming_player_game_context

---

## Raw Data Sources Status

### NBAC Gamebook (PRIMARY)
- Last processed: 2026-01-27 11:06 AM
- Run ID: `run_20260127_133005_9254da89`
- Source: `nba-com/gamebooks-data/2026-01-26/`
- Status: Data present but accuracy uncertain

### BDL Player Boxscores (FALLBACK)
- Data present for 2026-01-26
- 147 players with non-zero minutes in raw
- Status: Lower stats than NBAC for some players

### ESPN Boxscores
- No data for 2026-01-26
- Last available: Unknown

---

## Investigation Plan

### Phase 1: Verify Source Accuracy
1. Check official NBA.com for Luka's actual Jan 26 stats
2. Compare gamebook PDF with parsed data
3. Determine if NBAC or BDL is correct

### Phase 2: Fix Game_ID Mismatch
1. Verify commit d3066c88 is correct
2. Reprocess Jan 26 analytics
3. Validate usage_rate coverage improves

### Phase 3: Diagnose Prediction Pipeline
1. Check Phase 5 logs for errors
2. Verify ML feature store populated
3. Check if betting data (prop lines) available

### Phase 4: Full Lineage Validation
1. Run `/validate-lineage` for Jan 20-26
2. Identify cascade contamination
3. Plan remediation backfill

---

## Commands Reference

```bash
# Daily health check
./bin/monitoring/daily_health_check.sh

# Main validation
python scripts/validate_tonight_data.py

# Spot checks
python scripts/spot_check_data_accuracy.py --samples 10 --checks rolling_avg,usage_rate

# Check source discrepancy
bq query --use_legacy_sql=false "
WITH nbac AS (
  SELECT player_lookup, game_date, points as nbac_points
  FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
  WHERE game_date = '2026-01-26'
),
bdl AS (
  SELECT player_lookup, game_date, CAST(points AS INT64) as bdl_points
  FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
  WHERE game_date = '2026-01-26'
)
SELECT n.player_lookup, n.nbac_points, b.bdl_points, n.nbac_points - b.bdl_points as diff
FROM nbac n JOIN bdl b ON n.player_lookup = b.player_lookup
WHERE n.nbac_points != b.bdl_points
ORDER BY ABS(n.nbac_points - b.bdl_points) DESC"

# Check game_id JOIN status
bq query --use_legacy_sql=false "
SELECT DISTINCT p.game_id, t.game_id as team_game_id,
  CASE WHEN t.game_id IS NULL THEN 'NO MATCH' ELSE 'MATCHED' END
FROM \`nba-props-platform.nba_analytics.player_game_summary\` p
LEFT JOIN \`nba-props-platform.nba_analytics.team_offense_game_summary\` t
  ON p.game_id = t.game_id AND p.game_date = t.game_date
WHERE p.game_date = '2026-01-26'"
```

---

## Related Documentation

- [Validation Improvements](../validation-coverage-improvements/README.md)
- [Daily Operations Runbook](../../02-operations/daily-operations-runbook.md)
- [Troubleshooting Matrix](../../02-operations/troubleshooting-matrix.md)

---

## Change Log

| Time | Action | Result |
|------|--------|--------|
| 13:34 | Started validation | Found 3 critical issues |
| 13:40 | Documented findings | This file created |
| TBD | Investigation | Pending |
