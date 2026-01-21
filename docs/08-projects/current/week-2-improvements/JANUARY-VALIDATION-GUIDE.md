# January 2026 Backfill Validation Guide

**Purpose**: Comprehensive validation of January 2026 backfill completion
**Created**: 2026-01-21
**Scripts**: 3 validation tools created

---

## 🎯 Quick Start

Run the complete validation suite:

```bash
# Full validation (recommended)
bash bin/validation/run_complete_january_validation.sh

# Quick mode (skip per-day checks)
bash bin/validation/run_complete_january_validation.sh --quick
```

**Output**: `validation_results/january_2026_complete/final_report.txt`

---

## 📋 Validation Methods

### Method 1: Standard Pipeline Validation (Per-Day)

**Script**: `bin/validation/validate_january_2026.sh`

**What it does**:
- Runs the standard `validate_pipeline.py` for each day in January
- Validates all 6 phases (orchestration → raw → analytics → precompute → predictions → publishing)
- Checks completeness, consistency, and data quality per phase

**How it works**:
1. Loops through Jan 1-21, 2026
2. Runs validation for each date
3. Captures results in individual log files
4. Generates summary with pass/fail/partial counts

**Usage**:
```bash
# Run validation
bash bin/validation/validate_january_2026.sh

# With verbose output
bash bin/validation/validate_january_2026.sh --verbose

# With JSON output
bash bin/validation/validate_january_2026.sh --json-output
```

**Output**:
- `validation_results/january_2026/<date>.log` - Per-day validation logs
- `validation_results/january_2026/summary.txt` - Combined summary

**Success Criteria**:
- All 21 days should PASS
- 0 failed days
- Warnings acceptable if explained

---

### Method 2: Data Quality Analysis

**Script**: `bin/validation/validate_data_quality_january.py`

**What it does**:
Validates data quality from 6 different perspectives:

1. **Temporal Consistency** - Verify data exists for all expected dates
   - Checks each phase has data for all game dates
   - Identifies missing dates by phase

2. **Volume Analysis** - Check for anomalies in record counts
   - Calculates average players/games per day
   - Detects outliers (>2 std deviations from mean)
   - Flags abnormal data volumes

3. **Completeness Ratios** - Verify player coverage vs schedule
   - Compares actual vs expected players (26 per game)
   - Calculates completeness percentage
   - Flags days <80% complete

4. **Cross-Phase Consistency** - Ensure data flows through all phases
   - Compares player counts across Phase 2→3→4
   - Detects >10% player drops between phases
   - Identifies data loss in pipeline

5. **Statistical Anomalies** - Detect outliers in metrics
   - Checks for negative/extreme values
   - Validates FGM≤FGA, FTM≤FTA constraints
   - Detects data quality issues

6. **Missing Data Patterns** - Identify systematic gaps
   - Checks for NULL values in key columns
   - Identifies missing player_lookup, team, stats
   - Detects incomplete records

**Usage**:
```bash
# Run quality analysis
python3 bin/validation/validate_data_quality_january.py

# With detailed output
python3 bin/validation/validate_data_quality_january.py --detailed

# Custom date range
python3 bin/validation/validate_data_quality_january.py \
  --start-date 2026-01-01 \
  --end-date 2026-01-15
```

**Output**:
- Prints colored summary to terminal
- Shows pass/warning/fail for each check
- Lists specific dates/issues found

**Success Criteria**:
- All 6 checks should pass
- Completeness ≥80% for all days
- No statistical anomalies
- <10% player drop between phases

---

### Method 3: Complete Validation Suite

**Script**: `bin/validation/run_complete_january_validation.sh`

**What it does**:
- Runs both validation methods above
- Generates comprehensive combined report
- Includes additional validation recommendations

**How it works**:
1. Runs data quality analysis
2. Runs per-day pipeline validation (unless --quick)
3. Combines results into final report
4. Provides next steps and approval checklist

