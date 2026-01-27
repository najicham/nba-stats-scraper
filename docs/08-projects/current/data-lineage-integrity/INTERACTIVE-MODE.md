# Interactive Mode for /validate-lineage Skill

**Date**: 2026-01-26
**Status**: ✅ Complete
**Purpose**: Add guided workflow with questions to validation skill

---

## Overview

Added an **interactive mode** to the `/validate-lineage` skill that guides users through validation workflows with questions instead of requiring them to remember command-line flags.

---

## What Was Added

### 1. Interactive Mode Command

```bash
/validate-lineage interactive
```

This launches a guided workflow with 7 decision points:

1. **What do you want to validate?**
   - Recent data (last 7 days)
   - Specific date range
   - After backfill operation
   - Full season quality audit
   - Investigate specific issue

2. **Which layer?**
   - Analytics (Phase 3)
   - Precompute (Phase 4)
   - Predictions (Phase 5)
   - All layers

3. **What level of detail?**
   - Quick check (~2 min)
   - Standard validation (~10 min)
   - Thorough audit (~30 min)

4. **Quality focus?** (new quality metadata)
   - Check quality score trends
   - Find incomplete windows
   - Detect late-arriving data
   - Compare processing contexts

5. **Date range?**
   - Auto-suggested based on context
   - Custom input if needed

6. **Execute validation**
   - Confirmation step
   - Progress tracking
   - Results display

7. **Remediation?** (if issues found)
   - View details
   - Generate commands
   - Execute fixes
   - Validate fixes

---

## Example Interactive Session

```
> /validate-lineage interactive

📊 Data Lineage Validation - Interactive Mode

What do you want to validate?
  1. Recent data (last 7 days) - Quick health check
  2. Specific date range - Custom validation
  3. After backfill operation - Verify backfill quality
  4. Full season quality audit - Comprehensive check
  5. Investigate specific issue - Deep dive

Your choice: 3

You ran a backfill. What date range did you backfill?
Start date: 2025-11-01
End date: 2025-11-30

Which layer did you backfill?
  1. Analytics (Phase 3)
  2. Precompute (Phase 4) - Recommended
  3. Predictions (Phase 5)
  4. All layers

Your choice: 2

What level of detail?
  1. Quick check - Aggregate validation (~2 min)
  2. Standard validation - With sampling (~10 min) - Recommended
  3. Thorough audit - Full analysis (~30 min)

Your choice: 2

Include quality metadata checks?
(New feature - tracks incomplete windows and late data)
  Yes / No: Yes

=== Running Validation ===
Layer: Precompute (Phase 4)
Date Range: 2025-11-01 to 2025-11-30
Mode: Standard (with sampling)
Quality Checks: Enabled

[████████████████████░░░░] 78% - Checking 2025-11-25...

=== Results ===

Tier 1: Aggregate Validation
  ✓ Total dates: 30
  ⚠ Flagged dates: 3

Tier 2: Sample Validation (50 records per date)
  Date         Sampled  Issues  Quality  Status
  2025-11-10   50       8       78%      DEGRADED
  2025-11-15   50       3       82%      ACCEPTABLE
  2025-11-20   50       1       91%      GOOD

Quality Metadata Analysis:
  ⚠ 2025-11-10: 16% incomplete windows (L10, L7d)
  ⚠ 2025-11-15: 6% incomplete windows (L10)
  ✓ 2025-11-20: 2% incomplete windows (marginal)

Summary:
  Confirmed issues: 2 dates (2025-11-10, 2025-11-15)
  Estimated contaminated records: ~47 players
  Root cause: Late-arriving game data

What would you like to do?
  1. View detailed breakdown - See per-player analysis
  2. Generate remediation commands - Get reprocessing scripts
  3. Execute fixes now - Run backfill immediately
  4. Save report and exit - Export results to file

Your choice: 2

=== Remediation Plan ===

Priority 1: Critical (quality < 80%)
──────────────────────────────────────
Date: 2025-11-10
Records affected: 45 players
Reason: 16% incomplete windows

Reprocessing command:
  python scripts/backfill_phase3.py --start-date 2025-11-10 --end-date 2025-11-10
  python scripts/backfill_phase4.py --start-date 2025-11-10 --end-date 2025-11-10

Priority 2: Review (quality 80-90%)
──────────────────────────────────────
Date: 2025-11-15
Records affected: 23 players
Reason: 6% incomplete windows

Reprocessing command:
  python scripts/backfill_phase3.py --start-date 2025-11-15 --end-date 2025-11-15
  python scripts/backfill_phase4.py --start-date 2025-11-15 --end-date 2025-11-15

Execute Priority 1 fixes now?
(This will run backfill for 2025-11-10)
  Yes / No / Save script: Save script

✓ Commands saved to: /tmp/lineage_remediation_20260126.sh

To execute manually:
  bash /tmp/lineage_remediation_20260126.sh

After fixing, re-validate with:
  /validate-lineage investigate 2025-11-10

✓ Validation complete!
```

