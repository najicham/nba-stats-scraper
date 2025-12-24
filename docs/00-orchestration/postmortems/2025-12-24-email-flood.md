# Postmortem: Email Flood Incident

**Date:** December 24, 2025
**Duration:** ~18 hours (Dec 23 7 PM → Dec 24 9 AM ET)
**Impact:** 600+ error emails, schedule data stale
**Severity:** Medium (user impact, no data loss)

## Summary

A method signature bug in NbacScheduleProcessor caused every schedule processing attempt to fail, generating an error email for each failure. With no rate limiting, 600+ emails accumulated overnight.

## Timeline (all times ET)

| Time | Event |
|------|-------|
| Dec 23 ~7 PM | First schedule processor failures begin |
| Dec 23 ~7 PM | Error emails start arriving (1 per failure) |
| Dec 24 ~8 AM | User notices 600+ emails in inbox |
| Dec 24 ~9 AM | Root cause identified (method signature mismatch) |
| Dec 24 ~9:06 AM | Fix deployed to Phase 2 |
| Dec 24 ~9:30 AM | Schedule data verified fresh |
| Dec 24 ~10:50 AM | Rate limiting feature deployed |

## Root Cause

### The Bug

```python
# ProcessorBase.run() calls:
self.transform_data()  # NO arguments

# NbacScheduleProcessor expected:
def transform_data(self, raw_data: dict, file_path: str) -> list:  # 2 arguments
```

Result: `TypeError: transform_data() missing 2 required positional arguments`

### Why It Happened

Session 162 (Dec 23) modified the schedule processor to add timezone fixes. The `transform_data()` method was changed to take arguments, but this broke the ProcessorBase contract which calls it with no arguments.

### Why It Wasn't Caught

1. **Two code paths:** `process_file()` (backfills) passed arguments directly and worked. `run()` (Pub/Sub automation) relies on ProcessorBase and broke.
2. **No integration test:** Only `process_file()` was tested, not `run()`.
3. **No contract validation:** No check that processors match base class signature.

## Impact

### User Impact
- 600+ error emails flooded inbox
- Notification fatigue (important alerts lost in noise)

### System Impact
- Schedule data stale for ~18 hours
- No data loss (scrapers still wrote to GCS)
- Phase 2 couldn't process (failures retried repeatedly)

## Resolution

### Immediate Fix
Fixed `transform_data()` to follow ProcessorBase contract:
```python
def transform_data(self) -> None:
    raw_data = self.raw_data
    file_path = self.opts.get('file_path', '')
    # ... rest of transform logic
```

### Prevention Fix
Added notification rate limiting:
- Max 5 emails/hour per unique error signature
- Aggregation after 3 occurrences
- 60-minute cooldown before reset

## Lessons Learned

### What Went Well
- Root cause was identified quickly once investigated
- Fix was straightforward once understood
- Rate limiting feature was implemented same day

### What Went Wrong
- No automated detection of the issue
- Only knew about problem from inbox flood
- Two code paths not both tested

## Action Items

### Completed
- [x] Fix schedule processor method signature
- [x] Add notification rate limiting
- [x] Document rate limiting configuration
- [x] Create orchestration documentation

### TODO
- [ ] Add integration test for processor.run() path
- [ ] Add contract validation (verify method signatures)
- [ ] Add deployment version tracking (commit SHA)
- [ ] Create monitoring dashboard
- [ ] Add pre-deploy smoke tests

## Metrics

| Metric | Value |
|--------|-------|
| Time to detection | ~13 hours |
| Time to fix (from detection) | ~1 hour |
| Total emails sent | ~600 |
| Data staleness | ~18 hours |
| Services affected | Phase 2 (schedule processing) |

## Prevention

For future similar incidents:
1. **Rate limiting** now prevents email floods
2. **Integration tests** should cover both code paths
3. **Contract validation** should verify method signatures
4. **Monitoring dashboard** would show error spikes earlier
