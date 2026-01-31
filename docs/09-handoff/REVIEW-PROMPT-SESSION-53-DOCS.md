# Documentation Review Prompt - Session 53 Shot Zone Fix

**Purpose:** Review all documentation created for the shot zone data quality fix and suggest improvements.

---

## Your Task

You are a technical documentation expert reviewing the documentation suite created for a critical data quality fix in an NBA analytics platform. Your goal is to:

1. **Assess completeness** - Are all aspects of the fix documented?
2. **Evaluate clarity** - Is the documentation clear and easy to follow?
3. **Check consistency** - Do the documents align with each other?
4. **Identify gaps** - What's missing or could be improved?
5. **Suggest improvements** - Concrete recommendations for enhancement

---

## Background Context

### What Was Fixed
A critical shot zone data corruption issue where mixing play-by-play (PBP) and box score data sources caused invalid shot zone rates:
- **Problem:** Paint rate 25.9%, Three rate 61% (corrupted due to mixed sources)
- **Solution:** All zone fields now from same PBP source
- **Impact:** 3,538 records reprocessed, rates now accurate (Paint 41.5%, Three 32.7%)

### Documentation Created
The team created a comprehensive documentation suite with 8 documents across different categories.

---

## Documents to Review

### Category 1: Handoff Documents (4 docs)

#### 1. Investigation Handoff
**File:** `docs/09-handoff/2026-01-31-SHOT-ZONE-DATA-INVESTIGATION.md`

Please read this file and assess:
- Is the root cause analysis clear and complete?
- Does it provide enough evidence to support conclusions?
- Would another engineer be able to understand the investigation approach?
- Are the fix options well-evaluated?

#### 2. Completion Handoff
**File:** `docs/09-handoff/2026-01-31-SESSION-53-SHOT-ZONE-FIX-COMPLETE.md`

Please read this file and assess:
- Are the technical details sufficient for understanding the fix?
- Are validation results clearly presented?
- Would someone be able to replicate the fix based on this doc?
- Are prevention mechanisms well-documented?

#### 3. Final Handoff
**File:** `docs/09-handoff/2026-01-31-SESSION-53-FINAL-HANDOFF.md`

Please read this file and assess:
- Does it provide comprehensive session context?
- Are key learnings valuable for future work?
- Is it too long or just right for a comprehensive handoff?
- Would future sessions benefit from this format?

#### 4. Operational Handoff
**File:** `docs/09-handoff/2026-01-31-SHOT-ZONE-FIX-HANDOFF.md`

Please read this file and assess:
- Is it actionable enough for on-call engineers?
- Are troubleshooting steps clear and practical?
- Is the decision tree helpful?
- Would you use this during an incident?

#### 5. Next Session Handoff
**File:** `docs/09-handoff/2026-01-31-SESSION-53-NEXT-SESSION-HANDOFF.md`

Please read this file and assess:
- Does it provide the right context for continuing work?
- Are "known issues" and "next steps" well-prioritized?
- Would you know what to do first in the next session?
- Is anything missing that you'd want to know?

### Category 2: Project Documentation Updates (3 docs)

#### 6. Troubleshooting Matrix - Section 2.4
**File:** `docs/02-operations/troubleshooting-matrix.md`

Please read Section 2.4 (search for "Shot Zone Data Corruption") and assess:
- Does it fit well with the rest of the troubleshooting matrix?
- Are diagnosis steps practical?
- Is it at the right level of detail (not too brief, not too verbose)?
- Would you find this during troubleshooting?

#### 7. Daily Validation Checklist - Step 3b
**File:** `docs/02-operations/daily-validation-checklist.md`

Please read Step 3b (search for "Shot Zone Data Quality") and assess:
- Does it integrate well into the daily checklist?
- Are expected ranges clearly stated?
- Are red flags obvious and actionable?
- Is it quick enough for daily use?

#### 8. CLAUDE.md - Shot Zone Quality Section
**File:** `CLAUDE.md`

Please search for "Shot Zone Data Quality" and assess:
- Does it fit the style and format of CLAUDE.md?
- Is it concise enough for quick reference?
- Does it link to detailed docs appropriately?
- Would future Claude sessions benefit from this?

---

## Review Framework

For each document category, please analyze:

### 1. Completeness
- ✅ What's well-covered?
- ❌ What's missing?
- 🤔 What questions remain unanswered?

### 2. Clarity
- 📖 What's easy to understand?
- 😕 What's confusing or unclear?
- ✏️ What could be reworded for clarity?

### 3. Usability
- 🎯 What would you actually use?
- 🗑️ What seems like it won't be referenced?
- ⚡ What makes finding information easy/hard?

### 4. Consistency
- ✅ Where do documents align well?
- ⚠️ Where do they contradict or overlap?
- 🔄 What information is repeated unnecessarily?

---

## Specific Questions to Answer

### Documentation Structure
1. Are there too many documents or too few?
2. Is the purpose of each document clear and distinct?
3. Would you consolidate any documents?
4. Are there gaps that need new documents?

### Target Audiences
5. Are the right documents available for each audience (on-call, ML engineers, analysts)?
6. Is it clear which document to use when?
7. Are any audiences underserved?

### Operational Use
8. Could you use these docs during an incident?
9. Are queries copy-paste ready?
10. Is the troubleshooting flow practical?
11. Are rollback instructions clear?

