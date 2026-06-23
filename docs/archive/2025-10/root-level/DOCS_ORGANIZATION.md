# Documentation Organization Guide

## File Naming Strategy

### When to Use Date Prefixes

**Format:** `YY-MM-DD-descriptive-name.md`

**Use dates for:**
- 📝 Implementation notes at a specific point in time
- 🔄 Evolution/iteration docs (v1, v2, v3)
- 🎯 Decision logs (why we chose X at time Y)
- 📊 Historical context (how things worked back then)
- 🐛 Problem investigation notes
- 🧪 Experiment results

**Examples:**
```
docs/decisions/
├── 25-07-10-why-cloud-run.md          ← Decision made July 10
├── 25-07-15-bigquery-vs-postgres.md   ← Comparison at that time
└── 25-08-01-proxy-strategy-pivot.md   ← Strategy change

docs/reference/backfill/
├── 25-08-02-initial-strategy.md       ← First attempt
├── 25-08-05-revised-approach.md       ← After learning
└── 25-08-14-final-implementation.md   ← What we settled on

docs/investigations/
├── 25-10-14-proxy-exhaustion-debug.md ← Investigation notes
└── 25-10-13-bdl-api-slowness.md       ← Performance issue
```

### When NOT to Use Date Prefixes

**Use descriptive names for:**
- 📘 Current/canonical documentation
- 🏗️ Architecture overviews (current state)
- 💻 Development guides (how to do X now)
- 📚 API references
- 🔧 Troubleshooting guides (evergreen)

**Examples:**
```
docs/
├── README.md                          ← Always current index
├── CONTRIBUTING.md                    ← Current contribution guide
├── architecture/
│   ├── system-overview.md            ← Current architecture
│   ├── data-pipeline.md              ← How it works today
│   └── service-catalog.md            ← Current services
├── development/
│   ├── getting-started.md            ← Onboarding guide
│   ├── scraper-development.md        ← How to build scrapers
│   └── testing-guide.md              ← Testing practices
└── operations/
    ├── monitoring-guide.md           ← Current monitoring
    └── deployment-guide.md           ← How to deploy
```

## Migration Strategy for Your Existing Docs

### Step 1: Categorize Your Docs

Review each dated file and ask:
- **Is this historical context?** → Keep date, move to `reference/` or `decisions/`
- **Is this current practice?** → Remove date, consolidate into canonical doc
- **Is this outdated?** → Keep date, move to `archive/`

### Step 2: Consolidation Pattern

**Multiple dated docs on same topic:**
```bash
# Before:
docs/scrapers/
├── 25-07-12-flask.md
├── 25-07-13-journey.md
├── 25-07-17-pipeline-v2.md
└── 25-07-21-operational-ref.md

# After:
docs/development/
└── scraper-development.md              ← Consolidated current state

docs/reference/scrapers/history/
├── 25-07-12-flask-decision.md          ← Why Flask (context)
├── 25-07-17-pipeline-v2-changes.md     ← What changed in v2
└── evolution-summary.md                 ← Timeline of changes
```

### Step 3: Add "Last Updated" to Canonical Docs

For non-dated docs, add metadata:

```markdown
# Scraper Development Guide

**Last Updated:** 2025-10-14
**Last Reviewed:** 2025-10-14
**Maintainer:** @your-handle

---

[Content here]
```

## Directory Structure

