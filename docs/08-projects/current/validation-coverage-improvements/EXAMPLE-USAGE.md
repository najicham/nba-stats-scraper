# Golden Dataset - Example Usage

This is a complete, copy-paste example of using the Golden Dataset verification system.

---

## Example: Add LeBron James as First Golden Dataset Record

### Step 1: Create the Table (One-Time Setup)

```bash
cd /home/naji/code/nba-stats-scraper

bq query < schemas/bigquery/nba_reference/golden_dataset.sql
```

**Expected output**: `Table 'nba-props-platform:nba_reference.golden_dataset' successfully created.`

---

### Step 2: Generate INSERT Statement

```bash
python scripts/maintenance/populate_golden_dataset.py \
    --players "LeBron James" \
    --date 2024-12-15 \
    --notes "First golden dataset record - high-volume consistent scorer" \
    --output lebron_golden.sql
```

**Expected output**:
```
2026-01-27 10:30:00 - INFO - Fetching golden dataset records...

================================================================================
Processing: LeBron James on 2024-12-15
================================================================================
2026-01-27 10:30:01 - INFO -   Found: lebronjames (ID: 2544)
2026-01-27 10:30:02 - INFO -   Found 35 games before 2024-12-15
2026-01-27 10:30:02 - INFO -   Calculated averages:
2026-01-27 10:30:02 - INFO -     PTS L5:  26.4
2026-01-27 10:30:02 - INFO -     PTS L10: 25.8
2026-01-27 10:30:02 - INFO -     REB L5:  7.2
2026-01-27 10:30:02 - INFO -     AST L5:  8.4

================================================================================
Generated 1 INSERT statement(s)
================================================================================

INSERT statements written to: lebron_golden.sql

⚠️  IMPORTANT: Review these INSERT statements carefully before running!
   Verify the calculated values match expectations.
   Run: bq query < lebron_golden.sql
```

---

### Step 3: Review the Generated SQL

```bash
cat lebron_golden.sql
```

**Expected output** (example):
```sql
INSERT INTO `nba-props-platform.nba_reference.golden_dataset`
  (player_id, player_name, player_lookup, game_date,
   expected_pts_l5, expected_pts_l10, expected_pts_season,
   expected_reb_l5, expected_reb_l10,
   expected_ast_l5, expected_ast_l10,
   expected_minutes_l10, expected_usage_rate_l10,
   verified_by, verified_at, notes, is_active)
VALUES
  ('2544', 'LeBron James', 'lebronjames', '2024-12-15',
   26.4, 25.8, 26.1,
   7.2, 7.5,
   8.4, 8.1,
   35.2, 28.3,
   'script', CURRENT_TIMESTAMP(), 'First golden dataset record - high-volume consistent scorer', TRUE);
```

---

### Step 4: Manually Verify (CRITICAL!)

Don't trust the script blindly! Let's verify manually.

#### 4A. Get Last 5 Games

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  points,
  rebounds_total,
  assists,
  minutes_played
FROM nba_analytics.player_game_summary
WHERE player_lookup = 'lebronjames'
  AND game_date < '2024-12-15'
  AND season = '2024-25'
  AND minutes_played > 0
ORDER BY game_date DESC
LIMIT 5
"
```

**Example output**:
```
+------------+--------+---------------+---------+----------------+
| game_date  | points | rebounds_total| assists | minutes_played |
+------------+--------+---------------+---------+----------------+
| 2024-12-14 |     28 |             8 |       9 |             36 |
| 2024-12-12 |     25 |             7 |       8 |             35 |
| 2024-12-10 |     30 |             6 |       7 |             38 |
| 2024-12-08 |     22 |             8 |      10 |             32 |
| 2024-12-06 |     27 |             7 |       8 |             35 |
+------------+--------+---------------+---------+----------------+
```

#### 4B. Calculate Manually

**Points L5**: (28 + 25 + 30 + 22 + 27) / 5 = 132 / 5 = **26.4** ✓

**Rebounds L5**: (8 + 7 + 6 + 8 + 7) / 5 = 36 / 5 = **7.2** ✓

**Assists L5**: (9 + 8 + 7 + 10 + 8) / 5 = 42 / 5 = **8.4** ✓

**Matches script output?** ✓ YES → Safe to insert!

---

### Step 5: Insert the Record

```bash
bq query < lebron_golden.sql
```

**Expected output**: `Query complete (0 rows affected)`

---

### Step 6: Verify It's in the Table

```bash
bq query --use_legacy_sql=false "
SELECT
  player_name,
  game_date,
  expected_pts_l5,
  expected_pts_l10,
  verified_by,
  is_active
