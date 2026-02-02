# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records documenting key technical and architectural decisions made for the NBA Stats Scraper project.

## What is an ADR?

An Architecture Decision Record captures an important architectural decision made along with its context and consequences. ADRs help us:
- Understand why decisions were made
- Avoid repeating past mistakes
- Onboard new team members
- Review and reverse decisions when needed

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [001](./001-unified-health-monitoring.md) | Unified Health Monitoring System | Accepted | 2026-02-02 |
| [002](./002-deployment-runbooks.md) | Service-Specific Deployment Runbooks | Accepted | 2026-02-02 |
| [003](./003-integration-testing-strategy.md) | Integration Testing for Critical Paths | Accepted | 2026-02-02 |

## ADR Template

```markdown
# ADR XXX: [Title]

**Status**: [Proposed | Accepted | Deprecated | Superseded]
**Date**: YYYY-MM-DD
**Decision Makers**: [Who was involved]
**Tags**: [Relevant tags]

## Context
[What is the issue we're seeing that is motivating this decision?]

## Decision
[What is the change that we're proposing/doing?]

## Rationale
[Why this approach? What alternatives were considered?]

## Consequences
[What becomes easier or more difficult because of this change?]

## Implementation
[How was this implemented? Key files, commands, etc.]

## References
[Links to related docs, tickets, sessions]
```

## Status Definitions

- **Proposed**: Decision is being discussed
- **Accepted**: Decision has been made and implemented
- **Deprecated**: No longer recommended but may still be in use
- **Superseded**: Replaced by a newer decision (link to new ADR)

## How to Add an ADR

1. Copy the template above
2. Number sequentially (e.g., 004-new-decision.md)
3. Fill in all sections
4. Update this index
5. Create PR for review

## Tags

Common tags for filtering:
- `monitoring` - System monitoring and observability
- `deployment` - Deployment and release processes
- `testing` - Testing strategies and frameworks
- `data-quality` - Data quality and validation
- `performance` - Performance optimization
- `security` - Security considerations
- `prevention` - Error prevention systems

## Related Documentation

- [System Architecture](../README.md)
- [Deployment Runbooks](../../02-operations/runbooks/)
- [Prevention & Monitoring Strategy](../../08-projects/current/prevention-and-monitoring/)