```
docs/
├── README.md                          # Master index
│
├── architecture/                      # Current architecture (no dates)
│   ├── README.md
│   ├── system-overview.md
│   ├── data-flow.md
│   └── service-catalog.md
│
├── development/                       # Current dev guides (no dates)
│   ├── README.md
│   ├── getting-started.md
│   ├── scraper-development.md
│   ├── testing-guide.md
│   └── deployment-guide.md
│
├── operations/                        # Links to wiki (no dates)
│   ├── README.md
│   └── monitoring-setup.md
│
├── decisions/                         # Architecture Decision Records (WITH dates)
│   ├── README.md                     # Index of all decisions
│   ├── 25-07-10-001-cloud-run.md    # ADR format
│   ├── 25-07-15-002-database.md
│   └── template.md                   # ADR template
│
├── reference/                         # Historical implementation (WITH dates)
│   ├── backfill/
│   │   ├── 25-08-02-strategy.md
│   │   ├── 25-08-05-gamebook.md
│   │   └── 25-08-14-summary.md
│   ├── scrapers/
│   │   ├── 25-07-12-flask-decision.md
│   │   └── 25-07-17-pipeline-v2.md
│   └── processors/
│       └── basketball_ref_processor.md
│
├── investigations/                    # Problem investigations (WITH dates)
│   ├── 25-10-14-proxy-exhaustion.md
│   └── 25-10-13-api-slowness.md
│
└── archive/                           # Old/outdated docs (keep dates)
    ├── conversation-contexts/
    └── summaries/
```

## Best Practices

### For Dated Documents

1. **Use YYYY-MM-DD format** for better sorting:
   ```
   Good: 2025-10-14-proxy-fix.md
   Okay: 25-10-14-proxy-fix.md
   Bad:  10-14-25-proxy-fix.md
   ```

2. **Add context in filename:**
   ```
   Good: 25-08-14-backfill-final-summary.md
   Okay: 25-08-14-backfill.md
   Bad:  25-08-14-notes.md
   ```

3. **Include status in content:**
   ```markdown
   # Backfill Strategy

   **Status:** Superseded by [25-08-14-backfill-final-summary.md]
   **Date:** 2025-08-02
   **Context:** Initial exploration, later revised
   ```

### For Canonical Documents

1. **Include "Last Updated":**
   ```markdown
   # Scraper Development Guide

   **Last Updated:** 2025-10-14
   ```

2. **Link to historical context:**
   ```markdown
   ## History

   This guide consolidates:
   - [Flask decision (2025-07-12)](reference/scrapers/25-07-12-flask-decision.md)
   - [Pipeline v2 changes (2025-07-17)](reference/scrapers/25-07-17-pipeline-v2.md)
   ```

3. **Review schedule:**
   ```markdown
   **Review Schedule:** Quarterly
   **Next Review:** 2026-01-14
   ```

## Migration Script

```bash
#!/bin/bash
# Rename files to use full year format

for file in docs/**/*-*-*-*.md; do
    if [[ $file =~ ([0-9]{2})-([0-9]{2})-([0-9]{2})-(.*) ]]; then
        yy="${BASH_REMATCH[1]}"
        mm="${BASH_REMATCH[2]}"
        dd="${BASH_REMATCH[3]}"
        name="${BASH_REMATCH[4]}"

        # Convert 25 -> 2025
        yyyy="20${yy}"

        newname="${yyyy}-${mm}-${dd}-${name}"

        # Only rename if format changed
        if [[ $file != *"$newname"* ]]; then
            echo "Renaming: $(basename $file) -> ${newname}"
            # mv "$file" "$(dirname $file)/${newname}"
        fi
    fi
done
```

## Decision Log Template

For architecture decisions, use this template:

```markdown
# ADR-NNN: Title

**Date:** YYYY-MM-DD
**Status:** [Proposed | Accepted | Deprecated | Superseded by ADR-XXX]
**Deciders:** [Names]
**Tags:** [architecture, scrapers, data-pipeline]

## Context

What is the issue that we're seeing that is motivating this decision?

## Decision

What is the change that we're proposing and/or doing?

## Consequences

What becomes easier or more difficult to do because of this change?

## Alternatives Considered

What other options did we consider?

## References

- Link to related discussions
- Link to related code
```

## Summary

**Keep date prefixes when:**
- Documenting decisions at a point in time
- Showing evolution/history
- Investigation notes
- You want chronological context

**Remove date prefixes when:**
- Document should always be current
- Canonical reference documentation
- User guides that need to stay updated
- You want topic-based discovery

**Best of both worlds:**
- Dated docs in `decisions/`, `reference/`, `investigations/`
- Evergreen docs in `architecture/`, `development/`, `operations/`
- Both serve different purposes
