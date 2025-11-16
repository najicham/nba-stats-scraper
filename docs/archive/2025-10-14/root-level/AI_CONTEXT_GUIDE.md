# AI Context Guide

When working with AI assistants (Claude, ChatGPT, etc.) on your codebase, provide the right context for better results.

## Context Bundles by Task Type

### Working on a Processor

**Essential Context:**
1. **Architecture Overview**
   - `docs/ARCHITECTURE.md` - System overview
   - `docs/DATA_MODELS.md` - Data structures (create this!)
   
2. **The Processor Code**
   - File: `data_processors/raw/{source}/{processor_name}.py`
   - Example: `data_processors/raw/balldontlie/bdl_box_scores.py`
   
3. **Related Scraper Code**
   - File: `scrapers/{source}/{scraper_name}.py`
   - Shows what data format to expect
   
4. **Sample Data**
   ```bash
   # Get sample input file
   gsutil cat gs://nba-props-platform-raw/bdl_box_scores/2025/10/14/data.json
   ```
   
5. **BigQuery Schema**
   - File: `schemas/bigquery/raw/{table_name}.sql`
   - Shows expected output format
   
6. **Error Patterns**
   ```bash
   # Recent errors from this processor
   python monitoring/scripts/nba-monitor errors 48 | grep "processor_name"
   ```

**Optional Context:**
- `docs/TROUBLESHOOTING.md` - Common issues
- `docs/ALERT_SYSTEM.md` - How to add alerts
- Similar processor for reference

**AI Prompt Template:**
```
I'm working on the {processor_name} processor. Here's the context:

SYSTEM ARCHITECTURE:
[Paste relevant section from ARCHITECTURE.md]

CURRENT PROCESSOR CODE:
[Paste processor file]

SAMPLE INPUT DATA:
[Paste sample JSON from GCS]

BIGQUERY SCHEMA:
[Paste schema SQL]

RECENT ERRORS:
[Paste error logs]

TASK: [Describe what you want to do]
- Fix the error where...
- Add validation for...
- Improve performance by...
```

---

### Working on a Backfill

**Essential Context:**
1. **Backfill Guide** (create this!)
   - `docs/BACKFILL_GUIDE.md`
   
2. **The Backfill Script**
   - File: `backfill_jobs/raw/{source}/{script_name}/backfill.py`
   
3. **Alert System Doc**
   - `docs/ALERT_SYSTEM.md` - How to prevent email floods
   
4. **Date Range & Scope**
   - Start date, end date
   - Expected number of items
   - Estimated runtime
   
5. **Dependencies**
   - Which scrapers must run first?
   - Which processors depend on this?

**AI Prompt Template:**
```
I need to backfill {data_source} data from {start_date} to {end_date}.

BACKFILL SCRIPT:
[Paste backfill script]

ALERT SYSTEM SETUP:
[Paste from ALERT_SYSTEM.md about batching]

SCOPE:
- Date range: {start} to {end}
- Estimated items: ~{count}
- Expected runtime: ~{hours} hours

REQUIREMENTS:
- Must use alert batching (email flood prevention)
- Must handle rate limits
- Must be resumable if interrupted
- Must log progress

TASK: Help me make this backfill production-ready
```

---

### Working on a Scraper

**Essential Context:**
1. **Scraper Development Guide** (create this!)
   - `docs/development/SCRAPER_DEVELOPMENT.md`
   
2. **Scraper Base Class**
   - File: `scrapers/scraper_base.py`
   - Shows available utilities
   
3. **API Documentation**
   - Ball Don't Lie API docs
   - The Odds API docs
   - NBA.com API patterns
   
4. **Sample API Response**
   ```bash
   # Capture actual API response
   curl "https://api.example.com/endpoint" | jq . > sample_response.json
   ```
   
5. **GCS Output Path**
   - Where should it save data?
   - File naming convention?
   
6. **Existing Similar Scraper**
   - For reference/patterns

**AI Prompt Template:**
```
I'm building a scraper for {data_source} / {endpoint}.

SCRAPER BASE CLASS:
[Paste scraper_base.py relevant sections]

API DOCUMENTATION:
[Paste or link to API docs]

SAMPLE API RESPONSE:
[Paste sample JSON]

REQUIREMENTS:
- Save to: gs://nba-props-platform-raw/{path}/
- Use proxy: {yes/no}
- Rate limit: {requests/minute}
- Error handling: retry 3x with backoff

TASK: Build the scraper class
```

---

### Working on a Workflow

**Essential Context:**
1. **Workflow Monitoring Guide**
   - `docs/WORKFLOW_MONITORING.md`
   
2. **Existing Workflow**
   - File: `workflows/operational/{workflow_name}.yaml`
   
3. **Cloud Run Services**
   - List of available scrapers/processors
   ```bash
   gcloud run services list --region=us-west2
   ```
   
4. **Dependencies**
   - Which scrapers run first?
   - Which processors depend on scrapers?
   
5. **Schedule Requirements**
   - When should it run?
   - How long should it take?

**AI Prompt Template:**
```
I'm creating/updating the {workflow_name} workflow.

EXISTING WORKFLOW:
[Paste current workflow YAML]

AVAILABLE SERVICES:
- Scrapers: [list endpoints]
- Processors: [list endpoints]

REQUIREMENTS:
- Schedule: {cron expression}
- Scrapers to call: [list]
- Expected duration: < {minutes} minutes
- Error handling: {continue/fail}

TASK: {create new workflow / add scraper / fix error handling}
```

