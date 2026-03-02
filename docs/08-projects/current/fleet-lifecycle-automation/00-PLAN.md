# Fleet Lifecycle & System Health Automation Plan

**Session 387 — March 2, 2026**
**Status:** Phase 1 complete, Phase 2-5 planned

---

## Problem Statement

Every few sessions we manually clean up the same recurring issues:
- Dead/zombie models accumulating (Session 378c, 383b, 386, 387)
- Signals silently broken for weeks (`line_rising_over` 96.6% HR dead, `fast_pace_over` never fired)
- Scheduler jobs failing unnoticed (`nba-env-var-check-prod` every 5 min for unknown duration)
- Champion degrades but no automated promotion path
- Inconsistent data (negative edges, schema mismatches)
- Manual fleet triage consuming entire sessions

The infrastructure to **detect** problems exists (decay detection, signal health, model profiles). What's missing is the **automated response** layer and **proactive monitoring** to catch silent failures.

---

## Current State: Detection Without Action

| Layer | Detection | Automated Action | Gap |
|-------|-----------|-----------------|-----|
| Model decay | decay-detection CF (daily 11 AM) | Slack alert only | No auto-disable |
| Model BLOCKED state | model_performance_daily | Nothing | Manual deactivation |
| Signal health regime | signal_health_daily | Nothing | Informational only |
| Signal firing validation | **Not implemented** | N/A | Silent deaths undetected |
| Scheduler health | daily-health-check CF | Slack alert only | No auto-pause |
| Registry consistency | validate_model_registry.py | Manual SQL suggestions | No enforcement |
| Data consistency | Not implemented | N/A | Signed edge, schema drift |
| Champion promotion | Not implemented | N/A | Manual evaluation |

---

## Phase 1: Foundation Fixes (COMPLETE — Session 387)

