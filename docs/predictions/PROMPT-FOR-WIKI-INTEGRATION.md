# Prompt for Wiki Documentation Integration

Use this prompt to start a fresh conversation for integrating wiki documentation into the Phase 5 predictions docs.

---

## PROMPT FOR NEW CONVERSATION

I need help integrating wiki documentation into the official Phase 5 predictions documentation. I have 10 comprehensive wiki docs that need to be added to the existing documentation structure.

### Current State

**Existing Documentation**:
- Location: `docs/predictions/`
- Current files: 7 markdown files across 4 directories
- Structure:
  - `operations/` (4 files: 01-deployment-guide.md, 02-scheduling-strategy.md, 03-troubleshooting.md, 04-worker-deepdive.md)
  - `data-sources/` (1 file: 01-data-categorization.md)
  - `architecture/` (1 file: 01-parallelization-strategy.md)
  - `tutorials/` (1 file: 01-getting-started.md)

**Integration Plan**:
- Already created at `docs/predictions/INTEGRATION-PLAN-2025-11-16.md`
- Review this FIRST to understand the complete plan
- Plan adds 13 new files across 5 directories (3 new directories)

### What You Need to Do

**Step 1**: Review existing documentation structure
- Read `docs/predictions/README.md` to understand current organization
- Read `docs/predictions/INTEGRATION-PLAN-2025-11-16.md` for the complete integration plan
- Scan the 7 existing docs to understand style and formatting conventions

**Step 2**: Process wiki docs I will share
- I will share 10 wiki documents (labeled Doc 1-10)
- Each has already been analyzed for unique content vs redundancy
- Use the integration plan to know which parts to extract

**Step 3**: Create new documentation files
According to the integration plan, create these 13 new files:

**operations/** (5 new files):
- `05-daily-operations-checklist.md` (from Doc 1, parts 1-4)
- `06-performance-monitoring.md` (from Doc 6, complete)
- `07-weekly-maintenance.md` (from Doc 1, part 5)
- `08-monthly-maintenance.md` (from Doc 1, part 6)
- `09-emergency-procedures.md` (from Doc 1 part 7 + Doc 8)

**ml-training/** (2 new files, new directory):
- `01-initial-model-training.md` (from Doc 5, complete)
- `02-continuous-retraining.md` (from Doc 7, complete)

**algorithms/** (2 new files, new directory):
- `01-composite-factor-calculations.md` (from Doc 3, complete)
- `02-confidence-scoring-framework.md` (from Doc 4, complete)

**tutorials/** (3 new files):
- `02-understanding-prediction-systems.md` (from Doc 9, complete)
- `03-worked-prediction-examples.md` (from Doc 10, complete)
- `04-operations-command-reference.md` (from Doc 1, part 9)

**design/** (1 new file, new directory):
- `01-architectural-decisions.md` (from Doc 2, extract design rationale ONLY - 40% of content)

**Step 4**: Update README.md
- Add all 13 new files to the reading order
- Update directory structure diagram
- Add new quick start sections for ML training, algorithms
- Update documentation coverage table (7 → 20 files)

### Important Guidelines

**Formatting**:
- Use existing docs as style reference (check operations/01-deployment-guide.md)
- Include standard header: File path, Created date, Purpose, Status
- Use same markdown conventions (tables, code blocks, headings)
- Keep code blocks properly formatted with language tags

**Numbering**:
- DO NOT renumber existing files (they stay 01-04, 01, 01, 01)
- New files continue sequential numbering (05-09 in operations, 02-04 in tutorials)
- New directories start at 01

**Content Extraction**:
- For Docs 1, 3-10: Use complete content (95-100% unique)
- For Doc 2: Extract ONLY design rationale sections (~40% unique), discard architecture diagrams/flows (already documented elsewhere)
- For Doc 8: Merge advanced troubleshooting with Doc 1's emergency procedures

**Cross-References**:
- Link related docs (e.g., troubleshooting → emergency procedures)
- Link to processor cards in `docs/processor-cards/`
- Link to source code in `predictions/` directory

### Key Context

**Phase 5 Overview**:
- Coordinator-worker pattern for generating player points predictions
- 5 prediction systems: Moving Average, XGBoost, Zone Matchup, Similarity, Ensemble
- Pub/Sub orchestration, Cloud Run services
- Output: predictions with confidence scores and OVER/UNDER/PASS recommendations
- Status: Code complete, not yet deployed

**Critical Gaps Being Filled**:
- ML training procedures (how to train XGBoost model)
- Performance monitoring (GCP monitoring, Grafana dashboards)
- Algorithm specifications (mathematical formulas)
- Daily operations checklists
- Retraining and drift detection

### Wiki Docs I'll Share

I will share these 10 documents in the conversation:

1. **Doc 1**: Phase 5 Quick Reference & Operations Guide (daily/weekly/monthly operations, emergency procedures, commands)
2. **Doc 2**: Architecture & System Design (extract design rationale only)
3. **Doc 3**: Composite Factor Calculations (complete algorithm specs)
4. **Doc 4**: Confidence Scoring Logic (6-factor framework)
5. **Doc 5**: ML Model Training & Validation (XGBoost training guide)
6. **Doc 6**: Performance Monitoring & Dashboards (GCP monitoring, Grafana)
7. **Doc 7**: Retraining & Continuous Improvement (drift detection, A/B testing)
8. **Doc 8**: Troubleshooting Guide (advanced scenarios, merge with emergency procedures)
9. **Doc 9**: Understanding Rule-Based Prediction Systems (educational tutorial)
10. **Doc 10**: Phase 5 Prediction Systems Tutorial (worked examples)

### Expected Deliverables

1. **13 new markdown files** created in correct directories
2. **Updated README.md** with complete reading guide
3. **Validation report** confirming:
   - All files created successfully
   - Formatting matches existing conventions
   - Cross-references added
   - No broken links
   - No duplicate content

### Success Criteria

- ✅ All existing files preserved (no renumbering)
- ✅ 13 new files match integration plan structure
- ✅ README.md updated with all new docs
- ✅ Consistent formatting across all files
- ✅ Proper extraction (Doc 2 design rationale only)
- ✅ All internal links working

### Notes

- If conversation context is limited, prioritize creating the files first (Steps 1-3), then update README (Step 4) in a second conversation
- The integration plan document has complete analysis if you need more details
- Existing docs are well-formatted - use them as reference for style

---

## ALTERNATIVE: Split Across Two Conversations

If you need to split this work:

### Conversation 1: ML & Algorithms (6 new files)
**Task**: Create ml-training, algorithms, and design directories

Share Docs: 2, 3, 4, 5, 7
Create files:
- `ml-training/01-initial-model-training.md` (Doc 5)
- `ml-training/02-continuous-retraining.md` (Doc 7)
- `algorithms/01-composite-factor-calculations.md` (Doc 3)
- `algorithms/02-confidence-scoring-framework.md` (Doc 4)
- `design/01-architectural-decisions.md` (Doc 2 extract)

### Conversation 2: Operations & Tutorials (7 new files + README update)
**Task**: Add to operations and tutorials, update README

Share Docs: 1, 6, 8, 9, 10
Create files:
- `operations/05-daily-operations-checklist.md` (Doc 1)
- `operations/06-performance-monitoring.md` (Doc 6)
- `operations/07-weekly-maintenance.md` (Doc 1)
- `operations/08-monthly-maintenance.md` (Doc 1)
- `operations/09-emergency-procedures.md` (Doc 1 + Doc 8)
- `tutorials/02-understanding-prediction-systems.md` (Doc 9)
- `tutorials/03-worked-prediction-examples.md` (Doc 10)
- `tutorials/04-operations-command-reference.md` (Doc 1)
- Update `README.md` with all 13 new files

**Benefit of split**: Each conversation handles ~6-7 files instead of all 13

---

## Files to Reference in Working Directory

Before starting, review these files:
1. `docs/predictions/INTEGRATION-PLAN-2025-11-16.md` ← **READ THIS FIRST**
2. `docs/predictions/README.md`
3. `docs/predictions/operations/01-deployment-guide.md` (style reference)
4. `docs/processor-cards/phase5-prediction-coordinator.md`
5. `predictions/worker/ARCHITECTURE.md`

---

**Created**: 2025-11-16
**Purpose**: Handoff prompt for wiki documentation integration
**Status**: Ready to use in new conversation
