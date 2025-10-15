#!/bin/bash
#
# File: docs/migrate_documentation.sh
#
# Complete documentation migration script
# - Renames dated files to use full year (25-XX-XX → 2025-XX-XX)
# - Reorganizes into new structure
# - Creates new canonical documentation files
#
# Run from repo root: ./docs/migrate_documentation.sh

set -e

REPO_ROOT="$(pwd)"
DOCS_DIR="${REPO_ROOT}/docs"

echo "📚 NBA Props Platform Documentation Migration"
echo "=============================================="
echo ""

# Confirm we're in the right place
if [[ ! -f "scrapers/main_scraper_service.py" ]]; then
    echo "❌ Error: Please run this script from the repo root directory"
    echo "   Current directory: $(pwd)"
    exit 1
fi

echo "✓ Running from: ${REPO_ROOT}"
echo ""

# Backup existing docs
BACKUP_DIR="${DOCS_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
echo "📦 Creating backup at: ${BACKUP_DIR}"
cp -r "${DOCS_DIR}" "${BACKUP_DIR}"
echo "✓ Backup created"
echo ""

# ==============================================================================
# STEP 1: Create new directory structure
# ==============================================================================
echo "📁 Creating new directory structure..."

mkdir -p "${DOCS_DIR}/architecture"
mkdir -p "${DOCS_DIR}/development"
mkdir -p "${DOCS_DIR}/operations"
mkdir -p "${DOCS_DIR}/decisions"
mkdir -p "${DOCS_DIR}/reference/backfill"
mkdir -p "${DOCS_DIR}/reference/scrapers"
mkdir -p "${DOCS_DIR}/reference/processors"
mkdir -p "${DOCS_DIR}/reference/workflows"
mkdir -p "${DOCS_DIR}/reference/schedule"
mkdir -p "${DOCS_DIR}/reference/data_patterns"
mkdir -p "${DOCS_DIR}/investigations"
mkdir -p "${DOCS_DIR}/archive"

echo "✓ Directories created"
echo ""

# ==============================================================================
# STEP 2: Rename dated files to use full year (25-XX-XX → 2025-XX-XX)
# ==============================================================================
echo "📝 Renaming dated files to use full year format..."

rename_dated_files() {
    local dir="$1"
    local count=0
    
    # Find all files matching YY-MM-DD pattern
    find "$dir" -type f -name "25-*.md" 2>/dev/null | while read -r file; do
        local basename=$(basename "$file")
        local dirname=$(dirname "$file")
        
        # Extract date components
        if [[ $basename =~ ^25-([0-9]{2})-([0-9]{2})-(.*\.md)$ ]]; then
            local mm="${BASH_REMATCH[1]}"
            local dd="${BASH_REMATCH[2]}"
            local rest="${BASH_REMATCH[3]}"
            
            local newname="2025-${mm}-${dd}-${rest}"
            
            echo "  Renaming: ${basename} → ${newname}"
            mv "$file" "${dirname}/${newname}"
            ((count++)) || true
        fi
    done
}

rename_dated_files "${DOCS_DIR}"

echo "✓ File renaming complete"
echo ""

# ==============================================================================
# STEP 3: Move files to proper locations
# ==============================================================================
echo "🗂️  Reorganizing files..."

