<!-- File: validation/ARTIFACT_FILE_MAPPING.md -->
<!-- Description: Maps all Claude artifacts to their destination files -->

# Artifact to File Mapping

This document maps all the artifacts created in this conversation to their destination files in your project.

## Core Framework Files

### 1. base_validator.py
**Artifact ID:** `base_validator`  
**Destination:** `validation/base_validator.py`  
**Description:** Core validation framework with config-driven logic  
**Status:** ✅ Ready to copy

### 2. partition_filter.py
**Artifact ID:** `partition_filter_handler`  
**Destination:** `validation/utils/partition_filter.py`  
**Description:** Automatic partition filter injection for BigQuery queries  
**Status:** ✅ Ready to copy

---

## Configuration Files

### 3. ESPN Scoreboard Config (Example)
**Artifact ID:** `config_schema`  
**Destination:** `validation/configs/raw/espn_scoreboard.yaml`  
**Description:** Example validation config for ESPN Scoreboard processor  
**Status:** ✅ Ready to copy

### 4. Multiple Config Templates
**Artifact ID:** `config_templates`  
**Contains:**
- `validation/configs/raw/bdl_boxscores.yaml`
- `validation/configs/raw/odds_api_props.yaml`
- `validation/configs/raw/nbac_schedule.yaml`
- `validation/configs/raw/nbac_gamebook.yaml`

**Description:** Template configs for various processor types  
**Status:** ✅ Copy each section to respective file (separated by `---`)

### 5. Real Processor Configs (Based on Actual Schemas)
**Artifact ID:** `real_configs`  
**Contains:**
- `validation/configs/raw/espn_scoreboard.yaml` (detailed)
- `validation/configs/raw/bdl_boxscores.yaml` (detailed)
- `validation/configs/raw/odds_api_props.yaml` (detailed)
- `validation/configs/raw/nbac_schedule.yaml` (detailed)

**Description:** Production-ready configs based on your actual BigQuery schemas  
**Status:** ✅ Copy each section to respective file (separated by `---`)

---

## Validator Files

### 6. BDL Boxscores Validator (Custom Example)
**Artifact ID:** `custom_validator_example`  
**Destination:** `validation/validators/raw/bdl_boxscores_validator.py`  
**Description:** Example of custom validator extending BaseValidator  
**Status:** ✅ Ready to copy

---

## Documentation Files

### 7. Partition Filter Guide
**Artifact ID:** `partition_filter_readme`  
**Destination:** `validation/PARTITION_FILTER_GUIDE.md`  
**Description:** Explains BigQuery partition filtering and how framework handles it  
**Status:** ✅ Ready to copy

### 8. Implementation Guide
**Artifact ID:** `implementation_guide`  
**Destination:** `validation/IMPLEMENTATION_GUIDE.md`  
**Description:** Comprehensive guide for implementing the validation system  
**Status:** ✅ Ready to copy

---

## How to Use This Mapping

### Step 1: Copy Core Framework
```bash
cd ~/code/nba-stats-scraper/validation

# Copy base_validator.py from artifact
# Copy partition_filter.py from artifact
```

### Step 2: Copy One Config to Test
```bash
# Start with ESPN Scoreboard
# Copy from "real_configs" artifact (first section)
# Paste into validation/configs/raw/espn_scoreboard.yaml
```

### Step 3: Copy Documentation
```bash
# Copy PARTITION_FILTER_GUIDE.md from artifact
# Copy IMPLEMENTATION_GUIDE.md from artifact
```

### Step 4: Test
```bash
python -m validation.validators.raw.espn_scoreboard_validator \
  --last-days=7 \
  --no-notify
```

### Step 5: Expand
Once ESPN Scoreboard validator works, copy additional configs from `real_configs` and `config_templates` artifacts.

---

## Files Still Needed (Not in Artifacts)

These files need to be created but aren't in artifacts yet:

### Utility Files
- `validation/utils/schedule_utils.py` - NBA calendar awareness
- `validation/utils/query_builder.py` - Query construction helpers
- `validation/utils/remediation_utils.py` - Remediation command generation

### Schedule Files
- `validation/schedules/raw_daily.yaml` - Daily validation schedule
- `validation/schedules/analytics_daily.yaml` - Analytics validation schedule
- `validation/schedules/weekly_comprehensive.yaml` - Weekly deep checks
- `validation/schedules/season_start.yaml` - Season start comprehensive check

### BigQuery Schema
- `schemas/bigquery/nba_processing/validation_results.sql` - Table for storing validation results

### Test Files
- `validation/tests/test_base_validator.py` - Unit tests
- `validation/tests/test_partition_filter.py` - Partition filter tests

### Additional Validators
- `validation/validators/raw/espn_scoreboard_validator.py` - Need to create
- `validation/validators/raw/nbac_schedule_validator.py` - Need to create
- `validation/validators/raw/odds_api_props_validator.py` - Need to create

---

## Priority Order for Implementation

### Week 1 (Proof of Concept)
1. ✅ Copy `base_validator.py`
2. ✅ Copy `partition_filter.py`
3. ✅ Copy one config (ESPN Scoreboard from `real_configs`)
4. ✅ Create simple `espn_scoreboard_validator.py` (can use `custom_validator_example` as template)
5. ✅ Create `validation_results.sql` schema
6. ✅ Test end-to-end

### Week 2 (Expand Coverage)
1. Copy 3-4 more configs from `real_configs`
2. Create corresponding validators
3. Test each validator
4. Create schedule configs

### Week 3 (Production Ready)
1. Deploy validation runner
2. Set up Cloud Scheduler
3. Integrate with monitoring
4. Create dashboards

---

## Quick Reference Commands

### Copy Artifact Content
When copying from artifacts, look for the section headers:
```yaml
# ============================================================================
# File: path/to/file.yaml
# ============================================================================
```

Everything between the header and the next `---` or end of artifact goes in that file.

### Test a Validator
```bash
# Basic test
python -m validation.validators.raw.PROCESSOR_NAME_validator --last-days=7

# With date range
python -m validation.validators.raw.PROCESSOR_NAME_validator \
  --start-date=2024-11-01 \
  --end-date=2024-11-30

# Without notifications (for testing)
python -m validation.validators.raw.PROCESSOR_NAME_validator \
  --last-days=7 \
  --no-notify
```

---

## Context Window Usage

**Current Status:** ~126K / 190K tokens (~66% used)  
**Remaining:** ~64K tokens (34%)

**What We Can Still Fit:**
- ✅ BigQuery schema (small)
- ✅ 1-2 utility files
- ✅ Schedule configs
- ⚠️ Won't fit: All remaining validators (too many)

**Recommendation:**  
Get one validator working end-to-end, then start fresh chat with learnings for remaining validators.