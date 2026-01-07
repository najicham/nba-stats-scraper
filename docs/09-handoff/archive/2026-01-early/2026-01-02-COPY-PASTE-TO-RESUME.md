# Copy-Paste Prompt to Resume ML Investigation

**Instructions**: Copy everything below the line and paste into a new Claude Code session.

---

I'm continuing ML investigation and data quality fix for NBA player prediction system. Previous session completed 6-hour ultrathink analysis and identified critical data quality issue.

## Critical Finding

**95% of training data has missing values** - ML models (v1, v2, v3) are training on imputed fake defaults instead of real patterns.

```
Root Cause: player_game_summary.minutes_played is 99.5% NULL (423 of 83,534 rows)
Impact: Window functions on NULL → cascade to 95% NULL for minutes_avg_last_10
Result: Models learn from defaults (fatigue=70, usage=25) not reality
Current Performance: 4.63 MAE (6.9% worse than mock's 4.33)
```

## What Previous Session Accomplished

✅ Trained 3 ML models (v1, v2, v3) - all failed to beat mock baseline
✅ Investigated root cause - discovered 95% missing data issue
✅ Ran 5 parallel analysis agents (mock model, production ML, data quality, alternatives, business case)
✅ Created comprehensive fix plan with 7 phases over 18 weeks
✅ Created 4 detailed handoff documents
✅ Initialized 30-item todo list

## Strategy Determined

**NOT**: Replace mock with ML
**YES**: Fix data → Quick wins → Hybrid ensemble (mock + ML)

**Expected Outcome**: 3.40-3.60 MAE (20-25% better than mock)

## Your Mission

**Phase 1 (Week 1)**: Investigate why `minutes_played` is 99.5% NULL

**Immediate Actions**:
1. Run 3 data source health queries (bdl, nbac, gamebook)
2. Trace player_game_summary ETL pipeline
3. Determine if regression or historical gap
4. Document root cause and create fix plan

## Working Directory

`/home/naji/code/nba-stats-scraper`

## Key Files to Read

**START HERE** (pick one based on your preference):
- `docs/09-handoff/2026-01-02-COMPLETE-HANDOFF-NEW-SESSION.md` - Full handoff with step-by-step instructions ⭐
- `docs/09-handoff/2026-01-02-ULTRATHINK-EXECUTIVE-SUMMARY.md` - 10-minute executive summary
- `docs/09-handoff/2026-01-02-MASTER-INVESTIGATION-AND-FIX-PLAN.md` - Comprehensive 18-week roadmap

**Supporting docs**:
- `docs/09-handoff/2026-01-02-ML-V3-TRAINING-RESULTS.md` - Why v3 failed (technical analysis)

## First Query to Run

Verify the 95% NULL claim:

```sql
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';
```

Expected: ~99.5% NULL

If confirmed, proceed to investigation queries in COMPLETE-HANDOFF-NEW-SESSION.md (Step 1).

## Todo List

30 items tracked in TodoWrite tool. Current phase:

```
P0-WEEK1 (Investigation):
- [ ] Run 3 data source health queries
- [ ] Identify which source has minutes_played
- [ ] Trace player_game_summary processor
- [ ] Check if regression or historical gap
- [ ] Document root cause

P0-WEEK2 (Fix):
- [ ] Fix minutes_played collection
- [ ] Backfill 2021-2024 data
- [ ] Validate data quality >95%

P1-WEEK3-4 (Quick Wins + Retrain):
- [ ] Implement filters (minute threshold, confidence)
- [ ] Retrain XGBoost v3 with clean data
- [ ] DECISION: If beats mock, continue to ensemble

P2-WEEK5-9 (Hybrid Ensemble):
- [ ] Train CatBoost, LightGBM
- [ ] Create interaction features
- [ ] Build stacked ensemble
- [ ] Deploy with A/B test
```

## Success Criteria

**Week 1**: Root cause documented, fix plan created
**Week 4**: Data fixed (NULL <5%), XGBoost v3 MAE <4.20 (beats mock)
**Week 9**: Ensemble MAE <3.60 (20%+ better than mock)

## Key Insights from Previous Session

1. **Mock model is actually brilliant** - Uses 10+ hand-tuned rules encoding 50 years of basketball knowledge (back_to_back = -2.2 penalty, fatigue thresholds, pace × usage interactions)

2. **XGBoost can't learn mock's patterns with 64k samples** - Needs 200-500k samples to discover complex non-linear thresholds reliably

3. **Hybrid approach is the answer** - Combine mock's domain expertise + ML's data-driven adaptation for 20-25% gain

4. **Quick wins have 5-10x better ROI** - Filters (minute threshold, confidence) give 13-25% improvement for 4 hours work vs ML optimization

5. **Business case for pure ML is weak** - ROI is negative to marginal (-$4.7k to +$3.3k Year 1) vs quick wins + data quality ($40-80k)

## Decision Points

**After Week 1**: If root cause is fixable → proceed to fix. If unfixable → stop ML work, accept mock.

**After Week 4**: If XGBoost v3 beats mock (MAE <4.20) → proceed to ensemble. If not → investigate further.

**After Week 9**: If ensemble MAE <3.60 → deploy with A/B test. If >4.00 → reassess strategy.

## What NOT to Do

❌ Train more models before fixing data (garbage in, garbage out)
❌ Try to beat mock with pure ML (need hybrid approach)
❌ Skip quick wins to chase ML (negative ROI)
❌ Build production infrastructure before 90%+ system maturity

## What TO Do

✅ Fix the 95% NULL issue FIRST (everything else depends on this)
✅ Implement quick win filters WHILE investigating (parallel work)
✅ Study mock model's rules and encode as features (interactions)
✅ Build hybrid ensemble, not pure ML replacement
✅ A/B test everything before full deployment

## Expected Timeline

- Week 1: Investigation (4-6 hours)
- Weeks 2-4: Data fixes + quick wins (35-50 hours)
- Weeks 5-9: Hybrid ensemble (60-80 hours)
- **Total**: 100-136 hours over 9 weeks

## Next Steps

1. Read COMPLETE-HANDOFF-NEW-SESSION.md (focus on Phase 1 section)
2. Run verification query above
3. If confirmed, run the 3 data source queries (Step 1)
4. Trace ETL pipeline (Step 2)
5. Document findings and create fix plan
6. Update todos using TodoWrite tool as you progress

## Questions?

All details in the handoff docs. Key doc: `docs/09-handoff/2026-01-02-COMPLETE-HANDOFF-NEW-SESSION.md`

---

**Let's fix this data and build a winning hybrid ensemble!** 🚀
