# Session 70: Scraper Config Validation System

**Date**: February 1, 2026
**Session**: 70 (continued)
**Status**: COMPLETE

---

## What Was Built

Built a **3-layer validation system** to prevent the `espn_roster` bug from recurring.

### The Problem

**espn_roster Bug (Session 70)**:
- Config referenced non-existent table `nba_raw.espn_team_roster`
- `/catchup` endpoint tried to query it anyway
- Error: `400 Unrecognized name: processed_at`
- Scraper was disabled but still being queried

### The Solution

```
┌─────────────────────────────────────────────┐
│ Layer 1: Pre-Commit (Warning Only)          │
│ - Checks config on commit                   │
│ - Warns about missing tables                │
│ - Doesn't block (many aspirational tables)  │
└─────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Layer 2: Runtime Validation (Fails Fast)    │
│ - Services validate at startup              │
│ - Raises error if enabled scraper invalid   │
│ - Fails before processing starts            │
└─────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Layer 3: Skip Disabled (Prevention)         │
│ - Helper function checks enabled status     │
│ - Services skip disabled scrapers           │
│ - Never queries disabled configs            │
└─────────────────────────────────────────────┘
```

---

## Files Created

### 1. Pre-Commit Hook
**File**: `.pre-commit-hooks/validate_scraper_config_tables.py`

Checks all table references in scraper config, warns but doesn't block commits.

```bash
# Run manually
python .pre-commit-hooks/validate_scraper_config_tables.py
```

### 2. Runtime Validator
**File**: `shared/validation/scraper_config_validator.py`

Functions:
- `validate_enabled_scrapers()` - Check config at service startup
- `should_process_scraper()` - Skip disabled scrapers
- `get_enabled_scrapers()` - List enabled scrapers

```python
# In service startup
from shared.validation.scraper_config_validator import validate_enabled_scrapers

try:
    validate_enabled_scrapers()
except ValueError as e:
    logger.error(f"Invalid config: {e}")
    sys.exit(1)
```

### 3. Documentation
**File**: `shared/validation/README.md`

Usage examples and integration guide.

### 4. Pre-Commit Config
**File**: `.pre-commit-config.yaml` (updated)

Added:
```yaml
- id: validate-scraper-config-tables
  name: Validate scraper config table references (warning only)
  entry: python .pre-commit-hooks/validate_scraper_config_tables.py
```

---

## Validation Results

### Current State

Running the validator found **9 enabled scrapers with missing tables**:

| Scraper | Missing Table | Fix Needed |
|---------|---------------|------------|
| oddsa_events | nba_raw.odds_api_events | Disable or fix table name |
| oddsa_player_props | nba_raw.odds_api_player_props | Disable or fix table name |
| bp_player_props | nba_raw.bettingpros_player_props | Actual table: bettingpros_player_points_props |
| bp_events | nba_raw.bettingpros_events | Disable or create table |
| br_roster | nba_raw.br_team_roster | Disable or create table |
| nbac_player_boxscore | nba_raw.nbac_player_boxscore | Actual table uses different name? |
| nbac_roster | nba_raw.nbac_roster | Disable or create table |
| nbac_referee_assignments | nba_raw.nbac_referee_assignments | Disable or create table |
| bdl_odds | nba_raw.bdl_odds | Disable or create table |

**Note**: These are real issues! Config says they're enabled but tables don't exist.

### Disabled Scrapers (OK)

These are disabled and have missing tables (expected, OK):
- espn_boxscore
- espn_roster (the bug we're fixing!)
- pbpstats_boxscore
- bdl_live_box_scores

---

## How to Use

### For Service Developers

**Add to service startup:**

```python
from shared.validation.scraper_config_validator import validate_enabled_scrapers

def main():
    # Validate config before starting service
    try:
        validate_enabled_scrapers()
        logger.info("✓ Scraper config validated")
    except ValueError as e:
        logger.error(f"Invalid scraper config: {e}")
        sys.exit(1)

    # Start service
    run_service()
```

### For Catchup/Orchestrator Services

**Skip disabled scrapers:**

```python
from shared.validation.scraper_config_validator import should_process_scraper

for scraper_name in all_scrapers:
    if not should_process_scraper(scraper_name):
        logger.info(f"Skipping disabled: {scraper_name}")
        continue

    # Only process enabled scrapers
    check_completeness(scraper_name)
```

---

## Next Steps

### Immediate (Required)

1. **Fix config** - Disable or correct the 9 scrapers with invalid tables:
   ```bash
   # Edit shared/config/scraper_retry_config.yaml
   # For each invalid scraper, either:
   #   - Set enabled: false
   #   - Fix the table name
   #   - Create the missing table
   ```

2. **Update catchup service** - Add `should_process_scraper()` check:
   ```python
   # Find catchup/orchestrator code that queries scrapers
   # Add check to skip disabled scrapers
   ```

### Future (Nice to Have)

1. **Add runtime validation to services** - Services using scraper config should validate at startup
2. **Create missing tables** - If scrapers are supposed to be enabled, create the tables
3. **Config audit** - Review all scraper configs for accuracy

---

## Testing

### Test Pre-Commit Hook

```bash
# Trigger on config change
git add shared/config/scraper_retry_config.yaml
git commit -m "test: config change"

# Should show warnings but allow commit
```

### Test Runtime Validation

```bash
python -c "
from shared.validation.scraper_config_validator import validate_enabled_scrapers
validate_enabled_scrapers(raise_on_error=False)
"

# Should show 9 validation errors
```

---

## Impact

### Prevents

- Runtime errors from missing tables
- Silent failures in catchup services
- Querying disabled scrapers
- Weeks of undetected config errors

### Enables

- Fail-fast validation at service startup
- Clear documentation of enabled vs disabled scrapers
- Confidence in scraper config accuracy

---

## Related Files

| File | Purpose |
|------|---------|
| `.pre-commit-hooks/validate_scraper_config_tables.py` | Pre-commit validation |
| `shared/validation/scraper_config_validator.py` | Runtime validation |
| `shared/validation/README.md` | Usage documentation |
| `shared/config/scraper_retry_config.yaml` | Config being validated |
| `.pre-commit-config.yaml` | Pre-commit hook config |

---

## Key Learnings

1. **Disabled doesn't mean ignored** - Services must check enabled status
2. **Fail fast is better** - Runtime validation catches errors before damage
3. **Config drift is real** - Many enabled scrapers have invalid tables
4. **Warning-only pre-commit** - Too many aspirational configs to block strictly

---

*Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>*
