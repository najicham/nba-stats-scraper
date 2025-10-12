# Validator Creation Quick Reference

## For Teams Needing a Validator

### Step 1: Create Requirements File (5 min)
```bash
cd validation/requirements
./new_requirements.sh [your_processor_name]
```

### Step 2: Fill Critical Sections (30 min)
Must have:
- ✅ BigQuery table name (Section 1)
- ✅ GCS bucket path (Section 2)  
- ✅ Sample data - 10 rows (Section 7)

Run these queries and paste results:
```sql
-- Get sample data
SELECT * FROM `project.dataset.table` LIMIT 10;

-- Get schema
SELECT column_name, data_type 
FROM `project.dataset.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'your_table';
```

### Step 3: Submit (5 min)
Share completed file with validation team.

### Step 4: Get Validator (1-2 hours)
Validation team builds and delivers:
- Config file
- Validator script
- Test command

### Step 5: Test (15 min)
```bash
python -m validation.validators.raw.[processor]_validator \
  --last-days 7 --no-notify
```

## Time Commitment

- **Your time:** 45-90 minutes (mostly gathering info)
- **Wait time:** 1-2 hours (validator built)
- **Total:** ~3 hours from start to working validator

## Need Help?

- **Template:** `VALIDATOR_REQUIREMENTS_TEMPLATE.md`
- **Guide:** `HOW_TO_USE_VALIDATOR_TEMPLATE.md`
- **Examples:** `requirements/completed/`
- **Contact:** Validation team

## Common Questions

**Q: What if I don't know some information?**  
Mark as `[NEED CLARIFICATION]` and submit anyway.

**Q: Can I submit partial template?**  
Yes! Fill Critical sections and submit. Rest can be iterative.

**Q: How do I test the validator?**  
We provide test command when delivering validator.

**Q: What if validation fails?**  
That's the point! It catches real data quality issues.

## Success Rate

- ✅ ESPN Scoreboard: 14/14 checks passing
- ✅ BDL Boxscores: Built in 45 minutes
- ✅ Odds API Props: Caught 3 issues immediately

Your validator will be just as good! 🎯
