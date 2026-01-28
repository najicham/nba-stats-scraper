# Golden Dataset Verification System - Implementation Guide

**Created**: 2026-01-27
**Status**: Implemented
**Purpose**: High-confidence verification of rolling average calculations

---

## Overview

The Golden Dataset is a manually verified set of player-date combinations with known-correct rolling averages. This system provides 100% confidence validation of calculation logic, complementing the statistical spot-check system.

### Why Golden Dataset?

**Spot checks** (random sampling):
- Good for detecting widespread issues
- Statistical confidence (95%+)
- Fast, can run on many samples

**Golden dataset** (verified ground truth):
- Perfect for detecting calculation regressions
- 100% confidence (manually verified)
- Slower, runs on curated set (~10-20 records)

**Use both**: Spot checks for breadth, golden dataset for depth.

---

## Components

### 1. BigQuery Table

**Location**: `nba-props-platform.nba_reference.golden_dataset`

**Schema**: See `/home/naji/code/nba-stats-scraper/schemas/bigquery/nba_reference/golden_dataset.sql`

**Key fields**:
- `player_lookup`, `game_date` - Identifier
- `expected_pts_l5`, `expected_pts_l10` - Manually verified values
- `expected_reb_l5`, `expected_ast_l5` - Other stats
- `verified_by`, `verified_at` - Audit trail
- `is_active` - Toggle for active validation

### 2. Verification Script

**Location**: `/home/naji/code/nba-stats-scraper/scripts/verify_golden_dataset.py`

**Usage**:
```bash
# Verify all active records
python scripts/verify_golden_dataset.py

# Verify specific player
python scripts/verify_golden_dataset.py --player "LeBron James"

# Verify specific date
python scripts/verify_golden_dataset.py --date 2024-12-15

# Verbose output (shows calculations)
python scripts/verify_golden_dataset.py --verbose

# Custom tolerance (default 0.1)
python scripts/verify_golden_dataset.py --tolerance 0.05

# Skip cache comparison (only check raw calculation)
python scripts/verify_golden_dataset.py --raw-only
```

**What it does**:
1. Queries golden dataset records
2. For each record:
   - Fetches player's game history before date
   - Calculates rolling averages using same logic as `stats_aggregator.py`
   - Compares to expected values in golden dataset
   - Compares to cached values in `player_daily_cache`
3. Reports PASS/FAIL for each check
4. Returns exit code 0 (all pass) or 1 (any fail)

### 3. Population Helper Script

**Location**: `/home/naji/code/nba-stats-scraper/scripts/maintenance/populate_golden_dataset.py`

**Usage**:
```bash
# Generate INSERT statements for review
python scripts/maintenance/populate_golden_dataset.py \
    --players "LeBron James,Stephen Curry,Luka Doncic" \
    --date 2024-12-15 \
    --notes "Mid-season verification set" \
    --output golden_inserts.sql

# Review the generated SQL
cat golden_inserts.sql

# Run after manual verification
bq query < golden_inserts.sql
```

**Important**: Always review calculated values before inserting!

---

## How to Add Golden Dataset Records

### Step 1: Choose Good Candidates

**Selection criteria**:
- High-volume players (play most games)
- Starters (high minutes)
- Mix of positions/styles
- Recent games (within current season)

**Recommended players**:
- LeBron James (high-volume, consistent)
- Stephen Curry (3PT specialist)
- Luka Doncic (triple-double threat)
- Giannis Antetokounmpo (paint scorer)
- Joel Embiid (high-volume big)
- Jayson Tatum (versatile scorer)

### Step 2: Generate INSERT Statements

```bash
python scripts/maintenance/populate_golden_dataset.py \
    --players "LeBron James,Stephen Curry" \
    --date 2024-12-15 \
    --notes "Initial golden dataset" \
    --output golden_inserts.sql
```

### Step 3: Manual Verification

**CRITICAL**: Don't trust the script blindly! Manually verify at least one player:

1. Check the calculated values:
   ```bash
   # Get last 5 games before date
   bq query --use_legacy_sql=false "
   SELECT game_date, points, rebounds_total, assists
   FROM nba_analytics.player_game_summary
   WHERE player_lookup = 'lebronjames'
     AND game_date < '2024-12-15'
     AND season = '2024-25'
     AND minutes_played > 0
   ORDER BY game_date DESC
   LIMIT 5
   "
   ```

2. Calculate average manually (use calculator or spreadsheet)

3. Compare to script output

4. If matches → good to proceed
   If doesn't match → investigate before inserting!

### Step 4: Insert into BigQuery

```bash
# After verification
bq query < golden_inserts.sql
```

### Step 5: Verify It Works

```bash
python scripts/verify_golden_dataset.py --verbose
```

Expected: All checks PASS

---

## Integration with /validate-daily

The golden dataset verification is integrated as **Phase 3A2** in the validate-daily skill.

**When to run**:
- After cache regeneration (verify correctness)
- Weekly as part of comprehensive validation
- When spot check accuracy is borderline (90-95%)
- After code changes to `stats_aggregator.py`

**How to run in validation**:
```bash
# As part of comprehensive validation
python scripts/verify_golden_dataset.py

# Or with verbose output for investigation
python scripts/verify_golden_dataset.py --verbose
```

**Exit code interpretation**:
- `0` = PASS (all golden dataset records match)
- `1` = FAIL (at least one mismatch or error)

---

## Tolerance Threshold

**Default**: 0.1 points

