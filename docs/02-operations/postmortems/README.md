# Incident Postmortems

Chronological index of postmortems for major incidents and outages.

## 2025

- [GameBook Incident - December 2025](./2025/gamebook-incident-postmortem.md)
- [Daily Orchestration Failure - December 2025](./2025/daily-orchestration-postmortem.md)

## What is a Postmortem?

A postmortem is a blameless analysis of a significant incident that includes:
- **Timeline**: What happened and when
- **Root Cause**: Why it happened
- **Impact**: What was affected
- **Resolution**: How it was fixed
- **Prevention**: How to prevent recurrence

## When to Create a Postmortem

Create a postmortem when:
- ✅ Service outage > 30 minutes
- ✅ Data loss or corruption
- ✅ Security incident
- ✅ Performance degradation affecting users
- ✅ Repeated failures of same component

**Don't create for**:
- ❌ Minor bugs (document in troubleshooting guide)
- ❌ Expected maintenance
- ❌ Single failed deployment (document fix, not full postmortem)

## Process

1. **Create file**: `{year}/{descriptive-name}-postmortem.md`
2. **Use template**: See `docs/05-development/templates/postmortem-template.md` (if exists, or create)
3. **Update this index**: Add link above
4. **Share findings**: Update relevant troubleshooting guides with learnings

## Template Structure

```markdown
# [Incident Name] Postmortem

**Date**: YYYY-MM-DD
**Duration**: X hours
**Severity**: Critical/High/Medium
**Impact**: Brief description

## Summary
One-paragraph executive summary

## Timeline
- HH:MM - Event 1
- HH:MM - Event 2
- HH:MM - Resolution

## Root Cause
Why this happened

## Impact
- System A: Effect
- System B: Effect
- Users: Effect

## Resolution
How we fixed it

## Prevention
How we'll prevent recurrence

## Action Items
- [ ] Task 1
- [ ] Task 2

## Related Documentation
- [Troubleshooting guide updated](link)
- [Related incident](link)
```

## Related Documentation

- [Troubleshooting Matrix](../troubleshooting-matrix.md)
- [Lessons Learned](../../lessons-learned/README.md)
- [Daily Operations](../README.md)

---

**Last Updated**: January 6, 2026
