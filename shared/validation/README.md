# Scraper Config Validation

**Created**: Session 70 (2026-02-01)
**Purpose**: Prevent runtime errors from invalid scraper configurations

## Problem This Solves

The `espn_roster` bug (Session 70) showed that scraper configs can reference non-existent BigQuery tables, causing runtime errors that go undetected for weeks.

**What happened:**
- `espn_roster` scraper config referenced `nba_raw.espn_team_roster` (doesn't exist)
- `/catchup` endpoint queried all scrapers including disabled ones
- Errors: `400 Unrecognized name: processed_at`

## Solution: Multi-Layer Validation

### Layer 1: Pre-Commit Check (Informational)

Runs automatically on commit, warns about missing tables but doesn't block.

```bash
# Manually run
python .pre-commit-hooks/validate_scraper_config_tables.py
```

**Output:**
```
✅ nba_raw.nbac_schedule (used by nbac_schedule)
⚠️  Disabled scraper 'espn_roster' references missing table: nba_raw.espn_team_roster

⚠️  This check is informational only and won't block the commit.
```

### Layer 2: Runtime Validation (Fails Fast)

Services should validate at startup to catch config errors before processing.

```python
from shared.validation.scraper_config_validator import validate_enabled_scrapers

# At service startup (e.g., in main() or __init__)
try:
    validate_enabled_scrapers()
    logger.info("✓ Scraper config validated")
except ValueError as e:
    logger.error(f"Invalid scraper config: {e}")
    sys.exit(1)  # Fail fast - don't start service with bad config
```

### Layer 3: Skip Disabled Scrapers

Use the helper function to check if a scraper should be processed.

```python
from shared.validation.scraper_config_validator import should_process_scraper

# In catchup/orchestrator services
for scraper_name in all_scrapers:
    if not should_process_scraper(scraper_name):
        logger.info(f"Skipping disabled scraper: {scraper_name}")
        continue

    # Process enabled scraper
    run_completeness_check(scraper_name)
```

## Related

- **Config**: `shared/config/scraper_retry_config.yaml`
- **Config Loader**: `shared/config/scraper_retry_config.py`
- **Pre-Commit Hook**: `.pre-commit-hooks/validate_scraper_config_tables.py`
- **Runtime Validator**: `shared/validation/scraper_config_validator.py`

## Session History

- **Session 70 (2026-02-01)**: Created validation system after espn_roster bug
