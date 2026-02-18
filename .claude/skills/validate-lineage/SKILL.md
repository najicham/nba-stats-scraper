# Skill: validate-lineage

## Purpose

Validate data lineage integrity - ensure computed data was calculated with complete, correct upstream dependencies. Detects "cascade contamination" where records were computed while dependencies were missing.

## When to Use

- After backfill operations to verify data correctness
- Quarterly data quality audits
- When investigating suspicious predictions or model drift
- After major pipeline incidents

## Usage

```bash
# Interactive mode (recommended for first time)
/validate-lineage interactive

# Quick modes
/validate-lineage [mode] [options]
```

### Quick Examples

```bash
# Guided workflow with questions
/validate-lineage interactive

# Quick health check
/validate-lineage quick

# Validate after backfill
/validate-lineage standard --start-date 2025-11-01 --end-date 2025-11-30

# Investigate specific date
/validate-lineage investigate 2025-11-10

# Check quality metadata
/validate-lineage quality-trends --start-date 2025-11-01 --end-date 2025-11-30

# Find incomplete windows
/validate-lineage incomplete-windows --days 7

# Get remediation plan
/validate-lineage remediate --start-date 2025-11-01 --end-date 2025-11-30
```

### Modes

| Mode | Description | Speed |
|------|-------------|-------|
| `interactive` | **Guided workflow with questions** | Variable |
| `quick` | Aggregate validation only (Tier 1) | Fast (~2 min) |
| `standard` | Aggregate + sample validation (Tier 1-2) | Medium (~10 min) |
| `thorough` | Full validation with spot checks (Tier 1-3) | Slow (~30 min) |
| `investigate <date>` | Deep dive on specific date | Variable |
| `recompute <date>` | Recompute and compare all records for date | Slow |

### Interactive Mode

**Usage**: `/validate-lineage interactive`

The interactive mode guides you through validation with questions:

#### Question Flow

1. **What do you want to validate?**
   - Recent data (last 7 days)
   - Specific date range
   - After backfill operation
   - Full season quality audit
   - Investigate specific issue

2. **Which layer?**
   - Analytics (Phase 3: player_game_summary, team stats)
   - Precompute (Phase 4: composite factors, rolling windows)
   - Predictions (Phase 5: model outputs)
   - All layers (full pipeline)

3. **What level of detail?**
   - Quick check (aggregate only, ~2 min)
   - Standard validation (with sampling, ~10 min)
   - Thorough audit (full analysis, ~30 min)

4. **Quality focus?** (if new quality metadata available)
   - Check quality score trends
   - Find incomplete windows
   - Detect late-arriving data
   - Compare processing contexts

