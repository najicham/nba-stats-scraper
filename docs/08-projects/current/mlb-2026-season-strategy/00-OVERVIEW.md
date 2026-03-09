# MLB 2026 Season Strategy

**Status:** Pre-season preparation (deploy by Mar 24)
**Session:** 443
**Algorithm:** `mlb_v5_cross_validated_top3`

## Summary

11-agent cross-season validated strategy for MLB pitcher strikeout over/under predictions. CatBoost regressor with 2-tier pick system (Best Bets + Ultra). Walk-forward tested on 3,869 predictions across Apr 2024 - Sep 2025.

## Documents

| Doc | Contents |
|-----|----------|
| [01-RESEARCH-FINDINGS.md](01-RESEARCH-FINDINGS.md) | All 11 agent results, what survived cross-season validation |
| [02-STRATEGY.md](02-STRATEGY.md) | The definitive strategy: model, filters, tiers, staking |
| [03-DEPLOY-CHECKLIST.md](03-DEPLOY-CHECKLIST.md) | Step-by-step deployment before Mar 24 |
| [04-SEASON-GOALS.md](04-SEASON-GOALS.md) | Monthly/season targets, monitoring triggers |
| [05-DEAD-ENDS.md](05-DEAD-ENDS.md) | What we tested and rejected (don't revisit) |

## Season Goals

| Tier | HR Target | Volume | ROI Target | Staking |
|------|-----------|--------|------------|---------|
| Best Bets | 60-65% | 2-3/day | 15-25% | 1u |
| Ultra | 67-75% | 1-2/day | 25-40% | 2u |
| Combined | — | 3-4/day | 20-30% | Mixed |

## Key Dates

- **Mar 18-20:** Train final model on latest data
- **Mar 21-22:** Deploy worker, set env vars
- **Mar 24-25:** Season opens, schedulers resume
- **Mar 27:** First game day with full predictions
- **Apr 14:** First 3-week checkpoint (retrain)
- **May 1:** UNDER enablement decision point
