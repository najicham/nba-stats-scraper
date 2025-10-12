# How to Use the Validator Requirements Template

**Quick Start:** Copy the template, fill it out, get a validator in 1-2 hours! 🚀

---

## 📋 Step-by-Step Process

### 1. Copy the Template
```bash
# Create a new file for your specific processor
cp validation/VALIDATOR_REQUIREMENTS_TEMPLATE.md \
   validation/requirements/[processor_name]_requirements.md

# Example:
cp validation/VALIDATOR_REQUIREMENTS_TEMPLATE.md \
   validation/requirements/odds_game_lines_requirements.md
```

### 2. Fill Out Sections

**Priority Order (fill these first):**

**🔴 Critical (Can't start without):**
- Section 1: BigQuery table name, partition details
- Section 2: GCS paths and file patterns
- Section 7: Sample data (run queries, paste 10 rows)

**🟡 Important (Needed for complete validator):**
- Section 3: Data coverage expectations
- Section 4: Required fields and valid ranges
- Section 6: Cross-validation sources

**🟢 Nice to Have:**
- Section 5: Known issues
- Section 8: Processor details
- Section 9: Backfill timeline
- Section 10: Success criteria

### 3. Run the Sample Queries

The template includes ready-to-run queries. Just replace placeholders:

```sql
-- Example: Replace these placeholders
[PROJECT_ID]     → nba-props-platform
[DATASET]        → nba_raw
[TABLE_NAME]     → your_table_name
[RECENT_DATE]    → 2024-10-22
```

Then run in BigQuery and paste results.

### 4. Share with Validation Team

Once complete:
- ✅ Check that all `[FILL IN]` placeholders are replaced
- ✅ Check at least "Critical" sections are complete
- ✅ Share file with validation team
- ✅ Wait ~1 hour for validator to be built

---

## 🎯 Template Sections Explained

### Section 1: BigQuery Schema
**Why:** Tells us table structure, partition strategy, field types  
**How:** Run `INFORMATION_SCHEMA.COLUMNS` query or paste CREATE TABLE  
**Time:** 5 minutes

### Section 2: GCS Storage  
**Why:** Validates raw files exist before processing  
**How:** Provide bucket path, file naming pattern, sample file content  
**Time:** 5 minutes

### Section 3: Coverage & Expectations
**Why:** Defines what "complete" data looks like  
**How:** Specify date ranges, seasons, expected record counts  
**Time:** 10 minutes

### Section 4: Data Quality Rules
**Why:** Defines what "valid" data looks like  
**How:** List required fields, numeric ranges, valid enum values  
**Time:** 15 minutes

### Section 5: Known Issues
**Why:** Avoids false alarms on expected edge cases  
**How:** Document any known gaps, quirks, or systematic issues  
**Time:** 5 minutes

### Section 6: Cross-Validation
**Why:** Ensures consistency across related tables  
**How:** Specify reference tables to validate against  
**Time:** 10 minutes

### Section 7: Sample Data
**Why:** Shows us actual data structure and patterns  
**How:** Run provided queries, paste results  
**Time:** 10 minutes

### Section 8: Processor Info
**Why:** Helps us understand any transformations  
**How:** Link to processor code, describe any special logic  
**Time:** 5 minutes

### Section 9: Timeline
**Why:** Determines when/how to run validations  
**How:** Specify backfill dates, completion timeline  
**Time:** 2 minutes

### Section 10: Success Criteria
**Why:** Defines what passes vs fails  
**How:** Set thresholds, priorities, alert preferences  
**Time:** 5 minutes

**Total time to complete:** ~60-90 minutes

---

## 💡 Tips for Filling Out Template

### Tip 1: Start with Sample Queries
Run the queries in Section 7 first. The results will help you fill out many other sections!

### Tip 2: Don't Overthink It
- ✅ Good: "Team field uses 3-letter abbreviations like LAL, BOS"
- ❌ Overkill: Providing entire team mapping document

### Tip 3: Use Examples
The template includes examples throughout. Use similar format for your data.

### Tip 4: Mark Uncertainties
If unsure, write: `[NEED CLARIFICATION: reason]`

We'll help fill gaps during validator creation.

### Tip 5: Paste Real Output
Instead of describing query results, paste the actual output:
```
✅ Good:
game_date  | count | teams
2024-10-22 | 20    | 30

❌ Bad:
"Each date has about 20 rows"
```

---

## 🔍 Common Patterns by Data Type

### Raw Scraper Data
**Focus on:**
- GCS file structure (Section 2)
- Expected game/date coverage (Section 3)
- Cross-validation with schedule (Section 6)

**Examples:** ESPN scoreboard, NBA.com schedule, Basketball Reference rosters

### API Data
**Focus on:**
- API rate limits and timing (Section 5)
- Expected field completeness (Section 4)
- Multiple snapshots per day (Section 2)

**Examples:** Odds API, Ball Don't Lie API

### Analytics Tables
**Focus on:**
- Source data dependencies (Section 8)
- Aggregation correctness (Section 4)
- Cross-validation with raw sources (Section 6)

**Examples:** Player game summary, team offense stats

### Reference Data
**Focus on:**
- Completeness (all entities present) (Section 3)
- Valid values and enums (Section 4)
- Uniqueness constraints (Section 4)

**Examples:** Player registry, team reference

---

## 🚀 What Happens Next

### After You Submit

**Hour 0:** You submit completed template  
**Hour 1:** Validation team reviews, asks clarifying questions  
**Hour 2:** Validator code is written based on template  
**Hour 3:** You test validator on your data  
**Hour 4:** Iterate based on results  
**Done:** Deploy to production!

### What You'll Receive

1. **Config file:** `validation/configs/[layer]/[processor_name].yaml`
2. **Validator:** `validation/validators/[layer]/[processor_name]_validator.py`
3. **Test command:**
   ```bash
   python -m validation.validators.[layer].[processor_name]_validator \
     --start-date 2024-10-01 \
     --end-date 2024-10-31 \
     --no-notify
   ```
4. **Documentation:** Comments explaining each validation check

---

## 📁 Where to Save Requirements Docs

**Option 1: Central requirements directory (recommended)**
```bash
mkdir -p validation/requirements
# Save all requirements docs here
validation/requirements/
  ├── odds_game_lines_requirements.md
  ├── bdl_boxscores_requirements.md
  ├── player_game_stats_requirements.md
  └── ...
```

**Option 2: With processor code**
```bash
# Save alongside the processor being validated
data_processors/raw/odds_api/
  ├── game_lines_processor.py
  └── VALIDATOR_REQUIREMENTS.md
```

**Option 3: Shared docs directory**
```bash
mkdir -p docs/validator_requirements
# Central documentation location
```

**Recommendation:** Use Option 1 (central requirements directory) for easier discovery.

---

## ✅ Quality Checklist

Before submitting, verify:

- [ ] All `[FILL IN]` placeholders replaced
- [ ] At least 1 sample query result pasted
- [ ] Table name and partition details provided
- [ ] GCS path pattern provided
- [ ] Required fields listed
- [ ] At least one cross-validation source identified
- [ ] Known issues section completed (or marked "None")
- [ ] Contact information provided

**Minimum viable:** First 4 items. Rest can be filled iteratively.

---

## 🎓 Example: Odds Game Lines

**See:** `validation/requirements/odds_game_lines_requirements.md`

This is a completed example showing:
- How to fill out each section
- What level of detail is appropriate  
- How to paste query results
- How to document edge cases

Use it as a reference!

---

## 📞 Need Help?

**Common questions:**

**Q: What if I don't know some information?**  
A: Mark as `[NEED CLARIFICATION]` and submit anyway. We'll fill gaps together.

**Q: How detailed should I be?**  
A: Enough for someone unfamiliar with your data to understand it. When in doubt, more is better.

**Q: Can I submit partial template?**  
A: Yes! Fill out Critical sections (1, 2, 7) and we can start. Rest can be filled iteratively.

**Q: What if my data doesn't fit the template?**  
A: That's fine! Add custom sections or skip irrelevant ones. Template is a guide, not a strict requirement.

**Q: How long until I get a validator?**  
A: ~1-2 hours after submitting complete template.

---

## 🏆 Success Stories

**ESPN Scoreboard Validator**
- Template filled: 45 minutes
- Validator built: 60 minutes  
- Result: 14/14 checks passing ✅

**Odds API Props Validator**
- Template filled: 90 minutes (complex data model)
- Validator built: 75 minutes
- Result: Caught 3 data quality issues immediately! ✅

---

*Remember: The validator is only as good as the requirements! Take time to fill out the template thoroughly.* 🎯