---

## Implementation

The interactive mode uses Claude's `AskUserQuestion` tool:

```python
from claude.tools import AskUserQuestion

def run_interactive_validation():
    # Step 1: Ask what to validate
    validation_type = ask_user_question(
        question="What do you want to validate?",
        header="Validation Type",
        options=[
            {
                "label": "Recent data (last 7 days)",
                "description": "Quick health check of recent pipeline runs"
            },
            {
                "label": "After backfill operation",
                "description": "Verify backfill quality and detect contamination"
            },
            {
                "label": "Full season audit",
                "description": "Comprehensive quality check for entire season"
            }
        ]
    )

    # Step 2: Ask which layer (context-dependent)
    if validation_type == "After backfill operation":
        layer = ask_user_question(
            question="Which layer did you backfill?",
            header="Layer",
            options=[
                {
                    "label": "Precompute (Phase 4)",
                    "description": "Rolling windows and composite factors - Recommended"
                },
                {
                    "label": "Analytics (Phase 3)",
                    "description": "Game summaries and team stats"
                }
            ]
        )

    # Step 3-7: Continue flow...

    # Execute based on collected answers
    result = execute_validation(
        layer=layer,
        date_range=date_range,
        mode=mode,
        quality_checks=True
    )

    # Step 8: Offer remediation if needed
    if result.has_issues:
        action = ask_user_question(
            question="What would you like to do?",
            header="Next Steps",
            options=[
                {"label": "Generate remediation commands", "description": "Get scripts to fix issues"},
                {"label": "Execute fixes now", "description": "Run backfill immediately"},
                {"label": "Save report and exit", "description": "Export for later review"}
            ]
        )

        handle_remediation_action(action, result)
```

---

## Benefits

### 1. **Lower Barrier to Entry**
- New users don't need to learn command syntax
- No need to remember all flags and options
- Guided workflow reduces errors

### 2. **Context-Aware**
- Questions adapt based on previous answers
- Smart defaults recommended
- Only asks relevant questions

### 3. **Educational**
- Descriptions explain what each option does
- Recommendations highlight best practices
- Learn command syntax from generated commands

### 4. **Safe Execution**
- Confirmation steps before running operations
- Preview commands before execution
- Option to save and run manually later

### 5. **Efficient**
- Faster than looking up documentation
- Reduces back-and-forth questions
- Captures intent in fewer steps

---

## When to Use

### Use Interactive Mode When:
- 🆕 First time using validation
- 🤔 Not sure what to check
- 📚 Don't remember command syntax
- 🔍 Exploratory validation
- ⚠️ Want confirmation before executing

### Use Command Mode When:
- 🤖 Scripting/automation (CI/CD)
- ⚡ Power user who knows exactly what to run
- 📝 Documenting what was run
- 🔁 Repeating previous validation

---

## Comparison: Interactive vs Command

| Aspect | Interactive Mode | Command Mode |
|--------|------------------|--------------|
| **Launch** | `/validate-lineage interactive` | `/validate-lineage quick --start-date ...` |
| **Learning Curve** | Low (guided) | Medium (need docs) |
| **Speed** | Slower (questions) | Faster (one command) |
| **Flexibility** | High (adapts) | High (all flags) |
| **Automation** | Not suitable | Perfect for scripts |
| **Best For** | Humans, learning | Scripts, power users |

---

## Future Enhancements

### Potential Additions:

1. **Smart Defaults from Context**
   - Detect recent backfill from run history
   - Auto-suggest likely date ranges
   - Remember user preferences

2. **Multi-Select Questions**
   - Select multiple layers to validate
   - Choose multiple quality checks at once

3. **Validation History**
   - Show previous validation runs
   - Offer to re-run with same parameters
   - Compare to previous results

4. **Advanced Remediation**
   - Estimate fix duration
   - Check resource availability
   - Schedule fixes for later

5. **Export Options**
   - PDF report generation
   - Email results to team
   - Post to Slack/notifications

---

## Related Documentation

- **Skill Definition**: `.claude/skills/validate-lineage.md`
- **Implementation Summary**: `docs/.../IMPLEMENTATION-SUMMARY.md`
- **Integration Example**: `docs/.../INTEGRATION-EXAMPLE.md`
- **Quality Metadata**: `migrations/add_quality_metadata.sql`

---

## Testing Interactive Mode

To test the interactive mode:

```bash
# Launch interactive mode
/validate-lineage interactive

# Follow prompts and verify:
# 1. Questions flow correctly
# 2. Answers are validated
# 3. Commands are generated correctly
# 4. Confirmations work
# 5. Reports are clear
```

---

**Added**: 2026-01-26
**Status**: Ready for Use ✅
**Skill**: `/validate-lineage`
