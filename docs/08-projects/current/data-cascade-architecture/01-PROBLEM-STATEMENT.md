# Problem Statement: Silent Data Degradation in Rolling Windows

**Document:** 01-PROBLEM-STATEMENT.md
**Created:** January 22, 2026

---

## The Problem in One Sentence

When historical data is missing, the system continues processing with incomplete rolling averages, producing **biased features and predictions without any warning or tracking**.

---

## Real-World Example

### The Incident (January 2026)

1. **Dec 27 - Jan 21:** Team boxscore scraper failed silently for 26 days
2. **What happened:**
   - Raw data (`nbac_team_boxscore`) was not collected
   - Analytics tables (`team_defense_game_summary`, `team_offense_game_summary`) were empty for those dates
   - BUT: Completeness checks passed because they only validated TODAY's data
3. **The cascade effect:**
   - `player_daily_cache` calculated rolling averages with missing games
   - `ml_feature_store_v2` generated features using stale/biased data
   - Predictions were made with these degraded features
   - **No error, no warning, no flag**

### Concrete Numbers

For a player who played on Jan 1 (one of the missing dates):
- **Expected:** `points_avg_last_10` calculated from 10 most recent games
- **Actual:** Query returned 10 games, but 8 were from before the gap (Dec 26 and earlier)
- **Impact:** Rolling average reflected December performance, not current form
- **Prediction bias:** Could be off by 5-10 points depending on player's recent trajectory

---

## Why This Matters

### Business Impact

| Scenario | What Happens | Financial Impact |
|----------|--------------|------------------|
| High-scoring games missing | Average deflated | Under-predictions, missed value |
| Low-scoring games missing | Average inflated | Over-predictions, bad bets |
| Trend calculation gaps | `recent_trend` becomes meaningless | Model confidence misleading |
| Multiple gaps compound | All features degraded | Systematic prediction errors |

### Model Quality Impact

The CatBoost V8 model uses **33 features**. Key affected features when data is missing:

| Feature | Model Weight | Impact of Missing Data |
|---------|--------------|------------------------|
| `points_avg_last_10` | HIGH | Biased by 10-25% |
| `points_avg_last_5` | HIGH | Even more volatile |
| `recent_trend` | MEDIUM | Can flip sign (positive → negative) |
| `ppm_avg_last_10` | HIGH (14.6%) | Efficiency metric corrupted |
| `minutes_avg_last_10` | HIGH (10.9%) | Minutes pattern lost |
| `consistency_score` | MEDIUM | Std dev calculation wrong |

### Trust Impact

- Users see "95% confidence" on predictions made with stale data
- Quality scores show "100%" because features aren't null
- No way to identify which predictions were affected after the fact

---

## The Fundamental Gap

### What We Check Today

```
Processing Jan 22:

✓ Does Jan 22 schedule exist?           → YES (7 games)
✓ Does Jan 22 gamebook exist?           → YES (247 player records)
✓ Does Jan 22 props exist?              → YES (28,000+ lines)

ALL CHECKS PASS → PROCEED
```

### What We DON'T Check

```
Processing Jan 22:

✗ Does Jan 21 team_boxscore exist?      → NOT CHECKED
✗ Are all 10 games in window present?   → NOT CHECKED
✗ Does the window span a reasonable time? → NOT CHECKED
✗ Is the data we're about to USE there? → NOT CHECKED
```

### The Query That Lies

```python
# In feature_extractor.py
query = """
SELECT *
FROM player_game_summary
WHERE game_date < '2026-01-22'
  AND game_date >= DATE_SUB('2026-01-22', INTERVAL 60 DAY)
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY player_lookup
    ORDER BY game_date DESC
) <= 10
"""

# This query ALWAYS returns up to 10 rows
# It doesn't care if the "right" 10 rows exist
# It just returns the 10 most recent rows we HAVE
```

**The lie:** A successful query with 10 rows doesn't mean we have the RIGHT 10 games.

---

## Affected Components

### Direct Impact (Missing Data Period)

| Component | Table | Impact |
|-----------|-------|--------|
| Team Defense Stats | `team_defense_game_summary` | Empty for gap dates |
| Team Offense Stats | `team_offense_game_summary` | Empty for gap dates |
| Player Daily Cache | `player_daily_cache` | Rolling averages use wrong games |
| Composite Factors | `player_composite_factors` | Fatigue, pace scores degraded |
| ML Features | `ml_feature_store_v2` | Features biased |
| Predictions | `ml_predictions_v2` | Predictions unreliable |

### Cascade Impact (After Gap Period)

Even after the gap is "over", the effects linger:

```
Gap: Jan 1 missing

Jan 2:  Last 10 games = Dec 31, Dec 29, Dec 27... (missing Jan 1)
Jan 3:  Last 10 games = Jan 2, Dec 31, Dec 29... (missing Jan 1)
...
Jan 12: Last 10 games = Jan 11, Jan 10... (Jan 1 finally pushed out)

Impact duration: ~10-14 days after the missing date
```

---

## What "Complete" Should Mean

### Current Definition (Flawed)

```
Complete = TODAY's input data exists
```

### Required Definition

```
Complete =
  1. TODAY's input data exists
  AND
  2. ALL data needed for calculations exists
  AND
  3. Rolling windows have expected game counts
  AND
  4. Window spans are within expected ranges
```

### Specific Completeness Criteria

| Metric | Complete | Incomplete |
|--------|----------|------------|
| Games in 10-game window | 10 | < 10 |
| Window span (10 games) | ≤ 21 days | > 21 days |
| Games in 5-game window | 5 | < 5 |
| Window span (5 games) | ≤ 10 days | > 10 days |

---

## The Ask

1. **Detection:** Know immediately when historical data is incomplete
2. **Tracking:** Store what data was used and what was missing
3. **Flagging:** Mark features/predictions generated with incomplete data
4. **Cascade:** After backfill, know exactly what needs re-running
5. **Monitoring:** Daily visibility into data completeness across the pipeline

---

## Related Documents

- `02-ROOT-CAUSE-ANALYSIS.md` - Why this happens architecturally
- `../team-boxscore-data-gap-incident/INCIDENT-REPORT-JAN-22-2026.md` - The triggering incident
- `../../09-handoff/2026-01-22-DATA-CASCADE-PROBLEM-HANDOFF.md` - Initial analysis

---

**Document Status:** Complete
