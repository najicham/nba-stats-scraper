---
name: monitoring
description: Run pending monitoring checks from the checklist, evaluate results, and update the checklist with outcomes
---

# Monitoring Checklist Runner

You are running the pending monitoring checks from `docs/02-operations/MONITORING-CHECKLIST.md`. This is a **diagnostic + housekeeping** task — run queries, evaluate results against decision criteria, and update the checklist.

## Your Mission

1. Read the monitoring checklist
2. Identify which items are DUE (check date <= today)
3. Run the queries for each due item
4. Evaluate results against the decision criteria listed in the checklist
5. Present findings with clear recommendations
6. Update the checklist: move resolved items to RESOLVED, update dates for items that need more data

## Step 1: Read the Checklist

```bash
cat docs/02-operations/MONITORING-CHECKLIST.md
```

Read the file carefully. Identify items in the ACTIVE section whose check date has arrived or passed. Today's date is available from `date +%Y-%m-%d`.

## Step 2: Run Due Checks

For each item that is due, run the SQL query listed in the checklist using:

```bash
bq query --use_legacy_sql=false --format=pretty "QUERY_HERE"
```

Run multiple independent queries in parallel where possible.

## Step 3: Evaluate Results

For each check, compare results against the **decision criteria** listed in the checklist item. Classify each as:

- **PASS** — meets the criteria, item can be resolved
- **FAIL** — doesn't meet criteria, action needed (describe what)
- **INSUFFICIENT DATA** — N is too small, push the check date forward 1 week
- **NOT YET DUE** — check date hasn't arrived, skip

## Step 4: Present Summary

Format the output as:

```
## Monitoring Check Results — [DATE]

### DUE ITEMS

#### [Item #] [Item Name] — [PASS/FAIL/INSUFFICIENT]
- **Query result:** [1-2 line summary of what the data shows]
- **Decision criteria:** [what was expected]
- **Verdict:** [what to do]
- **Action needed:** [specific action, or "None — resolved"]

### NOT YET DUE
- Item #X: [name] — due ~[date]
- Item #Y: [name] — due ~[date]

### ITEMS NEEDING ATTENTION
[Any FAIL items with recommended actions]
```

## Step 5: Update the Checklist

After presenting results, update `docs/02-operations/MONITORING-CHECKLIST.md`:

1. Move PASS items to the RESOLVED section with today's date and the outcome
2. For INSUFFICIENT DATA items, update the check date to +1 week
3. For FAIL items, add a note about what was found and what action is recommended
4. Add any NEW monitoring items that arose from the checks (e.g., "monitor the fix we just applied")

**Important:** Use the Edit tool to make targeted changes. Do NOT rewrite the entire file.

## Step 6: New Items

If the user has done work this session that creates new monitoring needs, ask whether to add them to the checklist. Common triggers:
- New signals deployed (shadow or production)
- New filters added (active or observation mode)
- Model changes (retrain, disable, enable)
- Infrastructure changes (scheduler jobs, env vars)

## Guidelines

- **Be concise** — don't repeat the full query in the output, just summarize what it returned
- **Be decisive** — if the data is clear, make the recommendation. Don't hedge when N is sufficient.
- **Be honest about N** — if sample size is too small, say so and defer. Don't draw conclusions from N < 15.
- **Track everything** — every decision and outcome goes in the checklist. Future sessions depend on this history.
- **Don't run queries for items that aren't due** — respect the check dates to avoid wasting BQ quota on items that need more data accumulation.
