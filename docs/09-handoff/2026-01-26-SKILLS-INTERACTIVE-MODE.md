# Claude Code Skills - Interactive Mode Feature

**Date**: 2026-01-26
**Enhancement**: Added interactive mode to both validation skills
**Status**: ✅ Complete

---

## Overview

Both `/validate-daily` and `/validate-historical` skills now support **interactive mode** - when invoked without parameters, Claude will ask multiple-choice questions to guide you through the validation options.

This solves the "I forgot what flags exist" problem and makes the skills more discoverable.

---

## How It Works

### For `/validate-daily`

**Before** (had to remember options):
```bash
# User needs to remember what options exist
/validate-daily
```

**Now** (interactive prompts):
```bash
/validate-daily
  ↓
Question 1: What would you like to validate?
  - Today's pipeline (pre-game check)
  - Yesterday's results (post-game check)
  - Specific date
  - Quick health check only

Question 2: How thorough should the validation be?
  - Standard (Recommended)
  - Comprehensive
  - Quick scan
```

### For `/validate-historical`

**Before**:
```bash
# User needs to remember: date ranges, modes, flags
/validate-historical
```

**Now**:
```bash
/validate-historical
  ↓
Question 1: What date range would you like to validate?
  - Last 7 days (Recommended)
  - Last 14 days
  - Last 30 days
  - Full season (Oct 22 - today)
  - Custom date range

Question 2: What type of validation do you need?
  - Standard validation (Recommended)
  - Deep check
  - Player-specific
  - Verify backfill
  - Quick coverage scan
  - Find anomalies

Question 3 (if needed): Follow-up based on mode
  - If player-specific → "Which player?"
  - If verify backfill → "What date was backfilled?"
  - If custom range → "What date range?"
```

---

## User Experience Flow

### Scenario 1: User Knows What They Want

```bash
# User provides parameters directly
/validate-historical --deep-check 2026-01-18

# Claude skips questions, proceeds directly with deep check
```

### Scenario 2: User Wants Guidance

```bash
# User invokes without parameters
/validate-historical

# Claude asks questions:
Q: What date range?
A: Last 7 days

Q: What type of validation?
A: Standard validation

# Claude then runs: Standard validation for last 7 days
```

### Scenario 3: User Selects Complex Mode

```bash
/validate-historical

Q: What date range?
A: Custom date range

Q: What type of validation?
A: Player-specific

Q: What date range?
A: 2026-01-01 2026-01-15

Q: Which player?
A: LeBron James

# Claude runs: Player validation for LeBron, Jan 1-15
```

---

## Implementation Details

### Using AskUserQuestion Tool

The skills use the `AskUserQuestion` tool which provides:
- **Multiple choice options**: User selects from predefined choices
- **"Other" option**: Always available for custom input
- **Multi-select**: Can be enabled for selecting multiple options (not used in these skills)
- **Clear descriptions**: Each option explains what it does

### Question Structure

Each question has:
- **Header**: Short label (e.g., "Date range")
- **Question**: Full question text (e.g., "What date range would you like to validate?")
- **Options**: 2-4 clear choices with descriptions
- **Conditional follow-ups**: Based on previous answers

### Fallback Behavior

If user selects "Other" and provides custom text:
- Skills parse the custom input
- Extract date range, player name, or mode from free text
- Proceed with best interpretation

---

## Benefits

### 1. Discoverability

**Before**: Users had to:
- Remember flag names (`--deep-check`, `--player`, etc.)
- Know what modes exist
- Understand date range formats

**Now**: Users:
- See all available options
- Get descriptions of what each option does
- Can explore without documentation

### 2. Reduced Cognitive Load

**Before**: "What was that flag for verifying backfills... --verify-backfill or --check-backfill?"

**Now**: Just run `/validate-historical` and see "Verify backfill" in the menu

### 3. Faster Common Cases

**Recommended options marked**: "Last 7 days (Recommended)" guides users to best practices

### 4. Error Prevention

**Before**: User might type `/validate-historical --deep-check` and forget the date

**Now**: Claude asks for the date if not provided

---

## Examples in Practice

### Example 1: Daily Validation (Most Common)

```
User: /validate-daily

Claude:
┌─────────────────────────────────────────────────────────┐
│ What would you like to validate?                        │
├─────────────────────────────────────────────────────────┤
│ ○ Today's pipeline (pre-game check)                     │
│   → Check if today's data is ready before games start   │
│                                                          │
│ ○ Yesterday's results (post-game check) [Recommended]   │
│   → Verify yesterday's games processed correctly        │
│                                                          │
│ ○ Specific date                                         │
│   → Validate a custom date                              │
│                                                          │
│ ○ Quick health check only                               │
│   → Just run health check script, no deep investigation │
└─────────────────────────────────────────────────────────┘

User selects: Yesterday's results

Claude:
Running post-game validation for 2026-01-25...
[Proceeds with standard validation workflow]
```

### Example 2: Historical Deep Check

```
User: /validate-historical

Claude asks:
Q1: What date range?
→ User: Last 14 days

Q2: What type of validation?
→ User: Deep check

Claude:
Running deep check for 2026-01-12 through 2026-01-26...
This will recalculate rolling averages from source data and compare to cache.
Estimated time: 3-5 minutes for 14 days.

[Proceeds with deep check workflow]
```

### Example 3: Player Investigation

