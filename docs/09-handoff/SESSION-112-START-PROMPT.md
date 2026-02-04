# Session 112: Review and Validate Session 111 Findings

## Your Mission

Session 111 conducted a major investigation into model bias and hit rate optimization. Before implementing the proposed changes, **your job is to critically review the findings and either validate or challenge them**.

## Step 1: Read the Handoff

Start by reading the Session 111 handoff:
```
docs/09-handoff/2026-02-03-SESSION-111-HANDOFF.md
```

## Step 2: Review the Investigation Documentation

Read the full findings:
```
docs/08-projects/current/regression-to-mean-fix/README.md
docs/08-projects/current/regression-to-mean-fix/SESSION-111-OPTIMAL-SCENARIOS.md
docs/08-projects/current/regression-to-mean-fix/INVESTIGATION-FINDINGS.md
```

## Step 3: Use Agents to Independently Verify

Launch parallel agents to verify the claims:

### Agent 1: Verify Optimal Scenario Hit Rates
Query `nba_predictions.prediction_accuracy` to confirm:
- OVER + Line <12 + Edge ≥5 really achieves 87% hit rate
- UNDER + Line ≥25 + Edge ≥3 really achieves 66% hit rate
- Sample sizes are sufficient for statistical significance
- Results hold across different time periods (not just cherry-picked)

### Agent 2: Verify Anti-Pattern Claims
Confirm the anti-patterns are real:
- UNDER on lines <20 really underperforms
- The 5 blacklisted players (Luka, Maxey, Sharpe, Harden, Randle) really have poor UNDER hit rates
- Edge <3 picks really lose money

### Agent 3: Review the Bias Fix Experiments
Look at `ml/experiments/bias_fix_experiments.py` and verify:
- Quantile 0.53 really gives +1.4% improvement
- Aggressive calibration really hurts hit rate
- The experiment methodology is sound

### Agent 4: Study Current System Architecture
Understand how to implement the changes:
- How are subsets currently defined? (check Phase 6, predictions/)
- Where would scenario filters be added?
- What's the prediction output format?

## Step 4: Critical Questions to Answer

1. **Are the sample sizes sufficient?**
   - 71 bets for "optimal OVER" - is this enough?
   - What's the confidence interval?

2. **Is this overfitting to recent data?**
   - Do the patterns hold in Oct-Dec 2025?
   - Or only in Jan-Feb 2026?

3. **Are there confounding factors?**
   - Are low-line OVER picks just bench players who are easier to predict?
   - Is there selection bias in the analysis?

4. **What's the risk of the proposed changes?**
   - If we filter to only optimal scenarios, volume drops to 3-5 picks/day
   - Is that acceptable?

5. **Are there better approaches not considered?**
   - What about time-of-day patterns?
   - What about home/away splits?
   - What about back-to-back game effects?

## Step 5: Present Your Findings

After your review, present:

1. **Do you agree with the Session 111 findings?**
   - Which findings are solid?
   - Which need more validation?
   - Which might be wrong?

2. **Your own recommendations:**
   - Same as Session 111?
   - Modified approach?
   - Completely different strategy?

3. **Implementation priority:**
   - What should be done first?
   - What needs more research?
   - What should be skipped?

## Key Claims to Verify

| Claim | Source | Verify This |
|-------|--------|-------------|
| OVER + Line <12 + Edge ≥5 = 87.3% HR | Session 111 | Query prediction_accuracy |
| Only 15 bad records in feature store | Session 111 | Run full audit query |
| Quantile 0.53 improves HR by 1.4% | bias_fix_experiments.py | Review experiment results |
| Star bias (-9 pts) doesn't hurt HR | Session 111 | Analyze by tier |
| Feb 2 was one bad day, not systemic | Session 111 | Check daily breakdown |

## Files to Review

| File | Purpose |
|------|---------|
| `docs/09-handoff/2026-02-03-SESSION-111-HANDOFF.md` | Full session summary |
| `docs/08-projects/current/regression-to-mean-fix/` | All investigation docs |
| `ml/experiments/bias_fix_experiments.py` | Experiment code |
| `shared/ml/feature_contract.py` | New feature contract |
| `.claude/skills/spot-check-features/SKILL.md` | Audit queries |

## Expected Output

A comprehensive review that either:
1. **Validates** Session 111 findings and recommends proceeding with implementation
2. **Challenges** specific findings with data and suggests modifications
3. **Proposes** alternative approaches based on your own analysis

Be critical but constructive. The goal is to make the best decision for hit rate improvement.

---

**Important:** Don't just trust Session 111's conclusions. Verify them independently. The best outcome is either confident validation or catching a flaw before we implement something wrong.
