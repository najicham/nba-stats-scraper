# Processor Documentation Guide

**Created:** 2025-11-21 18:10:00 PST
**Last Updated:** 2025-11-21 18:10:00 PST

Quick reference for documenting NBA data processors consistently.

---

## Overview

**Purpose:** Ensure consistent, comprehensive processor documentation

**Two Types:**
1. **Processor Cards** (`docs/processor-cards/`) - 1-2 page quick reference
2. **Full Docs** (if needed) - Comprehensive documentation for complex processors

---

## Processor Cards (Quick Reference)

**Location:** `docs/processor-cards/`

**Format:** `phase{N}-{processor-name}.md`

**Length:** 1-2 pages (concise)

**Use for:** Daily operations, debugging, quick lookups

### Required Sections

**1. Essential Facts**
```markdown
| Attribute | Value |
|-----------|-------|
| **Type** | Phase 3 - Analytics |
| **Schedule** | After each game + nightly |
| **Duration** | 1-2 minutes |
| **Priority** | High |
| **Status** | ✅ Production Ready |
```

**2. Code & Tests**
```markdown
| Component | Location | Size |
|-----------|----------|------|
| **Processor** | path/to/file.py | XXX lines |
| **Schema** | schemas/path.sql | XX fields |
| **Tests** | tests/path/ | XX total |
```

**3. Dependencies**
```markdown
Phase 2 Raw Sources:
  ├─ table_name (CRITICAL) - Purpose
  └─ table_name (OPTIONAL) - Purpose

Consumers (Phase 4):
  ├─ processor_name - How used
```

**4. What It Does**
- 1-3 bullet points
- Primary function
- Key output
- Value proposition

**5. Key Metrics Calculated**
```python
# Show actual code + formula
def calculate_metric(args):
    """Brief description"""
    return result
```
- **Range:** Typical values
- **Example:** Real example

**6. Output Schema Summary**
```markdown
| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 5 | game_id, team_abbr |
| Metrics | 10 | points, rebounds |
```

**7. Health Check Query**
```sql
-- Working query to verify health
SELECT ...
```
- Include expected results

**8. Common Issues & Quick Fixes**
```markdown
### Issue 1: Problem Name
**Symptom**: What you see
**Diagnosis**: Query to check
**Fix**: Steps to resolve
```

---

## Full Documentation (Optional)

**Location:** Create only when processor cards insufficient

**Use for:** Complex processors, ML models, coordinator systems

### Additional Sections for Full Docs

**Design Decisions:**
- Options considered
- Choice made
- Rationale
- Tradeoffs

**Deployment:**
```bash
# Step-by-step commands
bq query --use_legacy_sql=false < schema.sql
python processor.py --start-date 2025-01-15
```

**Usage Examples:**
```sql
-- 3-5 real queries solving business questions
SELECT ... FROM ...
```

**Monitoring:**
- Key metrics to track
- Alert thresholds
- Performance benchmarks
- Cost estimates

**Historical Backfill** (if applicable):
- Status (complete/partial)
- Date range covered
- Number of records
- Command used

---

## Best Practices

### DO ✅

**Use real examples:**
```python
# ✅ GOOD - Actual code
def calculate_pace(possessions, minutes):
    return possessions * (48 / minutes)

# ❌ BAD - Pseudocode
calculate_metric(input)
```

**Be honest about status:**
```markdown
# ✅ GOOD
Status: ⏳ Core complete, monitoring pending

# ❌ BAD
Status: ✅ Production ready (when it's not)
```

**Make commands copy-pasteable:**
```bash
# ✅ GOOD - Complete command
python processor.py --start-date 2025-01-15 --end-date 2025-01-15

# ❌ BAD - Vague instruction
Run the processor
```

**Document what IS, not what was planned:**
```markdown
# ✅ GOOD
Aggregates from nba_raw.nbac_team_boxscore

# ❌ BAD
Will aggregate from player stats (not implemented)
```

### DON'T ❌

**Don't overpromise:**
```markdown
# ❌ BAD
Will support real-time streaming

# ✅ GOOD
Batch processing only (daily schedule)
```

**Don't use placeholders:**
```markdown
# ❌ BAD
[PLACEHOLDER - Add schema]

# ✅ GOOD
<actual schema>
```

**Don't skip testing section:**
- Tests prove it works
- Shows coverage
- Helps debugging

**Don't forget to update:**
- Update when implementation changes
- Mark last updated date
- Keep status current