FROM nba_reference.golden_dataset
WHERE player_lookup = 'lebronjames'
"
```

**Expected output**:
```
+---------------+------------+-----------------+------------------+-------------+-----------+
| player_name   | game_date  | expected_pts_l5 | expected_pts_l10 | verified_by | is_active |
+---------------+------------+-----------------+------------------+-------------+-----------+
| LeBron James  | 2024-12-15 |            26.4 |             25.8 | script      |      true |
+---------------+------------+-----------------+------------------+-------------+-----------+
```

---

### Step 7: Run Verification

```bash
python scripts/verify_golden_dataset.py --verbose
```

**Expected output**:
```
2026-01-27 10:35:00 - INFO - Fetching golden dataset records...
2026-01-27 10:35:01 - INFO - Found 1 golden dataset record(s) to verify

================================================================================
Verifying: LeBron James on 2024-12-15
================================================================================
2026-01-27 10:35:02 - INFO - Found 35 games before 2024-12-15
2026-01-27 10:35:02 - INFO - Last 10 games:
  game_date  points  rebounds  assists
  2024-12-14     28         8        9
  2024-12-12     25         7        8
  2024-12-10     30         6        7
  2024-12-08     22         8       10
  2024-12-06     27         7        8
  2024-12-04     24         9        7
  2024-12-02     26         6        9
  2024-11-30     23         8        8
  2024-11-28     28         7        9
  2024-11-26     25         8        7

2026-01-27 10:35:02 - INFO -
Calculated vs Expected:
  points_l5          : expected= 26.40, calculated= 26.40, diff= 0.0000 ✓ PASS
  points_l10         : expected= 25.80, calculated= 25.80, diff= 0.0000 ✓ PASS
  points_season      : expected= 26.10, calculated= 26.10, diff= 0.0000 ✓ PASS
  rebounds_l5        : expected=  7.20, calculated=  7.20, diff= 0.0000 ✓ PASS
  rebounds_l10       : expected=  7.50, calculated=  7.50, diff= 0.0000 ✓ PASS
  assists_l5         : expected=  8.40, calculated=  8.40, diff= 0.0000 ✓ PASS
  assists_l10        : expected=  8.10, calculated=  8.10, diff= 0.0000 ✓ PASS

2026-01-27 10:35:02 - INFO -
Calculated vs Cached:
  points_l5_cache    : calculated= 26.40, cached= 26.40, diff= 0.0000 ✓ PASS
  points_l10_cache   : calculated= 25.80, cached= 25.80, diff= 0.0000 ✓ PASS
  points_season_cache: calculated= 26.10, cached= 26.10, diff= 0.0000 ✓ PASS

2026-01-27 10:35:02 - INFO - ✓ PASS: All checks passed for LeBron James on 2024-12-15

================================================================================
VERIFICATION SUMMARY
================================================================================
Total records checked: 1
  ✓ Passed: 1
  ✗ Failed: 0
  ⚠ Errors: 0
```

**Success!** Your first golden dataset record is working. 🎉

---

## Example: Add Multiple Players at Once

```bash
python scripts/maintenance/populate_golden_dataset.py \
    --players "Stephen Curry,Luka Doncic,Giannis Antetokounmpo,Joel Embiid" \
    --date 2024-12-15 \
    --notes "Expanding golden dataset - diverse scoring styles" \
    --output more_players.sql

# Review the file
cat more_players.sql

# Manually verify at least ONE of them (same process as Step 4 above)