5. **Date range?** (based on your choice in #1)
   - Auto-suggests based on context
   - Recent: Last 7 days
   - Backfill: You specify dates
   - Season: Current season dates

6. **Execute validation**
   - Shows what will run
   - Asks for confirmation
   - Runs validation
   - Shows results

7. **Remediation?** (if issues found)
   - View contaminated dates
   - Generate reprocessing commands
   - Execute fixes (with confirmation)
   - Validate fixes

#### Example Interactive Session

```
/validate-lineage interactive

> What do you want to validate?
  1. Recent data (last 7 days) - Quick health check
  2. Specific date range - Custom validation
  3. After backfill operation - Verify backfill quality
  4. Full season quality audit - Comprehensive check
  5. Investigate specific issue - Deep dive

Your choice: 3

> You ran a backfill. What date range did you backfill?
Start date (YYYY-MM-DD): 2025-11-01
End date (YYYY-MM-DD): 2025-11-30

> Which layer did you backfill?
  1. Analytics (Phase 3)
  2. Precompute (Phase 4) - Recommended
  3. Predictions (Phase 5)
  4. All layers

Your choice: 2

> What level of detail?
  1. Quick check - Aggregate validation (~2 min)
  2. Standard validation - With sampling (~10 min) - Recommended
  3. Thorough audit - Full analysis (~30 min)

Your choice: 2

> Include quality metadata checks? (New feature - tracks incomplete windows)
  Yes / No: Yes

=== Running Validation ===
Layer: Precompute (Phase 4)
Date Range: 2025-11-01 to 2025-11-30
Mode: Standard (with sampling)
Quality Checks: Enabled

[Progress bar...]

=== Results ===
✓ Tier 1: Aggregate validation passed
⚠ Tier 2: Found issues in 3 dates

Flagged Dates:
  2025-11-10: 78% quality score (16% incomplete windows)
  2025-11-15: 82% quality score (6% incomplete windows)
  2025-11-20: 91% quality score (2% incomplete windows)

> What would you like to do?
  1. View detailed breakdown
  2. Generate remediation commands
  3. Execute fixes now
  4. Save report and exit

Your choice: 2

=== Remediation Commands ===

Priority 1: Critical (quality < 80%)
  Date: 2025-11-10
  Command: python scripts/backfill_phase4.py --start-date 2025-11-10 --end-date 2025-11-10

Priority 2: Review (quality 80-90%)
  Date: 2025-11-15
  Command: python scripts/backfill_phase4.py --start-date 2025-11-15 --end-date 2025-11-15

> Execute Priority 1 commands now?
  Yes / No: No

Commands saved to: /tmp/lineage_remediation_20260126.sh
Run manually: bash /tmp/lineage_remediation_20260126.sh

✓ Validation complete
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--season <YYYY-YY>` | Season to validate | Current |
| `--start-date <YYYY-MM-DD>` | Start of date range | Season start |
| `--end-date <YYYY-MM-DD>` | End of date range | Today |
| `--layer <layer>` | Specific layer to validate | All |
| `--threshold <pct>` | Difference threshold for flagging | 1% |
| `--sample-size <n>` | Records per date for Tier 2 | 50 |

### Layers

- `raw` - Raw game data (bdl_player_boxscores)
- `analytics` - Game summaries (player_game_summary)
- `precompute` - Derived metrics (player_composite_factors)
- `predictions` - Model outputs (player_prop_predictions)
- `all` - Full pipeline validation

## Validation Methodology

### Tier 1: Aggregate Validation

For each date, compare stored aggregates to recomputed:

```sql
-- Stored
SELECT game_date, AVG(points_composite) as avg_composite
FROM nba_precompute.player_composite_factors
WHERE game_date = @date
GROUP BY game_date

-- Recomputed (from upstream)
SELECT game_date, AVG(computed_composite) as avg_composite
FROM (
    -- Recompute composite from player_game_summary
    SELECT ...
)
GROUP BY game_date
```

**Pass criteria**: Difference < threshold (default 1%)

### Tier 2: Sample Validation

For dates flagged in Tier 1, validate individual records:

```python
for date in flagged_dates:
    sample = random_sample(date, n=50)
    for record in sample:
        stored = get_stored_value(record)
        computed = recompute_from_upstream(record)
        if abs(stored - computed) / stored > threshold:
            flag_as_contaminated(record)
```

**Pass criteria**: <5% of sample records differ

### Tier 3: Spot Check

Validate random records from "normal" dates to ensure no systemic issues.

## Output

### Quick Mode Output

```
=== Data Lineage Validation (Quick) ===
Season: 2025-26
Date Range: 2025-10-22 to 2026-01-26
Layer: precompute

Tier 1: Aggregate Validation
─────────────────────────────
Total dates checked: 96
Dates with differences: 12
Dates > 1% threshold: 3

Flagged Dates:
  2025-11-10: 2.3% difference (NEEDS REVIEW)
  2025-11-15: 1.8% difference (NEEDS REVIEW)
  2025-12-03: 1.2% difference (NEEDS REVIEW)

Recommendation: Run /validate-lineage standard to investigate flagged dates
```

### Standard Mode Output

```
=== Data Lineage Validation (Standard) ===
Season: 2025-26
Date Range: 2025-10-22 to 2026-01-26
Layer: precompute

Tier 1: Aggregate Validation
─────────────────────────────
Total dates: 96
Flagged dates: 3

Tier 2: Sample Validation (50 records per flagged date)
───────────────────────────────────────────────────────
Date        Sampled  Contaminated  Rate    Status
2025-11-10  50       8             16%     CONTAMINATED
2025-11-15  50       3             6%      CONTAMINATED
2025-12-03  50       1             2%      MARGINAL

Contamination Summary:
  Confirmed contaminated dates: 2
  Marginal dates: 1
  Estimated contaminated records: ~800

Recommendation: Reprocess 2025-11-10 and 2025-11-15
  Command: python scripts/backfill_phase4.py --start-date 2025-11-10 --end-date 2025-11-15
```

### Thorough Mode Output

Includes all above plus:
- Tier 3 spot check results
- Per-player contamination breakdown
- Lineage trace for worst cases
- Statistical confidence intervals

## Sample Size Guidelines

| Scenario | Tier 1 | Tier 2 | Tier 3 | Total Queries |
|----------|--------|--------|--------|---------------|
| Quick audit | All dates | 0 | 0 | ~100 |
| Standard validation | All dates | 50/flagged | 0 | ~200-500 |
| Thorough audit | All dates | 100/flagged | 100 | ~500-1000 |
| Full recompute | All dates | All records | All records | ~20,000+ |

## Automation

### Scheduled Validation

Add to weekly/monthly cron:

```bash
# Weekly quick check
0 6 * * 0 /validate-lineage quick --season 2025-26

# Monthly standard validation
0 6 1 * * /validate-lineage standard --season 2025-26
```

### Post-Backfill Validation

After any backfill operation, run:

```bash
/validate-lineage investigate <backfilled-date>
```

## Remediation

When contamination is found:

1. **Identify scope**: Which dates and players affected?
2. **Trace upstream**: What was the root cause (missing game, late data)?
3. **Reprocess**: Run backfill for affected date range
4. **Validate**: Re-run validation to confirm fix

```bash
# Reprocess contaminated dates
python scripts/backfill_phase3.py --start-date 2025-11-10 --end-date 2025-11-15
python scripts/backfill_phase4.py --start-date 2025-11-10 --end-date 2025-11-15

# Validate fix
/validate-lineage investigate 2025-11-10
```

## New Capabilities (2026-01-26)

### Quality Metadata Analysis

With the new quality metadata columns, the skill now supports:

#### 1. Quality Score Distribution

Check quality_score distribution by date to identify degraded data:

```sql
SELECT
  game_date,
  processing_context,
  COUNT(*) as record_count,
  AVG(quality_score) as avg_quality,
  MIN(quality_score) as min_quality,
  COUNTIF(quality_score < 0.7) as low_quality_count,
  COUNTIF(quality_score >= 1.0) as perfect_count
FROM `nba_precompute.player_daily_cache`
WHERE game_date BETWEEN @start_date AND @end_date
GROUP BY game_date, processing_context
HAVING avg_quality < 0.9 OR low_quality_count > 0
ORDER BY avg_quality ASC, game_date DESC;
```

**Usage**:
```
/validate-lineage quality-trends --start-date 2025-10-22 --end-date 2026-01-26
```

**Output**:
```
=== Quality Score Trends ===
Date        Context    Avg Quality  Low Quality Count  Status
2025-11-10  backfill   0.78        23                  DEGRADED
2025-11-15  cascade    0.82        15                  DEGRADED
2025-12-03  daily      0.91        3                   OK
2026-01-20  daily      0.95        0                   GOOD
```

#### 2. Incomplete Window Detection

Find records with incomplete rolling windows:

```sql
SELECT
  player_lookup,
  game_date,
  quality_score,
  window_completeness,
  -- List incomplete windows
  CONCAT(
    IF(NOT points_l5_complete, 'L5,', ''),
    IF(NOT points_l10_complete, 'L10,', ''),
    IF(NOT points_l7d_complete, 'L7d,', ''),
    IF(NOT points_l14d_complete, 'L14d,', '')
  ) as incomplete_windows,
  -- Count NULL rolling averages
  COUNTIF(points_l5_avg IS NULL) + COUNTIF(points_l10_avg IS NULL) as null_count
FROM `nba_precompute.player_daily_cache`
WHERE game_date BETWEEN @start_date AND @end_date
  AND (
    NOT points_l5_complete
    OR NOT points_l10_complete
    OR NOT points_l7d_complete
    OR NOT points_l14d_complete
  )
ORDER BY game_date DESC, quality_score ASC
LIMIT 100;
```

**Usage**:
```
/validate-lineage incomplete-windows --start-date 2025-11-01 --end-date 2025-11-30
```

**Output**:
```
=== Incomplete Windows Report ===
Found 47 players with incomplete windows in November 2025

Player              Date        Quality  Incomplete Windows  NULL Count
lebron_james        2025-11-10  0.70     L10,L7d            2
stephen_curry       2025-11-10  0.65     L10,L7d,L14d       3
kevin_durant        2025-11-15  0.75     L10                1

Summary:
  Total records affected: 47
  Dates with issues: 3
  Most common: L10 (40 records), L7d (25 records)

Action: These records were correctly marked incomplete. NULLs prevent
        contaminated averages. If data is now available, reprocess:
        python scripts/backfill_phase4.py --start-date 2025-11-10 --end-date 2025-11-15
```

#### 3. Stored vs Recomputed Comparison

Compare stored quality_score to freshly recomputed completeness:

```python
def validate_quality_metadata(date_range):
    """
    Validate that stored quality scores match current completeness.
    Detects if data arrived late after initial processing.
    """
    for date in date_range:
        # Get stored quality scores
        stored = query_stored_quality(date)

        # Recompute completeness now
        recomputed = recompute_completeness(date)

        # Compare
        for player in stored:
            stored_quality = stored[player]['quality_score']
            current_completeness = recomputed[player]['completeness_pct']

            if current_completeness - stored_quality > 0.1:  # 10% improvement
                flag_late_arrival(player, date, stored_quality, current_completeness)
```

**Usage**:
```
/validate-lineage quality-metadata 2025-11-10
```

**Output**:
```
=== Quality Metadata Validation: 2025-11-10 ===

Late Data Arrivals (quality improved since processing):
Player              Stored Quality  Current Completeness  Delta
lebron_james        0.70           0.90                  +0.20  LATE DATA
stephen_curry       0.80           1.00                  +0.20  LATE DATA
kevin_durant        0.75           0.85                  +0.10  MARGINAL

Summary: 2 players had significant late data (>10% improvement)
  - These records were correctly computed with partial data at the time
  - Current completeness is higher, suggesting data arrived late
  - Records are flagged with processing_context='cascade' or 'backfill'

Recommendation: If these records need perfect data, reprocess:
  python scripts/backfill_phase4.py --start-date 2025-11-10 --end-date 2025-11-10 --force
```

#### 4. Processing Context Analysis

Analyze distribution of processing contexts:

```sql
SELECT
  processing_context,
  COUNT(*) as record_count,
  AVG(quality_score) as avg_quality,
  COUNT(DISTINCT game_date) as date_count,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM `nba_precompute.player_daily_cache`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY processing_context
ORDER BY processing_context;
```

**Usage**:
```
/validate-lineage processing-context --days 90
```

**Output**:
```
=== Processing Context Distribution (Last 90 Days) ===

Context     Records   Avg Quality  Dates  Date Range
daily       8,452     0.97        85     2025-10-28 to 2026-01-26
backfill    1,234     0.82        23     2025-10-22 to 2025-11-15
cascade     456       0.88        8      2025-11-10 to 2025-11-20
manual      12        0.95        2      2025-12-15 to 2025-12-16

Analysis:
  ✓ Daily processing is dominant (87% of records) with high quality
  ⚠ Backfill records have lower quality (0.82) - expected for historical data
  ⚠ 8 dates triggered cascade reprocessing - investigate root cause

Quality by Context:
  daily:    97% avg (excellent)
  cascade:  88% avg (acceptable, data was late)
  backfill: 82% avg (acceptable, bootstrap period)
```

#### 5. Remediation Recommendations

Generate targeted remediation based on quality metadata:

**Usage**:
```
/validate-lineage remediate --start-date 2025-11-01 --end-date 2025-11-30
```

**Output**:
```
=== Remediation Recommendations: November 2025 ===

Priority 1: Critical Quality Issues (quality_score < 0.7)
───────────────────────────────────────────────────────
Date        Records  Avg Quality  Action
2025-11-10  45       0.68        REPROCESS REQUIRED
2025-11-15  23       0.65        REPROCESS REQUIRED

Commands:
  python scripts/backfill_phase3.py --start-date 2025-11-10 --end-date 2025-11-15
  python scripts/backfill_phase4.py --start-date 2025-11-10 --end-date 2025-11-15

Priority 2: Incomplete Windows (quality_score 0.7-0.9)
──────────────────────────────────────────────────────
Date        Records  Action
2025-11-12  18       Review - may improve with time
2025-11-18  12       Review - may improve with time

Priority 3: Monitoring (quality_score > 0.9)
────────────────────────────────────────────
Date        Records  Status
2025-11-20  156      GOOD
2025-11-25  142      GOOD

Summary:
  - 68 records need immediate reprocessing
  - 30 records to monitor (data may arrive late)
  - 298 records in good state

Estimated Impact:
  - Reprocessing 2 dates will fix ~68 contaminated records
  - Downstream predictions for these players should be regenerated
```

### Enhanced Validation Modes

The skill now includes quality-aware validation:

**New Mode: `quality-aware`**
```
/validate-lineage quality-aware --start-date 2025-11-01 --end-date 2025-11-30
```

This mode:
1. Checks stored quality_score against thresholds
2. Validates that NULL values exist where quality_score < 0.7
3. Ensures processing_context matches actual timing
4. Verifies gate_status is appropriate for quality_score

## Implementation Notes

### Interactive Mode Implementation

The interactive mode uses Claude's `AskUserQuestion` tool to create a guided workflow:

```python
# Step 1: Ask what to validate
response = ask_user_question(
    question="What do you want to validate?",
    options=[
        {"label": "Recent data (last 7 days)", "description": "Quick health check"},
        {"label": "Specific date range", "description": "Custom validation"},
        {"label": "After backfill operation", "description": "Verify backfill quality"},
        {"label": "Full season audit", "description": "Comprehensive check"},
    ]
)

validation_type = response["answer"]

# Step 2: Ask which layer
if validation_type == "After backfill operation":
    layer_response = ask_user_question(
        question="Which layer did you backfill?",
        options=[
            {"label": "Analytics (Phase 3)", "description": "Game summaries"},
            {"label": "Precompute (Phase 4)", "description": "Rolling windows - Recommended"},
            {"label": "Predictions (Phase 5)", "description": "Model outputs"},
        ]
    )

# Step 3-7: Continue guided flow...

# Execute validation based on collected answers
run_validation(
    layer=layer,
    date_range=date_range,
    mode=mode,
    quality_checks=quality_checks
)

# Step 8: Offer remediation
if issues_found:
    action_response = ask_user_question(
        question="What would you like to do?",
        options=[
            {"label": "View detailed breakdown", "description": "See per-date analysis"},
            {"label": "Generate remediation commands", "description": "Get reprocessing scripts"},
            {"label": "Execute fixes now", "description": "Run backfill immediately"},
            {"label": "Save report and exit", "description": "Export results"},
        ]
    )
```

### Benefits of Interactive Mode

1. **Guided Workflow**: Users don't need to remember all options/flags
2. **Context-Aware**: Questions adapt based on previous answers
3. **Validation**: Input validation at each step
4. **Defaults**: Recommends best practices
5. **Safe**: Asks confirmation before executing fixes
6. **Educational**: Descriptions explain what each option does

### When to Use Interactive Mode

- **New users**: Don't know validation options yet
- **Infrequent use**: Haven't memorized command syntax
- **Complex scenarios**: Multiple decisions needed
- **Exploratory**: Not sure what to check
- **Safe execution**: Want guidance and confirmations

### When to Use Command Mode

- **Scripts/CI**: Automated validation
- **Power users**: Know exactly what they want
- **Speed**: No interaction needed
- **Documentation**: Clear command shows what was run

## Feature Store vs Cache Validation (Session 27)

### Purpose

Validates that `ml_feature_store_v2` L5/L10 values match `player_daily_cache` values. This detects data leakage where feature store includes the current game in rolling averages.

### When to Use

- After feature store backfill operations
- When investigating prediction accuracy anomalies
- During season validation audits

### Validation Query

```sql
-- Feature Store vs Cache Match Rate
WITH comparison AS (
  SELECT
    fs.player_lookup,
    fs.game_date,
    ROUND(fs.features[OFFSET(0)], 2) as fs_l5,
    ROUND(c.points_avg_last_5, 2) as cache_l5,
    ROUND(fs.features[OFFSET(1)], 2) as fs_l10,
    ROUND(c.points_avg_last_10, 2) as cache_l10
  FROM `nba_predictions.ml_feature_store_v2` fs
  JOIN `nba_precompute.player_daily_cache` c
    ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
  WHERE fs.game_date BETWEEN @start_date AND @end_date
    AND ARRAY_LENGTH(fs.features) >= 2
)
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as total_records,
  COUNTIF(ABS(fs_l5 - cache_l5) < 0.1) as l5_matches,
  ROUND(100.0 * COUNTIF(ABS(fs_l5 - cache_l5) < 0.1) / COUNT(*), 1) as l5_match_pct,
  COUNTIF(ABS(fs_l10 - cache_l10) < 0.1) as l10_matches,
  ROUND(100.0 * COUNTIF(ABS(fs_l10 - cache_l10) < 0.1) / COUNT(*), 1) as l10_match_pct
FROM comparison
GROUP BY 1
ORDER BY 1
```

### Pass Criteria

- L5 match rate >= 95%
- L10 match rate >= 95%
- `source_daily_cache_rows_found IS NOT NULL` for >= 95% of records

### Alert Conditions

1. **Data Leakage (CRITICAL)**: L5/L10 match rate < 50% - feature store likely includes current game
2. **Cache Miss (HIGH)**: Match rate 50-95% - cache lookup failing for some records
3. **Metadata Missing (MEDIUM)**: `source_daily_cache_rows_found = NULL` for >5% - backfill mode didn't track sources

### Example Usage

```bash
# Check specific date range
/validate-lineage feature-cache --start-date 2025-01-01 --end-date 2025-01-31

# Check single date in detail
/validate-lineage feature-cache-detail 2025-01-15
```

### Known Issues

- 2024-25 season L5/L10 bug was FIXED in Session 27 (2026-01-29)
- `source_daily_cache_rows_found = NULL` for all backfill records (by design)

---

## Feature Store Validation (New - Session 27)

### Quick Start

```bash
# Validate last 7 days (default)
/validate-lineage feature-store

# Validate specific date range
/validate-lineage feature-store --start-date 2025-11-01 --end-date 2025-11-30

# After backfill - ALWAYS run this
/validate-lineage feature-store --start-date <backfill-start> --end-date <backfill-end>

# JSON output for automation
/validate-lineage feature-store --json

# CI mode (exit code 1 on failure)
/validate-lineage feature-store --ci
```

### What It Checks

| Check | Threshold | Alert Condition |
|-------|-----------|-----------------|
| **L5/L10 consistency** | >= 95% match | Feature store values don't match cache |
| **Duplicates** | 0 | Any duplicate (player, date) pairs |
| **Array integrity** | 0 invalid | NULL arrays, wrong length (!= 33), NaN/Inf |

### Implementation

The feature-store validation is implemented in Python:

```python
# Run programmatically
from shared.validation.feature_store_validator import validate_feature_store

result = validate_feature_store(
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 30),
)

if not result.passed:
    print(result.summary)
    for issue in result.issues:
        print(f"  - {issue}")
```

### CLI Usage

```bash
# Direct Python execution
python -m shared.validation.feature_store_validator --days 7

# With specific dates
python -m shared.validation.feature_store_validator \
    --start-date 2025-11-01 \
    --end-date 2025-11-30

# Just consistency check
python -m shared.validation.feature_store_validator --consistency-only

# Just duplicates
python -m shared.validation.feature_store_validator --duplicates-only
```

### BigQuery View

A daily validation summary view is available:

```sql
-- Check yesterday's validation status
SELECT * FROM `nba_predictions.v_daily_validation_summary`
WHERE check_date = CURRENT_DATE() - 1;

-- Find any failures in last 7 days
SELECT * FROM `nba_predictions.v_daily_validation_summary`
WHERE status = 'FAIL'
ORDER BY check_date DESC;
```

### After Backfill Checklist

1. Run feature store validation:
   ```bash
   /validate-lineage feature-store --start-date <start> --end-date <end>
   ```

2. Check L5/L10 match rate >= 95%

3. If match rate < 95%, investigate:
   - Were records created from cache or fallback?
   - Check `source_daily_cache_rows_found` column
   - Compare sample mismatches

4. If duplicates found, deduplicate before predictions

---

## Related

- `/validate-daily` - Daily pipeline health checks
- `/validate-historical` - Historical data completeness
- Project docs: `docs/08-projects/current/data-lineage-integrity/`
- Implementation: `shared/validation/processing_gate.py`
- Implementation: `shared/validation/window_completeness.py`
- **NEW:** Implementation: `shared/validation/feature_store_validator.py`
- **NEW:** View: `schemas/bigquery/predictions/views/v_daily_validation_summary.sql`