**Justification**:
- Rolling averages rounded to 4 decimal places
- Display precision typically 1 decimal place
- 0.1 point difference over 5 games = 0.02 ppg (negligible)
- Catches real errors, avoids floating-point false positives

**When to adjust**:
- Use stricter (0.05) for critical validation after code changes
- Use looser (0.2) if floating-point accumulation is suspected

---

## Maintenance

### Growing the Dataset

Start with 5-10 player-dates, grow to 20-30 over time:

**Phase 1** (Initial - 5-10 records):
- Top 5 high-volume players
- One date each from mid-season

**Phase 2** (Expand - 10-20 records):
- Add more positions (centers, guards, forwards)
- Add edge cases (rookies, low-minute players)

**Phase 3** (Comprehensive - 20-30 records):
- Multiple dates per player (season progression)
- Include trade scenarios
- Include injury returns

### Keeping It Current

**Recommended cadence**:
- Add 2-3 new records per month
- Update notes if player changes teams
- Mark old records `is_active = FALSE` after season ends

**Checklist for new season**:
1. Mark previous season records as inactive
2. Generate new set for current season (same players)
3. Verify current season data quality first
4. Add new star players who emerged

### Deactivating Records

```sql
UPDATE `nba-props-platform.nba_reference.golden_dataset`
SET is_active = FALSE,
    notes = CONCAT(notes, ' [Archived: 2025-06-01]')
WHERE game_date < '2024-10-01';  -- Before current season
```

---

## Troubleshooting

### All Checks Failing

**Symptom**: Every golden dataset record fails verification

**Likely causes**:
1. **Calculation logic changed** - Check recent commits to `stats_aggregator.py`
2. **Cache not updated** - Regenerate `player_daily_cache`
3. **Schema change** - Verify column names in queries

**Action**: Run with `--raw-only` to isolate cache vs calculation issue

### Specific Player Failing

**Symptom**: One player fails, others pass

**Likely causes**:
1. **Trade/roster change** - Player lookup may have changed
2. **Missing games** - Check if games before date exist
3. **Data quality** - Run `/spot-check-player <name>` for deep dive

**Action**: Run verbose mode for that player:
```bash
python scripts/verify_golden_dataset.py --player "Player Name" --verbose
```

### Cache Mismatch

**Symptom**: Raw calculation matches expected, but cache different

**Likely cause**: Cache stale or not regenerated

**Action**:
```bash
python scripts/regenerate_player_daily_cache.py
python scripts/verify_golden_dataset.py
```

---

## Example: Adding First Golden Dataset Record

```bash
# Step 1: Generate INSERT for LeBron James on Dec 15, 2024
python scripts/maintenance/populate_golden_dataset.py \
    --players "LeBron James" \
    --date 2024-12-15 \
    --notes "Initial golden dataset - high-volume consistent scorer" \
    --output lebron_golden.sql

# Step 2: Review the calculated values
cat lebron_golden.sql

# Step 3: Manually verify last 5 games
bq query --use_legacy_sql=false "
SELECT game_date, points
FROM nba_analytics.player_game_summary
WHERE player_lookup = 'lebronjames'
  AND game_date < '2024-12-15'
  AND season = '2024-25'
  AND minutes_played > 0
ORDER BY game_date DESC
LIMIT 5
"

# Step 4: Calculate average manually
# Example: 28, 25, 30, 22, 27 → avg = 26.4

# Step 5: If matches script output → insert
bq query < lebron_golden.sql

# Step 6: Verify it works
python scripts/verify_golden_dataset.py --verbose
```

---

## Benefits

1. **Regression Detection**: Catches bugs in calculation logic immediately
2. **High Confidence**: 100% certainty on verified records (vs 95% statistical)
3. **Code Change Safety**: Run before/after code changes to `stats_aggregator.py`
4. **Debugging Aid**: Known-good records help isolate issues
5. **Documentation**: Serves as executable specification of calculation logic

---

## Best Practices

1. **Start Small**: 5-10 records initially, grow over time
2. **Verify Manually**: Always manually check at least one record before bulk insert
3. **Diverse Coverage**: Mix of positions, scoring styles, minutes played
4. **Document Notes**: Add context (trade, injury return, season phase)
5. **Run Regularly**: Weekly as part of comprehensive validation
6. **Keep Updated**: Add 2-3 records per month, archive old seasons
7. **Verbose Debugging**: Use `--verbose` when investigating failures

---

## Related Documentation

- **Investigation findings**: `02-INVESTIGATION-FINDINGS.md`
- **Stats aggregator code**: `data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py`
- **Validate-daily skill**: `.claude/skills/validate-daily/SKILL.md`
- **Spot check system**: `scripts/spot_check_data_accuracy.py`

---

## Quick Reference

```bash
# Verify all golden dataset records
python scripts/verify_golden_dataset.py

# Add new records (review before inserting!)
python scripts/maintenance/populate_golden_dataset.py \
    --players "Player Name" --date YYYY-MM-DD --output file.sql

# Check what's in golden dataset
bq query --use_legacy_sql=false "
SELECT player_name, game_date, verified_at
FROM nba_reference.golden_dataset
WHERE is_active = TRUE
ORDER BY game_date DESC
"

# Run as part of daily validation
/validate-daily
# → Select "Comprehensive" thoroughness to include golden dataset check
```

---

**Status**: Ready for production use
**Next Steps**: Add initial 5-10 records covering top players
**Owner**: Data quality team