✅ Fixed `deactivate_model.py` bug (`updated_at` column doesn't exist)
✅ Fixed `fast_pace_over` threshold (102 on 0-1 normalized scale → 0.75)
✅ Fixed `line_rising_over` (removed dead champion model dependency from `prev_prop_lines` CTE)
✅ Fixed `model_health` listing in `ACTIVE_SIGNALS` (excluded from pick_signal_tags by design)
✅ Fixed edge storage consistency (`abs(edge)` in BQ and JSON)
✅ Cleaned fleet (disabled 4 models with inconsistent states)
✅ Paused noisy `nba-env-var-check-prod` scheduler job
✅ Deployed grading service, prediction-coordinator, phase6 exporters

---

## Phase 2: Signal Firing Canary (NEXT SESSION — HIGH PRIORITY)

### Problem
Signals can die silently when external dependencies change. Session 387 discovered 2 signals with 80%+ backtest HR that were completely dead for weeks with zero detection.

### Implementation

**Where:** Add to `ml/signals/signal_health.py` (runs post-grading daily)

**Logic:**
```python
def check_signal_firing(bq_client, target_date):
    """Detect signals that stopped firing."""
    query = """
    WITH recent_firing AS (
        SELECT signal_tag,
               COUNTIF(game_date >= DATE_SUB(@date, INTERVAL 7 DAY)) as fires_7d,
               COUNTIF(game_date >= DATE_SUB(@date, INTERVAL 30 DAY)) as fires_30d,
               COUNTIF(game_date >= DATE_SUB(@date, INTERVAL 30 DAY)
                   AND game_date < DATE_SUB(@date, INTERVAL 7 DAY)) as fires_prior_23d
        FROM pick_signal_tags
        WHERE game_date >= DATE_SUB(@date, INTERVAL 30 DAY)
        GROUP BY 1
    )
    SELECT signal_tag,
           fires_7d, fires_30d, fires_prior_23d,
           CASE
               WHEN fires_7d = 0 AND fires_prior_23d > 0 THEN 'DEAD'
               WHEN fires_7d > 0 AND fires_7d < fires_prior_23d * 0.3 THEN 'DEGRADING'
               ELSE 'HEALTHY'
           END as firing_status
    FROM recent_firing
    """
    # Alert on DEAD or DEGRADING signals
```

**Alert output:** Include in `daily-health-check` Slack summary:
```
⚠️ Signal Firing Canary:
  DEAD: line_rising_over (0 fires in 7d, was 23 in prior 23d)
  DEGRADING: fast_pace_over (2 fires in 7d, was 18 in prior 23d)
```

**Would have caught:**
- `line_rising_over` within 7 days of champion death
- `fast_pace_over` on first weekly check (0 fires ever)

**Effort:** ~2 hours. One BQ query + Slack formatting.

### Checklist
- [ ] Add `check_signal_firing()` to `signal_health.py`
- [ ] Include active signals from `ACTIVE_SIGNALS` set
- [ ] Post to `#nba-alerts` on DEAD/DEGRADING
- [ ] Add to `daily-health-check` CF summary
- [ ] Test with historical data (simulate dead signal)

---

## Phase 3: Auto-Disable BLOCKED Models (NEXT 1-2 SESSIONS)

### Problem
Models in BLOCKED state (7d HR < 52.4%) continue generating predictions that waste compute and can contaminate best bets if the filter stack has gaps.

### Implementation

**Where:** Extend `decay_detection` Cloud Function

**Logic:**
When a model transitions to BLOCKED:
1. Check safeguards:
   - Is this the production champion? → SKIP (alert human)
   - Does model have `auto_disable_exempt = TRUE`? → SKIP
   - Does model have N >= 15 graded picks in 14d? → PROCEED (avoids premature kill)
2. Execute deactivation cascade (reuse `deactivate_model.py` logic):
   - `enabled=FALSE, status='blocked'` in model_registry
   - `is_active=FALSE` for today's predictions
   - Remove from `signal_best_bets_picks`
3. Post Slack notification with full context

**Schema change:**
```sql
ALTER TABLE nba_predictions.model_registry
ADD COLUMN auto_disabled_at TIMESTAMP,
ADD COLUMN auto_disable_exempt BOOL DEFAULT FALSE;
```

**Safeguards:**
- Never auto-disable the production champion
- `auto_disable_exempt` flag for manual override
- Minimum N >= 15 before acting (prevents killing new models)
- Recovery: if model recovers to HEALTHY for 3d, auto-re-enable (set `enabled=TRUE, auto_disabled_at=NULL`)

### Checklist
- [ ] Add `auto_disabled_at` and `auto_disable_exempt` columns to model_registry
- [ ] Extract deactivation logic from `bin/deactivate_model.py` into shared function
- [ ] Add auto-disable to `decay_detection` CF on BLOCKED transition
- [ ] Add auto-re-enable on sustained HEALTHY recovery
- [ ] Add Slack notifications for both actions
- [ ] Test with dry-run flag first

---

## Phase 4: Registry Hygiene & Data Consistency (WHEN CONVENIENT)

### 4A: Registry Hygiene Automation

**Where:** New Cloud Scheduler job (weekly, Monday 10 AM ET)

**Logic:**
1. Find `enabled=FALSE` models with `status NOT IN ('blocked', 'deprecated', 'archived')` → auto-set status to 'blocked'
2. Find `enabled=TRUE` models with 0 predictions in last 30 days → alert as zombie
3. Find `enabled=FALSE, status='blocked'` models > 90 days old → set status='archived'
4. Post summary to Slack

### 4B: Data Consistency Enforcement

**Where:** Pre-write validation in signal exporters

**Rules:**
- Edge must be non-negative (enforce `abs()` at write time)
- `system_id` must be populated (no NULL model sources)
- `signal_count` must match length of `signal_tags` array
- `game_date` must be a valid date (not future, not > 7 days past)

### Checklist
- [ ] Create `bin/monitoring/registry_hygiene.py`
- [ ] Create Cloud Scheduler job for weekly execution
- [ ] Add data consistency checks to signal_best_bets_exporter.py
- [ ] Test with dry-run

---

## Phase 5: Champion Promotion Pipeline (FUTURE)

### Problem
When the champion is BLOCKED, there's no automated path to evaluate and promote the best-performing shadow model. Currently requires:
1. Manual query of model_performance_daily
2. Human evaluation of HR, N, direction split, edge bands
3. Manual registry update
4. Manual deploy verification

### Design (Not Yet Designed in Detail)

**Trigger:** Champion enters BLOCKED state for > 3 consecutive days

**Evaluation criteria (all must pass):**
1. Shadow model HR >= 55% on N >= 25 edge 3+ picks (14d window)
2. OVER and UNDER both above breakeven (52.4%)
3. Model age < 30 days since training end date
4. No active governance gate failures

**Output:** Slack notification with candidate ranking + one-click approval

**NOT auto-promoting** — human approval required. But the evaluation and recommendation is automated.

### Checklist
- [ ] Design evaluation criteria in detail
- [ ] Build candidate ranking query
- [ ] Add to decay_detection CF
- [ ] Create Slack interactive approval workflow (or CLI command)

---

## Ongoing: Monitoring Improvements

### Scheduler Health (Quick Win)
The `daily-health-check` CF already counts failing scheduler jobs and alerts on > 3. Improvement:
- Alert on ANY job failing for > 24 hours (currently only counts, doesn't track duration)
- Auto-pause jobs failing for > 72 hours with endpoint errors (like `nba-env-var-check-prod`)

### Signal Health Alerts (With Firing Canary)
Current signal health is informational. With the firing canary (Phase 2), add:
- Weekly signal health summary in `#nba-alerts`
- Flag signals with 14d HR below breakeven (52.4%) on N >= 30

### Deployment Trigger Coverage
Known gap: `prediction-coordinator` Cloud Build trigger only watches `predictions/coordinator/**`, NOT `ml/signals/`. Signal changes require manual deploy.

Options:
1. Expand trigger path to include `ml/signals/` and `data_processors/publishing/`
2. Add `ml/signals/` as a watched path in `cloudbuild-coordinator.yaml`
3. Accept manual deploy (current state) but document clearly

---

## Key Design Principles

1. **Detect AND respond** — Every alert should either auto-fix or provide a one-click fix
2. **Never auto-disable/promote champion** — Human-in-the-loop for production model changes
3. **Canaries catch silent failures** — Monitor that things ARE firing, not just their HR
4. **Consistency enforced at write time** — abs(edge), validated status transitions, non-null model sources
5. **Weekly hygiene beats quarterly cleanups** — Small automated checks prevent debt accumulation
6. **Graceful degradation** — Auto-disable failures should not cascade; always alert on auto-action failures
7. **Dry-run everything first** — All automation must support `--dry-run` mode before going live

---

## Priority Matrix

| Phase | Impact | Effort | Dependencies | Target |
|-------|--------|--------|-------------|--------|
| Phase 1 | HIGH | Done | None | ✅ Session 387 |
| Phase 2 (Signal canary) | HIGH | Small (2h) | None | Next session |
| Phase 3 (Auto-disable) | HIGH | Medium (4h) | Phase 1 | Next 1-2 sessions |
| Phase 4A (Registry hygiene) | LOW | Small (2h) | None | When convenient |
| Phase 4B (Data consistency) | LOW | Small (1h) | None | When convenient |
| Phase 5 (Champion promotion) | MEDIUM | Large (8h) | Phase 3 | Future |

---

## Historical Context: Why This Matters

| Session | Issue | Time Spent | Would Automation Have Helped? |
|---------|-------|-----------|------------------------------|
| 378c | XGBoost poisoned best bets | ~4h | Phase 3 would have auto-disabled |
| 383b | 1,275 zombie predictions | ~2h | Phase 3 would have prevented accumulation |
| 386 | Dead models in best bets, prevention system | ~6h | Phase 3+4 would have caught earlier |
| 387 | 2 dead signals, fleet cleanup | ~3h | Phase 2 would have caught immediately |

**Estimated sessions saved per month with full automation: 2-3**