---

## Templates

### Processor Card Template

```markdown
# {Processor Name} - Quick Reference

**Last Updated**: YYYY-MM-DD
**Verified**: ✅ Code verified

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase X - {Type} |
| **Schedule** | {Schedule} |
| **Duration** | {Duration} |
| **Priority** | {High/Medium/Low} |
| **Status** | {Status Icon} {Description} |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | path/to/file.py | XXX lines |
| **Schema** | schemas/path.sql | XX fields |
| **Tests** | tests/path/ | XX total |

---

## Dependencies (v4.0 Tracking)

[Dependency diagram]

---

## What It Does

1. **Primary Function**: {Description}
2. **Key Output**: {What it produces}
3. **Value**: {Why it matters}

---

## Key Metrics Calculated

### Metric Name
[Code example]
- **Range**: {Typical values}
- **Example**: {Real example}

---

## Output Schema Summary

**Total Fields**: {XX}

| Category | Count | Examples |
|----------|-------|----------|
| {Category} | {N} | {Examples} |

---

## Health Check Query

[SQL query with expected results]

---

## Common Issues & Quick Fixes

### Issue 1: {Problem}
**Symptom**: {What you see}
**Diagnosis**: {Query to check}
**Fix**: {Steps to resolve}

---

## Monitoring Alerts

**Critical:**
- ❌ {Alert 1}

**Warning:**
- ⚠️ {Alert 1}

---

**Last Verified**: {Date}
**Maintained By**: {Team}
```

---

## Pre-Publish Checklist

**Content:**
- [ ] All required sections present
- [ ] No placeholder text
- [ ] All code examples real (not pseudocode)
- [ ] All commands tested
- [ ] Sample queries work
- [ ] Schema matches BigQuery table
- [ ] Status accurate

**Quality:**
- [ ] No typos
- [ ] Consistent formatting
- [ ] Code blocks formatted
- [ ] Commands copy-pasteable
- [ ] Examples use realistic data

**Accuracy:**
- [ ] Field names match schema
- [ ] Table names correct
- [ ] Formulas verified
- [ ] Dependencies complete
- [ ] Test counts current
- [ ] Performance numbers realistic

**Usability:**
- [ ] New developer could understand
- [ ] Operations could deploy
- [ ] Stakeholder could understand purpose

---

## Example Reference

**Gold Standard:** `docs/processor-cards/phase3-team-offense-game-summary.md`

**Why it's good:**
- ✅ Complete coverage of required sections
- ✅ Real code examples
- ✅ Working SQL queries
- ✅ Honest about status
- ✅ Comprehensive test documentation
- ✅ Clear health checks
- ✅ Practical troubleshooting

---

## Status Icons

Use these consistently:

- ✅ Complete / Production Ready
- ⏳ In Progress / Partial
- 🚧 Under Development
- ❌ Not Started / Blocked
- 🔄 Refactoring
- ⚠️ Warning / Issue

---

## Documentation Philosophy

**1. Document what IS, not what was planned**

**2. Be honest about status**
- Mark incomplete features clearly
- Don't oversell capabilities
- Document known limitations

**3. Include real examples**
- Actual Python code
- Working SQL queries
- Copy-pasteable commands

**4. Make it actionable**
- Every command runnable
- Include all parameters
- Show expected output

**5. Keep it current**
- Update when implementation changes
- Mark last updated dates
- Version your docs

---

## When to Create Full Documentation

Create comprehensive docs (beyond processor cards) when:

1. **Complex ML model** - Multiple algorithms, training pipelines
2. **Coordinator system** - Orchestrates other processors
3. **Multi-step pipeline** - Multiple processing stages
4. **External integration** - Complex API interactions
5. **Requested by stakeholders** - Audit requirements, compliance

Otherwise, processor cards are sufficient.

---

## Files

**Processor Cards:**
- `docs/processor-cards/*.md` - Quick reference cards
- `docs/processor-cards/README.md` - Navigation index

**Templates:**
- See template section above

**Examples:**
- `docs/processor-cards/phase3-team-offense-game-summary.md` - Gold standard
- `docs/processor-cards/phase5-prediction-coordinator.md` - Complex processor

---

## See Also

- [Processor Development Guide](01-processor-development-guide.md)
- [Backfill Deployment Guide](03-backfill-deployment-guide.md)
- [Schema Change Process](04-schema-change-process.md)
