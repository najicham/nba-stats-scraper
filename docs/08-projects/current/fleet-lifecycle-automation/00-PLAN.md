# Fleet Lifecycle Automation Plan

**Session 387 — March 2, 2026**

## Problem Statement

Every few sessions we manually clean up the same recurring issues:
- Dead/zombie models accumulating (Session 378c, 383b, 386, 387)
- Signals silently broken for weeks (`line_rising_over` 96.6% HR dead, `fast_pace_over` never fired)
- Scheduler jobs failing unnoticed (`nba-env-var-check-prod` every 5 min for unknown duration)
- Champion degrades but no automated promotion path
- Inconsistent data (negative edges, schema mismatches)

The infrastructure to **detect** problems exists (decay detection, signal health, model profiles). What's missing is the **automated response** layer.

## Current State: Detection Without Action

| Layer | Detection | Automated Action |
|-------|-----------|-----------------|
| Model decay | decay-detection CF (daily 11 AM) | Slack alert only |
| Model BLOCKED state | model_performance_daily table | Nothing — manual deactivation |
| Signal health regime | signal_health_daily table | Nothing — informational only |
| Signal firing validation | Not implemented | N/A |
| Scheduler health | daily-health-check CF (counts >3 failing) | Slack alert only |
| Registry consistency | validate_model_registry.py (manual) | Manual SQL suggestions |

## Proposed Automation: Three Tiers

### Tier 1: Auto-Disable BLOCKED Models (HIGH PRIORITY)

**Problem:** Models in BLOCKED state (7d HR < 52.4%) continue generating predictions that compete in best bets selection.

**Implementation:** Extend `decay_detection` Cloud Function:
1. When a model transitions to BLOCKED state, call the `deactivate_model.py` cascade logic:
   - Set `enabled=FALSE, status='blocked'` in model_registry
   - Deactivate that day's predictions (`is_active=FALSE`)
   - Remove from signal_best_bets_picks
2. Log audit trail + Slack notification of auto-disable
3. Add `auto_disabled_at` timestamp to model_registry for tracking

**Safeguards:**
- Never auto-disable the production champion (require manual intervention)
- Only auto-disable shadow models with N >= 15 graded picks (avoid premature kills)
- Add `--no-auto-disable` flag to model_registry for manual override

**Estimated effort:** Small — reuse existing `deactivate_model.py` logic, add to decay_detection CF.

### Tier 2: Signal Firing Canary (MEDIUM PRIORITY)

**Problem:** Signals break silently (code bugs, schema mismatches, dead dependencies). We discovered 2 signals with 80%+ backtest HR that were completely dead.

**Implementation:** New daily check in `signal_health.py` or separate canary:
1. For each active signal, count picks in last 7 days with that tag
2. Compare to historical firing rate (% of predictions that qualify)
3. Alert if:
   - Signal fires 0 times in 7 days AND fired > 0 in prior 30 days → **DEAD SIGNAL**
   - Signal firing rate drops >50% from 30d average → **DEGRADING SIGNAL**
4. Include in daily-health-check Slack summary

**This would have caught:**
- `line_rising_over` immediately when champion died (dropped to 0 fires)
- `fast_pace_over` on Day 1 (never fired, 0 vs expected ~5% of OVER predictions)

**Estimated effort:** Small — add a BQ query to signal_health.py.

### Tier 3: Registry Hygiene Automation (LOW PRIORITY)

**Problem:** Disabled models accumulate with inconsistent `enabled`/`status` states (30+ disabled models found this session).

**Implementation:** Weekly Cloud Scheduler job:
1. Find all `enabled=FALSE` models with `status NOT IN ('blocked', 'deprecated')`
2. Auto-set status to 'blocked' for consistency
3. Find models with 0 predictions in last 30 days AND enabled=TRUE → alert as zombie
4. Archive models >90 days old with status='blocked' → set status='archived'

**Estimated effort:** Small — simple BQ UPDATE queries on a schedule.

## Implementation Order

```
Phase 1 (This session or next):
  ✅ Fixed deactivate_model.py bug (updated_at)
  ✅ Fixed fast_pace_over threshold (0-1 scale)
  ✅ Fixed line_rising_over (removed dead champion dependency)
  ✅ Fixed edge storage consistency (abs values)
  ✅ Cleaned fleet (disabled 4 models)
  [ ] Commit and deploy signal fixes

Phase 2 (Next 1-2 sessions):
  [ ] Add signal firing canary to signal_health.py
  [ ] Add auto-disable to decay_detection CF

Phase 3 (When convenient):
  [ ] Registry hygiene automation
  [ ] Scheduler health monitoring improvements
```

## Key Design Principles

1. **Detect AND respond** — Every alert should either auto-fix or provide a one-click fix
2. **Never auto-disable champion** — Human-in-the-loop for production model changes
3. **Canaries catch silent failures** — Monitor that things ARE firing, not just their HR
4. **Consistency enforced at write time** — abs(edge), validated status transitions
5. **Weekly hygiene beats quarterly cleanups** — Small automated checks prevent debt accumulation
