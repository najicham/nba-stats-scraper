# Session 158 Prompt

Copy everything below this line into a new chat:

---

START, then read `docs/09-handoff/2026-02-07-SESSION-157-HANDOFF.md` for full context.

## Session 157 Summary

We discovered and fixed training data contamination in the ML pipeline:

- **33.2% of V9 training data had garbage default values** that passed the quality filter because `feature_quality_score` was a weighted average that masked individual defaults (5 defaults → score 91.9, still passing >= 70).
- **Fixed with 3 layers:** (1) shared training data loader enforcing `required_default_count = 0`, (2) quality score now capped at 69 when defaults exist, (3) fixed 7,088 historical BigQuery records
- **Migrated 6 active training scripts** to shared loader, archived 41 legacy scripts
- **V9 retrain** tested but eval window too small — waiting for backfill + clean data

## Priority 1: Feature Store Backfill (DO THIS FIRST)

Re-run ML feature store processor for current season (Nov 2025 - Feb 2026) with Session 156 improvements. This will produce fewer defaults and cleaner training data for the regular end-of-month retrain.

**Before running, review and update the backfill script:**
1. Read `scripts/regenerate_ml_feature_store.py` — this runs `MLFeatureStoreProcessor` locally for a date range
2. Consider whether `PlayerDailyCacheProcessor` also needs re-running (Session 156 expanded its player selection with roster UNION)
3. **Add logging for missing data** — when a feature falls back to default, log which player/date/feature was affected so we can identify data gaps to fix upstream
4. Run the backfill:
```bash
PYTHONPATH=. python scripts/regenerate_ml_feature_store.py \
  --start-date 2025-11-02 --end-date 2026-02-07
```

## Priority 2: Tier Bias Investigation

Both V9 and clean retrain show regression-to-mean: stars -9 pts, bench +7 pts. Investigate root cause and fix.

## DO NOT retrain V9 yet

V9 is performing adequately (54-56% hit rate, 65%+ at edge 3+). A clean retrain was tested in Session 157 but the eval window was too small to draw conclusions. **Wait until end of February for the regular monthly retrain** — by then the backfilled data + 2-3 weeks of new clean data will give a much better training set and enough eval data for a reliable comparison.

## Feature Ideas (Later)

- `games_missed_in_last_10` — team games missed, indicates injury/rest patterns
- `days_on_current_team` — for recently traded players, usage may be unpredictable first 5-10 games