**Usage**:
```bash
# Full validation (recommended)
bash bin/validation/run_complete_january_validation.sh

# Quick mode (skip per-day checks, ~2 min)
bash bin/validation/run_complete_january_validation.sh --quick
```

**Output**:
- `validation_results/january_2026_complete/final_report.txt` - **Main deliverable**
- `validation_results/january_2026_complete/data_quality.txt` - Quality analysis
- `validation_results/january_2026_complete/pipeline_summary.txt` - Per-day summary
- `validation_results/january_2026_complete/pipeline_validation/` - Individual logs

**Estimated Time**:
- Full mode: 15-20 minutes
- Quick mode: 2-3 minutes

---

## 🔍 Additional Validation Approaches

Beyond the automated scripts, consider these manual checks:

### 1. Spot Check Validation

Pick 3-5 random dates and manually verify:

```bash
# Example: Validate Jan 15
python3 bin/validate_pipeline.py 2026-01-15 --verbose --show-missing

# Check against official sources
# - NBA.com box scores
# - ESPN game summaries
# - Basketball Reference
```

### 2. Grading Accuracy Check

Verify prediction grading for completed games:

```sql
-- Check grading coverage
SELECT
  game_date,
  COUNT(*) as graded_predictions,
  COUNT(DISTINCT player_lookup) as graded_players
FROM `nba_predictions.prediction_grading`
WHERE game_date BETWEEN '2026-01-01' AND '2026-01-21'
GROUP BY game_date
ORDER BY game_date;

-- Expected: 70-90% grading coverage
-- Should have data for every game date
```

### 3. Time Series Analysis

Plot daily metrics to spot trends:

```sql
-- Daily player counts
SELECT
  game_date,
  COUNT(*) as player_count,
  COUNT(DISTINCT game_id) as game_count
FROM `nba_raw.nbac_player_boxscore`
WHERE game_date BETWEEN '2026-01-01' AND '2026-01-21'
GROUP BY game_date
ORDER BY game_date;

-- Plot in spreadsheet or BI tool
-- Look for: Gaps, spikes, declining trends
```

### 4. Comparison with Previous Month

Compare December 2025 vs January 2026:

```sql
-- Compare volumes
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(*) as total_players,
  COUNT(DISTINCT game_id) as total_games,
  ROUND(COUNT(*) / COUNT(DISTINCT game_id), 1) as avg_players_per_game
FROM `nba_raw.nbac_player_boxscore`
WHERE game_date BETWEEN '2025-12-01' AND '2026-01-31'
GROUP BY month
ORDER BY month;

-- Should have similar patterns and volumes
-- January should not show degradation
```

### 5. Manual Star Player Verification

Pick 2-3 high-profile games and verify star player stats:

```sql
-- Example: LeBron James on Jan 15
SELECT
  game_date,
  player_lookup,
  team,
  points,
  rebounds,
  assists,
  minutes
FROM `nba_raw.nbac_player_boxscore`
WHERE game_date = '2026-01-15'
  AND player_lookup = 'lebronjames'
;

-- Manually compare against:
-- - NBA.com box score
-- - ESPN game summary
-- - Basketball Reference
```

### 6. Downstream Impact Check

Verify data reached downstream systems:

```bash
# Check GCS exports
gsutil ls gs://nba-predictions-export/daily/2026-01-15/

# Expected files:
# - predictions.json
# - best_bets.json
# - player_reports.json
# - etc.

# Verify JSON structure
gsutil cat gs://nba-predictions-export/daily/2026-01-15/predictions.json | jq '.' | head -50

# Check web app (if applicable)
# - Visit prediction dashboard
# - Verify Jan 1-21 dates show predictions
# - Check for missing dates or errors
```

---

## ✅ Validation Approval Checklist

Before declaring January 2026 backfill complete, verify:

**Automated Validation**:
- [ ] All dates have data across all phases (temporal consistency)
- [ ] Player counts are within expected ranges (volume analysis)
- [ ] No statistical anomalies detected (data quality)
- [ ] Cross-phase consistency maintained (<10% drop)
- [ ] Completeness ≥80% for all days
- [ ] Standard pipeline validation passed for all days

