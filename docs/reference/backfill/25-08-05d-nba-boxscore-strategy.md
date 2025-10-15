# NBA Box Score Strategy

## Core Concept
The **box score is the central data structure** for both historical analysis and daily forecasting. We use different approaches to get box score data depending on whether we're looking backward or forward in time.

## Two Operational Modes

### Backfill Operations (Historical)
**Goal**: Extract historical box score data

**Process**:
- Scrape NBA Gamebook PDFs
- Extract player results (points scored, full stats)
- Extract game status (who played, who was DNP, injury reasons)

**Key Insight**: 
- ✅ **Box score contains everything we need**
- ✅ **No separate roster or injury scraping required**
- ✅ **One comprehensive data source**

### Daily Operations (Forecasting)
**Goal**: Forecast what the box score will look like

**Process**:
- Scrape injury reports (who's hurt today)
- Scrape daily rosters (who's available today)  
- Use historical patterns to forecast future box score
- Predict player performance (expected points)
- Predict player status (who will play/sit)

**Key Insight**:
- 🔮 **We're forecasting the box score**
- 🔮 **Use current conditions + historical data to predict outcomes**
- 🔮 **Multiple data sources needed for prediction**

## The Strategy

### Historical = Extract Box Score
```
NBA Gamebook PDF → Extract → Historical Box Score Data
```
*Everything we need is already in the completed box score*

### Daily = Forecast Box Score  
```
Injury Reports + Rosters + Historical Patterns → Predict → Future Box Score Data
```
*Use current conditions to predict what the box score will contain*

## Why This Works

- **Same data structure** for historical and predictive analysis
- **Efficient historical collection** - one source has everything
- **Comprehensive forecasting** - multiple inputs for better predictions
- **Perfect for prop betting** - historical context + future predictions

## Summary

**Backward Looking**: Box score already exists → extract it  
**Forward Looking**: Box score doesn't exist yet → forecast it

The box score is always the target - we just get there differently depending on timing.
