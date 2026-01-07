# Daily Orchestration Post-Mortem - December 29, 2025

**Incident Date:** December 29, 2025
**Detection Time:** ~1:45 PM ET (manual discovery during morning checklist)
**Resolution Time:** ~2:25 PM ET
**Total Impact Duration:** ~4 hours (predictions were due by 1:30 PM ET)
**Severity:** Medium (predictions delayed but generated before games started)

---

## Executive Summary

Today's prediction pipeline failed to generate predictions by the scheduled time (1:30 PM ET) due to two cascading issues:

1. **Design Issue:** The `same-day-phase3` scheduler only triggers 1 of 5 Phase 3 processors, but the Phase 3→4 orchestrator waits for all 5 before triggering Phase 4.

2. **Deployment Issue:** The Phase 4 precompute service was running the wrong code (analytics instead of precompute), causing `/process-date` endpoint to return 404.

After manual intervention, predictions were generated successfully (~1,700+ predictions for 11 games tonight).

---

## Timeline

| Time (ET) | Event |
|-----------|-------|
| 12:30 PM | `same-day-phase3` scheduler runs - triggers only `UpcomingPlayerGameContextProcessor` |
| 12:30 PM | Phase 3→4 orchestrator sees 1/5 processors complete, waits for remaining 4 |
| 1:00 PM | `same-day-phase4` scheduler runs - calls `/process-date` endpoint |
| 1:00 PM | Phase 4 returns 404 (wrong code deployed) |
| 1:30 PM | `same-day-predictions` scheduler runs - no Phase 4 data, predictions blocked |
| ~1:45 PM | Issue discovered during manual morning checklist review |
| ~1:55 PM | Root cause identified: Phase 3 only 1/5 complete, Phase 4 service misconfigured |
| ~2:10 PM | Phase 4 service redeployed with correct precompute code |
| ~2:18 PM | ML Feature Store manually triggered, generates 352 records |
| ~2:19 PM | Prediction coordinator triggered, starts generating predictions |
| ~2:25 PM | Predictions verified generating (1,700+ for 11 games) |

---

## Root Cause Analysis

### Issue 1: Phase 3 Orchestrator Design Mismatch

**What:** The `same-day-phase3` scheduler is configured to trigger only ONE processor:
```json
{
  "processors": ["UpcomingPlayerGameContextProcessor"],
  "backfill_mode": true
}
```

However, the Phase 3→4 orchestrator (`phase3-to-phase4-orchestrator`) waits for ALL 5 Phase 3 processors:
```python
EXPECTED_PROCESSORS = [
    'player_game_summary',
    'team_defense_game_summary',
    'team_offense_game_summary',
    'upcoming_player_game_context',
    'upcoming_team_game_context',
]
```

**Why:** The orchestrator was designed for overnight processing where all 5 processors run. Same-day processing only needs `upcoming_player_game_context` (for forecasting future games).

**Impact:** Orchestrator stuck at 1/5 completion, never triggered Phase 4.

### Issue 2: Phase 4 Service Running Wrong Code

**What:** The Phase 4 precompute service (`nba-phase4-precompute-processors`) was returning 404 for `/process-date` and showing analytics code in logs:
```
INFO:data_processors.analytics.main_analytics_service:No analytics processors configured...
```

**Why:** The service was deployed with the wrong container or entrypoint, running `main_analytics_service` instead of `main_precompute_service`.

**Impact:** Even though `same-day-phase4` scheduler ran correctly, the endpoint didn't exist.

### Issue 3: ESPN Roster Storage Import (Minor)

**What:** The ESPN roster processor was failing with `NameError: name 'storage' is not defined`.

**Why:** A previous session added ESPN folder handling code but forgot to import the `google.cloud.storage` module.

**Impact:** ESPN roster processing errors (not directly blocking predictions).

---

## What Went Well

1. **Morning checklist caught the issue** - We had a documented checklist that prompted investigation
2. **Root cause was identifiable** - Firestore state (`phase3_completion`) clearly showed 1/5 complete
3. **Quick resolution once identified** - Manual triggers worked correctly
4. **Predictions generated successfully** - 1,700+ predictions for all 11 games

---

## What Needs Improvement

### Immediate Fixes Needed