**Manual Verification**:
- [ ] Grading coverage is 70-90%+ for completed games
- [ ] Spot checks pass for 3-5 random dates
- [ ] Star player stats match official sources
- [ ] No systematic gaps in data collection

**Downstream Validation**:
- [ ] Web app showing predictions correctly
- [ ] GCS exports are complete and well-formed
- [ ] No errors in downstream consumers

**Comparison Checks**:
- [ ] January volumes similar to December
- [ ] No degradation in data quality
- [ ] Similar patterns and distributions

---

## 📊 Expected Results

### Successful Validation

A successful January 2026 backfill should show:

1. **Coverage**: 100% of game dates have data
2. **Completeness**: ≥80% player coverage per game
3. **Consistency**: <10% player drop between phases
4. **Quality**: No statistical anomalies
5. **Grading**: 70-90% prediction grading coverage
6. **Volume**: ~13 players per team, 2 teams per game = ~26 players/game

### Common Issues & Resolutions

**Issue**: Missing dates in Phase 3/4
- **Cause**: Analytics/Precompute processors not triggered
- **Fix**: Manually trigger processors for missing dates
- **See**: `docs/02-operations/backfill-guide.md`

**Issue**: Low completeness (<80%)
- **Cause**: Partial boxscore data from source
- **Fix**: Re-scrape source data if available
- **Note**: May be acceptable if source data incomplete

**Issue**: Player drops between phases
- **Cause**: Validation filters (e.g., minutes_played threshold)
- **Fix**: Check if drops are intentional filters
- **Verify**: Review processor validation logic

**Issue**: Statistical anomalies
- **Cause**: Source data quality issue or parsing error
- **Fix**: Investigate specific records, may need source data correction

---

## 🚀 Running the Validation

### Recommended Workflow

1. **Run quick validation** (2-3 min)
   ```bash
   bash bin/validation/run_complete_january_validation.sh --quick
   ```

2. **Review results**
   ```bash
   cat validation_results/january_2026_complete/final_report.txt
   ```

3. **If issues found**, run full validation
   ```bash
   bash bin/validation/run_complete_january_validation.sh
   ```

4. **Investigate failures**
   ```bash
   # Check specific date
   python3 bin/validate_pipeline.py 2026-01-15 --verbose --show-missing
   ```

5. **Manual spot checks**
   - Pick 3-5 random dates
   - Verify against official sources
   - Check grading coverage

6. **Approval**
   - Complete checklist above
   - Document findings
   - Sign off on backfill

---

## 📁 Output Files

All validation results saved to `validation_results/january_2026_complete/`:

- **final_report.txt** - Main deliverable, combined summary
- **data_quality.txt** - Quality analysis results
- **pipeline_summary.txt** - Per-day validation summary
- **pipeline_validation/\<date\>.log** - Individual date logs

---

## 📞 Troubleshooting

### Validation Script Fails

```bash
# Check Python dependencies
pip3 install google-cloud-bigquery pandas

# Check BigQuery access
gcloud auth application-default login

# Check project ID
echo $GCP_PROJECT_ID
```

### Permission Errors

```bash
# Ensure proper GCP permissions
gcloud projects get-iam-policy $GCP_PROJECT_ID

# Need: BigQuery Data Viewer, Firestore Viewer
```

### Slow Performance

```bash
# Use quick mode
bash bin/validation/run_complete_january_validation.sh --quick

# Or validate specific date range
python3 bin/validation/validate_data_quality_january.py \
  --start-date 2026-01-15 \
  --end-date 2026-01-21
```

---

## 📚 Related Documentation

- `docs/02-operations/backfill-guide.md` - Backfill procedures
- `docs/02-operations/daily-operations.md` - Daily validation
- `bin/validate_pipeline.py` - Standard validation script
- `shared/validation/` - Validation library code

---

**Created**: 2026-01-21
**Author**: Week 2 Analysis Session
**Status**: Ready to use
**Next**: Run validation and review results