### ML/Analytics Use
12. Is guidance for ML engineers clear?
13. Are data quality filters well-documented?
14. Would analysts know how to use the data correctly?

### Maintenance
15. Will these docs stay relevant as the codebase evolves?
16. Are code locations specific enough but not too brittle?
17. What will need updating when code changes?

---

## Deliverables Requested

Please provide:

### 1. Executive Summary (1 page)
- Overall assessment of documentation quality
- 3-5 key strengths
- 3-5 critical gaps or issues
- Overall grade (A-F) with justification

### 2. Document-by-Document Review (1-2 paragraphs each)
For each of the 8 documents:
- Purpose and audience
- Strengths
- Weaknesses
- Specific improvement recommendations

### 3. Cross-Cutting Issues (1 page)
- Consistency problems across documents
- Redundancy or gaps in coverage
- Structural or organizational issues
- Navigation and discoverability concerns

### 4. Prioritized Improvement Recommendations
Rank these by impact:
1. **Critical** (must fix) - Issues that make docs unusable or misleading
2. **High** (should fix) - Significant gaps or confusion points
3. **Medium** (nice to have) - Improvements that add value
4. **Low** (polish) - Minor clarifications or formatting

For each recommendation, specify:
- What to change
- Why it matters
- Which document(s) to modify
- Estimated effort (trivial / small / medium / large)

### 5. Alternative Structures (if applicable)
If you think the documentation could be organized differently:
- Propose alternative structure
- Explain benefits over current approach
- Suggest migration path

### 6. Template Recommendations
Based on this example, suggest:
- What worked well that should be a template for future data quality fixes
- What was overkill that shouldn't be repeated
- What documentation template would help

---

## Evaluation Criteria

Use these criteria to assess the documentation:

### Quality Dimensions
- **Accuracy**: Is information correct and up-to-date?
- **Completeness**: Are all aspects covered?
- **Clarity**: Is it easy to understand?
- **Conciseness**: No more words than necessary?
- **Actionability**: Can readers act on the information?
- **Findability**: Can readers find what they need?
- **Maintainability**: Will docs stay current with code?

### Red Flags to Watch For
- 🚩 Contradictory information between documents
- 🚩 Outdated code line numbers or file paths
- 🚩 Vague instructions ("check the logs")
- 🚩 Missing context (assumes too much knowledge)
- 🚩 Over-documentation (walls of text)
- 🚩 Under-documentation (critical steps missing)
- 🚩 Poor navigation (can't find what you need)

---

## Context Questions

To calibrate your review, consider:

### Project Context
- This is a production NBA analytics platform
- Multiple teams use this data (ML engineers, analysts, operations)
- Issues can impact live predictions and business metrics
- Documentation is critical because Claude sessions don't have memory

### User Context
- On-call engineers may not know the codebase deeply
- ML engineers need to know how data quality affects training
- Future Claude sessions need to understand past fixes
- Data analysts need to know when to trust shot zone data

### Time Context
- This fix was completed in a single 2-hour session
- Documentation was created immediately after the fix
- The goal was comprehensive coverage for future reference
- Trade-off between thoroughness and maintainability

---

## How to Conduct Your Review

### Step 1: Read All Documents (30-45 min)
Read each document fully to understand the complete picture.

### Step 2: Take Notes (15-20 min)
As you read, note:
- Strengths and weaknesses
- Questions that arise
- Confusing sections
- Missing information

### Step 3: Cross-Reference (10-15 min)
Check consistency:
- Do technical details match across docs?
- Are queries consistent?
- Do line numbers align?
- Are thresholds the same everywhere?

### Step 4: User Scenarios (15-20 min)
Test the docs against scenarios:
- "I'm on-call and shot zone rates look wrong"
- "I'm training an ML model and need shot zone data"
- "I'm starting a new session and need context"
- "I want to understand what happened"

### Step 5: Synthesize (20-30 min)
Write your review following the deliverables format.

---

## Example Review Format

```markdown
# Documentation Review: Session 53 Shot Zone Fix

## Executive Summary
[Overall assessment with grade]

## Document Reviews

### Investigation Handoff
**Purpose:** [state purpose]
**Audience:** [who uses this]
**Strengths:**
- [bullet points]
**Weaknesses:**
- [bullet points]
**Recommendations:**
- [specific improvements]

[... repeat for each document ...]

## Cross-Cutting Issues
[Consistency, redundancy, navigation issues]

## Prioritized Recommendations

### Critical (Must Fix)
1. [Issue] - [Fix] - [Effort: X]

### High Priority (Should Fix)
1. [Issue] - [Fix] - [Effort: X]

[... etc ...]

## Alternative Structure Proposal
[If applicable]

## Template Recommendations
[What to keep for future fixes]
```

---

## Success Criteria

Your review is successful if:
- ✅ You've read all 8 documents thoroughly
- ✅ You've identified both strengths and weaknesses
- ✅ Recommendations are specific and actionable
- ✅ You've tested against user scenarios
- ✅ Improvements are prioritized by impact
- ✅ The review helps improve documentation quality

---

## Final Notes

- Be honest and critical - the goal is improvement
- Consider both current usability and long-term maintenance
- Think about different user personas (on-call, ML, analysts, future Claude)
- Balance thoroughness with conciseness
- Suggest concrete improvements, not just critiques
- Consider what will age well vs. become outdated quickly

---

**Ready to begin?**

Start by reading all documents, then provide your comprehensive review following the deliverables format above.

Good luck! 🚀
