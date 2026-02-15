# Session 271 Prompt — Design My Daily Steering Process

## Context

Games resume Feb 19 after All-Star break. I need a clear, simple daily process for manually steering the system — what to check, what decisions to make, and when to act.

The system now has a lot of automation and monitoring, but I need to understand what actually requires MY attention vs what runs on its own. Session 270 just removed the health gate (signal best bets are now always produced), so the system is less "hands-off block everything when decaying" and more "always produce picks, human decides what to do."

## What Exists Today

**Automated (runs without me):**
- Pipeline: scrapers → raw → analytics → precompute → predictions → publishing (daily, starts ~6 AM ET)
- Grading: auto-grades after games finish
- `model_performance_daily`: auto-computed after grading
- `signal_health_daily`: auto-computed after grading
- `decay-detection` CF: runs 11 AM ET, Slack alerts on state changes
- `daily-health-check` CF: meta-monitoring, verifies freshness
- Signal best bets: always produced now (health gate removed Session 270)
- `model-health.json` + `signal-health.json`: auto-exported to GCS

**Manual tools available:**
- `/daily-steering` — morning report (model health, signal health, best bets performance, recommendations)
- `/validate-daily` — comprehensive pipeline validation
- `/replay` — backtest model strategies
- `steering_replay.py` — backtest full signal pipeline
- `/reconcile-yesterday` — check for gaps
- Model steering playbook: `docs/02-operations/runbooks/model-steering-playbook.md`

**Decisions that are currently manual:**
- Switching `BEST_BETS_MODEL_ID` between champion/challenger
- Triggering retrains
- Pausing on market disruption days (cross-model crash)
- Interpreting Slack alerts and deciding action

## Task

Design my daily process. Specifically:

1. **Review all the automated pieces** and verify nothing is missing or redundant. Map out what runs when.

2. **Design a simple morning routine** (5-10 min). What do I check? In what order? What am I looking for? When do I act vs ignore?

3. **Design an evening/post-game routine** (if needed). Or is everything auto-handled?

4. **Update the steering playbook** (`docs/02-operations/runbooks/model-steering-playbook.md`) to reflect:
   - Health gate removal (Scenario 3 still says "Signal best bets exporter automatically blocks all picks")
   - The new reality: picks always produced, I decide if model needs switching
   - Clearer decision thresholds (when to actually switch vs just monitor)

5. **Create a one-page daily checklist** — something I can literally follow each morning. Put it somewhere obvious like `docs/02-operations/runbooks/daily-checklist.md`.

6. **Identify gaps** — are there decisions I'll need to make that don't have tooling yet? Anything I'm missing?

## What I DON'T want

- Over-engineering or new automation. The system is mature enough.
- More Cloud Functions or scheduled jobs.
- More Slack alerts (I already get enough).
- Theoretical frameworks — I want practical "do this, then this, then this."

## Outcome

By end of session I should have:
- A clear morning routine I can follow starting Feb 19
- An updated steering playbook reflecting current reality
- A daily checklist doc
- Confidence that I understand what needs my attention vs what doesn't
