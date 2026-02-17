# Daily Checklist

**Your 5-minute morning routine. Start after 11 AM ET (when decay-detection has run).**

Updated: 2026-02-15 (Session 271)

---

## Step 1: Check Slack (30 seconds)

Scan `#nba-alerts` and `#deployment-alerts` for overnight messages.

| Alert | What it means | Action |
|-------|---------------|--------|
| No alerts | Everything normal | Continue to Step 2 |
| "MODEL DECAY — WATCH" | 7d HR dipped below 58% | Note it, continue to Step 2 |
| "MODEL DECAY — DEGRADING" | 7d HR below 55% for 3+ days | **Act after Step 2** |
| "MODEL DECAY — BLOCKED" | Below breakeven (52.4%) | **Act after Step 2** |
| "MARKET DISRUPTION" (dark red) | 2+ models crashed <40% | **Do NOT switch models.** Pause betting 1 day. |
| "Challenger outperforming" | Shadow model beating champion | Note it, verify in Step 2 |
| Deployment drift | Code pushed but not deployed | Run `./bin/deploy-service.sh SERVICE` |

## Step 2: Run Daily Steering (2 minutes)

```
/daily-steering
```

Read the recommendation line. It will say one of:

| Recommendation | What to do |
|----------------|------------|
| **ALL CLEAR** | Done. Close laptop. |
| **WATCH** | Note it. Check again tomorrow. No action needed. |
| **SWITCH** | Follow the switch command provided. Takes 30 seconds. |
| **RETRAIN** | Plan a retrain session (not urgent, within the week). |
| **BLOCKED** | Model below breakeven. Check if challenger viable (Step 3). |

If ALL CLEAR or WATCH: **you're done.** Most days end here.

## Step 3: Only If Action Needed

### Switching models (SWITCH or BLOCKED with viable challenger)

The steering report will show which challenger to switch to. Run:
```bash
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="BEST_BETS_MODEL_ID=<challenger_model_id>"
```

Verify the switch took effect:
```bash
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | grep BEST_BETS
```

### No viable challenger (BLOCKED, no good option)

Picks still get produced (health gate removed), but quality is low. Options:
1. **Start retrain** — see steering playbook Scenario 5
2. **Wait** — if model is <3 days stale, it may self-correct
3. **Pause manually** — tell users to sit out (rare, only for extended decay)

### Market disruption (MARKET DISRUPTION alert)

Do NOT switch models. All models are affected equally. Pause betting for 1 day.

---

## Optional: Deeper Validation

Only run these if something looks off or you want extra confidence:

```
/validate-daily --quick          # 3 min — pipeline health snapshot
/reconcile-yesterday             # 3 min — check yesterday's gaps
```

---

## Evening Routine

**None required.** Everything is automated:
- Grading triggers automatically when games finish (~15 min after last game)
- Post-grading export updates model performance metrics
- Signal health recalculated
- Picks re-exported with actual scores

Only check Slack if you're curious. No action needed.

---

## Weekly (Optional)

- **Monday:** Glance at 7-day model trend in `/daily-steering` — is HR trending up or down?
- **Monthly:** Plan a retrain if champion is 30+ days stale (even if performing well)

---

## What You Can Safely Ignore

- `#canary-alerts` — auto-healed, informational only
- Individual grading gap alerts — auto-backfilled
- Pipeline health summaries — informational
- Phase transition notifications — automated

## What Needs Your Attention

- State transition alerts (WATCH → DEGRADING → BLOCKED)
- Cross-model crash (MARKET DISRUPTION)
- Challenger outperformance (potential model switch)
- Deployment drift (deploy if >24h stale)