# If verified → insert
bq query < more_players.sql

# Verify all records
python scripts/verify_golden_dataset.py
```

---

## Example: Using in Daily Validation

### As standalone check

```bash
# Quick check (exit code only)
python scripts/verify_golden_dataset.py
echo "Exit code: $?"

# Detailed output
python scripts/verify_golden_dataset.py --verbose
```

### As part of /validate-daily skill

```bash
# In Claude interface
/validate-daily

# When prompted:
# - "What would you like to validate?" → "Yesterday's results"
# - "How thorough?" → "Comprehensive"

# Golden dataset check will run as Phase 3A2
```

---

## Example: Troubleshooting a Failure

### Scenario: Golden dataset check fails

```bash
python scripts/verify_golden_dataset.py
```

**Output shows**:
```
✗ FAIL: 1 check(s) failed for Stephen Curry on 2024-12-15
  - PTS L5: expected=28.40, calculated=27.80, diff=0.6000
```

### Investigation steps

#### 1. Run in verbose mode

```bash
python scripts/verify_golden_dataset.py --player "Stephen Curry" --verbose
```

#### 2. Check raw data

```bash
bq query --use_legacy_sql=false "
SELECT game_date, points
FROM nba_analytics.player_game_summary
WHERE player_lookup = 'stephencurry'
  AND game_date < '2024-12-15'
  AND season = '2024-25'
  AND minutes_played > 0
ORDER BY game_date DESC
LIMIT 5
"
```

#### 3. Calculate manually

Did a game get added/removed? Is the expected value wrong?

#### 4. Check cache vs raw

```bash
# Run with raw-only flag
python scripts/verify_golden_dataset.py --player "Stephen Curry" --raw-only

# If raw-only passes but normal mode fails → cache is stale
python scripts/regenerate_player_daily_cache.py
```

#### 5. Update golden dataset if needed

If the expected value in golden dataset is wrong (e.g., game was retroactively adjusted):

```sql
UPDATE `nba-props-platform.nba_reference.golden_dataset`
SET expected_pts_l5 = 27.80,
    notes = CONCAT(notes, ' [Updated 2024-12-20: Game retroactively adjusted]')
WHERE player_lookup = 'stephencurry'
  AND game_date = '2024-12-15';
```

---

## Common Patterns

### Pattern 1: Weekly Validation

```bash
# Every Monday morning
python scripts/verify_golden_dataset.py

# If passes → confidence in calculation logic
# If fails → investigate immediately (likely regression)
```

### Pattern 2: After Code Deploy

```bash
# Before deploy
python scripts/verify_golden_dataset.py
# → All pass

# Deploy changes to stats_aggregator.py

# After deploy
python scripts/verify_golden_dataset.py
# → If any fail, rollback and investigate
```

### Pattern 3: Monthly Growth

```bash
# First Monday of month
python scripts/maintenance/populate_golden_dataset.py \
    --players "Jayson Tatum,Kevin Durant" \
    --date $(date -d "last week" +%Y-%m-%d) \
    --notes "Monthly expansion $(date +%Y-%m)" \
    --output monthly_golden.sql

bq query < monthly_golden.sql
python scripts/verify_golden_dataset.py
```

---

## Quick Reference

```bash
# Create table (one-time)
bq query < schemas/bigquery/nba_reference/golden_dataset.sql

# Add records (review first!)
python scripts/maintenance/populate_golden_dataset.py --players "Name" --date YYYY-MM-DD --output file.sql
bq query < file.sql

# Verify all
python scripts/verify_golden_dataset.py

# Verify with details
python scripts/verify_golden_dataset.py --verbose

# Check what's in golden dataset
bq query --use_legacy_sql=false "
SELECT player_name, game_date, verified_at
FROM nba_reference.golden_dataset
WHERE is_active = TRUE
ORDER BY game_date DESC
"
```

---

**That's it!** You now have a working Golden Dataset verification system.

Start with 1-2 records, verify they work, then gradually expand to 10-20 records covering diverse players and scenarios.
