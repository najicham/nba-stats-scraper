# GCS → BigQuery Completeness Validation

**Status:** Implemented (v1.0)
**Created:** 2025-12-02
**Tool:** `bin/validation/validate_gcs_bq_completeness.py`

---

## Problem Statement

The Phase 1 → Phase 2 data flow (GCS JSON files → BigQuery raw tables) can fail silently:

1. **Orphaned GCS files** - Scrapers save JSON but Phase 2 processors never run
2. **Partial processing** - Some files processed, others skipped
3. **Duplicate processing** - Same file processed multiple times
4. **Missing data** - Phase 2 ran but inserted fewer records than expected

The main `validate_pipeline.py` shows GCS file counts and BQ record counts side by side, but doesn't validate that the **ratios are correct** or detect **processing gaps**.

---

## Solution

A separate validation tool that:

1. **Counts GCS files/folders** for each source and date
2. **Counts BQ records** for the same source and date
3. **Calculates expected record ranges** based on known ratios
4. **Identifies anomalies** (GCS_ONLY, LOW, HIGH, etc.)

### Why Separate from Main Validation?

- **Performance**: GCS API calls are slow (~2-3 sec per date per source)
- **Use case**: Deep audit, not daily validation
- **Complexity**: Ratio validation adds logic not needed for daily checks

---

## Usage

```bash
# Validate a single date
python bin/validation/validate_gcs_bq_completeness.py 2021-10-25

# Validate a date range
python bin/validation/validate_gcs_bq_completeness.py 2021-10-19 2021-11-15

# Validate specific sources only
python bin/validation/validate_gcs_bq_completeness.py 2021-10-25 \
    --sources nbac_gamebook_player_stats,nbac_team_boxscore

# Verbose output (per-date details)
python bin/validation/validate_gcs_bq_completeness.py 2021-10-19 2021-10-31 -v

# JSON output for programmatic use
python bin/validation/validate_gcs_bq_completeness.py 2021-10-25 --format json
```

---

## Validation Status Meanings

| Status | Symbol | Meaning | Action |
|--------|--------|---------|--------|
| `ok` | ✅ | Records within expected range | None needed |
| `bq_only` | ⚠️ | BQ has data, GCS is empty | Normal for old data (GCS cleaned up) |
| `gcs_only` | ❌ | GCS has data, BQ is empty | **Phase 2 may not have run** |
| `low` | 🔻 | Fewer BQ records than expected | Check for processing errors |
| `high` | 🔺 | More BQ records than expected | Possible duplicates |
| `no_data` | ⬜ | Neither GCS nor BQ has data | No games that day, or both missing |

---

## Expected Ratios

These ratios were derived from data analysis:

| Source | Records per Game | Notes |
|--------|-----------------|-------|
| nbac_gamebook_player_stats | 25-38 | ~25-38 players incl DNPs |
| nbac_team_boxscore | 2 | Always 2 teams per game |
| bettingpros_player_points_props | 8-20 | Varies by bookmaker coverage |
| odds_api_game_lines | 6-20 | Multiple bookmakers |
| espn_scoreboard | 1 | 1 entry per game |
| bdl_player_boxscores | 20-30 | Players per game |
| bigdataball_play_by_play | 350-550 | Events per game |

---

## Architecture

```
bin/validation/
└── validate_gcs_bq_completeness.py  # Main tool

Uses existing config from:
└── shared/validation/chain_config.py
    └── GCS_PATH_MAPPING          # Source → GCS path mapping
    └── GCS_BUCKET                # nba-scraped-data
```

### Key Classes

- `GCSInventory` - Counts files/folders in GCS with caching
- `BQCounter` - Counts records in BigQuery with caching
- `SourceExpectation` - Defines expected ratios for each source
- `SourceValidationResult` - Result for one source/date
- `DateValidationResult` - Result for one date (all sources)
- `ValidationSummary` - Aggregate summary

---

## Future Enhancements

### P1: High Priority

- [ ] Add to CI/CD as post-deployment check
- [ ] Add Slack alerting for `gcs_only` status (critical)
- [ ] Support season-based sources (bigdataball)

### P2: Medium Priority

- [ ] Add per-record checksums for exact validation
- [ ] Cross-reference with `processor_run_history` for failed runs
- [ ] Add `--fix` mode to trigger reprocessing of gaps

### P3: Low Priority

- [ ] Add Grafana dashboard integration
- [ ] Historical trend analysis
- [ ] Cost estimation for GCS storage cleanup

---

## Integration with Existing Tools

### With `validate_pipeline.py`

The main validation script shows GCS vs BQ counts per chain. This tool provides **deeper analysis** with ratio validation.

```bash
# Daily check (fast)
python bin/validate_pipeline.py today

# Deep audit (slower but more thorough)
python bin/validation/validate_gcs_bq_completeness.py 2024-01-01 2024-01-31 -v
```

### With Backfill Operations

Before running backfill, validate source data completeness:

```bash
# Check Phase 1-2 completeness for backfill window
python bin/validation/validate_gcs_bq_completeness.py 2021-10-19 2021-11-15

# If issues found, investigate before proceeding
```

---

## Troubleshooting

### GCS_ONLY Status (Critical)

**Cause:** GCS has JSON files but BQ table is empty for that date.

**Investigation:**
1. Check `processor_run_history` for failed runs
2. Check Cloud Run logs for Phase 2 processor
3. Verify Pub/Sub message was delivered

**Fix:**
1. Manually trigger Phase 2 processor for that date
2. Or run Phase 2 backfill script

### LOW Status

**Cause:** Fewer BQ records than expected.

**Investigation:**
1. Check if all games were scraped (compare to schedule)
2. Check processor logs for errors during insertion
3. Verify JSON files are complete

**Fix:**
1. Re-run Phase 2 processor
2. If JSON is corrupt, re-run Phase 1 scraper

### HIGH Status

**Cause:** More BQ records than expected (possible duplicates).

**Investigation:**
1. Check for duplicate processing (Pub/Sub retries)
2. Query for duplicate records

```sql
SELECT game_date, player_lookup, COUNT(*) as cnt
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date = '2021-10-25'
GROUP BY 1, 2
HAVING COUNT(*) > 1
```

**Fix:**
1. Delete duplicates (use most recent scrape)
2. Investigate deduplication logic in processor

---

## Version History

- **v1.0 (2025-12-02)**: Initial implementation with ratio validation