```
User: /validate-historical

Q1: Date range?
→ User: Last 7 days

Q2: Validation type?
→ User: Player-specific

Q3: Which player?
→ User: Giannis Antetokounmpo

Claude:
Investigating Giannis Antetokounmpo's data for 2026-01-19 through 2026-01-26...

[Proceeds with player-specific validation]
```

---

## Technical Implementation

### In validate-daily/SKILL.md

```markdown
## Interactive Mode (User Preference Gathering)

**If the user invoked the skill without specific parameters**, ask them what they want to check:

Use the AskUserQuestion tool to gather preferences:

Question 1: "What would you like to validate?"
Options:
  - "Today's pipeline (pre-game check)"
  - "Yesterday's results (post-game check)"
  - "Specific date"
  - "Quick health check only"

[Claude then proceeds based on selection]
```

### In validate-historical/SKILL.md

```markdown
## Interactive Mode (User Preference Gathering)

**If the user invoked the skill without specific parameters or flags**, ask them what they want to validate:

Question 1: "What date range would you like to validate?"
[4-5 options with descriptions]

Question 2: "What type of validation do you need?"
[6 validation modes with descriptions]

Question 3 (conditional): Follow-up questions based on mode
[Player name, backfill date, or custom range]

[Claude constructs effective command and proceeds]
```

---

## Design Decisions

### Why Multiple Choice?

**Considered**: Free-text input (e.g., "What do you want to do?")

**Chosen**: Multiple choice because:
- Clearer options (user sees what's possible)
- No ambiguity (exact match to skill modes)
- Faster selection (click vs type)
- Guided experience (descriptions help choose)

### Why Conditional Questions?

**Instead of** asking all questions upfront:
- Q1: Date range
- Q2: Mode
- Q3: Player name
- Q4: Export path
- Q5: ...

**We ask** only relevant follow-ups:
- Q1: Date range
- Q2: Mode
- Q3: (only if mode needs it) Player/date/etc.

**Benefit**: Fewer clicks for common cases

### Why "Recommended" Labels?

Guide users to best practices:
- **validate-daily**: "Yesterday's results" (most common daily workflow)
- **validate-historical**: "Last 7 days" (good default for weekly checks)

---

## Future Enhancements

### Possible Improvements

1. **Remember Last Selection**:
   - Store user's last choice in session state
   - Offer "Use last time's settings?" option

2. **Smart Defaults Based on Context**:
   - If it's 6 AM ET → Default to "Yesterday's results"
   - If it's 5 PM ET → Default to "Today's pipeline"

3. **Multi-Step Wizards** for complex scenarios:
   - "Let me guide you through investigating a prediction miss"
   - Step-by-step questions to build complete investigation

4. **Quick Actions** shortcut:
   - "Common actions: [Standard weekly check] [Investigate gap] [Verify backfill]"
   - One-click for frequent workflows

---

## User Feedback Loop

After using interactive mode, users can:

1. **Learn the flags**: See "Oh, I can use `--deep-check` next time"
2. **Build commands**: Skill shows equivalent command (optional)
3. **Save time**: Bookmark common workflows

**Example Enhancement**:
```
After Q1 (Last 7 days) + Q2 (Standard):

Claude: "Running standard validation for last 7 days...

💡 Tip: Next time you can run this directly with:
   /validate-historical 7

Or for deep check:
   /validate-historical 7 --deep-check
```

---

## Documentation Updates

### Files Modified

1. **validate-daily/SKILL.md**:
   - Added "Interactive Mode" section
   - Explains when questions are asked vs skipped
   - Lists all questions and options

2. **validate-historical/SKILL.md**:
   - Added "Interactive Mode" section
   - Explains conditional question flow
   - Shows how answers map to modes

3. **This document**:
   - Comprehensive guide to interactive mode feature
   - Usage examples and benefits
   - Design rationale

---

## Testing the Feature

### Test Cases

**Test 1: No parameters provided**
```bash
/validate-daily
# Expected: Questions asked
```

**Test 2: Parameters provided**
```bash
/validate-daily yesterday
# Expected: Questions skipped, proceeds with validation
```

**Test 3: Complex mode selection**
```bash
/validate-historical
→ Last 7 days
→ Player-specific
→ LeBron James
# Expected: Player validation for LeBron, last 7 days
```

**Test 4: User selects "Other"**
```bash
/validate-historical
→ Custom date range
→ Other: "Last month"
# Expected: Claude parses "last month" as ~30 days
```

---

## Success Metrics

### Usability Improvements

**Before Interactive Mode**:
- User needs to read documentation to learn flags
- Trial-and-error to find correct syntax
- Cognitive load remembering 7+ modes

**After Interactive Mode**:
- Self-guided exploration
- No documentation needed for basic usage
- Visual menu of all options

### Expected Outcomes

- **Faster adoption**: New users can use skills immediately
- **Fewer errors**: No typos in flags or dates
- **Better discovery**: Users learn about modes they didn't know existed
- **Reduced support**: Fewer "how do I..." questions

---

## Conclusion

Interactive mode makes the validation skills:
1. **More discoverable**: See all options without docs
2. **Easier to use**: No need to memorize flags
3. **Faster for common cases**: Click instead of type
4. **Error-resistant**: Validated inputs only

The skills remain **flexible**:
- Power users can still use flags directly
- New users get guided experience
- Both paths lead to same validation quality

---

**Feature Status**: ✅ Complete and ready for testing
**Next Step**: Test interactive mode in new Claude Code session
