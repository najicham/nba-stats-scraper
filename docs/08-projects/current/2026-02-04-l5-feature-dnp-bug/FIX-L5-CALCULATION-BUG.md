# Fix L5 Feature Calculation Bug - Action Required

## The Problem

The `points_avg_last_5` feature in `nba_analytics.upcoming_player_game_context` is calculating incorrect values for ~26% of players. This directly impacts prediction accuracy.

## Evidence (Verified 2026-02-04)

| Player | Feature Shows | Should Be | Error |
|--------|--------------|-----------|-------|
| Nikola Jokic | 6.2 | 34.2 | **28.0 pts off** |
| Lauri Markkanen | 3.8 | 26.6 | 22.8 pts off |
| Kawhi Leonard | 9.0 | 29.2 | 20.2 pts off |
| Ja Morant | 4.8 | 23.6 | 18.8 pts off |

20+ players showing differences >5 points in recent games (Jan-Feb 2026).

## Diagnostic Query

```sql
WITH manual_calc AS (
  SELECT
    player_lookup,
    game_date,
    ROUND(AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ), 1) as manual_l5
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2025-12-01'
    AND points IS NOT NULL
    AND is_dnp = FALSE
),
feature_values AS (
  SELECT player_lookup, game_date, points_avg_last_5
  FROM nba_analytics.upcoming_player_game_context
  WHERE game_date >= '2026-01-01'
)
SELECT
  f.player_lookup,
  f.game_date,
  f.points_avg_last_5 as feature_l5,
  m.manual_l5,
  ROUND(ABS(f.points_avg_last_5 - m.manual_l5), 1) as difference
FROM feature_values f
JOIN manual_calc m USING (player_lookup, game_date)
WHERE ABS(f.points_avg_last_5 - m.manual_l5) > 5
ORDER BY difference DESC
LIMIT 20;
```

**Expected result after fix:** Zero rows (or only edge cases with <1 pt difference)

## Where to Fix

The `upcoming_player_game_context` table is populated by **Phase 4 precompute processors**.

**Start here:**
```bash
# Find where points_avg_last_5 is calculated
grep -r "points_avg_last_5" data_processors/precompute/
```

**Likely culprits:**
1. **DNP games included** - Are games where `is_dnp = TRUE` incorrectly counted?
2. **Date window wrong** - Is the "last 5 games" window calculated correctly?
3. **Ordering issue** - Is `ORDER BY game_date DESC` being used when it should be ASC (or vice versa)?
4. **Wrong table join** - Is source data coming from the wrong table/view?

## Fix Checklist

- [ ] Find L5 calculation code in `data_processors/precompute/`
- [ ] Identify root cause (likely DNP handling or date logic)
- [ ] Fix the calculation
- [ ] Test locally with diagnostic query
- [ ] Reprocess Phase 4 for recent dates (Jan-Feb 2026 minimum)
- [ ] Verify fix: run diagnostic query, expect 0 rows with >5 pt difference
- [ ] Regenerate predictions (Phase 5) with corrected features
- [ ] Deploy Phase 4 service: `./bin/deploy-service.sh nba-phase4-precompute-processors`

## Recent Fix (Session 113)

A fix was committed that **excludes DNP games from L5/L10 calculations** in the ML feature store:

```
commit: 8eba5ec3
file: data_processors/precompute/player_feature_calculator.py:102-109
```

**BUT the diagnostic query shows this fix hasn't taken effect yet.** Possible causes:
1. Fix not deployed to Cloud Run
2. Feature store not regenerated after fix
3. Fix incomplete or in wrong location

## Verification Steps

After you think it's fixed:

```bash
# 1. Check deployed commit
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# 2. Compare to latest commit with fix
git log --oneline | grep -i "dnp\|l5"

# 3. Run diagnostic query (should return 0 problematic rows)
bq query --use_legacy_sql=false < diagnostic_query.sql
```

## Why This Matters

- **Blocks Phase 6 exporter** - Can't publish picks if predictions are wrong
- **Hurts model accuracy** - Star players most affected
- **Wasted capital** - Bad predictions = losing bets

## Related Docs

- Full investigation: `docs/09-handoff/2026-02-04-SESSION-113-L5-FEATURE-BUG-HANDOFF.md`
- Phase 4 architecture: `docs/03-phases/phase-4-precompute.md`

---

**Priority:** HIGH - Fix before proceeding with Phase 6 exporter
**Created:** 2026-02-04 Session 114
**Status:** Ready for investigation
