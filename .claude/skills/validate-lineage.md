# Skill: validate-lineage

## Purpose

Validate data lineage integrity - ensure computed data was calculated with complete, correct upstream dependencies. Detects "cascade contamination" where records were computed while dependencies were missing.

## When to Use

- After backfill operations to verify data correctness
- Quarterly data quality audits
- When investigating suspicious predictions or model drift
- After major pipeline incidents

## Usage

```
/validate-lineage [mode] [options]
```

### Modes

| Mode | Description | Speed |
|------|-------------|-------|
| `quick` | Aggregate validation only (Tier 1) | Fast (~2 min) |
| `standard` | Aggregate + sample validation (Tier 1-2) | Medium (~10 min) |
| `thorough` | Full validation with spot checks (Tier 1-3) | Slow (~30 min) |
| `investigate <date>` | Deep dive on specific date | Variable |
| `recompute <date>` | Recompute and compare all records for date | Slow |

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

## Related

- `/validate-daily` - Daily pipeline health checks
- `/validate-historical` - Historical data completeness
- Project docs: `docs/08-projects/current/data-lineage-integrity/`