| Fix | Priority | Effort | Owner |
|-----|----------|--------|-------|
| **Same-day schedulers should bypass orchestrator** | P0 | 2h | - |
| Update `same-day-phase4` to call `/process-date` directly | | | |
| Remove dependency on Phase 3 completion tracking for same-day | | | |

### Medium-Term Improvements

| Improvement | Priority | Effort | Details |
|-------------|----------|--------|---------|
| **Self-heal should check TODAY's predictions** | P1 | 4h | Currently only checks tomorrow |
| **Add alerting for Phase stuck states** | P1 | 4h | Alert if Phase 3 1/5 for >30 min |
| **Phase 3→4 timeout-based fallback** | P2 | 6h | Trigger Phase 4 after N minutes if 3/5 complete |
| **Daily validation scheduler at 2 PM ET** | P2 | 4h | Auto-check predictions before games |

### Long-Term Improvements

| Improvement | Priority | Effort | Details |
|-------------|----------|--------|---------|
| **Unified processor execution log** | P2 | 8h | Track all Phase 2-5 runs in BigQuery |
| **Dashboard for pipeline status** | P3 | 6h | Single view of all phases |
| **Circuit breaker pattern** | P3 | 8h | Prevent cascade failures |

---

## Architecture Understanding

### Same-Day Processing Flow (INTENDED)

```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│ same-day-phase3│────▶│  Phase 3       │────▶│ Upcoming       │
│   (12:30 PM)   │     │  Analytics     │     │ Player Context │
└────────────────┘     └────────────────┘     └────────┬───────┘
                                                       │
                                                       │ (SHOULD trigger directly)
                                                       ▼
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│ same-day-phase4│────▶│  Phase 4       │────▶│ ML Feature     │
│   (1:00 PM)    │     │  Precompute    │     │ Store          │
└────────────────┘     └────────────────┘     └────────┬───────┘
                                                       │
                                                       ▼
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│ same-day-pred  │────▶│  Prediction    │────▶│ Predictions    │
│   (1:30 PM)    │     │  Coordinator   │     │ (~1700/day)    │
└────────────────┘     └────────────────┘     └────────────────┘
```

### What Actually Happened

```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│ same-day-phase3│────▶│  Phase 3       │────▶│ Upcoming       │
│   (12:30 PM)   │     │  Analytics     │     │ Player Context │
└────────────────┘     └────────────────┘     └────────┬───────┘
                                                       │
                                                       ▼
                                               ┌─────────────────┐
                                               │ Phase 3→4       │
                                               │ Orchestrator    │◀──── STUCK
                                               │ (1/5 complete)  │
                                               └─────────────────┘
                                                       ✗
                                              (Never triggers Phase 4)

┌────────────────┐     ┌────────────────┐
│ same-day-phase4│────▶│  Phase 4       │────▶ 404 ERROR
│   (1:00 PM)    │     │  (Wrong code!) │     (analytics code)
└────────────────┘     └────────────────┘
```

---

## Action Items

### Today (P0)

- [x] Fixed ESPN roster storage import (`bd7fe6e`)
- [x] Redeployed Phase 4 precompute service with correct code
- [x] Manually triggered ML Feature Store and predictions
- [x] Verified predictions generated for all 11 games

### This Week (P1)

- [ ] Review and update `same-day-phase4` scheduler to be independent of orchestrator
- [ ] Update self-heal function to also check TODAY's predictions
- [ ] Add monitoring alert for Phase 3 completion state
- [ ] Update morning checklist with these new failure modes

### Next Sprint (P2)

- [ ] Implement Phase 3→4 timeout-based fallback
- [ ] Create unified processor execution log
- [ ] Build pipeline status dashboard

---

## Related Documents

- `docs/02-operations/daily-validation-checklist.md` - Morning checklist
- `docs/08-projects/current/ORCHESTRATION-IMPROVEMENTS.md` - Improvement plan
- `docs/08-projects/current/2025-12-29-PIPELINE-ANALYSIS.md` - Agent analysis
- `docs/01-architecture/orchestration/orchestrators.md` - Orchestrator architecture
- `docs/08-projects/current/self-healing-pipeline/README.md` - Self-healing system

---

## Commits from This Session

```
bd7fe6e fix: Add missing storage import for ESPN roster folder handling
```

---

*Post-mortem created: December 29, 2025*
*Next review: January 2, 2026*
