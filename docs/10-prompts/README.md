# Design Prompts

This directory contains detailed problem descriptions meant to be used as prompts for AI assistants or architectural discussions.

## Purpose

When we encounter complex design decisions that need careful thought:
1. Document the full context and constraints
2. List the options we've considered
3. Specify what questions need answering
4. Use the document as a prompt for focused discussions

## How to Use

1. Copy the content of a prompt document
2. Paste into a fresh AI chat session (Claude, ChatGPT, etc.)
3. Discuss, iterate, and capture the solution
4. Bring the solution back to implement

## Current Prompts

| Prompt | Status | Description |
|--------|--------|-------------|
| [data-completeness-strategy.md](data-completeness-strategy.md) | **Resolved** | How to handle missing/incomplete data across the pipeline |
| [data-pipeline-overview.md](data-pipeline-overview.md) | Reference | Condensed data flow reference (used with above) |

## Resolved Prompts

### data-completeness-strategy.md (2025-11-26)

**Resolution:** Produced comprehensive "Source Coverage System" design via external AI chat.

**Output:** 5 design documents ready to save to `docs/architecture/source-coverage/`:
- 00-index.md - Navigation
- 01-core-design.md - Architecture & decisions
- 02-schema-reference.md - DDL & schemas
- 03-implementation-guide.md - Python code
- 04-testing-operations.md - Tests & runbooks

**See handoff:** `docs/09-handoff/2025-11-26-source-coverage-design.md`

## Template

When creating new prompts, include:
- **Context**: What system/code is involved
- **Problem**: What specific issue triggered this
- **Requirements**: What the solution must do
- **Constraints**: Technical/business limitations
- **Options considered**: What we've thought of so far
- **Questions**: What we need answered
- **Example scenarios**: Edge cases to consider
