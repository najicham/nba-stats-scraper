# Schema Change Management Process

**Created:** 2025-11-21 18:00:00 PST
**Last Updated:** 2025-11-21 18:00:00 PST

Quick reference for managing BigQuery schema changes safely across all phases.

---

## Overview

**Use this process for ANY change to:**
- BigQuery table schemas (add/remove/modify fields)
- Data processor input/output formats
- Field types, constraints, or validations

**Key Principles:**
- Documentation first - changelog before changes
- Backward compatible - new code works with old data
- Synchronize everything - schema, docs, processors updated together
- Test before deploy - validate with historical data
- Rollback ready - always have a rollback plan

---

## Risk Levels

| Change Type | Risk | Review Required |
|------------|------|-----------------|
| Add optional field | 🟢 LOW | Tech Lead |
| Add required field | 🟡 MEDIUM | Architecture Team |
| Modify field type | 🟡 MEDIUM | Architecture Team |
| Rename field | 🔴 HIGH | Architecture + Testing |
| Remove field | 🔴 HIGH | Architecture + Testing |

---

## 10-Step Process

### 1. Create Changelog Document

**Template:** `changelogs/YYYYMM_schema_change_[table_name].md`

Required sections:
- Executive summary (what, why, impact)
- Exact schema changes (SQL)
- Backward compatibility strategy
- Documentation updates needed
- Processor changes required
- Testing strategy
- Rollback plan

### 2. Review & Approve

- **Low risk (🟢):** Tech Lead review (~1 day)
- **Medium risk (🟡):** Architecture Team (~2-3 days)
- **High risk (🔴):** Full team design review (~1 week)

### 3. Update BigQuery Schema

```sql
-- Add new optional field (always nullable initially)
ALTER TABLE `project.dataset.table_name`
ADD COLUMN IF NOT EXISTS new_field_name TYPE
OPTIONS (description="Field description");
```

**Rules:**
- ✅ Use `IF NOT EXISTS` for idempotency
- ✅ Add fields as nullable initially
- ❌ Never remove fields in this step
- ❌ Never change field types directly

### 4. Update Documentation

**Files to update (in order):**

1. **Main schema file:** `schemas/bigquery/[phase]/[table]_tables.sql`
   ```sql
   existing_field INT64,
   new_field INT64,  -- ADDED: 2025-01 - See changelog_202501.md
   ```

2. **Phase documentation:** Update field counts and descriptions

3. **Data mapping docs:** Add field to mapping tables

4. **Processor docs:** Add to output schema sections

5. **Master changelog:** `docs/SCHEMA_CHANGELOG.md`
   ```markdown
   ## 2025-01 - Table Name Updates
   - **Changes:** Added `new_field`
   - **Changelog:** [202501_schema_change.md](...)
   - **Status:** ✅ Deployed (2025-01-28)
   ```

### 5. Update Processors (Backward Compatible)

**Critical:** Processors must work with BOTH old and new data.

**Pattern: Optional field**
```python
def transform_data(self, raw_data: dict) -> dict:
    """Must handle old data (missing field) and new data."""

    # Use .get() with default for backward compatibility
    new_field_value = raw_data.get('new_field_source', 0)

    return {
        'existing_field': raw_data['existing_field'],
        'new_field': new_field_value,  # 0 for old data
    }
```

**Pattern: Read from table with new field**
```python
def extract_data(self):
    """Handle tables with and without new fields."""

    query = f"""
    SELECT
        existing_field,
        COALESCE(new_field, 0) as new_field,  -- Default if missing
    FROM `dataset.table`
    WHERE date = @date
    """

    self.data = self.bq_client.query(query).to_dataframe()

    # Handle old schema
    if 'new_field' not in self.data.columns:
        logger.warning("new_field not in schema, using 0")
        self.data['new_field'] = 0
```

**Add tests for both formats:**
```python
def test_processor_with_old_data():
    """Test with data missing new fields."""
    old_data = {'existing_field': 10}  # No new_field
    result = processor.transform(old_data)
    assert result['new_field'] == 0  # Default

def test_processor_with_new_data():
    """Test with data including new fields."""
    new_data = {'existing_field': 10, 'new_field_source': 5}
    result = processor.transform(new_data)
    assert result['new_field'] == 5  # Calculated
```

### 6. Test with Historical Data

```python
def test_processor_with_real_historical_data():
    """Test on actual data before schema change."""
    processor = MyProcessor()

    # Use date before schema change
    historical_date = date(2024, 10, 15)

    # Should NOT fail even though data missing new fields
    success = processor.run({'game_date': historical_date})
    assert success
```

**Validation query:**
```sql
-- Historical data should work with defaults
SELECT
  game_date,
  existing_field,      -- Old field (has value)
  new_field,           -- New field (should be 0/NULL)
FROM `dataset.table`
WHERE game_date = '2024-10-15'  -- Before change
LIMIT 10;
```

### 7. Backfill (If Needed)

**When needed:**
- New field can be calculated from existing data
- Historical data should have populated values (not just defaults)
- Downstream systems need complete historical data

**Test on sample first:**
```sql
-- Test on single day
UPDATE `dataset.table`
SET new_field = calculation_logic
WHERE game_date = '2024-01-15'
  AND new_field IS NULL
LIMIT 100;
```

**Execute full backfill:**
```sql
-- Backfill all historical data
UPDATE `dataset.table`
SET new_field = calculation_logic
WHERE new_field IS NULL
  AND game_date >= '2021-10-01'
  AND game_date < CURRENT_DATE();
```

**Validate:**
```sql
-- Check for NULLs (should be 0)
SELECT
  COUNT(*) as total,
  COUNT(new_field) as populated,
  COUNT(*) - COUNT(new_field) as nulls
FROM `dataset.table`
WHERE game_date >= '2021-10-01';
```

