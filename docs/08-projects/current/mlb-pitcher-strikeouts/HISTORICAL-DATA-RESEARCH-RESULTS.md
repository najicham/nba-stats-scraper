# Historical Betting Lines Research Results

**Date**: 2026-01-13
**Research Time**: 30 minutes
**Status**: COMPLETE - Verdict: No readily available sources

---

## Research Summary

Conducted comprehensive search for historical MLB pitcher strikeout prop betting data for 2024-2025 seasons.

### Sources Investigated

#### 1. OddsPortal
**URL**: [OddsPortal MLB](https://www.oddsportal.com/baseball/usa/mlb/)

**Finding**: ❌ Does NOT archive player props
- Focuses on game-level markets (moneyline, spread, totals)
- Historical data available for game lines only
- No pitcher strikeout props in archives

**Conclusion**: Not viable

---

#### 2. Kaggle Datasets
**Searches**:
- [Major League Baseball Dataset](https://www.kaggle.com/datasets/saurabhshahane/major-league-baseball-dataset)
- [Sports Betting Odds Analysis](https://www.kaggle.com/code/devraai/sports-betting-odds-analysis-prediction)

**Finding**: ❌ No pitcher props datasets for 2024-2025
- General MLB datasets exist (mostly 2021 and earlier)
- Betting datasets focus on game lines
- No player prop specific data found

**Conclusion**: Not viable

---

#### 3. GitHub Repositories
**Notable Repos**:
- [BerkeleyBets](https://github.com/zak-510/BerkeleyBets) - Predictive models, no historical archive
- [mlb-prop-bet-tracker](https://github.com/Daniel-Higgins/mlb-prop-bet-tracker) - Tracking tool, not data archive

**Finding**: ❌ No historical data repositories
- Projects exist for CURRENT props
- No comprehensive historical archives
- Focus is on prediction, not archival

**Conclusion**: Not viable

---

#### 4. Alternative Data Providers

**BigDataBall**: [MLB Data](https://www.bigdataball.com/datasets/mlb-data/)
- Game log spreadsheets with stats & odds
- **Check**: Game-level odds, not player props
- **Conclusion**: Not viable for player props

**OddsShark Database**: [MLB Database](https://www.oddsshark.com/mlb/database)
- Game dates, starting pitchers, scores, moneylines
- **Check**: No player props
- **Conclusion**: Not viable

**EV Analytics**: [MLB Stats](https://evanalytics.com/mlb/stats/strikeouts)
- Historical betting results for trends
- **Check**: Current props only, no historical archive access found
- **Conclusion**: Potential but not accessible

---

## Why Historical Player Props Don't Exist

### Storage Economics
- **Game lines**: ~15 games/day × 3 markets = 45 data points/day
- **Player props**: ~15 games × 40 players × 8 markets = 4,800 data points/day
- **Ratio**: 100x more data to store

### Business Model
- Most betting analysis focuses on game outcomes
- Player props are short-lived markets (hours, not days)
- Lower demand for historical player prop archives
- High storage cost vs low monetization potential

### Market Reality
- The Odds API doesn't archive player props (confirmed via testing)
- OddsPortal doesn't archive player props (confirmed via research)
- No free/open archives exist (confirmed via Kaggle/GitHub search)

---

## Commercial Options (Not Pursued)

### SportsDataIO / DonBest
**Potential**: HIGH - Professional odds data providers
**Access**: Contact sales for quote
**Cost**: Likely $500-5,000+ (enterprise pricing)
**Timeline**: 1-2 weeks for data delivery
**Recommendation**: Only if budget available AND coverage >70%

### Pinnacle Historical Data
**Potential**: MEDIUM - Pinnacle keeps extensive records
**Access**: Request academic/research access
**Cost**: Unknown (may provide free for research)
**Timeline**: 2-4 weeks for approval process
**Recommendation**: Worth email inquiry if time permits

---

## Verdict

**❌ No readily available historical pitcher prop data found**

### Coverage Assessment
- OddsPortal: 0%
- Kaggle/GitHub: 0%
- Free sources: 0%
- **Total coverage**: 0%

### Recommendation
**SKIP historical backfill, proceed with:**
1. ✅ Raw accuracy analysis (use actual strikeout results)
2. ✅ Synthetic hit rate (estimate what lines would have been)
3. ✅ Forward validation (collect betting lines from TODAY forward)

---

## Next Steps

### Immediate (This Week)
1. Execute raw accuracy analysis on 8,130 predictions
2. Calculate synthetic hit rates using available data
3. Generate comprehensive model performance report

### Forward (Starting Now)
4. Implement daily betting line collection
5. Fix prediction pipeline to enforce line dependency
6. Start building track record with real betting lines

---

## Sources

### Research Sources
- [OddsPortal MLB Results](https://www.oddsportal.com/baseball/usa/mlb/results/)
- [Kaggle Major League Baseball Dataset](https://www.kaggle.com/datasets/saurabhshahane/major-league-baseball-dataset)
- [BigDataBall MLB Data](https://www.bigdataball.com/datasets/mlb-data/)
- [GitHub BerkeleyBets](https://github.com/zak-510/BerkeleyBets)
- [EV Analytics MLB Strikeouts](https://evanalytics.com/mlb/stats/strikeouts)
- [OddsShark MLB Database](https://www.oddsshark.com/mlb/database)

---

**Research Completed**: 2026-01-13
**Time Invested**: 30 minutes
**Decision**: Proceed with proxy analysis + forward validation
