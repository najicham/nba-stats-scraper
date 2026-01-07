# Lessons Learned Index

Cross-project retrospectives and organizational learning. This directory synthesizes insights from multiple projects, major incidents, and architectural discoveries.

## 2026

- [Data Quality Journey - January 2026](./DATA-QUALITY-JOURNEY-JAN-2026.md)
  - Discovery of data completeness requirements
  - Impact of data quality on ML training
  - Validation framework implementation

## 2025

- [Phase 5 Deployment - November 2025](./PHASE5-DEPLOYMENT-LESSONS-2025-11.md)
  - Lessons from Phase 5 deployment and integration

## Purpose

This directory captures organizational learning from:
- Major projects and migrations
- Data quality incidents
- Architecture decisions
- Process improvements
- Recurring problems and their solutions

## How This Differs from Postmortems

| Postmortems | Lessons Learned |
|-------------|-----------------|
| Single incident | Cross-project synthesis |
| What happened when | Why it keeps happening |
| Timeline-focused | Pattern-focused |
| Immediate resolution | Long-term prevention |

**Example**:
- **Postmortem**: "GameBook incident on Dec 28" (single event)
- **Lesson Learned**: "Data Quality Journey Jan 2026" (synthesizes multiple events)

## When to Create a Lesson Learned Document

Create a lessons learned document when:
- ✅ Pattern emerges across multiple projects
- ✅ Significant architectural insight discovered
- ✅ Major project completes with valuable learnings
- ✅ Repeated issues need organizational awareness
- ✅ Process improvement that applies broadly

**Don't create for**:
- ❌ Single incidents (use postmortems)
- ❌ Project-specific findings (keep in project docs)
- ❌ Temporary workarounds

## Document Structure

Each lessons learned document should include:

```markdown
# Lesson Learned: [Topic]

**Date**: YYYY-MM
**Context**: Brief description of what prompted this

## Summary
One-paragraph overview of what we learned

## Background
How we got here, what led to this learning

## What We Learned

### Lesson 1: [Title]
- **Context**: When this applies
- **What Happened**: Specific examples
- **Root Cause**: Why this is important
- **Prevention**: How to avoid in future

### Lesson 2: [Title]
...

## Impact
How this changes our approach

## Recommendations
Concrete actions based on these learnings

## References
- [Related project](../08-projects/completed/...)
- [Updated procedure](../02-operations/...)
- [Related postmortem](../02-operations/postmortems/...)
```

## Maintenance

When completing a major project:
1. Review for significant cross-cutting insights
2. Check if lesson learned document warranted
3. If yes, create document here
4. Update this index
5. Link from project README

## Related Documentation

- [Postmortems](../02-operations/postmortems/) - Single incidents
- [Completed Projects](../08-projects/completed/) - Historical execution details
- [Architecture Decisions](../01-architecture/decisions/) - ADRs

---

**Last Updated**: January 6, 2026