---

### Debugging an Error

**Essential Context:**
1. **Error Logs**
   ```bash
   # Get recent errors
   python monitoring/scripts/nba-monitor errors 24
   
   # Get specific workflow errors
   gcloud workflows executions describe {execution_id} \
     --workflow={workflow_name} --location=us-west2
   ```
   
2. **Troubleshooting Guide**
   - `docs/TROUBLESHOOTING.md`
   
3. **The Failing Code**
   - Processor, scraper, or workflow causing the error
   
4. **Recent Changes**
   ```bash
   # What changed recently?
   git log --oneline --since="3 days ago" -- path/to/file
   ```
   
5. **Expected vs Actual**
   - What should happen?
   - What's actually happening?

**AI Prompt Template:**
```
I'm debugging an error in {component_name}.

ERROR MESSAGE:
[Paste full error from logs]

FAILING CODE:
[Paste relevant code section]

CONTEXT:
- Started happening: {when}
- Happens: {always / intermittently / only for certain dates}
- Recent changes: {yes/no - describe}

EXPECTED BEHAVIOR:
[What should happen]

ACTUAL BEHAVIOR:
[What's happening instead]

TASK: Help me identify and fix the root cause
```

---

## General Best Practices

### DO Provide:
✅ **Specific error messages** (full stack trace)  
✅ **Sample data** (actual JSON, not just schema)  
✅ **Recent changes** (git log)  
✅ **Context about scale** (100 records or 100,000?)  
✅ **Time constraints** (needs to run in < 5 minutes)  
✅ **Related code** (dependencies, similar implementations)

### DON'T Provide:
❌ **Entire codebase** (too much, AI gets confused)  
❌ **Sensitive data** (API keys, credentials, PII)  
❌ **Irrelevant files** (unrelated modules)  
❌ **Vague descriptions** ("it doesn't work")  
❌ **Multiple unrelated questions** (focus on one thing)

---

## Context Bundle Templates

### Quick Reference: What to Share

| Task | Core Files | Supporting Docs | Sample Data |
|------|------------|----------------|-------------|
| **Processor** | Processor file, scraper file | ARCHITECTURE.md, schema | GCS input, expected output |
| **Backfill** | Backfill script | ALERT_SYSTEM.md, BACKFILL_GUIDE.md | Date range, item count |
| **Scraper** | Scraper base class | API docs | API response sample |
| **Workflow** | Workflow YAML | WORKFLOW_MONITORING.md | Service list |
| **Debugging** | Failing code | TROUBLESHOOTING.md | Error logs, recent git log |

---

## Keeping Context Concise

**Too much context:**
```
[Pastes entire 5000-line file]
```

**Right amount of context:**
```python
# File: data_processors/raw/balldontlie/bdl_box_scores.py (lines 45-120)
# Context: This is the main processing function that fails

def process_box_scores(raw_data):
    # [Paste only the relevant function]
    ...
```

**Use comments to explain:**
```python
# This worked fine until we added team stats
# Now it fails with KeyError on 'team_id'
# Expected structure: {'team_id': 1, 'stats': {...}}
# Actual structure: {'stats': {...}}  # team_id missing!

def process_team_stats(data):
    team_id = data['team_id']  # ← Fails here
    ...
```

---

## Advanced: Multi-File Context

When the problem spans multiple files, use this structure:

```
I'm working on {feature/bug} that involves multiple files:

FILE 1: scrapers/bdl_box_scores.py (THE SCRAPER)
[Paste relevant section]

FILE 2: data_processors/raw/balldontlie/bdl_box_scores.py (THE PROCESSOR)
[Paste relevant section]

FILE 3: schemas/bigquery/raw/bdl_box_scores.sql (THE SCHEMA)
[Paste schema]

THE ISSUE:
The scraper outputs field 'player_name' but processor expects 'playerName'.

QUESTION: Should I change the scraper or the processor?
```

---

## Example: Real Context Bundle

Here's what a good context bundle looks like for fixing a processor:

```markdown
# Context: Fixing bdl_box_scores processor

## Problem
Processor fails with: `KeyError: 'game_id'` when processing box scores from 2025-10-14

## Processor Code
\`\`\`python
# File: data_processors/raw/balldontlie/bdl_box_scores.py (lines 78-95)
def process_game(game_data):
    game_id = game_data['game_id']  # Line 79 - FAILS HERE
    home_team = game_data['home_team']
    # ...
\`\`\`

## Sample Input (from GCS)
\`\`\`json
{
  "id": 12345,  // Note: field is 'id' not 'game_id'!
  "home_team": {...},
  "away_team": {...}
}
\`\`\`

## Expected Schema
\`\`\`sql
CREATE TABLE raw.bdl_box_scores (
  game_id STRING,  -- We want 'game_id' in BigQuery
  ...
)
\`\`\`

## Task
Fix the processor to handle the field name mismatch
\`\`\`

This gives the AI everything it needs and nothing it doesn't!

---

## Summary

**The Golden Rule:**  
> Provide just enough context for the AI to understand the problem and the constraints, but not so much that it gets lost in details.

**Quick Checklist:**
- [ ] Specific file paths and line numbers
- [ ] Actual error messages (full text)
- [ ] Sample data (real examples)
- [ ] Expected behavior clearly stated
- [ ] Recent changes mentioned
- [ ] Related docs linked
- [ ] Sensitive data removed

---

**Last Updated:** 2025-10-14
