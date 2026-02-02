# Kalshi Integration Roadmap

**Created:** February 2, 2026
**Status:** Integration Complete, Monitoring Phase

## Timeline Overview

```
Week 1 (Feb 3-9)     │ Monitor & Validate
Week 2 (Feb 10-16)   │ Quick Wins + Trade Deadline (Feb 6)
Week 3 (Feb 17-23)   │ All-Star Break (Feb 14-19) + Analytics
Week 4+ (Feb 24+)    │ Advanced Features
```

---

## Week 1: Monitor & Validate (Feb 3-9)

### Goals
- Confirm Kalshi enrichment is working in production
- Establish baseline coverage metrics
- Identify any data quality issues

### Daily Checks
```sql
-- Run this daily to track Kalshi coverage
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNTIF(kalshi_available) as with_kalshi,
  ROUND(100.0 * COUNTIF(kalshi_available) / COUNT(*), 1) as kalshi_pct,
  ROUND(AVG(CASE WHEN kalshi_available THEN ABS(line_discrepancy) END), 2) as avg_discrepancy
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-03'
  AND system_id = 'catboost_v9'
GROUP BY game_date
ORDER BY game_date;
```

### Success Criteria
- [ ] Kalshi fields populated in predictions (kalshi_available = TRUE for 30-50% of players)
- [ ] No errors in prediction-coordinator logs related to Kalshi queries
- [ ] `/validate-daily` Phase 0.9 passing

### Action Items
| Task | Priority | Owner | Notes |
|------|----------|-------|-------|
| Verify Feb 3 predictions have Kalshi data | P1 | Auto | Check after 7 AM ET |
| Monitor Kalshi scraper success rate | P2 | Auto | Should be 100% |
| Document baseline coverage % | P2 | Manual | Expected 30-50% |

---

## Week 2: Quick Wins + Trade Deadline (Feb 10-16)

### NBA Context
- **Trade Deadline: February 6, 2026** - Player movements may affect Kalshi coverage
- Registry auto-updates within 30 minutes of trades (Session 74)

### Goals
- Implement arbitrage detection alerts
- Add Kalshi to /top-picks skill
- Handle any trade deadline disruptions

### Arbitrage Alert Implementation

**Option A: Simple Cloud Function**
```python
# Trigger: After prediction batch completes
# Action: Query for line_discrepancy >= 2, send notification

def check_arbitrage(event, context):
    query = """
    SELECT player_lookup, current_points_line, kalshi_line, line_discrepancy
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = CURRENT_DATE()
      AND kalshi_available = TRUE
      AND ABS(line_discrepancy) >= 2
    ORDER BY ABS(line_discrepancy) DESC
    LIMIT 10
    """
    # Execute and send to Discord/Slack
```

**Option B: Add to Prediction Coordinator**
- After batch completes, query for arbitrage opportunities
- Log to dedicated table or send notification

### Update /top-picks Skill
Add columns to show Kalshi comparison:
```
| Player | Vegas | Predicted | Edge | Kalshi | Discrepancy |
|--------|-------|-----------|------|--------|-------------|
| LeBron | 24.5  | 29.1      | +4.6 | 24.5   | 0.0         |
| Tatum  | 28.5  | 22.3      | -6.2 | 29.5   | +1.0        |
```

### Action Items
| Task | Priority | Est. Effort | Notes |
|------|----------|-------------|-------|
| Create arbitrage alert function | P1 | 2-3 hours | Cloud Function or in-coordinator |
| Update /top-picks skill | P2 | 1 hour | Add Kalshi columns |
| Monitor trade deadline impact | P1 | Ongoing | Check registry updates |

---

## Week 3: All-Star Break + Analytics (Feb 17-23)

### NBA Context
- **All-Star Break: February 14-19, 2026**
- No regular games = no predictions needed
- Good time for analysis and improvements

### Goals
- Analyze first 2 weeks of Kalshi data
- Build Kalshi accuracy comparison
- Backtest arbitrage profitability

### Analytics Queries

**Kalshi vs Vegas Accuracy (Post-Game)**
```sql
-- Which line was closer to actual points?
SELECT
  COUNTIF(ABS(kalshi_line - actual_points) < ABS(current_points_line - actual_points)) as kalshi_wins,
  COUNTIF(ABS(kalshi_line - actual_points) > ABS(current_points_line - actual_points)) as vegas_wins,
  COUNTIF(ABS(kalshi_line - actual_points) = ABS(current_points_line - actual_points)) as ties
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.kalshi_available = TRUE
  AND p.game_date >= '2026-02-03'
  AND p.game_date < CURRENT_DATE();
```

