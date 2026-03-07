# Start Here — Session 433

**Previous Session:** 432 (2026-03-07)
**Handoff:** `docs/09-handoff/2026-03-07-SESSION-432-HANDOFF.md`

## Quick Status
- Auto-demote filter system fully deployed and tested
- 4 scheduled monitoring CFs: data source (7AM), filter CF HR (11:30AM), signal decay (12PM), weight report (Mon 10AM)
- All 5 CI pre-commit checks BLOCKING
- 8 enabled models, AUTO_DISABLE live
- 27 active + 26 shadow signals, 19 active negative filters (13 eligible for auto-demote)

## Priorities
1. **MLB Pre-Season** (Mar 24-25) — resume schedulers, retrain, E2E test
2. **SPOF Fallback Scrapers** — NumberFire, RotoWire, VSiN, Covers, Hashtag
3. **Model Diversity** — all 8 models r >= 0.95 redundant
4. **Slack webhook for filter CF** — add SLACK_WEBHOOK_URL_WARNING env var