### 8. Deploy to Production

```bash
# Deploy updated processor
gcloud run deploy processor-name \
  --image=gcr.io/project/processor:v2.1 \
  --region=us-west2

# Monitor first run
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=processor-name" \
  --limit=100
```

**Validate production data:**
```sql
-- Check recent data has new fields
SELECT
  game_date,
  COUNT(*) as games,
  COUNT(new_field) as has_new_field,
  AVG(new_field) as avg_value
FROM `dataset.table`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date
ORDER BY game_date DESC;
```

### 9. Monitor (3-7 Days)

**Daily validation:**
```sql
SELECT
  game_date,
  COUNT(*) as total_games,
  COUNT(new_field) as has_field,
  ROUND(100.0 * COUNT(new_field) / COUNT(*), 2) as coverage_pct,
  AVG(new_field) as avg_value,
  CASE
    WHEN COUNT(new_field) = COUNT(*) AND AVG(new_field) > 0 THEN '✅ OK'
    WHEN COUNT(new_field) = COUNT(*) THEN '⚠️ Values Low'
    ELSE '❌ Missing Data'
  END as status
FROM `dataset.table`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

### 10. Mark Complete & Archive

```markdown
## Status: ✅ Deployed to Production

**Deployment Date:** 2025-01-28
**Schema Version:** v3.2
**Processor Version:** v2.1
**Validation Period:** 2025-01-28 to 2025-02-04
**Status:** Complete - No issues detected
```

Move changelog from `/changelogs/pending/` to `/changelogs/complete/`

---

## Backward Compatibility Patterns

### Adding Optional Field

```python
# Phase 1: Add field as optional
ALTER TABLE ADD COLUMN new_field TYPE;

# Processors use .get() with defaults
new_field = data.get('new_field', default_value)
```

### Adding Required Field

```python
# Phase 1: Add as optional
ALTER TABLE ADD COLUMN new_field TYPE;

# Phase 2: Backfill with values
UPDATE TABLE SET new_field = calculated WHERE new_field IS NULL;

# Phase 3: Make required (after all data populated)
ALTER TABLE ALTER COLUMN new_field SET NOT NULL;
```

### Deprecating Field

```python
# Phase 1: Add replacement, mark old deprecated
'''DEPRECATED: use new_field_name. Removes: 2025-06'''
old_field TYPE,
new_field TYPE,  # Replacement

# Phase 2: Update processors to use new_field

# Phase 3: Stop populating old_field (3-6 months)

# Phase 4: Remove old_field
ALTER TABLE DROP COLUMN old_field;
```

### Changing Field Type

```python
# Phase 1: Add new field with new type
ALTER TABLE ADD COLUMN new_field NEW_TYPE;

# Phase 2: Populate from old field
UPDATE TABLE SET new_field = CAST(old_field AS NEW_TYPE);

# Phase 3: Update processors to use new_field

# Phase 4: Deprecate old_field

# Phase 5: Remove old_field (3-6 months later)
```

---

## Rollback Procedures

### Rollback Processor Only

**When:** Processor bugs, but schema OK

```bash
# Revert to previous version
gcloud run deploy processor-name \
  --image=gcr.io/project/processor:v2.0 \
  --region=us-west2
```

### Rollback Schema Change

**When:** Schema causing issues

```sql
-- Remove newly added field
ALTER TABLE `dataset.table`
DROP COLUMN IF EXISTS new_field;

-- Verify removal
SELECT column_name
FROM `INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'table_name'
  AND column_name = 'new_field';
-- Should return 0 rows
```

### Full Rollback

1. Rollback processor
2. Rollback schema
3. Verify old system working
4. Document root cause
5. Fix issues before retry

---

## Checklists

### Pre-Change Checklist

- [ ] Changelog document created and approved
- [ ] All affected systems identified
- [ ] Backward compatibility strategy defined
- [ ] Documentation updates listed
- [ ] Processor changes identified
- [ ] Testing strategy defined
- [ ] Rollback plan documented

### Post-Deployment Checklist

- [ ] Schema updated (dev and prod)
- [ ] All documentation updated
- [ ] All processors updated
- [ ] Backward compatibility tests pass
- [ ] Historical data works correctly
- [ ] New data populates correctly
- [ ] Downstream systems validated
- [ ] Alerts configured
- [ ] Monitoring in place (1 week)
- [ ] Changelog marked complete

---

## Common Issues

### "Cannot query over table without filter over partition column"

**Problem:** DELETE/SELECT on partitioned table needs partition filter

**Solution:**
```sql
-- ❌ WRONG
DELETE FROM `table` WHERE game_id = 'X'

-- ✅ CORRECT
DELETE FROM `table`
WHERE game_id = 'X'
  AND game_date = DATE('2024-11-20')
```

### "'NoneType' object has no attribute 'query'"

**Problem:** Missing BigQuery client initialization

**Solution:**
```python
def __init__(self):
    super().__init__()
    self.bq_client = bigquery.Client()
    self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
```

### "No processor found for file"

**Problem:** Registry key doesn't match GCS path

**Solution:**
```python
# In main_processor_service.py
PROCESSOR_REGISTRY = {
    'nba-com/scoreboard-v2': ScoreboardProcessor,  # Must match GCS path
}
```

---

## Files

**Templates:**
- `changelogs/template_schema_change.md` - Changelog template

**Master Log:**
- `docs/SCHEMA_CHANGELOG.md` - All schema changes log

**Deployment Scripts:**
- `bin/*/deploy/*.sh` - Processor deployment

---

## See Also

- [Backfill Deployment Guide](03-backfill-deployment-guide.md)
- [Processor Development Guide](01-processor-development-guide.md)
- [Quick Start Processor](02-quick-start-processor.md)
