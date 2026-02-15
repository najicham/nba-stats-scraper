# Prompt for New Chat Session — Signal Testing Continuation

Copy and paste this into your new chat:

---

Read `docs/09-handoff/2026-02-14-SESSION-255-HANDOFF.md` — this is the latest handoff.

**Context:** Session 255 tested 4 new signals (accepted 2: `cold_snap` 64.3% HR, `blowout_recovery` 56.4% HR; rejected 2: `hot_streak` 47.5%, `rest_advantage` 50.8%). The signal framework is now production-ready with BQ tables created and backfilled. However, the registry has 23 total signals including 15 prototypes from an earlier session that need review.

**Critical issue:** Some prototype signals in the registry are **actively harmful** (e.g., `prop_value_gap_extreme` at 12.5% HR). The handoff notes: *"Some prototypes are actively harmful. Next session should review the backfill results in `v_signal_performance` and remove low-performers."*

**Your immediate mission:**

1. **Query signal performance** to identify harmful signals:
   ```sql
   SELECT * FROM nba_predictions.v_signal_performance
   ORDER BY hit_rate DESC;
   ```

2. **Review and clean up the registry** (`ml/signals/registry.py`):
   - Remove signals with HR < 52.4% (below breakeven)
   - Keep only proven performers
   - Document which were removed and why

3. **Test remaining signals properly** using the backtest harness:
   ```bash
   PYTHONPATH=. python ml/experiments/signal_backtest.py --save
   ```

4. **Then** continue with new signal exploration following the master plan in:
   - `docs/08-projects/current/signal-discovery-framework/COMPREHENSIVE-SIGNAL-TEST-PLAN.md`

**Current production signals (proven):**
- `model_health` (gate)
- `high_edge` (66.7% HR)
- `3pt_bounce` (74.9% HR)
- `minutes_surge` (53.7% standalone, 87.5% overlap)
- `cold_snap` (64.3% HR, NEW)
- `blowout_recovery` (56.4% HR, NEW)

**Prototypes to review (15 signals from earlier session):**
These are in the registry but performance unknown. Check `v_signal_performance` table to see if they're helping or hurting.

**Key documents:**
- `docs/09-handoff/2026-02-14-SESSION-255-HANDOFF.md` — Session 255 handoff
- `docs/08-projects/current/signal-discovery-framework/COMPREHENSIVE-SIGNAL-TEST-PLAN.md` — Master strategy
- `docs/08-projects/current/signal-discovery-framework/01-BACKTEST-RESULTS.md` — Latest backtest results

**What's NOT done yet:**
- Cloud Function redeploy (post-grading-export, phase5-to-phase6-orchestrator)
- Frontend integration for Best Bets
- Registry cleanup (remove harmful prototypes)

**Expected outcomes:**
- Clean registry with only profitable signals
- Validate which signals are production-ready
- Continue implementing new high-value signals
- Build toward comprehensive signal coverage

**Philosophy:** Quality > quantity. Remove signals that hurt performance before adding more.

Start by querying `v_signal_performance` and cleaning up the registry! 🧹

---