# Move backfill docs (already in right place, just ensure)
if [[ -d "${DOCS_DIR}/backfill" ]]; then
    echo "  Moving backfill docs..."
    mv "${DOCS_DIR}/backfill"/* "${DOCS_DIR}/reference/backfill/" 2>/dev/null || true
    rmdir "${DOCS_DIR}/backfill" 2>/dev/null || true
fi

# Move scraper docs
if [[ -d "${DOCS_DIR}/scrapers" ]]; then
    echo "  Moving scraper docs..."
    mv "${DOCS_DIR}/scrapers"/* "${DOCS_DIR}/reference/scrapers/" 2>/dev/null || true
    rmdir "${DOCS_DIR}/scrapers" 2>/dev/null || true
fi

# Move processor docs
if [[ -d "${DOCS_DIR}/processors" ]]; then
    echo "  Moving processor docs..."
    mv "${DOCS_DIR}/processors"/* "${DOCS_DIR}/reference/processors/" 2>/dev/null || true
    rmdir "${DOCS_DIR}/processors" 2>/dev/null || true
fi

# Move workflow docs
if [[ -d "${DOCS_DIR}/workflow" ]]; then
    echo "  Moving workflow docs..."
    mv "${DOCS_DIR}/workflow"/* "${DOCS_DIR}/reference/workflows/" 2>/dev/null || true
    rmdir "${DOCS_DIR}/workflow" 2>/dev/null || true
fi

# Move schedule docs
if [[ -d "${DOCS_DIR}/schedule" ]]; then
    echo "  Moving schedule docs..."
    mv "${DOCS_DIR}/schedule"/* "${DOCS_DIR}/reference/schedule/" 2>/dev/null || true
    rmdir "${DOCS_DIR}/schedule" 2>/dev/null || true
fi

# Move data patterns
if [[ -d "${DOCS_DIR}/data_patterns" ]]; then
    echo "  Moving data pattern docs..."
    mv "${DOCS_DIR}/data_patterns"/* "${DOCS_DIR}/reference/data_patterns/" 2>/dev/null || true
    rmdir "${DOCS_DIR}/data_patterns" 2>/dev/null || true
fi

# Move existing architecture/dev docs to reference if they're dated
mv "${DOCS_DIR}/architecture.md" "${DOCS_DIR}/architecture/system-architecture.md" 2>/dev/null || true
mv "${DOCS_DIR}/service-architecture.md" "${DOCS_DIR}/architecture/" 2>/dev/null || true
mv "${DOCS_DIR}/infrastructure-decisions.md" "${DOCS_DIR}/architecture/" 2>/dev/null || true
mv "${DOCS_DIR}/development-workflow.md" "${DOCS_DIR}/development/" 2>/dev/null || true
mv "${DOCS_DIR}/dev-cheatsheet.md" "${DOCS_DIR}/development/" 2>/dev/null || true
mv "${DOCS_DIR}/docker-strategy.md" "${DOCS_DIR}/development/" 2>/dev/null || true
mv "${DOCS_DIR}/dockerfile.md" "${DOCS_DIR}/development/" 2>/dev/null || true
mv "${DOCS_DIR}/cloud-run-deployment.md" "${DOCS_DIR}/development/" 2>/dev/null || true
mv "${DOCS_DIR}/scraper-testing-guide.md" "${DOCS_DIR}/development/" 2>/dev/null || true
mv "${DOCS_DIR}/fixture-capture.md" "${DOCS_DIR}/development/" 2>/dev/null || true

# Move existing operational docs
mv "${DOCS_DIR}/monitoring-guide.md" "${DOCS_DIR}/operations/" 2>/dev/null || true
mv "${DOCS_DIR}/troubleshooting.md" "${DOCS_DIR}/operations/" 2>/dev/null || true

# Archive old contexts and summaries
mv "${DOCS_DIR}/conversation-contexts" "${DOCS_DIR}/archive/" 2>/dev/null || true
mv "${DOCS_DIR}/summaries" "${DOCS_DIR}/archive/" 2>/dev/null || true
mv "${DOCS_DIR}/first-schema" "${DOCS_DIR}/archive/" 2>/dev/null || true
mv "${DOCS_DIR}/general" "${DOCS_DIR}/archive/" 2>/dev/null || true

# Move validation guide
mv "${DOCS_DIR}/VALIDATION_HANDOFF_GUIDE_v2.md" "${DOCS_DIR}/reference/" 2>/dev/null || true

echo "✓ Files reorganized"
echo ""

# ==============================================================================
# STEP 4: Create new documentation files
# ==============================================================================
echo "📄 Creating new documentation files..."

# Helper function to create file with content marker
create_doc() {
    local filepath="$1"
    local title="$2"
    
    echo "  Creating: ${filepath}"
    
    cat > "$filepath" << 'EOF'
# PLACEHOLDER - Copy content from Claude artifacts

This file needs to be populated with content from the corresponding Claude artifact.

See: https://claude.ai (search for the artifact name in your conversation)

EOF
}

# Main docs README
cat > "${DOCS_DIR}/README.md" << 'EOF'
# NBA Props Platform Documentation

**Quick Links:**
- 📖 **[Wiki](https://your-wiki-url)** - Operational guides, troubleshooting, daily procedures
- 💻 **[GitHub](.)** - Technical docs, architecture, development guides

## Documentation Structure

This repository contains **technical and development documentation**. For operational guides and how-tos, see the **[Wiki](https://your-wiki-url)**.

### 📁 What's Where

```
docs/
├── architecture/        → System design and architecture decisions
├── development/         → Development workflows and guides
├── operations/          → Links to wiki for operational guides
├── decisions/           → Architecture Decision Records
├── reference/           → Historical implementation notes (dated files)
├── investigations/      → Problem investigation notes (dated files)
└── archive/             → Old/outdated documentation
```

## Quick Start

### For New Developers
1. Read [architecture/system-overview.md](architecture/system-overview.md)
2. Read [development/getting-started.md](development/getting-started.md)
3. Set up monitoring: [operations/README.md](operations/README.md)

### For Operators/On-Call
1. Go to [Wiki](https://your-wiki-url) - this is your main resource
2. Use `nba-monitor status yesterday` daily
3. See [operations/README.md](operations/README.md) for tools

### For Troubleshooting
1. Check [Wiki: Troubleshooting](https://your-wiki-url/troubleshooting)
2. Use monitoring tools in [operations/README.md](operations/README.md)
3. Review recent [investigations/](investigations/)

## Directory Overview

### architecture/
Current system architecture and design decisions.
- **system-overview.md** - High-level architecture
- **system-architecture.md** - Detailed technical architecture
- **service-architecture.md** - Cloud Run services
- **infrastructure-decisions.md** - Infrastructure choices

### development/
Development workflows and practices.
- **getting-started.md** - Onboarding guide
- **development-workflow.md** - Development process
- **scraper-testing-guide.md** - Testing scrapers
- **deployment-guide.md** - Deployment procedures

### operations/
Operational guides (most content in Wiki).
- **README.md** - Links to wiki and monitoring tools
- **monitoring-setup.md** - How to set up monitoring

### decisions/
Architecture Decision Records (ADRs) with dates.
- Format: `YYYY-MM-DD-title.md`
- Records why we made specific architectural choices

### reference/
Historical implementation notes (dated files).
- **backfill/** - Backfill strategies over time
- **scrapers/** - Scraper evolution
- **processors/** - Processor implementations
- **workflows/** - Workflow configurations

### investigations/
Problem investigation notes (dated files).
- Format: `YYYY-MM-DD-problem-description.md`
- Debugging notes and resolution

## Documentation Standards

**Dated files** (decisions, reference, investigations):
- Format: `YYYY-MM-DD-descriptive-name.md`
- Use for historical context
- Include status at top (Active, Superseded, etc.)

**Canonical files** (architecture, development, operations):
- No date prefix
- Always kept current
- Include "Last Updated: YYYY-MM-DD" at top

## Contributing

See [DOCS_ORGANIZATION.md](DOCS_ORGANIZATION.md) for detailed guidelines on:
- When to use date prefixes
- File naming conventions
- Where to put new docs

---

**Last Updated:** $(date +%Y-%m-%d)
**Backup Location:** ${BACKUP_DIR}
EOF

echo "  Created: docs/README.md"

# Architecture README
cat > "${DOCS_DIR}/architecture/README.md" << 'EOF'
# Architecture Documentation

Current system architecture and design decisions.

## Files

- **system-overview.md** - High-level architecture overview (start here!)
- **system-architecture.md** - Detailed technical architecture
- **service-architecture.md** - Cloud Run services details
- **infrastructure-decisions.md** - Why we chose specific infrastructure

## Related

- See [../decisions/](../decisions/) for specific architecture decisions (dated)
- See [Wiki: Architecture](https://your-wiki-url/architecture) for user-friendly overview
EOF

# Development README
cat > "${DOCS_DIR}/development/README.md" << 'EOF'
# Development Documentation

Development workflows, guides, and best practices.

## Getting Started

1. **[getting-started.md](getting-started.md)** - New developer onboarding
2. **[development-workflow.md](development-workflow.md)** - Development process
3. **[scraper-testing-guide.md](scraper-testing-guide.md)** - How to test scrapers

## Deployment

- **[deployment-guide.md](deployment-guide.md)** - How to deploy changes
- **[cloud-run-deployment.md](cloud-run-deployment.md)** - Cloud Run specifics

## Reference

- **[dev-cheatsheet.md](dev-cheatsheet.md)** - Quick command reference
- **[docker-strategy.md](docker-strategy.md)** - Docker & containerization

## Related

- See [../reference/scrapers/](../reference/scrapers/) for scraper evolution history
- See [Wiki: Development](https://your-wiki-url/development) for additional guides
EOF

# Operations README
cat > "${DOCS_DIR}/operations/README.md" << 'EOF'
# Operations Documentation

For detailed operational guides, see the **[Wiki](https://your-wiki-url)**.

## Quick Links to Wiki

- **[Workflow Monitoring Guide](https://your-wiki-url/monitoring)** - Daily monitoring procedures
- **[Troubleshooting Guide](https://your-wiki-url/troubleshooting)** - Common issues and fixes
- **[System Overview](https://your-wiki-url/overview)** - How the system works
- **[Runbooks](https://your-wiki-url/runbooks)** - Step-by-step procedures

## Monitoring Tools

### nba-monitor (Main Tool)

Daily status check:
```bash
nba-monitor status yesterday
```

View errors:
```bash
nba-monitor errors 24
```

View workflows:
```bash
nba-monitor workflows
```

**Installation:**
```bash
chmod +x monitoring/scripts/nba-monitor
export PATH="$PATH:$(pwd)/monitoring/scripts"
```

**Full documentation:** [../monitoring/scripts/README.md](../../monitoring/scripts/README.md)

### Other Tools

- **check-scrapers.py** - Simple status checker
- **workflow_monitoring.py** - Python library for custom monitoring
- See [../../monitoring/scripts/README.md](../../monitoring/scripts/README.md) for all tools

## Local Operational Docs

- **[monitoring-setup.md](monitoring-setup.md)** - How to set up monitoring tools

## Related

- **[../../shared/utils/README.md](../../shared/utils/README.md)** - Shared utilities documentation
- **[../../monitoring/scripts/README.md](../../monitoring/scripts/README.md)** - Monitoring tools documentation
EOF

# Decisions README
cat > "${DOCS_DIR}/decisions/README.md" << 'EOF'
# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records - documents that capture important architectural decisions along with their context and consequences.

## Format

ADRs use the format: `YYYY-MM-DD-NNN-title.md`

Example: `2025-07-10-001-cloud-run-choice.md`

## Template

When creating a new ADR, use [template.md](template.md).

## Index

| Date | Title | Status |
|------|-------|--------|
| TBD | TBD | TBD |

## Related

- See [../architecture/](../architecture/) for current architecture
- See [../reference/](../reference/) for historical implementation notes
EOF

# Decisions Template
cat > "${DOCS_DIR}/decisions/template.md" << 'EOF'
# ADR-NNN: [Title]

**Date:** YYYY-MM-DD  
**Status:** [Proposed | Accepted | Deprecated | Superseded by ADR-XXX]  
**Deciders:** [Names or roles]  
**Tags:** [e.g., architecture, scrapers, database]

## Context

What is the issue that we're seeing that is motivating this decision or change?

## Decision

What is the change that we're actually proposing or doing?

## Consequences

What becomes easier or more difficult to do because of this change?

### Positive
- ...

### Negative
- ...

### Neutral
- ...

## Alternatives Considered

What other options did we look at?

### Option 1: [Name]
- Pros: ...
- Cons: ...
- Reason not chosen: ...

### Option 2: [Name]
- Pros: ...
- Cons: ...
- Reason not chosen: ...

## References

- [Link to related discussions]
- [Link to related code]
- [Link to related documentation]
EOF

# Reference README
cat > "${DOCS_DIR}/reference/README.md" << 'EOF'
# Reference Documentation

Historical implementation notes and detailed specifications.

These documents use date prefixes (YYYY-MM-DD) to provide historical context and show evolution over time.

## Directories

- **backfill/** - Backfill strategies and implementations
- **scrapers/** - Scraper development history and decisions
- **processors/** - Processor implementations
- **workflows/** - Workflow configurations
- **schedule/** - Scheduling strategies
- **data_patterns/** - Data pattern documentation

## Usage

Reference docs help you understand:
- Why something was built a certain way
- How approaches evolved over time
- Historical context for current decisions
- Detailed implementation notes

For current/canonical documentation, see:
- [../architecture/](../architecture/) - Current architecture
- [../development/](../development/) - Current development practices
EOF

# Investigations README
cat > "${DOCS_DIR}/investigations/README.md" << 'EOF'
# Investigation Notes

Problem investigation and debugging notes.

Format: `YYYY-MM-DD-problem-description.md`

## When to Create an Investigation Doc

- Complex bug that takes > 1 hour to debug
- Recurring issues that need documented
- Performance problems
- Unexplained behavior

## Template

```markdown
# [Problem Description]

**Date:** YYYY-MM-DD  
**Status:** [Investigating | Resolved | Ongoing]  
**Affected Components:** [service names]

## Symptoms

What did we observe?

## Investigation

What did we check? What did we find?

## Root Cause

What was actually causing the problem?

## Resolution

How did we fix it?

## Prevention

How can we prevent this in the future?

## Related Issues

Links to similar problems or related docs
```
EOF

# Getting Started Guide
cat > "${DOCS_DIR}/development/getting-started.md" << 'EOF'
# Getting Started

Welcome to the NBA Props Platform! This guide will help you get set up and productive.

## Prerequisites

- Python 3.12+
- Docker
- gcloud CLI
- Access to GCP project: `nba-props-platform`

## Initial Setup

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd nba-stats-scraper
   ```

2. **Set up Python environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

3. **Configure GCP:**
   ```bash
   gcloud auth login
   gcloud config set project nba-props-platform
   gcloud auth application-default login
   ```

4. **Set up monitoring tools:**
   ```bash
   chmod +x monitoring/scripts/nba-monitor
   export PATH="$PATH:$(pwd)/monitoring/scripts"
   ```

5. **Test your setup:**
   ```bash
   nba-monitor status yesterday
   ```

## Project Structure

```
nba-stats-scraper/
├── scrapers/           # Scraping external APIs
├── data_processors/    # Processing data into BigQuery
├── workflows/          # Cloud Workflow definitions
├── monitoring/         # Monitoring tools and scripts
├── shared/             # Shared utilities
└── docs/              # Documentation (you are here!)
```

## Next Steps

1. Read [../architecture/system-overview.md](../architecture/system-overview.md)
2. Review [development-workflow.md](development-workflow.md)
3. Try [scraper-testing-guide.md](scraper-testing-guide.md)
4. Check out [../operations/README.md](../operations/README.md) for monitoring

## Getting Help

- Check [Wiki: Troubleshooting](https://your-wiki-url/troubleshooting)
- Review recent [../investigations/](../investigations/)
- Ask the team on Slack

**Last Updated:** $(date +%Y-%m-%d)
EOF

# System Overview
cat > "${DOCS_DIR}/architecture/system-overview.md" << 'EOF'
# System Architecture Overview

High-level overview of the NBA Props Platform architecture.

**Last Updated:** $(date +%Y-%m-%d)

## Overview

The NBA Props Platform is a data pipeline that:
1. Scrapes NBA data and betting odds from multiple sources
2. Processes and normalizes the data
3. Generates analytics and predictions
4. Serves data for prop bet recommendations

## Architecture Diagram

```
┌─────────────────┐
│ Cloud Scheduler │  ← Triggers workflows on schedule
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Workflows     │  ← Orchestrates scraping & processing
└────────┬────────┘
         │
         ├──────────────────────┬──────────────────────┐
         ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  nba-scrapers   │    │ nba-processors  │    │ nba-analytics-   │
│  (Cloud Run)    │    │  (Cloud Run)    │    │ processors       │
└────────┬────────┘    └────────┬────────┘    └────────┬─────────┘
         │                      │                       │
         ▼                      ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│   GCS Buckets   │───→│    BigQuery     │←───│   BigQuery       │
│   (Raw JSON)    │    │   (Processed)   │    │   (Analytics)    │
└─────────────────┘    └─────────────────┘    └──────────────────┘
```

## Components

### Cloud Scheduler
Triggers workflows on schedule (e.g., every 2 hours, daily at 8am)

### Workflows
Orchestrates multiple scrapers/processors in sequence

### Cloud Run Services
- **nba-scrapers**: Fetches data from external APIs
- **nba-processors**: Processes raw data into BigQuery
- **nba-analytics-processors**: Generates analytics

### Storage
- **GCS**: Raw JSON files from scrapers
- **BigQuery**: Structured data for querying

## Data Flow

1. **Scraping**: External API → nba-scrapers → GCS (raw JSON)
2. **Processing**: GCS (raw) → nba-processors → BigQuery (structured)
3. **Analytics**: BigQuery (raw) → nba-analytics-processors → BigQuery (analytics)

## Key Workflows

- **real-time-business**: Updates odds/props every 2 hours
- **morning-operations**: Daily setup and recovery
- **post-game-collection**: Collects game data after games

## Monitoring

Use `nba-monitor status yesterday` to check system health.

See [../operations/README.md](../operations/README.md) for monitoring tools.

## Related

- [system-architecture.md](system-architecture.md) - Detailed technical architecture
- [Wiki: Architecture](https://your-wiki-url/architecture) - User-friendly overview
EOF

# Deployment Guide
cat > "${DOCS_DIR}/development/deployment-guide.md" << 'EOF'
# Deployment Guide

How to deploy changes to the NBA Props Platform.

**Last Updated:** $(date +%Y-%m-%d)

## Quick Deploy

### Scrapers
```bash
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

### Processors
```bash
./bin/processors/deploy/deploy_processors_simple.sh
```

### Analytics
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

### Workflows
```bash
./bin/infrastructure/workflows/deploy_workflows.sh
```

## Deployment Process

1. **Test locally first**
2. **Deploy to Cloud Run**
3. **Verify deployment**
4. **Monitor for errors**

## Rollback

If something goes wrong:

```bash
# List revisions
gcloud run revisions list --service=nba-scrapers --region=us-west2

# Rollback to previous
gcloud run services update-traffic nba-scrapers \
  --region=us-west2 \
  --to-revisions=nba-scrapers-00057-xyz=100
```

## Best Practices

- Deploy during low-traffic times
- Test with small date ranges first
- Monitor logs after deployment
- Keep deployment scripts up to date

## Related

- [cloud-run-deployment.md](cloud-run-deployment.md) - Cloud Run specifics
- [development-workflow.md](development-workflow.md) - Full development process
EOF

# Monitoring Setup
cat > "${DOCS_DIR}/operations/monitoring-setup.md" << 'EOF'
# Monitoring Setup

How to set up monitoring tools for the NBA Props Platform.

**Last Updated:** $(date +%Y-%m-%d)

## Installation

```bash
# From repo root
chmod +x monitoring/scripts/nba-monitor
chmod +x monitoring/scripts/check-scrapers.py

# Add to PATH
export PATH="$PATH:$(pwd)/monitoring/scripts"

# Or create symlink
sudo ln -s $(pwd)/monitoring/scripts/nba-monitor /usr/local/bin/nba-monitor
```

## Usage

Daily status check:
```bash
nba-monitor status yesterday
```

View errors:
```bash
nba-monitor errors 24
```

View workflows:
```bash
nba-monitor workflows
```

## Daily Routine

Every morning at 9am:
```bash
# 1. Check yesterday's status
nba-monitor status yesterday

# 2. If errors, investigate
nba-monitor errors 24

# 3. Check specific workflow if needed
gcloud workflows executions list morning-operations --location=us-west2 --limit=3
```

## Full Documentation

See [../../monitoring/scripts/README.md](../../monitoring/scripts/README.md) for:
- All available commands
- Integration with existing systems
- Advanced usage

## Related

- [Wiki: Monitoring Guide](https://your-wiki-url/monitoring) - Complete monitoring procedures
- [Wiki: Troubleshooting](https://your-wiki-url/troubleshooting) - How to fix common issues
EOF

echo "✓ New documentation files created"
echo ""

# ==============================================================================
# STEP 5: Create index files for reference directories
# ==============================================================================
echo "📑 Creating index files for reference directories..."

# Backfill index
cat > "${DOCS_DIR}/reference/backfill/README.md" << 'EOF'
# Backfill Documentation

Historical documentation of backfill strategies and implementations.

Files are prefixed with dates (YYYY-MM-DD) to show evolution over time.

## Files

- Review the dated files in this directory to see how backfill approaches evolved
- Most recent files represent current/final strategies
- Older files provide historical context

## Related

- See [../../development/](../../development/) for current development practices
EOF

# Scrapers index
cat > "${DOCS_DIR}/reference/scrapers/README.md" << 'EOF'
# Scraper Documentation

Historical documentation of scraper development and decisions.

Files are prefixed with dates (YYYY-MM-DD) to show evolution over time.

## Files

- Review the dated files in this directory to see how scrapers evolved
- Check subdirectories for organized historical docs

## Related

- See [../../development/](../../development/) for current scraper development guide
EOF

# Processors index
cat > "${DOCS_DIR}/reference/processors/README.md" << 'EOF'
# Processor Documentation

Documentation of data processor implementations.

## Files

- Review files in this directory for processor implementation details

## Related

- See [../../architecture/](../../architecture/) for current architecture
EOF

echo "✓ Index files created"
echo ""

# ==============================================================================
# Summary
# ==============================================================================
echo ""
echo "✅ Migration complete!"
echo ""
echo "Summary:"
echo "--------"
echo "✓ Backup created at: ${BACKUP_DIR}"
echo "✓ Files renamed to use full year (2025-XX-XX)"
echo "✓ New directory structure created"
echo "✓ Files reorganized into proper locations"
echo "✓ New documentation files created"
echo ""
echo "Next steps:"
echo "-----------"
echo "1. Review the new structure: ls -la ${DOCS_DIR}"
echo "2. Update the following placeholder files with content from Claude artifacts:"
echo "   - (See files marked as PLACEHOLDER)"
echo ""
echo "3. Update wiki URL placeholders:"
echo "   - Find: 'https://your-wiki-url'"
echo "   - Replace with your actual wiki URL"
echo ""
echo "4. Test monitoring tools:"
echo "   cd $(pwd)"
echo "   nba-monitor status yesterday"
echo ""
echo "5. Create wiki pages with content from Claude artifacts:"
echo "   - WORKFLOW_MONITORING.md"
echo "   - TROUBLESHOOTING.md"
echo "   - ARCHITECTURE.md"
echo ""
echo "If you need to restore the backup:"
echo "  rm -rf ${DOCS_DIR}"
echo "  mv ${BACKUP_DIR} ${DOCS_DIR}"
echo ""