**Arbitrage Hit Rate**
```sql
-- When Kalshi differs by 2+, who's right more often?
SELECT
  CASE
    WHEN line_discrepancy > 0 THEN 'Kalshi Higher'
    ELSE 'Vegas Higher'
  END as scenario,
  COUNT(*) as occurrences,
  ROUND(100.0 * COUNTIF(
    (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
    (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
  ) / COUNT(*), 1) as model_hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.kalshi_available = TRUE
  AND ABS(p.line_discrepancy) >= 2
  AND p.game_date >= '2026-02-03'
GROUP BY scenario;
```

### Action Items
| Task | Priority | Est. Effort | Notes |
|------|----------|-------------|-------|
| Run Kalshi vs Vegas accuracy analysis | P1 | 1 hour | During All-Star break |
| Analyze arbitrage opportunities | P1 | 2 hours | What's the ROI? |
| Document findings | P2 | 1 hour | Update project README |

---

## Week 4+: Advanced Features (Feb 24+)

### Goals
- Multi-prop Kalshi (rebounds, assists, threes)
- Line movement tracking
- Kalshi as ML feature

### Multi-Prop Extension

Currently only points props are enriched. To extend:

1. **Update `_query_kalshi_line()` in player_loader.py**
   - Add `prop_type` parameter
   - Query for each prop type

2. **Add schema fields**
   ```sql
   ALTER TABLE player_prop_predictions
   ADD COLUMN IF NOT EXISTS kalshi_rebounds_line FLOAT64,
   ADD COLUMN IF NOT EXISTS kalshi_assists_line FLOAT64,
   ADD COLUMN IF NOT EXISTS kalshi_threes_line FLOAT64;
   ```

3. **Consider if valuable**
   - Do we predict rebounds/assists/threes?
   - Is there arbitrage opportunity in these markets?

### Line Movement Tracking

To track how Kalshi lines move:

1. **Create historical table**
   ```sql
   CREATE TABLE nba_predictions.kalshi_line_history (
     player_lookup STRING,
     game_date DATE,
     prop_type STRING,
     line_value FLOAT64,
     yes_price INT64,
     captured_at TIMESTAMP
   );
   ```

2. **Scrape multiple times per day**
   - 2 AM (current), 10 AM, 4 PM, 7 PM
   - Track line movement patterns

### Kalshi as ML Feature

Could `line_discrepancy` be predictive?

Hypothesis: When Kalshi and Vegas disagree significantly, one market may have better information.

Test:
```sql
-- Does high discrepancy predict model accuracy?
SELECT
  CASE
    WHEN ABS(line_discrepancy) >= 3 THEN 'High Discrepancy'
    WHEN ABS(line_discrepancy) >= 1 THEN 'Medium Discrepancy'
    ELSE 'Low Discrepancy'
  END as discrepancy_tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.player_prop_predictions p
  ON pa.player_lookup = p.player_lookup
  AND pa.game_date = p.game_date
  AND pa.system_id = p.system_id
WHERE p.kalshi_available = TRUE
GROUP BY discrepancy_tier;
```

---

## Key Dates

| Date | Event | Impact |
|------|-------|--------|
| Feb 3 | First predictions with Kalshi | Verify enrichment working |
| Feb 6 | Trade Deadline | Player registry updates |
| Feb 14-19 | All-Star Break | No games, analysis time |
| Feb 24 | Post-ASB games resume | Full data collection resumes |
| Mar 1 | 1 month of Kalshi data | Meaningful analytics possible |

## Success Metrics

### Week 1-2
- Kalshi coverage: 30-50% of predictions
- Zero Kalshi-related errors in logs
- Arbitrage alerts functional

### Week 3-4
- Kalshi vs Vegas accuracy analyzed
- Arbitrage profitability documented
- Decision on multi-prop extension

### Month 1+
- Clear understanding of Kalshi value
- Either: Expand usage OR deprioritize based on data
- ML feature experiment complete

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Kalshi API changes | Low | High | Monitor scraper logs, have fallback |
| Low Kalshi coverage | Medium | Low | Kalshi is supplementary, not critical |
| Query performance | Low | Medium | Kalshi query is simple, cached in coordinator |
| Trade deadline disruption | Medium | Low | Registry auto-updates, monitoring in place |

---

*Last Updated: February 2, 2026*
