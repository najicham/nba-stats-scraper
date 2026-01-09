# Next Steps & Recommendations

## Deployment Plan

### Immediate: Shadow Mode (Week 1-2)
```
1. Deploy v8 model alongside existing mock
2. Log both predictions for every game
3. Compare accuracy daily
4. Monitor for:
   - Prediction latency
   - Feature availability issues
   - Edge cases (new players, trades, etc.)
```

### Phase 2: Gradual Rollout (Week 3-4)
```
1. 25% traffic to v8, 75% to mock
2. A/B test actual betting outcomes
3. Monitor bankroll impact
4. Expand to 50%, then 100% if metrics hold
```

### Production Checklist
- [ ] Ensure Vegas lines are refreshed before predictions
- [ ] Ensure minutes/PPM history features are calculated
- [ ] Set up alerting for missing feature data
- [ ] Define fallback strategy (use mock if v8 fails)
- [ ] Log confidence scores with predictions

---

## Immediate Opportunity: Injury Report Filter

### Analysis Results (2024-25 Season)

We analyzed 6,411 DNPs (players with Vegas lines who didn't play):

| DNP Category | Count | % of DNPs | Action |
|--------------|-------|-----------|--------|
| Listed as "OUT" | 1,833 | **28.6%** | **Filter immediately** |
| Listed as "QUESTIONABLE" | 567 | 8.8% | Flag high uncertainty |
| Listed as "DOUBTFUL" | 10 | 0.2% | Flag high uncertainty |
| No injury report entry | 3,760 | 58.6% | Can't catch (late scratches) |

### Key Insight

**This is NOT a model training change - it's an inference-time filter.**

The v9 training attempt (2.6% coverage) failed because:
1. Training data excludes DNPs (by definition, we only train on games played)
2. A feature that's 0 for 97% of training samples can't add signal

**The solution**: Check injury report BEFORE generating predictions.

### Implementation Plan

```python
# At inference time, before generating prediction:
def should_generate_prediction(player_lookup, game_date):
    injury_status = get_latest_injury_status(player_lookup, game_date)

    if injury_status == 'out':
        return False, "SKIP: Player listed as OUT"
    elif injury_status == 'doubtful':
        return True, "WARNING: Player listed as DOUBTFUL"
    elif injury_status == 'questionable':
        return True, "WARNING: Player listed as QUESTIONABLE"
    else:
        return True, "OK"
```

### Expected Impact

- **Prevents 28.6% of DNP errors** (1,833 bad predictions avoided)
- **Average DNP error**: ~13 points (the Vegas line they had)
- **Total error prevented**: ~24,000 points per season
- **Betting impact**: Avoids guaranteed losses on OUT players

### Data Source

```sql
-- Get latest injury status before game
SELECT player_lookup, injury_status
FROM `nba_raw.nbac_injury_report`
WHERE game_date = @target_date
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY player_lookup
  ORDER BY report_hour DESC
) = 1
```

**Coverage**: ~15,000+ unique player-game entries per season (2024-25)

---

## Further Model Improvements

### Worth Pursuing (Medium ROI)

#### 2. Game Totals (O/U) as Feature
**Priority**: HIGH
**Expected Impact**: 0.05-0.10 MAE reduction

Higher game totals mean more scoring opportunities for everyone.

**Implementation**:
- Add `game_total_ou` from Vegas scraper
- Normalize by dividing player's share of typical team scoring

#### 3. Starter Confirmation
**Priority**: MEDIUM
**Expected Impact**: Helps role players specifically

**Challenge**: Data available ~30 min before tip
**Use case**: Distinguish starter vs bench designation

---

### Not Worth Pursuing (Diminishing Returns)

| Approach | Why Skip |
|----------|----------|
| Neural networks | High complexity, marginal expected gain |
| Player embeddings | Star-specific models already failed |
| More ensemble layers | Already optimal with 3 models |
| Position-specific models | Same issue as tier segmentation |
| Advanced hyperparameter tuning | 0.01 MAE max gain |

---

## Theoretical Limits

| Metric | Value |
|--------|-------|
| Current best | 3.40 MAE |
| Theoretical floor | ~3.0-3.2 MAE |
| Remaining gap | 0.2-0.4 points |

**Why the floor exists**:
- Player performance has inherent variance
- Load management (stars resting in blowouts)
- Game flow (blowouts reduce minutes for starters)
- Minor injuries not reported
- Day-to-day form fluctuations

---

## Maintenance Tasks

### Regular
- [ ] Retrain model monthly with new data
- [ ] Monitor train/test gap for drift
- [ ] Update Vegas feature extraction if source changes

### Seasonal
- [ ] Full retrain at season start
- [ ] Evaluate performance by player tier
- [ ] Check for new high-value features in data

---

## Success Metrics

### Model Quality
| Metric | Target | Current |
|--------|--------|---------|
| MAE | < 3.5 | 3.40 |
| vs Vegas | > 20% better | 25% better |
| Within 5 pts | > 75% | 76-78% |

### Betting Performance
| Metric | Target | Current |
|--------|--------|---------|
| O/U Accuracy | > 60% | 71.6% |
| High-confidence (>5pt edge) | > 85% | 91.5% |
| ROI | > 5% | TBD (needs live testing) |

---

## Summary

**The v8 model is production-ready.** Deploy now in shadow mode.

Further improvements are possible but face diminishing returns:
- Best opportunities: game-day injury status, game totals O/U
- Expected max additional gain: 0.1-0.2 MAE
- Theoretical floor: ~3.0-3.2 MAE

Focus energy on deployment and real-world validation rather than further optimization.
